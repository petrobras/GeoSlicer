import logging
import os
import re
import traceback
from pathlib import Path

import ctk
import qt
import slicer

from ltrace.slicer import ui
from ltrace.slicer.helpers import BlockSignals
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer.virtual import folder as virtual_folder
from ltrace.slicer.virtual.fourd.dataset import FourDDataset
from ltrace.slicer.virtual.fourd.manager import get_manager as get_fourd_manager
from ltrace.slicer.virtual.monitor import FolderMonitorService
from ltrace.slicer.widget.fourd_player import FourDPlayerWidget
from ltrace.slicer_utils import LTracePlugin, LTracePluginLogic, LTracePluginWidget

try:
    from Test.FolderMonitorTest import FolderMonitorTest
except ImportError:
    FolderMonitorTest = None  # tests not deployed to final version or closed source


class FolderMonitor(LTracePlugin):
    SETTING_KEY = "FolderMonitor"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Folder Monitor"
        self.parent.categories = ["Tools", "MicroCT", "Multiscale"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = (
            "Import a folder without loading it: each dataset inside becomes a node holding a small sample "
            "of the data, and the folder can be kept in sync while it is still being written. Numbered "
            "entries can be loaded as a time sequence (4D) instead."
        )

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class FolderMonitorWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = FolderMonitorLogic()
        self.__scan = None

    # -- construction ---------------------------------------------------------------------------------
    def setup(self):
        LTracePluginWidget.setup(self)

        self.layout.addWidget(self.__setupImportSection())
        self.layout.addWidget(self.__setupSequenceSection())
        self.layout.addWidget(self.__setupMonitoredSection())
        self.layout.addStretch(1)

        self.logic.folderChanged.connect(self.__onFolderRegistryChanged)
        self.__onDirectorySelected(self.directoryButton.directory)
        self.__refreshMonitoredList()

    def __setupImportSection(self):
        section = ctk.ctkCollapsibleButton()
        section.text = "Import folder"
        section.collapsed = False
        layout = qt.QFormLayout(section)

        self.directoryButton = ctk.ctkDirectoryButton()
        self.directoryButton.setMaximumWidth(374)
        self.directoryButton.objectName = "Folder Monitor Directory Button"
        self.directoryButton.setToolTip("Folder to list. Its contents stay on disk.")
        saved = FolderMonitor.get_setting("InputDir", None)
        if saved:
            self.directoryButton.directory = saved
        self.directoryButton.directoryChanged.connect(self.__onDirectorySelected)
        layout.addRow("Folder:", self.directoryButton)

        self.deferredCheckBox = qt.QCheckBox("Deferred loading (keep the data on disk)")
        self.deferredCheckBox.objectName = "Folder Monitor Deferred CheckBox"
        self.deferredCheckBox.setToolTip(
            "Load only a small sample of each dataset — the first rows of a table, a downsampled image — and "
            "read the rest on demand. Uncheck to load everything into memory now."
        )
        self.deferredCheckBox.setChecked(True)
        layout.addRow(self.deferredCheckBox)

        self.monitorCheckBox = qt.QCheckBox("Keep in sync with the folder")
        self.monitorCheckBox.objectName = "Folder Monitor Sync CheckBox"
        self.monitorCheckBox.setToolTip(
            "Watch the folder and list datasets as they appear or change. Use this while a simulation or an "
            "acquisition is still writing into it."
        )
        self.monitorCheckBox.setChecked(True)
        layout.addRow(self.monitorCheckBox)

        self.scanLabel = qt.QLabel()
        self.scanLabel.setWordWrap(True)
        self.scanLabel.objectName = "Folder Monitor Scan Label"
        layout.addRow(self.scanLabel)

        self.importButton = ui.ApplyButton(
            onClick=self.__onImportClicked, text="Import folder", tooltip="List this folder's datasets as nodes."
        )
        self.importButton.objectName = "Folder Monitor Import Button"
        layout.addRow(self.importButton)

        return section

    def __setupSequenceSection(self):
        section = ctk.ctkCollapsibleButton()
        section.text = "Time sequence (4D)"
        section.collapsed = False
        section.setToolTip(
            "Load numbered entries of the folder as the frames of one time sequence, played from a "
            "downsampled preview so that memory does not grow with the number of frames."
        )
        layout = qt.QFormLayout(section)

        self.patternComboBox = qt.QComboBox()
        self.patternComboBox.objectName = "Folder Monitor Pattern ComboBox"
        self.patternComboBox.setEditable(True)
        self.patternComboBox.setToolTip(
            "Regular expression matching the frame folders or files, e.g. 'vis\\d+' or 'recon_\\d+'. "
            "Suggestions come from the names found in the folder."
        )
        self.patternComboBox.currentTextChanged.connect(self.__onPatternChanged)
        layout.addRow("Frame pattern:", self.patternComboBox)

        self.variableComboBox = qt.QComboBox()
        self.variableComboBox.objectName = "Folder Monitor Variable ComboBox"
        self.variableComboBox.setToolTip("Which field of each frame to show (LBPM frames hold several).")
        layout.addRow("Field:", self.variableComboBox)

        self.frameLabel = qt.QLabel()
        self.frameLabel.setWordWrap(True)
        self.frameLabel.objectName = "Folder Monitor Frame Label"
        layout.addRow(self.frameLabel)

        self.excludeFramesCheckBox = qt.QCheckBox("Keep these frames out of the folder listing")
        self.excludeFramesCheckBox.objectName = "Folder Monitor Exclude Frames CheckBox"
        self.excludeFramesCheckBox.setToolTip(
            "Matching entries belong to the sequence, so they are not listed as separate datasets. Uncheck "
            "to get both: a node per entry and the sequence."
        )
        self.excludeFramesCheckBox.setChecked(True)
        self.excludeFramesCheckBox.toggled.connect(lambda _: self.__rescan())
        layout.addRow(self.excludeFramesCheckBox)

        self.followCheckBox = qt.QCheckBox("Follow the newest frame while it is written")
        self.followCheckBox.objectName = "Folder Monitor Follow CheckBox"
        self.followCheckBox.setToolTip(
            "Jump to the latest frame as new ones appear. Useful for a running simulation. This sets how a "
            "sequence starts; after that the scrubber's own Follow latest owns it."
        )
        layout.addRow(self.followCheckBox)

        self.createFourDButton = qt.QPushButton("Create 4D node")
        self.createFourDButton.objectName = "Folder Monitor Create 4D Button"
        self.createFourDButton.setToolTip(
            "Show the frames this pattern matches as one time sequence. A folder already shown is refreshed "
            "rather than added a second time."
        )
        self.createFourDButton.setFixedHeight(30)
        self.createFourDButton.clicked.connect(self.__onCreateFourDClicked)
        layout.addRow(self.createFourDButton)

        self.playerWidget = FourDPlayerWidget()
        self.playerWidget.visible = False
        layout.addRow(self.playerWidget)

        return section

    def __setupMonitoredSection(self):
        section = ctk.ctkCollapsibleButton()
        section.text = "Monitored folders"
        section.collapsed = False
        layout = qt.QVBoxLayout(section)

        self.monitoredList = qt.QListWidget()
        self.monitoredList.objectName = "Folder Monitor List"
        self.monitoredList.setSelectionMode(qt.QAbstractItemView.SingleSelection)
        self.monitoredList.setMinimumHeight(90)
        layout.addWidget(self.monitoredList)

        buttonsLayout = qt.QHBoxLayout()

        self.syncButton = qt.QPushButton("Sync now")
        self.syncButton.objectName = "Folder Monitor Sync Button"
        self.syncButton.setToolTip("Look for new or changed datasets in the selected folder immediately.")
        self.syncButton.clicked.connect(self.__onSyncClicked)
        buttonsLayout.addWidget(self.syncButton)

        self.stopButton = qt.QPushButton("Stop monitoring")
        self.stopButton.objectName = "Folder Monitor Stop Button"
        self.stopButton.setToolTip("Keep the nodes but stop watching the folder.")
        self.stopButton.clicked.connect(self.__onStopClicked)
        buttonsLayout.addWidget(self.stopButton)

        layout.addLayout(buttonsLayout)
        return section

    # -- events ---------------------------------------------------------------------------------------
    def __onDirectorySelected(self, directory):
        path = Path(directory) if directory else None
        if path is None or not path.is_dir():
            self.scanLabel.setText("Select a folder to see what it holds.")
            self.importButton.enabled = False
            return

        # Suggestions first: what the scan reports depends on which entries are claimed by a sequence.
        self.__fillPatternSuggestions(path)
        self.__rescan()

    def __rescan(self):
        directory = self.directoryButton.directory
        path = Path(directory) if directory else None
        if path is None or not path.is_dir():
            return

        try:
            self.__scan = self.logic.preview(path, pattern=self.__effectivePattern())
        except Exception as error:
            logging.info(f"Unable to scan {path}: {error}\n{traceback.format_exc()}")
            self.scanLabel.setText(f"This folder could not be read: {error}")
            self.importButton.enabled = False
            return

        self.importButton.enabled = bool(self.__scan.items) or bool(self.__scan.frames)
        self.scanLabel.setText(self.logic.describeScan(self.__scan))

    def __fillPatternSuggestions(self, path):
        with BlockSignals(self.patternComboBox):
            self.patternComboBox.clear()
            for pattern, count, examples in self.logic.suggestPatterns(path):
                self.patternComboBox.addItem(f"{pattern}    ({count} matches: {', '.join(examples)}…)", pattern)
        self.__onPatternChanged(self.patternComboBox.currentText)

    def __onPatternChanged(self, _text=None):
        pattern = self.__currentPattern()
        self.variableComboBox.clear()
        self.frameLabel.setText("")
        self.createFourDButton.enabled = False

        if not pattern:
            self.__rescan()
            return

        try:
            summary, variables = self.logic.previewSequence(Path(self.directoryButton.directory), pattern)
        except Exception as error:
            self.frameLabel.setText(f"{error}")
            self.__rescan()
            return

        self.frameLabel.setText(summary)
        self.__rescan()
        for variable in variables:
            self.variableComboBox.addItem(variable)
        self.variableComboBox.enabled = len(variables) > 1
        self.createFourDButton.enabled = True

    def __effectivePattern(self):
        """The pattern the import must skip, or ``None`` when every entry should be listed."""
        if not getattr(self, "excludeFramesCheckBox", None) or not self.excludeFramesCheckBox.checked:
            return None
        return self.__currentPattern()

    def __currentPattern(self):
        data = self.patternComboBox.currentData
        if data:
            return data
        text = self.patternComboBox.currentText.split("    (")[0].strip()
        return text or None

    def __onImportClicked(self):
        directory = Path(self.directoryButton.directory)
        FolderMonitor.set_setting("InputDir", directory.as_posix())

        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            report = self.logic.importFolder(
                directory,
                deferred=self.deferredCheckBox.checked,
                monitored=self.monitorCheckBox.checked,
                pattern=self.__effectivePattern(),
            )
            slicer.util.showStatusMessage(f"{directory.name}: {report.summary()}", 5000)
            self.scanLabel.setText(f"Imported: {report.summary()}.")
        except Exception as error:
            logging.error(f"Failed to import {directory}: {error}\n{traceback.format_exc()}")
            slicer.util.errorDisplay(f"Could not import this folder: {error}")
        finally:
            qt.QApplication.restoreOverrideCursor()
            self.__refreshMonitoredList()

    def __onCreateFourDClicked(self):
        directory = Path(self.directoryButton.directory)
        pattern = self.__currentPattern()
        if not pattern:
            return

        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            node, player = self.logic.createSequence(
                directory,
                pattern=pattern,
                variable=self.variableComboBox.currentText or None,
                follow=self.followCheckBox.checked,
            )
            self.playerWidget.setPlayer(player)
            self.playerWidget.visible = True
            slicer.util.showStatusMessage(f"{node.GetName()}: {player.frameCount} frames", 5000)
        except Exception as error:
            logging.error(f"Failed to create a 4D node for {directory}: {error}\n{traceback.format_exc()}")
            slicer.util.errorDisplay(f"Could not create the time sequence: {error}")
        finally:
            qt.QApplication.restoreOverrideCursor()
            self.__refreshMonitoredList()

    def __onSyncClicked(self):
        root = self.__selectedRoot()
        if root is None:
            return
        report = self.logic.sync(root)
        slicer.util.showStatusMessage(f"{Path(root).name}: {report.summary()}", 5000)
        self.__refreshMonitoredList()

    def __onStopClicked(self):
        root = self.__selectedRoot()
        if root is None:
            return
        self.logic.stopMonitoring(root)
        self.__refreshMonitoredList()

    def __onFolderRegistryChanged(self, _root=None):
        self.__refreshMonitoredList()

    def __selectedRoot(self):
        item = self.monitoredList.currentItem()
        return item.data(qt.Qt.UserRole) if item else None

    def __refreshMonitoredList(self):
        current = self.__selectedRoot()
        self.monitoredList.clear()

        for description, root in self.logic.monitoredFolders():
            item = qt.QListWidgetItem(description)
            item.setData(qt.Qt.UserRole, root)
            self.monitoredList.addItem(item)
            if root == current:
                self.monitoredList.setCurrentItem(item)

        hasFolders = self.monitoredList.count > 0
        self.syncButton.enabled = hasFolders
        self.stopButton.enabled = hasFolders

    def cleanup(self):
        super().cleanup()
        self.playerWidget.clear()
        try:
            self.logic.folderChanged.disconnect()
        except (TypeError, RuntimeError):
            pass


class FolderMonitorLogic(LTracePluginLogic):
    folderChanged = qt.Signal(str)

    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.manager = virtual_folder.manager()
        self.fourd = get_fourd_manager()
        self.monitor = FolderMonitorService.instance()
        self.manager.folderSynced.connect(self.folderChanged)
        self.manager.folderRegistered.connect(self.folderChanged)
        self.manager.folderUnregistered.connect(self.folderChanged)

    # -- inspection -----------------------------------------------------------------------------------
    @staticmethod
    def preview(path, pattern: str = None) -> virtual_folder.ScanResult:
        return virtual_folder.scan(path, pattern=pattern)

    @staticmethod
    def suggestPatterns(path):
        return virtual_folder.suggest_patterns(path)

    @staticmethod
    def describeScan(scan: virtual_folder.ScanResult) -> str:
        parts = [f"{len(scan.items)} dataset{'s' if len(scan.items) != 1 else ''} found"]
        if scan.frames:
            parts.append(f"{len(scan.frames)} numbered entries kept for the sequence")
        if scan.truncated:
            parts.append(f"{scan.truncated} more not listed (use a frame pattern for numbered families)")
        if scan.skipped:
            parts.append(f"{len(scan.skipped)} file{'s' if len(scan.skipped) != 1 else ''} skipped")
        return ", ".join(parts) + "."

    @staticmethod
    def previewSequence(path, pattern: str):
        """``(summary, variables)`` for the frames ``pattern`` matches inside ``path``."""
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError(f"Invalid pattern: {error}")

        dataset = FourDDataset(path, pattern=pattern)
        if not dataset.frame_count:
            raise ValueError(f"Nothing in this folder matches '{pattern}'.")

        info = dataset.describe()
        labels = dataset.labels()
        shape = "×".join(str(size) for size in reversed(info.shape_zyx or ()))
        summary = (
            f"{dataset.frame_count} frames of {shape} {info.dtype}, "
            f"from {labels[0]} to {labels[-1]} — shown as a 1:{dataset.preview_factor()} preview while scrubbing."
        )
        return summary, list(info.variables)

    # -- actions --------------------------------------------------------------------------------------
    def importFolder(self, path, deferred: bool = True, monitored: bool = True, pattern: str = None):
        folder = virtual_folder.VirtualFolder(root=Path(path), deferred=deferred, monitored=monitored, pattern=pattern)
        return self.manager.register(folder)

    def createSequence(self, path, pattern: str, variable: str = None, follow: bool = False):
        """The 4D sequence for ``path``, created on the first call and refreshed on the next ones.

        A 4D node is a view of a folder, not a snapshot of it, so asking for the same folder, pattern and
        variable again returns what is already on screen instead of adding a second node beside it.
        ``follow`` seeds a sequence being created; after that the player's own *Follow latest* owns it.
        """
        path = Path(path)
        variable = variable or None

        existing = self.fourd.find(path, pattern=pattern, variable=variable)
        if existing is not None:
            existing.refreshFrames()
            return existing.node, existing

        return self.fourd.create(path, pattern=pattern, variable=variable, follow=follow)

    def sync(self, root):
        return self.manager.sync(root)

    def stopMonitoring(self, root):
        self.manager.unregister(root)

    def monitoredFolders(self):
        """``(description, root)`` for every registered folder, for display in a list."""
        entries = []
        for folder in self.manager.folders():
            state = "watching" if self.monitor.isWatched(folder.root) else "not watching"
            entries.append((f"{Path(folder.root).name} — {len(folder.nodes)} datasets, {state}", folder.key))

        for node_id, player in self.fourd.players().items():
            node = slicer.mrmlScene.GetNodeByID(node_id)
            name = node.GetName() if node else "4D dataset"
            entries.append(
                (
                    (
                        f"{name} — {player.frameCount} frames, following"
                        if player.follow
                        else f"{name} — {player.frameCount} frames"
                    ),
                    player.dataset.root.as_posix(),
                )
            )

        return entries
