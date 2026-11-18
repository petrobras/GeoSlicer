import os
import slicer
import json
import re
import tempfile

from unittest.mock import patch

from commons.slicer.ai_models.defs import get_model_download_links
from commons.slicer.ui import DirOrFileWidget
from commons.slicer_utils import LTracePluginTest
from commons.slicer.tests.utils import check_for_message_box
from commons.slicer.widget.filtered_node_combo_box import FilteredNodeComboBox
from commons.slicer.widget.trained_model_selector import TrainedModelSelector
from commons.slicer.ai_models.widget import AIModelsPathModel
from pathlib import Path


class WidgetsTest(LTracePluginTest):
    def test_dir_or_file_widget_default_path(self):
        slicer.app.settings().remove("TestDirOrFileWidget/dialogDirectory")
        widget = DirOrFileWidget(settingKey="TestDirOrFileWidget/dialogDirectory")
        this_file = Path(__file__)
        this_dir = this_file.parent
        this_file = this_file.as_posix()
        this_dir = this_dir.as_posix()

        assert widget.getDefaultPath() == "", f"Expected an empty string, but got {widget.getDefaultPath()}"

        widget.pathLineEdit.text = this_dir
        widget.pathLineEdit.editingFinished.emit()
        assert widget.getDefaultPath() == this_dir, f"Expected  {this_dir} but got {widget.getDefaultPath()}"

        widget.path = this_file
        assert widget.pathLineEdit.text == this_file, f"Expected {this_file} but got {widget.pathLineEdit.text}"
        assert widget.getDefaultPath() == this_file, f"Expected  {this_file} but got {widget.getDefaultPath()}"

        does_not_exist = this_dir + "/does_not_exist"
        widget.path = does_not_exist
        assert widget.pathLineEdit.text == does_not_exist, (
            f"Expected {does_not_exist} but got {widget.pathLineEdit.text}"
        )
        assert widget.getDefaultPath() == this_file, f"Expected  {this_file} but got {widget.getDefaultPath()}"

    def test_dir_or_file_widget_unreachable_default_path(self):
        """A persisted path on an unreachable location (os.stat raising OSError,
        e.g. a full or offline network drive) must not crash construction and
        must not be auto-restored."""
        settingKey = "TestDirOrFileWidget/dialogDirectory"
        unreachable = "Z:/Microtomografia/out_of_space_dir"
        slicer.app.settings().setValue(settingKey, unreachable)

        real_stat = os.stat

        def fake_stat(path, *args, **kwargs):
            if unreachable in str(path).replace("\\", "/"):
                raise OSError(112, "No space left on device")
            return real_stat(path, *args, **kwargs)

        try:
            with patch("os.stat", fake_stat):
                widget = DirOrFileWidget(settingKey=settingKey)
                assert widget.getDefaultPath() == "", f"Expected empty, got {widget.getDefaultPath()}"
                assert widget.path == "", f"Expected empty, got {widget.path}"
        finally:
            slicer.app.settings().remove(settingKey)

    def test_filtered_node_combobox_add_item(self):
        validNodes = []
        validNodes.append(slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "TEST_TABLE"))
        validNodes.append(slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "TEST_SCALAR"))
        validNodes.append(slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "TEST_LABELMAP"))

        invalidNodes = []
        invalidNodes.append(slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "TEST_SEGMENTATION"))

        comboBox = FilteredNodeComboBox(
            nodeTypes=[
                "vtkMRMLScalarVolumeNode",
                "vtkMRMLTableNode",
                "vtkMRMLLabelMapVolumeNode",
            ],
        )

        # Check if nodes create before the combobox are added correctly
        assert comboBox.count == len(validNodes) + 1, (
            f"Expected {len(validNodes) + 1} items, but got {comboBox.count}"
        )  # First item is None

        for index in range(1, comboBox.count):
            assert comboBox.itemText(index) in [node.GetName() for node in validNodes], (
                f"Expected {comboBox.itemText(index)} to be in {[node.GetName() for node in validNodes]}"
            )
            assert comboBox.itemText(index) not in [node.GetName() for node in invalidNodes], (
                f"Expected {comboBox.itemText(index)} to NOT be in {[node.GetName() for node in invalidNodes]}"
            )

        validNodes.append(slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "TEST_SCALAR_2"))
        validNodes.append(slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "TEST_LABELMAP_2"))
        invalidNodes.append(slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "TEST_MODEL"))

        # Check if observers were called and added new itens after instacing the combobox
        assert comboBox.count == len(validNodes) + 1, (
            f"Expected {len(validNodes) + 1} items, but got {comboBox.count}"
        )  # First item is None

        for index in range(1, comboBox.count):
            assert comboBox.itemText(index) in [node.GetName() for node in validNodes]
            assert comboBox.itemText(index) not in [node.GetName() for node in invalidNodes]

    def test_ai_model_selector(self):
        aiModels = AIModelsPathModel()
        selector = TrainedModelSelector("testEnv")

        assert selector.currentData is None

        modelTitle = "Model Title"
        modelName = "testmodel"

        with tempfile.TemporaryDirectory() as tempDir:
            tempDirPath = Path(tempDir)
            tagPath = tempDirPath / "testEnv"
            tagPath.mkdir()
            modelPath = tagPath / modelName
            modelPath.mkdir()

            pthPath = modelPath / "model.pth"
            pthPath.touch()

            metadata = modelPath / "meta.json"
            metaDataData = {
                "title": modelTitle,
            }
            with open(metadata, "w") as f:
                json.dump(metaDataData, f)

            aiModels.addPath(str(tempDirPath))

            assert selector.count == 1
            assert selector.currentText == modelTitle, f"Expected {modelTitle}, but got {selector.currentText}"
            assert selector.currentData == modelPath, f"Expected {modelPath}, but got {selector.currentData}"
            assert selector.getSelectedModelPth() == pthPath.as_posix(), (
                f"Expected {pthPath}, but got {selector.getSelectedModelPth()}"
            )
            assert selector.getSelectedModelMetadata() == metaDataData, (
                f"Expected {metadata}, but got {selector.getSelectedModelMetadata()}"
            )

        aiModels.removePath(str(tempDirPath))
        assert selector.count == 1
        assert selector.currentData is None

    def test_model_versioning(self):
        selector = TrainedModelSelector("testEnv")

        modelLinksDict = get_model_download_links()
        linksListHtml = ""
        pluralSuffix = "s" if len(modelLinksDict) > 1 else ""

        for model in modelLinksDict:
            versionPattern = r"-\d+\.\d+\.\d+\.zip"
            versionMatch = re.search(versionPattern, modelLinksDict[model])

            versionedModel = model[:]
            if versionMatch:
                versionedModel += f" v{Path(versionMatch.group()).stem[1:]}"
            else:
                versionedModel += " (original)"

            linksListHtml += f'<li><a href="{modelLinksDict[model]}">{versionedModel}</a></<li>'

        messageBoxText = f"""<p>The current version of GeoSlicer requires a specific AI model package for this task. 
            The compatible package version{pluralSuffix} can be found in the following
            link{pluralSuffix}:</p>
                {linksListHtml}
            <p>Make sure to download the appropriate package and add its path by clicking on
            "Load Models" below. Remove older versions in order to avoid
            duplicates in other tasks.</p>
        """

        with check_for_message_box(message=messageBoxText):
            selector.triggerMissingModel()
