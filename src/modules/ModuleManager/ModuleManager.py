import os
from pathlib import Path

import qt
import slicer

from commons.slicer.custom_modules import logic
from commons.slicer.custom_modules.logic import FolderStatus, ModuleStatus, customModules
from commons.slicer.custom_modules.menu import chooseModuleFolder
from commons.slicer.helpers import BlockSignals, svgToQIcon
from commons.slicer.widget.message_banner import MessageBanner, MessageLevel, levelColor
from commons.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, getResourcePath


try:
    from Test.ModuleManagerTest import ModuleManagerTest
except ImportError:
    ModuleManagerTest = None


class ModuleManager(LTracePlugin):
    SETTING_KEY = "ModuleManager"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Module Manager"
        self.parent.categories = ["Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = f"""
Loads custom modules from folders. A folder can hold a single module or several module folders.
Folders listed in the {logic.ENVIRONMENT_VARIABLE} environment variable are loaded for every user.
"""
        self.setHelpUrl("GettingStarted/ModuleManager.html")
        self.parent.acknowledgementText = """
This file was originally developed by LTrace Geophysics Solutions.
"""


class FolderDropTree(qt.QTreeWidget):
    """Tree that accepts folders dragged from the file browser and emits their local paths.

    It is as tall as its rows, so the buttons below stay close to the list, and scrolls past MAXIMUM_ROWS. The
    module panel sizes modules to their preferred height, so the cap is what keeps a long list from stretching it.
    """

    pathsDropped = qt.Signal(object)

    DRAG_STYLE = "QTreeWidget { border: 2px dashed #26C252; }"
    # Keeps an empty list tall enough to drop a folder on
    MINIMUM_ROWS = 4
    MAXIMUM_ROWS = 15

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Preferred)
        self.itemExpanded.connect(lambda _: self.updateGeometry())
        self.itemCollapsed.connect(lambda _: self.updateGeometry())

    # py_q_* call the QTreeWidget implementations
    def sizeHint(self):
        return qt.QSize(self.py_q_sizeHint().width(), self.__heightFor(self.__visibleRowHeights()))

    def minimumSizeHint(self):
        return qt.QSize(self.py_q_minimumSizeHint().width(), self.__heightFor([]))

    def __heightFor(self, rowHeights):
        rowHeight = rowHeights[0] if rowHeights else self.fontMetrics().height() + 8
        rowHeights = rowHeights[: self.MAXIMUM_ROWS]
        rows = sum(rowHeights) + rowHeight * max(0, self.MINIMUM_ROWS - len(rowHeights))
        header = 0 if self.header().isHidden() else self.header().sizeHint.height()
        scrollBar = self.horizontalScrollBar().sizeHint.height() if self.horizontalScrollBar().isVisible() else 0
        return rows + header + scrollBar + 2 * self.frameWidth

    def __visibleRowHeights(self):
        heights = []
        for index in range(self.topLevelItemCount):
            item = self.topLevelItem(index)
            heights.append(self.visualItemRect(item).height())
            if item.isExpanded():
                heights.extend(self.visualItemRect(item.child(child)).height() for child in range(item.childCount()))
        return [height for height in heights if height > 0]

    def dragEnterEvent(self, event):
        if self.__localPaths(event):
            event.acceptProposedAction()
            self.setStyleSheet(self.DRAG_STYLE)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.__localPaths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")

    def dropEvent(self, event):
        self.setStyleSheet("")
        paths = self.__localPaths(event)
        if not paths:
            event.ignore()
            return

        event.acceptProposedAction()
        self.pathsDropped.emit(paths)

    @staticmethod
    def __localPaths(event):
        mimeData = event.mimeData()
        if not mimeData.hasUrls():
            return []
        return [url.toLocalFile() for url in mimeData.urls() if url.isLocalFile()]


class ModuleManagerWidget(LTracePluginWidget):
    FOLDER_ROLE = qt.Qt.UserRole
    MODULE_ROLE = qt.Qt.UserRole + 1

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = ModuleManagerLogic()

        self.layout.setSpacing(12)

        infoLabel = qt.QLabel(
            "GeoSlicer loads custom modules from the folders below. "
            "A folder can hold a single module or several module folders. "
            "Drop a folder on the list below to add it."
        )
        infoLabel.setWordWrap(True)
        self.layout.addWidget(infoLabel)

        foldersLabel = qt.QLabel("Module folders")
        font = foldersLabel.font
        font.setBold(True)
        foldersLabel.setFont(font)

        self.rescanButton = qt.QToolButton()
        self.rescanButton.objectName = "Rescan Button"
        self.rescanButton.setIcon(self.__icon("Refresh"))
        self.rescanButton.setAutoRaise(True)
        self.rescanButton.toolTip = "Rescan the folders for new modules"
        self.rescanButton.clicked.connect(self.refresh)

        foldersHeaderLayout = qt.QHBoxLayout()
        foldersHeaderLayout.setContentsMargins(0, 0, 0, 0)
        foldersHeaderLayout.addWidget(foldersLabel)
        foldersHeaderLayout.addStretch(1)
        foldersHeaderLayout.addWidget(self.rescanButton)

        self.banner = MessageBanner()

        self.tree = FolderDropTree()
        self.tree.objectName = "Module Folders Tree"
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Folder / Module", "Status"])
        self.tree.header().setSectionResizeMode(0, qt.QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, qt.QHeaderView.ResizeToContents)
        self.tree.header().setStretchLastSection(False)
        self.tree.setSelectionMode(qt.QAbstractItemView.SingleSelection)
        # Keep the folder name visible on long paths
        self.tree.setTextElideMode(qt.Qt.ElideMiddle)
        self.tree.itemSelectionChanged.connect(self.__onSelectionChanged)
        self.tree.itemDoubleClicked.connect(self.__onItemDoubleClicked)
        self.tree.itemChanged.connect(self.__onItemChanged)
        self.tree.pathsDropped.connect(self.addDroppedPaths)

        # Rebuilding the tree deletes the toggled item, so the toggle is applied once its signal returns
        self.__pendingToggle = None
        self.__toggleTimer = qt.QTimer(self.parent)
        self.__toggleTimer.setSingleShot(True)
        self.__toggleTimer.setInterval(0)
        self.__toggleTimer.timeout.connect(self.__applyPendingToggle)

        foldersLayout = qt.QVBoxLayout()
        foldersLayout.setSpacing(4)
        foldersLayout.addLayout(foldersHeaderLayout)
        foldersLayout.addWidget(self.banner)
        foldersLayout.addWidget(self.tree)
        foldersLayout.addWidget(self.__createErrorPanel())
        self.layout.addLayout(foldersLayout)

        self.addFolderButton = qt.QPushButton("Add folder...")
        self.addFolderButton.objectName = "Add Folder Button"
        self.addFolderButton.setIcon(self.__icon("FolderPlus"))
        self.addFolderButton.setProperty("class", "actionButtonBackground")
        self.addFolderButton.toolTip = "Add a module folder, or a folder containing several module folders."
        self.addFolderButton.clicked.connect(self.__onAddFolderClicked)

        self.removeFolderButton = qt.QPushButton("Remove")
        self.removeFolderButton.objectName = "Remove Folder Button"
        self.removeFolderButton.setIcon(self.__icon("Trash"))
        self.removeFolderButton.toolTip = "Stop loading modules from the selected folder. Takes effect after restart."
        self.removeFolderButton.clicked.connect(self.__onRemoveFolderClicked)

        self.showInFilesButton = qt.QPushButton("Show in files")
        self.showInFilesButton.objectName = "Show In Files Button"
        self.showInFilesButton.setIcon(self.__icon("FolderOpen"))
        self.showInFilesButton.toolTip = "Show the selected folder in the file browser."
        self.showInFilesButton.clicked.connect(self.__onShowInFilesClicked)

        self.buttonsLayout = buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.setSpacing(6)
        buttonsLayout.addWidget(self.addFolderButton)
        buttonsLayout.addWidget(self.removeFolderButton)
        buttonsLayout.addWidget(self.showInFilesButton)
        self.layout.addLayout(buttonsLayout)
        self.layout.addStretch(1)

        self.__populateTree(customModules().folders)

        # Modules that failed while GeoSlicer started are only reported here
        broken = [module for module in customModules().modules() if module.hasError]
        if broken:
            self.__setStatus(
                f"{self.__count(broken)} could not be loaded. Select them in the list to see why.",
                MessageLevel.WARNING,
            )

    def __createErrorPanel(self):
        self.errorPanel = qt.QWidget()
        self.errorPanel.objectName = "Module Error Panel"

        self.errorTitle = qt.QLabel()
        self.errorTitle.objectName = "Module Error Title"
        self.errorTitle.setWordWrap(True)
        self.errorTitle.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
        font = self.errorTitle.font
        font.setBold(True)
        self.errorTitle.setFont(font)

        self.errorDetails = qt.QPlainTextEdit()
        self.errorDetails.objectName = "Module Error Details"
        self.errorDetails.setReadOnly(True)
        self.errorDetails.setLineWrapMode(qt.QPlainTextEdit.NoWrap)
        # QFontDatabase.FixedFont resolves to a proportional font on Windows. The style hint picks the fallback
        tracebackFont = qt.QFont("Consolas")
        tracebackFont.setStyleHint(qt.QFont.TypeWriter)
        self.errorDetails.setFont(tracebackFont)
        self.errorDetails.setMaximumHeight(160)

        self.errorHint = qt.QLabel()
        self.errorHint.objectName = "Module Error Hint"
        self.errorHint.setWordWrap(True)

        layout = qt.QVBoxLayout(self.errorPanel)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.errorTitle)
        layout.addWidget(self.errorDetails)
        layout.addWidget(self.errorHint)
        self.errorPanel.visible = False
        return self.errorPanel

    def enter(self) -> None:
        super().enter()
        self.__fitButtons()
        self.__populateTree(customModules().folders)

    def __fitButtons(self) -> None:
        """Widen this module's panel to fit the buttons, which don't shrink. Measured once the widget is shown,
        with its final font and style. The panel scrolls sideways when narrower, so other modules are unaffected."""
        buttons = (self.addFolderButton, self.removeFolderButton, self.showInFilesButton)
        margins = self.layout.contentsMargins()
        width = sum(button.sizeHint.width() for button in buttons) + self.buttonsLayout.spacing * 2
        self.setModuleMinimumWidth(max(self.DEFAULT_MINIMUM_WIDTH, width + margins.left() + margins.right()))

    def refresh(self) -> None:
        # Waits up to a couple of seconds for unreachable network folders
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            self.__populateTree(self.logic.refresh())
        finally:
            qt.QApplication.restoreOverrideCursor()

    def addFolder(self, path: str):
        """Register a folder, load its modules and report the result. Returns the new ModuleFolder, or None."""
        added, folder, replaced = self.logic.addFolder(path)
        self.__populateTree(customModules().folders)

        if not added and (folder is None or self.__isSamePath(folder.path, path)):
            self.__setStatus(f"{path} is already registered.", MessageLevel.INFO)
        elif not added:
            modules = [module for module in folder.modules if self.__isInside(module.info.path, path)]
            if len(modules) == 1:
                verb = "loaded from" if modules[0].status == ModuleStatus.LOADED else "listed under"
                text = f"{self.__moduleTitle(modules[0])} is already {verb} {folder.path}."
            else:
                text = f"The modules in {path} are already listed under {folder.path}."
            self.__setStatus(text, MessageLevel.INFO)
            if modules:
                self.__selectModule(modules[0])
        elif folder is not None and folder.status in (FolderStatus.MISSING, FolderStatus.UNREACHABLE):
            self.__setStatus(
                f"Added {path}, but it can't be read right now ({folder.status.value}). "
                "Click the rescan button to try again.",
                MessageLevel.WARNING,
            )
        elif folder is not None and folder.status == FolderStatus.EMPTY and any(Path(path).glob("*.zip")):
            self.__setStatus(
                f"No modules were found in {path}, but it contains zip files. Extract the zip first, "
                "then add the extracted folder.",
                MessageLevel.WARNING,
            )
        elif folder is None or folder.status == FolderStatus.EMPTY:
            self.__setStatus(
                f"No modules were found in {path}. A module is a Python file that defines a class with the same "
                "name as the file, derived from LTracePlugin, and sets self.parent.categories.",
                MessageLevel.WARNING,
            )
        else:
            loaded = [module for module in folder.modules if module.status == ModuleStatus.LOADED]
            self.__setStatus(
                f"Loaded {len(loaded)} of {len(folder.modules)} module(s) from {path}. "
                + self.__resultHint(folder.modules, replaced),
                MessageLevel.SUCCESS if len(loaded) == len(folder.modules) else MessageLevel.WARNING,
            )
            self.__selectFirstError(folder.modules)

        return folder if added else None

    def addDroppedPaths(self, paths) -> None:
        """Add the folders dropped on the folder list. A dropped module file adds its folder."""
        folders, ignored = logic.droppedFolders(paths)
        if len(folders) == 1 and not ignored:
            self.addFolder(folders[0])
            return

        added = []
        replaced = []
        for path in folders:
            wasAdded, folder, replacedFolders = self.logic.addFolder(path)
            if wasAdded:
                added.append(folder)
                replaced.extend(replacedFolders)
        self.__populateTree(customModules().folders)

        messages = []
        level = MessageLevel.INFO
        if added:
            modules = [module for folder in added if folder is not None for module in folder.modules]
            loaded = [module for module in modules if module.status == ModuleStatus.LOADED]
            level = MessageLevel.SUCCESS if modules and len(loaded) == len(modules) else MessageLevel.WARNING
            messages.append(
                f"Added {len(added)} folder(s) and loaded {len(loaded)} of {len(modules)} module(s). "
                + self.__resultHint(modules, replaced)
            )
            self.__selectFirstError(modules)
        if len(added) < len(folders):
            messages.append(f"{len(folders) - len(added)} folder(s) were already listed.")
        if ignored:
            names = ", ".join(Path(path).name for path in ignored)
            messages.append(f"Ignored {names}: drop module folders or module .py files.")
            level = MessageLevel.WARNING
        self.__setStatus(" ".join(messages), level)

    def setModuleEnabled(self, module, enabled: bool) -> None:
        """Enable or disable a module. Enabling loads it right away; a loaded module stays loaded until restart."""
        module = self.logic.setModuleEnabled(module.info.path, enabled)
        self.__populateTree(customModules().folders)
        if module is None:
            return

        title = self.__moduleTitle(module)
        if enabled and module.status == ModuleStatus.LOADED:
            self.__setStatus(f"Enabled {title}.", MessageLevel.SUCCESS)
        elif enabled and module.status == ModuleStatus.FAILED:
            self.__setStatus(f"{title} failed to load again and was disabled: {module.message}", MessageLevel.ERROR)
            self.__selectFirstError([module])
        elif enabled and module.status == ModuleStatus.INVALID:
            self.__setStatus(f"Enabled {title}, but it can't be loaded: {module.message}", MessageLevel.WARNING)
            self.__selectFirstError([module])
        elif enabled:
            self.__setStatus(f"Enabled {title}, but it was not loaded. {module.message}.", MessageLevel.WARNING)
        elif module.status == ModuleStatus.LOADED:
            self.__setStatus(f"Disabled {title}. It stays loaded until GeoSlicer is restarted.", MessageLevel.SUCCESS)
        else:
            self.__setStatus(f"Disabled {title}.", MessageLevel.SUCCESS)

    def __onItemChanged(self, item, column) -> None:
        module = self.__moduleForItem(item)
        if column != 0 or module is None:
            return

        enabled = item.checkState(0) == qt.Qt.Checked
        if enabled != module.enabled:
            self.__pendingToggle = (module, enabled)
            self.__toggleTimer.start()

    def __applyPendingToggle(self) -> None:
        if self.__pendingToggle is not None:
            module, enabled = self.__pendingToggle
            self.__pendingToggle = None
            self.setModuleEnabled(module, enabled)

    def __onAddFolderClicked(self) -> None:
        path = chooseModuleFolder(self.parent)
        if path:
            self.addFolder(path)

    def __onRemoveFolderClicked(self) -> None:
        folder = self.__selectedFolder()
        if folder is None or not folder.isRemovable:
            return

        self.logic.removeFolder(folder.path)
        self.__populateTree(customModules().folders)
        self.__setStatus(
            f"Removed {folder.path}. Its modules stay loaded until GeoSlicer is restarted."
            if folder.modules
            else f"Removed {folder.path}.",
            MessageLevel.SUCCESS,
        )

    def __onShowInFilesClicked(self) -> None:
        path = self.__selectedPath()
        if path and os.path.isdir(path):
            qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(path))

    def __onItemDoubleClicked(self, item, column) -> None:
        module = self.__selectedModule()
        if module is not None and module.isMenuEntry:
            slicer.util.selectModule(module.info.key)

    def __populateTree(self, folders) -> None:
        selectedModule = self.__selectedModule()
        selectedFolder = self.__selectedFolder()
        # Setting the check states below must not count as the user toggling modules
        with BlockSignals(self.tree):
            self.__buildTree(folders)
            # Keeps the selection, such as a module selected to show its error, when the tree is rebuilt on enter
            if selectedModule is not None:
                self.__selectModule(selectedModule)
            elif selectedFolder is not None:
                self.__selectFolder(selectedFolder)
        self.__onSelectionChanged()

    def __onSelectionChanged(self) -> None:
        self.__updateButtons()
        self.__updateErrorPanel()

    def __updateErrorPanel(self) -> None:
        module = self.__selectedModule()
        if module is None or not module.hasError:
            self.errorPanel.visible = False
            return

        self.errorTitle.text = f"{module.info.key}: {module.message}"
        self.errorDetails.setPlainText(module.details)
        self.errorDetails.visible = bool(module.details)
        if module.status == ModuleStatus.FAILED:
            self.errorHint.text = "The module was disabled. Fix the error, then check the module to load it again."
        else:
            self.errorHint.text = "Fix the file, then click the rescan button to load it."
        self.errorPanel.visible = True

    def __selectFirstError(self, modules) -> None:
        """Select the first module with an error, so its error is shown below the list."""
        broken = next((module for module in modules if module.hasError), None)
        if broken is not None:
            self.__selectModule(broken)

    def __selectModule(self, target) -> None:
        for folderIndex, folder in self.__folders.items():
            for moduleIndex, module in enumerate(folder.modules):
                if self.__isSamePath(module.info.path, target.info.path):
                    self.tree.setCurrentItem(self.tree.topLevelItem(folderIndex).child(moduleIndex))
                    return

    def __selectFolder(self, target) -> None:
        for folderIndex, folder in self.__folders.items():
            if self.__isSamePath(folder.path, target.path):
                self.tree.setCurrentItem(self.tree.topLevelItem(folderIndex))
                return

    def __buildTree(self, folders) -> None:
        self.tree.clear()
        self.__folders = {}
        self.__errorIcon = svgToQIcon(
            getResourcePath("Icons") / "svg" / "TriangleAlert.svg", color=levelColor(MessageLevel.WARNING)
        )

        for index, folder in enumerate(folders):
            folderItem = qt.QTreeWidgetItem([folder.path, self.__folderStatusText(folder)])
            folderItem.setData(0, self.FOLDER_ROLE, index)
            self.__folders[index] = folder
            if not folder.isRemovable:
                folderItem.setToolTip(
                    0,
                    f"Set by the {logic.ENVIRONMENT_VARIABLE} environment variable. It can't be removed here.",
                )
                font = folderItem.font(0)
                font.setItalic(True)
                folderItem.setFont(0, font)
            else:
                folderItem.setToolTip(0, folder.path)

            for moduleIndex, module in enumerate(folder.modules):
                moduleItem = qt.QTreeWidgetItem([self.__moduleTitle(module), self.__moduleStatusText(module)])
                moduleItem.setData(0, self.FOLDER_ROLE, index)
                moduleItem.setData(0, self.MODULE_ROLE, moduleIndex)
                moduleItem.setFlags(moduleItem.flags() | qt.Qt.ItemIsUserCheckable)
                moduleItem.setCheckState(0, qt.Qt.Checked if module.enabled else qt.Qt.Unchecked)
                moduleItem.setToolTip(0, module.info.path)
                if module.message:
                    moduleItem.setToolTip(1, module.message)
                if module.hasError:
                    moduleItem.setIcon(1, self.__errorIcon)
                folderItem.addChild(moduleItem)

            self.tree.addTopLevelItem(folderItem)
            folderItem.setExpanded(True)

        if not folders:
            placeholder = qt.QTreeWidgetItem(["No module folders yet. Add or drop one here."])
            placeholder.setFlags(qt.Qt.NoItemFlags)
            self.tree.addTopLevelItem(placeholder)
            placeholder.setFirstColumnSpanned(True)

        self.tree.updateGeometry()

    def __updateButtons(self) -> None:
        folder = self.__selectedFolder()
        module = self.__selectedModule()
        self.removeFolderButton.enabled = folder is not None and module is None and folder.isRemovable
        self.showInFilesButton.enabled = folder is not None and folder.status in (FolderStatus.OK, FolderStatus.EMPTY)

    def __selectedItem(self):
        items = self.tree.selectedItems()
        return items[0] if items else None

    def __selectedFolder(self):
        item = self.__selectedItem()
        if item is None:
            return None
        index = item.data(0, self.FOLDER_ROLE)
        return self.__folders.get(index) if index is not None else None

    def __selectedModule(self):
        item = self.__selectedItem()
        return self.__moduleForItem(item) if item is not None else None

    def __moduleForItem(self, item):
        folder = self.__folders.get(item.data(0, self.FOLDER_ROLE))
        moduleIndex = item.data(0, self.MODULE_ROLE)
        if folder is None or moduleIndex is None:
            return None
        return folder.modules[moduleIndex]

    def __selectedPath(self):
        module = self.__selectedModule()
        if module is not None:
            return module.info.searchPath
        folder = self.__selectedFolder()
        return folder.path if folder is not None else None

    def __setStatus(self, text: str, level: MessageLevel) -> None:
        self.banner.showMessage(text, level)

    @staticmethod
    def __icon(name: str):
        return svgToQIcon(getResourcePath("Icons") / "svg" / f"{name}.svg")

    @staticmethod
    def __folderStatusText(folder) -> str:
        if folder.status != FolderStatus.OK:
            return folder.status.value
        count = len(folder.modules)
        return f"{count} module" if count == 1 else f"{count} modules"

    @staticmethod
    def __moduleStatusText(module) -> str:
        return ModuleStatus.DISABLED.value if not module.enabled and not module.hasError else module.status.value

    @staticmethod
    def __count(modules) -> str:
        return "1 module" if len(modules) == 1 else f"{len(modules)} modules"

    @staticmethod
    def __isSamePath(path, other) -> bool:
        return logic.normalizePath(path) == logic.normalizePath(other)

    @staticmethod
    def __isInside(path, folder) -> bool:
        return Path(logic.normalizePath(path)).is_relative_to(logic.normalizePath(folder))

    def __resultHint(self, modules, replaced=()) -> str:
        hints = []
        if any(module.status == ModuleStatus.LOADED for module in modules):
            hints.append("Find them under My Modules in the module toolbar.")
        broken = [module for module in modules if module.hasError]
        if broken:
            hints.append(f"{self.__count(broken)} could not be loaded: select them in the list to see why.")
        if replaced:
            its = "its" if len(replaced) == 1 else "their"
            hints.append(f"Removed {', '.join(replaced)} from the list, as the new folder includes {its} modules.")
        return " ".join(hints)

    @staticmethod
    def __moduleTitle(module) -> str:
        slicerModule = getattr(slicer.modules, module.info.key.lower(), None)
        title = getattr(slicerModule, "title", None) if module.status == ModuleStatus.LOADED else None
        return title or module.info.key


class ModuleManagerLogic(LTracePluginLogic):
    def refresh(self):
        return customModules().refresh()

    def addFolder(self, path: str):
        """Register a folder and load its modules, keeping each module file listed under a single folder.

        Returns (added, folder, replaced). folder is the registered ModuleFolder, or None. A folder whose modules are
        all listed under a registered folder, such as a module inside a registered collection, is not added: folder
        is then the one that lists them. replaced holds the paths of the registered folders the new one lists every
        module of, which are removed.
        """
        logic.setLastAddedFolder(path)
        modulePaths = self.__modulePaths(path)
        listedIn = {
            logic.normalizePath(module.info.path): folder
            for folder in customModules().folders
            for module in folder.modules
        }
        # A folder inside the new one is replaced instead, even if it lists every module of the new one
        listing = [listedIn.get(modulePath) for modulePath in modulePaths]
        if listing and all(folder is not None and not self.__isSubfolder(folder.path, path) for folder in listing):
            return False, listing[0], []

        added = logic.addUserPath(path)
        replaced = []
        if added:
            for folder in customModules().folders:
                folderPaths = {logic.normalizePath(module.info.path) for module in folder.modules}
                if folder.isRemovable and folderPaths and folderPaths.issubset(modulePaths):
                    logic.removeUserPath(folder.path)
                    replaced.append(folder.path)

        folders = customModules().refresh()
        target = logic.normalizePath(path)
        folder = next((f for f in folders if logic.normalizePath(f.path) == target), None)
        return added, folder, replaced

    @staticmethod
    def __isSubfolder(path: str, folder: str) -> bool:
        path, folder = logic.normalizePath(path), logic.normalizePath(folder)
        return path != folder and Path(path).is_relative_to(folder)

    @staticmethod
    def __modulePaths(path: str) -> list:
        """Normalized file paths of the modules in a folder, including those that can't be loaded."""
        # An unreachable network folder would block the scan
        if not logic.probeFolders([path])[path]:
            return []
        infos, problems = logic.findFolderModules(path)
        return [logic.normalizePath(info.path) for info in infos + [problem[0] for problem in problems]]

    def setModuleEnabled(self, modulePath: str, enabled: bool):
        """Persist the choice and rescan, which loads a newly enabled module. Returns the module's new state."""
        logic.setModuleEnabled(modulePath, enabled)
        customModules().refresh()
        target = logic.normalizePath(modulePath)
        return next((m for m in customModules().modules() if logic.normalizePath(m.info.path) == target), None)

    def removeFolder(self, path: str) -> bool:
        removed = logic.removeUserPath(path)
        customModules().refresh()
        return removed
