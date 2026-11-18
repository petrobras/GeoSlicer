import os
from pathlib import Path
import shutil
import multiprocessing

from commons.slicer import helpers
import slicer
import numpy as np
import qt
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import (
    load_project,
    process_events,
    wait_cli_to_finish,
    waitCondition,
    getNodeName,
)
from commons.slicer.helpers import tryGetNode, createLabelmapInput, getSourceVolume
from commons.slicer import metadata

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
MULTISCALE_PROJECT_FILE = TEST_RESOURCES_DIR / "MULTISCALE" / "MULTISCALE.mrml"


class MultiScaleTest(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = {
            # input
            "trainingImageInput": self.find_widget("Training Image Segmentation ComboBox"),
            "trainingSegmentList": self.find_widget("Training Image Segment List"),
            "hardDataInput": self.find_widget("Hard Data Segmentation ComboBox"),
            "hardDataSegmentList": self.find_widget("Hard Data Segment List"),
            "tiResolutionText": self.find_widget("Training Image Resolution Text"),
            "hdResolutionText": self.find_widget("Hard Data Image Resolution Text"),
            "maskResolutionText": self.find_widget("Mask Image Resolution Text"),
            "maskInput": self.find_widget("Mask Segmentation ComboBox"),
            "maskSegmentList": self.find_widget("Mask Segment List"),
            "depthTopSpinBox": self.find_widget("depthTopSpinBox"),
            "depthBottomSpinBox": self.find_widget("depthBottomSpinBox"),
            "previewOptionsWidget": self.find_widget("previewOptionsWidget"),
            "previewDimensionSpinBox": self.find_widget("previewDimensionSpinBox"),
            "previewButton": self.find_widget("previewButton"),
            "enableWrapCheckBox": self.find_widget("enableWrapCheckBox"),
            "continuousDataCheckBox": self.find_widget("continuousDataCheckBox"),
            "resampleCheckBox": self.find_widget("resampleCheckBox"),
            # parameters
            "finalImageResolution": [
                self.find_widget("finalImageResolution_0"),
                self.find_widget("finalImageResolution_1"),
                self.find_widget("finalImageResolution_2"),
            ],
            "finalImageSize": [
                self.find_widget("finalImageSize_0"),
                self.find_widget("finalImageSize_1"),
                self.find_widget("finalImageSize_2"),
            ],
            "resampleContainer": self.find_widget("resample Container"),
            "trainingImageResampleWidget": self.find_widget("Training Image Resample Widget"),
            "hardDataResampleWidget": self.find_widget("Hard Data Resample Widget"),
            "maskResampleWidget": self.find_widget("Mask Resample Widget"),
            "ncond": self.find_widget("conditioningsNumber"),
            "nreal": self.find_widget("realizationsNumber"),
            "maxIterationsSpinBox": self.find_widget("maxIterationsValue"),
            "randomSeedValue": self.find_widget("randomSeedValue"),
            "colocateDimension": self.find_widget("colocateDimension"),
            "maxSearchRadius": self.find_widget("maxSearchRadius"),
            "distanceMax": self.find_widget("distanceMax"),
            "distancePower": self.find_widget("distancePower"),
            # Output
            "outputPrefix": self.find_widget("outputPrefix"),
            "saveAsSequence": self.find_widget("saveAsSequence"),
            "saveSingle": self.find_widget("saveSingle"),
            "saveAsVolume": self.find_widget("saveAsVolume"),
            "saveAsFile": self.find_widget("saveAsFile"),
            "fileDirectory": self.find_widget("fileDirectory"),
            "runButton": self.find_widget("runButton"),
            "MPSTimeLabel": self.find_widget("MPS Time QLabel"),
        }

    def tear_down(self):
        pass

    def default_test_config(self):
        ncond = self._widgets["ncond"]
        nreal = self._widgets["nreal"]
        maxIterationsSpinBox = self._widgets["maxIterationsSpinBox"]

        load_project(project_file_path=MULTISCALE_PROJECT_FILE)

        nreal.value = 3
        ncond.value = 3
        maxIterationsSpinBox.value = 100

    def run_parallel(self):
        runButton = self._widgets["runButton"]
        assert runButton.enabled, "The 'Run' button is disabled"
        runButton.clicked()
        waitCondition(lambda: self._module_widget.logic.cliNode is not None)
        cliNode = self._module_widget.logic.cliNode
        assert cliNode is not None
        wait_cli_to_finish(cliNode)
        assert cliNode.GetStatusString() == "Completed", f"Error: {cliNode.GetErrorText()}"

        return cliNode

    def test_interface_default_values(self):
        assert self._widgets["hardDataInput"].currentNode() is None
        assert self._widgets["trainingImageInput"].currentNode() is None
        assert self._widgets["tiResolutionText"].text == "0 x 0 x 0 (mm)"
        assert self._widgets["hdResolutionText"].text == "0 x 0 x 0 (mm)"
        assert self._widgets["maskResolutionText"].text == "0 x 0 x 0 (mm)"
        assert self._widgets["maskInput"].currentNode() is None
        assert self._widgets["depthTopSpinBox"].value == 0
        assert self._widgets["depthBottomSpinBox"].value == 0
        assert self._widgets["previewDimensionSpinBox"].value == 122
        assert self._widgets["previewButton"].enabled is False
        assert self._widgets["enableWrapCheckBox"].enabled is False
        assert self._widgets["enableWrapCheckBox"].isChecked() is False
        assert self._widgets["continuousDataCheckBox"].enabled
        assert self._widgets["continuousDataCheckBox"].isChecked() is False
        assert [box.text for box in self._widgets["finalImageResolution"]] == ["", "", ""]
        assert [box.value for box in self._widgets["finalImageSize"]] == [1, 1, 1]
        assert self._widgets["ncond"].value == 16
        assert self._widgets["nreal"].value == multiprocessing.cpu_count() - 1
        assert self._widgets["maxIterationsSpinBox"].value == 1000
        assert self._widgets["maxIterationsSpinBox"].enabled
        assert self._widgets["randomSeedValue"].value == 0
        assert self._widgets["colocateDimension"].currentText == "X"
        assert self._widgets["maxSearchRadius"].value == 10000.000
        assert self._widgets["distanceMax"].value == 0
        assert self._widgets["distancePower"].value == 0
        assert self._widgets["outputPrefix"].text == ""
        assert self._widgets["saveSingle"].isChecked()
        assert self._widgets["saveAsVolume"].isChecked() is False
        assert self._widgets["saveAsSequence"].isChecked()
        assert self._widgets["saveAsFile"].isChecked() is False
        assert self._widgets["fileDirectory"].enabled is False
        assert self._widgets["runButton"].enabled is False
        assert self._widgets["MPSTimeLabel"].visible is False

    def test_training_image_as_hard_data_should_return_training_image(self):
        outputPrefix = self._widgets["outputPrefix"]
        hardDataInput = self._widgets["hardDataInput"]
        trainingImageInput = self._widgets["trainingImageInput"]

        self.default_test_config()

        trainingImageNode = tryGetNode("TI_label")
        assert trainingImageNode is not None
        trainingImageInput.setCurrentNode(trainingImageNode)
        hardDataInput.setCurrentNode(trainingImageNode)

        outputPrefix.text = "test_output"

        metadata.Metadata(trainingImageNode)["DummyMetadataTest"] = "test_value"

        self.run_parallel()
        process_events()

        lastRealizationNode = tryGetNode(outputPrefix.text)
        assert lastRealizationNode is not None

        lastRealizationArray = slicer.util.arrayFromVolume(lastRealizationNode)
        trainingImageArray = slicer.util.arrayFromVolume(trainingImageNode)

        assert np.allclose(lastRealizationArray, trainingImageArray)
        assert metadata.Metadata(lastRealizationNode)["DummyMetadataTest"] == "test_value"

        # assert metadata propagation TODO (AM-11) Will we use the Metadata for subject hierarchy attributes also?
        assert metadata.Metadata(lastRealizationNode)["DummyMetadataTest"] == "test_value"

    def test_set_rseed_should_always_give_same_results(self):
        outputPrefix = self._widgets["outputPrefix"]
        hardDataInput = self._widgets["hardDataInput"]
        trainingImageInput = self._widgets["trainingImageInput"]
        nreal = self._widgets["nreal"]
        randomSeedValue = self._widgets["randomSeedValue"]
        saveAsVolume = self._widgets["saveAsVolume"]
        saveAsSequence = self._widgets["saveAsSequence"]

        self.default_test_config()

        trainingImageNode = tryGetNode("TI_label")
        assert trainingImageNode is not None
        trainingImageInput.setCurrentNode(trainingImageNode)

        hardDataNode = tryGetNode("HD_seg")
        assert hardDataNode is not None
        hardDataInput.setCurrentNode(hardDataNode)

        randomSeedValue.value = 1
        saveAsVolume.setChecked(qt.Qt.Checked)
        saveAsSequence.setChecked(qt.Qt.Unchecked)
        basePrefixText = "test_output"

        outputPrefix.text = f"{basePrefixText}_first"
        self.run_parallel()
        process_events()

        outputPrefix.text = f"{basePrefixText}_second"
        self.run_parallel()
        process_events()

        for i in range(nreal.value):
            firstRealization = tryGetNode(f"{basePrefixText}_first_r{i}")
            assert firstRealization is not None
            firstRealizationArray = slicer.util.arrayFromVolume(firstRealization)

            secondRealization = tryGetNode(f"{basePrefixText}_second_r{i}")
            assert secondRealization is not None
            secondRealizationArray = slicer.util.arrayFromVolume(secondRealization)

            assert np.allclose(firstRealizationArray, secondRealizationArray)

    def test_save_realizations_as_volumes_and_file(self):
        outputPrefix = self._widgets["outputPrefix"]
        hardDataInput = self._widgets["hardDataInput"]
        trainingImageInput = self._widgets["trainingImageInput"]
        nreal = self._widgets["nreal"]
        saveAsVolume = self._widgets["saveAsVolume"]
        saveAsSequence = self._widgets["saveAsSequence"]
        saveAsFile = self._widgets["saveAsFile"]
        fileDirectory = self._widgets["fileDirectory"]

        self.default_test_config()

        trainingImageNode = tryGetNode("TI_label")
        assert trainingImageNode is not None
        trainingImageInput.setCurrentNode(trainingImageNode)

        hardDataNode = tryGetNode("HD_seg")
        assert hardDataNode is not None
        hardDataInput.setCurrentNode(hardDataNode)

        saveAsVolume.setChecked(qt.Qt.Checked)
        saveAsFile.setChecked(qt.Qt.Checked)
        saveAsSequence.setChecked(qt.Qt.Unchecked)

        outputPath = TEST_RESOURCES_DIR / "Outputs"
        outputPath.mkdir(exist_ok=True)

        fileDirectory.directory = outputPath
        outputPrefix.text = "test_output"

        metadata.Metadata(getSourceVolume(hardDataNode))["DummyMetadataTest"] = "test_value"

        self.run_parallel()

        process_events()

        for i in range(nreal.value):
            assert tryGetNode(f"{outputPrefix.text}_r{i}") is not None
            # assert metadata propagation TODO (AM-11) Will we use the Metadata for subject hierarchy attributes also?
            assert metadata.Metadata(tryGetNode(f"{outputPrefix.text}_r{i}"))["DummyMetadataTest"] == "test_value"

        assert len([name for name in os.listdir(outputPath) if name[-4:] == ".tif"]) == nreal.value

        shutil.rmtree(outputPath, ignore_errors=True)

    def test_hard_data_update_rules(self):
        hardDataInput = self._widgets["hardDataInput"]
        previewOptionsWidget = self._widgets["previewOptionsWidget"]
        enableWrapCheckBox = self._widgets["enableWrapCheckBox"]
        continuousDataCheckBox = self._widgets["continuousDataCheckBox"]

        self.default_test_config()

        nodeList = ["HD_seg", "Imagelog_volume", "Imagelog_discrete_seg"]
        previewVisibility = [True, False, True]
        previewEnabled = [False, True, True]
        wrapEnabled = [False, True, True]
        continousChecked = [False, True, False]
        resolutionsList = ["0.235 x 0.235 x 0.235", "5.000 x 0.480 x 10.000", "5.000 x 0.480 x 10.000"]

        for index in range(3):
            hardDataNode = tryGetNode(nodeList[index])
            assert hardDataNode is not None
            hardDataInput.setCurrentNode(hardDataNode)

            assert self._widgets["hdResolutionText"].text == f"{resolutionsList[index]} (mm)", (
                f"Expected {resolutionsList[index]} (mm), got {self._widgets['hdResolutionText'].text} instead"
            )
            assert previewOptionsWidget.visible is previewVisibility[index], (
                f"Node {nodeList[index]}: Expected {previewVisibility[index]}, got {previewOptionsWidget.visible}"
            )
            assert previewOptionsWidget.enabled is previewEnabled[index], (
                f"Node {nodeList[index]}: Expected {previewEnabled[index]}, got {previewOptionsWidget.enabled}"
            )
            assert enableWrapCheckBox.enabled is wrapEnabled[index], (
                f"Node {nodeList[index]}: Expected {wrapEnabled[index]}, got {enableWrapCheckBox.enabled}"
            )
            assert continuousDataCheckBox.isChecked() is continousChecked[index], (
                f"Node {nodeList[index]}: Expected {continousChecked[index]}, got {continuousDataCheckBox.isChecked()}"
            )

    def test_verify_on_imagelog_change_and_generate_preview(self):
        hardDataInput = self._widgets["hardDataInput"]
        hardDataSegmentList = self._widgets["hardDataSegmentList"]
        depthTopSpinBox = self._widgets["depthTopSpinBox"]
        depthBottomSpinBox = self._widgets["depthBottomSpinBox"]
        previewButton = self._widgets["previewButton"]

        self.default_test_config()

        hardDataNode = tryGetNode("Imagelog_discrete_seg")
        referenceNode = tryGetNode("Imagelog_volume")
        assert hardDataNode is not None
        assert referenceNode is not None
        hardDataInput.setCurrentNode(hardDataNode)

        start = round(-referenceNode.GetOrigin()[2] / 1000, 5)
        end = round(start + referenceNode.GetImageData().GetDimensions()[2] * referenceNode.GetSpacing()[2] / 1000, 5)

        assert hardDataSegmentList.count == 3
        assert depthTopSpinBox.value == start
        assert depthBottomSpinBox.value == end

        previewButton.clicked()
        process_events()

        previewLabelmap = tryGetNode("previewLabelmap")
        assert previewLabelmap is not None
        previewSegmentation = tryGetNode("previewSegmentation")
        assert previewSegmentation is not None

    def test_verify_save_as_sequence(self):
        outputPrefix = self._widgets["outputPrefix"]
        hardDataInput = self._widgets["hardDataInput"]
        trainingImageInput = self._widgets["trainingImageInput"]
        nreal = self._widgets["nreal"]
        saveAsSequence = self._widgets["saveAsSequence"]

        self.default_test_config()

        trainingImageNode = tryGetNode("TI_label")
        assert trainingImageNode is not None
        trainingImageInput.setCurrentNode(trainingImageNode)

        hardDataNode = tryGetNode("HD_seg")
        assert hardDataNode is not None
        hardDataInput.setCurrentNode(hardDataNode)

        saveAsSequence.setChecked(qt.Qt.Checked)

        self.run_parallel()
        process_events()

        proxyNode = tryGetNode(f"{outputPrefix.text}_proxy")
        assert proxyNode is not None
        sequenceNode = tryGetNode(f"{outputPrefix.text}_sequence")
        assert sequenceNode is not None
        browserNode = tryGetNode(f"{outputPrefix.text}_browser")
        assert browserNode is not None
        assert browserNode.GetNumberOfItems() == nreal.value

    def test_imagelog_input_results(self):
        trainingImageInput = self._widgets["trainingImageInput"]
        hardDataInput = self._widgets["hardDataInput"]
        finalImageResolution = self._widgets["finalImageResolution"]
        wrapCheckBox = self._widgets["enableWrapCheckBox"]
        saveAsSequence = self._widgets["saveAsSequence"]
        outputPrefix = self._widgets["outputPrefix"]

        self.default_test_config()

        trainingImageNode = tryGetNode("TI_label")
        assert trainingImageNode is not None
        trainingImageInput.setCurrentNode(trainingImageNode)

        hardDataNode = tryGetNode("Imagelog_discrete_seg")
        assert hardDataNode is not None
        hardDataInput.setCurrentNode(hardDataNode)

        wrapCheckBox.setChecked(qt.Qt.Checked)

        finalImageResolution[0].text = 9
        finalImageResolution[1].text = 9
        finalImageResolution[2].text = 10

        saveAsSequence.setChecked(qt.Qt.Unchecked)

        outputPrefix.text = "test_result"

        metadata.Metadata(helpers.getSourceVolume(hardDataNode))["DummyMetadataTest"] = (
            "test_value"  # tryGetNode('Imagelog_volume')
        )

        self.run_parallel()
        process_events()

        result = tryGetNode("test_result")
        assert result is not None
        assert result.GetSpacing() == (9, 9, 10)

        # assert metadata propagation TODO (AM-11) Will we use the Metadata for subject hierarchy attributes also?
        assert metadata.Metadata(result)["DummyMetadataTest"] == "test_value"

    def test_2D_continuous_simulation(self):
        trainingImageInput = self._widgets["trainingImageInput"]
        hardDataInput = self._widgets["hardDataInput"]
        trainingSegmentList = self._widgets["trainingSegmentList"]
        hardDataSegmentList = self._widgets["hardDataSegmentList"]
        continuousDataCheckBox = self._widgets["continuousDataCheckBox"]
        saveAsSequence = self._widgets["saveAsSequence"]
        outputPrefix = self._widgets["outputPrefix"]

        self.default_test_config()

        nodesList = ["Imagelog_inpaint_seg", "Imagelog_flip_mask"]
        referecesList = ["Imagelog_inpaint_volume", "Imagelog_flip_volume"]
        nodesShapes = [(100, 1, 180), (100, 1, 50)]

        saveAsSequence.setChecked(qt.Qt.Unchecked)

        for node in range(len(nodesList)):
            imagelogSegmentation = tryGetNode(nodesList[node])
            assert imagelogSegmentation is not None

            trainingImageInput.setCurrentNode(imagelogSegmentation)
            hardDataInput.setCurrentNode(imagelogSegmentation)

            trainingSegmentList.item(0).setCheckState(qt.Qt.Unchecked)
            hardDataSegmentList.item(0).setCheckState(qt.Qt.Unchecked)

            continuousDataCheckBox.setChecked(qt.Qt.Checked)

            labelmap, _ = createLabelmapInput(imagelogSegmentation, "")
            maskArray = slicer.util.arrayFromVolume(labelmap)

            assert maskArray.shape == nodesShapes[node], f"Expected shape: {nodesShapes[node]}, got: {maskArray.shape}"

            outputPrefix.text = f"test_result_{nodesList[node]}"

            metadata.Metadata(tryGetNode(referecesList[node]))["DummyMetadataTest"] = "test_value"

            self.run_parallel()

            process_events()

            result = tryGetNode(outputPrefix.text)
            assert result is not None

            referenceArray = slicer.util.arrayFromVolume(tryGetNode(referecesList[node]))

            assert np.allclose(
                referenceArray[np.isin(maskArray, [2])],
                slicer.util.arrayFromVolume(result)[np.isin(maskArray, [2])],
                0.05,
            ), f"Expected {True}, but got {False}"
            assert not np.allclose(
                referenceArray[np.isin(maskArray, [1])],
                slicer.util.arrayFromVolume(result)[np.isin(maskArray, [1])],
                0.05,
            )

            # assert metadata propagation TODO (AM-11) Will we use the Metadata for subject hierarchy attributes also?
            assert metadata.Metadata(result)["DummyMetadataTest"] == "test_value"
            # TODO (AM-11) Will we use the Metadata for subject hierarchy attributes also?

    def test_mask_simulation(self):
        trainingImageInput = self._widgets["trainingImageInput"]
        maskInput = self._widgets["maskInput"]
        maskSegmentList = self._widgets["maskSegmentList"]
        continuousDataCheckBox = self._widgets["continuousDataCheckBox"]
        saveAsSequence = self._widgets["saveAsSequence"]
        outputPrefix = self._widgets["outputPrefix"]

        self.default_test_config()

        tiSegmentation = tryGetNode("Mask_TI_seg")
        assert tiSegmentation is not None
        maskSegmentation = tryGetNode("Mask_seg")
        assert maskSegmentation is not None

        trainingImageInput.setCurrentNode(tiSegmentation)
        maskInput.setCurrentNode(maskSegmentation)

        assert self._widgets["tiResolutionText"].text == "0.235 x 0.235 x 0.235 (mm)"
        assert self._widgets["maskResolutionText"].text == "0.235 x 0.235 x 0.235 (mm)"

        maskSegmentList.item(1).setCheckState(qt.Qt.Checked)

        saveAsSequence.setChecked(qt.Qt.Unchecked)

        labelmap, _ = createLabelmapInput(maskSegmentation, "")
        maskArray = slicer.util.arrayFromVolume(labelmap)

        for i in range(2):
            outputPrefix.text = f"mask_test_result_{i}"

            metadata.Metadata(helpers.getSourceVolume(maskSegmentation))["DummyMetadataTest"] = (
                "test_value"  # why not tiSegmentation?
            )

            self.run_parallel()

            result = tryGetNode(outputPrefix.text)
            assert result is not None

            resultArray = slicer.util.arrayFromVolume(result)

            adjustValue = 0

            if not self._widgets["continuousDataCheckBox"].isChecked():
                assert isinstance(result, slicer.vtkMRMLLabelMapVolumeNode), (
                    f"Expected output to be vtkMRMLLabelMapVolumeNode, but got {result.GetClassName()}"
                )
                uniqueValues = np.unique(resultArray)
                assert len(uniqueValues) == 4, f"Expected 4 unique values, but got {len(uniqueValues)}"
                adjustValue = 1

            else:
                assert isinstance(result, slicer.vtkMRMLScalarVolumeNode)

            assert not (maskArray[np.isin(maskArray, [2])] == resultArray[np.isin(maskArray, [2])]).all()
            assert (maskArray[np.isin(maskArray, [1])] + 2 * adjustValue == resultArray[np.isin(maskArray, [1])]).all()
            assert (maskArray[np.isin(maskArray, [3])] + 1 * adjustValue == resultArray[np.isin(maskArray, [3])]).all()

            continuousDataCheckBox.setChecked(qt.Qt.Checked)

            # assert metadata propagation TODO (AM-11) Will we use the Metadata for subject hierarchy attributes also?
            assert metadata.Metadata(result)["DummyMetadataTest"] == "test_value"

    def test_resample_simulation(self):
        trainingImageInput = self._widgets["trainingImageInput"]
        hardDataInput = self._widgets["hardDataInput"]
        wrapCheckBox = self._widgets["enableWrapCheckBox"]
        finalImageResolution = self._widgets["finalImageResolution"]
        finalImageSize = self._widgets["finalImageSize"]
        resampleCheckBox = self._widgets["resampleCheckBox"]
        resampleContainer = self._widgets["resampleContainer"]
        tiResampleWidget = self._widgets["trainingImageResampleWidget"]
        hdResampleWidget = self._widgets["hardDataResampleWidget"]
        outputPrefix = self._widgets["outputPrefix"]

        self.default_test_config()

        hardDataNode = tryGetNode("Imagelog_discrete_seg")
        referenceNode = tryGetNode("Imagelog_volume")
        assert hardDataNode is not None, "Expected a node, got None instead"
        hardDataInput.setCurrentNode(hardDataNode)

        trainingImageArray = (np.random.randint(3, size=(50, 50, 50)) + 1).astype(np.uint8)
        trainingImageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "Training Image")
        modified = trainingImageNode.StartModify()
        trainingImageNode.CreateDefaultDisplayNodes()
        slicer.util.updateVolumeFromArray(trainingImageNode, trainingImageArray)
        trainingImageNode.SetSpacing(8, 9, 10)
        trainingImageNode.EndModify(modified)

        trainingImageInput.setCurrentNode(trainingImageNode)

        metadata.Metadata(referenceNode)["DummyMetadataTest"] = "test_value"

        gridResolution = [7, 7, 7]
        gridDimension = [41, 41, 143]

        for lineEdit in finalImageResolution:
            lineEdit.text = 7

        resampleCheckBox.setChecked(qt.Qt.Checked)
        wrapCheckBox.setChecked(qt.Qt.Checked)
        process_events()

        assert resampleContainer.visible, f"Expected True, got {resampleContainer.visible} intead"
        assert [spinBox.value for spinBox in finalImageSize] == gridDimension, (
            f"Expected {gridDimension}, got {[spinBox.value for spinBox in finalImageSize]} instead"
        )

        hdSpacing = referenceNode.GetSpacing()
        hdDimensions = referenceNode.GetImageData().GetDimensions()
        tiSpacing = trainingImageNode.GetSpacing()
        tiDimensions = trainingImageNode.GetImageData().GetDimensions()

        for dim in range(3):
            spacing = hdSpacing[dim] if dim == 1 else 7
            assert np.allclose(hdResampleWidget.dimensionsGroup[dim][0].value, spacing), (
                f"Expected {spacing}, got {hdResampleWidget.dimensionsGroup[dim][0].value}"
            )
            expectedSize = (hdSpacing[dim] * hdDimensions[dim]) / spacing + 0.5
            expectedSizeText = f"{int(expectedSize)} px"
            assert hdResampleWidget.dimensionsGroup[dim][1].text == expectedSizeText, (
                f"expected {expectedSizeText}, got {hdResampleWidget.dimensionsGroup[dim][1].text}"
            )
            ratio = round(hdDimensions[dim] / expectedSize, 2)
            assert hdResampleWidget.dimensionsGroup[dim][2].value == ratio, (
                f"Expected {ratio}, got {hdResampleWidget.dimensionsGroup[dim][2].value}"
            )

        for dim in range(3):
            spacing = 7
            assert tiResampleWidget.dimensionsGroup[dim][0].value == spacing, (
                f"Expected {spacing}, got {tiResampleWidget.dimensionsGroup[dim][0].value}"
            )
            expectedSize = (tiSpacing[dim] * tiDimensions[dim]) / spacing + 0.5
            expectedSizeText = f"{int(expectedSize)} px"
            assert tiResampleWidget.dimensionsGroup[dim][1].text == expectedSizeText, (
                f"expected {expectedSizeText}, got {tiResampleWidget.dimensionsGroup[dim][2].text}"
            )
            ratio = round(tiDimensions[dim] / expectedSize, 2)
            assert tiResampleWidget.dimensionsGroup[dim][2].value == ratio, (
                f"Expected {ratio}, got {tiResampleWidget.dimensionsGroup[dim][2].value}"
            )

        outputPrefix.text = "output"

        self.run_parallel()

        outputNode = tryGetNode(outputPrefix.text)
        assert outputNode is not None
        assert list(outputNode.GetSpacing()) == gridResolution, (
            f"Expected {gridDimension}, got {list(outputNode.GetSpacing())}"
        )
        assert list(outputNode.GetImageData().GetDimensions()) == gridDimension, (
            f"Expected {gridDimension}, got {list(outputNode.GetImageData().GetDimensions())}"
        )

        # assert metadata propagation TODO (AM-11) Will we use the Metadata for subject hierarchy attributes also?
        assert metadata.Metadata(outputNode)["DummyMetadataTest"] == "test_value"

    def test_resample_mask_simulation(self):
        trainingImageInput = self._widgets["trainingImageInput"]
        maskInput = self._widgets["maskInput"]
        maskSegmentList = self._widgets["maskSegmentList"]
        finalImageResolution = self._widgets["finalImageResolution"]
        finalImageSize = self._widgets["finalImageSize"]
        resampleCheckBox = self._widgets["resampleCheckBox"]
        resampleContainer = self._widgets["resampleContainer"]
        outputPrefix = self._widgets["outputPrefix"]

        self.default_test_config()

        trainingImageArray = (np.random.randint(3, size=(50, 50, 50)) + 1).astype(np.uint8)
        trainingImageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "Training Image")
        modified = trainingImageNode.StartModify()
        trainingImageNode.CreateDefaultDisplayNodes()
        slicer.util.updateVolumeFromArray(trainingImageNode, trainingImageArray)
        trainingImageNode.SetSpacing(8, 9, 10)
        trainingImageNode.EndModify(modified)
        process_events()

        trainingImageInput.setCurrentNode(trainingImageNode)

        maskImageArray = np.zeros((50, 50, 50)).astype(np.uint8) + 1
        maskImageArray[25:, 25:, 25:] += 1
        maskImageNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "Mask")
        modified = maskImageNode.StartModify()
        maskImageNode.CreateDefaultDisplayNodes()
        slicer.util.updateVolumeFromArray(maskImageNode, maskImageArray)
        maskImageNode.SetSpacing(10, 10, 10)
        maskImageNode.EndModify(modified)

        maskInput.setCurrentNode(maskImageNode)
        maskSegmentList.item(1).setCheckState(qt.Qt.Checked)

        gridResolution = [20, 20, 20]
        gridDimension = [25, 25, 25]

        resampleCheckBox.setChecked(qt.Qt.Checked)
        process_events()

        for lineEdit in finalImageResolution:
            lineEdit.text = 20
        process_events()

        assert resampleContainer.visible, f"Expected True, got {resampleContainer.visible} intead"
        assert [spinBox.value for spinBox in finalImageSize] == gridDimension, (
            f"Expected {gridDimension}, got {[spinBox.value for spinBox in finalImageSize]} instead"
        )

        outputPrefix.text = "output"

        metadata.Metadata(maskImageNode)["DummyMetadataTest"] = "test_value"

        assert trainingImageInput.currentNode() == trainingImageNode, (
            f"Training Image Input current node is {getNodeName(trainingImageInput.currentNode())}"
        )
        assert maskInput.currentNode() == maskImageNode, (
            f"Mask Input current bode is {getNodeName(maskInput.currentNode())}"
        )
        self.run_parallel()

        outputNode = tryGetNode(outputPrefix.text)
        assert outputNode is not None
        assert list(outputNode.GetSpacing()) == gridResolution, (
            f"Expected {gridDimension}, got {list(outputNode.GetSpacing())}"
        )
        assert list(outputNode.GetImageData().GetDimensions()) == gridDimension, (
            f"Expected {gridDimension}, got {list(outputNode.GetImageData().GetDimensions())}"
        )

        # assert metadata propagation TODO (AM-11) Will we use the Metadata for subject hierarchy attributes also?
        assert metadata.Metadata(outputNode)["DummyMetadataTest"] == "test_value"
