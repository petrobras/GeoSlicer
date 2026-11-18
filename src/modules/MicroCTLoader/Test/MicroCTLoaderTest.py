from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events, wait
from commons.slicer.helpers import tryGetNode, get_subject_hierarchy_siblings, getVolumeNullValue
from pathlib import Path
from commons.slicer.micro_ct.AmLoader import AmLoaderLogic
from unittest.mock import patch

import tempfile
import slicer
import qt
import numpy as np
import shutil
import os

RESOURCES = Path(__file__).parent / "Resources"
TEST_RESOURCES_DIR_2D = Path(__file__).parent / "Resources" / "2D"
TEST_RESOURCES_DIR_3D = Path(__file__).parent / "Resources" / "3D"
EXAMPLE_FILE_TIF2D = TEST_RESOURCES_DIR_2D / "example_00.tif"
EXAMPLE_FILE_TIF3D = TEST_RESOURCES_DIR_3D / "A_B_C_D_CT_00.tif"

# RAW
BIN_PATH = RESOURCES / "THIS_IS_A_TEST_BIN_30_20_10_99900nm.raw"
BIN_FLOAT_PATH = RESOURCES / "WEIRD_FLOAT_SEGMENTATION_TEST_BIN_30_20_10_99900nm.raw"
BASINS_PATH = RESOURCES / "THIS_IS_A_TEST_BASINS_30_20_10_99900nm.raw"
LABELS_PATH = RESOURCES / "THIS_IS_A_TEST_LABELS_30_20_10_99900nm.raw"
CUPS_PATH = RESOURCES / "SEP9D_520700_SAT_AL_CT_0400_0375_0272_153600nm.raw"
EXPECTED_SPACING = (0.0999,) * 3

TESCAN_ROOT = RESOURCES / "tescan"

# AmiraMesh .am
AM_FILE = RESOURCES / "test_volume_4x3x2_1um.am"
AM_VOLUME_NAME = AM_FILE.stem
AM_FILE_SHIFTED_Z = RESOURCES / "test_volume_4x3x2_1um_shifted_z.am"
AM_VOLUME_NAME_SHIFTED_Z = AM_FILE_SHIFTED_Z.stem


