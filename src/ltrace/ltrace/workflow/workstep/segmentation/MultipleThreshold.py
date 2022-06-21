import qt
import slicer
from SegmentEditorEffects import *
from ltrace.workflow.workstep import Workstep, WorkstepWidget


class MultipleThreshold(Workstep):
    NAME = "Segmentation: Multiple Threshold"

    INPUT_TYPES = (
        slicer.vtkMRMLScalarVolumeNode,
        slicer.vtkMRMLVectorVolumeNode,
    )
    OUTPUT_TYPE = slicer.vtkMRMLSegmentationNode

    SEGMENT_COLORS = [(0, 1, 0), (1, 0, 1), (0, 0.5, 1), (1, 0.5, 0), (0.5, 0.75, 0.5)]

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.numberOfSegments = 2
        self.delete_inputs = False

    def run(self, sourceVolumeNodes):
        # Create segment editor to get access to effects
        segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
        segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
        segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
        segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)

        for sourceVolumeNode in sourceVolumeNodes:
            # Create segmentation
            segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
            # segmentationNode.CreateDefaultDisplayNodes()  # only needed for display
            segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(sourceVolumeNode)
            segmentationNode.SetName(
                slicer.mrmlScene.GetUniqueNameByString(sourceVolumeNode.GetName() + " - Segmentation")
            )
            subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            itemParent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(sourceVolumeNode))
            subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(segmentationNode), itemParent)

            segmentIDs = []
            segmentation = segmentationNode.GetSegmentation()
            segmentEditorWidget.setSegmentationNode(segmentationNode)
            segmentEditorWidget.setSourceVolumeNode(sourceVolumeNode)

            for color in self.SEGMENT_COLORS[: self.numberOfSegments]:
                segmentID = segmentation.AddEmptySegment()
                segmentation.GetSegment(segmentID).SetColor(color)
                segmentIDs.append(segmentID)

            segmentEditorWidget.setActiveEffectByName("Multiple Threshold")
            effect = segmentEditorWidget.activeEffect()

            displayNode = segmentationNode.GetDisplayNode()
            for segmentID in segmentIDs:
                displayNode.SetSegmentVisibility2DOutline(segmentID, False)
                displayNode.SetSegmentOpacity2DFill(segmentID, 2)

            effect.self().applyKmeans()
            effect.self().onApply()

            self.discard_input(sourceVolumeNode)

            yield segmentationNode

        effect.self().clearObservers()
        slicer.mrmlScene.RemoveNode(segmentEditorNode)

    def widget(self):
        return MultipleThresholdWidget(self)


class MultipleThresholdWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)
        formLayout = qt.QFormLayout()
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.layout().addLayout(formLayout)
        self.numberOfSegmentsSlider = slicer.qMRMLSliderWidget()
        self.numberOfSegmentsSlider.maximum = len(self.workstep.SEGMENT_COLORS)
        self.numberOfSegmentsSlider.minimum = 2
        self.numberOfSegmentsSlider.decimals = 0
        self.numberOfSegmentsSlider.singleStep = 1
        formLayout.addRow("Number of segments:", self.numberOfSegmentsSlider)
        self.delete_inputsCheckbox = qt.QCheckBox("Remove input images from project after segmentation")
        self.delete_inputsCheckbox.setToolTip(
            "Remove input images as soon as they are no longer needed in order to reduce memory usage."
        )
        formLayout.addRow(self.delete_inputsCheckbox)

    def save(self):
        self.workstep.numberOfSegments = int(self.numberOfSegmentsSlider.value)
        self.workstep.delete_inputs = self.delete_inputsCheckbox.isChecked()

    def load(self):
        self.numberOfSegmentsSlider.value = self.workstep.numberOfSegments
        self.delete_inputsCheckbox.setChecked(self.workstep.delete_inputs)
