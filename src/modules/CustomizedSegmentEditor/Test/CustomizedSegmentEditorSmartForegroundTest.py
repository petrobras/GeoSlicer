import numpy as np
import slicer

from pathlib import Path
from commons.slicer import helpers
from commons.slicer.application_observables import ApplicationObservables
from commons.assets_utils import get_model_by_name, get_pth
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import (
    load_project,
    save_project,
    wait_cli_to_finish,
    process_events,
    check_for_message_box,
)


RESOURCES = Path(__file__).parent / "Resources"
SMART_FOREGROUND_2D_RAW_PROJECT_FILE = RESOURCES / "SMART_FOREGROUND_2D_RAW" / "SMART_FOREGROUND_2D_RAW.mrml"
SMART_FOREGROUND_2D_PROJECT_FILE = RESOURCES / "SMART_FOREGROUND_2D" / "SMART_FOREGROUND_2D.mrml"
SMART_FOREGROUND_3D_RAW_PROJECT_FILE = RESOURCES / "SMART_FOREGROUND_3D_RAW" / "SMART_FOREGROUND_3D_RAW.mrml"
SMART_FOREGROUND_3D_PROJECT_FILE = RESOURCES / "SMART_FOREGROUND_3D" / "SMART_FOREGROUND_3D.mrml"


