import qt
from SegmentEditorEffects import *
from ltrace.workflow.workstep import Workstep, WorkstepWidget
from ltrace.slicer.helpers import getSourceVolume


class Margin(Workstep):
    NAME = "Segmentation: Margin"

    INPUT_TYPES = (slicer.vtkMRMLSegmentationNode,)
    OUTPUT_TYPE = slicer.vtkMRMLSegmentationNode

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.operation = -1
        self.marginSize = 3.0

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
            segmentEditorWidget.setActiveEffectByName("Margin")
            effect = segmentEditorWidget.activeEffect()
            effect.setParameter("MarginSizeMm", self.marginSize * self.operation)
            effect.self().onApply()
            yield segmentationNode

        # Clean up
        segmentEditorWidget = None
        slicer.mrmlScene.RemoveNode(segmentEditorNode)

    def widget(self):
        return MarginWidget(self)

    def validate(self):
        if self.marginSize is None:
            return "Margin size is required."
        return True


class MarginWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)

        self.formLayout = qt.QFormLayout()
        self.formLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.layout().addLayout(self.formLayout)

        self.operationComboBox = qt.QComboBox()
        self.operationComboBox.addItem("Shrink", -1)
        self.operationComboBox.addItem("Grow", 1)
        self.formLayout.addRow("Smoothing method:", self.operationComboBox)
        self.marginSizeLineEdit = qt.QLineEdit()
        self.doubleValidator = qt.QRegExpValidator(qt.QRegExp("[-+]?[0-9]*\\.?[0-9]+([eE][-+]?[0-9]+)?"))
        self.marginSizeLineEdit.setValidator(self.doubleValidator)
        self.formLayout.addRow("Margin size (mm):", self.marginSizeLineEdit)
        self.layout().addStretch(1)

    def save(self):
        self.workstep.operation = self.operationComboBox.currentData
        try:
            self.workstep.marginSize = float(self.marginSizeLineEdit.text)
        except ValueError:
            self.workstep.marginSize = None

    def load(self):
        self.setComboBoxIndexByData(self.operationComboBox, self.workstep.operation)
        self.marginSizeLineEdit.text = self.workstep.marginSize if self.workstep.marginSize is not None else ""
