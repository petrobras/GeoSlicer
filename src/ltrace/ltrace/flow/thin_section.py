import sys

from ltrace.flow.framework import (
    FlowWidget,
    FlowState,
    FlowStep,
)
from ltrace.flow.util import (
    createSimplifiedSegmentEditor,
    onSegmentEditorEnter,
    onSegmentEditorExit,
)

from ltrace import assets_utils as assets
from ltrace.slicer import helpers, widgets
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widget.pixel_size_editor import PixelSizeEditor
from ltrace.units import global_unit_registry as ureg
from ltrace.utils.callback import Callback
from ltrace.utils.ProgressBarProc import ProgressBarProc
from ltrace.slicer.cli_queue import CliQueue

import ctk
import qt
import slicer
import importlib


Segmenter = helpers.LazyLoad("Segmenter")
QEMSCANLoader = helpers.LazyLoad("QEMSCANLoader")
ThinSectionLoader = helpers.LazyLoad("ThinSectionLoader")


class Load(FlowStep):
    KEY = "load"

    def __init__(self, hasPx: bool):
        self.hasPx = hasPx
        if hasPx:
            self.TITLE = "Load PP/PX"
            self.HELP = """
<h3>Load PP/PX</h3>
Choose the PP (plane polarized) and PX (cross polarized) image files to load.
"""

            self.BACK_OFF_STATE = (False, "This is the first step")
            self.SKIP_OFF_STATE = (False, "You must load the images before you can continue")
            self.NEXT_OFF_STATE = (False, "You must select the images before you can continue")
            self.NEXT_ON_STATE = (True, "Load selected images")
        else:
            self.TITLE = "Load PP"
            self.HELP = """
<h3>Load PP</h3>
Choose the PP (plane polarized) image file to load.
"""

            self.BACK_OFF_STATE = (False, "This is the first step")
            self.SKIP_OFF_STATE = (False, "You must load the image before you can continue")
            self.NEXT_OFF_STATE = (False, "You must select the image before you can continue")
            self.NEXT_ON_STATE = (True, "Load selected image")

    def setup(self):
        widget = qt.QFrame()
        layout = qt.QFormLayout(widget)
        self.ppFileSelector = ctk.ctkPathLineEdit()
        self.ppFileSelector.setToolTip("Choose the PP image file.")
        self.ppFileSelector.settingKey = "PpPxFlow/PpFileSelector"
        self.ppFileSelector.currentPathChanged.connect(self.onPathChanged)
        layout.addRow("PP:", self.ppFileSelector)

        if self.hasPx:
            self.pxFileSelector = ctk.ctkPathLineEdit()
            self.pxFileSelector.setToolTip("Choose the PX image file.")
            self.pxFileSelector.settingKey = "PpPxFlow/PxFileSelector"
            self.pxFileSelector.currentPathChanged.connect(self.onPathChanged)
            layout.addRow("PX:", self.pxFileSelector)

        return widget

    def enter(self):
        self.nav.setButtonsState(self.BACK_OFF_STATE, self.SKIP_OFF_STATE, self.NEXT_OFF_STATE)
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)
        self.onPathChanged()

    def exit(self):
        pass

    def next(self):
        with ProgressBarProc() as pb:
            logic = slicer.util.getModuleLogic("ThinSectionLoader")

            path = self.ppFileSelector.currentPath
            pb.setMessage("Loading PP image")
            pb.setProgress(0)
            params = ThinSectionLoader.ThinSectionLoaderWidget.LoadParameters(path)
            imageInfo = logic.load(params)

            pp = imageInfo["node"]

            try:
                detectedScale = imageInfo["scale_size_mm"], imageInfo["scale_size_px"]
            except KeyError:
                detectedScale = None

            if self.hasPx:
                pb.setMessage("Loading PX image")
                pb.setProgress(50)
                path = self.pxFileSelector.currentPath
                params = ThinSectionLoader.ThinSectionLoaderWidget.LoadParameters(path, automaticImageSpacing=False)
                imageInfo = logic.load(params)
                px = imageInfo["node"]

                # PX should have same spacing as PP
                px.CopyOrientation(pp)

        helpers.save_path(self.ppFileSelector)
        if self.hasPx:
            helpers.save_path(self.pxFileSelector)

        self.state.setVisibility()
        self.state.reset()

        if self.hasPx:
            directoryName = f"{pp.GetName()}_{px.GetName()}_Flow"
        else:
            directoryName = f"{pp.GetName()}_Flow"

        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        dirId = shNode.CreateFolderItem(shNode.GetSceneItemID(), directoryName)

        ppParent = shNode.GetItemParent(shNode.GetItemByDataNode(pp))
        ppParentParent = shNode.GetItemParent(ppParent)

        self.state.dir = dirId
        self.state.addToDir(pp)
        if self.hasPx:
            self.state.addToDir(px)

        shNode.RemoveItem(ppParent)
        shNode.RemoveItem(ppParentParent)

        self.state.pp = pp
        if self.hasPx:
            self.state.px = px
        self.state.detectedScale = detectedScale
        self.nav.next()

    def onPathChanged(self):
        enabled = self.ppFileSelector.currentPath and (not self.hasPx or self.pxFileSelector.currentPath)
        nextState = self.NEXT_ON_STATE if enabled else self.NEXT_OFF_STATE
        self.nav.setButtonsState(self.BACK_OFF_STATE, self.SKIP_OFF_STATE, nextState)


