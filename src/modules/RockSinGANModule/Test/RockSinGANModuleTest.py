from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from pathlib import Path
from commons.slicer.tests.utils import load_project, process_events, wait_cli_to_finish
from commons.slicer.helpers import tryGetNode
from time import sleep
import qt
import slicer

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
MULTISCALE_SINGAN_PROJECT_FILE = TEST_RESOURCES_DIR / "SINGAN" / "SINGAN.mrml"


class RockSinGANModuleTest(LTracePluginTest):
    def pre_setup(self):
        self._no_model_timer = qt.QTimer()
        self._no_model_timer.setInterval(500)

        def _dismiss_no_model_dialog():
            mw = slicer.modules.AppContextInstance.mainWindow
            for msg_box in mw.findChildren(qt.QMessageBox):
                if msg_box.visible and msg_box.windowTitle == "No model found":
                    msg_box.reject()
                    self._no_model_timer.stop()
                    return

        self._no_model_timer.timeout.connect(_dismiss_no_model_dialog)
        self._no_model_timer.start()

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._no_model_timer.stop()
        self._no_model_timer.deleteLater()
        self._no_model_timer = None

        model_selector = self.find_widget("Model Selector")
        assert model_selector.currentData is not None, (
            "No SinGAN model found. Please download and load the required model package."
        )

        self._widgets = {
            "apply_button": self.find_widget("Apply Button"),
            "output_prefix_line_edit": self.find_widget("outputPrefix"),
            "model_selector": model_selector,
            "generate_ti_push_button": self.find_widget("Generate TI Push Button"),
            "hard_data_widget": self.find_widget("Hard Data Widget"),
            "scale_check_box": self.find_widget("Scale CheckBox"),
            "hd_scale_spin_box": self.find_widget("HD Scale Spin Box"),
            "preview_hd_scales_button": self.find_widget("Preview HD Scales Button"),
            "imagelog_widget": self.find_widget("Imagelog Widget"),
            "imagelog_preview_button": self.find_widget("Imagelog Preview Button"),
            "calculate_parameters_button": self.find_widget("Calculate Parameters Button"),
            "crop_method_combo_box": self.find_widget("Crop Method Combo Box"),
            "chunk_0": self.find_widget("chunk_0"),
            "chunk_1": self.find_widget("chunk_1"),
            "chunk_2": self.find_widget("chunk_2"),
            "base_volume_spin_box": self.find_widget("Base Volume Spin Box"),
            "split_scale_spin_box": self.find_widget("Split Scale Spin Box"),
            "crop_scale_spin_box": self.find_widget("Crop Scale Spin Box"),
            "disk_scale_spin_box": self.find_widget("Disk Scale Spin Box"),
            "seed_spin_box": self.find_widget("Seed Spin Box"),
            "realizations_spin_box": self.find_widget("realizationsSpinBox"),
            "save_as_volume_check_box": self.find_widget("saveAsVolume"),
            "save_as_sequence_check_box": self.find_widget("saveAsSequence"),
            "save_as_big_image_check_box": self.find_widget("saveAsBigImage"),
            "save_as_file_check_box": self.find_widget("saveAsFile"),
            "file_directory_button": self.find_widget("fileDirectory"),
            "partitions_spin_box": self.find_widget("partitionsSpinBox"),
            "cancel_button": self.find_widget("cancelButton"),
        }

    def tear_down(self):
        pass

    def test_small(self):
        load_project(project_file_path=MULTISCALE_SINGAN_PROJECT_FILE)
        model_selector = self._widgets["model_selector"]
        assert model_selector.currentText == "2025_01_30_14_10_54_microct_500x_17s"

        trainingImageNode = tryGetNode("40x40x40_singan_cropped23x23x23")
        assert trainingImageNode is not None
        hard_data_widget = self._widgets["hard_data_widget"]
        hard_data_widget.mainInput.setCurrentNode(trainingImageNode)
        hard_data_widget.selectSegments([0, 2])

        apply_button = self._widgets["apply_button"]
        assert not apply_button.enabled

        crop_method_combo = self._widgets["crop_method_combo_box"]
        assert crop_method_combo.currentText == "Calculate parameters first"

        calc_params_btn = self._widgets["calculate_parameters_button"]
        assert calc_params_btn.enabled
        calc_params_btn.clicked()

        prefix = self._widgets["output_prefix_line_edit"]
        assert prefix.text == "40x40x40_singan_cropped23x23x23_rocksingan"

        process_events()
        sleep(0.1)
        assert apply_button.enabled
        apply_button.clicked()

        process_events()

        cliNode = self._module_widget.logic.cliNode
        assert cliNode is not None

        wait_cli_to_finish(cliNode, timeout_sec=3600)

        assert cliNode.GetStatusString() == "Completed"

        lastRealizationNode = tryGetNode(prefix.text)
        assert lastRealizationNode is not None

    def test_default_interface_configuration(self):
        apply_button = self._widgets["apply_button"]
        output_prefix_line_edit = self._widgets["output_prefix_line_edit"]
        assert not apply_button.enabled
        assert output_prefix_line_edit is not None
        assert output_prefix_line_edit.enabled
        assert output_prefix_line_edit.text == ""