class MicroCTLoaderTest(LTracePluginTest):
    GLOBAL_TIMEOUT_MS = 15000

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def pre_setup(self) -> None:
        self.__dialogDirectoryValue = slicer.app.settings().value("MicroCTLoader/dialogDirectory")
        slicer.app.settings().remove("MicroCTLoader/dialogDirectory")

    def tear_down(self):
        slicer.app.settings().setValue("MicroCTLoader/dialogDirectory", self.__dialogDirectoryValue)

    def post_setup(self) -> None:
        """Test case setup handler, applied before reloding the widgets"""
        self.DirOrFileWidget = self._module_widget.pathWidget
        self.__widgets = dict()

        # Input tab
        self.__widgets["DirOrFileWidget"] = self.DirOrFileWidget
        self.__widgets["chooseDirButton"] = self.find_widget(name="Choose folder…", obj=self.DirOrFileWidget)
        self.__widgets["chooseFileButton"] = self.find_widget(name="Choose file…", obj=self.DirOrFileWidget)
        self.__widgets["pathLineEdit"] = self.find_widget(name="Path Line", obj=self.DirOrFileWidget)
        self.__widgets["imageSpacing1"] = self.find_widget(name="Image Spacing 1")
        self.__widgets["imageSpacing2"] = self.find_widget(name="Image Spacing 2")
        self.__widgets["imageSpacing3"] = self.find_widget(name="Image Spacing 3")
        self.__widgets["centerVolume"] = self.find_widget(name="Center volume")
        self.__widgets["loadAsLabelmap"] = self.find_widget(name="Load as Labelmap")
        self.__widgets["loadAsSequence"] = self.find_widget(name="Load volumes as sequence")
        self.__widgets["invertWidth"] = self.find_widget(name="invertWidth")
        self.__widgets["invertLength"] = self.find_widget(name="invertLength")
        self.__widgets["invertHeight"] = self.find_widget(name="invertHeight")
        self.__widgets["loadMicroCTs"] = self.find_widget(name="Load micro CTs")

        for objectName, widget in self.__widgets.items():
            assert widget is not None, f"widget related to the objectName '{objectName}' is None!"

        # Use different setting keys to avoid conflicts with the user's settings
        settingKey = "Test/MicroCTLoader/dialogDirectory"
        slicer.app.settings().remove(settingKey)
        self.DirOrFileWidget.settingKey = settingKey
        self.DirOrFileWidget.path = ""

        self._module_widget.cropCylinderCheckBox.setChecked(False)

    def test_interface_default(self) -> None:
        DirOrFile_Widget = self.__widgets["DirOrFileWidget"]

        centerVolume_checkbox = self.__widgets["centerVolume"]
        loadAsLabelmapCheckbox = self.__widgets["loadAsLabelmap"]
        loadAsSequenceCheckbox = self.__widgets["loadAsSequence"]
        load_button = self.__widgets["loadMicroCTs"]
        invertWidthCheckBox = self.__widgets["invertWidth"]
        invertLengthCheckBox = self.__widgets["invertLength"]
        invertHeightCheckBox = self.__widgets["invertHeight"]

        assert DirOrFile_Widget.enabled, "Input file selector is not enabled."
        assert DirOrFile_Widget.isVisible(), (
            f"Expected the input file selector visibility to be True, but it is {centerVolume_checkbox.isVisible()}"
        )
        assert centerVolume_checkbox.isVisible() is False, (
            f"Expected the centerVolume checkbox visibility to be False, but it is {centerVolume_checkbox.isVisible()}"
        )
        assert loadAsLabelmapCheckbox.isVisible() is False, (
            f"Expected the centerVolume checkbox visibility to be False, but it is {loadAsLabelmapCheckbox.isVisible()}"
        )
        assert loadAsLabelmapCheckbox.isChecked() is False, (
            f"Expected to be False, but is {loadAsLabelmapCheckbox.isChecked()}"
        )
        assert loadAsSequenceCheckbox.isChecked() is False, (
            f"Expected to be False, but is {loadAsSequenceCheckbox.isChecked()}"
        )
        assert invertWidthCheckBox.isVisible() is False, (
            f"Expected the invertWidthC checkbox visibility to be False, but it is {invertWidthCheckBox.isVisible()}"
        )
        assert invertWidthCheckBox.isChecked(), f"Expected to be True, but is {invertWidthCheckBox.isChecked()}"
        assert invertLengthCheckBox.isVisible() is False, (
            f"Expected the invertLength checkbox visibility to be False, but it is {invertLengthCheckBox.isVisible()}"
        )
        assert invertLengthCheckBox.isChecked(), f"Expected to be True, but is {invertLengthCheckBox.isChecked()}"
        assert invertHeightCheckBox.isVisible() is False, (
            f"Expected the invertHeight checkbox visibility to be False, but it is {invertHeightCheckBox.isVisible()}"
        )
        assert invertHeightCheckBox.isChecked() is False, (
            f"Expected to be False, but is {invertHeightCheckBox.isChecked()}"
        )

        assert not load_button.enabled, (
            f"Expected the load MicroCT Button visibility to be False, but it is {load_button.enabled}"
        )

    def test_import_folder_of_slices(self):
        load_button = self.__widgets["loadMicroCTs"]
        imageSpacing1 = self.__widgets["imageSpacing1"]
        imageSpacing2 = self.__widgets["imageSpacing2"]
        imageSpacing3 = self.__widgets["imageSpacing3"]
        invertWidthCheckBox = self.__widgets["invertWidth"]
        invertLengthCheckBox = self.__widgets["invertLength"]

        # Update path in widget 2D
        self._module_widget.pathWidget.path = TEST_RESOURCES_DIR_2D
        message = self._module_widget.pathInfoLabel.text
        self.assertEqual(message, "Will import a volume with 3 slices from example_00.tif")
        assert load_button.enabled, f"Load button attribute is set as '{load_button.enabled}'. Expected True"
        imageSpacing1.setText("1")
        imageSpacing2.setText("1")
        imageSpacing3.setText("1")
        invertWidthCheckBox.setCheckState(qt.Qt.Unchecked)
        invertLengthCheckBox.setCheckState(qt.Qt.Unchecked)

        # Load files in folder 2D
        load_button.click()

        # Check node created from the thin section image loading process
        node = tryGetNode(EXAMPLE_FILE_TIF2D.stem)
        assert node is not None, "Node was not generated from the loading process."
        sibling_nodes = get_subject_hierarchy_siblings(node)
        assert len(sibling_nodes) == 1, "Expected 1 node to be generated from the loading process."

        # Check if folder 2D node directions WERE NOT inverted
        directions = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        node.GetIJKToRASDirections(directions)
        assert directions == [[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0]], f"got {directions}"

        min_, max_ = node.GetImageData().GetScalarRange()
        self.assertAlmostEqual(min_, 12)
        self.assertAlmostEqual(max_, 255)

    def test_cylinder_detection_failure(self):
        load_button = self.__widgets["loadMicroCTs"]
        self._module_widget.pathWidget.path = TEST_RESOURCES_DIR_2D
        self._module_widget.cropCylinderCheckBox.setChecked(True)

        assert self._module_widget.manualCylinderWidget.section.collapsed
        load_button.click()

        # Check node created from the thin section image loading process
        node = tryGetNode(EXAMPLE_FILE_TIF2D.stem)
        assert node is not None, "Node was not generated from the loading process."
        sibling_nodes = get_subject_hierarchy_siblings(node)
        assert len(sibling_nodes) == 1, (
            f"Expected 1 node to be generated from the loading process. Got {len(sibling_nodes)}."
        )

        min_, max_ = node.GetImageData().GetScalarRange()
        expectedMin = 12
        expectedMax = 255
        self.assertAlmostEqual(min_, expectedMin, delta=0.0001)
        self.assertAlmostEqual(max_, expectedMax, delta=0.0001)

        label = self._module_widget.manualCylinderWidget.instructionLabel.statusLabel
        assert label.text == "Drag the handles on the view until the box tightly fits the rock cylinder."
        assert not self._module_widget.manualCylinderWidget.section.collapsed
        assert self._module_widget.manualCylinderWidget.adjustButton.text == "Apply crop"
        assert self._module_widget.manualCylinderWidget.cancelButton.visible
        assert self._module_widget.manualCylinderWidget.cylinderRoi.GetName() == "Cylinder bounds"

    def test_import_folder_of_volumes(self):
        load_button = self.__widgets["loadMicroCTs"]
        imageSpacing1 = self.__widgets["imageSpacing1"]
        imageSpacing2 = self.__widgets["imageSpacing2"]
        imageSpacing3 = self.__widgets["imageSpacing3"]
        invertWidthCheckBox = self.__widgets["invertWidth"]
        invertLengthCheckBox = self.__widgets["invertLength"]
        invertHeightCheckBox = self.__widgets["invertHeight"]

        # Update path in widget 3D
        self._module_widget.pathWidget.path = TEST_RESOURCES_DIR_3D
        message = self._module_widget.pathInfoLabel.text
        assert message == "Will import 4 volumes"
        assert load_button.enabled, f"Load button attribute is set as '{load_button.enabled}'. Expected True"
        imageSpacing1.setText("1")
        imageSpacing2.setText("1")
        imageSpacing3.setText("1")
        invertWidthCheckBox.setCheckState(qt.Qt.Unchecked)
        invertLengthCheckBox.setCheckState(qt.Qt.Unchecked)
        invertHeightCheckBox.setCheckState(qt.Qt.Checked)

        # Load files in folder 3D
        load_button.click()

        # Check node created from the thin section image loading process
        node = tryGetNode(EXAMPLE_FILE_TIF3D.stem)
        assert node is not None, "Node was not generated from the loading process."
        sibling_nodes = get_subject_hierarchy_siblings(node)
        assert len(sibling_nodes) == 4, "Expected 4 nodes to be generated from the loading process."

        # Check if one of the 3D node directions WERE inverted
        directions = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        node.GetIJKToRASDirections(directions)
        assert directions == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, -1.0]], f"got {directions}"

    def test_import_file(self):
        load_button = self.__widgets["loadMicroCTs"]
        imageSpacing1 = self.__widgets["imageSpacing1"]
        imageSpacing2 = self.__widgets["imageSpacing2"]
        imageSpacing3 = self.__widgets["imageSpacing3"]
        invertWidthCheckBox = self.__widgets["invertWidth"]
        invertLengthCheckBox = self.__widgets["invertLength"]
        invertHeightCheckBox = self.__widgets["invertHeight"]

        # Update path in widget 2D
        self._module_widget.pathWidget.path = EXAMPLE_FILE_TIF2D
        message = self._module_widget.pathInfoLabel.text
        assert message == "Will import a single slice from example_00.tif"
        assert load_button.enabled, f"Load button attribute is set as '{load_button.enabled}'. Expected True"
        imageSpacing1.setText("1")
        imageSpacing2.setText("1")
        imageSpacing3.setText("1")
        invertWidthCheckBox.setCheckState(qt.Qt.Unchecked)
        invertLengthCheckBox.setCheckState(qt.Qt.Unchecked)
        invertHeightCheckBox.setCheckState(qt.Qt.Checked)
        # Load files in folder 2D
        load_button.click()

        # Check node created from the thin section image loading process
        node = tryGetNode(EXAMPLE_FILE_TIF2D.stem)
        assert node is not None, "Node was not generated from the loading process."
        sibling_nodes = get_subject_hierarchy_siblings(node)
        assert len(sibling_nodes) == 1, "Expected 1 node to be generated from the loading process."

        # Check if node directions WAS inverted
        directions = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        node.GetIJKToRASDirections(directions)
        assert directions == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, -1.0]], f"got {directions}"

        # Update path in widget 3D
        self._module_widget.pathWidget.path = EXAMPLE_FILE_TIF3D
        message = self._module_widget.pathInfoLabel.text
        self.assertEqual(message, "Will import a volume with 10 slices from A_B_C_D_CT_00.tif")
        assert load_button.enabled, f"Load button attribute is set as '{load_button.enabled}'. Expected True"
        imageSpacing1.setText("1")
        imageSpacing2.setText("1")
        imageSpacing3.setText("1")
        invertWidthCheckBox.setCheckState(qt.Qt.Unchecked)
        invertLengthCheckBox.setCheckState(qt.Qt.Unchecked)
        invertHeightCheckBox.setCheckState(qt.Qt.Checked)
        # Load files in folder 3D
        load_button.click()

        # Check node created from the thin section image loading process
        node = tryGetNode(EXAMPLE_FILE_TIF3D.stem)
        assert node is not None, "Node was not generated from the loading process."
        sibling_nodes = get_subject_hierarchy_siblings(node)
        assert len(sibling_nodes) == 1, "Expected 1 node to be generated from the loading process."

        # Check if node directions WAS inverted
        directions = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        node.GetIJKToRASDirections(directions)
        assert directions == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, -1.0]], f"got {directions}"

    def test_import_labelmap_file(self):
        load_button = self.__widgets["loadMicroCTs"]
        loadAsLabelmapCheckbox = self.__widgets["loadAsLabelmap"]

        self._module_widget.pathWidget.path = EXAMPLE_FILE_TIF3D
        message = self._module_widget.pathInfoLabel.text
        assert message == "Will import a volume with 10 slices from A_B_C_D_CT_00.tif"
        assert load_button.enabled, f"Load button attribute is set as '{load_button.enabled}'. Expected True"

        loadAsLabelmapCheckbox.setCheckState(qt.Qt.Checked)
        load_button.click()

        node = tryGetNode(EXAMPLE_FILE_TIF3D.stem)
        assert node is not None, "Node was not generated from the loading process."
        sibling_nodes = get_subject_hierarchy_siblings(node)
        assert len(sibling_nodes) == 1, "Expected 1 node to be generated from the loading process."
        assert isinstance(node, slicer.vtkMRMLLabelMapVolumeNode), (
            f"Expected class vtkMRMLLabelMapVolumeNode. Got {node.GetClassName()}"
        )

    def test_import_sequence_of_volumes(self):
        loadButton = self.__widgets["loadMicroCTs"]
        loadAsSequenceCheckbox = self.__widgets["loadAsSequence"]

        self._module_widget.pathWidget.path = TEST_RESOURCES_DIR_3D
        message = self._module_widget.pathInfoLabel.text
        assert message == "Will import 4 volumes"
        assert loadButton.enabled, f"Load button attribute is set as '{loadButton.enabled}'. Expected True"

        loadAsSequenceCheckbox.setCheckState(qt.Qt.Checked)
        loadButton.click()

        pathName = TEST_RESOURCES_DIR_3D.name

        proxNode = tryGetNode(f"{pathName}_proxy")
        assert proxNode is not None, f"Proxy node {pathName}_proxy was not generated from the loading process."

        sequenceNode = tryGetNode(f"{pathName}_sequence")
        assert sequenceNode is not None, "Sequence node was not generated from the loading process."
        assert sequenceNode.GetNumberOfDataNodes() == 4, (
            f"Expected 4 data nodes in sequence, but got {sequenceNode.GetNumberOfDataNodes()}"
        )

        browserNode = tryGetNode(f"{pathName}_browser")
        assert browserNode is not None, "Browser node was not generated from the loading process."

    def test_count_images_in_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_names = [
                "foo_5nm0001.tif",
                "foo_5nm0002.tif",
                "foo_5nm0003.tif",
                "bar_10nm0000.tif",
                "bar_10nm0001.tif",
                "bar_10nm0003.tif",
                "bar_10nm0004.tif",
                "biz.jpg",
                "blah.nc",
            ]

            for file_name in file_names:
                if file_name.endswith(".tif"):
                    # copy from test resources
                    shutil.copy(TEST_RESOURCES_DIR_2D / "example_00.tif", Path(temp_dir, file_name))
                else:
                    Path(temp_dir, file_name).touch()

            widget = self._module_widget
            widget.pathWidget.pathLineEdit.setText(temp_dir)
            widget.pathWidget.pathLineEdit.editingFinished.emit()

            self.assertEqual(widget.pathInfoLabel.text, "Will import a volume with 3 slices from foo_5nm0001.tif")

            shutil.copy(TEST_RESOURCES_DIR_2D / "example_00.tif", Path(temp_dir, "bar_10nm0002.tif"))

            widget.pathWidget.pathLineEdit.setText("")
            widget.pathWidget.pathLineEdit.editingFinished.emit()
            self.assertEqual(widget.pathInfoLabel.text, "No images found")

            widget.pathWidget.pathLineEdit.setText(temp_dir)
            widget.pathWidget.pathLineEdit.editingFinished.emit()

            self.assertEqual(widget.pathInfoLabel.text, "Will import a volume with 5 slices from bar_10nm0000.tif")

            path = Path(temp_dir, "blah.nc")
            widget.pathWidget.pathLineEdit.setText(path.absolute().as_posix())
            widget.pathWidget.pathLineEdit.editingFinished.emit()

            self.assertEqual(widget.pathInfoLabel.text, "Will import image(s) from NetCDF file")

            path = Path(temp_dir, "biz.jpg")
            widget.pathWidget.pathLineEdit.setText(path.absolute().as_posix())
            widget.pathWidget.pathLineEdit.editingFinished.emit()

            self.assertEqual(widget.pathInfoLabel.text, "Will import a single slice from biz.jpg")

    def test_unreachable_path_does_not_crash(self):
        """A directory that exists but cannot be listed (os.listdir/os.scandir
        raising PermissionError, as with C:/denydir) must not crash the loader;
        it is reported as having no images."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_posix = Path(temp_dir).as_posix()

            def deny(orig):
                def wrapped(path, *args, **kwargs):
                    if temp_posix in str(path).replace("\\", "/"):
                        raise PermissionError(13, "Access is denied")
                    return orig(path, *args, **kwargs)

                return wrapped

            with patch("os.scandir", deny(os.scandir)), patch("os.listdir", deny(os.listdir)):
                self._module_widget.pathWidget.path = temp_dir

            self.assertEqual(self._module_widget.pathInfoLabel.text, "No images found")
            node = tryGetNode(Path(temp_dir).stem)
            assert node is None, "No node should be created for an unlistable directory"

    def _test_import_nc(self, crop, mode, expected_mean, expected_range, expected_dtype):
        file_name = RESOURCES / "SEP9D_520700_SAT_AL_38400nm_small.nc"

        self._module_widget.pathWidget.path = file_name

        self._module_widget.cropCylinderCheckBox.setChecked(crop)

        self._module_widget.loadButton.click()

        if crop:
            assert self._module_widget.manualCylinderWidget.adjustButton.text == "Apply crop"
            self._module_widget.manualCylinderWidget.adjustButton.click()

        node_name = "test_3_cups"
        if crop:
            node_name += " - Cylinder"
        node = tryGetNode(node_name)
        array = slicer.util.arrayFromVolume(node)
        min_ = array.min()
        max_ = array.max()
        mean = array.mean()

        delta = (expected_range[1] - expected_range[0]) * 0.01
        self.assertAlmostEqual(mean, expected_mean, delta=delta)
        self.assertAlmostEqual(min_, expected_range[0], delta=delta)
        self.assertAlmostEqual(max_, expected_range[1], delta=delta)
        self.assertEqual(array.dtype, expected_dtype)

        if crop:
            np.testing.assert_array_equal(array[:, :15, :], min_)
            np.testing.assert_array_equal(array[:, -15:, :], min_)
            np.testing.assert_array_equal(array[:, :, :15], min_)
            np.testing.assert_array_equal(array[:, :, -15:], min_)
            self.assertAlmostEqual(getVolumeNullValue(node), expected_range[0])

    def test_import_nc_no_conversion(self):
        self._test_import_nc(False, None, 9077.57397860294, (2240.0, 61529.0), np.uint16)

        label = self._module_widget.manualCylinderWidget.instructionLabel.statusLabel
        assert label.text == "Select a volume to manually crop the rock cylinder."
        assert self._module_widget.manualCylinderWidget.section.collapsed
        assert self._module_widget.manualCylinderWidget.adjustButton.text == "Start adjusting crop"
        assert not self._module_widget.manualCylinderWidget.cancelButton.visible
        assert self._module_widget.manualCylinderWidget.cylinderRoi is None

        self._module_widget.manualCylinderWidget.section.collapsed = False
        process_events()

        node_name = "test_3_cups"
        node = tryGetNode(node_name)
        self._module_widget.manualCylinderWidget.volumeInput.setCurrentNode(node)
        process_events()
        self._module_widget.manualCylinderWidget.adjustButton.click()
        process_events()
        assert self._module_widget.manualCylinderWidget.adjustButton.text == "Apply crop"
        assert self._module_widget.manualCylinderWidget.cancelButton.visible
        assert label.text == "Drag the handles on the view until the box tightly fits the rock cylinder."
        assert self._module_widget.manualCylinderWidget.cylinderRoi.GetName() == "Cylinder bounds"
        assert not self._module_widget.manualCylinderWidget.section.collapsed

        self._module_widget.manualCylinderWidget.cancelButton.click()
        process_events()
        assert self._module_widget.manualCylinderWidget.adjustButton.text == "Start adjusting crop"
        assert not self._module_widget.manualCylinderWidget.cancelButton.visible
        assert label.text == "Select a volume to manually crop the rock cylinder."
        assert self._module_widget.manualCylinderWidget.cylinderRoi is None
        assert not slicer.mrmlScene.GetFirstNodeByName("Cylinder bounds")
        assert not self._module_widget.manualCylinderWidget.section.collapsed

        self._module_widget.manualCylinderWidget.adjustButton.click()
        process_events()
        assert self._module_widget.manualCylinderWidget.adjustButton.text == "Apply crop"
        assert self._module_widget.manualCylinderWidget.cancelButton.visible
        assert label.text == "Drag the handles on the view until the box tightly fits the rock cylinder."
        assert self._module_widget.manualCylinderWidget.cylinderRoi.GetName() == "Cylinder bounds"
        assert not self._module_widget.manualCylinderWidget.section.collapsed

        self._module_widget.manualCylinderWidget.adjustButton.click()
        process_events()
        assert self._module_widget.manualCylinderWidget.adjustButton.text == "Start adjusting crop"
        assert not self._module_widget.manualCylinderWidget.cancelButton.visible
        assert label.text == "Select a volume to manually crop the rock cylinder."
        assert self._module_widget.manualCylinderWidget.cylinderRoi is None
        assert not slicer.mrmlScene.GetFirstNodeByName("Cylinder bounds")
        assert self._module_widget.manualCylinderWidget.section.collapsed

        manual_crop_array = slicer.util.arrayFromVolume(tryGetNode("test_3_cups - Cylinder"))
        original_array = slicer.util.arrayFromVolume(tryGetNode("test_3_cups"))
        # No adjustment was made, so the manual crop shape should be the original + 15 pixels on each side
        expected_shape = (original_array.shape[0], original_array.shape[1] + 30, original_array.shape[2] + 30)
        assert manual_crop_array.shape == expected_shape

    def test_import_nc_convert_to_al_mean(self):
        self._test_import_nc(False, 1, 9077.57397860294, (2240.0, 61529.0), np.uint16)

    def test_import_nc_convert_to_al_contrast(self):
        self._test_import_nc(False, 2, 9077.57397860294, (2240.0, 61529.0), np.uint16)

    def test_import_nc_no_conversion_with_crop(self):
        # Import, detect cylinder, confirm crop
        self._test_import_nc(True, None, 8601.265358271276, (0.0, 61529.0), np.uint16)

        label = self._module_widget.manualCylinderWidget.instructionLabel.statusLabel
        assert self._module_widget.manualCylinderWidget.adjustButton.text == "Start adjusting crop"
        assert not self._module_widget.manualCylinderWidget.cancelButton.visible
        assert label.text == "Select a volume to manually crop the rock cylinder."
        assert self._module_widget.manualCylinderWidget.cylinderRoi is None
        assert not slicer.mrmlScene.GetFirstNodeByName("Cylinder bounds")

        # Enter adjustment again
        self._module_widget.manualCylinderWidget.section.collapsed = False
        self._module_widget.manualCylinderWidget.adjustButton.click()
        assert self._module_widget.manualCylinderWidget.adjustButton.text == "Apply crop"
        assert self._module_widget.manualCylinderWidget.cancelButton.visible
        assert label.text == "Drag the handles on the view until the box tightly fits the rock cylinder."
        assert self._module_widget.manualCylinderWidget.cylinderRoi.GetName() == "Cylinder bounds"

        # Apply adjustment
        self._module_widget.manualCylinderWidget.adjustButton.click()
        assert self._module_widget.manualCylinderWidget.adjustButton.text == "Start adjusting crop"
        assert not self._module_widget.manualCylinderWidget.cancelButton.visible
        assert label.text == "Select a volume to manually crop the rock cylinder."
        assert self._module_widget.manualCylinderWidget.cylinderRoi is None
        assert not slicer.mrmlScene.GetFirstNodeByName("Cylinder bounds")
        assert self._module_widget.manualCylinderWidget.section.collapsed

    def test_import_nc_convert_to_al_mean_with_crop(self):
        self._test_import_nc(True, 1, 8601.265358271276, (0.0, 61529.0), np.uint16)

    def test_import_nc_convert_to_al_contrast_with_crop(self):
        self._test_import_nc(True, 2, 8601.265358271276, (0.0, 61529), np.uint16)

    ### RAW tests
    def check_color_node(self, color_node, color_list):
        i = 1
        self.assertEqual(color_node.GetNumberOfColors(), len(color_list) + 1)
        for name, color_rgb_256 in color_list:
            self.assertEqual(color_node.GetColorName(i), name)
            if color_rgb_256:
                color_rgb_01 = tuple(c / 255 for c in color_rgb_256) + (1,)
                color = [0] * 4
                color_node.GetColor(i, color)
                for a, b in zip(color_rgb_01, color):
                    self.assertAlmostEqual(a, b, delta=0.001)
            i += 1

    def create_bin_array(self):
        data = np.array([0, 0, 1, 0, 1], dtype=np.uint8)
        data = np.tile(data, (10, 20, 6))
        return data

    def generate_bin_array(self):
        data = self.create_bin_array()
        data.tofile(BIN_PATH)

    def create_bin_float_array(self):
        data = np.array([0, 0, 1, 0, 1], dtype=np.float32) + 0.2
        data = np.tile(data, (10, 20, 6))
        return data

    def generate_bin_float_array(self):
        data = self.create_bin_float_array()
        data.tofile(BIN_FLOAT_PATH)

    def create_basins_array(self):
        data = np.array([0, 1, 2, 3, 4, 5, 4, 3, 2, 1], dtype=np.uint8)
        data = np.tile(data, (10, 20, 3))
        return data

    def generate_basins_array(self):
        data = self.create_basins_array()
        data.tofile(BASINS_PATH)

    def create_labels_array(self):
        data = np.array([0, 1, 3, 4, 6, 9, 10, 11, 12, 15], dtype=np.uint8)
        data = np.tile(data, (10, 20, 3))
        return data

    def generate_labels_array(self):
        data = self.create_labels_array()
        data.tofile(LABELS_PATH)

    def _common_raw_test(
        self, path, name, color_list=None, expected_array=None, auto_crop: bool = False, dtype=None
    ) -> None:
        widget = self._module_widget.rawWidget
        widget.inputFileSelector.path = str(path)
        process_events()

        if dtype:
            widget.pixelTypeComboBox.setCurrentText(dtype)
        self._module_widget.cropCylinderCheckBox.setChecked(auto_crop)

        process_events()

        widget.updateButton.click()
        output_name = widget.outputVolumeName.text
        self.assertTrue(
            output_name.startswith(name), f"Expected output name to start with '{name}', got '{output_name}'"
        )

        node = slicer.util.getNode(output_name)
        array = slicer.util.arrayFromVolume(node)
        if expected_array is not None:
            self.assertTrue(np.array_equal(array, expected_array))
            self.assertEqual(node.GetSpacing(), EXPECTED_SPACING)

        if color_list is not None:
            color_node = node.GetDisplayNode().GetColorNode()
            self.assertIsNotNone(color_node)
            self.check_color_node(color_node, color_list)

        return node

    def test_raw_load_bin(self):
        self._common_raw_test(
            path=BIN_PATH,
            name="THIS_IS_A_TEST",
            color_list=[("Pore", (0, 128, 255))],
            expected_array=self.create_bin_array(),
        )

    def test_raw_load_after_deleting_labelmap(self):
        output_node = self._common_raw_test(
            path=BIN_PATH,
            name="THIS_IS_A_TEST",
            color_list=[("Pore", (0, 128, 255))],
            expected_array=self.create_bin_array(),
        )
        slicer.mrmlScene.RemoveNode(output_node)
        self._common_raw_test(
            path=BIN_PATH,
            name="THIS_IS_A_TEST",
            color_list=[("Pore", (0, 128, 255))],
            expected_array=self.create_bin_array(),
        )

    def test_raw_load_bin_float(self):
        self._common_raw_test(
            path=BIN_FLOAT_PATH,
            name="WEIRD_FLOAT_SEGMENTATION_TEST",
            color_list=[("Pore", (0, 128, 255))],
            expected_array=np.rint(self.create_bin_float_array()).astype(np.uint16),
            dtype="float",
        )

    def test_raw_load_labels(self):
        colors = [(f"Segment_{i}", None) for i in range(1, 16)]
        self._common_raw_test(
            path=LABELS_PATH, name="THIS_IS_A_TEST", color_list=colors, expected_array=self.create_labels_array()
        )

    def test_raw_load_basins(self):
        colors = [
            ("Pore", (0, 128, 255)),
            ("Quartz", (0, 0, 255)),
            ("Microporosity", (255, 0, 0)),
            ("Calcite", (0, 255, 0)),
            ("High attenuation coefficient", (255, 255, 0)),
        ]
        self._common_raw_test(
            path=BASINS_PATH, name="THIS_IS_A_TEST", color_list=colors, expected_array=self.create_basins_array()
        )

    def test_raw_load_bin_with_auto_crop(self):
        widget = self._module_widget.rawWidget
        outputNode = self._common_raw_test(path=CUPS_PATH, name="SEP9D_520700_SAT_AL", auto_crop=True)
        assert widget.manualCylinderWidget.cylinderRoi is not None

        assert widget.manualCylinderWidget.adjustButton.text == "Apply crop"
        widget.manualCylinderWidget.adjustButton.click()
        process_events()

        assert widget.manualCylinderWidget.adjustButton.text == "Start adjusting crop"
        assert tryGetNode(f"{outputNode.GetName()} - Cylinder") is not None
        assert widget.manualCylinderWidget.cylinderRoi is None

    def test_raw_load_bin_with_manual_crop(self):
        widget = self._module_widget.rawWidget
        outputNode = self._common_raw_test(path=CUPS_PATH, name="SEP9D_520700_SAT_AL", auto_crop=False)
        wait(1)
        assert widget.manualCylinderWidget.cylinderRoi is None
        assert widget.manualCylinderWidget.adjustButton.text == "Start adjusting crop"
        assert widget.manualCylinderWidget.volumeInput.currentNode() is not None
        assert widget.manualCylinderWidget.volumeInput.currentNode().GetName() == outputNode.GetName(), (
            f"Expected '{outputNode.GetName()}', got {widget.manualCylinderWidget.volumeInput.currentNode().GetName()}"
        )

        widget.manualCylinderWidget.adjustButton.click()
        process_events()

        assert tryGetNode(f"{outputNode.GetName()} - Cylinder") is None
        assert widget.manualCylinderWidget.cylinderRoi is not None
        assert widget.manualCylinderWidget.adjustButton.text == "Apply crop"

        widget.manualCylinderWidget.adjustButton.click()
        process_events()

        assert tryGetNode(f"{outputNode.GetName()} - Cylinder") is not None
        assert widget.manualCylinderWidget.cylinderRoi is None
        assert widget.manualCylinderWidget.adjustButton.text == "Start adjusting crop"

    def test_raw_load(self):
        widget = self._module_widget.rawWidget
        widget.inputFileSelector.path = str(CUPS_PATH)
        process_events()

        widget.updateButton.click()

        output_name = widget.outputVolumeName.text
        node = slicer.util.getNode(output_name)
        array = slicer.util.arrayFromVolume(node)

        mean = array.mean()
        min_ = array.min()
        max_ = array.max()

        # Values from raw_normalization test
        self.assertNotEqual(mean, 3.4305172)
        self.assertNotEqual(min_, 0.8465207)
        self.assertNotEqual(max_, 23.252487)

        # Expected values
        self.assertAlmostEqual(mean, 9077.57397, delta=0.01)
        self.assertAlmostEqual(min_, 2240, delta=0.01)
        self.assertAlmostEqual(max_, 61529, delta=0.01)

    def _test_tescan_load(self, input_path, custom_inversion=None):
        expected_spacing_mm = 0.12313137
        expected_origin_mm = (-2.8262, 204.5443, 0.0)
        node_name = "scan_000034"

        self._module_widget.pathWidget.path = str(input_path)
        process_events()

        recon_dir = TESCAN_ROOT / "recon"

        self.assertEqual(self._module_widget.pathWidget.path, str(recon_dir))
        self.assertEqual(
            self._module_widget.pathInfoLabel.text,
            f"Will import a volume with 10 slices from {node_name}.tif",
        )
        self.assertAlmostEqual(float(self.__widgets["imageSpacing1"].text), expected_spacing_mm * 1000, places=3)
        self.assertTrue(self.__widgets["loadMicroCTs"].enabled)

        inversion_widgets = (
            self.__widgets["invertWidth"],
            self.__widgets["invertLength"],
            self.__widgets["invertHeight"],
        )
        if custom_inversion:
            for widget, flag in zip(inversion_widgets, custom_inversion):
                widget.setChecked(flag)

        inversion_multipliers = [-1 if w.isChecked() else 1 for w in inversion_widgets]

        self.__widgets["loadMicroCTs"].click()
        process_events()

        node = tryGetNode(node_name)
        self.assertIsNotNone(node, f"Node '{node_name}' was not loaded.")

        np.testing.assert_allclose(node.GetSpacing(), (expected_spacing_mm,) * 3, atol=1e-6)

        final_origin_mm = tuple(o * m for o, m in zip(expected_origin_mm, inversion_multipliers))
        np.testing.assert_allclose(node.GetOrigin(), final_origin_mm, atol=1e-6)

    def test_import_tescan_from_root_dir(self):
        self._test_tescan_load(TESCAN_ROOT)

    def test_import_tescan_from_recon_dir_with_custom_inversion(self):
        custom_inversion_flags = (False, False, True)
        self._test_tescan_load(TESCAN_ROOT / "recon", custom_inversion=custom_inversion_flags)

    def test_import_file_with_without_auto_crop_feature(self):
        #
        def process(filePath: Path, autoCrop: bool = False) -> None:
            widget = self._module_widget.rawWidget
            widget.inputFileSelector.path = str(filePath)
            process_events()
            if autoCrop:
                self._module_widget.cropCylinderCheckBox.setChecked(autoCrop)
            process_events()

            widget.updateButton.click()

        dataWithoutAutoCropFeature = BIN_PATH
        dataWithAutoCropFeature = CUPS_PATH

        assert not self._module_widget.cropCylinderCheckBox.isChecked()

        wait(1)
        process(filePath=dataWithAutoCropFeature, autoCrop=True)

        assert self._module_widget.cropCylinderCheckBox.visible
        assert self._module_widget.cropCylinderCheckBox.isChecked()

        wait(1)
        process(filePath=dataWithoutAutoCropFeature, autoCrop=False)

        assert not self._module_widget.cropCylinderCheckBox.visible
        assert not self._module_widget.cropCylinderCheckBox.isChecked()

    def test_import_nc_from_directory(self):
        sampleNcFile = RESOURCES / "SEP9D_520700_SAT_AL_38400nm_small.nc"
        samplesNumber = 4
        datasetName = "dataset_name"
        with tempfile.TemporaryDirectory() as tempDir:
            tempDir = Path(tempDir) / datasetName
            tempDir.mkdir(parents=True, exist_ok=True)
            for i in range(samplesNumber):
                shutil.copy(sampleNcFile, tempDir / f"{sampleNcFile.stem}_{i}.nc")
                assert Path(tempDir / f"{sampleNcFile.stem}_{i}.nc").exists()

            self._module_widget.pathWidget.path = tempDir.as_posix()
            self._module_widget.loadButton.click()

            process_events()

            nodeName = "test_3_cups"
            node = tryGetNode(nodeName)

            assert node is not None, f"Node '{nodeName}' was not generated from the loading process."
            shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
            folderId = shNode.GetItemByName(datasetName)
            assert folderId != 0, "Folder 'dataset_name' was not generated from the loading process."
            assert node.GetImageData().GetDimensions() == (
                400,
                375,
                1088,
            ), f"Expected: (400, 375, 1088). Actual: {node.GetImageData().GetDimensions()}"

    ### AmiraMesh .am tests
    def test_am_file_ui(self):
        """Selecting a .am file should show amWidget and update pathInfoLabel."""
        self._module_widget.pathWidget.path = AM_FILE

        message = self._module_widget.pathInfoLabel.text
        self.assertEqual(message, "Will read AmiraMesh compatible data and load into GeoSlicer format")

        assert self._module_widget.amWidget.visible, "amWidget should be visible for .am files"
        assert not self._module_widget.normalWidget.visible, "normalWidget should be hidden for .am files"
        assert self._module_widget.amWidget._loadButton.enabled, "amWidget load button should be enabled"

        name_in_edit = self._module_widget.amWidget._nameEdit.text
        self.assertTrue(
            name_in_edit.startswith(AM_VOLUME_NAME),
            f"Expected name edit to start with '{AM_VOLUME_NAME}', got '{name_in_edit}'",
        )

    def test_import_am_file(self):
        """Loading a .am file should create a scalar volume node with correct data."""
        self._module_widget.pathWidget.path = AM_FILE
        process_events()

        self._module_widget.amWidget._loadButton.click()
        process_events()

        node_name = self._module_widget.amWidget._nameEdit.text
        node = tryGetNode(node_name)
        assert node is not None, f"Volume node '{node_name}' was not created."
        assert isinstance(node, slicer.vtkMRMLScalarVolumeNode), (
            f"Expected vtkMRMLScalarVolumeNode, got {node.GetClassName()}"
        )

        array = slicer.util.arrayFromVolume(node)
        # File has shape (nz=2, ny=3, nx=4)
        self.assertEqual(array.shape, (2, 3, 4), f"Unexpected shape: {array.shape}")
        self.assertEqual(int(array.min()), 0, f"Unexpected min: {array.min()}")
        self.assertEqual(int(array.max()), 23, f"Unexpected max: {array.max()}")

        # Spacing derived from BoundingBox [0,0.003]x[0,0.002]x[0,0.001] mm → 0.001 mm/voxel on each axis
        spacing = node.GetSpacing()
        self.assertAlmostEqual(spacing[0], 0.001, places=6)
        self.assertAlmostEqual(spacing[1], 0.001, places=6)
        self.assertAlmostEqual(spacing[2], 0.001, places=6)

    def test_import_am_labelmap(self):
        """Loading a .am file with 'Load as Labelmap' should create a labelmap node."""
        self._module_widget.pathWidget.path = AM_FILE
        process_events()

        self._module_widget.amWidget._labelmapCheckbox.setChecked(True)
        self._module_widget.amWidget._loadButton.click()
        process_events()

        node_name = self._module_widget.amWidget._nameEdit.text
        node = tryGetNode(node_name)
        assert node is not None, f"Labelmap node '{node_name}' was not created."
        assert isinstance(node, slicer.vtkMRMLLabelMapVolumeNode), (
            f"Expected vtkMRMLLabelMapVolumeNode, got {node.GetClassName()}"
        )

        color_node = node.GetDisplayNode().GetColorNode()
        assert color_node is not None, "Labelmap should have a dedicated color node."
        assert color_node.GetColorName(1) == "Segment_1", (
            f"Expected custom label name 'Segment_1', got '{color_node.GetColorName(1)}' "
            "(Slicer's default jake/Peach/Brain... table was not replaced)."
        )

    def test_am_bounding_box_registration(self):
        """Two .am volumes with adjacent bounding boxes should be positioned contiguously in space.

        Bottom volume: BoundingBox z=[0, 0.001] mm  → origin_z=0.0,   spacing_z=0.001
        Top    volume: BoundingBox z=[0.001, 0.002] mm → origin_z=0.001, spacing_z=0.001

        The RAS origin of the top volume must equal the last voxel centre of the bottom volume,
        i.e. origin_z(top) == origin_z(bottom) + (nz-1) * spacing_z(bottom).
        """
        logic = AmLoaderLogic()

        node_bottom = logic.load(AM_FILE, volumeName="am_bottom")
        node_top = logic.load(AM_FILE_SHIFTED_Z, volumeName="am_top")

        origin_bottom = node_bottom.GetOrigin()  # (x, y, z) in mm
        origin_top = node_top.GetOrigin()
        spacing_bottom = node_bottom.GetSpacing()  # (sx, sy, sz) in mm

        nz = node_bottom.GetImageData().GetDimensions()[2]

        # x and y origins should be identical (same x/y bounding box)
        self.assertAlmostEqual(origin_bottom[0], origin_top[0], places=6, msg="x origins differ")
        self.assertAlmostEqual(origin_bottom[1], origin_top[1], places=6, msg="y origins differ")

        # bottom volume starts at z=0
        self.assertAlmostEqual(origin_bottom[2], 0.0, places=6, msg="bottom origin_z should be 0")

        # top volume starts exactly one step above the last voxel of the bottom volume
        expected_top_origin_z = origin_bottom[2] + (nz - 1) * spacing_bottom[2]
        self.assertAlmostEqual(
            origin_top[2],
            expected_top_origin_z,
            places=6,
            msg=f"top origin_z {origin_top[2]} != expected {expected_top_origin_z}",
        )

        # Sanity-check data ranges so we know the right files were loaded
        array_bottom = slicer.util.arrayFromVolume(node_bottom)
        array_top = slicer.util.arrayFromVolume(node_top)
        self.assertEqual(int(array_bottom.min()), 0)
        self.assertEqual(int(array_bottom.max()), 23)
        self.assertEqual(int(array_top.min()), 100)
        self.assertEqual(int(array_top.max()), 123)