class Scale(FlowStep):
    HELP = """<h3>Scale</h3>
<p>Set the pixel size in mm for the image.</p>
<p>If the image has a scale bar, it may be detected automatically.</p>
<p>If detection fails, use the <b>Measure bar</b> tool to measure the size of the bar in pixels, and then enter the size of the bar in millimeters.</p>
"""
    KEY = "scale"
    TITLE = "Scale"

    BACK_ON_STATE = (True, "Go back to the previous step")
    SKIP_ON_STATE = (True, "Keep the current image spacing")
    NEXT_OFF_STATE = (False, "You must specify the image spacing in order to apply it")
    NEXT_ON_STATE = (True, "Apply this image spacing for the image")

    def __init__(self, hasPx: bool):
        self.hasPx = hasPx

    def setup(self):
        widget = qt.QFrame()
        layout = qt.QFormLayout(widget)
        self.statusLabel = qt.QLabel()
        layout.addRow(self.statusLabel)
        self.pixelSizeEditor = PixelSizeEditor()
        self.pixelSizeEditor.savePixelSizeButton.setVisible(False)
        self.pixelSizeEditor.imageSpacingLineEdit.textChanged.connect(self.onSpacingChanged)
        self.pixelSizeEditor.scaleSizePxRuler.setText("Measure bar")
        layout.addRow(self.pixelSizeEditor)
        return widget

    def enter(self):
        self.pixelSizeEditor.currentNode = self.state.pp
        if self.state.detectedScale is None:
            self.statusLabel.text = "Could not detect scale automatically. Please define it manually."
            self.pixelSizeEditor.setScaleSizeMmText("")
            self.pixelSizeEditor.setScaleSizePxText("")
            self.pixelSizeEditor.setImageSpacingText("")
        else:
            self.statusLabel.text = "Scale detected automatically. Adjust if necessary."
            scaleSizeMm, scaleSizePx = self.state.detectedScale
            self.pixelSizeEditor.setScaleSizeMmText(scaleSizeMm)
            self.pixelSizeEditor.setScaleSizePxText(scaleSizePx)
            self.pixelSizeEditor.scaleSizePxLineEdit.textEdited.emit(scaleSizePx)
        self.onSpacingChanged(self.pixelSizeEditor.imageSpacingLineEdit.text)
        self.state.setVisibility(pp=True)

    def exit(self):
        pass

    def next(self):
        spacing = float(self.pixelSizeEditor.imageSpacingLineEdit.text)
        self.state.pp.SetSpacing(spacing, spacing, spacing)
        if self.hasPx:
            self.state.px.SetSpacing(spacing, spacing, spacing)
        self.nav.next()

    def onSpacingChanged(self, text):
        try:
            float(text)
            nextState = self.NEXT_ON_STATE
        except ValueError:
            nextState = self.NEXT_OFF_STATE
        self.nav.setButtonsState(self.BACK_ON_STATE, self.SKIP_ON_STATE, nextState)


class Register(FlowStep):
    HELP = """<h3>Register</h3>
<p>Register the PP image to the PX image, ensuring they are spacially aligned.</p>
<p>Click the <b>Add</b> button and then click the image to add a marker. Drag the same marker on the other image to ensure the marker is in the same position in both images.</p>
<p>Add more markers until the images are aligned.</p>

"""
    KEY = "register"
    TITLE = "Register"

    BACK_ON_STATE = (True, "Go back to the previous step")
    SKIP_ON_STATE = (True, "Cancel registration and go to next step")
    NEXT_ON_STATE = (True, "Finish registration and go to next step")

    def setup(self):
        moduleWidget = slicer.modules.thinsectionregistration.createNewWidgetRepresentation()
        widget = moduleWidget.self()
        widget.imagesFrame.visible = False
        widget.applyCancelButtons.visible = False
        return moduleWidget

    def enter(self):
        self.state.setVisibility()
        widget = self.widget.self()
        widget.setupDialog()
        widget.volumeDialogSelectors["Fixed"].setCurrentNode(self.state.pp)
        widget.volumeDialogSelectors["Moving"].setCurrentNode(self.state.px)
        widget.onVolumeDialogApply()
        self.nav.setButtonsState(self.BACK_ON_STATE, self.SKIP_ON_STATE, self.NEXT_ON_STATE)

    def exit(self):
        widget = self.widget.self()
        if widget.interfaceFrame.visible:
            widget.cancelRegistration()
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)

    def next(self):
        widget = self.widget.self()
        self.state.px = widget.finishRegistration()
        self.state.addToDir(self.state.px)

        self.nav.next()


