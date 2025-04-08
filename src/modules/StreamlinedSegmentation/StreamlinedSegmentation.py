import os
from pathlib import Path

import qt
import slicer
import json
import ctk
from slicer.util import VTKObservationMixin
import qSlicerSegmentationsEditorEffectsPythonQt
import qSlicerSegmentationsModuleWidgetsPythonQt

from ltrace.slicer.app import getApplicationVersion
from ltrace.utils.ProgressBarProc import ProgressBarProc
from distinctipy import distinctipy
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer.application_observables import ApplicationObservables
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, getResourcePath
from ltrace.slicer.lazy import lazy
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer import helpers


try:
    from Test.StreamlinedSegmentationTest import StreamlinedSegmentationTest
except ImportError:
    StreamlinedSegmentationTest = None


class StreamlinedSegmentation(LTracePlugin):
    SETTING_KEY = "StreamlinedSegmentation"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Virtual Segmentation Flow"
        self.parent.categories = ["Tools", "MicroCT"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = (
            f"file:///{(getResourcePath('manual') / 'Modules/Volumes/StreamlinedSegmentation.html').as_posix()}"
        )

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class StreamlinedSegmentationWidget(LTracePluginWidget, VTKObservationMixin):
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

        #
        # Segment editor widget
        #
        self.editor = qSlicerSegmentationsModuleWidgetsPythonQt.qMRMLSegmentEditorWidget()
        self.layout.addWidget(self.editor)
        self.editor.setMaximumNumberOfUndoStates(0)
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
        sourceVolumeNodeLabel.visible = False

        segmentationNodeLabel = self.editor.findChild(qt.QLabel, "SegmentationNodeLabel")
        segmentationNodeLabel.visible = False

        self.sourceVolumeNodeComboBox = self.editor.findChild(slicer.qMRMLNodeComboBox, "SourceVolumeNodeComboBox")
        self.sourceVolumeNodeComboBox.visible = False

        self.segmentationNodeComboBox = self.editor.findChild(slicer.qMRMLNodeComboBox, "SegmentationNodeComboBox")
        self.segmentationNodeComboBox.visible = False

        self.editor.findChild(qt.QFrame, "EffectsGroupBox").visible = False
        self.editor.findChild(qt.QFrame, "UndoRedoGroupBox").visible = False

        # Get layout named "NodeSelectorLayout" and add the custom volume selector
        layout = self.editor.findChild(qt.QGridLayout, "NodeSelectorLayout")

        self.customVolumeComboBox = hierarchyVolumeInput(
            onChange=self.onInputChanged, nodeTypes=["vtkMRMLScalarVolumeNode"]
        )

        self.startOverButton = qt.QPushButton("Start over")
        cancelIcon = slicer.app.style().standardIcon(qt.QStyle.SP_ArrowLeft)

        self.startOverButton.setIcon(cancelIcon)
        self.startOverButton.enabled = False
        self.startOverButton.clicked.connect(self.onStartOver)
        self.startOverButton.setToolTip(
            "Create a new volume and go back to multiple threshold effect (current segmentation will remain)"
        )
        label = qt.QLabel("Input:")
        layout.addWidget(label, 0, 0)
        layout.addWidget(self.customVolumeComboBox, 0, 1)
        layout.addWidget(self.startOverButton, 0, 2)

        switchToSegmentationsButton = self.editor.findChild(qt.QToolButton, "SwitchToSegmentationsButton")
        switchToSegmentationsButton.setVisible(False)

        tableView = self.editor.findChild(qt.QTableView, "SegmentsTable")
        tableView.setColumnHidden(0, True)
        self.editor.findChild(qt.QPushButton, "AddSegmentButton").visible = False
        self.editor.findChild(qt.QPushButton, "RemoveSegmentButton").visible = False
        self.editor.findChild(slicer.qMRMLSegmentationShow3DButton, "Show3DButton").visible = False

        self.multipleThresholdEffect = self.editor.effectByName("Multiple Threshold").self()
        self.boundaryRemovalEffect = self.editor.effectByName("Boundary removal").self()
        self.expandSegmentsEffect = self.editor.effectByName("Expand segments").self()
        self.multipleThresholdEffect.applyFinishedCallback = self.onMultipleThresholdFinished
        self.boundaryRemovalEffect.applyFinishedCallback = self.onBoundaryRemovalFinished
        self.expandSegmentsEffect.applyFinishedCallback = self.onExpandSegmentsFinished
        self.multipleThresholdEffect.applyAllSupported = False
        self.boundaryRemovalEffect.applyAllSupported = False
        self.expandSegmentsEffect.applyAllSupported = False

        self.applyGroup = qt.QGroupBox()
        self.applyGroup.visible = False
        applyLayout = qt.QFormLayout(self.applyGroup)

        self.volumeSelector = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLTextNode"],
            tooltip="Select the image within the NetCDF dataset to preview.",
        )
        self.volumeSelector.selectorWidget.addNodeAttributeFilter("LazyNode", "1")

        self.exportPathEdit = ctk.ctkPathLineEdit()
        self.exportPathEdit.filters = ctk.ctkPathLineEdit.Files | ctk.ctkPathLineEdit.Writable
        self.exportPathEdit.nameFilters = ["*.nc"]
        self.exportPathEdit.settingKey = "VirtualSegmentation/OutputPath"
        self.exportPathEdit.setToolTip("Select the output path for the resulting .nc image")

        self.applyButton = qt.QPushButton("Apply segmentation on full volume")
        self.applyButton.toolTip = "Run the algorithm on the whole image"
        self.applyButton.clicked.connect(self.onApplyButtonClicked)
        self.cliProgressBar = LocalProgressBar()
        self.cliProgressBar.visible = False

        applyLayout.addRow("Input Image:", self.volumeSelector)
        applyLayout.addRow("Output Path:", self.exportPathEdit)
        applyLayout.addRow(self.applyButton)
        applyLayout.addRow(self.cliProgressBar)
        self.layout.addWidget(self.applyGroup)
        self.layout.addStretch(1)

        ApplicationObservables().applicationLoadFinished.connect(self.__onApplicationLoadFinished)

        self.logic = StreamlinedSegmentationLogic()
        self.multiFinishedTimer = qt.QTimer()
        self.multiFinishedTimer.setSingleShot(True)
        self.multiFinishedTimer.setInterval(100)

        self.enter()

    def onApplyButtonClicked(self):
        lazyData = lazy.data(self.volumeSelector.currentNode())

        self.logic.apply(lazyData, self.exportPathEdit.currentPath, progress_bar=self.cliProgressBar)
        helpers.save_path(self.exportPathEdit)

    def onStartOver(self, _=None):
        self.onInputChanged(None)

    def onMultipleThresholdFinished(self):
        self.logic.multipleThresholds = self.multipleThresholdEffect.transitions.tolist()
        pb = ProgressBarProc()
        pb.setMessage("Initializing boundary removal")
        self.editor.setActiveEffectByName("Boundary removal")

        def afterWait():
            with pb:
                pb.setMessage("Initializing boundary removal")

                # Make all segments invisible except for microporosity
                display = self.segmentationNodeComboBox.currentNode().GetDisplayNode()
                display.SetSegmentVisibility("Macroporosity", False)
                display.SetSegmentVisibility("Microporosity", True)
                display.SetSegmentVisibility("Solid", False)
                display.SetSegmentVisibility("Reference Solid", False)

                self.boundaryRemovalEffect.initialize()
                self.boundaryRemovalEffect.initializeButton.visible = False

        self.multiFinishedTimer.timeout.connect(afterWait)
        self.multiFinishedTimer.start()

    def onBoundaryRemovalFinished(self):
        self.logic.boundaryThresholds = self.boundaryRemovalEffect.appliedMinMax
        self.pb = ProgressBarProc()
        self.pb.setMessage("Expanding segments")
        self.editor.setActiveEffectByName("Expand segments")
        display = self.segmentationNodeComboBox.currentNode().GetDisplayNode()

        # Make all segments visible except for microporosity
        display = self.segmentationNodeComboBox.currentNode().GetDisplayNode()
        display.SetSegmentVisibility("Macroporosity", True)
        display.SetSegmentVisibility("Microporosity", False)
        display.SetSegmentVisibility("Solid", True)
        display.SetSegmentVisibility("Reference Solid", True)

        self.expandSegmentsEffect.applyButton.click()

    def getParentLazyNode(self):
        node = self.customVolumeComboBox.currentNode()
        parentLazyNodeId = node.GetAttribute("ParentLazyNode")
        if parentLazyNodeId:
            lazyNode = slicer.mrmlScene.GetNodeByID(parentLazyNodeId)
            if lazyNode:
                return lazyNode
        return None

    def onExpandSegmentsFinished(self):
        with self.pb:
            self.editor.setActiveEffectByName("")
            display = self.segmentationNodeComboBox.currentNode().GetDisplayNode()
            display.SetSegmentVisibility("Microporosity", True)
            if self.getParentLazyNode():
                self.applyGroup.visible = True
                self.volumeSelector.setCurrentNode(self.getParentLazyNode())

    def onInputChanged(self, _):
        sourceNode = self.customVolumeComboBox.currentNode()
        self.startOverButton.enabled = bool(sourceNode)
        if not sourceNode:
            return
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLSegmentationNode", sourceNode.GetName() + "_Segmentation"
        )
        segmentationNode.CreateDefaultDisplayNodes()
        segmentNames = ["Macroporosity", "Microporosity", "Solid", "Reference Solid"]

        colors = []
        for i, segmentName in enumerate(segmentNames):
            if i == 0:
                color = (1, 0, 0)
            else:
                color = distinctipy.get_colors(1, colors)[0]
            colors.append(color)
            segmentation = segmentationNode.GetSegmentation()
            segmentation.AddEmptySegment(segmentName)
            segmentation.GetSegment(segmentName).SetColor(color)

        self.logic.segmentNames = segmentNames
        self.logic.segmentColors = colors

        self.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        self.sourceVolumeNodeComboBox.setCurrentNode(sourceNode)
        self.editor.setActiveEffectByName("Multiple Threshold")

    def __onApplicationLoadFinished(self):
        # Connect observers to scene events
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndImportEvent, self.onSceneEndImport)
        self.activateEditorRegisteredCallback()
        ApplicationObservables().applicationLoadFinished.disconnect(self.__onApplicationLoadFinished)

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
        """Runs whenever the module is reopened"""
        super().enter()
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
        self.multipleThresholdEffect.applyFinishedCallback = lambda: None
        self.boundaryRemovalEffect.applyFinishedCallback = lambda: None
        self.expandSegmentsEffect.applyFinishedCallback = lambda: None
        self.multiFinishedTimer.stop()
        self.multiFinishedTimer.timeout.disconnect()
        ApplicationObservables().applicationLoadFinished.disconnect(self.__onApplicationLoadFinished)


class StreamlinedSegmentationLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.segmentNames = None
        self.segmentColors = None
        self.multipleThresholds = None
        self.boundaryThresholds = None

    def apply(self, lazyData, outputPath, progress_bar=None):
        lazyDataProtocol = lazyData.get_protocol()
        lazyDataHost = lazyDataProtocol.host()

        params = {
            "input_url": lazyData.url,
            "input_var": lazyData.var,
            "input_host": lazyDataHost.to_dict(),
            "output_url": outputPath,
            "multiple_thresholds": self.multipleThresholds,
            "boundary_thresholds": self.boundaryThresholds,
            "colors": self.segmentColors,
            "names": self.segmentNames,
            "geoslicer_version": getApplicationVersion(),
        }
        cli_config = {
            "params": json.dumps(params),
        }
        self.outputLazyData = lazy.LazyNodeData("file://" + params["output_url"], params["input_var"] + "_segmented")

        progress_bar.visible = True

        self._cli_node = slicer.cli.run(
            slicer.modules.streamlinedsegmentationcli,
            None,
            cli_config,
            wait_for_completion=False,
        )
        self.__cli_node_modified_observer = self._cli_node.AddObserver(
            "ModifiedEvent", lambda c, ev, info=cli_config: self.__on_cli_modified_event(c, ev, info)
        )

        if progress_bar is not None:
            progress_bar.setCommandLineModuleNode(self._cli_node)

    def __on_cli_modified_event(self, caller, event, info):
        if caller is None:
            self._cli_node = None
            return

        if caller.IsBusy():
            return

        if caller.GetStatusString() == "Completed":
            self.outputLazyData.to_node()

        if self.__cli_node_modified_observer is not None:
            self._cli_node.RemoveObserver(self.__cli_node_modified_observer)
            self.__cli_node_modified_observer = None

        self._cli_node = None
