import os
from pathlib import Path

import ctk
import qt
import slicer
from ltrace.slicer_utils import *


class ImageLogSegmentEditor(LTracePlugin):
    SETTING_KEY = "ImageLogSegmentEditor"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Manual Segmentation"
        self.parent.categories = ["Tools", "Segmentation", "ImageLog", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ImageLogSegmentEditor.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ImageLogSegmentEditorWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.customizedSegmentEditorWidget = None
        self.segmentEditorWidget = None

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = ImageLogSegmentEditorLogic(self.parent)

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        formLayout = qt.QFormLayout(frame)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        self.customizedSegmentEditorWidget = slicer.util.getNewModuleWidget("CustomizedSegmentEditor")
        self.segmentEditorWidget = self.customizedSegmentEditorWidget.editor

        self.customizedSegmentEditorWidget.selectParameterNodeByTag(ImageLogSegmentEditor.SETTING_KEY)
        self.configureEffects()
        self.segmentEditorWidget.unorderedEffectsVisible = False
        self.segmentEditorWidget.setAutoShowSourceVolumeNode(False)
        self.segmentEditorWidget.findChild(ctk.ctkMenuButton, "Show3DButton").setVisible(False)
        self.segmentEditorWidget.segmentationNodeChanged.connect(self.segmentationNodeOrSourceVolumeNodeChanged)
        self.segmentEditorWidget.sourceVolumeNodeChanged.connect(self.segmentationNodeOrSourceVolumeNodeChanged)
        self.segmentEditorWidget.sourceVolumeNodeChanged.connect(self.onSourceVolumeNodeChanged)
        formLayout.addWidget(self.segmentEditorWidget)

        self.layout.addStretch()

        self.lastSegUpdate = None

    def segmentationNodeOrSourceVolumeNodeChanged(self):
        if not slicer.util.selectedModule() == "ImageLogSegmentEditor":
            return

        segmentationNode = self.segmentEditorWidget.segmentationNode()
        sourceVolumeNode = self.segmentEditorWidget.sourceVolumeNode()

        # Deduplicate calls to this method when both are updated at once
        segId = segmentationNode.GetID() if segmentationNode is not None else None
        sourceId = sourceVolumeNode.GetID() if sourceVolumeNode is not None else None
        params = segId, sourceId
        if params == self.lastSegUpdate:
            return
        self.lastSegUpdate = params

        if segmentationNode is not None:
            segmentationNode.SetAttribute("ImageLogSegmentation", "True")
        self.logic.imageLogDataLogic.segmentationNodeOrSourceVolumeNodeChanged(segmentationNode, sourceVolumeNode)

    def onSourceVolumeNodeChanged(self, node):
        colorSupport = node and node.GetImageData() and node.GetImageData().GetNumberOfScalarComponents() == 3
        self.configureEffects(colorSupport=colorSupport)

    def configureEffects(self, colorSupport=False):
        effects = [
            "Threshold",
            "Paint",
            "Draw",
            "Erase",
            "Level tracing",
            "Margin",
            "Smoothing",
            "Scissors",
            "Islands",
            "Watershed",
            "Logical operators",
            "Mask Image",
            "Multiple Threshold",
            "Depth Segmenter",
            "Boundary removal",
        ]
        if colorSupport:
            effects.append("Color threshold")
        self.segmentEditorWidget.setEffectNameOrder(effects)
        self.segmentEditorWidget.unorderedEffectsVisible = False

    def enter(self) -> None:
        super().enter()
        segmentationNodeComboBox = self.segmentEditorWidget.findChild(
            slicer.qMRMLNodeComboBox, "SegmentationNodeComboBox"
        )
        segmentationNodeComboBox.setEnabled(True)

    def initializeSavedNodes(self):
        segmentEditorNode = self.segmentEditorWidget.mrmlSegmentEditorNode()
        if segmentEditorNode is None:
            return

        toLoadSegmentation = segmentEditorNode.GetSegmentationNode()
        self.segmentEditorWidget.mrmlSegmentEditorNode().SetAndObserveSegmentationNode(None)
        self.segmentEditorWidget.blockSignals(True)
        self.segmentEditorWidget.setSegmentationNode(toLoadSegmentation)
        self.segmentEditorWidget.blockSignals(False)

    def exit(self):
        # Leaving the module sets the active effect to "None"
        self.segmentEditorWidget.setActiveEffectByName("None")

    def cleanup(self):
        super().cleanup()
        self.customizedSegmentEditorWidget.cleanup()
        self.logic.imageLogDataLogic = None
        del self.logic


class ImageLogSegmentEditorLogic(LTracePluginLogic):
    def __init__(self, parent):
        LTracePluginLogic.__init__(self, parent)
        self.setImageLogDataLogic()

    def setImageLogDataLogic(self):
        """
        Allows Image Log Segmenter to perform changes in the Image Log Data views.
        """
        self.imageLogDataLogic = slicer.util.getModuleLogic("ImageLogData")
