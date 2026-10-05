"""Scrubber widget for a 4D dataset.

Bound to a :class:`~ltrace.slicer.virtual.fourd.player.FourDPlayer`, which owns all the behaviour; this is
only the surface. It is embedded both in the Explorer panel (when a 4D proxy node is selected) and in the
modules that create 4D nodes, so the controls are where the user already is.
"""

import qt

from ltrace.slicer.virtual.fourd import proxy
from ltrace.slicer.virtual.fourd.player import FourDPlayer


class FourDPlayerWidget(qt.QWidget):
    def __init__(self, parent=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.player = None
        self._updating = False
        self.setup()

    # -- construction ---------------------------------------------------------------------------------
    def setup(self):
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        style = self.style()

        self.firstButton = self._button(style.standardIcon(qt.QStyle.SP_MediaSkipBackward), "First frame", "First")
        self.previousButton = self._button(
            style.standardIcon(qt.QStyle.SP_MediaSeekBackward), "Previous frame (by the step below)", "Previous"
        )
        self.playButton = self._button(style.standardIcon(qt.QStyle.SP_MediaPlay), "Play / pause", "Play")
        self.nextButton = self._button(
            style.standardIcon(qt.QStyle.SP_MediaSeekForward), "Next frame (by the step below)", "Next"
        )
        self.lastButton = self._button(style.standardIcon(qt.QStyle.SP_MediaSkipForward), "Last frame", "Last")

        self.stepSpinBox = qt.QSpinBox()
        self.stepSpinBox.objectName = "FourD Step SpinBox"
        self.stepSpinBox.setRange(1, 9999)
        self.stepSpinBox.setValue(1)
        self.stepSpinBox.setToolTip("How many frames the previous/next buttons and playback advance at a time.")
        self.stepSpinBox.setFixedWidth(60)

        transportLayout = qt.QHBoxLayout()
        for widget in (self.firstButton, self.previousButton, self.playButton, self.nextButton, self.lastButton):
            transportLayout.addWidget(widget)
        transportLayout.addSpacing(8)
        transportLayout.addWidget(qt.QLabel("Step:"))
        transportLayout.addWidget(self.stepSpinBox)
        transportLayout.addStretch(1)
        layout.addLayout(transportLayout)

        self.frameSlider = qt.QSlider(qt.Qt.Horizontal)
        self.frameSlider.objectName = "FourD Frame Slider"
        self.frameSlider.setToolTip("Scrub through the sequence. Frames are shown from the downsampled preview.")
        self.frameSlider.setSingleStep(1)
        self.frameSlider.setPageStep(1)
        self.frameSlider.valueChanged.connect(self._onSliderChanged)

        self.frameLabel = qt.QLabel()
        self.frameLabel.objectName = "FourD Frame Label"
        self.frameLabel.setMinimumWidth(140)
        self.frameLabel.setAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)

        sliderLayout = qt.QHBoxLayout()
        sliderLayout.addWidget(self.frameSlider, 1)
        sliderLayout.addWidget(self.frameLabel)
        layout.addLayout(sliderLayout)

        self.loopCheckBox = qt.QCheckBox("Loop")
        self.loopCheckBox.objectName = "FourD Loop CheckBox"
        self.loopCheckBox.setToolTip("Restart from the first frame when playback reaches the end.")
        self.loopCheckBox.toggled.connect(self._onLoopToggled)

        self.followCheckBox = qt.QCheckBox("Follow latest")
        self.followCheckBox.objectName = "FourD Follow CheckBox"
        self.followCheckBox.setToolTip(
            "Keep showing the newest frame as it is written. Use this to watch a simulation while it runs."
        )
        self.followCheckBox.toggled.connect(self._onFollowToggled)

        togglesLayout = qt.QHBoxLayout()
        togglesLayout.addWidget(self.loopCheckBox)
        togglesLayout.addWidget(self.followCheckBox)
        togglesLayout.addStretch(1)
        layout.addLayout(togglesLayout)

        self.resolutionLabel = qt.QLabel()
        self.resolutionLabel.objectName = "FourD Resolution Label"

        self.loadFullButton = qt.QPushButton("Load full resolution")
        self.loadFullButton.objectName = "FourD Load Full Button"
        self.loadFullButton.setToolTip(
            "Read the current frame at full resolution. Available once you stop on a frame; the preview is "
            "kept for every other frame so scrubbing stays fast."
        )
        self.loadFullButton.clicked.connect(self._onLoadFullClicked)

        self.autoFullCheckBox = qt.QCheckBox("automatically")
        self.autoFullCheckBox.objectName = "FourD Auto Full CheckBox"
        self.autoFullCheckBox.setToolTip(
            "Load the full resolution on its own whenever you settle on a frame. Off by default, because a "
            "full frame can be hundreds of megabytes."
        )
        self.autoFullCheckBox.toggled.connect(self._onAutoFullToggled)

        self.reloadButton = qt.QPushButton("Reload frames")
        self.reloadButton.objectName = "FourD Reload Button"
        self.reloadButton.setToolTip(
            "Re-list the folder and re-read every cached frame. Frames that appear or grow are picked up "
            "automatically; use this after frames were rewritten in place."
        )
        self.reloadButton.clicked.connect(self._onReloadClicked)

        resolutionLayout = qt.QHBoxLayout()
        resolutionLayout.addWidget(self.loadFullButton)
        resolutionLayout.addWidget(self.autoFullCheckBox)
        resolutionLayout.addStretch(1)
        resolutionLayout.addWidget(self.reloadButton)
        layout.addWidget(self.resolutionLabel)
        layout.addLayout(resolutionLayout)

        self.cacheLabel = qt.QLabel()
        self.cacheLabel.objectName = "FourD Cache Label"
        self.cacheLabel.setStyleSheet("QLabel { color: palette(mid); }")
        layout.addWidget(self.cacheLabel)

        self.firstButton.clicked.connect(lambda: self._withPlayer(lambda player: player.firstFrame()))
        self.previousButton.clicked.connect(lambda: self._withPlayer(lambda player: player.previousFrame()))
        self.playButton.clicked.connect(lambda: self._withPlayer(lambda player: player.togglePlay()))
        self.nextButton.clicked.connect(lambda: self._withPlayer(lambda player: player.nextFrame()))
        self.lastButton.clicked.connect(lambda: self._withPlayer(lambda player: player.lastFrame()))
        self.stepSpinBox.valueChanged.connect(lambda value: self._withPlayer(lambda player: player.setStep(value)))

        self.setEnabled(False)

    def _button(self, icon, tooltip: str, name: str) -> qt.QToolButton:
        button = qt.QToolButton()
        button.setIcon(icon)
        button.setToolTip(tooltip)
        button.objectName = f"FourD {name} Button"
        button.setAutoRaise(True)
        return button

    # -- binding --------------------------------------------------------------------------------------
    def setPlayer(self, player: FourDPlayer) -> None:
        if self.player is player:
            self.updateWidgets()
            return

        self._disconnectPlayer()
        self.player = player

        if player is None:
            self.setEnabled(False)
            self.frameLabel.setText("")
            self.cacheLabel.setText("")
            self.resolutionLabel.setText("")
            return

        player.frameChanged.connect(self._onFrameChanged)
        player.stateChanged.connect(self.updateWidgets)
        player.cacheChanged.connect(self._onCacheChanged)
        player.framesAppended.connect(lambda count: self.updateWidgets())
        player.frameUnavailable.connect(self._onFrameUnavailable)

        self.setEnabled(True)
        self.updateWidgets()
        self._onCacheChanged(str(player.cacheStats()))

    def clear(self) -> None:
        self.setPlayer(None)

    def _disconnectPlayer(self) -> None:
        if self.player is None:
            return
        for signal in (
            self.player.frameChanged,
            self.player.stateChanged,
            self.player.cacheChanged,
            self.player.framesAppended,
            self.player.frameUnavailable,
        ):
            try:
                signal.disconnect()
            except (TypeError, RuntimeError):
                pass

    # -- updates --------------------------------------------------------------------------------------
    def updateWidgets(self) -> None:
        player = self.player
        if player is None:
            return

        self._updating = True
        try:
            count = player.frameCount
            self.frameSlider.setRange(0, max(0, count - 1))
            self.frameSlider.setValue(player.index)
            self.frameSlider.setEnabled(count > 1)

            label = player.frameLabel()
            self.frameLabel.setText(f"frame {player.index + 1}/{count}" + (f" · {label}" if label else ""))

            self.stepSpinBox.setValue(player.step)
            self.loopCheckBox.setChecked(player.loop)
            self.followCheckBox.setChecked(player.follow)
            self.autoFullCheckBox.setChecked(player.autoLoadFull)

            style = self.style()
            self.playButton.setIcon(
                style.standardIcon(qt.QStyle.SP_MediaPause if player.playing else qt.QStyle.SP_MediaPlay)
            )

            isFull = player.resolution == proxy.RESOLUTION_FULL
            if not player.frameAvailable:
                self.resolutionLabel.setText(
                    f"Frame {player.index + 1} could not be read — it may still be being written."
                )
            else:
                self.resolutionLabel.setText(
                    "Showing this frame at full resolution."
                    if isFull
                    else f"Showing a 1:{player.cache.factor} preview of each axis."
                )
            self.loadFullButton.setEnabled(
                player.settled and not player.playing and not isFull and player.frameAvailable
            )
        finally:
            self._updating = False

    def _onFrameChanged(self, index: int) -> None:
        self.updateWidgets()

    def _onCacheChanged(self, text: str) -> None:
        self.cacheLabel.setText(text)

    def _onFrameUnavailable(self, index: int) -> None:
        self.updateWidgets()

    # -- input ----------------------------------------------------------------------------------------
    def _withPlayer(self, action) -> None:
        if self.player is not None and not self._updating:
            action(self.player)

    def _onSliderChanged(self, value: int) -> None:
        self._withPlayer(lambda player: player.seek(value))

    def _onLoopToggled(self, checked: bool) -> None:
        self._withPlayer(lambda player: player.setLoop(checked))

    def _onFollowToggled(self, checked: bool) -> None:
        self._withPlayer(lambda player: player.setFollow(checked))

    def _onAutoFullToggled(self, checked: bool) -> None:
        self._withPlayer(lambda player: player.setAutoLoadFull(checked))

    def _onReloadClicked(self) -> None:
        if self.player is None:
            return

        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            self.player.reload()
        finally:
            qt.QApplication.restoreOverrideCursor()

    def _onLoadFullClicked(self) -> None:
        if self.player is None:
            return

        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            self.player.loadFullResolution()
        finally:
            qt.QApplication.restoreOverrideCursor()