class Soi(FlowStep):
    HELP = """<h3>Segment of Interest</h3>
Select the segment of interest (SOI) for the PP/PX images.
<br><br>
All further analysis will be performed inside this region only.
"""
    KEY = "soi"
    TITLE = "SOI"

    BACK_ON_STATE = (True, "Go back to the previous step")
    SKIP_ON_STATE = (True, "Consider the whole image as segment of interest")
    NEXT_ON_STATE = (True, "Confirm segment of interest")

    def setup(self):
        widget, _, self.soiVolumeComboBox, self.soiSegmentComboBox = createSimplifiedSegmentEditor()
        effects = ["Scissors"]
        widget.setEffectNameOrder(effects)
        widget.unorderedEffectsVisible = False
        tableView = widget.findChild(qt.QTableView, "SegmentsTable")
        tableView.setFixedHeight(100)
        return widget

    def enter(self):
        onSegmentEditorEnter(self.widget, "PpPxFlow_Soi")

        sourceNode = self.state.pp or self.state.qemscan
        if self.state.soi is None:
            soiNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", sourceNode.GetName() + "_SOI")
            soiNode.CreateDefaultDisplayNodes()
            segmentation = soiNode.GetSegmentation()
            segmentation.AddEmptySegment("SOI")
            segmentation.GetSegment("SOI").SetColor(1, 0, 0)
            self.state.addToDir(soiNode)
            self.state.soi = soiNode
        else:
            soiNode = self.state.soi

        self.soiSegmentComboBox.setCurrentNode(soiNode)
        self.soiVolumeComboBox.setCurrentNode(sourceNode)

        self.widget.setCurrentSegmentID("SOI")

        slicer.app.processEvents(1000)
        self.widget.setActiveEffectByName("Scissors")
        # self.widget.findChild(qt.QWidget, "Scissors").click()
        scissors = self.widget.effectByName("Scissors")
        FILL_INSIDE = 2
        scissors.setOperation(FILL_INSIDE)
        RECTANGLE = 2
        scissors.setShape(RECTANGLE)

        maskingWidget = self.widget.findChild(qt.QGroupBox, "MaskingGroupBox")
        maskingWidget.visible = False
        maskingWidget.setFixedHeight(0)

        self.state.setVisibility(pp=True, qemscan=True, soi=True)
        self.nav.setButtonsState(self.BACK_ON_STATE, self.SKIP_ON_STATE, self.NEXT_ON_STATE)

    def exit(self):
        if self.state.soi:
            array = slicer.util.arrayFromSegmentBinaryLabelmap(self.state.soi, "SOI")
            if array is None:
                soiIsEmpty = True
            else:
                soiIsEmpty = array.max() == 0

            if soiIsEmpty:
                slicer.mrmlScene.RemoveNode(self.state.soi)
                self.state.soi = None

        onSegmentEditorExit(self.widget)

    def next(self):
        self.nav.next()