class CustomizedSegmentEditorSmartForegroundTest(LTracePluginTest):
    def post_setup(self) -> None:
        """Test case setup handler, applied before reloding the widgets"""
        self.__widgets = {
            "smartForegroundFillInsideButton": self.find_widget(name="Smart Foreground Fill Inside Button"),
            "smartForegroundEraseOutsideButton": self.find_widget(name="Smart Foreground Erase Outside Button"),
            "smartForegroundSplitLabel": self.find_widget(name="Smart Foreground Split Fragments Section Label"),
            "smartForegroundSplitCheckbox": self.find_widget(name="Smart Foreground Split Checkbox"),
            "smartForegroundSplitAllButton": self.find_widget(name="Smart Foreground Split All Button"),
            "smartForegroundFragFilterButton": self.find_widget(name="Smart Foreground Fragments Filter Button"),
            "smartForegroundFragFilterInput": self.find_widget("Smart Foreground Fragments Filter Input"),
            "smartForegroundAnnotsLabel": self.find_widget("Smart Foreground Annotations Label"),
            "smartForegroundAnnotsCombobox": self.find_widget("Smart Foreground Annotations Combobox"),
            "smartForegroundAnnotsRefreshButton": self.find_widget(
                "Smart Foreground Annotation Segments Refresh Button"
            ),
            "smartForegroundTextureAnnotsCombobox": self.find_widget("Smart Foreground Texture Annotations Combobox"),
            "smartForegroundTextureAnnotsLabel": self.find_widget("Smart Foreground Texture Annotations Label"),
            "smartForegroundResinAnnotsCombobox": self.find_widget("Smart Foreground Resin Annotations Combobox"),
            "smartForegroundResinAnnotsLabel": self.find_widget("Smart Foreground Resin Annotations Label"),
            "smartForegroundApplyButton": self.find_widget(name="Smart Foreground Apply Button"),
        }

        for objectName, widget in self.__widgets.items():
            assert widget is not None, f"widget related to the objectName '{objectName}' is None!"

    def tear_down(self) -> None:
        widget = self._module_widget
        widget.editor.setActiveEffectByName("")
        process_events()

        widget.segmentationNodeComboBox.setCurrentNode(None)
        widget.sourceVolumeNodeComboBox.setCurrentNode(None)

    def _selectSourceVolumeNode(self, widget, sourceNode: slicer.vtkMRMLVolumeNode) -> None:
        """Select `sourceNode` in the source volume combobox."""
        segmentationNode = widget.segmentationNodeComboBox.currentNode()
        currentReference = helpers.getSourceVolume(segmentationNode) if segmentationNode else None
        hasSegments = segmentationNode is not None and segmentationNode.GetSegmentation().GetNumberOfSegments() > 0
        expectsConfirmation = currentReference is not None and currentReference is not sourceNode and hasSegments

        if expectsConfirmation:
            with check_for_message_box("already references the image", should_accept=True, timeout_sec=5):
                widget.sourceVolumeNodeComboBox.setCurrentNode(sourceNode)
        else:
            widget.sourceVolumeNodeComboBox.setCurrentNode(sourceNode)
        process_events()

    def _test_smart_foreground(
        self,
        fill_inside: bool,
        template_name: str | None = None,
        split: bool = False,
        filter: bool = False,
        input2d: bool = True,
        use_ai_model: bool = True,
        frag_filter_count: int | None = None,
        generateDataOnly: bool = False,
    ) -> None:
        sourceNodeName = "Volume"

        if not generateDataOnly:
            projectFilePath = SMART_FOREGROUND_2D_PROJECT_FILE if input2d else SMART_FOREGROUND_3D_PROJECT_FILE
            load_project(project_file_path=projectFilePath)

        widget = self._module_widget
        widget.enter()

        sourceNode = helpers.tryGetNode(sourceNodeName)
        assert sourceNode is not None

        segmentationNode = self.__resetSmartForegroundSegmentationNode(fill_inside, sourceNode)
        assert segmentationNode is not None

        templateSegNode = None
        if template_name and not generateDataOnly:
            templateSegNode = helpers.tryGetNode(template_name)
            assert templateSegNode is not None

        if not use_ai_model:
            annotsSegNode = helpers.tryGetNode("Annotations")
            assert (not input2d) or (annotsSegNode is not None)

        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        process_events()
        widget.sourceVolumeNodeComboBox.setCurrentNode(sourceNode)
        process_events()

        widget.editor.setActiveEffectByName("Smart foreground")
        effect = widget.editor.effectByName("Smart foreground").self()
        process_events()

        self.__resetSmartForegroundEffectUI()

        if not use_ai_model:
            # simulating absent AI models
            effect.inputModelPath = None
            effect.setVisibleFragSplitting()
            effect.updateApplyButtonEnablement()
            effect.reactivateIfOpen()

        operationButton = self.__widgets[
            "smartForegroundFillInsideButton" if fill_inside else "smartForegroundEraseOutsideButton"
        ]
        fragSplitCheckbox = self.__widgets["smartForegroundSplitCheckbox"]
        fragButton = self.__widgets["smartForegroundFragFilterButton" if filter else "smartForegroundSplitAllButton"]
        fragFilterInput = self.__widgets["smartForegroundFragFilterInput"]
        applyButton = self.__widgets["smartForegroundApplyButton"]
        annotsComboBox = self.__widgets["smartForegroundAnnotsCombobox"]
        textureAnnotsComboBox = self.__widgets["smartForegroundTextureAnnotsCombobox"]
        resinAnnotsComboBox = self.__widgets["smartForegroundResinAnnotsCombobox"]

        operationButton.setChecked(True)

        if split:
            fragSplitCheckbox.click()
            fragButton.setChecked(True)
            if filter and frag_filter_count is not None:
                fragFilterInput.value = frag_filter_count

        assert annotsComboBox.visible == (input2d and (not use_ai_model))
        assert not textureAnnotsComboBox.visible
        assert not resinAnnotsComboBox.visible

        if annotsComboBox.visible:
            annotsComboBox.setCurrentNode(annotsSegNode)

            assert textureAnnotsComboBox.visible and textureAnnotsComboBox.currentText == "Texture"
            assert resinAnnotsComboBox.visible and resinAnnotsComboBox.currentText == "Resin"

        if template_name:
            assert applyButton.isEnabled()
            applyButton.click()

            wait_cli_to_finish(effect.cliQueue)
            if generateDataOnly:
                segmentationNode.SetName(template_name)
                return

            # Asserts
            resultArray = self.__getSegmentArray(segmentationNode, "Segment_1")
            templateArray = self.__getSegmentArray(templateSegNode, "Segment_1")

            # The no-AI ("bayesian-inference") segmentation path is not deterministic across runs.
            # So a precision target is desirable for assertion.
            intersection = np.count_nonzero(resultArray & templateArray)
            precision = 2 * intersection / (np.count_nonzero(resultArray) + np.count_nonzero(templateArray))
            targetPrecision = 0.90
            assert precision >= targetPrecision, (
                f"Result diverges from template (Dice={precision:.5f}, expected >= {targetPrecision})."
            )

    def __createSmartForegroundSegmentationNode(
        self, name: str, sourceNode: slicer.vtkMRMLVolumeNode
    ) -> slicer.vtkMRMLSegmentationNode:
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        segmentationNode.SetName(name)
        helpers.setSourceVolume(segmentationNode, sourceNode)
        return segmentationNode

    def __getSegmentArray(
        self, segmentationNode: slicer.vtkMRMLSegmentationNode, segmentName: str = "Segment_1"
    ) -> np.ndarray:
        segmentation = segmentationNode.GetSegmentation()
        segmentId = segmentation.GetSegmentIdBySegmentName(segmentName)
        segmentArray = slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, segmentId)
        return segmentArray

    def __resetSmartForegroundEffectUI(self) -> None:
        # Scenarios chained without a project reload (generateDataOnly) may leave the
        # split checkbox checked and an annotations node selected from a previous run;
        # clear both so this scenario starts from the same neutral UI state a fresh
        # project load would produce.
        annotsComboBox = self.__widgets["smartForegroundAnnotsCombobox"]
        annotsComboBox.setCurrentNode(None)

        fragSplitCheckbox = self.__widgets["smartForegroundSplitCheckbox"]
        if fragSplitCheckbox.isChecked():
            fragSplitCheckbox.click()

    def __resetSmartForegroundSegmentationNode(
        self, fill_inside: bool, sourceNode: slicer.vtkMRMLVolumeNode
    ) -> slicer.vtkMRMLSegmentationNode:
        segmentationNodeName = "New segmentation" if fill_inside else "Prior segmentation (PS)"

        if fill_inside:
            segmentationNode = self.__createSmartForegroundSegmentationNode(segmentationNodeName, sourceNode)
            segmentationNode.GetSegmentation().AddEmptySegment("Segment_1", "Segment_1")
        else:
            # "Erase outside" needs the genuinely partial pre-existing selection already baked into the raw project
            originalSegmentationNode = helpers.tryGetNode("Prior segmentation (PS)")
            assert originalSegmentationNode is not None
            segmentationNode = self.__cloneSegmentationNode(originalSegmentationNode, "New segmentation", sourceNode)

        return segmentationNode

    def __cloneSegmentationNode(
        self,
        segmentationNode: slicer.vtkMRMLSegmentationNode,
        clonedNodeName: str,
        sourceNode: slicer.vtkMRMLVolumeNode,
    ) -> slicer.vtkMRMLSegmentationNode:
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemIDToClone = shNode.GetItemByDataNode(segmentationNode)
        clonedItemID = slicer.modules.subjecthierarchy.logic().CloneSubjectHierarchyItem(shNode, itemIDToClone)
        process_events()
        shNode.SetItemName(clonedItemID, clonedNodeName)
        clonedNode = shNode.GetItemDataNode(clonedItemID)
        clonedNode.SetReferenceImageGeometryParameterFromVolumeNode(sourceNode)
        return clonedNode

    def generate_template_project_smart_foreground_2d(self) -> None:
        # Load raw project with the necessary data to generate the templates
        load_project(project_file_path=SMART_FOREGROUND_2D_RAW_PROJECT_FILE)

        self.test_2d_fill_inside(generateDataOnly=True)
        self.test_2d_split_all_and_fill_inside(generateDataOnly=True)
        self.test_2d_filter_and_fill_inside(generateDataOnly=True)
        self.test_2d_filter_and_fill_inside_with_custom_fragment_count(generateDataOnly=True)
        self.test_2d_erase_outside(generateDataOnly=True)
        self.test_2d_split_all_and_erase_outside(generateDataOnly=True)
        self.test_2d_filter_and_erase_outside(generateDataOnly=True)
        self.test_2d_split_all_and_fill_inside_geoslicer_without_ai_models(generateDataOnly=True)
        self.test_2d_split_all_and_erase_outside_geoslicer_without_ai_models(generateDataOnly=True)
        self.test_2d_filter_and_fill_inside_geoslicer_without_ai_models(generateDataOnly=True)
        self.test_2d_filter_and_erase_outside_geoslicer_without_ai_models(generateDataOnly=True)
        self.test_2d_annotations_available_in_geoslicer_without_ai_models(generateDataOnly=True)

        assert save_project(project_path=SMART_FOREGROUND_2D_PROJECT_FILE), "Failed to save generated data to project."

    def generate_template_project_smart_foreground_3d(self) -> None:
        load_project(project_file_path=SMART_FOREGROUND_3D_RAW_PROJECT_FILE)
        self.test_3d_fill_inside(generateDataOnly=True)
        self.test_3d_erase_outside(generateDataOnly=True)

        assert save_project(project_path=SMART_FOREGROUND_3D_PROJECT_FILE), "Failed to save generated data to project."

    def test_2d_fill_inside(self, generateDataOnly: bool = False) -> None:
        self._test_smart_foreground(template_name="Rock Area", fill_inside=True, generateDataOnly=generateDataOnly)

    def test_2d_erase_outside(self, generateDataOnly: bool = False) -> None:
        self._test_smart_foreground(
            template_name="PS erased outside", fill_inside=False, generateDataOnly=generateDataOnly
        )

    def test_2d_split_all_and_fill_inside(self, generateDataOnly: bool = False) -> None:
        self._test_smart_foreground(
            template_name="Split fragments", fill_inside=True, split=True, generateDataOnly=generateDataOnly
        )

    def test_2d_split_all_and_erase_outside(self, generateDataOnly: bool = False) -> None:
        self._test_smart_foreground(
            template_name="PS split and erased outside",
            fill_inside=False,
            split=True,
            generateDataOnly=generateDataOnly,
        )

    def test_2d_filter_and_fill_inside(self, generateDataOnly: bool = False) -> None:
        self._test_smart_foreground(
            template_name="Largest fragment",
            fill_inside=True,
            split=True,
            filter=True,
            generateDataOnly=generateDataOnly,
        )

    def test_2d_filter_and_erase_outside(self, generateDataOnly: bool = False) -> None:
        self._test_smart_foreground(
            fill_inside=False,
            split=True,
            filter=True,
            template_name="PS filtered and erased outside",
            generateDataOnly=generateDataOnly,
        )

    def test_3d_fill_inside(self, generateDataOnly: bool = False) -> None:
        self._test_smart_foreground(
            template_name="Rock Area", fill_inside=True, input2d=False, generateDataOnly=generateDataOnly
        )

    def test_3d_erase_outside(self, generateDataOnly: bool = False) -> None:
        self._test_smart_foreground(
            template_name="PS erased outside", fill_inside=False, input2d=False, generateDataOnly=generateDataOnly
        )

    def __createFragmentationTestVolumeNode(self, name: str, is2d: bool) -> slicer.vtkMRMLVolumeNode:
        if is2d:
            # A 3-component (RGB) volume is how the effect recognizes 2D/thin-section input.
            volumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode", name)
            array = np.random.randint(0, 255, size=(1, 100, 100, 3), dtype=np.uint8)
        else:
            volumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", name)
            array = np.random.randint(0, 255, size=(100, 100, 100), dtype=np.uint8)
        slicer.util.updateVolumeFromArray(volumeNode, array)
        return volumeNode

    def _test_fragmentation_options_visibility(self, test3dfirst: bool = False) -> None:
        widget = self._module_widget
        widget.enter()

        volume2d = self.__createFragmentationTestVolumeNode("Fragmentation Test Volume 2D", is2d=True)
        segmentation2d = self.__createSmartForegroundSegmentationNode("Fragmentation Test Segmentation 2D", volume2d)
        segmentation2d.GetSegmentation().AddEmptySegment("Segment_1", "Segment_1")

        volume3d = self.__createFragmentationTestVolumeNode("Fragmentation Test Volume 3D", is2d=False)
        segmentation3d = self.__createSmartForegroundSegmentationNode("Fragmentation Test Segmentation 3D", volume3d)
        segmentation3d.GetSegmentation().AddEmptySegment("Segment_1", "Segment_1")

        inputs = [(volume2d, segmentation2d, True), (volume3d, segmentation3d, False)]
        if test3dfirst:
            inputs = list(reversed(inputs))

        for sourceNode, segmentationNode, fragmentationCompatible in inputs:
            widget.segmentationNodeComboBox.setCurrentNode(None)
            widget.sourceVolumeNodeComboBox.setCurrentNode(None)
            process_events()
            widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
            process_events()
            self._selectSourceVolumeNode(widget, sourceNode)
            process_events()

            widget.editor.setActiveEffectByName("Smart foreground")
            effect = widget.editor.effectByName("Smart foreground").self()
            process_events()

            # simulating absent AI models to maximize the number of widgets to test
            effect.inputModelPath = None
            effect.setVisibleFragSplitting()
            effect.updateApplyButtonEnablement()
            effect.reactivateIfOpen()

            if fragmentationCompatible:
                self.__widgets["smartForegroundSplitCheckbox"].click()
                self.__widgets["smartForegroundAnnotsCombobox"].setCurrentNode(segmentationNode)

            for fragWidgetKey in [
                "smartForegroundSplitLabel",
                "smartForegroundSplitCheckbox",
                "smartForegroundSplitAllButton",
                "smartForegroundFragFilterButton",
                "smartForegroundFragFilterInput",
                "smartForegroundAnnotsLabel",
                "smartForegroundAnnotsCombobox",
                "smartForegroundAnnotsRefreshButton",
                "smartForegroundTextureAnnotsLabel",
                "smartForegroundTextureAnnotsCombobox",
                "smartForegroundResinAnnotsLabel",
                "smartForegroundResinAnnotsCombobox",
            ]:
                fragWidget = self.__widgets[fragWidgetKey]
                assert fragWidget.isVisible() is fragmentationCompatible, (
                    f"Expected widget '{fragWidgetKey}' visibility to be {fragmentationCompatible}"
                )

    def test_change_input_type_2d_to_3d(self) -> None:
        self._test_fragmentation_options_visibility()

    def test_change_input_type_3d_to_2d(self) -> None:
        self._test_fragmentation_options_visibility(test3dfirst=True)

    def test_2d_annotations_available_in_geoslicer_without_ai_models(self, generateDataOnly: bool = False) -> None:
        self._test_smart_foreground(fill_inside=True, split=True, use_ai_model=False, generateDataOnly=generateDataOnly)

    def test_2d_split_all_and_fill_inside_geoslicer_without_ai_models(self, generateDataOnly: bool = False) -> None:
        self._test_smart_foreground(
            fill_inside=True,
            split=True,
            template_name="Split fragments (no AI)",
            use_ai_model=False,
            generateDataOnly=generateDataOnly,
        )

    def test_2d_split_all_and_erase_outside_geoslicer_without_ai_models(self, generateDataOnly: bool = False) -> None:
        self._test_smart_foreground(
            fill_inside=False,
            split=True,
            template_name="PS split and erased outside (no AI)",
            use_ai_model=False,
            generateDataOnly=generateDataOnly,
        )

    def test_2d_filter_and_fill_inside_geoslicer_without_ai_models(self, generateDataOnly: bool = False) -> None:
        self._test_smart_foreground(
            fill_inside=True,
            split=True,
            filter=True,
            template_name="Largest fragment (no AI)",
            use_ai_model=False,
            generateDataOnly=generateDataOnly,
        )

    def test_2d_filter_and_erase_outside_geoslicer_without_ai_models(self, generateDataOnly: bool = False) -> None:
        self._test_smart_foreground(
            fill_inside=False,
            split=True,
            filter=True,
            template_name="PS filtered and erased outside (no AI)",
            use_ai_model=False,
            generateDataOnly=generateDataOnly,
        )

    def test_2d_filter_and_fill_inside_with_custom_fragment_count(self, generateDataOnly: bool = False) -> None:
        self._test_smart_foreground(
            template_name="Largest 2 fragments",
            fill_inside=True,
            split=True,
            filter=True,
            frag_filter_count=2,
            generateDataOnly=generateDataOnly,
        )

    def test_model_path_update_refreshes_ai_availability(self) -> None:
        widget = self._module_widget
        widget.enter()

        load_project(project_file_path=SMART_FOREGROUND_2D_PROJECT_FILE)

        sourceNode = helpers.tryGetNode("Volume")
        assert sourceNode is not None
        segmentationNode = self.__resetSmartForegroundSegmentationNode(fill_inside=True, sourceNode=sourceNode)

        widget.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        widget.sourceVolumeNodeComboBox.setCurrentNode(sourceNode)

        widget.editor.setActiveEffectByName("Smart foreground")
        effect = widget.editor.effectByName("Smart foreground").self()

        # Force a value a real detection could never produce, then let the actual
        # ApplicationObservables().modelPathUpdated signal (the one activate() subscribes
        # the effect's model-availability refresh to) correct it back, instead of poking
        # the effect's private state directly.
        effect.inputModelPath = "/not/a/real/model.pth"
        ApplicationObservables().modelPathUpdated.emit()

        try:
            expectedModelPath = get_pth(get_model_by_name("bayes_3px")).as_posix()
        except Exception:
            expectedModelPath = None

        assert effect.inputModelPath == expectedModelPath
