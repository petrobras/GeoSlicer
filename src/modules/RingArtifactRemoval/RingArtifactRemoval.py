import logging
import os
import time
from pathlib import Path

import ctk
import numpy as np
import qt
import slicer
import vtk

from commons.lmath.ring_artifact_removal import (
    remove_ring_artifacts,
    remove_ring_artifacts_volume,
    center_from_reconstruction_parameters,
)
from commons.lmath.utils import low_memory_percentile
from commons.lmath.streak_artifact_removal import (
    find_fan_center,
    remove_radial_streak_artifacts,
    remove_radial_streak_artifacts_volume,
)
from commons.slicer import helpers
from commons.slicer.metadata import get_item_metadata, get_node_metadata
from commons.slicer.node_attributes import NodeEnvironment
from commons.slicer.side_by_side_image_layout import enable_zoom_sync
from commons.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from commons.slicer.widget.global_progress_bar import CompanionProgressBar
from commons.slicer.widget.help_button import HelpButton

try:
    from Test.RingArtifactRemovalTest import RingArtifactRemovalTest
except ImportError:
    RingArtifactRemovalTest = None  # tests not deployed to final version or closed source

# The companion CLI that drives the progress bar exits after this many seconds.
# It has to outlast any plausible run: the bar dies with it, and the correction
# then carries on with no progress shown.
APPLY_TIMEOUT_SECONDS = 2**30


class OperationCancelledError(Exception):
    """Raised out of the apply loop when the user presses Cancel."""


