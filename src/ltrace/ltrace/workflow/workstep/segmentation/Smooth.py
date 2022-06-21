import qt
from SegmentEditorEffects import *
from ltrace.workflow.workstep import Workstep, WorkstepWidget
from ltrace.slicer.helpers import getSourceVolume


class N:
    def GetName(self):
        return "Dummy"


class Smooth(Workstep):
    NAME = "Segmentation: Smooth"

    INPUT_TYPES = (slicer.vtkMRMLSegmentationNode,)
    OUTPUT_TYPE = slicer.vtkMRMLSegmentationNode

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.smoothingMethod = MEDIAN
        self.kernelSize = 3.0

    def run(self, segmentationNodes):
        # Create segment editor to get access to effects
        segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
        segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
        segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
        segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)

        for segmentationNode in segmentationNodes:
            self.makeSegmentsVisible(segmentationNode)

            sourceVolumeNode = getSourceVolume(segmentationNode)
            if sourceVolumeNode:
                segmentEditorWidget.setSourceVolumeNode(sourceVolumeNode)

            segmentEditorWidget.setSegmentationNode(segmentationNode)
            segmentEditorWidget.setActiveEffectByName("Smoothing")
            effect = segmentEditorWidget.activeEffect()
            effect.setParameter("SmoothingMethod", self.smoothingMethod)
            effect.setParameter("KernelSizeMm", self.kernelSize)
            effect.self().onApply()
            yield segmentationNode

        # Clean up
        segmentEditorWidget = None
        slicer.mrmlScene.RemoveNode(segmentEditorNode)

    def widget(self):
        return SmoothWidget(self)

    def validate(self):
        if self.kernelSize is None:
            return "Kernel size is required."
        return True


class SmoothWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)

        self.formLayout = qt.QFormLayout()
        self.formLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.layout().addLayout(self.formLayout)

        self.smoothingMethodComboBox = qt.QComboBox()
        self.smoothingMethodComboBox.addItem("Median", MEDIAN)
        self.smoothingMethodComboBox.addItem("Opening (remove extrusions)", MORPHOLOGICAL_OPENING)
        self.smoothingMethodComboBox.addItem("Closing (fill holes)", MORPHOLOGICAL_CLOSING)
        self.smoothingMethodComboBox.addItem("Gaussian", GAUSSIAN)
        self.smoothingMethodComboBox.addItem("Joint smoothing", JOINT_TAUBIN)
        self.formLayout.addRow("Smoothing method:", self.smoothingMethodComboBox)
        self.kernelSizeLineEdit = qt.QLineEdit()
        self.doubleValidator = qt.QRegExpValidator(qt.QRegExp("[-+]?[0-9]*\\.?[0-9]+([eE][-+]?[0-9]+)?"))
        self.kernelSizeLineEdit.setValidator(self.doubleValidator)
        self.formLayout.addRow("Kernel size (mm):", self.kernelSizeLineEdit)
        self.layout().addStretch(1)

    def save(self):
        self.workstep.smoothingMethod = self.smoothingMethodComboBox.currentData
        try:
            self.workstep.kernelSize = float(self.kernelSizeLineEdit.text)
        except ValueError:
            self.workstep.kernelSize = None

    def load(self):
        self.setComboBoxIndexByData(self.smoothingMethodComboBox, self.workstep.smoothingMethod)
        self.kernelSizeLineEdit.text = self.workstep.kernelSize if self.workstep.kernelSize is not None else ""
