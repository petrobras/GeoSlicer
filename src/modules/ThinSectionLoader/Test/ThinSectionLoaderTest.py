from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events, load_project, save_project, check_for_message_box, wait
from commons.slicer.helpers import tryGetNode, make_directory_writable
from pathlib import Path

# import time
import numpy as np
import tempfile
import time
import shutil
import slicer

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
JPG_EXAMPLE_FILE = TEST_RESOURCES_DIR / "example.JPG"
TIF_EXAMPLE_FILE = TEST_RESOURCES_DIR / "example.tif"
PNG_EXAMPLE_FILE = TEST_RESOURCES_DIR / "example.png"

CZI_PROJECT = TEST_RESOURCES_DIR / "czi" / "czi_images" / "czi_images.mrml"


class ThinSectionLoaderTest(LTracePluginTest):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def post_setup(self) -> None:
        """Test case setup handler, applied before reloding the widgets"""
        self.__widgets = dict()

        # Input tab
        inputFileSelector = self.find_widget(name="Input File Selector")
        self.__widgets["inputFileSelector"] = inputFileSelector
        self.__widgets["losslessCheckbox"] = self.find_widget(name="Lossless Checkbox")
        self.__widgets["loadButton"] = self.find_widget(name="Load Thin Section Button")
        self.__widgets["advancedCollapsibleButton"] = self.find_widget(name="Advanced Collapsible Button")
        self.__widgets["automaticImageSpacingCheckBox"] = self.find_widget(name="Automatic Detect Spacing CheckBox")
        self.__widgets["scaleSizePxLineEdit"] = self.find_widget(name="scaleSizePxLineEdit")
        self.__widgets["scaleSizeMmLineEdit"] = self.find_widget(name="scaleSizeMmLineEdit")
        self.__widgets["imageSpacing1LineEdit"] = self.find_widget(name="imageSpacing1LineEdit")
        self.__widgets["cziSection"] = self.find_widget(name="cziSection")
        self.__widgets["commonFormatSection"] = self.find_widget(name="commonFormatSection")

        for objectName, widget in self.__widgets.items():
            assert widget is not None, f"widget related to the objectName '{objectName}' is None!"

        # Update widgets default value
        inputFileSelector.settingKey = None  # Avoid data store/load from QSettings
        inputFileSelector.setCurrentPath("")  # Erase current data
        # Emit signal as the setter doesn't, to trigger events related to the path change.
        inputFileSelector.currentPathChanged.emit("")
        # Create temporary directory to save the tests files
        self.__temp_project_dir_path = Path(tempfile.mkdtemp())

    def tear_down(self) -> None:
        # Delete the temporary directory
        shutil.rmtree(self.__temp_project_dir_path, onexc=make_directory_writable)

    def _load_image(self, timeout_sec: int = 10, success=True) -> None:
        """Wrapper for load button click action and check if it was loaded until timeout."""
        load_button = self.__widgets["loadButton"]
        assert load_button is not None
        start_time = time.perf_counter()
        message_box_timeout_sec = 5 if success else timeout_sec

        try:
            with check_for_message_box(
                "Failed to detect scale in the selected image", timeout_sec=message_box_timeout_sec
            ):
                load_button.clicked.emit()
                process_events()

        except AttributeError as e:
            if success:
                pass  # Expected to not open message box in success case
            else:
                raise AttributeError(e)
        else:
            if success:
                raise RuntimeError("Expected not to fail scale detection.")
            else:
                pass  # Expected to not open message box in failure case

        while not self._module_widget.logic.loaded:
            now = time.perf_counter()
            if now - start_time >= timeout_sec:
                break
            wait(0.1)
        assert self._module_widget.logic.loaded, f"Failed to load image before the {timeout_sec}s timeout!"

    def test_interface_default(self) -> None:
        input_file_selector = self.__widgets["inputFileSelector"]
        lossless_checkbox = self.__widgets["losslessCheckbox"]
        czi_section = self.__widgets["cziSection"]
        common_format_section = self.__widgets["commonFormatSection"]
        assert input_file_selector.enabled, "Input file selector is not enabled."
        assert not input_file_selector.currentPath, (
            f"Current path is not empty. Actual value: {input_file_selector.currentPath}."
        )
        assert input_file_selector.isVisible(), (
            f"Expected the input file selector visibility to be True, but it is {lossless_checkbox.isVisible()}"
        )
        assert not czi_section.visible, "CZI section should be invisible by default"
        assert not common_format_section.visible, "Common formats section should be invisible by default"

    def test_import_jpg_image_lossless(self) -> None:
        input_file_selector = self.__widgets["inputFileSelector"]
        lossless_checkbox = self.__widgets["losslessCheckbox"]
        load_button = self.__widgets["loadButton"]
        # Update path in Input File Selector
        input_file_selector.setCurrentPath(JPG_EXAMPLE_FILE.as_posix())
        assert input_file_selector.currentPath == JPG_EXAMPLE_FILE.as_posix(), (
            f"Expected Input File Selector path as {JPG_EXAMPLE_FILE.as_posix()}, but is  {input_file_selector.currentPath}"
        )

        # Open advanced collapsable button
        self.__widgets["advancedCollapsibleButton"].collapsed = False

        # Assert interface changes after setting the path in Input File Selector
        assert lossless_checkbox.isVisible(), (
            f"Expected lossless checkbox visibility to be True, but it is {lossless_checkbox.isVisible()}"
        )
        assert not lossless_checkbox.isChecked()

        # Change configuration to create a 'lossless' image node
        lossless_checkbox.setChecked(True)
        assert lossless_checkbox.isChecked()

        # Load the test image
        with check_for_message_box("Failed to detect scale in the selected image", timeout_sec=15):
            load_button.click()
            process_events()

        # Check node created from the thin section image loading process
        node = tryGetNode(JPG_EXAMPLE_FILE.stem)
        assert node is not None, "Node was not generated from the loading process."
        lossless_attribute = node.GetAttribute("Lossless")
        assert lossless_attribute == "True", f"'Lossless' attribute is set as '{lossless_attribute}'. Expected True"

        # Create temporary directory to save the project
        temp_project_file = self.__temp_project_dir_path / "test" / "test.mrml"

        assert save_project(temp_project_file), "Failed to save temporary project."

        process_events()
        # Update node reference after save
        node = tryGetNode(node.GetID())

        # Assert node attributes
        storage_node = node.GetStorageNode()
        node_project_file_path = Path(storage_node.GetFileName())

        node_project_file_size = node_project_file_path.stat().st_size
        lossless_attribute = node.GetAttribute("Lossless")
        assert node_project_file_path.suffix == ".nrrd"
        assert storage_node.GetNumberOfFileNames() == 0, (
            f"Expected storage node to have 0 file name, but it has {storage_node.GetNumberOfFileNames()}"
        )
        assert lossless_attribute == "True", f"'Lossless' attribute is set as '{lossless_attribute}'. Expected True"
        uncompressed_bitmap_size = 5041 * 3429 * 3
        max_expected_size = uncompressed_bitmap_size + 10_000
        assert node_project_file_size <= max_expected_size, (
            f"Expected the node project file to be, at most, {max_expected_size} bytes. Actual size is {node_project_file_size} bytes"
        )

    def test_import_jpg_image_lossy(self) -> None:
        input_file_selector = self.__widgets["inputFileSelector"]
        lossless_checkbox = self.__widgets["losslessCheckbox"]
        load_button = self.__widgets["loadButton"]

        # Update path in Input File Selector
        input_file_selector.setCurrentPath(JPG_EXAMPLE_FILE.as_posix())
        assert input_file_selector.currentPath == JPG_EXAMPLE_FILE.as_posix(), (
            f"Expected Input File Selector path as {JPG_EXAMPLE_FILE.as_posix()}, but is  {input_file_selector.currentPath}"
        )

        # Open advanced collapsable button
        self.__widgets["advancedCollapsibleButton"].collapsed = False

        # Assert interface changes after setting the path in Input File Selector
        assert lossless_checkbox.isVisible(), (
            f"Expected lossless checkbox visibility to be True, but it is {lossless_checkbox.isVisible()}"
        )
        assert not lossless_checkbox.isChecked()

        # Maintain configuration to create a 'lossy' image node
        lossless_checkbox.setChecked(False)
        assert not lossless_checkbox.isChecked()

        # Load the test image
        with check_for_message_box("Failed to detect scale in the selected image", timeout_sec=15):
            load_button.click()
            process_events()

        # Check node created from the thin section image loading process
        node = tryGetNode(JPG_EXAMPLE_FILE.stem)
        assert node is not None, "Node was not generated from the loading process."

        lossless_attribute = node.GetAttribute("Lossless")
        assert lossless_attribute == "False", f"'Lossless' attribute is set as '{lossless_attribute}'. Expected False"
        assert node.GetAttribute("SourceImage") is None, "Expected the attribute to not exist before saving the node"

        # Create temporary directory to save the project
        temp_project_file = self.__temp_project_dir_path / "test" / "test.mrml"
        assert save_project(temp_project_file), "Failed to save temporary project."

        process_events()
        # Update node reference after save
        node = tryGetNode(node.GetID())

        # Assert node attributes
        storage_node = node.GetStorageNode()
        node_project_file_path = Path(storage_node.GetFileName())
        node_project_file_size = node_project_file_path.stat().st_size
        expected_image_project_file_path = temp_project_file.parent / "Data" / JPG_EXAMPLE_FILE.name
        expected_image_project_file_size = expected_image_project_file_path.stat().st_size
        lossless_attribute = node.GetAttribute("Lossless")
        source_image_attribute = node.GetAttribute("SourceImage")

        assert node_project_file_path.suffix == ".nrrd"
        assert storage_node.GetNumberOfFileNames() == 1, (
            f"Expected the storage node to have 1 files, but it has {storage_node.GetNumberOfFileNames()}"
        )
        assert lossless_attribute == "False", f"'Lossless' attribute is set as '{lossless_attribute}'. Expected False"
        assert expected_image_project_file_path.samefile(Path(source_image_attribute)), (
            f"'SourceImage' attribute is set as '{source_image_attribute}'. Expected to be related to {expected_image_project_file_path.as_posix()}"
        )
        assert node_project_file_size <= 10000, (
            f"Expected the node .nrrd file to be 10kB at most. Actual size is {node_project_file_size} bytes"
        )
        assert expected_image_project_file_size <= (JPG_EXAMPLE_FILE.stat().st_size) * 2.5, (
            f"Expected the project image file size to be 2 times greater than the original image file size at most. Actual size is {expected_image_project_file_size} bytes"
        )

    def test_import_tif_image_lossless_even_if_lossy_checkbox_checked(self) -> None:
        input_file_selector = self.__widgets["inputFileSelector"]
        lossless_checkbox = self.__widgets["losslessCheckbox"]
        load_button = self.__widgets["loadButton"]
        # Update path in Input File Selector
        input_file_selector.setCurrentPath(TIF_EXAMPLE_FILE.as_posix())
        assert input_file_selector.currentPath == TIF_EXAMPLE_FILE.as_posix(), (
            f"Expected Input File Selector path as {TIF_EXAMPLE_FILE.as_posix()}, but is {input_file_selector.currentPath}"
        )

        # Assert interface changes after setting the path in Input File Selector
        assert not self.__widgets["advancedCollapsibleButton"].visible
        assert not lossless_checkbox.isVisible(), (
            f"Expected lossless checkbox visibility to be False, but it is {lossless_checkbox.isVisible()}"
        )

        # Force lossy checkbox being unchecked
        lossless_checkbox.setChecked(False)

        # Load the test image
        with check_for_message_box("Failed to detect scale in the selected image", timeout_sec=15):
            load_button.click()
            process_events()

        # Check node created from the thin section image loading process
        node = tryGetNode(TIF_EXAMPLE_FILE.stem)
        assert node is not None, "Node was not generated from the loading process."
        lossless_attribute = node.GetAttribute("Lossless")
        assert lossless_attribute == "True", f"'Lossless' attribute is set as '{lossless_attribute}'. Expected True"

    def test_import_tif_image_with_dot_in_name(self) -> None:
        input_file_selector = self.__widgets["inputFileSelector"]
        load_button = self.__widgets["loadButton"]

        # Update path in Input File Selector
        input_file_selector.setCurrentPath((TEST_RESOURCES_DIR / "example.2.test.tif").as_posix())

        # Load the test image
        with check_for_message_box("Failed to detect scale in the selected image", timeout_sec=15):
            load_button.click()
            process_events()

        # Check node created from the thin section image loading process
        node = tryGetNode("example.2.test")
        assert node is not None, "Node was not generated from the loading process."

    def test_import_png_lossless_behavior(self) -> None:
        input_file_selector = self.__widgets["inputFileSelector"]
        lossless_checkbox = self.__widgets["losslessCheckbox"]
        load_button = self.__widgets["loadButton"]

        # Update path in Input File Selector
        input_file_selector.setCurrentPath(PNG_EXAMPLE_FILE.as_posix())
        assert input_file_selector.currentPath == PNG_EXAMPLE_FILE.as_posix(), (
            f"Expected Input File Selector path as {PNG_EXAMPLE_FILE.as_posix()}, but is  {input_file_selector.currentPath}"
        )

        # Open advanced collapsable button
        self.__widgets["advancedCollapsibleButton"].collapsed = False

        # Assert interface changes after setting the path in Input File Selector
        assert lossless_checkbox.isVisible(), (
            f"Expected lossless checkbox visibility to be True, but it is {lossless_checkbox.isVisible()}"
        )
        assert lossless_checkbox.isChecked()

        # Load the test image
        with check_for_message_box("Failed to detect scale in the selected image", timeout_sec=15):
            load_button.click()
            process_events()

        # Check node created from the thin section image loading process
        node = tryGetNode(PNG_EXAMPLE_FILE.stem)
        assert node is not None, "Node was not generated from the loading process."

        lossless_attribute = node.GetAttribute("Lossless")
        assert lossless_attribute == "True", f"'Lossless' attribute is set as '{lossless_attribute}'. Expected True"

        # Create temporary directory to save the project
        temp_project_file = self.__temp_project_dir_path / "test" / "test.mrml"
        assert save_project(temp_project_file), "Failed to save temporary project."

        process_events()
        # Update node reference after save
        node = tryGetNode(node.GetID())

        # Assert node attributes
        storage_node = node.GetStorageNode()
        node_project_file_path = Path(storage_node.GetFileName())
        lossless_attribute = node.GetAttribute("Lossless")
        source_image_attribute = node.GetAttribute("SourceImage")
        array = slicer.util.arrayFromVolume(node)

        assert node_project_file_path.suffix == ".nrrd"
        assert storage_node.GetNumberOfFileNames() == 0, (
            f"Expected storage node to have 0 file name, but it has {storage_node.GetNumberOfFileNames()}"
        )
        assert lossless_attribute == "True", f"'Lossless' attribute is set as '{lossless_attribute}'. Expected True"
        assert source_image_attribute is None
        assert array.shape[3] == 3, "Expected a 2D RGB array equivalent shape (1, x, y, 3)."

    def test_automatic_scale_detection(
        self,
    ):
        tests = [
            ["cm_PP.png", 652, 1.0],
            ["cm_PX.png", 652, 1.0],
            ["mm.png", 186, 2.0],
            ["um.jpg", None, 2.0],
            ["um_PP.png", 756, 1.0],
            ["um_PX.png", 756, 1.0],
        ]

        for test in tests:
            image, expected_px_size, expected_mm_size = test

            input_file_selector = self.__widgets["inputFileSelector"]
            load_button = self.__widgets["loadButton"]
            automatic_image_spacing_checkbox = self.__widgets["automaticImageSpacingCheckBox"]
            px_size_line_edit = self.__widgets["scaleSizePxLineEdit"]
            mm_size_line_edit = self.__widgets["scaleSizeMmLineEdit"]

            # Assert widget existance
            assert input_file_selector is not None
            assert automatic_image_spacing_checkbox is not None
            assert load_button is not None

            # Add image path
            image_file = (TEST_RESOURCES_DIR / Path(image)).as_posix()
            input_file_selector.setCurrentPath(image_file)
            assert input_file_selector.currentPath == image_file, (
                f"Expected input file to be {image_file}, but it is {input_file_selector.currentPath}."
            )

            # Check the automatic spacing
            automatic_image_spacing_checkbox.setChecked(True)
            assert automatic_image_spacing_checkbox.isChecked()

            # Load
            self._load_image(timeout_sec=30)

            assert px_size_line_edit.text, f"Failed to detect scale px size for {image_file}"
            assert mm_size_line_edit.text, f"Failed to detect scale mm size for {image_file}"

            px_size_value = int(np.ceil(float(px_size_line_edit.text)))
            mm_size_value = float(mm_size_line_edit.text)

            if expected_px_size:
                assert expected_px_size == px_size_value, (
                    f"Expected px size to be {expected_px_size} for image {image}, but it is {px_size_value}."
                )

            assert expected_mm_size == mm_size_value, (
                f"Expected mm size to be {expected_mm_size} for image {image}, but it is {mm_size_value}."
            )

    def test_scale_size_ruler_button_click_finish_callback(self) -> None:
        """Regression test: finishing the scale line pick used to raise
        "AttributeError: QWidget has no attribute named 'marku'" because the
        picking finish callback referenced a misspelled `self.marku` instead
        of `self.markup` while cleaning up the markup.
        """
        input_file_selector = self.__widgets["inputFileSelector"]
        load_button = self.__widgets["loadButton"]

        input_file_selector.setCurrentPath(JPG_EXAMPLE_FILE.as_posix())
        with check_for_message_box("Failed to detect scale in the selected image", timeout_sec=15):
            load_button.click()
            process_events()

        volume_node = tryGetNode(JPG_EXAMPLE_FILE.stem)
        assert volume_node is not None, "Node was not generated from the loading process."

        pixel_size_editor = self._module_widget.commonFormatWidget.pixelSizeEditor
        pixel_size_editor.currentNode = volume_node

        # Simulate the user clicking the ruler button, starting the scale line picking.
        pixel_size_editor.scaleSizePxRuler.click()
        process_events()
        assert pixel_size_editor.markup is not None, "Expected the scale line picking to have started."

        markup = pixel_size_editor.markup
        markup.markups_node.AddControlPoint(0.0, 0.0, 0.0)
        markup.markups_node.AddControlPoint(10.0, 0.0, 0.0)
        markup.markups_node.SetNthControlPointAssociatedNodeID(0, volume_node.GetID())
        markup.markups_node.SetNthControlPointAssociatedNodeID(1, volume_node.GetID())

        # Simulate finishing the pick with 2 points selected, the same call made internally
        # once the finish criterion (2 selected points) is met.
        try:
            markup.finish_callback(markup, 1)
        except AttributeError as error:
            self.fail(f"finish_callback raised an unexpected AttributeError: {error}")
        finally:
            markup.stop_picking()

        process_events()

        assert pixel_size_editor.scaleSizePxLineEdit.text, "Expected scale size (px) field to be populated."
        assert markup.finish_callback is None, (
            "Expected markup's finish_callback to be cleared after finishing the pick."
        )
        assert markup.finish_criterion is None, (
            "Expected markup's finish_criterion to be cleared after finishing the pick."
        )

    def test_scale_size_ruler_button_click_twice_does_not_break_second_pick(self) -> None:
        """Regression test: starting a second scale-line pick (clicking the ruler button
        again, after a first pick already finished) used to get stuck waiting for more
        points instead of finishing after 2 points.
        """
        input_file_selector = self.__widgets["inputFileSelector"]
        load_button = self.__widgets["loadButton"]

        input_file_selector.setCurrentPath(JPG_EXAMPLE_FILE.as_posix())
        with check_for_message_box("Failed to detect scale in the selected image", timeout_sec=15):
            load_button.click()
            process_events()

        volume_node = tryGetNode(JPG_EXAMPLE_FILE.stem)
        assert volume_node is not None, "Node was not generated from the loading process."

        pixel_size_editor = self._module_widget.commonFormatWidget.pixelSizeEditor
        pixel_size_editor.currentNode = volume_node
        selection_node = slicer.mrmlScene.GetNodeByID("vtkMRMLSelectionNodeSingleton")

        # First use
        pixel_size_editor.scaleSizePxRuler.click()
        first_markup = pixel_size_editor.markup
        assert first_markup is not None, "Expected the first scale line picking to have started."
        first_markup.markups_node.AddControlPoint(0.0, 0.0, 0.0)
        first_markup.markups_node.AddControlPoint(10.0, 0.0, 0.0)
        first_markup.markups_node.SetNthControlPointAssociatedNodeID(0, volume_node.GetID())
        first_markup.markups_node.SetNthControlPointAssociatedNodeID(1, volume_node.GetID())
        first_markup.finish_callback(first_markup, 1)
        assert pixel_size_editor.markup is None, "Expected the first pick to finish and clear the markup."

        # Second use
        pixel_size_editor.scaleSizePxRuler.click()
        second_markup = pixel_size_editor.markup
        assert second_markup is not None, "Expected the second scale line picking to have started."
        assert second_markup is not first_markup
        second_markup.markups_node.AddControlPoint(0.0, 0.0, 0.0)
        second_markup.markups_node.SetNthControlPointAssociatedNodeID(0, volume_node.GetID())

        # Force the first (already-finished) markup's deferred cleanup to run now, in the
        # middle of the second pick to check if it won't remove all Markup nodes tagged as 'Markup'
        #  using the remove temporary node wrapper
        first_markup.__del__()

        assert slicer.mrmlScene.GetNodeByID(second_markup.markups_node.GetID()) is not None, (
            "The second pick's markups node must survive the first pick's deferred cleanup."
        )
        assert selection_node.GetActivePlaceNodeID() == second_markup.markups_node.GetID(), (
            "The second pick's active place node reference must not be cleared by the first pick's deferred cleanup."
        )

        # Finish the second pick
        second_markup.markups_node.AddControlPoint(10.0, 0.0, 0.0)
        second_markup.markups_node.SetNthControlPointAssociatedNodeID(1, volume_node.GetID())
        assert second_markup.get_number_of_selected_points() >= 2, (
            "Expected 2 points to be selected for the second pick."
        )
        second_markup.finish_callback(second_markup, 1)

        assert pixel_size_editor.markup is None, "Expected the second pick to finish and clear the markup."
        assert pixel_size_editor.scaleSizePxLineEdit.text, "Expected scale size (px) field to be populated."

    def _test_czi_file(self, filename: str, expected_nodes_info: list, resolution_index: int = None):
        load_project(CZI_PROJECT)

        # Collect reference node names before importing (they come from the scene)
        reference_nodes = {info["name"]: tryGetNode(info["name"]) for info in expected_nodes_info}
        for node_name, ref_node in reference_nodes.items():
            self.assertIsNotNone(
                ref_node,
                f"Reference node '{node_name}' not found in the loaded scene. Make sure it was saved to {CZI_PROJECT}.",
            )

        # Import the CZI via the module UI
        czi_file = TEST_RESOURCES_DIR / "czi" / filename
        self.assertTrue(czi_file.exists(), f"Test file {filename} not found in {TEST_RESOURCES_DIR}")

        input_file_selector = self.__widgets["inputFileSelector"]
        input_file_selector.setCurrentPath(czi_file.as_posix())
        slicer.app.processEvents()

        if resolution_index is not None:
            czi_section = self.__widgets["cziSection"]
            resolution_combobox = czi_section.findChild("QComboBox")
            resolution_combobox.setCurrentIndex(resolution_index)
            slicer.app.processEvents()

        czi_load_button = input_file_selector.window().findChild("QPushButton", "Load CZI Image Button")
        if czi_load_button:
            czi_load_button.click()
            slicer.app.processEvents()
        else:
            raise RuntimeError("Load CZI Image Button not found in the UI")

        # Verify each loaded node against its reference
        for info in expected_nodes_info:
            node_name = info["name"]

            loaded_node = slicer.mrmlScene.GetFirstNodeByName(f"{node_name}_1")
            self.assertIsNotNone(
                loaded_node,
                f"Loaded node matching '{node_name}' not found after import.",
            )

            ref_node = reference_nodes[node_name]

            # Sanity checks: shape, dtype, spacing
            array = slicer.util.arrayFromVolume(loaded_node)
            self.assertIsNotNone(array, f"Could not extract array from loaded node '{node_name}'")

            self.assertEqual(
                array.shape,
                info["shape"],
                f"Shape mismatch for '{node_name}'",
            )
            self.assertEqual(
                array.dtype,
                info["dtype"],
                f"Dtype mismatch for '{node_name}'",
            )

            spacing = loaded_node.GetSpacing()
            np.testing.assert_almost_equal(
                spacing,
                info["spacing"],
                decimal=5,
                err_msg=f"Spacing mismatch for '{node_name}'",
            )

            # Primary check: voxel data must match the reference node
            ref_array = slicer.util.arrayFromVolume(ref_node)
            self.assertIsNotNone(ref_array, f"Could not extract array from reference node '{node_name}'")

            np.testing.assert_array_equal(
                array,
                ref_array,
                err_msg=f"Pixel data mismatch between loaded and reference node for '{node_name}'",
            )

    def test_import_czi_different_resolutions(self):
        """Test loading a CZI file with multiple resolutions (pyramid)."""
        filename = "test_pyramid.czi"

        # Test loading at a lower resolution
        self._test_czi_file(
            filename,
            [
                {
                    "name": "test_pyramid",
                    "shape": (1, 1000, 1250),
                    "spacing": (0.004, 0.004, 0.001),
                    "dtype": np.uint8,
                }
            ],
            resolution_index=2,
        )

    def test_import_czi_2d_1ch(self):
        self._test_czi_file(
            "test_2d_1ch.czi",
            [
                {
                    "name": "test_2d_1ch",
                    "shape": (1, 100, 100),
                    "spacing": (0.001, 0.001, 0.001),
                    "dtype": np.uint8,
                }
            ],
        )

    def test_import_czi_3d_1ch_uniform(self):
        self._test_czi_file(
            "test_3d_1ch_uniform.czi",
            [
                {
                    "name": "test_3d_1ch_uniform",
                    "shape": (5, 100, 100),
                    "spacing": (0.0005, 0.0005, 0.002),
                    "dtype": np.uint8,
                }
            ],
        )

    def test_import_czi_3d_1ch_varying(self):
        self._test_czi_file(
            "test_3d_1ch_varying.czi",
            [
                {
                    "name": "test_3d_1ch_varying",
                    "shape": (3, 100, 100),
                    "spacing": (0.00035, 0.00035, 0.00035),
                    "dtype": np.uint8,
                }
            ],
        )

    def test_import_czi_2d_timeseries(self):
        self._test_czi_file(
            "test_2d_timeseries.czi",
            [
                {
                    "name": "test_2d_timeseries",
                    "shape": (1, 100, 100),
                    "spacing": (0.001, 0.001, 0.001),
                    "dtype": np.uint8,
                }
            ],
        )

    def test_import_czi_2d_3ch(self):
        # Channels have explicit names: "Gradient", "Circle", "Noise"
        self._test_czi_file(
            "test_2d_3ch.czi",
            [
                {
                    "name": f"test_2d_3ch_{ch}",
                    "shape": (1, 100, 100),
                    "spacing": (0.0001, 0.0001, 0.0001),
                    "dtype": np.uint8,
                }
                for ch in ("Gradient", "Circle", "Noise")
            ],
        )

    def test_import_czi_2d_6ch(self):
        # Channels have explicit names: "Ch1" … "Ch6"
        self._test_czi_file(
            "test_2d_6ch.czi",
            [
                {
                    "name": f"test_2d_6ch_Ch{i + 1}",
                    "shape": (1, 100, 100),
                    "spacing": (0.001, 0.001, 0.001),
                    "dtype": np.uint8,
                }
                for i in range(6)
            ],
        )

    def test_import_czi_3d_timeseries_4d(self):
        self._test_czi_file(
            "test_3d_timeseries.czi",
            [
                {
                    "name": "test_3d_timeseries",
                    "shape": (3, 64, 64),
                    "spacing": (0.001, 0.001, 0.005),
                    "dtype": np.uint8,
                }
            ],
        )

    def test_import_czi_5d_lowres(self):
        # Channels have explicit names: "Red", "Green", "Blue"
        self._test_czi_file(
            "test_5d_lowres.czi",
            [
                {
                    "name": f"test_5d_lowres_{ch}",
                    "shape": (10, 10, 10),
                    "spacing": (0.01, 0.01, 0.01),
                    "dtype": np.uint8,
                }
                for ch in ("Red", "Green", "Blue")
            ],
        )

    def test_import_czi_mosaic_scenes(self):
        """Mosaic CZI with multiple scenes — each scene becomes a separate node."""
        self._test_czi_file(
            "test_mosaic_scenes.czi",
            [
                {
                    "name": "test_mosaic_scenes_S0",
                    "scene_idx": 0,
                    "shape": (1, 100, 100),
                    "spacing": (0.001, 0.001, 0.001),
                    "dtype": np.uint8,
                },
                {
                    "name": "test_mosaic_scenes_S1",
                    "scene_idx": 1,
                    "shape": (1, 100, 100),
                    "spacing": (0.001, 0.001, 0.001),
                    "dtype": np.uint8,
                },
            ],
        )

    def test_import_czi_float_data(self):
        self._test_czi_file(
            "test_float32.czi",
            [
                {
                    "name": "test_float32",
                    "shape": (1, 100, 100),
                    "spacing": (0.001, 0.001, 0.001),
                    "dtype": np.float32,
                }
            ],
        )

    def test_import_czi_rgb_pixel_type(self):
        self._test_czi_file(
            "test_bgr_pixeltype.czi",
            [
                {
                    "name": "test_bgr_pixeltype",
                    "shape": (1, 100, 100, 3),
                    "spacing": (0.001, 0.001, 0.001),
                    "dtype": np.uint8,
                }
            ],
        )

    def test_import_czi_compressed(self):
        self._test_czi_file(
            "test_compressed.czi",
            [
                {
                    "name": "test_compressed",
                    "shape": (1, 200, 200),
                    "spacing": (0.001, 0.001, 0.001),
                    "dtype": np.uint8,
                }
            ],
        )

    def test_import_czi_2d_3ch_vector(self):
        self._test_czi_file(
            "test_2d_3ch_vector.czi",
            [
                {
                    "name": "test_2d_3ch_vector",
                    "shape": (1, 100, 100, 3),
                    "spacing": (0.001, 0.001, 0.001),
                    "dtype": np.uint8,
                }
            ],
        )

    def test_import_czi_2d_6ch_vector(self):
        self._test_czi_file(
            "test_2d_6ch_vector.czi",
            [
                {
                    "name": f"test_2d_6ch_vector_S{i}",
                    "scene_idx": i,
                    "shape": (1, 100, 100, 3),
                    "spacing": (0.001, 0.001, 0.001),
                    "dtype": np.uint8,
                }
                for i in range(2)
            ],
        )
