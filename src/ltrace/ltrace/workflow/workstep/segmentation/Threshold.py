import qt
import slicer
from SegmentEditorEffects import *
from ltrace.workflow.workstep import Workstep, WorkstepWidget


class Threshold(Workstep):
    NAME = "Segmentation: Threshold"

    INPUT_TYPES = (slicer.vtkMRMLScalarVolumeNode,)
    OUTPUT_TYPE = slicer.vtkMRMLSegmentationNode

    THRESHOLD_MODE_MANUAL = "MANUAL"
    THRESHOLD_MODE_AUTOMATIC = "AUTOMATIC"

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.thresholdMode = self.THRESHOLD_MODE_MANUAL
        self.manualThresholdLowerBound = 0.0
        self.manualThresholdUpperBound = 0.0
        self.automaticThresholdMethod = METHOD_OTSU
        self.automaticThresholdMode = MODE_SET_LOWER_MAX
        self.deleteInputs = False

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
            addedSegmentID = segmentationNode.GetSegmentation().AddEmptySegment("")
            segmentationNode.SetName(
                slicer.mrmlScene.GetUniqueNameByString(sourceVolumeNode.GetName() + " - Segmentation")
            )
            segmentEditorWidget.setSegmentationNode(segmentationNode)
            segmentEditorWidget.setSourceVolumeNode(sourceVolumeNode)
            segmentEditorWidget.setActiveEffectByName("Threshold")
            effect = segmentEditorWidget.activeEffect()
            if self.thresholdMode == self.THRESHOLD_MODE_MANUAL:
                effect.setParameter("MinimumThreshold", str(self.manualThresholdLowerBound))
                effect.setParameter("MaximumThreshold", str(self.manualThresholdUpperBound))
            else:
                effect.setParameter("AutoThresholdMethod", self.automaticThresholdMethod)
                effect.setParameter("AutoThresholdMode", self.automaticThresholdMode)
            effect.self().onApply()
            segmentationNode.GetSegmentation().GetSegment(addedSegmentID).SetColor([0, 1, 0])
            segmentationNode.GetDisplayNode().SetSegmentVisibility2DOutline(addedSegmentID, False)
            segmentationNode.GetDisplayNode().SetSegmentOpacity2DFill(addedSegmentID, 2)
            segmentationNode.GetDisplayNode().SetVisibility(False)

            subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            itemParent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(sourceVolumeNode))
            subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(segmentationNode), itemParent)

            self.discard_input(sourceVolumeNode)

            yield segmentationNode

        # Clean up
        segmentEditorWidget = None
        slicer.mrmlScene.RemoveNode(segmentEditorNode)

    def widget(self):
        return ThresholdWidget(self)

    def validate(self):
        if self.thresholdMode == self.THRESHOLD_MODE_MANUAL:
            if self.manualThresholdLowerBound is None:
                return "Lower bound is required."
            if self.manualThresholdUpperBound is None:
                return "Upper bound is required."
        return True


class ThresholdWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)
        formLayout = qt.QFormLayout()
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.layout().addLayout(formLayout)
        self.thresholdTypeComboBox = qt.QComboBox()
        self.thresholdTypeComboBox.addItem("Manual", self.workstep.THRESHOLD_MODE_MANUAL)
        self.thresholdTypeComboBox.addItem("Automatic", self.workstep.THRESHOLD_MODE_AUTOMATIC)
        formLayout.addRow("Type:", self.thresholdTypeComboBox)
        formLayout.addRow(" ", None)
        self.manualThresholdWidget = self.manualThresholdWidgett()
        self.automaticThresholdWidget = self.automaticThresholdWidgett()
        formLayout.addRow(self.manualThresholdWidget)
        formLayout.addRow(self.automaticThresholdWidget)

        self.deleteInputsCheckbox = qt.QCheckBox("Delete input images after segmentation")
        self.deleteInputsCheckbox.setToolTip(
            "Delete input images as soon as they are no longer needed in order to reduce memory usage."
        )
        formLayout.addRow(self.deleteInputsCheckbox)

        self.onThresholdTypeChanged()
        self.layout().addStretch(1)

        # Connections
        self.thresholdTypeComboBox.currentIndexChanged.connect(self.onThresholdTypeChanged)

    def onThresholdTypeChanged(self):
        self.hideThresholdWidgets()
        if self.thresholdTypeComboBox.currentData == self.workstep.THRESHOLD_MODE_MANUAL:
            self.manualThresholdWidget.setVisible(True)
        elif self.thresholdTypeComboBox.currentData == self.workstep.THRESHOLD_MODE_AUTOMATIC:
            self.automaticThresholdWidget.setVisible(True)

    def hideThresholdWidgets(self):
        self.manualThresholdWidget.setVisible(False)
        self.automaticThresholdWidget.setVisible(False)

    def manualThresholdWidgett(self):
        frame = qt.QFrame()
        formLayout = qt.QFormLayout(frame)
        formLayout.setContentsMargins(0, 0, 0, 0)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.doubleValidator = qt.QRegExpValidator(qt.QRegExp("[-+]?[0-9]*\\.?[0-9]+([eE][-+]?[0-9]+)?"))
        self.manualThresholdLowerBoundLineEdit = qt.QLineEdit()
        self.manualThresholdLowerBoundLineEdit.setValidator(self.doubleValidator)
        formLayout.addRow("Lower bound:", self.manualThresholdLowerBoundLineEdit)
        self.manualThresholdUpperBoundLineEdit = qt.QLineEdit()
        self.manualThresholdUpperBoundLineEdit.setValidator(self.doubleValidator)
        formLayout.addRow("Upper bound:", self.manualThresholdUpperBoundLineEdit)
        return frame

    def automaticThresholdWidgett(self):
        frame = qt.QFrame()
        formLayout = qt.QFormLayout(frame)
        formLayout.setContentsMargins(0, 0, 0, 0)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.automaticThresholdMethodComboBox = qt.QComboBox()
        self.automaticThresholdMethodComboBox.addItem("Otsu", METHOD_OTSU)
        self.automaticThresholdMethodComboBox.addItem("Huang", METHOD_HUANG)
        self.automaticThresholdMethodComboBox.addItem("IsoData", METHOD_ISO_DATA)
        self.automaticThresholdMethodComboBox.addItem("Kittler-Illingworth", METHOD_KITTLER_ILLINGWORTH)
        self.automaticThresholdMethodComboBox.addItem("Maximum entropy", METHOD_MAXIMUM_ENTROPY)
        self.automaticThresholdMethodComboBox.addItem("Moments", METHOD_MOMENTS)
        self.automaticThresholdMethodComboBox.addItem("Renyi entropy", METHOD_RENYI_ENTROPY)
        self.automaticThresholdMethodComboBox.addItem("Shanbhag", METHOD_SHANBHAG)
        self.automaticThresholdMethodComboBox.addItem("Triangle", METHOD_TRIANGLE)
        self.automaticThresholdMethodComboBox.addItem("Yen", METHOD_YEN)
        formLayout.addRow("Method:", self.automaticThresholdMethodComboBox)

        self.automaticThresholdModeComboBox = qt.QComboBox()
        self.automaticThresholdModeComboBox.addItem("auto → maximum", MODE_SET_LOWER_MAX)
        self.automaticThresholdModeComboBox.addItem("minimum → auto", MODE_SET_MIN_UPPER)
        self.automaticThresholdModeComboBox.addItem("as lower", MODE_SET_LOWER)
        self.automaticThresholdModeComboBox.addItem("as upper", MODE_SET_UPPER)
        formLayout.addRow("Mode:", self.automaticThresholdModeComboBox)

        return frame

    def save(self):
        self.workstep.thresholdMode = self.thresholdTypeComboBox.currentData

        try:
            self.workstep.manualThresholdLowerBound = float(self.manualThresholdLowerBoundLineEdit.text)
        except ValueError:
            self.workstep.manualThresholdLowerBound = None

        try:
            self.workstep.manualThresholdUpperBound = float(self.manualThresholdUpperBoundLineEdit.text)
        except ValueError:
            self.workstep.manualThresholdUpperBound = None

        self.workstep.automaticThresholdMethod = self.automaticThresholdMethodComboBox.currentData
        self.workstep.automaticThresholdMode = self.automaticThresholdModeComboBox.currentData
        self.workstep.deleteInputs = self.deleteInputsCheckbox.isChecked()

    def load(self):
        self.setComboBoxIndexByData(self.thresholdTypeComboBox, self.workstep.thresholdMode)
        self.manualThresholdLowerBoundLineEdit.text = (
            self.workstep.manualThresholdLowerBound if self.workstep.manualThresholdLowerBound is not None else ""
        )
        self.manualThresholdUpperBoundLineEdit.text = (
            self.workstep.manualThresholdUpperBound if self.workstep.manualThresholdUpperBound is not None else ""
        )
        self.setComboBoxIndexByData(self.automaticThresholdMethodComboBox, self.workstep.automaticThresholdMethod)
        self.setComboBoxIndexByData(self.automaticThresholdModeComboBox, self.workstep.automaticThresholdMode)
        self.deleteInputsCheckbox.setChecked(self.workstep.deleteInputs)
