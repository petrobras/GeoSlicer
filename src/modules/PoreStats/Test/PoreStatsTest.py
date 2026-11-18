import os
import shutil

import pandas as pd
import tempfile
from pathlib import Path
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import wait
from commons.slicer.node_attributes import NodeEnvironment
from unittest.mock import patch

from .util_pore_stats import (
    SINGLE_WELL_DATASET_PATH,
    NO_PX_DATASET_PATH,
    MULTIWELL_DATASET_PATH,
    NO_IMAGE_DATASET_PATH,
    INVALID_IMAGE_NAME_DATASET_PATH,
    NON_EXISTENT_DATASET_PATH,
    TWO_TS_DATASET_PATH,
    MANY_SPURIOUS_DATASET_PATH,
    TEMPLATES,
    SHEETS_TEMPLATE_PATH,
    LAS_TEMPLATE_PATH,
    NO_SPURIOUS_TEMPLATE_PATH,
    CLEAN_RESIN_PX_TEMPLATE_PATH,
    CLEAN_RESIN_PX_SMART_REG_TEMPLATE_PATH,
    CLEAN_RESIN_DO_NOT_USE_PX_TEMPLATE_PATH,
    CLEAN_RESIN_NO_PX_TEMPLATE_PATH,
    SINGLE_FRAG_TEMPLATE_PATH,
    WATERSHED_TEMPLATE_PATH,
    test_and_delete_results,
    test_las_files_are_equal,
    test_message_box,
    test_netcdf,
    delete_dir_if_exists,
    sort_df,
)


from functools import partial


