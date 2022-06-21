import qt
from SegmentEditorEffects import *
from ltrace.workflow.workstep import Workstep, WorkstepWidget
from ltrace.slicer.helpers import getSourceVolume


class Watershed(Workstep):
    NAME = "Segmentation: Watershed"

    INPUT_TYPES = (slicer.vtkMRMLSegmentationNode,)
    OUTPUT_TYPE = slicer.vtkMRMLSegmentationNode

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.objectScale = 0.025

    def run(self, segmentationNodes):
        # Create segment editor to get access to effects
        segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
        segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
        segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
        segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)

        for segmentationNode in segmentationNodes:
            self.makeSegmentsVisible(segmentationNode)
            sourceVolumeNode = getSourceVolume(segmentationNode)

            # Cloning segmentation node (Leandro's request)
            subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            item = subjectHierarchyNode.GetItemByDataNode(segmentationNode)
            clonedItem = slicer.modules.subjecthierarchy.logic().CloneSubjectHierarchyItem(subjectHierarchyNode, item)
            segmentationNodeName = slicer.mrmlScene.GenerateUniqueName(segmentationNode.GetName())
            segmentationNode = subjectHierarchyNode.GetItemDataNode(clonedItem)
            segmentationNode.SetName(segmentationNodeName)
            segmentationNode.SetNodeReferenceID("referenceImageGeometryRef", sourceVolumeNode.GetID())

            # Watershed
            segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(sourceVolumeNode)
            addedSegmentID = segmentationNode.GetSegmentation().AddEmptySegment("")
            segmentEditorWidget.setSegmentationNode(segmentationNode)
            segmentEditorWidget.setSourceVolumeNode(sourceVolumeNode)
            segmentEditorWidget.setActiveEffectByName("Watershed")
            effect = segmentEditorWidget.activeEffect()
            effect.setParameter("ObjectScaleMm", self.objectScale)
            effect.self().onPreview()
            effect.self().onApply()

            yield segmentationNode

        segmentEditorWidget = None
        slicer.mrmlScene.RemoveNode(segmentEditorNode)

    def widget(self):
        return WatershedWidget(self)


class WatershedWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)
        formLayout = qt.QFormLayout()
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.layout().addLayout(formLayout)

        self.objectScaleSpinBox = qt.QDoubleSpinBox()
        self.objectScaleSpinBox.setDecimals(3)
        self.objectScaleSpinBox.setSingleStep(0.001)
        self.objectScaleSpinBox.setMinimum(0.001)
        formLayout.addRow("Object scale (mm):", self.objectScaleSpinBox)

    def save(self):
        self.workstep.objectScale = self.objectScaleSpinBox.value

    def load(self):
        self.objectScaleSpinBox.setValue(self.workstep.objectScale)