class SmartSeg(FlowStep):
    HELP = """<h3>Smart segmentation</h3>
<p>Automatically segment the image using a machine learning model.</p>
"""
    KEY = "smartseg"
    TITLE = "Smart-seg"

    BACK_ON_STATE = (True, "Go back to the previous step")
    SKIP_ON_STATE = (True, "Skip smart-segmentation and use manual segmentation instead")
    NEXT_OFF_STATE = (False, "You must select the model to use for smart-segmentation")
    NEXT_ON_STATE = (True, "Run smart-segmentation")
    NEXT_IN_PROGRESS_STATE = (False, "Smart-segmentation is already running.")

    def __init__(self, hasPx: bool):
        self.hasPx = hasPx

    def setup(self):
        widget = qt.QFrame()
        layout = qt.QFormLayout(widget)

        self.modelComboBox = qt.QComboBox()
        self.modelComboBox.setToolTip("Select the model to use for segmentation.")
        self.modelComboBox.addItem("Select a model")
        layout.addRow("Model:", self.modelComboBox)

        modelDirs = assets.get_trained_models_with_metadata("ThinSectionEnv")
        self.metadata = {}
        for modelDir in modelDirs:
            metadata = assets.get_metadata(modelDir)
            if not metadata["is_segmentation_model"]:
                continue
            inputs = metadata["inputs"]
            if self.hasPx:
                if not "PP" in inputs or not "PX" in inputs:
                    continue
            else:
                if not "PP" in inputs or "PX" in inputs:
                    continue

            modelName = metadata["title"]
            self.metadata[modelName] = metadata
            self.modelComboBox.addItem(modelName, modelDir)

        self.modelInfo = qt.QLabel()
        self.modelInfo.setTextFormat(qt.Qt.RichText)
        self.modelInfo.setWordWrap(True)
        layout.addRow(self.modelInfo)
        self.modelComboBox.currentIndexChanged.connect(self.onModelChanged)

        cleaningSection = ctk.ctkCollapsibleButton()
        cleaningSection.text = "Cleaning"
        cleaningLayout = qt.QVBoxLayout(cleaningSection)

        self.removeSpuriousCheckbox = qt.QCheckBox("Remove spurious")
        self.removeSpuriousCheckbox.toolTip = "Detect and remove spurious predictions."
        self.removeSpuriousCheckbox.checked = True
        self.removeSpuriousCheckbox.objectName = "Remove Spurious CheckBox"

        self.cleanResinCheckbox = qt.QCheckBox("Clean resin")
        self.cleanResinCheckbox.toolTip = "Detect and clean bubbles and residues in pore resin."
        self.cleanResinCheckbox.checked = True
        self.cleanResinCheckbox.objectName = "Clean Resin CheckBox"

        cleaningLayout.addWidget(self.removeSpuriousCheckbox)
        cleaningLayout.addWidget(self.cleanResinCheckbox)

        layout.addRow(cleaningSection)

        self.stepLabel = qt.QLabel()
        self.progressBar = LocalProgressBar()
        layout.addRow(self.stepLabel)
        layout.addRow(self.progressBar)

        return widget

    def onModelChanged(self, index):
        if index == 0:
            self.modelInfo.setText("")
            self.nav.setButtonsState(self.BACK_ON_STATE, self.SKIP_ON_STATE, self.NEXT_OFF_STATE)
            return
        modelName = self.modelComboBox.currentText
        metadata = self.metadata[modelName]

        try:
            classNames = metadata["outputs"]["y"]["class_names"]
            classColors = metadata["outputs"]["y"]["class_colors"]
        except KeyError:
            classNames = metadata["outputs"]["output_1"]["class_names"]
            classColors = metadata["outputs"]["output_1"]["class_colors"]

        segments = ""
        for segmentName, colorHex in zip(classNames, classColors):
            segments += f'<p><big><font color="{colorHex}">\u25a0</font></big> {segmentName}</p>'
        self.modelInfo.setText(
            f"""
<p>{metadata["description"]}</p>
<h4>Output segments:</h4>
{segments}
"""
        )

        self.nav.setButtonsState(self.BACK_ON_STATE, self.SKIP_ON_STATE, self.NEXT_ON_STATE)

    def enter(self):
        self.onModelChanged(self.modelComboBox.currentIndex)
        self.state.setVisibility(pp=True, soi=True, segmentation=True)

    def exit(self):
        pass

    def next(self):
        if self.state.segmentation is not None:
            msg_box = qt.QMessageBox(slicer.util.mainWindow())
            msg_box.setIcon(qt.QMessageBox.Warning)
            msg_box.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.No)
            msg_box.setDefaultButton(qt.QMessageBox.No)
            msg_box.text = "This will overwrite the existing segmentation. Do you wish to continue?"
            msg_box.setWindowTitle("Delete segmentation")
            result = msg_box.exec()
            if result == qt.QMessageBox.No:
                return
            slicer.mrmlScene.RemoveNode(self.state.segmentation)
            self.state.segmentation = None

        metadata = self.metadata[self.modelComboBox.currentText]
        modelKind = metadata["kind"]

        extraNodes = [self.state.px if self.hasPx else None, None]
        outputPrefix = self.state.pp.GetName() + "_{type}"

        cliQueue = CliQueue(update_display=False, progress_bar=self.progressBar, progress_label=self.stepLabel)

        kernelSize = None
        if modelKind == "torch":
            self.logic = Segmenter.MonaiModelsLogic(False, parent=self.widget)
            tmpReferenceNode, tmpOutNode = self.logic.run(
                self.modelComboBox,
                self.state.pp,
                extraNodes,
                self.state.soi,
                outputPrefix,
                False,
                cliQueue,
            )
        elif modelKind == "bayesian":
            self.logic = Segmenter.BayesianInferenceLogic(False, parent=self.widget)
            kernelSize = metadata["kernel_size"]
            tmpReferenceNode, tmpOutNode = self.logic.run(
                self.modelComboBox.currentData,
                None,
                self.state.pp,
                extraNodes,
                self.state.soi,
                outputPrefix,
                None,
                cliQueue,
            )
        self.logic.node_created.connect(self.onFinish)
        cleaningLogic = Segmenter.PoreCleaningLogic(
            removeSpurious=self.removeSpuriousCheckbox.isChecked(),
            cleanResin=self.cleanResinCheckbox.isChecked(),
            selectedPxNode=self.state.px,
            smartReg=False,
        )
        cleaningLogic.run(tmpReferenceNode, tmpOutNode, self.state.soi, modelKind, kernelSize, cliQueue)
        cliQueue.run()
        self.nav.setButtonsState(self.BACK_ON_STATE, self.SKIP_ON_STATE, self.NEXT_IN_PROGRESS_STATE)

    def onFinish(self, node_id):
        result = slicer.mrmlScene.GetNodeByID(node_id)
        if result.GetSegmentation().GetNumberOfSegments() == 0:
            slicer.util.warningDisplay(
                "The resulting segmentation is empty. Try another segmentation model, adjust the SOI, or skip this step and segment manually.",
                windowTitle="Empty Segmentation",
            )
            return
        self.state.segmentation = result
        self.state.addToDir(self.state.segmentation)
        self.onModelChanged(self.modelComboBox.currentIndex)
        self.nav.next()


