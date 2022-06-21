import qt
from SegmentEditorEffects import *
from ltrace.workflow.workstep import Workstep, WorkstepWidget
from ltrace.slicer.helpers import getSourceVolume
from ltrace.slicer.ui import intParam


class Islands(Workstep):
    NAME = "Segmentation: Islands"

    INPUT_TYPES = (slicer.vtkMRMLSegmentationNode,)
    OUTPUT_TYPE = slicer.vtkMRMLSegmentationNode

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.mode = KEEP_LARGEST_ISLAND
        self.islandMinimumSize = 10

    def run(self, segmentationNodes):
        # Create segment editor to get access to effects
        segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
        segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
        segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
        segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)

        for segmentationNode in segmentationNodes:
            self.makeSegmentsVisible(segmentationNode)
            segmentEditorWidget.setSegmentationNode(segmentationNode)

            sourceVolumeNode = getSourceVolume(segmentationNode)
            if sourceVolumeNode:
                segmentEditorWidget.setSourceVolumeNode(sourceVolumeNode)

            segmentEditorWidget.setActiveEffectByName("Islands")
            effect = segmentEditorWidget.activeEffect()
            effect.setParameter("Operation", self.mode)
            effect.setParameter("MinimumSize", self.islandMinimumSize)
            effect.self().onApply()
            yield segmentationNode

        # Clean up
        segmentEditorWidget = None
        slicer.mrmlScene.RemoveNode(segmentEditorNode)

    def widget(self):
        return IslandsWidget(self)

    def validate(self):
        if not self.mode == KEEP_LARGEST_ISLAND and self.islandMinimumSize is None:
            return "Minimum size is required."
        return True


class IslandsWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)

        self.formLayout = qt.QFormLayout()
        self.formLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.layout().addLayout(self.formLayout)

        self.modeComboBox = qt.QComboBox()
        self.modeComboBox.addItem("Keep largest island", KEEP_LARGEST_ISLAND)
        self.modeComboBox.addItem("Remove small islands", REMOVE_SMALL_ISLANDS)
        self.modeComboBox.addItem("Split islands to segments", SPLIT_ISLANDS_TO_SEGMENTS)
        self.formLayout.addRow("Mode:", self.modeComboBox)
        self.islandMinimumSizeLineEdit = intParam(value=self.workstep.islandMinimumSize)
        self.formLayout.addRow("Minimum size (voxels):", self.islandMinimumSizeLineEdit)
        self.layout().addStretch(1)
        self.onModeChanged()

        # Connections
        self.modeComboBox.currentIndexChanged.connect(self.onModeChanged)

    def onModeChanged(self):
        if self.modeComboBox.currentData == KEEP_LARGEST_ISLAND:
            self.islandMinimumSizeLineEdit.hide()
            self.formLayout.labelForField(self.islandMinimumSizeLineEdit).hide()
        else:
            self.islandMinimumSizeLineEdit.show()
            self.formLayout.labelForField(self.islandMinimumSizeLineEdit).show()

    def save(self):
        self.workstep.mode = self.modeComboBox.currentData
        try:
            self.workstep.islandMinimumSize = int(self.islandMinimumSizeLineEdit.text)
        except ValueError:
            self.workstep.islandMinimumSize = None

    def load(self):
        self.setComboBoxIndexByData(self.modeComboBox, self.workstep.mode)
        self.islandMinimumSizeLineEdit.text = (
            self.workstep.islandMinimumSize if self.workstep.islandMinimumSize is not None else ""
        )
