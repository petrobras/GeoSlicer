import logging
import os
from pathlib import Path

import ctk
import numpy as np
import qt
import slicer

from ltrace.algorithms.fast_registration import fast_reg, fast_reg_slicer
from ltrace.slicer import ui
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.utils.ProgressBarProc import ProgressBarProc

try:
    from Test.FastRegistrationTest import FastRegistrationTest
except ImportError:
    FastRegistrationTest = None  # tests not deployed to final version or closed source


# Actionable, user-facing text for each way fast_reg can fail. The keys are substrings of the
# RegistrationFailed reason (see fast_reg.register); the fallback covers anything unmapped.
_FAILURE_MESSAGES = {
    "too few blobs": (
        "Not enough high-density features were detected in one or both scans. This method needs "
        "compact, bright inclusions visible in both volumes. Try manual registration instead."
    ),
    "no RANSAC consensus": (
        "Features were detected but could not agree on a single alignment. The scans may not "
        "overlap, or may differ too much for automatic registration. Try manual registration."
    ),
    "consensus too low": (
        "Features were detected but too few agreed on a single alignment to trust the result. "
        "Try manual registration."
    ),
    "no geometric lock": (
        "Features were detected but could not agree on one rigid transform. The scans may not "
        "overlap, or may differ too much for automatic registration. Try manual registration."
    ),
}


def _failure_message(reason):
    for key, message in _FAILURE_MESSAGES.items():
        if key in reason:
            return message
    return f"Registration failed: {reason}. Try manual registration instead."


