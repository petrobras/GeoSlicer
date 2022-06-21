import SimpleITK as sitk
import qt
import sitkUtils
from SegmentEditorEffects import *
from ltrace.workflow.workstep import Workstep, WorkstepWidget


class BoundaryRemoval(Workstep):
    NAME = "Segmentation: Boundary Removal"

    INPUT_TYPES = (slicer.vtkMRMLSegmentationNode,)
    OUTPUT_TYPE = slicer.vtkMRMLSegmentationNode

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.minimumThresholdMultiplier = 0

    def run(self, segmentationNodes):
        # Create segment editor to get access to effects
        segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
        segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
        segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
        segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)

        for segmentationNode in segmentationNodes:
            sourceVolumeNode = slicer.mrmlScene.GetNodeByID(
                segmentationNode.GetNodeReferenceID("referenceImageGeometryRef")
            )

            # Cloning segmentation node (Leandro's request)
            subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            item = subjectHierarchyNode.GetItemByDataNode(segmentationNode)
            clonedItem = slicer.modules.subjecthierarchy.logic().CloneSubjectHierarchyItem(subjectHierarchyNode, item)
            segmentationNodeName = slicer.mrmlScene.GenerateUniqueName(segmentationNode.GetName())
            segmentationNode = subjectHierarchyNode.GetItemDataNode(clonedItem)
            segmentationNode.SetName(segmentationNodeName)

            # Applying Gradient Magnitude Image Filter
            filterOutputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
            simpleFiltersWidget = slicer.modules.simplefilters.createNewWidgetRepresentation()
            simpleFiltersWidget.self().filterSelector.setCurrentText("GradientMagnitudeImageFilter")
            sitkFilter = simpleFiltersWidget.self().filterParameters.filter
            inputImage = sitk.ReadImage(sitkUtils.GetSlicerITKReadWriteAddress(sourceVolumeNode.GetName()))
            outputImage = sitkFilter.Execute(*[inputImage])
            nodeWriteAddress = sitkUtils.GetSlicerITKReadWriteAddress(filterOutputVolume.GetName())
            sitk.WriteImage(outputImage, nodeWriteAddress)

            # Segmenting
            segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(filterOutputVolume)
            addedSegmentID = segmentationNode.GetSegmentation().AddEmptySegment("")
            segmentEditorWidget.setSegmentationNode(segmentationNode)
            segmentEditorWidget.setSourceVolumeNode(filterOutputVolume)
            segmentEditorWidget.setCurrentSegmentID(addedSegmentID)
            segmentEditorWidget.setActiveEffectByName("Threshold")
            effect = segmentEditorWidget.activeEffect()
            effect.setParameter("AutoThresholdMethod", "OTSU")
            effect.setParameter("AutoThresholdMode", "SET_LOWER_MAX")
            effect.self().onAutoThreshold()

            # After applying auto threshold
            minimumThreshold = float(effect.parameter("MinimumThreshold"))
            maximumThreshold = float(effect.parameter("MaximumThreshold"))
            minimumThreshold = minimumThreshold + self.minimumThresholdMultiplier * minimumThreshold
            if minimumThreshold > maximumThreshold:
                minimumThreshold = maximumThreshold
            effect.setParameter("MinimumThreshold", str(minimumThreshold))

            effect.self().onApply()
            segmentationNode.GetSegmentation().GetSegment(addedSegmentID).SetColor([0, 0, 1])
            segmentationNode.GetDisplayNode().SetSegmentVisibility2DOutline(addedSegmentID, False)
            segmentationNode.GetDisplayNode().SetSegmentOpacity2DFill(addedSegmentID, 2)
            segmentationNode.RemoveSegment(addedSegmentID)

            slicer.mrmlScene.RemoveNode(filterOutputVolume)
            segmentationNode.SetNodeReferenceID("referenceImageGeometryRef", sourceVolumeNode.GetID())

            yield segmentationNode

        segmentEditorWidget = None
        slicer.mrmlScene.RemoveNode(segmentEditorNode)

    def widget(self):
        return BoundaryRemovalWidget(self)


class BoundaryRemovalWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)
        formLayout = qt.QFormLayout()
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.layout().addLayout(formLayout)
        self.minimumThresholdMultiplierSlider = slicer.qMRMLSliderWidget()
        self.minimumThresholdMultiplierSlider.maximum = 3
        self.minimumThresholdMultiplierSlider.minimum = -3
        self.minimumThresholdMultiplierSlider.decimals = 1
        self.minimumThresholdMultiplierSlider.singleStep = 0.1
        self.minimumThresholdMultiplierSlider.toolTip = """\
            This parameter controls the minimum value of the automatic threshold found in the gradient magnitude image filter result, used 
            for the interface segmentation. Increase it to reduce unwanted noise in that segmentation.\
        """
        formLayout.addRow("Minimum threshold multiplier:", self.minimumThresholdMultiplierSlider)

    def save(self):
        self.workstep.minimumThresholdMultiplier = self.minimumThresholdMultiplierSlider.value

    def load(self):
        self.minimumThresholdMultiplierSlider.value = self.workstep.minimumThresholdMultiplier
