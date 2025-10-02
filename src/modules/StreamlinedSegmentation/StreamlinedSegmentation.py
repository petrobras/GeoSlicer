import qt
import slicer
import ctk
import json
import logging
import os
import numpy as np
import qSlicerSegmentationsEditorEffectsPythonQt
import qSlicerSegmentationsModuleWidgetsPythonQt

from distinctipy import distinctipy
from ltrace.slicer import helpers
from ltrace.slicer.app import getApplicationVersion
from ltrace.slicer.application_observables import ApplicationObservables
from ltrace.slicer.lazy import lazy
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, getResourcePath
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.utils.ProgressBarProc import ProgressBarProc
from pathlib import Path
from slicer.util import VTKObservationMixin


try:
    from Test.StreamlinedSegmentationTest import StreamlinedSegmentationTest
except ImportError:
    StreamlinedSegmentationTest = None


MULTIPLE_THRESHOLD_LABEL = "Multiple Threshold"
BOUNDARY_REMOVAL_LABEL = "Boundary removal"
EXPAND_SEGMENTS_LABEL = "Expand segments"

from dataclasses import dataclass


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
        self.setHelpUrl("Volumes/BigImage/StreamlinedSegmentation.html")

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
        self.__lastUsedEffect = None

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
        self.segmentationNodeComboBox.currentNodeChanged.connect(self.__onSegmentationNodeChanged)

        self.editor.findChild(qt.QFrame, "EffectsGroupBox").visible = False
        self.editor.findChild(qt.QFrame, "UndoRedoGroupBox").visible = False

        # Get layout named "NodeSelectorLayout" and add the custom volume selector
        layout = self.editor.findChild(qt.QGridLayout, "NodeSelectorLayout")

        self.customVolumeComboBox = hierarchyVolumeInput(
            onChange=self.onInputChanged, nodeTypes=["vtkMRMLScalarVolumeNode"], hasNone=True
        )

        self.startOverButton = qt.QPushButton("Start over")
        cancelIcon = slicer.app.style().standardIcon(qt.QStyle.SP_ArrowLeft)

        self.startOverButton.setIcon(cancelIcon)
        self.startOverButton.enabled = False
        self.startOverButton.clicked.connect(self.onStartOverButtonClicked)
        self.startOverButton.setToolTip(
            "Create a new volume and go back to multiple threshold effect (current segmentation will remain)"
        )

        self.addBackgroundCheckBox = qt.QCheckBox("Add background")
        self.addBackgroundCheckBox.setToolTip("Add background segment")
        self.addBackgroundCheckBox.checked = False
        self.addBackgroundCheckBox.visible = False
        self.addBackgroundCheckBox.stateChanged.connect(self.__onAddBackgroundCheckBoxChanged)
        self.addBackgroundCheckBox.objectName = "Add Background CheckBox"

        label = qt.QLabel("Input:")
        layout.addWidget(label, 0, 0)
        layout.addWidget(self.customVolumeComboBox, 0, 1)
        layout.addWidget(self.startOverButton, 0, 2)
        layout.addWidget(self.addBackgroundCheckBox, 1, 1)

        switchToSegmentationsButton = self.editor.findChild(qt.QToolButton, "SwitchToSegmentationsButton")
        switchToSegmentationsButton.setVisible(False)

        tableView = self.editor.findChild(qt.QTableView, "SegmentsTable")
        tableView.setColumnHidden(0, True)
        self.editor.findChild(qt.QPushButton, "AddSegmentButton").visible = False
        self.editor.findChild(qt.QPushButton, "RemoveSegmentButton").visible = False
        self.editor.findChild(slicer.qMRMLSegmentationShow3DButton, "Show3DButton").visible = False

        self.multipleThresholdEffect = self.editor.effectByName(MULTIPLE_THRESHOLD_LABEL).self()
        self.boundaryRemovalEffect = self.editor.effectByName(BOUNDARY_REMOVAL_LABEL).self()
        self.expandSegmentsEffect = self.editor.effectByName(EXPAND_SEGMENTS_LABEL).self()
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

        self.logic = StreamlinedSegmentationLogic(parent=self.parent)
        self.logic.processFinished.connect(self.onCLIFinished)
        self.multiFinishedTimer = qt.QTimer()
        self.multiFinishedTimer.setSingleShot(True)
        self.multiFinishedTimer.setInterval(100)

        self.enter()

    def onApplyButtonClicked(self):
        lazyData = lazy.data(self.volumeSelector.currentNode())

        self.logic.apply(lazyData, self.exportPathEdit.currentPath, progress_bar=self.cliProgressBar)
        helpers.save_path(self.exportPathEdit)

    def onStartOverButtonClicked(self, mode: bool) -> None:
        self.handleStartOver()

    def handleStartOver(self):
        self.segmentationNodeComboBox.setCurrentNode(None)
        self.sourceVolumeNodeComboBox.setCurrentNode(None)
        self.onInputChanged(-1)

    def __onAddBackgroundCheckBoxChanged(self, state: qt.Qt.CheckState) -> None:
        # Check if current effect is the first one (multiple threshold)
        if self.editor.activeEffect().name.lower() != MULTIPLE_THRESHOLD_LABEL.lower():
            return

        createBackgroundSegment = state == qt.Qt.Checked
        self.__populateSegments(self.segmentationNodeComboBox.currentNode(), createBackgroundSegment)

    def onMultipleThresholdFinished(self):
        source = self.sourceVolumeNodeComboBox.currentNode()
        source_dtype = slicer.util.arrayFromVolume(source).dtype
        if np.issubdtype(source_dtype, np.integer):
            dtype_min = np.iinfo(source_dtype).min
        elif np.issubdtype(source_dtype, np.floating):
            dtype_min = np.finfo(source_dtype).min  # most negative float

        self.logic.multipleThresholds = self.multipleThresholdEffect.transitions.tolist()
        self.logic.multipleThresholds[0] = dtype_min

        self.editor.setActiveEffectByName(BOUNDARY_REMOVAL_LABEL)

        def afterWait():
            with ProgressBarProc() as pb:
                pb.setMessage("Initializing boundary removal")

                self.__updateSegmentsVisibility(microporosity=True, others=False)

                self.addBackgroundCheckBox.visible = False

                self.boundaryRemovalEffect.initialize()
                self.boundaryRemovalEffect.initializeButton.visible = False

        self.multiFinishedTimer.timeout.disconnect()
        self.multiFinishedTimer.timeout.connect(afterWait)
        self.multiFinishedTimer.start()

    def onBoundaryRemovalFinished(self):
        self.logic.boundaryThresholds = self.boundaryRemovalEffect.appliedMinMax
        with ProgressBarProc() as pb:
            self.editor.setActiveEffectByName(EXPAND_SEGMENTS_LABEL)
            self.addBackgroundCheckBox.visible = False
            pb.setMessage("Expanding segments")

            self.__updateSegmentsVisibility(microporosity=False, others=True)

            self.expandSegmentsEffect.applyButton.click()

    def getParentLazyNode(self):
        node = self.customVolumeComboBox.currentNode()
        if node is None:
            return None

        parentLazyNodeId = node.GetAttribute("ParentLazyNode")
        if parentLazyNodeId:
            lazyNode = slicer.mrmlScene.GetNodeByID(parentLazyNodeId)
            if lazyNode:
                return lazyNode
        return None

    def __updateSegmentsVisibility(self, microporosity: bool, others: bool) -> None:
        display = self.segmentationNodeComboBox.currentNode().GetDisplayNode()
        display.SetSegmentVisibility("Background", others)
        display.SetSegmentVisibility("Macroporosity", others)
        display.SetSegmentVisibility("Microporosity", microporosity)
        display.SetSegmentVisibility("Solid", others)
        display.SetSegmentVisibility("High Attenuation", others)

    def onExpandSegmentsFinished(self):
        with ProgressBarProc() as pb:
            self.editor.setActiveEffectByName("")
            self.addBackgroundCheckBox.visible = False
            self.__updateSegmentsVisibility(microporosity=True, others=True)
            segmentationNode = self.segmentationNodeComboBox.currentNode()
            segmentationNode.RemoveAttribute("StreamlinedSegmentation")
            if self.getParentLazyNode():
                self.applyGroup.visible = True
                self.volumeSelector.setCurrentNode(self.getParentLazyNode())
            else:
                self.customVolumeComboBox.setCurrentNode(None)
                self.handleStartOver()

    def __removeWorkingSegmentation(self):
        segmentationNode = self.segmentationNodeComboBox.currentNode()
        if segmentationNode is None:
            return

        attribute = segmentationNode.GetAttribute("StreamlinedSegmentation")
        if attribute is None:
            return

        with helpers.BlockSignals(self.segmentationNodeComboBox):
            logging.info("Removing working segmentation node...")
            self.segmentationNodeComboBox.setCurrentNode(None)
            slicer.mrmlScene.RemoveNode(segmentationNode)

    def onInputChanged(self, itemId: int) -> None:
        sourceNode = self.customVolumeComboBox.currentNode()
        self.startOverButton.enabled = bool(sourceNode)
        self.applyGroup.visible = False
        self.addBackgroundCheckBox.visible = True

        self.__removeWorkingSegmentation()
        self.editor.setActiveEffectByName("")

        if sourceNode is None:
            return

        segmentationNode = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLSegmentationNode", sourceNode.GetName() + "_Segmentation"
        )
        segmentationNode.CreateDefaultDisplayNodes()
        segmentationNode.SetAttribute("StreamlinedSegmentation", "True")
        self.__populateSegments(segmentationNode, self.addBackgroundCheckBox.isChecked())

        self.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        self.sourceVolumeNodeComboBox.setCurrentNode(sourceNode)
        self.editor.setActiveEffectByName(MULTIPLE_THRESHOLD_LABEL)

    def __populateSegments(self, segmentationNode: slicer.vtkMRMLSegmentationNode, withBackground: bool):
        segmentNames = ["Background", "Macroporosity", "Microporosity", "Solid", "High Attenuation"]

        # Remove previous segments:
        segmentation = segmentationNode.GetSegmentation()
        segmentation.RemoveAllSegments()

        if not withBackground:
            segmentNames = segmentNames[1:]

        colors = []
        for segmentName in segmentNames:
            if segmentName == "Background":
                color = (0, 0, 0)
            elif segmentName == "Macroporosity":
                color = (1, 0, 0)
            else:
                previousColors = colors[1:] if withBackground else colors
                color = distinctipy.get_colors(1, previousColors)[0]

            colors.append(color)
            segmentation.AddEmptySegment(segmentName, segmentName, color)

        self.logic.segmentNames = segmentNames
        self.logic.segmentColors = colors

    def __onSegmentationNodeChanged(self):
        if self.segmentationNodeComboBox.currentNode() is not None:
            return

        self.customVolumeComboBox.setCurrentNode(None)
        self.handleStartOver()

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

        self.__enterEffect()

    def __enterEffect(self):
        if not self.__lastUsedEffect:
            self.editor.updateWidgetFromMRML()
            self.selectParameterNode()
            return

        self.editor.setActiveEffectByName(self.__lastUsedEffect)
        self.editor.updateWidgetFromMRML()
        self.editor.setupViewObservations()

        if self.__lastUsedEffect.lower() == MULTIPLE_THRESHOLD_LABEL.lower():
            if self.segmentationNodeComboBox.currentNode() is not None:
                self.__updateSegmentsVisibility(microporosity=True, others=True)
        elif self.__lastUsedEffect.lower() == BOUNDARY_REMOVAL_LABEL.lower():
            self.__updateSegmentsVisibility(microporosity=True, others=False)
            self.boundaryRemovalEffect.initialize()
            self.boundaryRemovalEffect.initializeButton.visible = True
        elif self.__lastUsedEffect.lower() == EXPAND_SEGMENTS_LABEL.lower():
            self.__updateSegmentsVisibility(microporosity=True, others=True)

    def exit(self):
        self.__lastUsedEffect = self.editor.activeEffect().name if self.editor.activeEffect() is not None else None
        self.editor.setActiveEffect(None)
        self.editor.removeViewObservations()

    def onSceneStartClose(self, caller, event):
        self.parameterSetNode = None
        self.editor.setSegmentationNode(None)
        self.editor.removeViewObservations()

    def onSceneEndClose(self, caller, event):
        if self.parent.isEntered:
            self.selectParameterNode()
            self.editor.setupViewObservations()
            self.editor.updateWidgetFromMRML()

    def onSceneEndImport(self, caller, event):
        if self.parent.isEntered:
            self.selectParameterNode()
            self.editor.updateWidgetFromMRML()

    def onCLIFinished(self, lazyOutputNode):
        segmentationNode = self.segmentationNodeComboBox.currentNode()
        if segmentationNode is not None:
            segmentationNode.GetDisplayNode().SetVisibility(False)

        with helpers.BlockSignals(self.customVolumeComboBox):
            self.customVolumeComboBox.setCurrentNode(None)
            self.handleStartOver()

        self.__lastUsedEffect = None

        lazy.set_visibility(lazyOutputNode, True)

    def cleanup(self):
        super().cleanup()
        self.removeObservers()
        self.multipleThresholdEffect.applyFinishedCallback = lambda: None
        self.boundaryRemovalEffect.applyFinishedCallback = lambda: None
        self.expandSegmentsEffect.applyFinishedCallback = lambda: None
        self.multiFinishedTimer.stop()
        self.multiFinishedTimer.timeout.disconnect()
        self.segmentationNodeComboBox.setCurrentNode(None)
        self.sourceVolumeNodeComboBox.setCurrentNode(None)
        ApplicationObservables().applicationLoadFinished.disconnect(self.__onApplicationLoadFinished)


class StreamlinedSegmentationLogic(LTracePluginLogic):
    processFinished = qt.Signal(object)

    def __init__(self, parent):
        LTracePluginLogic.__init__(self, parent)
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
            node = self.outputLazyData.to_node()
            self.processFinished.emit(node)

        if self.__cli_node_modified_observer is not None:
            self._cli_node.RemoveObserver(self.__cli_node_modified_observer)
            self.__cli_node_modified_observer = None

        self._cli_node = None
