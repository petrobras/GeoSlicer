import os
from pathlib import Path

import qSlicerSegmentationsEditorEffectsPythonQt
import qSlicerSegmentationsModuleWidgetsPythonQt
import qt
import slicer
from distinctipy import distinctipy
from slicer.util import VTKObservationMixin

from CustomizedEffects.Margin import SegmentEditorMarginEffect
from CustomizedEffects.Threshold import SegmentEditorThresholdEffect
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, getResourcePath

# Checks if closed source code is available
try:
    from Test.CustomizedSegmentEditorTest import CustomizedSegmentEditorTest
except ImportError:
    CustomizedSegmentEditorTest = None


class CustomizedSegmentEditor(LTracePlugin):
    SETTING_KEY = "CustomizedSegmentEditor"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Manual Segmentation"
        self.parent.categories = ["Tools", "Segmentation", "Thin Section", "ImageLog", "Core", "MicroCT", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = (
            f"file:///{(getResourcePath('manual') / 'Modules/Thin_section/SegmentEditor.html').as_posix()}"
        )

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class CustomizedSegmentEditorWidget(LTracePluginWidget, VTKObservationMixin):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.parameterSetNode = None
        self.editor = None
        self.__tag = None

    def setup(self):
        LTracePluginWidget.setup(self)

        # Add margin to the sides
        self.layout.setContentsMargins(4, 0, 4, 0)

        # TODO: For some reason the instance() function cannot be called as a class function although it's static
        factory = qSlicerSegmentationsEditorEffectsPythonQt.qSlicerSegmentEditorEffectFactory()
        self.effectFactorySingleton = factory.instance()

        # Edit threshold effect
        for effect in self.effectFactorySingleton.registeredEffects():
            if effect.name == "Threshold":
                effectFilename = SegmentEditorThresholdEffect.__file__
                effect.setPythonSource(effectFilename.replace("\\", "/"))
                effect.self().register()
            elif effect.name == "Margin":
                effectFilename = SegmentEditorMarginEffect.__file__
                effect.setPythonSource(effectFilename.replace("\\", "/"))
                effect.self().register()

        #
        # Segment editor widget
        #
        self.editor = qSlicerSegmentationsModuleWidgetsPythonQt.qMRMLSegmentEditorWidget()
        self.layout.addWidget(self.editor)
        self.editor.setMaximumNumberOfUndoStates(10)
        # Set parameter node first so that the automatic selections made when the scene is set are saved
        # Note: Commented because preload make this unnecessary
        ### self.selectParameterNode()
        self.editor.setMRMLScene(slicer.mrmlScene)

        # Observe editor effect registrations to make sure that any effects that are registered
        # later will show up in the segment editor widget. For example, if Segment Editor is set
        # as startup module, additional effects are registered after the segment editor widget is created.
        # Increasing buttons width to improve visibility
        specifyGeometryButton = self.editor.findChild(qt.QToolButton, "SpecifyGeometryButton")
        specifyGeometryButton.setVisible(False)

        sliceRotateWarningButton = self.editor.findChild(qt.QToolButton, "SliceRotateWarningButton")
        sliceRotateWarningButton.setFixedWidth(100)

        addSegmentButton = self.editor.findChild(qt.QPushButton, "AddSegmentButton")
        addSegmentButton.clicked.connect(self.onAddSegmentButton)

        sourceVolumeNodeLabel = self.editor.findChild(qt.QLabel, "SourceVolumeNodeLabel")
        sourceVolumeNodeLabel.setText("Input image:")

        segmentationNodeLabel = self.editor.findChild(qt.QLabel, "SegmentationNodeLabel")
        segmentationNodeLabel.setText("Output segmentation:")

        self.sourceVolumeNodeComboBox = self.editor.findChild(slicer.qMRMLNodeComboBox, "SourceVolumeNodeComboBox")
        self.sourceVolumeNodeComboBox.removeEnabled = False
        self.sourceVolumeNodeComboBox.renameEnabled = False
        self.sourceVolumeNodeComboBox.currentNodeChanged.connect(self.onSourceVolumeNodeChanged)

        self.segmentationNodeComboBox = self.editor.findChild(slicer.qMRMLNodeComboBox, "SegmentationNodeComboBox")
        self.segmentationNodeComboBox.removeEnabled = False

        switchToSegmentationsButton = self.editor.findChild(qt.QToolButton, "SwitchToSegmentationsButton")
        switchToSegmentationsButton.setVisible(False)

        self.layout.addStretch()

        self.configureEffects()

        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndImportEvent, self.onSceneEndImport)
        self.activateEditorRegisteredCallback()

    def activateEditorRegisteredCallback(self):
        self.effectFactorySingleton.effectRegistered.connect(self.editorEffectRegistered)

    def deactivateEditorRegisteredCallback(self):
        self.effectFactorySingleton.effectRegistered.disconnect(self.editorEffectRegistered)

    def onAddSegmentButton(self):
        segmentation = self.segmentationNodeComboBox.currentNode().GetSegmentation()
        nSegments = segmentation.GetNumberOfSegments()

        existentColors = []
        for i in range(nSegments):
            segmentID = segmentation.GetNthSegmentID(i)
            existentColors.append(segmentation.GetSegment(segmentID).GetColor())

        segmentID = segmentation.GetNthSegmentID(nSegments - 1)
        newColor = distinctipy.get_colors(1, existentColors)[0]
        segmentation.GetSegment(segmentID).SetColor(newColor)

    def onSourceVolumeNodeChanged(self, node):
        color_support = node and node.GetImageData() and node.GetImageData().GetNumberOfScalarComponents() == 3
        self.configureColorSupport(color_support=color_support)

    def configureEffectsForThinSectionEnvironment(self):
        self.selectParameterNodeByTag("ThinSectionEnv")

        self.editor.setEffectNameOrder(
            [
                "Paint",
                "Draw",
                "Erase",
                "Grow from seeds",
                "Margin",
                "Smoothing",
                "Scissors",
                "Islands",
                "Logical operators",
                "Mask Image",
                "Connectivity",
                "Level tracing",
                "Smart foreground",
                "Color threshold",
                "Boundary removal",
            ]
        )
        self.editor.unorderedEffectsVisible = False

    # WARNING this should be called only once at the initialization
    def configureEffects(self, color_support=False):
        effects = [
            "Threshold",
            "Paint",
            "Draw",
            "Erase",
            "Level tracing",
            "Grow from seeds",
            "Fill between slices",
            "Margin",
            "Smoothing",
            "Scissors",
            "Islands",
            "Logical operators",
            "Mask Image",
            "Multiple Threshold",
            "Connectivity",
            "Boundary removal",
            "Expand segments",
            "Sample segmentation",
            "Smart foreground",
        ]
        if color_support:
            effects.append("Color threshold")
        self.editor.setEffectNameOrder(effects)
        self.editor.unorderedEffectsVisible = False

    def configureColorSupport(self, color_support=False):
        effects = self.editor.effectNameOrder()
        effects = list(effects)
        if color_support and "Color threshold" not in effects:
            effects.append("Color threshold")
        elif not color_support and "Color threshold" in effects:
            effects.remove("Color threshold")
        self.editor.setEffectNameOrder(effects)
        self.editor.unorderedEffectsVisible = False

    def editorEffectRegistered(self, effect=None) -> None:
        """Callback for registres effect signal. A QTimer is used to avoid multiple calls at once when multiple effects are registered.
        The method 'qMRMLSegmentEditorWidget.updateEffectList' causes some widget's to update, it might result in some widgets blinking in the background if parent tree is not defined.
        """
        self.editor.updateEffectList()

    def selectParameterNodeByTag(self, tag: str):
        if not tag:
            raise ValueError("Parameter node 'tag' is empty")

        self.__tag = tag
        self.selectParameterNode()
        instance = self.editor.effectByName("Mask Image")
        effect = instance.self()
        effect.setEnvironment(self.__tag)

    def selectParameterNode(self):
        # Select parameter set node if one is found in the scene, and create one otherwise
        # Note: join in case of whitespaces
        if not self.__tag:
            segmentEditorSingletonTag = "_".join([*slicer.util.selectedModule().split(" "), "SegmentEditor"])
        else:
            segmentEditorSingletonTag = f"{self.__tag}_SegmentEditor"

        segmentEditorNode = slicer.mrmlScene.GetSingletonNode(segmentEditorSingletonTag, "vtkMRMLSegmentEditorNode")
        if segmentEditorNode is None:
            segmentEditorNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLSegmentEditorNode")
            segmentEditorNode.UnRegister(None)
            segmentEditorNode.SetSingletonTag(segmentEditorSingletonTag)
            segmentEditorNode = slicer.mrmlScene.AddNode(segmentEditorNode)

        if self.parameterSetNode == segmentEditorNode:
            # nothing changed
            return

        self.parameterSetNode = segmentEditorNode
        self.editor.setMRMLSegmentEditorNode(self.parameterSetNode)

    def enter(self) -> None:
        super().enter()
        """Runs whenever the module is reopened"""
        if self.editor.turnOffLightboxes():
            slicer.util.warningDisplay(
                "Segment Editor is not compatible with slice viewers in light box mode." "Views are being reset.",
                windowTitle="Segment Editor",
            )

        # Allow switching between effects and selected segment using keyboard shortcuts
        self.editor.installKeyboardShortcuts()

        # Set parameter set node if absent
        self.selectParameterNode()
        self.editor.updateWidgetFromMRML()

    def exit(self):
        self.editor.setActiveEffect(None)
        self.editor.uninstallKeyboardShortcuts()
        self.editor.removeViewObservations()

    def onSceneStartClose(self, caller, event):
        self.parameterSetNode = None
        self.editor.setSegmentationNode(None)
        self.editor.removeViewObservations()

    def onSceneEndClose(self, caller, event):
        if self.parent.isEntered:
            self.selectParameterNode()
            self.editor.updateWidgetFromMRML()

    def onSceneEndImport(self, caller, event):
        if self.parent.isEntered:
            self.selectParameterNode()
            self.editor.updateWidgetFromMRML()

    def cleanup(self):
        super().cleanup()
        self.removeObservers()
        self.deactivateEditorRegisteredCallback()