class FastRegistration(LTracePlugin):
    SETTING_KEY = "FastRegistration"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "MicroCT Fast Registration"
        self.parent.categories = ["Registration", "MicroCT"]
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = FastRegistration.help()
        self.setHelpUrl("Volumes/Register/Register.html")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class FastRegistrationWidget(LTracePluginWidget):
    # Foreground-opacity ping-pong (the "it worked" QC animation) advances by `_PING_PONG_STEP`
    # every `_PING_PONG_INTERVAL_MS`, bouncing between fully-fixed and fully-moving, and holding
    # for `_PING_PONG_DWELL_TICKS` ticks at each extreme so each volume is clearly readable.
    _PING_PONG_INTERVAL_MS = 30
    _PING_PONG_STEP = 0.05
    _PING_PONG_DWELL_TICKS = 12

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = None
        self._transformNode = None
        self._fixedNode = None
        self._movingNode = None
        self._pingPongTimer = None
        self._pingPongValue = 0.0
        self._pingPongDir = 1.0
        self._pingPongDwell = 0
        # Slice-viewer layer state captured just before the preview overrides it, so Cancel can
        # put the views back exactly as the user had them before the registration.
        self._displayState = None

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = FastRegistrationLogic()
        self.logic.registrationFinished.connect(self._onRegistrationFinished)

        self._pingPongTimer = qt.QTimer(self.parent)
        self._pingPongTimer.setInterval(self._PING_PONG_INTERVAL_MS)
        self._pingPongTimer.timeout.connect(self._onPingPongTick)

        # --- Input section ---
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.text = "Input"
        inputSection.collapsed = False
        inputLayout = qt.QFormLayout(inputSection)
        inputLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.fixedInput = ui.hierarchyVolumeInput(
            hasNone=True,
            nodeTypes=["vtkMRMLScalarVolumeNode"],
            onChange=self._onInputChanged,
            tooltip="The reference volume. It stays fixed; the moving volume is aligned to it.",
        )
        self.fixedInput.setMRMLScene(slicer.mrmlScene)
        self.fixedInput.resetStyleOnValidNode()
        inputLayout.addRow("Fixed volume:", self.fixedInput)

        self.movingInput = ui.hierarchyVolumeInput(
            hasNone=True,
            nodeTypes=["vtkMRMLScalarVolumeNode"],
            onChange=self._onInputChanged,
            tooltip="The volume to be aligned. It receives the registration transform.",
        )
        self.movingInput.setMRMLScene(slicer.mrmlScene)
        self.movingInput.resetStyleOnValidNode()
        inputLayout.addRow("Moving volume:", self.movingInput)

        self.validationLabel = qt.QLabel()
        self.validationLabel.setWordWrap(True)
        self.validationLabel.setStyleSheet("color: #C8963C;")
        self.validationLabel.visible = False
        inputLayout.addRow(self.validationLabel)

        # --- Apply ---
        # A plain button with a comfortable fixed height; the default ApplyButton renders its
        # label too small on high-DPI (4k) screens.
        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setFixedHeight(40)
        self.applyButton.setProperty("class", "actionButtonBackground")
        self.applyButton.setToolTip("Run fast registration")
        self.applyButton.enabled = False
        self.applyButton.objectName = "Apply Button"
        self.applyButton.clicked.connect(self._onApplyClicked)

        applyLayout = qt.QHBoxLayout()
        applyLayout.addWidget(self.applyButton)

        # --- Result section (hidden until a successful run) ---
        self.resultSection = self._buildResultSection()
        self.resultSection.visible = False

        # --- Failure section (hidden until a failed run) ---
        self.failureSection = self._buildFailureSection()
        self.failureSection.visible = False

        self.layout.addWidget(inputSection)
        self.layout.addSpacing(10)
        self.layout.addLayout(applyLayout)
        self.layout.addSpacing(12)
        self.layout.addWidget(self.resultSection)
        self.layout.addWidget(self.failureSection)
        self.layout.addStretch(1)

        self._updateApplyState()

    def _buildResultSection(self):
        section = ctk.ctkCollapsibleButton()
        section.text = "Result"
        section.collapsed = False
        layout = qt.QVBoxLayout(section)
        layout.setSpacing(5)

        # --- Status ---
        statusBox = qt.QGroupBox()
        statusLayout = qt.QVBoxLayout(statusBox)
        self.qcBanner = qt.QLabel()
        self.qcBanner.setWordWrap(True)
        self.qcBanner.setStyleSheet(
            "QLabel { background-color: #2E5D34; color: #FFFFFF; border-radius: 4px; padding: 8px; }"
        )
        statusLayout.addWidget(self.qcBanner)
        layout.addWidget(statusBox)

        # --- Alignment preview (ping-pong overlay controls) ---
        overlayBox = qt.QGroupBox("Alignment preview")
        overlayBox.setToolTip(
            "The fixed and aligned moving volumes are overlaid and cross-faded so you can confirm "
            "the alignment. Features that stay put as it fades mean the registration succeeded."
        )
        overlayLayout = qt.QHBoxLayout(overlayBox)
        overlayLayout.setSpacing(4)

        self.pauseButton = qt.QPushButton("Pause")
        self.pauseButton.setToolTip("Pause or resume the cross-fade preview.")
        self.pauseButton.clicked.connect(self._onPauseResumeClicked)
        overlayLayout.addWidget(self.pauseButton)

        self.showFixedButton = qt.QPushButton("Show fixed")
        self.showFixedButton.setToolTip("Pause the preview showing only the fixed volume.")
        self.showFixedButton.clicked.connect(lambda: self._pauseOn(0.0))
        overlayLayout.addWidget(self.showFixedButton)

        self.showMovingButton = qt.QPushButton("Show moving")
        self.showMovingButton.setToolTip("Pause the preview showing only the aligned moving volume.")
        self.showMovingButton.clicked.connect(lambda: self._pauseOn(1.0))
        overlayLayout.addWidget(self.showMovingButton)
        overlayLayout.addStretch(1)
        layout.addWidget(overlayBox)

        # --- Registration transform: matrix + copy ---
        transformBox = qt.QGroupBox("Registration transform (moving → fixed)")
        transformLayout = qt.QVBoxLayout(transformBox)
        self.matrixTable = qt.QTableWidget(4, 4)
        self.matrixTable.setFrameShape(qt.QFrame.NoFrame)
        self.matrixTable.horizontalHeader().setVisible(False)
        self.matrixTable.verticalHeader().setVisible(False)
        self.matrixTable.horizontalHeader().setSectionResizeMode(qt.QHeaderView.Stretch)
        verticalHeader = self.matrixTable.verticalHeader()
        # The style imposes a minimumSectionSize (32px here) that silently clamps our requested row
        # height, so the four rows ended up taller than the widget and scrolled a few pixels. Lower
        # the minimum so 30px is honoured, then size the widget to the header's *actual* length
        # (not a hardcoded 30*4) so content and viewport always match and no scrollbar can appear.
        verticalHeader.setMinimumSectionSize(1)
        verticalHeader.setSectionResizeMode(qt.QHeaderView.Fixed)
        verticalHeader.setDefaultSectionSize(30)
        self.matrixTable.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        self.matrixTable.setSelectionMode(qt.QAbstractItemView.NoSelection)
        self.matrixTable.setVerticalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        self.matrixTable.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        # NoFrame (set above) means zero frame width, so the header's total length is the exact
        # height the four rows occupy — sizing to it guarantees content and viewport match.
        self.matrixTable.setFixedHeight(verticalHeader.length())
        transformLayout.addWidget(self.matrixTable)

        # The matrix is reference material, not an action, so Copy sits unobtrusively in the
        # bottom-right corner of its own box instead of competing with the section's real buttons.
        self.copyMatrixButton = ui.ClickableLabel.flatSvgIconButton(
            "Copy",
            tooltip="Copy the 4x4 transform matrix to the clipboard.",
            onClick=self._onCopyMatrixClicked,
        )
        self.copyMatrixButton.objectName = "Copy Matrix Button"

        copyRow = qt.QHBoxLayout()
        copyRow.setContentsMargins(0, 0, 0, 0)
        copyRow.addStretch(1)
        copyRow.addWidget(self.copyMatrixButton)
        transformLayout.addLayout(copyRow)
        layout.addWidget(transformBox)

        # --- Finish: Cancel / Apply ---
        # Applying the registration is the step that ends the preview, so it lives here as the
        # section's own Apply, mirroring the input section's Apply above.
        layout.addSpacing(6)

        # Discards the registration: removes the transform, restores the views, and hides Result.
        self.cancelResultButton = qt.QPushButton("Cancel")
        self.cancelResultButton.setFixedHeight(40)
        self.cancelResultButton.setToolTip(
            "Discard this registration: remove the transform and restore the volumes and views to "
            "how they were before."
        )
        self.cancelResultButton.clicked.connect(self._onCancelResultClicked)

        self.applyTransformButton = qt.QPushButton("Apply")
        self.applyTransformButton.setFixedHeight(40)
        self.applyTransformButton.setProperty("class", "actionButtonBackground")
        self.applyTransformButton.setToolTip(
            "Keep this registration: write the alignment into the moving volume's position and end "
            "the preview. The voxels are not resampled, but this cannot be undone."
        )
        self.applyTransformButton.objectName = "Apply Transform Button"
        self.applyTransformButton.clicked.connect(self._onApplyTransformClicked)

        finishRow = qt.QHBoxLayout()
        finishRow.addWidget(self.cancelResultButton, 1)
        finishRow.addWidget(self.applyTransformButton, 1)
        layout.addLayout(finishRow)
        return section

    def _buildFailureSection(self):
        section = ctk.ctkCollapsibleButton()
        section.text = "Registration failed"
        section.collapsed = False
        layout = qt.QVBoxLayout(section)

        self.failureLabel = qt.QLabel()
        self.failureLabel.setWordWrap(True)
        self.failureLabel.setStyleSheet(
            "QLabel { background-color: #5D2E2E; color: #FFFFFF; border-radius: 4px; padding: 8px; }"
        )
        layout.addWidget(self.failureLabel)

        self.manualRegButton = qt.QPushButton("Switch to Manual Registration")
        self.manualRegButton.setToolTip("Open the Manual Registration module with these volumes.")
        self.manualRegButton.clicked.connect(self._onManualRegistrationClicked)
        layout.addWidget(self.manualRegButton)
        return section

    # ------------------------------------------------------------------ public API

    def setMovingNode(self, node):
        """Select `node` as the moving volume.

        Entry point for callers outside this module, such as the Explorer's "Register this..."
        context-menu action.
        """
        self.movingInput.setCurrentNode(node)

    # ------------------------------------------------------------------ validation

    def _onInputChanged(self, *args):
        self._updateApplyState()

    def _validationError(self):
        """Return a user-facing reason the inputs can't be registered, or None if they're valid.

        Empty string means "not ready yet" (missing selection) with nothing to warn about.
        """
        fixed = self.fixedInput.currentNode()
        moving = self.movingInput.currentNode()
        if fixed is None or moving is None:
            return ""
        if fixed is moving:
            return "Fixed and moving volumes must be different."
        if not np.allclose(fixed.GetSpacing(), moving.GetSpacing(), rtol=1e-3):
            return "Fixed and moving volumes must have the same voxel spacing."
        return None

    def _updateApplyState(self):
        error = self._validationError()
        # While a registration is waiting to be applied or discarded, the only Apply that means
        # anything is the one in the Result section: lock this one so there are never two.
        pending = self._transformNode is not None
        self.applyButton.enabled = error is None and not pending
        self.applyButton.setToolTip(
            "Apply or cancel the current registration first" if pending else "Run fast registration"
        )
        self.validationLabel.text = error or ""
        self.validationLabel.visible = bool(error)

    # ------------------------------------------------------------------ apply

    def _onApplyClicked(self, *args):
        if self._validationError() is not None:
            return
        self._fixedNode = self.fixedInput.currentNode()
        self._movingNode = self.movingInput.currentNode()

        self._resetOutputs()
        self._setRunning(True)
        try:
            # The algorithm runs on the GUI thread and blocks it for the whole run (~20 s for a
            # 12 GB pair): Slicer's bundled NumPy holds the GIL in a way that keeps a worker thread
            # from freeing the UI, and VTK/MRML access is not thread-safe. ProgressBarProc draws
            # from its own process, so it keeps showing real progress while this thread is stuck.
            with ProgressBarProc() as progressBar:
                progressBar.setTitle("Fast Registration")

                def onProgress(fraction, message):
                    progressBar.nextStep(int(fraction * 100), message)

                self.logic.run(self._fixedNode, self._movingNode, progress_callback=onProgress)
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected to the user
            # run() reports algorithm failures through `error`/`failure`, so this only catches the
            # progress window itself failing to start -- in which case no finished signal is coming
            # and the busy state has to be cleared here.
            logging.error("Fast registration could not start: %s", exc, exc_info=True)
            slicer.util.errorDisplay(f"Registration could not be started: {exc}")
            self._setRunning(False)

    def _setRunning(self, running):
        """Toggle the busy state: while a registration runs, Apply and the inputs are locked. The
        finished handler flips it back regardless of outcome."""
        self.applyButton.enabled = not running
        self.fixedInput.enabled = not running
        self.movingInput.enabled = not running
        if not running:
            self._updateApplyState()

    def _onRegistrationFinished(self):
        self._setRunning(False)
        if self.logic.result is not None:
            self._transformNode, ras_matrix = fast_reg_slicer.build_transform_node(
                self._fixedNode, self._movingNode, self.logic.result
            )
            self._showResult(self.logic.result, ras_matrix)
        elif self.logic.failure is not None:
            logging.info(
                "Fast registration failed: %s (%s)",
                self.logic.failure.get("reason"),
                self.logic.failure.get("diagnostics"),
            )
            self._showFailure(self.logic.failure.get("reason", ""))
        elif self.logic.error is not None:
            slicer.util.errorDisplay(f"Registration could not be completed: {self.logic.error}")
        # else: nothing to show. Only reachable once runs can be cancelled again (see the class
        # docstring on FastRegistrationLogic); a synchronous run always sets one of the three.

    # ------------------------------------------------------------------ result display

    def _showResult(self, index_matrix, ras_matrix):
        self.failureSection.visible = False
        r = index_matrix[:3, :3]
        rotation_deg = np.degrees(np.arccos(np.clip((np.trace(r) - 1) / 2, -1.0, 1.0)))
        self.qcBanner.text = f"Registration succeeded: {rotation_deg:.1f}° rotation."
        self._fillMatrixTable(ras_matrix)
        self.applyTransformButton.enabled = True
        self.cancelResultButton.enabled = True
        self.resultSection.visible = True
        self._startPingPong()
        self._updateApplyState()

    def _fillMatrixTable(self, matrix):
        for i in range(4):
            for j in range(4):
                item = qt.QTableWidgetItem(f"{matrix[i, j]:.4f}")
                item.setTextAlignment(qt.Qt.AlignCenter)
                self.matrixTable.setItem(i, j, item)

    def _showFailure(self, reason):
        self._resetOutputs()
        self.failureLabel.text = _failure_message(reason)
        self.failureSection.visible = True

    # ------------------------------------------------------------------ ping-pong overlay

    def _startPingPong(self):
        if self._fixedNode is None or self._movingNode is None:
            return
        self._displayState = self._captureDisplayState()
        self._applyPreviewLayers(fit=True)
        self._setForegroundOpacity(0.0)
        self._pingPongValue = 0.0
        self._pingPongDir = 1.0
        self._pingPongDwell = 0
        self.pauseButton.text = "Pause"
        self._pingPongTimer.start()

    def _stopPingPong(self):
        if self._pingPongTimer is not None:
            self._pingPongTimer.stop()

    def _onPingPongTick(self):
        # Hold at an extreme for a few ticks so each volume is clearly readable before reversing.
        if self._pingPongDwell > 0:
            self._pingPongDwell -= 1
            return
        self._pingPongValue += self._pingPongDir * self._PING_PONG_STEP
        if self._pingPongValue >= 1.0:
            self._pingPongValue = 1.0
            self._pingPongDir = -1.0
            self._pingPongDwell = self._PING_PONG_DWELL_TICKS
        elif self._pingPongValue <= 0.0:
            self._pingPongValue = 0.0
            self._pingPongDir = 1.0
            self._pingPongDwell = self._PING_PONG_DWELL_TICKS
        self._setForegroundOpacity(self._pingPongValue)

    def _applyPreviewLayers(self, fit=False):
        """(Re)assert the preview arrangement: fixed as background, aligned moving as foreground.

        The displayed layers can be changed from outside this module -- the Data module's visibility
        toggles, for instance -- which leaves the cross-fade driving a foreground opacity that no
        longer has anything to do with the two registered volumes, so the preview looks dead. Every
        preview control re-asserts the arrangement first, so clicking one always brings the preview
        back instead of appearing to do nothing.
        """
        if self._fixedNode is None or self._movingNode is None:
            return
        slicer.util.setSliceViewerLayers(background=self._fixedNode, foreground=self._movingNode, fit=fit)

    def _pauseOn(self, opacity):
        """Pause the preview on one extreme (0.0 = fixed only, 1.0 = moving only)."""
        self._stopPingPong()
        self.pauseButton.text = "Resume"
        self._applyPreviewLayers()
        self._pingPongValue = opacity
        self._pingPongDir = -1.0 if opacity >= 1.0 else 1.0
        self._pingPongDwell = 0
        self._setForegroundOpacity(opacity)

    def _setForegroundOpacity(self, value):
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return
        for sliceViewName in layoutManager.sliceViewNames():
            sliceWidget = layoutManager.sliceWidget(sliceViewName)
            if sliceWidget is None:
                continue
            compositeNode = sliceWidget.sliceLogic().GetSliceCompositeNode()
            compositeNode.SetForegroundOpacity(value)

    def _captureDisplayState(self):
        """Snapshot the current background/foreground volumes and foreground opacity so Cancel can
        restore the slice views. Returns None if there are no slice views to read from."""
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return None
        names = layoutManager.sliceViewNames()
        if not names:
            return None
        composite = layoutManager.sliceWidget(names[0]).sliceLogic().GetSliceCompositeNode()
        return {
            "background": composite.GetBackgroundVolumeID(),
            "foreground": composite.GetForegroundVolumeID(),
            "foregroundOpacity": composite.GetForegroundOpacity(),
        }

    def _restoreDisplayState(self, state):
        if state is None:
            return
        scene = slicer.mrmlScene
        background = scene.GetNodeByID(state["background"]) if state["background"] else None
        foreground = scene.GetNodeByID(state["foreground"]) if state["foreground"] else None
        slicer.util.setSliceViewerLayers(
            background=background,
            foreground=foreground,
            foregroundOpacity=state["foregroundOpacity"],
        )

    def _onPauseResumeClicked(self):
        self._applyPreviewLayers()
        if self._pingPongTimer.isActive():
            self._pingPongTimer.stop()
            self.pauseButton.text = "Resume"
        else:
            self._pingPongTimer.start()
            self.pauseButton.text = "Pause"
        # The opacity can also have been changed from outside, so put it back on the preview's own
        # value: both a paused frame and a resumed fade then show what the buttons say they show.
        self._setForegroundOpacity(self._pingPongValue)

    # ------------------------------------------------------------------ matrix actions

    def _onCopyMatrixClicked(self):
        rows = []
        for i in range(4):
            rows.append(" ".join(self.matrixTable.item(i, j).text() for j in range(4)))
        qt.QApplication.clipboard().setText("\n".join(rows))

    def _onApplyTransformClicked(self):
        """Keep the registration: bake the transform into the moving volume's geometry (an
        IJK-to-RAS update, no resampling) and drop the now-redundant transform node."""
        if self._movingNode is None or self._transformNode is None:
            return
        self._movingNode.HardenTransform()
        slicer.mrmlScene.RemoveNode(self._transformNode)
        self._transformNode = None
        self.applyTransformButton.enabled = False
        # The transform is now baked into the moving volume; there is nothing left to revert.
        self.cancelResultButton.enabled = False
        self._pauseOn(1.0)
        self.qcBanner.text = f"Alignment applied to '{self._movingNode.GetName()}'."
        self._updateApplyState()

    def _onCancelResultClicked(self):
        """Discard the registration: drop the transform (reverting the moving volume), put the
        slice views back the way they were, and hide the Result section."""
        displayState = self._displayState
        self._resetOutputs()
        self._restoreDisplayState(displayState)

    def _onManualRegistrationClicked(self):
        try:
            slicer.util.selectModule("MicroCTTransforms")
            widget = slicer.modules.microcttransforms.widgetRepresentation().self()
            if self._movingNode is not None:
                widget.movingNodeSelector.setCurrentNode(self._movingNode)
        except Exception as exc:  # noqa: BLE001 - best-effort convenience, never block the switch
            logging.warning("Could not pre-select the moving volume in Manual Registration: %s", exc)

    # ------------------------------------------------------------------ lifecycle

    def _resetOutputs(self):
        self._stopPingPong()
        if self._transformNode is not None and slicer.mrmlScene.IsNodePresent(self._transformNode):
            slicer.mrmlScene.RemoveNode(self._transformNode)
        self._transformNode = None
        self._displayState = None
        self.resultSection.visible = False
        self.failureSection.visible = False
        self._updateApplyState()

    def exit(self):
        if self._transformNode is not None:
            self._onCancelResultClicked()
        else:
            self._stopPingPong()
            self.pauseButton.text = "Resume"
        if self.logic is not None:
            self.logic.cancel()

    def cleanup(self):
        super().cleanup()
        self._stopPingPong()
        if self.logic is not None:
            self.logic.cancel()
            # Drop the signal connection so the logic no longer holds this widget alive through the
            # bound slot (otherwise the widget leaks after the module is torn down).
            self.logic.registrationFinished.disconnect(self._onRegistrationFinished)
        if self._pingPongTimer is not None:
            self._pingPongTimer.timeout.disconnect()
            self._pingPongTimer = None


