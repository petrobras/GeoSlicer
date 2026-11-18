from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import check_for_message_box, load_project, wait_cli_to_finish
from commons.slicer.helpers import tryGetNode
from pathlib import Path
from pathvalidate import sanitize_filepath
from typing import List

from commons.slicer.lazy import lazy
import commons.slicer.netcdf as netcdf
import numpy as np
import shutil
import slicer
import tempfile
from dataclasses import dataclass

RESOURCE_DIR = Path(__file__).parent / "Resources"
PROJECT_FILE_PATH = RESOURCE_DIR / "RAW" / "RAW.mrml"


@dataclass
class Settings:
    outputPathLineEditSettingKey: str = ""
    outputPathLineEditCurrentPath: str = ""


class BoundaryRemovalBigImageTest(LTracePluginTest):
    def pre_setup(self) -> None:
        self._tempDirectory = Path(tempfile.TemporaryDirectory().name)
        self._tempDirectory.mkdir(parents=True, exist_ok=True)

    def post_setup(self) -> None:
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = {
            "applyButton": self.find_widget("Apply Button"),
            "outputPathLineEdit": self.find_widget("Output Path Line Edit"),
            "threshouldSlider": self.find_widget("Threshold Slider"),
            "inputSelector": self.find_widget("Input Selector"),
            "segmentationSelector": self.find_widget("Segmentation Selector"),
        }

        for objectName, widget in self._widgets.items():
            assert widget is not None, f"Missing widget {objectName}"

        self._avoid_qsettings_conflict()

    def tear_down(self) -> None:
        if self._tempDirectory.exists():
            shutil.rmtree(self._tempDirectory)

        # Maintain widgets old Settings values

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
            return node

    def _assert_segmentation_nodes(
        self,
        templateNode: slicer.vtkMRMLSegmentationNode,
        generatedNode: slicer.vtkMRMLSegmentationNode,
        volumeNode: slicer.vtkMRMLNode,
    ) -> None:
        def getSegmentsIds(node: slicer.vtkMRMLSegmentationNode) -> List[str]:
            segmentation = node.GetSegmentation()
            segmentsIds = segmentation.GetSegmentIDs()
            return segmentsIds

        def getArrayFromSegmentId(
            segmentationNode: slicer.vtkMRMLSegmentationNode, segmentId: slicer.vtkMRMLSegmentationNode
        ) -> np.ndarray:
            return slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, segmentId, volumeNode)

        # Check same number and name of segments.
        templateSegmentIds = getSegmentsIds(templateNode)
        generatedSegmentIds = getSegmentsIds(generatedNode)

        assert templateSegmentIds == generatedSegmentIds

        for segmentId in templateSegmentIds:
            templateSegmentArray = getArrayFromSegmentId(segmentationNode=templateNode, segmentId=segmentId)
            generatedSegmentArray = getArrayFromSegmentId(segmentationNode=generatedNode, segmentId=segmentId)

            np.testing.assert_array_equal(
                templateSegmentArray, generatedSegmentArray, err_msg=f"Problem with segment ID {segmentId}"
            )

    def test_default_interface_configuration(self) -> None:
        applyButton = self._widgets["applyButton"]
        outputPathLineEdit = self._widgets["outputPathLineEdit"]
        thresholdSlider = self._widgets["threshouldSlider"]
        inputSelector = self._widgets["inputSelector"]
        segmentationSelector = self._widgets["segmentationSelector"]

        assert applyButton is not None
        assert applyButton.enabled
        assert outputPathLineEdit.enabled
        assert outputPathLineEdit.currentPath == ""
        assert thresholdSlider.enabled
        assert np.isclose(thresholdSlider.minimumValue, 0)
        assert np.isclose(thresholdSlider.maximumValue, 0)
        assert inputSelector.currentNode() is None, f"Current input node is {inputSelector.currentNode.GetName()}"
        assert segmentationSelector.currentNode() is None, (
            f"Current segmentation node is {segmentationSelector.currentNode.GetName()}"
        )

    def test_attempt_to_execute_without_input_node(self) -> None:
        applyButton = self._widgets["applyButton"]

        data = {"volumeNode": None, "segmentationNode": None, "exportPath": ""}

        self._module_widget.setParameters(**data)

        # Simulate click on apply button
        with check_for_message_box("Please select an input node.", timeout_sec=5):
            applyButton.clicked()

    def test_attempt_to_execute_without_segmentation_node(self) -> None:
        load_project(PROJECT_FILE_PATH)
        applyButton = self._widgets["applyButton"]

        volumeNode = slicer.util.getNode("IMAGE")
        assert volumeNode is not None

        data = {"volumeNode": volumeNode, "segmentationNode": None, "exportPath": ""}

        self._module_widget.setParameters(**data)

        # Simulate click on apply button
        with check_for_message_box("Please select a segmentation node.", timeout_sec=5):
            applyButton.clicked()

    def test_attempt_to_execute_without_export_path(self) -> None:
        load_project(PROJECT_FILE_PATH)
        applyButton = self._widgets["applyButton"]

        volumeNode = slicer.util.getNode("IMAGE")
        segmentationNode = slicer.util.getNode("Segmentation")
        assert volumeNode is not None
        assert segmentationNode is not None

        data = {"volumeNode": volumeNode, "segmentationNode": segmentationNode, "exportPath": ""}

        self._module_widget.setParameters(**data)

        # Simulate click on apply button
        with check_for_message_box("Please select an output path.", timeout_sec=5):
            applyButton.clicked()

    def test_apply_filter_using_usual_nodes(self) -> None:
        load_project(PROJECT_FILE_PATH)
        volumeNode = slicer.util.getNode("IMAGE")
        segmentationNode = slicer.util.getNode("Segmentation")
        assert volumeNode is not None
        assert segmentationNode is not None

        data = {
            "volumeNode": volumeNode,
            "segmentationNode": segmentationNode,
            "thresholdMinimumValue": 2000.00,
            "thresholdMaximumValue": 25255.00,
            "exportPath": (self._tempDirectory / "test.nc").as_posix(),
        }

        self._execute_plugin(data=data)

        # Assert result
        templateSegmentationNode = tryGetNode("Segmentation Template")
        newSegmentationNode = tryGetNode("Segmentation_filtered")

        assert (self._tempDirectory / "test.nc").exists()
        assert templateSegmentationNode is not None
        assert newSegmentationNode is not None

        convertedNewSegmentationNode = self._convertToUsualNode(newSegmentationNode)
        self._assert_segmentation_nodes(
            generatedNode=convertedNewSegmentationNode, templateNode=templateSegmentationNode, volumeNode=volumeNode
        )

    def test_apply_filter_using_lazy_nodes(self) -> None:
        load_project(PROJECT_FILE_PATH)

        volumeNode = slicer.util.getNode("IMAGE")
        segmentationNode = slicer.util.getNode("Segmentation")
        assert volumeNode is not None
        assert segmentationNode is not None

        # Create LazyNode from usual nodes
        volumeLazyNode = self._convertToLazyNode(volumeNode)
        segmentationLazyNode = self._convertToLazyNode(segmentationNode)

        assert volumeLazyNode is not None and lazy.is_lazy_node(volumeLazyNode)
        assert segmentationLazyNode is not None and lazy.is_lazy_node(segmentationLazyNode)

        data = {
            "volumeNode": volumeLazyNode,
            "segmentationNode": segmentationLazyNode,
            "thresholdMinimumValue": 2000.00,
            "thresholdMaximumValue": 25255.00,
            "exportPath": self._tempDirectory / "test.nc",
        }

        self._execute_plugin(data=data)

        # Assert result
        templateSegmentationNode = tryGetNode("Segmentation Template")
        newSegmentationNode = tryGetNode("Segmentation_filtered")
        assert (self._tempDirectory / "test.nc").exists()
        assert templateSegmentationNode is not None
        assert newSegmentationNode is not None

        convertedNewSegmentationNode = self._convertToUsualNode(newSegmentationNode)
        self._assert_segmentation_nodes(
            generatedNode=convertedNewSegmentationNode, templateNode=templateSegmentationNode, volumeNode=volumeNode
        )
