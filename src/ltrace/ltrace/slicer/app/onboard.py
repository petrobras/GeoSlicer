import logging
from dataclasses import dataclass
from pathlib import Path

import qt
import slicer

from ltrace.slicer.module_utils import loadModules
from ltrace.slicer.ui import LineSeparator, LineSeparatorWithText
from ltrace.slicer_utils import getResourcePath
from ltrace.utils.ProgressBarProc import ProgressBarProc
from ltrace.slicer.app import tryDetectProjectDataType


class ui_IntroToolButton(qt.QToolButton):
    def __init__(self, text: str, moduleName: str, icon: str, parent=None) -> None:
        super().__init__(parent)

        self.__updateStyleSheet()
        self.__moduleName = moduleName
        self.objectName = f"{moduleName} Tool Button"
        iconWidget = qt.QIcon(icon.as_posix())
        self.setToolButtonStyle(qt.Qt.ToolButtonTextUnderIcon)
        self.setIcon(iconWidget)
        self.setText(text)
        self.setIconSize(qt.QSize(60, 60))
        self.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)
        #
        # self.clicked.connect(self._action)

    def __updateStyleSheet(self) -> None:
        self.setStyleSheet(
            "QToolButton {\
                background-color: transparent;\
                border: none;\
                padding-top: 8px;\
                padding-bottom: 8px;\
            }\
            QToolButton:hover {\
                background-color: gray;\
                border-radius: 3px;\
            }\
            QToolButton:pressed {\
                background-color: #6B6B6B;\
            }"
        )

    def _action(self):
        try:
            if self.__moduleName is not None:
                slicer.util.selectModule(self.__moduleName)

        except Exception as error:
            logging.debug(f"Error in {self.__moduleName} shortcut: {error}.")


