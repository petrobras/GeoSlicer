from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import check_for_message_box, load_project, wait_cli_to_finish, wait
from commons.slicer.helpers import tryGetNode
from pathlib import Path
from pathvalidate import sanitize_filepath

from commons.slicer.lazy import lazy
import commons.slicer.netcdf as netcdf
import shutil
import slicer
import tempfile
from dataclasses import dataclass

from unittest.mock import patch

RESOURCE_DIR = Path(__file__).parent / "Resources"
PROJECT_FILE_PATH = RESOURCE_DIR / "RAW" / "RAW.mrml"


@dataclass
class Settings:
    outputPathLineEditSettingKey: str = ""
    outputPathLineEditCurrentPath: str = ""


class PolynomialShadingCorrectionBigImageTest(LTracePluginTest):
    GLOBAL_TIMEOUT_MS = 30000

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.getSliceGroupSizePatcher = patch(
            "PolynomialShadingCorrectionBigImage.PolynomialShadingCorrectionBigImageWidget.getSliceGroupSize",
            lambda x: 7,
        )
        self.getFittingPointsPercentagePatcher = patch(
            "PolynomialShadingCorrectionBigImage.PolynomialShadingCorrectionBigImageWidget.getFittingPointsPercentage",
            lambda x: 60,
        )

    def pre_setup(self) -> None:
        self._tempDirectory = Path(tempfile.TemporaryDirectory().name)
        self._tempDirectory.mkdir(parents=True, exist_ok=True)
        self.getSliceGroupSizePatcher.start()
        self.getFittingPointsPercentagePatcher.start()

    def post_setup(self) -> None:
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = {
            "applyButton": self.find_widget("Apply Button"),
            "cancelButton": self.find_widget("Cancel Button"),
            "outputPathLineEdit": self.find_widget("Output Path Line Edit"),
            "inputImageSelector": self.find_widget("Input Image Selector"),
            "inputShadingMaskSelector": self.find_widget("Input Shading Mask Selector"),
            "sliceGroupSize": self.find_widget("Slice Group Size"),
            "fittingPointsPercentage": self.find_widget("Fitting Points Percentage"),
        }

        for objectName, widget in self._widgets.items():
            assert widget is not None, f"Missing widget {objectName}"

        self._avoid_qsettings_conflict()

    def tear_down(self) -> None:
        if self._tempDirectory.exists():
            shutil.rmtree(self._tempDirectory)

        # Maintain widgets old Settings values
        self.getSliceGroupSizePatcher.stop()
        self.getFittingPointsPercentagePatcher.stop()

        outputPathLineEdit = self._widgets["outputPathLineEdit"]
        outputPathLineEdit.settingKey = self._pluginOldSettings.outputPathLineEditSettingKey
        outputPathLineEdit.setCurrentPath(self._pluginOldSettings.outputPathLineEditCurrentPath)

        # Emit signal as the setter doesn't, to trigger events related to the path change.
        outputPathLineEdit.currentPathChanged.emit("")

    def _avoid_qsettings_conflict(self) -> None:
        outputPathLineEdit = self._widgets["outputPathLineEdit"]

        self._pluginOldSettings = Settings(
            outputPathLineEditSettingKey=outputPathLineEdit.settingKey,
            outputPathLineEditCurrentPath=outputPathLineEdit.setCurrentPath,
        )

        # Update widget default value
        outputPathLineEdit.settingKey = None  # Avoid data store/load from QSettings
        outputPathLineEdit.setCurrentPath("")  # Erase current data

        # Emit signal as the setter doesn't, to trigger events related to the path change.
        outputPathLineEdit.currentPathChanged.emit("")

    def _execute_plugin(self, data: dict) -> None:
        self._module_widget.setParameters(**data)

        # Simulate click on apply button
        with check_for_message_box("Process finished successfully.", timeout_sec=20):
            self._widgets["applyButton"].clicked()
            cliNode = self._module_widget.logic._cliNode
            wait_cli_to_finish(cli_entity=cliNode)

    def _convertToLazyNode(self, node: slicer.vtkMRMLNode) -> lazy.LazyNodeData:
        path = self._tempDirectory / f"{node.GetName().lower()}.nc"
        path = sanitize_filepath(file_path=path, platform="auto")
        netcdf.exportNetcdf(path, [node])

        assert path.exists(), f"Failed to export node {node.GetName()} as NetCDF"
        return lazy.LazyNodeData(url=f"file://{path.as_posix()}", var=f"{node.GetName()}").to_node()

    def _convertToUsualNode(self, node: slicer.vtkMRMLTextNode) -> slicer.vtkMRMLNode:
        if not lazy.is_lazy_node(node):
            return node

        lazyData = lazy.data(node)
        dataset = lazy.load_dataset(lazyData.url)
        for node in netcdf.import_dataset(dataset):
            node.SetAttribute("NullValue", "0")
            return node

    def test_default_interface_configuration(self) -> None:
        applyButton = self._widgets["applyButton"]
        cancelButton = self._widgets["cancelButton"]
        outputPathLineEdit = self._widgets["outputPathLineEdit"]
        inputImageSelector = self._widgets["inputImageSelector"]
        inputShadingMaskSelector = self._widgets["inputShadingMaskSelector"]
        sliceGroupSize = self._widgets["sliceGroupSize"]
        fittingPointsPercentage = self._widgets["fittingPointsPercentage"]

        assert inputImageSelector.currentNode() is None, (
            f"Current input node is {inputImageSelector.currentNode.GetName()}"
        )
        assert inputShadingMaskSelector.currentNode() is None, (
            f"Current input node is {inputShadingMaskSelector.currentNode.GetName()}"
        )
        assert sliceGroupSize.value == 7
        assert fittingPointsPercentage.value == 60
        assert outputPathLineEdit.enabled
        assert outputPathLineEdit.currentPath == ""
        assert applyButton is not None
        assert applyButton.enabled
        assert not cancelButton.enabled

    def test_attempt_to_execute_without_input_node(self) -> None:
        applyButton = self._widgets["applyButton"]

        data = {"inputNode": None, "inputShadingMaskNode": None, "exportPath": ""}

        self._module_widget.setParameters(**data)

        # Simulate click on apply button
        with check_for_message_box("Please select a volume node as the input.", timeout_sec=5):
            applyButton.clicked()

    def test_attempt_to_execute_without_input_shading_mask_node(self) -> None:
        load_project(PROJECT_FILE_PATH)
        applyButton = self._widgets["applyButton"]

        inputNode = slicer.util.getNode("shaded")
        assert inputNode is not None

        data = {"inputNode": inputNode, "inputShadingMaskNode": None, "exportPath": ""}

        self._module_widget.setParameters(**data)

        # Simulate click on apply button
        with check_for_message_box("Please select a node as the input shading mask.", timeout_sec=5):
            applyButton.clicked()

    def test_attempt_to_execute_without_export_path(self) -> None:
        load_project(PROJECT_FILE_PATH)
        applyButton = self._widgets["applyButton"]

        inputNode = slicer.util.getNode("shaded")
        inputShadingMaskNode = slicer.util.getNode("shading_mask")
        assert inputNode is not None
        assert inputShadingMaskNode is not None

        data = {
            "inputNode": inputNode,
            "inputShadingMaskNode": inputShadingMaskNode,
            "exportPath": "",
        }

        self._module_widget.setParameters(**data)

        # Simulate click on apply button
        with check_for_message_box("Please select an output path.", timeout_sec=5):
            applyButton.clicked()

    def test_apply_filter_using_usual_nodes(self) -> None:
        load_project(PROJECT_FILE_PATH)
        inputNode = slicer.util.getNode("shaded")
        inputShadingMaskNode = slicer.util.getNode("shading_mask")
        assert inputNode is not None
        assert inputShadingMaskNode is not None

        data = {
            "inputNode": inputNode,
            "inputShadingMaskNode": inputShadingMaskNode,
            "sliceGroupSize": 1,
            "fittingPointsPercentage": 100,
            "functionType": "Polynomial Radial",
            "polynomialOrder": 4,
            "useCustomCenter": False,
            "exportPath": (self._tempDirectory / "test.nc").as_posix(),
        }

        self._execute_plugin(data=data)

        # Assert result
        templateVolumeNode = tryGetNode("shaded_ShadingCorrection_Template_1")
        newVolumeNode = tryGetNode("shaded_filtered")

        assert (self._tempDirectory / "test.nc").exists()
        assert templateVolumeNode is not None
        assert newVolumeNode is not None

    def test_apply_filter_using_lazy_nodes(self) -> None:
        load_project(PROJECT_FILE_PATH)
        inputNode = slicer.util.getNode("shaded")
        inputShadingMaskNode = slicer.util.getNode("shading_mask")
        assert inputNode is not None
        assert inputShadingMaskNode is not None

        # Create LazyNode from usual nodes
        inputLazyNode = self._convertToLazyNode(inputNode)
        inputShadingMaskLazyNode = self._convertToLazyNode(inputShadingMaskNode)

        assert inputLazyNode is not None and lazy.is_lazy_node(inputLazyNode)
        assert inputShadingMaskLazyNode is not None and lazy.is_lazy_node(inputShadingMaskLazyNode)

        data = {
            "inputNode": inputNode,
            "inputShadingMaskNode": inputShadingMaskNode,
            "sliceGroupSize": 1,
            "fittingPointsPercentage": 100,
            "functionType": "Polynomial Radial",
            "polynomialOrder": 4,
            "useCustomCenter": False,
            "exportPath": (self._tempDirectory / "test.nc").as_posix(),
        }

        self._execute_plugin(data=data)

        # Assert result
        templateVolumeNode = tryGetNode("shaded_ShadingCorrection_Template_1")
        newVolumeNode = tryGetNode("shaded_filtered")

        assert (self._tempDirectory / "test.nc").exists()
        assert templateVolumeNode is not None
        assert newVolumeNode is not None

    def test_apply_filter_and_cancel(self) -> None:
        load_project(PROJECT_FILE_PATH)
        inputNode = slicer.util.getNode("shaded")
        inputShadingMaskNode = slicer.util.getNode("shading_mask")
        cancelButton = self._widgets["cancelButton"]
        applyButton = self._widgets["applyButton"]

        assert inputNode is not None
        assert inputShadingMaskNode is not None
        assert cancelButton is not None
        assert cancelButton.enabled is False
        assert applyButton is not None
        assert applyButton.enabled is True

        data = {
            "inputNode": inputNode,
            "inputShadingMaskNode": inputShadingMaskNode,
            "sliceGroupSize": 1,
            "fittingPointsPercentage": 100,
            "functionType": "Polynomial Radial",
            "polynomialOrder": 4,
            "useCustomCenter": False,
            "exportPath": (self._tempDirectory / "test.nc").as_posix(),
        }

        self._module_widget.setParameters(**data)

        applyButton.clicked()
        wait(0.1)
        assert self._module_widget.logic._cliNode is not None
        assert cancelButton.enabled is True
        assert applyButton.enabled is False

        cancelButton.clicked()
        wait(0.5)
        assert self._module_widget.logic._cliNode is None
        assert tryGetNode("shaded_filtered") is None
        assert cancelButton.enabled is False
        assert applyButton.enabled is True