class RingArtifactRemoval(LTracePlugin):
    SETTING_KEY = "RingArtifactRemoval"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Ring Artifact Removal"
        self.parent.categories = ["Tools", "MicroCT", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.setHelpUrl("Volumes/Filter/Filter.html#ring-artifact-removal", NodeEnvironment.MICRO_CT)

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class RingArtifactRemovalWidget(LTracePluginWidget):
    ADD_POINT_TOOLTIP = (
        "Adds a marker at an estimated center, so there is nothing to click on the\n"
        "slice. Drag it afterwards if it looks off.\n\n"
        "In Ring mode the estimate is the rotation center stored with the\n"
        "volume or, without it, the image center. Expect a rough\n"
        "guess, since a shifted ring's center can sit far from it. In Radial fan mode the target is a\n"
        "real object, the dense grain the streaks come from, so the marker usually\n"
        "lands on the right voxel."
    )
    ADD_POINT_AT_LIMIT_TOOLTIP = (
        "Radial fan mode corrects a single fan, around one focus, so only one point\n"
        "can be added. Remove the existing point to place a different one."
    )

    OUTPUT_SUFFIX = "_remove_rings"

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = None

    def setup(self):
        LTracePluginWidget.setup(self)

        self.logic = RingArtifactRemovalLogic()
        self.logic.centersChanged.connect(self.__onCentersChanged)
        self.logic.radiusRangeChanged.connect(self.__onRadiusRangeDragged)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.text = "Input"
        inputSection.collapsed = False

        self.__inputSelector = slicer.qMRMLNodeComboBox()
        self.__inputSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
        self.__inputSelector.selectNodeUponCreation = True
        self.__inputSelector.addEnabled = False
        self.__inputSelector.removeEnabled = False
        self.__inputSelector.noneEnabled = True
        self.__inputSelector.showHidden = False
        self.__inputSelector.showChildNodeTypes = False
        self.__inputSelector.setMRMLScene(slicer.mrmlScene)
        self.__inputSelector.setObjectName("Input Selector")
        self.__inputSelector.setToolTip("Volume with artifacts (ring or streak) to be corrected.")
        self.__inputSelector.currentNodeChanged.connect(self.__onInputNodeChanged)

        inputLayout = qt.QFormLayout(inputSection)
        inputLayout.addRow("Input volume:", self.__inputSelector)

        self.__artifactTypeComboBox = qt.QComboBox()
        self.__artifactTypeComboBox.addItem("Ring (circular)")
        self.__artifactTypeComboBox.addItem("Radial fan (streaks emanating from a point)")
        self.__artifactTypeComboBox.setToolTip(
            "Ring: a constant bias at a given radius around a center, as produced by\n"
            "rotation axis misalignment. Radial fan: streaks emanating from a fixed\n"
            "point, such as a dense inclusion or a piece of metal. The fan correction\n"
            "handles the whole angular distribution at once, with no radii to enumerate,\n"
            "and adapts to each slice on its own."
        )
        self.__artifactTypeComboBox.currentIndexChanged.connect(self.__onArtifactTypeChanged)

        # Everything that defines the correction and lets the user try it out:
        # the artifact type, the reference points, the parameters acting on them
        # and the single-slice preview. "Output" is then only about producing the
        # volume.
        correctionSection = ctk.ctkCollapsibleButton()
        correctionSection.text = "Correction"
        correctionSection.collapsed = False

        centersLayout = qt.QVBoxLayout(correctionSection)

        # First in the section: it decides which points and parameters below apply.
        self.__helpButton = HelpButton(self.__centersHelpText())

        artifactTypeRow = qt.QHBoxLayout()
        artifactTypeRow.addWidget(self.__artifactTypeComboBox, 1)
        artifactTypeRow.addWidget(self.__helpButton)
        artifactTypeLayout = qt.QFormLayout()
        artifactTypeLayout.addRow("Artifact type:", artifactTypeRow)
        centersLayout.addLayout(artifactTypeLayout)

        self.__centersList = qt.QListWidget()
        self.__centersList.setToolTip("Points (row j, column i) used in the correction.")
        centersLayout.addWidget(self.__centersList)

        centersButtonsLayout = qt.QHBoxLayout()
        self.__addCenterButton = qt.QPushButton("Add point")
        self.__addCenterButton.setToolTip(self.ADD_POINT_TOOLTIP)
        self.__addCenterButton.clicked.connect(self.__onAddCenterClicked)
        self.__removeCenterButton = qt.QPushButton("Remove selected")
        self.__removeCenterButton.clicked.connect(self.__onRemoveCenterClicked)
        self.__clearCentersButton = qt.QPushButton("Clear all")
        self.__clearCentersButton.clicked.connect(self.__onClearCentersClicked)
        centersButtonsLayout.addWidget(self.__addCenterButton)
        centersButtonsLayout.addWidget(self.__removeCenterButton)
        centersButtonsLayout.addWidget(self.__clearCentersButton)
        centersLayout.addLayout(centersButtonsLayout)

        self.__medianSizeSpinBox = qt.QSpinBox()
        self.__medianSizeSpinBox.setRange(3, 199)
        self.__medianSizeSpinBox.setSingleStep(2)
        self.__medianSizeSpinBox.setValue(17)
        self.__medianSizeSpinBox.setToolTip(
            "Window size of the radial median filter, odd values only. Larger windows\n"
            "remove wider rings but can blur more detail."
        )
        self.__medianSizeSpinBox.valueChanged.connect(self.__onMedianSizeChanged)

        self.__arcWidthSpinBox = qt.QDoubleSpinBox()
        self.__arcWidthSpinBox.setRange(1.0, 50.0)
        self.__arcWidthSpinBox.setSingleStep(1.0)
        self.__arcWidthSpinBox.setValue(5.0)
        self.__arcWidthSpinBox.setToolTip(
            "Radial fan: typical width of a streak, in pixels. The window keeps a\n"
            "constant arc length, so one width works both near and far from the center."
        )
        self.__arcWidthLabel = qt.QLabel("Streak width (px):")

        self.__radialCoherenceSpinBox = qt.QSpinBox()
        self.__radialCoherenceSpinBox.setRange(3, 301)
        self.__radialCoherenceSpinBox.setValue(21)
        self.__radialCoherenceSpinBox.setToolTip(
            "Radial fan: over how many pixels of radius a streak has to stay coherent to\n"
            "be corrected. This is what separates streaks from rock texture. Set it too\n"
            "high and the fan comes back, because the rays curve slightly as they go out."
        )
        self.__radialCoherenceLabel = qt.QLabel("Radial coherence (px):")

        self.__minRadiusSpinBox = qt.QSpinBox()
        self.__minRadiusSpinBox.setRange(0, 100000)
        self.__minRadiusSpinBox.setSuffix(" px")
        self.__minRadiusSpinBox.setToolTip(
            "Nothing closer than this to the point is corrected. Drag the handle on the slice to set it."
        )

        self.__maxRadiusSpinBox = qt.QSpinBox()
        self.__maxRadiusSpinBox.setRange(0, 100000)
        self.__maxRadiusSpinBox.setSuffix(" px")
        self.__maxRadiusSpinBox.setSpecialValueText("No limit")
        self.__maxRadiusSpinBox.setToolTip(
            "Nothing farther than this from the point is corrected. 0 means no limit. "
            "Drag the handle on the slice to set it."
        )

        self.__minRadiusSpinBox.valueChanged.connect(self.__onRadiusRangeEdited)
        self.__maxRadiusSpinBox.valueChanged.connect(self.__onRadiusRangeEdited)

        # A widget rather than a bare layout, so the row can be hidden together with its label.
        self.__radiusRangeWidget = qt.QWidget()
        radiusRangeLayout = qt.QHBoxLayout(self.__radiusRangeWidget)
        radiusRangeLayout.setContentsMargins(0, 0, 0, 0)
        radiusRangeLayout.addWidget(self.__minRadiusSpinBox)
        radiusRangeLayout.addWidget(qt.QLabel("to"))
        radiusRangeLayout.addWidget(self.__maxRadiusSpinBox)

        parametersLayout = qt.QFormLayout()
        self.__medianSizeLabel = qt.QLabel("Ring width (px):")
        parametersLayout.addRow(self.__medianSizeLabel, self.__medianSizeSpinBox)
        parametersLayout.addRow(self.__arcWidthLabel, self.__arcWidthSpinBox)
        parametersLayout.addRow(self.__radialCoherenceLabel, self.__radialCoherenceSpinBox)
        self.__radiusRangeLabel = qt.QLabel("Radius range:")
        parametersLayout.addRow(self.__radiusRangeLabel, self.__radiusRangeWidget)
        centersLayout.addLayout(parametersLayout)

        self.__previewButton = qt.QPushButton("Preview on current slice")
        self.__previewButton.clicked.connect(self.__onPreviewButtonClicked)

        self.__exitPreviewButton = qt.QPushButton("Exit preview")
        self.__exitPreviewButton.clicked.connect(self.__onExitPreviewClicked)

        previewButtonsLayout = qt.QHBoxLayout()
        previewButtonsLayout.addWidget(self.__previewButton)
        previewButtonsLayout.addWidget(self.__exitPreviewButton)
        centersLayout.addLayout(previewButtonsLayout)

        outputSection = ctk.ctkCollapsibleButton()
        outputSection.text = "Output"
        outputSection.collapsed = False

        outputLayout = qt.QFormLayout(outputSection)

        self.__outputNameLineEdit = qt.QLineEdit()
        self.__outputNameLineEdit.setObjectName("Output Name Line Edit")
        outputLayout.addRow("Output name:", self.__outputNameLineEdit)

        self.__applyButton = qt.QPushButton("Apply to entire volume")
        self.__applyButton.setObjectName("Apply Button")
        self.__applyButton.setFixedHeight(40)
        self.__applyButton.clicked.connect(self.__onApplyButtonClicked)

        self.__cancelButton = qt.QPushButton("Cancel")
        self.__cancelButton.setObjectName("Cancel Button")
        self.__cancelButton.setFixedHeight(40)
        self.__cancelButton.enabled = False
        self.__cancelButton.setToolTip("Stop the run in progress. No output volume is produced.")
        self.__cancelButton.clicked.connect(self.__onCancelButtonClicked)

        applyButtonsLayout = qt.QHBoxLayout()
        applyButtonsLayout.addWidget(self.__applyButton)
        applyButtonsLayout.addWidget(self.__cancelButton)
        outputLayout.addRow(applyButtonsLayout)

        # Progress shows up on the module panel and, through the companion CLI,
        # on the application status bar, so a long run stays visible even after
        # the user moves to another module.
        self.__progressBar = CompanionProgressBar()
        outputLayout.addRow(self.__progressBar)

        # Update layout
        self.layout.addWidget(inputSection)
        self.layout.addWidget(correctionSection)
        self.layout.addWidget(outputSection)
        self.layout.addStretch(1)

        self.__onInputNodeChanged(self.__inputSelector.currentNode())
        self.__onArtifactTypeChanged(self.__artifactTypeComboBox.currentIndex)

    def __onRadiusRangeEdited(self, value=None):
        # The circles are drawn around the first point, so there is nothing to show without one.
        # Add it, as "Add point" would, rather than leave the range invisible until the user finds out why.
        inputNode = self.__inputSelector.currentNode()
        hasRange = self.__minRadiusSpinBox.value or self.__maxRadiusSpinBox.value
        if inputNode is not None and hasRange and not self.logic.getCentersIJK(inputNode):
            self.__onAddCenterClicked()
        self.logic.setRadiusRange(
            self.__minRadiusSpinBox.value, self.__maxRadiusSpinBox.value, self.__inputSelector.currentNode()
        )

    def __onRadiusRangeDragged(self, rMin, rMax):
        for spinBox, value in ((self.__minRadiusSpinBox, rMin), (self.__maxRadiusSpinBox, rMax)):
            spinBox.blockSignals(True)
            spinBox.setValue(value)
            spinBox.blockSignals(False)

    def __radiusRange(self):
        """(r_min, r_max) in pixels, with None for an end that is not limited."""
        if self.__isLineMode():
            return None, None
        return self.__minRadiusSpinBox.value or None, self.__maxRadiusSpinBox.value or None

    def __isLineMode(self):
        return self.__artifactTypeComboBox.currentIndex == 1

    def __centersHelpText(self):
        if self.__isLineMode():
            return (
                "Add point marks the dense grain the streaks come from, found automatically "
                "in the whole volume. Drag it if it lands on the wrong spot. You only mark "
                "where the streaks start: which way they point is measured on every slice, "
                "so a fan that turns with depth needs no extra input. One fan has one focus, "
                "so this mode takes a single point."
            )
        return (
            "Add point marks an estimated ring center: the rotation center stored with the volume or, "
            "without it, the image center. Treat it as a first guess and drag it onto the ring center "
            "you can see. Add one point per ring that has its own center."
        )

    def __onArtifactTypeChanged(self, index):
        self.__helpButton.message = self.__centersHelpText()
        self.__updateAddCenterButton()
        lineMode = self.__isLineMode()
        self.__arcWidthSpinBox.setVisible(lineMode)
        self.__arcWidthLabel.setVisible(lineMode)
        self.__radialCoherenceSpinBox.setVisible(lineMode)
        self.__radialCoherenceLabel.setVisible(lineMode)
        self.__medianSizeSpinBox.setVisible(not lineMode)
        self.__medianSizeLabel.setVisible(not lineMode)
        # The radius range is a Ring option. Radial fan works on the whole slice, so drop the range
        # (and with it the circles on the slice) instead of leaving it set but ignored.
        self.__radiusRangeWidget.setVisible(not lineMode)
        self.__radiusRangeLabel.setVisible(not lineMode)
        if lineMode:
            self.__minRadiusSpinBox.setValue(0)
            self.__maxRadiusSpinBox.setValue(0)

    def __onMedianSizeChanged(self, value):
        if value % 2 == 0:
            # Round to the nearest odd value (prefers rounding up, except at the top of the range).
            corrected = value + 1 if value < self.__medianSizeSpinBox.maximum else value - 1
            self.__medianSizeSpinBox.blockSignals(True)
            self.__medianSizeSpinBox.setValue(corrected)
            self.__medianSizeSpinBox.blockSignals(False)

    def __onInputNodeChanged(self, node):
        enabled = node is not None
        self.__updateAddCenterButton()
        self.__previewButton.enabled = enabled
        self.__applyButton.enabled = enabled

        if node is None:
            self.__outputNameLineEdit.setText("")
            return

        self.__outputNameLineEdit.setText(node.GetName() + self.OUTPUT_SUFFIX)

    def __currentSliceIndex(self, inputNode):
        array = slicer.util.arrayFromVolume(inputNode)
        lastIndex = array.shape[0] - 1
        currentSlice = self.logic.getCurrentSliceIndex(inputNode)
        if currentSlice is None:
            return array.shape[0] // 2
        return max(0, min(currentSlice, lastIndex))

    def __onAddCenterClicked(self):
        inputNode = self.__inputSelector.currentNode()
        if inputNode is None:
            slicer.util.errorDisplay("Select an input volume.")
            return
        self.logic.addEstimatedCenter(
            inputNode,
            sliceIndex=self.__currentSliceIndex(inputNode),
            medianSize=self.__medianSizeSpinBox.value,
            mode="line" if self.__isLineMode() else "ring",
        )

    def __onRemoveCenterClicked(self):
        row = self.__centersList.currentRow
        if row < 0:
            return
        self.logic.removeCenterAt(row)

    def __onClearCentersClicked(self):
        self.logic.clearCenters()

    def __onCentersChanged(self):
        self.__centersList.clear()
        for i, (cy, cx) in enumerate(self.logic.getCentersIJK(self.__inputSelector.currentNode())):
            self.__centersList.addItem(f"Point {i + 1}: (j={cy:.1f}, i={cx:.1f})")
        self.__updateAddCenterButton()

    def __updateAddCenterButton(self):
        """Radial fan corrects one fan around one focus, so it takes a single point.

        Blocking the button is clearer than accepting a second point and refusing
        it later at apply time, and the tooltip says why it is disabled.
        """
        inputNode = self.__inputSelector.currentNode()
        count = len(self.logic.getCentersIJK(inputNode)) if self.logic else 0
        atLimit = self.__isLineMode() and count >= 1
        self.__addCenterButton.enabled = inputNode is not None and not atLimit
        self.__addCenterButton.setToolTip(self.ADD_POINT_AT_LIMIT_TOOLTIP if atLimit else self.ADD_POINT_TOOLTIP)

    def __onPreviewButtonClicked(self):
        inputNode = self.__inputSelector.currentNode()
        if inputNode is None:
            slicer.util.errorDisplay("Select an input volume.")
            return

        centers = self.logic.getCentersIJK(inputNode)
        if self.__isLineMode() and len(centers) != 1:
            slicer.util.errorDisplay("'Radial fan' mode requires exactly 1 marked point (the focus of the streaks).")
            return

        sliceIndex = self.__currentSliceIndex(inputNode)
        self.logic.preview(
            inputNode,
            centers,
            medianSize=self.__medianSizeSpinBox.value,
            sliceIndex=sliceIndex,
            mode="line" if self.__isLineMode() else "ring",
            arcWidth=self.__arcWidthSpinBox.value,
            radialCoherence=self.__radialCoherenceSpinBox.value,
            radiusRange=self.__radiusRange(),
        )

    def __onExitPreviewClicked(self):
        self.logic.exitPreview()

    def __onApplyButtonClicked(self):
        inputNode = self.__inputSelector.currentNode()
        if inputNode is None:
            slicer.util.errorDisplay("Select an input volume.")
            return

        outputName = self.__outputNameLineEdit.text.strip()
        if not outputName:
            slicer.util.errorDisplay("Enter an output name.")
            return

        centers = self.logic.getCentersIJK(inputNode)
        if self.__isLineMode() and len(centers) != 1:
            slicer.util.errorDisplay("'Radial fan' mode requires exactly 1 marked point (the focus of the streaks).")
            return

        self.__setRunning(True)
        self.__progressBar.processStopped()
        self.__progressBar.start(f"ring_artifact_removal_{time.time_ns()}", APPLY_TIMEOUT_SECONDS)
        try:
            outputNode = self.logic.apply(
                inputNode,
                centers,
                medianSize=self.__medianSizeSpinBox.value,
                outputName=outputName,
                mode="line" if self.__isLineMode() else "ring",
                arcWidth=self.__arcWidthSpinBox.value,
                radialCoherence=self.__radialCoherenceSpinBox.value,
                radiusRange=self.__radiusRange(),
                progressCallback=self.__onApplyProgress,
            )
        except OperationCancelledError:
            # No popup: the user asked for this, and producing no volume is the
            # expected outcome.
            logging.info("Ring artifact removal cancelled by the user.")
            return
        finally:
            # Driving the bar to 100% is how the companion CLI winds down, the same
            # way the interactive segmenter's _stopSegmentation does it. It reports
            # "Completed" even when the run was cancelled. Deleting the progress
            # file here instead would cut the CLI off before it reads this last
            # value and leave the bar short of the end, and the processStopped()
            # before start() above already covers the leftover file.
            self.__progressBar.update(1.0)
            self.__setRunning(False)

        # The filter run is over: back to the traditional layout (the 3-panel
        # preview shows a single slice, so keeping it would hide the volume
        # the user just produced) and drop the markers along with it.
        self.logic.exitPreview()
        self.logic.removeCenters()
        slicer.util.setSliceViewerLayers(background=outputNode, fit=True)

    def __onApplyProgress(self, fraction):
        # update() calls processEvents() itself, which is what lets Cancel be
        # clicked at all while apply runs on the main thread. The companion CLI
        # reads the value every few seconds, so calling this once per slice
        # costs nothing and keeps the bar moving.
        self.__progressBar.update(max(0.0, min(fraction, 1.0)))

    def __onCancelButtonClicked(self):
        # Only raises a flag. The apply loop checks it once per slice.
        self.__cancelButton.enabled = False
        self.__cancelButton.setText("Cancelling...")
        self.logic.requestCancel()

    def __setRunning(self, running):
        self.__applyButton.enabled = not running
        self.__previewButton.enabled = not running
        self.__cancelButton.enabled = running
        self.__cancelButton.setText("Cancel")

    def exit(self):
        # Called when another tool is picked in "Filters", or the module is left.
        # Restores the layout the preview changed and drops the center markers.
        if self.logic:
            self.logic.exitPreview()
            self.logic.removeCenters()

    def cleanup(self):
        super().cleanup()
        if self.logic:
            self.logic.exitPreview()
            self.logic.centersChanged.disconnect(self.__onCentersChanged)
            self.logic.radiusRangeChanged.disconnect(self.__onRadiusRangeDragged)
            self.logic = None


class RingArtifactRemovalLogic(LTracePluginLogic):
    centersChanged = qt.Signal()
    # (min, max) in pixels, emitted when a radius handle is dragged on the slice.
    radiusRangeChanged = qt.Signal(int, int)

    CIRCLE_POINTS = 96
    RADIUS_HANDLE_LABELS = ("Min radius", "Max radius")

    PREVIEW_LAYOUT_ID = 220
    PREVIEW_VIEW_GROUP = 80
    PREVIEW_LAYOUT_XML = f"""
        <layout type="horizontal" split="true">
            <item splitSize="333">
                <view class="vtkMRMLSliceNode" singletontag="RingPreviewBefore">
                    <property name="orientation" action="default">XY</property>
                    <property name="viewlabel" action="default">A</property>
                    <property name="viewcolor" action="default">#EEEEEE</property>
                    <property name="viewgroup" action="default">{PREVIEW_VIEW_GROUP}</property>
                </view>
            </item>
            <item splitSize="333">
                <view class="vtkMRMLSliceNode" singletontag="RingPreviewAfter">
                    <property name="orientation" action="default">XY</property>
                    <property name="viewlabel" action="default">D</property>
                    <property name="viewcolor" action="default">#EEEEEE</property>
                    <property name="viewgroup" action="default">{PREVIEW_VIEW_GROUP}</property>
                </view>
            </item>
            <item splitSize="333">
                <view class="vtkMRMLSliceNode" singletontag="RingPreviewDiff">
                    <property name="orientation" action="default">XY</property>
                    <property name="viewlabel" action="default">Δ</property>
                    <property name="viewcolor" action="default">#EEEEEE</property>
                    <property name="viewgroup" action="default">{PREVIEW_VIEW_GROUP}</property>
                </view>
            </item>
        </layout>
    """

    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.centersMarkupsNode = None
        self.markupsObserverTags = []
        self.inputPreviewVolume = None
        self.outputPreviewVolume = None
        self.diffPreviewVolume = None
        self.previewActive = False
        self.previewLayoutRegistered = False
        self.lastLayout = None
        self.lastBackgroundVolumeID = None
        self.cancelRequested = False
        self.radiusRange = (0, 0)
        self.radiusVolume = None
        self.radiusCircleNodes = []
        self.radiusHandlesNode = None
        self.radiusHandlesObserverTag = None
        self.syncingRadius = False
        self.destroyed.connect(self.__del__)

    def __del__(self):
        # No centersChanged here: this runs while the widget is being destroyed,
        # and emitting into a half-torn-down slot is a good way to get a crash.
        self.__destroyMarkupsNode()
        helpers.removeTemporaryNodes(environment="RingArtifactRemoval")

    # -- Centers (markups) -------------------------------------------------

    def ensureMarkupsNode(self):
        if self.centersMarkupsNode is None or slicer.mrmlScene.GetNodeByID(self.centersMarkupsNode.GetID()) is None:
            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "Ring Artifact Centers")
            node.CreateDefaultDisplayNodes()
            displayNode = node.GetDisplayNode()
            if displayNode is not None:
                displayNode.SetGlyphScale(2.0)
                displayNode.SetTextScale(2.5)
                displayNode.SetSelectedColor(1.0, 0.6, 0.0)
                # A center is the same (x, y) for the whole volume, but a fiducial
                # is drawn only on the slice it sits on, so it would vanish as soon
                # as the user scrolls in z. Slice projection draws it dimmed on the
                # other slices, keeping it visible through the stack without adding
                # anything to the scene.
                displayNode.SetSliceProjection(True)
                displayNode.SetSliceProjectionUseFiducialColor(False)
                displayNode.SetSliceProjectionColor(1.0, 0.6, 0.0)
                displayNode.SetSliceProjectionOpacity(0.4)
            self.centersMarkupsNode = node
            self.__removeMarkupsObservers()
            self.markupsObserverTags = [
                node.AddObserver(slicer.vtkMRMLMarkupsNode.PointAddedEvent, self.__onMarkupsChanged),
                node.AddObserver(slicer.vtkMRMLMarkupsNode.PointRemovedEvent, self.__onMarkupsChanged),
                node.AddObserver(slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.__onMarkupsChanged),
            ]
        return self.centersMarkupsNode

    def removeCenters(self):
        """Drop the center markers from the scene, after applying or cancelling.

        `clearCenters` empties the node but keeps it, so more points can be
        added. This removes the node itself: the markers belonged to a run that
        is over, and left in the scene they keep showing up in every view and in
        the subject hierarchy.
        """
        self.__destroyMarkupsNode()
        self.centersChanged.emit()

    def __destroyMarkupsNode(self):
        self.__destroyRadiusNodes()
        self.__removeMarkupsObservers()
        if self.centersMarkupsNode is not None:
            slicer.mrmlScene.RemoveNode(self.centersMarkupsNode)
            self.centersMarkupsNode = None

    def __removeMarkupsObservers(self):
        if self.centersMarkupsNode is not None:
            for tag in self.markupsObserverTags:
                self.centersMarkupsNode.RemoveObserver(tag)
        self.markupsObserverTags = []

    def __onMarkupsChanged(self, caller=None, event=None):
        self.__refreshRadiusDisplay()
        self.centersChanged.emit()

    # -- Radius range (circles and handles on the slice) ----------------------

    def setRadiusRange(self, rMin, rMax, volumeNode=None):
        """Set the radius range, in pixels, and redraw its circles around the first point.

        0 means the end is not limited, and has no circle.
        """
        self.radiusRange = (int(rMin), int(rMax))
        if volumeNode is not None:
            self.radiusVolume = volumeNode
        self.__refreshRadiusDisplay()

    def __firstCenterIJK(self):
        """(i, j, k) of the first marked point in `radiusVolume`, or None."""
        if self.centersMarkupsNode is None or self.radiusVolume is None:
            return None
        if self.centersMarkupsNode.GetNumberOfControlPoints() == 0:
            return None
        ras = slicer.util.arrayFromMarkupsControlPoints(self.centersMarkupsNode)[0]
        m = vtk.vtkMatrix4x4()
        self.radiusVolume.GetRASToIJKMatrix(m)
        return (slicer.util.arrayFromVTKMatrix(m) @ np.append(ras, 1.0))[:3]

    def __ijkToRas(self, ijk):
        m = vtk.vtkMatrix4x4()
        self.radiusVolume.GetIJKToRASMatrix(m)
        return (slicer.util.arrayFromVTKMatrix(m) @ np.array([ijk[0], ijk[1], ijk[2], 1.0]))[:3]

    def __ensureRadiusNodes(self):
        """Two display-only circles and one node holding the two draggable handles."""
        alive = [n for n in self.radiusCircleNodes if slicer.mrmlScene.GetNodeByID(n.GetID()) is not None]
        if len(alive) != 2:
            self.__destroyRadiusNodes()
            for name in self.RADIUS_HANDLE_LABELS:
                # A tube along the slice axis, shown only where it cuts the slice. Unlike a curve
                # drawn on one slice, its cut is a full line on every slice and in every view,
                # including the preview panels, which show a single slice of their own.
                node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", f"{name} circle")
                node.CreateDefaultDisplayNodes()
                display = node.GetDisplayNode()
                display.SetVisibility3D(False)
                display.SetSliceIntersectionVisibility(True)
                display.SetSliceIntersectionThickness(2)
                display.SetColor(1.0, 0.6, 0.0)
                self.radiusCircleNodes.append(node)
        if self.radiusHandlesNode is None or slicer.mrmlScene.GetNodeByID(self.radiusHandlesNode.GetID()) is None:
            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "Ring Artifact Radius")
            node.CreateDefaultDisplayNodes()
            display = node.GetDisplayNode()
            display.SetGlyphScale(2.0)
            display.SetTextScale(2.0)
            display.SetSelectedColor(1.0, 0.6, 0.0)
            self.radiusHandlesNode = node
            self.radiusHandlesObserverTag = node.AddObserver(
                slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.__onRadiusHandleModified
            )
        return self.radiusCircleNodes, self.radiusHandlesNode

    def __destroyRadiusNodes(self):
        if self.radiusHandlesNode is not None:
            if self.radiusHandlesObserverTag is not None:
                self.radiusHandlesNode.RemoveObserver(self.radiusHandlesObserverTag)
            slicer.mrmlScene.RemoveNode(self.radiusHandlesNode)
        for node in self.radiusCircleNodes:
            slicer.mrmlScene.RemoveNode(node)
        self.radiusHandlesNode = None
        self.radiusHandlesObserverTag = None
        self.radiusCircleNodes = []

    def __setCircle(self, modelNode, center, radius):
        """Make `modelNode` a tube of `radius` around `center`, spanning every slice of the volume."""
        polyData = vtk.vtkPolyData()
        if radius:
            angles = np.linspace(0, 2 * np.pi, self.CIRCLE_POINTS, endpoint=False)
            depth = self.radiusVolume.GetImageData().GetDimensions()[2]
            points = vtk.vtkPoints()
            for k in (-1, depth):
                for angle in angles:
                    ijk = (center[0] + radius * np.cos(angle), center[1] + radius * np.sin(angle), k)
                    points.InsertNextPoint(*self.__ijkToRas(ijk))
            polys = vtk.vtkCellArray()
            n = self.CIRCLE_POINTS
            for i in range(n):
                j = (i + 1) % n
                for triangle in ((i, j, n + i), (j, n + j, n + i)):
                    polys.InsertNextCell(3, triangle)
            polyData.SetPoints(points)
            polyData.SetPolys(polys)
        modelNode.SetAndObservePolyData(polyData)

    def __refreshRadiusDisplay(self):
        """Redraw circles and handles from `radiusRange` and the position of the first point."""
        center = self.__firstCenterIJK()
        if center is None or not any(self.radiusRange):
            self.__destroyRadiusNodes()
            return
        circles, handles = self.__ensureRadiusNodes()
        self.syncingRadius = True
        try:
            handles.RemoveAllControlPoints()
            for index, radius in enumerate(self.radiusRange):
                self.__setCircle(circles[index], center, radius)
                if radius:
                    handleRas = self.__ijkToRas((center[0] + radius, center[1], center[2]))
                    handles.AddControlPoint(vtk.vtkVector3d(*handleRas), self.RADIUS_HANDLE_LABELS[index])
        finally:
            self.syncingRadius = False

    def __onRadiusHandleModified(self, caller=None, event=None):
        """A handle was dragged: its distance to the point is the new radius."""
        if self.syncingRadius or self.radiusHandlesNode is None:
            return
        center = self.__firstCenterIJK()
        if center is None:
            return
        m = vtk.vtkMatrix4x4()
        self.radiusVolume.GetRASToIJKMatrix(m)
        rasToIjk = slicer.util.arrayFromVTKMatrix(m)
        radii = list(self.radiusRange)
        for point in range(self.radiusHandlesNode.GetNumberOfControlPoints()):
            label = self.radiusHandlesNode.GetNthControlPointLabel(point)
            if label not in self.RADIUS_HANDLE_LABELS:
                continue
            ras = np.array(self.radiusHandlesNode.GetNthControlPointPositionVector(point))
            ijk = (rasToIjk @ np.append(ras, 1.0))[:3]
            radii[self.RADIUS_HANDLE_LABELS.index(label)] = max(
                1, int(round(np.hypot(ijk[0] - center[0], ijk[1] - center[1])))
            )
        self.radiusRange = tuple(radii)
        # Circles only: rebuilding the handles now would pull one out from under the cursor.
        self.syncingRadius = True
        try:
            circles, _ = self.__ensureRadiusNodes()
            for index, radius in enumerate(self.radiusRange):
                self.__setCircle(circles[index], center, radius)
        finally:
            self.syncingRadius = False
        self.radiusRangeChanged.emit(*self.radiusRange)

    def clearCenters(self):
        if self.centersMarkupsNode is not None:
            self.centersMarkupsNode.RemoveAllControlPoints()
        self.centersChanged.emit()

    def removeCenterAt(self, index):
        if self.centersMarkupsNode is None:
            return
        if 0 <= index < self.centersMarkupsNode.GetNumberOfControlPoints():
            self.centersMarkupsNode.RemoveNthControlPoint(index)
        self.centersChanged.emit()

    @classmethod
    def getDefaultCenter(cls, volumeNode):
        """Return the (cy, cx) ring center to use when none was marked.

        Reconstructions are centered on the rotation axis, so without a recorded
        center the grid center is a better guess than the sample centroid, which
        is skewed by whatever material fills the slice.
        """
        dims = volumeNode.GetImageData().GetDimensions()
        return cls.getMetadataCenter(volumeNode) or ((dims[1] - 1) / 2.0, (dims[0] - 1) / 2.0)

    @staticmethod
    def getMetadataCenter(volumeNode):
        """Return the (cy, cx) rotation center stored with the volume, or None if it has none."""
        rec = get_node_metadata(volumeNode).get("rec")
        if not rec:
            shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
            itemId = shNode.GetItemByDataNode(volumeNode)
            parentId = shNode.GetItemParent(itemId) if itemId else 0
            rec = get_item_metadata(parentId).get("rec") if parentId else None
        dims = volumeNode.GetImageData().GetDimensions()
        return center_from_reconstruction_parameters(rec, (dims[1], dims[0]))

    def addEstimatedCenter(self, volumeNode, sliceIndex, medianSize=17, mode="ring"):
        """Add a marker at an automatically estimated center.

        This is all of "Add point"; nothing has to be clicked on the slice. The
        marker is a starting point for calibration, draggable and meant to be
        corrected by eye.

        The two modes are not equally reliable, and the panel says as much. In
        "line" mode the fan focus is a real object, so `find_fan_center` scans the
        whole volume for the most attenuating voxel and lands on it. In "ring"
        mode the center is a geometric point with no object to look for, so the
        guess is `getDefaultCenter`. A ring whose center sits away from it, from
        axis misalignment or a cone beam, still has to be dragged into place.

        Returns the estimated (cy, cx).
        """
        array = slicer.util.arrayFromVolume(volumeNode)
        sliceIndex = int(max(0, min(sliceIndex, array.shape[0] - 1)))

        if mode == "line":
            cy, cx = find_fan_center(array)
        else:
            cy, cx = self.getDefaultCenter(volumeNode)

        m = vtk.vtkMatrix4x4()
        volumeNode.GetIJKToRASMatrix(m)
        ijkToRasArr = slicer.util.arrayFromVTKMatrix(m)
        ras = ijkToRasArr @ np.array([cx, cy, sliceIndex, 1.0])

        self.radiusVolume = volumeNode
        node = self.ensureMarkupsNode()
        node.AddControlPoint(vtk.vtkVector3d(ras[0], ras[1], ras[2]))
        self.centersChanged.emit()
        return cy, cx

    def getCentersIJK(self, volumeNode):
        """Return the list of centers as (j, i), that is row and column, within a slice."""
        if volumeNode is None or self.centersMarkupsNode is None:
            return []
        n = self.centersMarkupsNode.GetNumberOfControlPoints()
        if n == 0:
            return []

        ras = slicer.util.arrayFromMarkupsControlPoints(self.centersMarkupsNode)
        ras1 = np.c_[ras, np.ones(len(ras))]

        m = vtk.vtkMatrix4x4()
        volumeNode.GetRASToIJKMatrix(m)
        rasToIjkArr = slicer.util.arrayFromVTKMatrix(m)
        ijk = (rasToIjkArr @ ras1.T).T[:, :3]

        # arrayFromVolume returns (k, j, i); Slicer IJK comes as (i, j, k).
        return [(float(p[1]), float(p[0])) for p in ijk]

    def getCurrentSliceIndex(self, volumeNode, sliceViewName="Red"):
        sliceWidget = slicer.app.layoutManager().sliceWidget(sliceViewName)
        if sliceWidget is None or volumeNode is None:
            return None

        sliceNode = sliceWidget.mrmlSliceNode()
        sliceToRAS = sliceNode.GetSliceToRAS()
        originRAS = [sliceToRAS.GetElement(r, 3) for r in range(3)] + [1.0]

        m = vtk.vtkMatrix4x4()
        volumeNode.GetRASToIJKMatrix(m)
        ijk = [sum(m.GetElement(r, c) * originRAS[c] for c in range(4)) for r in range(3)]

        # Assumes the axial axis (k) is aligned with the first array axis (no rotation) --
        # this holds for the tested microCT volumes; a manual adjustment is available in
        # the UI spinbox in case the volume has a different orientation.
        return int(round(ijk[2]))

    # -- Preview -------------------------------------------------------

    def _registerPreviewLayout(self):
        if self.previewLayoutRegistered:
            return
        layoutNode = slicer.app.layoutManager().layoutLogic().GetLayoutNode()
        # SetLayoutDescription overwrites even if the ID is already registered
        # (e.g. from a previous GeoSlicer session with an old version of the
        # XML), and AddLayoutDescription is a no-op in that case.
        if layoutNode.IsLayoutDescription(self.PREVIEW_LAYOUT_ID):
            layoutNode.SetLayoutDescription(self.PREVIEW_LAYOUT_ID, self.PREVIEW_LAYOUT_XML)
        else:
            layoutNode.AddLayoutDescription(self.PREVIEW_LAYOUT_ID, self.PREVIEW_LAYOUT_XML)
        self.previewLayoutRegistered = True

    def _enterPreviewLayout(self):
        self._registerPreviewLayout()
        if self.previewActive:
            return
        layoutManager = slicer.app.layoutManager()
        self.lastLayout = layoutManager.layout
        redComposite = layoutManager.sliceWidget("Red").sliceLogic().GetSliceCompositeNode()
        self.lastBackgroundVolumeID = redComposite.GetBackgroundVolumeID()
        self.previewActive = True

    def exitPreview(self):
        if not self.previewActive:
            return
        layoutManager = slicer.app.layoutManager()
        if self.lastLayout is not None:
            layoutManager.setLayout(self.lastLayout)
        if self.lastBackgroundVolumeID:
            slicer.util.setSliceViewerLayers(
                background=slicer.mrmlScene.GetNodeByID(self.lastBackgroundVolumeID), fit=True
            )
        self.previewActive = False
        helpers.removeTemporaryNodes(environment="RingArtifactRemoval")
        self.inputPreviewVolume = None
        self.outputPreviewVolume = None
        self.diffPreviewVolume = None

    def _ensurePreviewNodes(self, inputVolume, sliceIndex):
        if self.inputPreviewVolume is None or slicer.mrmlScene.GetNodeByID(self.inputPreviewVolume.GetID()) is None:
            self.inputPreviewVolume = helpers.createTemporaryNode(
                slicer.vtkMRMLScalarVolumeNode,
                "Ring removal - before",
                uniqueName=False,
                environment="RingArtifactRemoval",
            )
            self.outputPreviewVolume = helpers.createTemporaryNode(
                slicer.vtkMRMLScalarVolumeNode,
                "Ring removal - after",
                uniqueName=False,
                environment="RingArtifactRemoval",
            )
            self.diffPreviewVolume = helpers.createTemporaryNode(
                slicer.vtkMRMLScalarVolumeNode,
                "Ring removal - diff (before - after)",
                uniqueName=False,
                environment="RingArtifactRemoval",
            )
        ijkToRas = vtk.vtkMatrix4x4()
        inputVolume.GetIJKToRASMatrix(ijkToRas)
        sliceOrigin = ijkToRas.MultiplyPoint((0, 0, sliceIndex, 1))[:3]
        for node in (self.inputPreviewVolume, self.outputPreviewVolume, self.diffPreviewVolume):
            node.CopyOrientation(inputVolume)
            node.SetOrigin(sliceOrigin)
        helpers.copy_display(inputVolume, self.inputPreviewVolume)
        helpers.copy_display(inputVolume, self.outputPreviewVolume)
        self.diffPreviewVolume.CreateDefaultDisplayNodes()

    def _updateDiffDisplay(self, diffArray):
        slicer.util.updateVolumeFromArray(self.diffPreviewVolume, diffArray[None, :, :].astype(np.float32))
        displayNode = self.diffPreviewVolume.GetDisplayNode()
        if displayNode is not None:
            maxAbs = float(np.percentile(np.abs(diffArray), 99.5)) if diffArray.size else 0.0
            maxAbs = max(maxAbs, 1e-6)
            displayNode.SetAutoWindowLevel(False)
            displayNode.SetWindowLevel(2 * maxAbs, 0.0)

    def preview(
        self,
        inputVolume,
        centers,
        medianSize,
        sliceIndex,
        mode="ring",
        arcWidth=5.0,
        radialCoherence=21,
        radiusRange=None,
    ):
        self._enterPreviewLayout()
        array = slicer.util.arrayFromVolume(inputVolume)
        sliceIndex = int(max(0, min(sliceIndex, array.shape[0] - 1)))
        sl = array[sliceIndex].astype(np.float64)

        if mode == "line":
            mask = sl > np.percentile(sl, 1)
            rMin, rMax = radiusRange or (None, None)
            corrected = remove_radial_streak_artifacts(
                sl,
                centers[0],
                mask=mask,
                arc_width=arcWidth,
                radial_coherence=radialCoherence,
                min_radius=rMin or 3.0,
                max_radius=rMax,
            )
        else:
            corrected = sl.copy()
            for center in centers or [self.getDefaultCenter(inputVolume)]:
                corrected = remove_ring_artifacts(
                    corrected, center=center, median_size=medianSize, radius_range=radiusRange
                )

        before = sl.astype(array.dtype)
        after = corrected.astype(array.dtype)
        diff = sl - corrected  # before - after = what was removed

        self._ensurePreviewNodes(inputVolume, sliceIndex)
        slicer.util.updateVolumeFromArray(self.inputPreviewVolume, before[None, :, :])
        slicer.util.updateVolumeFromArray(self.outputPreviewVolume, after[None, :, :])
        self._updateDiffDisplay(diff)

        self._showPreviewLayout()

    PREVIEW_VIEW_NAMES = ("RingPreviewBefore", "RingPreviewAfter", "RingPreviewDiff")

    def _showPreviewLayout(self):
        layoutManager = slicer.app.layoutManager()
        layoutManager.setLayout(self.PREVIEW_LAYOUT_ID)
        # Give the UI time to process the layout change (widgets with their
        # final size) before adjusting the fit. Otherwise the first view
        # sometimes computes FitSliceToAll with the old/wrong geometry.
        slicer.app.processEvents()
        volumesByView = {
            "RingPreviewBefore": self.inputPreviewVolume,
            "RingPreviewAfter": self.outputPreviewVolume,
            "RingPreviewDiff": self.diffPreviewVolume,
        }
        for viewName in self.PREVIEW_VIEW_NAMES:
            widget = layoutManager.sliceWidget(viewName)
            if widget is None:
                continue
            sliceLogic = widget.sliceLogic()
            sliceLogic.GetSliceCompositeNode().SetBackgroundVolumeID(volumesByView[viewName].GetID())
            sliceLogic.FitSliceToAll()

        # Repeat the fit in a second pass: right after the layout change, the
        # render window of the first processed panel sometimes has not finished
        # resizing yet (even with the processEvents above), and FitSliceToAll
        # computes with the old size, and the second pass fixes it at almost
        # no cost.
        slicer.app.processEvents()
        for viewName in self.PREVIEW_VIEW_NAMES:
            widget = layoutManager.sliceWidget(viewName)
            if widget is None:
                continue
            widget.sliceLogic().FitSliceToAll()

        # Synchronize pan/zoom/slice across the 3 panels. The "default" viewgroup in
        # the layout XML is only applied when the singleton node is created, so if the
        # node already exists in the scene (from a previous layout switch), it must be
        # set explicitly here, otherwise it stays in group 0 (shared with
        # Red/Yellow/Green) and the link does not work as expected.
        for viewName in self.PREVIEW_VIEW_NAMES:
            sliceLogic = layoutManager.sliceWidget(viewName).sliceLogic()
            sliceLogic.GetSliceNode().SetViewGroup(self.PREVIEW_VIEW_GROUP)
            sliceLogic.GetSliceCompositeNode().SetLinkedControl(1)
        enable_zoom_sync("RingPreviewBefore", "RingPreviewAfter")
        enable_zoom_sync("RingPreviewAfter", "RingPreviewDiff")

    # -- Apply -----------------------------------------------------------

    def requestCancel(self):
        """Ask a running `apply` to stop. Checked once per slice."""
        self.cancelRequested = True

    def apply(
        self,
        inputVolume,
        centers,
        medianSize,
        outputName,
        mode="ring",
        arcWidth=5.0,
        radialCoherence=21,
        radiusRange=None,
        progressCallback=None,
    ):
        """Correct the whole volume, reporting progress once per slice.

        `radiusRange` is (r_min, r_max) in pixels from each point, None for an end without limit.
        `progressCallback(fraction)` receives a value in [0, 1]. If
        `requestCancel` was called, this raises `OperationCancelledError` and no
        output node is created.
        """
        self.cancelRequested = False
        array = slicer.util.arrayFromVolume(inputVolume)
        # Only the radial fan needs a sample mask; a ring center is always known.
        # A whole-volume percentile and mask are not affordable here. For a
        # 2000**3 uint16 volume np.percentile partitions a 16 GB copy and the
        # boolean mask costs another 8 GB. The percentile is streamed slice by
        # slice instead, exact for integer data and with nothing subsampled, and
        # the mask is derived per slice inside the correction loop from this same
        # threshold.
        backgroundLevel = low_memory_percentile(array, 1, axis=0) if mode == "line" else None

        # Each slice is corrected in float64 and stored back in the input dtype
        # right away. The output node is written in that dtype regardless, so
        # keeping a float64 volume would only quadruple the peak memory.
        corrected = array
        centersToUse = [centers[0]] if mode == "line" else (centers or [self.getDefaultCenter(inputVolume)])

        # One pass per center, each pass one slice at a time. The fraction below
        # spans the whole run, so the bar advances steadily rather than jumping
        # once per center, or only at the very end as it did in "line" mode.
        passCount = len(centersToUse)

        def makeSliceCallback(passIndex):
            def onSlice(done, total):
                if progressCallback is not None:
                    progressCallback((passIndex * total + done) / (passCount * total))
                # Checked after reporting, so the bar shows where it stopped.
                if self.cancelRequested:
                    raise OperationCancelledError()

            return onSlice

        rMin, rMax = radiusRange or (None, None)
        for i, center in enumerate(centersToUse):
            if mode == "line":
                corrected = remove_radial_streak_artifacts_volume(
                    corrected,
                    center,
                    axis=0,
                    arc_width=arcWidth,
                    radial_coherence=radialCoherence,
                    min_radius=rMin or 3.0,
                    max_radius=rMax,
                    out_dtype=array.dtype,
                    background_level=backgroundLevel,
                    progress_callback=makeSliceCallback(i),
                )
            else:
                corrected = remove_ring_artifacts_volume(
                    corrected,
                    axis=0,
                    center=center,
                    median_size=medianSize,
                    radius_range=radiusRange,
                    out_dtype=array.dtype,
                    progress_callback=makeSliceCallback(i),
                )

        return self._createOutputNode(inputVolume, corrected, outputName)

    @staticmethod
    def _createOutputNode(inputVolume, correctedArray, outputName):
        outputNode = slicer.mrmlScene.AddNewNodeByClass(inputVolume.GetClassName(), outputName)
        outputNode.CopyOrientation(inputVolume)
        slicer.util.updateVolumeFromArray(outputNode, correctedArray)
        outputNode.CreateDefaultDisplayNodes()
        if inputVolume.GetDisplayNode() is not None:
            outputNode.GetDisplayNode().Copy(inputVolume.GetDisplayNode())

        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        inputItem = subjectHierarchyNode.GetItemByDataNode(inputVolume)
        outputItem = subjectHierarchyNode.GetItemByDataNode(outputNode)
        subjectHierarchyNode.SetItemParent(outputItem, subjectHierarchyNode.GetItemParent(inputItem))

        return outputNode