class ui_DataLoaderSelectorDialog(qt.QDialog):
    signalEnvironmentClicked = qt.Signal(object)

    def __init__(self, modules, parent=None) -> None:
        super().__init__(parent)

        self.projectOptionVisible = True

        self.setWindowIcon(qt.QIcon((getResourcePath("Icons") / "GeoSlicer.ico").as_posix()))

        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        self.setMinimumWidth(400)
        self.setWindowTitle("Open Image")

        self.projectOptionFrame = qt.QFrame()
        layoutProjectOption = qt.QVBoxLayout(self.projectOptionFrame)

        openProjectButton = qt.QPushButton("Open .mrml Project")
        openProjectButton.clicked.connect(self.openProject)
        openProjectButton.setSizePolicy(qt.QSizePolicy.MinimumExpanding, qt.QSizePolicy.Fixed)
        openProjectButton.setProperty("class", "actionButtonBackground")

        OrLine = LineSeparatorWithText("Or")

        layoutProjectOption.addWidget(openProjectButton)
        layoutProjectOption.addWidget(OrLine)
        layoutProjectOption.setContentsMargins(0, 0, 0, 0)

        introMsgLabel = qt.QLabel("Choose a data type to start")
        lineFrame = LineSeparator()
        buttonsFrame = qt.QFrame()
        buttonsGridLayout = qt.QGridLayout(buttonsFrame)

        self.helpBoxTextEdit = qt.QTextEdit()
        self.helpBoxTextEdit.setReadOnly(True)
        self.helpBoxTextEdit.setFixedHeight(64)

        for i, module in enumerate(modules):
            button = ui_IntroToolButton(text=module.displayName, moduleName=module.moduleName, icon=module.icon)
            button.installEventFilter(self)
            button.setToolTip(f"Load {module.displayName} data")
            buttonsGridLayout.addWidget(button, i // 3, i % 3)
            button.clicked.connect(lambda _, m=module: self.handleSignalEmit(m))

        layout.addWidget(self.projectOptionFrame)
        layout.addWidget(introMsgLabel)
        layout.addWidget(lineFrame)
        layout.addWidget(buttonsFrame)
        layout.addWidget(self.helpBoxTextEdit)

        self.projectOptionFrame.visible = self.projectOptionVisible

    def handleSignalEmit(self, module):
        self.signalEnvironmentClicked.emit(module)

    def eventFilter(self, obj, event):
        if event.type() == qt.QEvent.Enter:
            self.helpBoxTextEdit.setText(obj.toolTip)
        elif event.type() == qt.QEvent.Leave:
            self.helpBoxTextEdit.clear()
        return False

    def openProject(self):
        selected = slicer.modules.AppContextInstance.projectEventsLogic.loadScene()
        if not selected:
            return

        category = tryDetectProjectDataType()
        if category:
            self.close()
            loaderInfo: LoaderInfo = LOADERS[category]
            self.handleSignalEmit(loaderInfo)
        else:
            self.showOnlyDataTypes()

    def showOnlyDataTypes(self):
        self.projectOptionFrame.visible = False


@dataclass
class LoaderInfo:
    displayName: str
    moduleName: str
    icon: Path
    category: str = None
    environment: str = None


LOADERS = {
    li.displayName: li
    for li in [
        LoaderInfo(
            displayName="Volumes",
            moduleName="MicroCTLoader",
            icon=getResourcePath("Icons") / "MicroCT3D.png",
            category="MicroCT",
            environment="MicroCTEnv",
        ),
        LoaderInfo(
            displayName="Thin Section",
            moduleName="ThinSectionLoader",
            icon=getResourcePath("Icons") / "ThinSection.png",
            category="Thin Section",
            environment="ThinSectionEnv",
        ),
        LoaderInfo(
            displayName="Well Logs",
            moduleName="ImageLogData",
            icon=getResourcePath("Icons") / "ImageLog.png",
            category="ImageLog",
            environment="ImageLogEnv",
        ),
        LoaderInfo(
            displayName="Core",
            moduleName="Multicore",
            icon=getResourcePath("Icons") / "CoreEnv.png",
            category="Core",
            environment="CoreEnv",
        ),
        LoaderInfo(
            displayName="Multiscale",
            moduleName="CustomizedData",
            icon=getResourcePath("Icons") / "MultiscaleIcon.png",
            category="Multiscale",
            environment="MultiscaleEnv",
        ),
        LoaderInfo(
            displayName="NetCDF",
            moduleName="NetCDFLoader",
            icon=getResourcePath("Icons") / "NetCDF.png",
            category="MicroCT",
            environment="MicroCTEnv",
        ),
    ]
}


def loadEnvironment(toolbar, environmentInfo):
    groups = slicer.modules.AppContextInstance.modules.groups
    mainWindow = slicer.modules.AppContextInstance.mainWindow
    with ProgressBarProc() as pb:
        windowModified = slicer.modules.AppContextInstance.mainWindow.isWindowModified()
        related = groups[environmentInfo.category]
        loadModules(related, permanent=False, favorite=False)

        try:
            toolbar.clear()  # clear before add
            module = getattr(slicer.modules, f"{environmentInfo.environment}Instance")
            module.environment.modulesToolbar = toolbar  # APP_TOOLBARS["ModuleToolBar"]
            module.environment.setCategory(environmentInfo.category)
            module.environment.setupEnvironment()
            module.environment.enter()

            # TODO this is ugly, move to class/module
            sval = slicer.app.userSettings().value(f"{slicer.app.applicationName}/LeftDrawerVisible", True)
            if slicer.util.toBool(sval):
                widget = toolbar.widgetForAction(toolbar.actions()[0])
                if widget.toolButtonStyle != qt.Qt.ToolButtonTextBesideIcon:
                    mainToolBar = slicer.util.mainWindow().findChild(qt.QToolBar, "MainToolBar")
                    mainToolBar.actions()[0].trigger()

        except AttributeError as e:
            import traceback

            traceback.print_exc()
            logging.error(f"Error setting up environment {environmentInfo.environment}: {e}")

        slicer.util.selectModule(environmentInfo.moduleName)

        moduleSelectorToolbar = slicer.util.mainWindow().moduleSelector()
        envSelectorButton = moduleSelectorToolbar.findChild(qt.QToolButton, "environment Selector Menu")
        envSelectorButton.setText(environmentInfo.displayName)
        envSelectorButton.setIcon(qt.QIcon(environmentInfo.icon))
        envSelectorButton.setToolButtonStyle(qt.Qt.ToolButtonTextBesideIcon)
        slicer.modules.AppContextInstance.mainWindow.setWindowModified(windowModified)


def loadEnvironmentByName(toolbar, displayName):
    module = LOADERS[displayName]
    loadEnvironment(toolbar, module)


def showDataLoaders(toolbar):
    def threadWrapper(*args):
        loadEnvironment(*args)
        welcomeDialog.signalEnvironmentClicked.disconnect()
        welcomeDialog.close()

    welcomeDialog = ui_DataLoaderSelectorDialog(
        [LOADERS[category] for category in LOADERS],
        parent=slicer.util.mainWindow(),
    )

    welcomeDialog.signalEnvironmentClicked.connect(lambda envInfo: threadWrapper(toolbar, envInfo))

    welcomeDialog.exec_()