class FastRegistrationLogic(LTracePluginLogic):
    registrationFinished = qt.Signal()

    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.result = None
        self.failure = None
        self.error = None

    def run(self, fixedNode, movingNode, progress_callback=None):
        """Register movingNode onto fixedNode, blocking until it finishes.

        `progress_callback(fraction, message)` is forwarded to fast_reg.register. The result is
        published on `registrationFinished`, not returned -- see the class docstring.
        """
        self.result = self.failure = self.error = None
        try:
            fixed_arr = slicer.util.arrayFromVolume(fixedNode)
            moving_arr = slicer.util.arrayFromVolume(movingNode)
            self.result = fast_reg.register(fixed_arr, moving_arr, progress_callback=progress_callback)
        except fast_reg.RegistrationFailed as exc:
            # A structured failure is an expected outcome, not a crash: the widget maps the reason
            # to actionable text.
            self.failure = {"reason": str(exc), "diagnostics": exc.diagnostics}
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected to the user
            logging.error("Fast registration error: %s", exc, exc_info=True)
            self.error = str(exc)
        # Deferred to the next event-loop turn so the caller's progress window is torn down before
        # the result UI appears, and so no caller can come to depend on the signal arriving inline.
        qt.QTimer.singleShot(0, self.registrationFinished.emit)

    def cancel(self):
        """No-op: a synchronous run cannot be interrupted. Kept so the widget's teardown path is
        the same one an out-of-process version needs."""