class ManualSeg(FlowStep):
    HELP = """
<h3>Manual Segmentation</h3>
<p>Use segmentation tools to create or edit the existing segmentation.</p>
"""
    KEY = "manualseg"
    TITLE = "Manual Seg"

    BACK_ON_STATE = (True, "Go back to the previous step")
    SKIP_ON_STATE = (True, "Go to next step")
    NEXT_ON_STATE = (True, "Go to next step")

    def setup(self):
        moduleWidget = slicer.modules.customizedsegmenteditor.createNewWidgetRepresentation()
        widget = moduleWidget.self()

        widget.selectParameterNodeByTag("PpPxFlow/ManualSeg")
        widget.configureEffectsForThinSectionEnvironment()

        editor = widget.editor
        self.segmentationNodeComboBox = editor.findChild(slicer.qMRMLNodeComboBox, "SegmentationNodeComboBox")
        self.sourceVolumeNodeComboBox = editor.findChild(slicer.qMRMLNodeComboBox, "SourceVolumeNodeComboBox")
        self.segmentationNodeComboBox.visible = False
        self.sourceVolumeNodeComboBox.visible = False
        sourceVolumeNodeLabel = editor.findChild(qt.QLabel, "SourceVolumeNodeLabel")
        sourceVolumeNodeLabel.visible = False
        segmentationNodeLabel = editor.findChild(qt.QLabel, "SegmentationNodeLabel")
        segmentationNodeLabel.visible = False

        return moduleWidget

    def enter(self):
        if self.state.segmentation is None:
            self.state.segmentation = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLSegmentationNode", self.state.pp.GetName() + "_Segmentation"
            )
            self.state.segmentation.CreateDefaultDisplayNodes()
            self.state.addToDir(self.state.segmentation)

        self.segmentationNodeComboBox.setCurrentNode(self.state.segmentation)
        self.sourceVolumeNodeComboBox.setCurrentNode(self.state.pp)

        self.state.setVisibility(pp=True, segmentation=True)
        self.nav.setButtonsState(self.BACK_ON_STATE, self.SKIP_ON_STATE, self.NEXT_ON_STATE)

    def exit(self):
        onSegmentEditorExit(self.widget.self().editor)

    def next(self):
        self.nav.next()