class PoreStatsTest(LTracePluginTest):
    def pre_setup(self):
        self.resultsDirPath = Path(tempfile.TemporaryDirectory().name)
        self.__envPatcher = patch("commons.slicer.helpers.getCurrentEnvironment", lambda: NodeEnvironment.THIN_SECTION)
        self.__envPatcher.start()

    def tear_down(self):
        if self.resultsDirPath.exists():
            shutil.rmtree(self.resultsDirPath)

        self.__envPatcher.stop()

    def test_models(self):
        def check_template(output_path):
            image_name = "ABC-123_3080.0m_2.5x_c1"

            results_subdirs = os.listdir(output_path)
            assert results_subdirs == ["netCDFs"]

            nc_subdirs = os.listdir(Path(output_path) / "netCDFs")
            assert nc_subdirs == [image_name + ".nc"]

            test_netcdf(image_name=image_name, template_results_path=template_path, output_path=output_path)

        for model_name in ["Bayesian small kernel", "Bayesian big kernel", "Carbonate (U-net)"]:
            model_name_for_path = (
                model_name.lower().replace("(", "").replace(")", "").replace(" ", "_").replace("-", "_")
            )
            output_path = (self.resultsDirPath / f"results_{model_name_for_path}").as_posix()
            template_path = TEMPLATES / (model_name_for_path + "_template")

            test_and_delete_results(
                self,
                input_path=SINGLE_WELL_DATASET_PATH,
                output_path=output_path,
                result_messages="Batch porosity analysis completed.",
                message_timeouts_sec=120,
                model_name=model_name,
                checks_callback=partial(check_template, output_path),
            )
            delete_dir_if_exists(output_path)

    def test_export_images(self):
        def check_image(output_path):
            image_name = "ABC-123_3080.0m_2.5x_c1"

            results_subdirs = os.listdir(output_path)
            assert len(results_subdirs) == 2 and all(subdir in results_subdirs for subdir in ["netCDFs", "pores"])

            pores_subdirs = os.listdir(Path(output_path) / "pores")
            assert pores_subdirs == [image_name]

            reports_files = os.listdir(Path(output_path) / "pores" / image_name)
            assert reports_files == [image_name + ".png"]

        output_path = (self.resultsDirPath / "results_images").as_posix()

        test_and_delete_results(
            self,
            input_path=SINGLE_WELL_DATASET_PATH,
            output_path=output_path,
            result_messages="Batch porosity analysis completed.",
            message_timeouts_sec=120,
            checks_callback=partial(check_image, output_path),
            export_images=True,
        )

    def test_export_sheets(self):
        def check_sheets(output_path):
            image_name = "ABC-123_3080.0m_2.5x_c1"

            results_subdirs = os.listdir(output_path)
            assert len(results_subdirs) == 2 and all(subdir in results_subdirs for subdir in ["netCDFs", "pores"])

            pores_subdirs = os.listdir(Path(output_path) / "pores")
            assert pores_subdirs == [image_name]

            reports_files = os.listdir(Path(output_path) / "pores" / image_name)
            assert len(reports_files) == 2 and all(
                file in reports_files
                for file in [f"AllStats_{image_name}_pores.xlsx", f"GroupsStats_{image_name}_pores.xlsx"]
            )

            all_stats_result = sort_df(
                pd.read_excel(Path(output_path) / "pores" / image_name / f"AllStats_{image_name}_pores.xlsx")
            )
            groups_stats_result = sort_df(
                pd.read_excel(Path(output_path) / "pores" / image_name / f"GroupsStats_{image_name}_pores.xlsx")
            )

            all_stats_template = sort_df(
                pd.read_excel(SHEETS_TEMPLATE_PATH / "pores" / image_name / f"AllStats_{image_name}_pores.xlsx")
            )
            groups_stats_template = sort_df(
                pd.read_excel(SHEETS_TEMPLATE_PATH / "pores" / image_name / f"GroupsStats_{image_name}_pores.xlsx")
            )

            pd.testing.assert_frame_equal(all_stats_template, all_stats_result)
            pd.testing.assert_frame_equal(groups_stats_template, groups_stats_result)

        output_path = (self.resultsDirPath / "results_sheets").as_posix()

        test_and_delete_results(
            self,
            input_path=SINGLE_WELL_DATASET_PATH,
            output_path=output_path,
            result_messages="Batch porosity analysis completed.",
            message_timeouts_sec=120,
            checks_callback=partial(check_sheets, output_path),
            export_sheets=True,
        )

    def test_export_las(self):
        def check_las(output_path):
            results_subdirs = os.listdir(output_path)
            assert len(results_subdirs) == 2 and all(subdir in results_subdirs for subdir in ["netCDFs", "pores"])

            pores_subdirs = os.listdir(Path(output_path) / "pores")
            assert pores_subdirs == ["LAS"]

            reports_files = os.listdir(Path(output_path) / "pores" / "LAS")
            assert len(reports_files) == 5 and all(
                f"las_{stat}.las" in reports_files for stat in ["max", "mean", "median", "min", "std"]
            )

            for stat in ["max", "mean", "median", "min", "std"]:
                result_las_path = Path(output_path) / "pores" / "LAS" / f"las_{stat}.las"
                template_las_path = LAS_TEMPLATE_PATH / "pores" / "LAS" / f"las_{stat}.las"

                test_las_files_are_equal(template_las_path, result_las_path)

        output_path = (self.resultsDirPath / "results_las").as_posix()

        test_and_delete_results(
            self,
            input_path=SINGLE_WELL_DATASET_PATH,
            output_path=output_path,
            result_messages="Batch porosity analysis completed.",
            message_timeouts_sec=120,
            checks_callback=partial(check_las, output_path),
            export_las=True,
        )

    def test_remove_spurious(self):
        def check_template(output_path):
            test_netcdf(
                image_name="ABC-123_3117.75m_2.5x_c1",
                template_results_path=NO_SPURIOUS_TEMPLATE_PATH,
                output_path=output_path,
            )

        output_path = (self.resultsDirPath / "results_no_spurious").as_posix()

        test_and_delete_results(
            self,
            input_path=MANY_SPURIOUS_DATASET_PATH,
            output_path=output_path,
            result_messages="Batch porosity analysis completed.",
            message_timeouts_sec=120,
            checks_callback=partial(check_template, output_path),
            remove_spurious=True,
            model_name="Carbonate (U-net)",
        )

    def test_clean_resin_px(self):
        output_path = (self.resultsDirPath / "results_clean_resin").as_posix()
        # ✓  Use PX; () Smart registration
        # ✓  Use PX; ✓  Smart registration
        # () Use PX
        for use_px, smart_reg in zip([True, True, False], [False, True, False]):
            test_and_delete_results(
                self,
                input_path=SINGLE_WELL_DATASET_PATH,
                output_path=output_path,
                result_messages="Batch porosity analysis completed.",
                message_timeouts_sec=120,
                checks_callback=partial(self.check_pp_px_templates, output_path, use_px, smart_reg),
                clean_resin=True,
                use_px=use_px,
                reg_method=smart_reg,
            )
            wait(0.4)
            delete_dir_if_exists(output_path)

    def test_clean_resin_pp(self):
        output_path = (self.resultsDirPath / "results_clean_resin").as_posix()
        ## Dataset with PP only
        # () Use PX
        test_and_delete_results(
            self,
            input_path=NO_PX_DATASET_PATH,
            output_path=output_path,
            result_messages="Batch porosity analysis completed.",
            message_timeouts_sec=120,
            checks_callback=partial(self.check_pp_template, output_path),
            clean_resin=True,
        )

    def test_clean_resin_no_px_and_pp(self):
        output_path = (self.resultsDirPath / "results_clean_resin").as_posix()
        # ✓  Use PX
        test_and_delete_results(
            self,
            input_path=NO_PX_DATASET_PATH,
            output_path=output_path,
            result_messages="FileNotFoundError: [Errno 2] No such file or directory:",
            message_timeouts_sec=30,
            clean_resin=True,
            use_px=True,
        )

    def test_limit_frags(self):
        def check_template(output_path):
            test_netcdf(
                image_name="ABC-123_3080.0m_2.5x_c1",
                template_results_path=SINGLE_FRAG_TEMPLATE_PATH,
                output_path=output_path,
            )

        output_path = (self.resultsDirPath / "results_1_frag").as_posix()

        test_and_delete_results(
            self,
            input_path=SINGLE_WELL_DATASET_PATH,
            output_path=output_path,
            result_messages="Batch porosity analysis completed.",
            message_timeouts_sec=120,
            checks_callback=partial(check_template, output_path),
            limit_frags=True,
        )

    def test_watershed(self):
        def check_template(output_path):
            test_netcdf(
                image_name="ABC-123_3080.0m_2.5x_c1",
                template_results_path=WATERSHED_TEMPLATE_PATH,
                output_path=output_path,
            )

        output_path = (self.resultsDirPath / "results_watershed").as_posix()

        test_and_delete_results(
            self,
            input_path=SINGLE_WELL_DATASET_PATH,
            output_path=output_path,
            result_messages="Batch porosity analysis completed.",
            message_timeouts_sec=120,
            partit_method="Over-Segmented Watershed",
            checks_callback=partial(check_template, output_path),
        )

    def test_input_data_from_different_wells(self):
        output_path = (self.resultsDirPath / "results_multiwell").as_posix()
        # wells order in message is not fixed.
        test_and_delete_results(
            self,
            input_path=MULTIWELL_DATASET_PATH,
            output_path=output_path,
            result_messages="ValueError: The input directory is expected to contain images from a single well. Got wells",
            message_timeouts_sec=15,
        )

    def test_empty_input_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(
                temp_dir
            ).as_posix()  # creating the empty directory in runtime as git ignores pre-created empty directories
            output_path = (self.resultsDirPath / "results_no_data").as_posix()
            test_and_delete_results(
                self,
                input_path=input_path,
                output_path=output_path,
                result_messages="Batch porosity analysis failed:\n\nFileNotFoundError: No valid images were found in the input directory.",
                message_timeouts_sec=10,
            )

    def test_no_valid_input_data(self):
        output_path = (self.resultsDirPath / "results_no_valid_data").as_posix()
        for input_path in [NO_IMAGE_DATASET_PATH, INVALID_IMAGE_NAME_DATASET_PATH]:
            test_and_delete_results(
                self,
                input_path=input_path,
                output_path=output_path,
                result_messages="Batch porosity analysis failed:\n\nFileNotFoundError: No valid images were found in the input directory.",
                message_timeouts_sec=10,
            )
            delete_dir_if_exists(output_path)

    def test_non_existent_input_dir(self):
        tempDir = tempfile.TemporaryDirectory().name

        test_message_box(
            self,
            input_path=NON_EXISTENT_DATASET_PATH,
            output_path=tempDir,
            result_messages="Input directory does not exist.",
        )

    def test_empty_output_dir(self):
        def create_empty_dir(output_path):
            os.makedirs(output_path, exist_ok=True)

        output_path = (self.resultsDirPath / "results_empty").as_posix()

        test_and_delete_results(
            self,
            input_path=SINGLE_WELL_DATASET_PATH,
            output_path=output_path,
            result_messages="Batch porosity analysis completed.",
            message_timeouts_sec=120,
            result_simul_callback=partial(create_empty_dir, output_path),
        )

    def test_non_empty_output_dir_dont_proceed(self):
        output_path = (self.resultsDirPath / "results_non_empty").as_posix()

        test_and_delete_results(
            self,
            input_path=SINGLE_WELL_DATASET_PATH,
            output_path=output_path,
            result_messages="The selected output directory is not empty. Proceed?",
            buttons_texts_to_click="&No",
            result_simul_callback=partial(self.create_non_empty_dir, output_path),
        )

    def test_non_empty_output_dir_proceed(self):
        output_path = (self.resultsDirPath / "results_non_empty").as_posix()
        test_and_delete_results(
            self,
            input_path=SINGLE_WELL_DATASET_PATH,
            output_path=output_path,
            result_messages=[
                "The selected output directory is not empty. Proceed?",
                "Batch porosity analysis completed.",
            ],
            message_timeouts_sec=[10, 120],
            buttons_texts_to_click=["&Yes", None],
            result_simul_callback=partial(self.create_non_empty_dir, output_path),
            should_apply=[True, False],
        )

    def test_cancel_unfinished_execution(self):
        output_path = (self.resultsDirPath / "results_initialized").as_posix()

        test_and_delete_results(
            self,
            input_path=TWO_TS_DATASET_PATH,
            output_path=output_path,
            result_messages="A previous unfinished execution was detected on the selected output directory. What do you want to do?",
            buttons_texts_to_click="Cancel",
            message_timeouts_sec=60,
            result_simul_callback=partial(self.create_initialized_dir, output_path),
        )

    def test_resume_unfinished_execution(self):
        output_path = (self.resultsDirPath / "results_initialized").as_posix()
        test_and_delete_results(
            self,
            input_path=TWO_TS_DATASET_PATH,
            output_path=output_path,
            result_messages=[
                "A previous unfinished execution was detected on the selected output directory. What do you want to do?",
                "Batch porosity analysis completed.",
            ],
            message_timeouts_sec=[10, 120],
            buttons_texts_to_click=["Resume", None],
            result_simul_callback=partial(self.create_initialized_dir, output_path),
            checks_callback=partial(self.check_resumed, output_path),
            should_apply=[True, False],
        )

    def test_restart_unfinished_execution(self):
        output_path = (self.resultsDirPath / "results_initialized").as_posix()
        test_and_delete_results(
            self,
            input_path=TWO_TS_DATASET_PATH,
            output_path=output_path,
            result_messages=[
                "A previous unfinished execution was detected on the selected output directory. What do you want to do?",
                "Batch porosity analysis completed.",
            ],
            # message_timeouts_sec=[120, 2],
            message_timeouts_sec=[10, 120],
            buttons_texts_to_click=["Restart", None],
            result_simul_callback=partial(self.create_initialized_dir, output_path),
            checks_callback=partial(self.check_restarted, output_path),
            should_apply=[True, False],
        )

    def test_export_sheets_multiimage(self):
        output_path = (self.resultsDirPath / "results_sheets_multiimage").as_posix()

        test_and_delete_results(
            self,
            input_path=TWO_TS_DATASET_PATH,
            output_path=output_path,
            result_messages="Batch porosity analysis completed.",
            message_timeouts_sec=120,
            export_sheets=True,
        )

    def create_non_empty_dir(self, output_path):
        os.makedirs(output_path, exist_ok=True)
        os.makedirs(Path(output_path) / "sample", exist_ok=True)

    def create_initialized_dir(self, output_path):
        os.makedirs(output_path, exist_ok=True)
        with open(Path(output_path) / "checkpoint.txt", "w") as checkpoint_file:
            checkpoint_file.write(str(TWO_TS_DATASET_PATH / "ABC-123_3100.0m_2.5x_c1.jpg"))

    def check_resumed(self, output_path):
        assert os.listdir(Path(output_path) / "netCDFs") == ["ABC-123_3100.0m_2.5x_c1.nc"]

    def check_restarted(self, output_path):
        ncs = os.listdir(Path(output_path) / "netCDFs")
        assert len(ncs) == 2 and all(nc in ncs for nc in ["ABC-123_3080.0m_2.5x_c1.nc", "ABC-123_3100.0m_2.5x_c1.nc"])

    def check_pp_px_templates(self, output_path, use_px, smart_reg) -> None:
        if use_px:
            if not smart_reg:
                test_netcdf(
                    image_name="ABC-123_3080.0m_2.5x_c1",
                    template_results_path=CLEAN_RESIN_PX_TEMPLATE_PATH,
                    output_path=output_path,
                )
            else:
                test_netcdf(
                    image_name="ABC-123_3080.0m_2.5x_c1",
                    template_results_path=CLEAN_RESIN_PX_SMART_REG_TEMPLATE_PATH,
                    output_path=output_path,
                )
        else:
            test_netcdf(
                image_name="ABC-123_3080.0m_2.5x_c1",
                template_results_path=CLEAN_RESIN_DO_NOT_USE_PX_TEMPLATE_PATH,
                output_path=output_path,
            )

    def check_pp_template(self, output_path) -> None:
        test_netcdf(
            image_name="ABC-123_3080.0m_2.5x_c1",
            template_results_path=CLEAN_RESIN_NO_PX_TEMPLATE_PATH,
            output_path=output_path,
        )
