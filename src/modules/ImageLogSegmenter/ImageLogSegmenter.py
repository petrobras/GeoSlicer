import os
from pathlib import Path

import ctk
import qt
import slicer
from ltrace.slicer_utils import *


class ImageLogSegmenter(LTracePlugin):
    SETTING_KEY = "ImageLogSegmenter"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Image Log Segmenter"
        self.parent.categories = ["LTrace Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ImageLogSegmenter.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ImageLogSegmenterWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = ImageLogSegmenterLogic()

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        formLayout = qt.QFormLayout(frame)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.customizedSegmentEditorWidget = slicer.modules.customizedsegmenteditor.createNewWidgetRepresentation()
        self.customizedSegmentEditorWidget.self().selectParameterNodeByTag(ImageLogSegmenter.SETTING_KEY)
        self.segmentEditorWidget = self.customizedSegmentEditorWidget.self().editor
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
        if not slicer.util.selectedModule() == "ImageLogEnv":
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
        color_support = node and node.GetImageData() and node.GetImageData().GetNumberOfScalarComponents() == 3
        self.configureEffects(color_support=color_support)

    def configureEffects(self, color_support=False):
        effects = [
            "Threshold",
            "Paint",
            "Draw",
            "Erase",
            "Depth Segmenter",
            "Level tracing",
            "Margin",
            "Smoothing",
            "Scissors",
            "Islands",
            "Logical operators",
            "Mask Image",
            "Multiple Threshold",
            "Watershed",
        ]
        if color_support:
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
        toLoadSegmentation = self.segmentEditorWidget.mrmlSegmentEditorNode().GetSegmentationNode()
        self.segmentEditorWidget.mrmlSegmentEditorNode().SetAndObserveSegmentationNode(None)
        self.segmentEditorWidget.blockSignals(True)
        self.segmentEditorWidget.setSegmentationNode(toLoadSegmentation)
        self.segmentEditorWidget.blockSignals(False)

    def exit(self):
        # Leaving the module sets the active effect to "None"
        self.segmentEditorWidget.setActiveEffectByName("None")

    def cleanup(self):
        super().cleanup()
        self.customizedSegmentEditorWidget.self().cleanup()


class ImageLogSegmenterLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def setImageLogDataLogic(self, imageLogDataLogic):
        """
        Allows Image Log Segmenter to perform changes in the Image Log Data views.
        """
        self.imageLogDataLogic = imageLogDataLogic