class Inspector(FlowStep):
    HELP = """
<h3>Automatic Labeling</h3>
<p>Split the current segmentation into multiple labels using the chosen method.</p>
<p>Choose which segments in the current segmentation to split into labels using the checkboxes.</p>
<h4>Methods:</h4>
<ul>
    <li><b>Watershed:</b> split segments by finding basins in the values of the underlying image.</li>
    <li><b>Separate objects:</b> split segments into contiguous regions. Labels will not touch each other.</li>
</ul>
"""
    KEY = "inspector"
    TITLE = "Auto-label"

    BACK_ON_STATE = (True, "Go back to the previous step")
    SKIP_OFF_STATE = (False, "You must create a labelmap before you can continue")
    NEXT_OFF_STATE = (False, "You must select at least one segment to label")
    NEXT_ON_STATE = (True, "Run auto-labeling")
    NEXT_IN_PROGRESS_STATE = (False, "Auto-labeling is already running.")

    WATERSHED = "Watershed"
    SEPARATE_OBJECTS = "Separate objects"

    def setup(self):
        widget = qt.QFrame()
        layout = qt.QFormLayout(widget)

        self.methodComboBox = qt.QComboBox()
        self.methodComboBox.addItem(self.WATERSHED)
        self.methodComboBox.addItem(self.SEPARATE_OBJECTS)
        layout.addRow("Method:", self.methodComboBox)

        self.segmentSelector = widgets.SingleShotInputWidget(hideImage=True, hideSoi=True)
        self.segmentSelector.segmentationLabel.hide()
        self.segmentSelector.targetBox.hide()
        layout.addRow(self.segmentSelector)

        self.poreRadioBtn = qt.QRadioButton("Pore")
        self.grainRadioBtn = qt.QRadioButton("Grain")
        self.poreRadioBtn.setChecked(True)

        componentLayout = qt.QHBoxLayout()
        componentLayout.addStretch(1)
        componentLayout.addWidget(self.poreRadioBtn, 3)
        componentLayout.addWidget(self.grainRadioBtn, 3)
        componentLayout.addStretch(3)

        tooltip = "Specify whether the selected input segments represent pores or grains. This affects the labels of the size classes."
        self.poreRadioBtn.setToolTip(tooltip)
        self.grainRadioBtn.setToolTip(tooltip)
        layout.addRow("Component of interest:", componentLayout)

        progressLayout = qt.QHBoxLayout()
        self.progressBar = LocalProgressBar()
        progressLayout.addWidget(self.progressBar, 1)

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.visible = False
        self.cancelButton.setToolTip("Cancel the auto-labeling.")
        self.cancelButton.setFixedHeight(30)
        progressLayout.addWidget(self.cancelButton, 0)

        layout.addRow(progressLayout)

        self.segmentSelector.segmentSelectionChanged.connect(self.onSegmentSelected)
        self.cancelButton.clicked.connect(self.onCancel)

        self.logic = slicer.util.getModuleLogic("SegmentInspector")
        self.logic.inspector_process_finished.connect(self.onFinish)

        return widget

    def enter(self):
        # Force trigger signal
        self.segmentSelector.mainInput.setCurrentNode(None)
        self.segmentSelector.mainInput.setCurrentNode(self.state.segmentation or self.state.qemscan)

        self.segmentSelector.soiInput.setCurrentNode(self.state.soi)
        self.onSegmentSelected(self.segmentSelector.getSelectedSegments())
        self.state.setVisibility(pp=True, segmentation=True, qemscan=True)

    def exit(self):
        pass

    def next(self):
        if self.state.labelmap is not None:
            msg_box = qt.QMessageBox(slicer.util.mainWindow())
            msg_box.setIcon(qt.QMessageBox.Warning)
            msg_box.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.No)
            msg_box.setDefaultButton(qt.QMessageBox.No)
            msg_box.text = "This will overwrite the existing labelmap. Do you wish to continue?"
            msg_box.setWindowTitle("Overwrite labelmap")
            result = msg_box.exec()
            if result == qt.QMessageBox.No:
                return
            slicer.mrmlScene.RemoveNode(self.state.labelmap)
            self.state.labelmap = None
        method = self.methodComboBox.currentText
        refNode = self.state.pp or self.state.qemscan
        mainNode = self.state.segmentation or self.state.qemscan
        prefix = refNode.GetName() + "_{type}"
        if method == self.WATERSHED:
            params = {
                "method": "snow",
                "sigma": 0.005,
                "d_min_filter": 5.0,
                "size_min_threshold": 0.0,
                "direction": [],
                "generate_throat_analysis": False,
                "voxel_size": None,
                "is_pore": self.poreRadioBtn.isChecked(),
            }
        elif method == self.SEPARATE_OBJECTS:
            params = {"method": "islands", "size_min_threshold": 0.0, "direction": []}

        self.cliNode = self.logic.runSelectedMethod(
            mainNode,
            segments=self.segmentSelector.getSelectedSegments(),
            outputPrefix=prefix,
            params=params,
            products=["all"],
            referenceNode=refNode,
            soiNode=self.state.soi,
        )
        if self.cliNode is None:
            return
        self.progressBar.setCommandLineModuleNode(self.cliNode)
        self.nav.setButtonsState(self.BACK_ON_STATE, self.SKIP_OFF_STATE, self.NEXT_IN_PROGRESS_STATE)
        self.cancelButton.visible = True

    def onFinish(self):
        if self.cliNode.GetStatusString() == "Completed":
            self.state.labelmap = slicer.mrmlScene.GetNodeByID(self.logic.outLabelMapId)
            shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            parent = shNode.GetItemParent(shNode.GetItemByDataNode(self.state.labelmap))
            shNode.SetItemParent(parent, self.state.dir)
            self.onSegmentSelected(self.segmentSelector.getSelectedSegments())
            self.cancelButton.visible = False
            self.nav.next()
        else:
            self.onSegmentSelected(self.segmentSelector.getSelectedSegments())
            self.cancelButton.visible = False

    def onSegmentSelected(self, segmentList):
        if segmentList:
            self.nav.setButtonsState(self.BACK_ON_STATE, self.SKIP_OFF_STATE, self.NEXT_ON_STATE)
        else:
            self.nav.setButtonsState(self.BACK_ON_STATE, self.SKIP_OFF_STATE, self.NEXT_OFF_STATE)

    def onCancel(self):
        if self.cliNode is not None:
            self.cliNode.Cancel()


class LabelEditor(FlowStep):
    HELP = """
<h3>Edit Labels</h3>
<p>Manually separate or join labels detected by the automatic labeling tool.</p>
<p>After editing, press <b>Next</b> to recalculate the report table.</p>

<h4>Tools Hotkeys</h4>

<ul>
    <li><b>m:</b> Merge two labels</li>
    <li><b>a:</b> Automatically split label using watershed</li>
    <li><b>s:</b> Slice label with a straight line</li>
    <li><b>c:</b> Cut label at point</li>
    <li><b>z:</b> Undo</li>
    <li><b>x:</b> Redo</li>
</ul>
"""
    KEY = "labeleditor"
    TITLE = "Edit Labels"

    BACK_ON_STATE = (True, "Go back to the previous step")
    SKIP_ON_STATE = (True, "Keep the generated labelmap and table as is")
    NEXT_ON_STATE = (True, "Recalculate the table and save the labelmap")
    NEXT_IN_PROGRESS_STATE = (False, "Recalculating the table, please wait")

    def setup(self):
        moduleWidget = slicer.modules.labelmapeditor.createNewWidgetRepresentation()
        widget = moduleWidget.self()

        widget.input_collapsible.visible = False
        widget.output_collapsible.visible = False
        widget.applyCancelButtons.visible = False
        widget.labelmapGenerated = self.onFinish
        widget.throat_analysis_checkbox.setChecked(False)

        return moduleWidget

    def enter(self):
        widget = self.widget.self()
        self.state.setVisibility()
        widget.enter()
        # Force update
        widget.input_selector.setCurrentNode(None)
        widget.input_selector.setCurrentNode(self.state.labelmap)
        self.nav.setButtonsState(self.BACK_ON_STATE, self.SKIP_ON_STATE, self.NEXT_ON_STATE)

    def exit(self):
        widget = self.widget.self()
        widget.cancel_button.click()
        widget.exit()

    def next(self):
        widget = self.widget.self()
        widget.on_save_button_clicked()

    def onFinish(self, labelmapId):
        labelmap = slicer.mrmlScene.GetNodeByID(labelmapId)
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        parent = shNode.GetItemParent(shNode.GetItemByDataNode(labelmap))
        shNode.SetItemParent(parent, self.state.dir)
        self.state.labelmap = labelmap
        self.nav.setButtonsState(self.BACK_ON_STATE, self.SKIP_ON_STATE, self.NEXT_ON_STATE)
        slicer.app.processEvents(1000)
        self.nav.next()


class Finish(FlowStep):
    HELP = """<h3>Flow Completed</h3>
<p>Check the results. Remember to <b>save the project</b> (Ctrl+S).</p>
<p>Click <b>Next</b> to begin this flow again with another image.</p>
"""
    KEY = "finish"
    TITLE = "Finish"

    BACK_ON_STATE = (True, "Go back to the previous step")
    SKIP_OFF_STATE = (False, "This is the last step")
    NEXT_ON_STATE = (True, "Run this flow again with new images")

    def setup(self):
        widget = qt.QGroupBox()
        layout = qt.QVBoxLayout(widget)
        layout.addWidget(slicer.modules.customizeddata.createNewWidgetRepresentation())

        return widget

    def enter(self):
        self.state.setVisibility(pp=True, labelmap=True)
        self.nav.setButtonsState(self.BACK_ON_STATE, self.SKIP_OFF_STATE, self.NEXT_ON_STATE)

    def exit(self):
        pass

    def next(self):
        self.state.reset()
        self.nav.next()


class LoadQemscan(FlowStep):
    HELP = """<h3>Load QEMSCAN</h3>
<p>Choose a .tif file to load as a QEMSCAN image.</p>
<p>Optionally, specify the pixel size in millimeters.</p>
"""
    KEY = "load"
    TITLE = "Load QEMSCAN"

    BACK_OFF_STATE = (False, "This is the first step")
    SKIP_OFF_STATE = (False, "You must load the image before you can continue")
    NEXT_OFF_STATE = (False, "You must select the image before you can continue")
    NEXT_ON_STATE = (True, "Load selected image")

    def setup(self):
        widget = qt.QFrame()
        layout = qt.QFormLayout(widget)
        self.pathWidget = ctk.ctkPathLineEdit()
        self.pathWidget.filters = ctk.ctkPathLineEdit.Files
        self.pathWidget.nameFilters = [f"Image files (*.tif *.tiff);;Any files (*)"]
        self.pathWidget.settingKey = "QEMSCANLoader/InputFile"
        self.pathWidget.currentPathChanged.connect(self.onPathChanged)
        layout.addRow("QEMSCAN file:", self.pathWidget)

        self.imageSpacingLineEdit = qt.QLineEdit("0.01")
        self.imageSpacingValidator = qt.QDoubleValidator()
        self.imageSpacingValidator.bottom = 0
        self.imageSpacingLocale = qt.QLocale()
        self.imageSpacingLocale.setNumberOptions(qt.QLocale.RejectGroupSeparator)
        self.imageSpacingValidator.setLocale(self.imageSpacingLocale)
        self.imageSpacingLineEdit.setValidator(self.imageSpacingValidator)
        self.imageSpacingLineEdit.setToolTip("Pixel size in millimeters")
        layout.addRow("Pixel size (mm):", self.imageSpacingLineEdit)

        self.logic = slicer.util.getModuleLogic("QEMSCANLoader")

        return widget

    def enter(self):
        self.logic.loadQEMSCANLookupColorTables()
        self.onPathChanged(self.pathWidget.currentPath)

    def exit(self):
        pass

    def next(self):
        with ProgressBarProc() as pb:
            loadParameters = QEMSCANLoader.QEMSCANLoaderWidget.LoadParameters(
                callback=Callback(on_update=lambda message, percent, processEvents=True: pb.nextStep(percent, message)),
                lookupColorTableNode=None,
                fillMissing=True,
                imageSpacing=float(self.imageSpacingLineEdit.text) * ureg.millimeter,
            )
            qemscan = self.logic.load(self.pathWidget.currentPath, loadParameters)
            shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            directoryName = f"{qemscan.GetName()}_Flow"
            dirId = shNode.CreateFolderItem(shNode.GetSceneItemID(), directoryName)
            self.state.dir = dirId

            qemscanParent = shNode.GetItemParent(shNode.GetItemByDataNode(qemscan))
            qemscanParentParent = shNode.GetItemParent(qemscanParent)

            self.state.addToDir(qemscan)
            self.state.qemscan = qemscan

            shNode.RemoveItem(qemscanParent)
            shNode.RemoveItem(qemscanParentParent)
            helpers.save_path(self.pathWidget)
        self.nav.next()

    def onPathChanged(self, path):
        enabled = self.pathWidget.currentPath
        nextState = self.NEXT_ON_STATE if enabled else self.NEXT_OFF_STATE
        self.nav.setButtonsState(self.BACK_OFF_STATE, self.SKIP_OFF_STATE, nextState)


class ThinSectionState(FlowState):
    def __init__(self):
        super().__init__()

    def reset(self):
        self.dir = None
        self.pp = None
        self.px = None
        self.qemscan = None
        self.detectedScale = None
        self.soi = None
        self.segmentation = None
        self.labelmap = None

    def setVisibility(self, pp=False, qemscan=False, soi=False, segmentation=False, labelmap=False):
        pp = self.pp if pp else None
        qemscan = self.qemscan if qemscan else None
        labelmap = self.labelmap if labelmap else None
        slicer.util.setSliceViewerLayers(background=pp, foreground=None, label=(labelmap or qemscan), fit=True)

        if self.soi is not None:
            self.soi.SetDisplayVisibility(soi)

        if self.segmentation is not None:
            self.segmentation.SetDisplayVisibility(segmentation)

    def addToDir(self, node):
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        itemId = shNode.GetItemByDataNode(node)
        shNode.SetItemParent(itemId, self.dir)


class PpPxState(ThinSectionState):
    def availableSteps(self):
        if self.pp is None:
            return ["load"]
        if self.segmentation is None:
            return ["load", "scale", "register", "soi", "smartseg", "manualseg"]
        if self.labelmap is None:
            return ["load", "scale", "register", "soi", "smartseg", "manualseg", "inspector"]
        return ["load", "scale", "register", "soi", "smartseg", "manualseg", "inspector", "labeleditor", "finish"]


class PpState(ThinSectionState):
    def availableSteps(self):
        if self.pp is None:
            return ["load"]
        if self.segmentation is None:
            return ["load", "scale", "soi", "smartseg", "manualseg"]
        if self.labelmap is None:
            return ["load", "scale", "soi", "smartseg", "manualseg", "inspector"]
        return ["load", "scale", "soi", "smartseg", "manualseg", "inspector", "labeleditor", "finish"]


class QemscanState(ThinSectionState):
    def availableSteps(self):
        if self.qemscan is None:
            return ["load"]
        if self.labelmap is None:
            return ["load", "soi", "inspector"]
        return ["load", "soi", "inspector", "labeleditor", "finish"]


def ppPxFlowWidget():
    return FlowWidget(
        [
            Load(hasPx=True),
            Scale(hasPx=True),
            Register(),
            Soi(),
            SmartSeg(hasPx=True),
            ManualSeg(),
            Inspector(),
            LabelEditor(),
            Finish(),
        ],
        PpPxState(),
    )


def ppFlowWidget():
    return FlowWidget(
        [
            Load(hasPx=False),
            Scale(hasPx=False),
            Soi(),
            SmartSeg(hasPx=False),
            ManualSeg(),
            Inspector(),
            LabelEditor(),
            Finish(),
        ],
        PpState(),
    )


def qemscanFlowWidget():
    return FlowWidget(
        [
            LoadQemscan(),
            Soi(),
            Inspector(),
            LabelEditor(),
            Finish(),
        ],
        QemscanState(),
    )
