import argparse
import logging
import os
import shutil
from string import Template
from functools import partial
from pathlib import Path
from types import MethodType

import ctk
import qt
import slicer
import slicer.util
import traceback

from commons.slicer.about.about_dialog import AboutDialog
from commons.slicer.ai_models.widget import AIModelsPathDialog, AIModelsPathModel
from commons.slicer.app import getApplicationVersion, updateWindowTitle, getJsonData, MANUAL_BASE_URL
from commons.slicer.app.custom_3dview import customize_3d_view as customize3DView
from commons.slicer.app.custom_colormaps import customize_color_maps as customizeColorMaps
from commons.slicer.app.onboard import LOADERS, loadEnvironment
from commons.slicer.app.onboard_view import showOnboardView
from commons.slicer.application_observables import ApplicationObservables
from commons.slicer.bug_report import BugReportDialog
from commons.slicer.custom_export_to_file import customizeExportToFile
from commons.slicer.custom_modules.logic import customModules, recoverFromCrash
from commons.slicer.custom_modules.menu import showCrashRecoveryMessage
from commons.slicer.module_info import ModuleInfo
from commons.slicer.widget.custom_toolbar_buttons import setToolbarNamesVisible, toolbarNamesVisible
from commons.slicer.widget.global_progress_bar import GlobalProgressBar
from commons.slicer.widget.memory_usage import MemoryUsageWidget
from commons.slicer.widget.module_header import ModuleHeader
from commons.slicer_utils import slicer_is_in_developer_mode, getResourcePath
from commons.slicer import helpers
from commons.utils.custom_event_filter import CustomEventFilter

DEBUG = False

if DEBUG:
    import sys
    import faulthandler

    # Pass the true, unredirected stderr so faulthandler has a real OS file descriptor
    if hasattr(sys, "__stderr__") and sys.__stderr__ is not None:
        faulthandler.enable(file=sys.__stderr__)
    import gc

    gc.set_debug(gc.DEBUG_STATS | gc.DEBUG_COLLECTABLE)


# This import is necessary to make the custom keyring available in the keyring module

# This line solve some problems with Geoslicer Restart when mmengine in installed
# because of a dependence on opencv, instead of opencv-headless, currently used in
# geoslicer. The problem and some solutions are described in this
# post: https://forum.qt.io/post/617768
os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
os.environ["TESSDATA_PREFIX"] = Path(f"{slicer.app.slicerHome}/bin/Tesseract-OCR/tessdata/").as_posix()
os.environ["PYQTGRAPH_QT_LIB"] = "PySide2"

RUN_MODE = os.environ.get("GEOSLICER_RUN_MODE", "development")
APP_NAME = slicer.app.applicationName
# slicerHome ends in "bin/..", which would otherwise carry into module paths and break comparisons with resolved paths
APP_HOME = Path(os.path.normpath(slicer.app.slicerHome))
RESOURCES_PATH = APP_HOME / "LTrace" / "Resources"
ICON_DIR = RESOURCES_PATH / "Icons"
APP_TOOLBARS = {toolbar.name: toolbar for toolbar in slicer.util.mainWindow().findChildren("QToolBar")}

toBool = slicer.util.toBool


def getAppContext():
    if not hasattr(slicer.modules, "AppContextInstance"):
        return None

    return slicer.modules.AppContextInstance


# {
#     "MainToolBar": QToolBar(0x1A0040D6EC0, name="MainToolBar"),
#     "ModuleSelectorToolBar": qSlicerModuleSelectorToolBar(0x1A0040DAB00, name="ModuleSelectorToolBar"),
#     "ModuleToolBar": QToolBar(0x1A0040D7000, name="ModuleToolBar"),
#     "ViewToolBar": QToolBar(0x1A0040D6A00, name="ViewToolBar"),
#     "MouseModeToolBar": qSlicerMouseModeToolBar(0x1A0040D6BC0, name="MouseModeToolBar"),
#     "CaptureToolBar": qMRMLCaptureToolBar(0x1A00415A4B0, name="CaptureToolBar"),
#     "ViewersToolBar": qSlicerViewersToolBar(0x1A0040D82C0, name="ViewersToolBar"),
#     "DialogToolBar": QToolBar(0x1A0040D93C0, name="DialogToolBar"),
#     "MarkupsToolBar": qMRMLMarkupsToolBar(0x1A000D6F3F0, name="MarkupsToolBar"),
#     "SequenceBrowserToolBar": qMRMLSequenceBrowserToolBar(0x1A003DB7870, name="SequenceBrowserToolBar"),
#     "": QToolBar(0x1A01F1DA6F0),
# }

# __indicator = ModuleIndicator(APP_TOOLBARS["ModuleSelectorToolBar"])


def trySelectModule(clicked, moduleName=None):
    try:
        if not moduleName:
            return

        slicer.util.selectModule(moduleName)
    except Exception as e:
        logging.error(f"Error selecting module {moduleName}: {e}")


def toggleMenuBar():
    # Toggle the visibility of the menu bar
    menubar = slicer.util.mainWindow().menuBar()
    menubar.setVisible(not menubar.isVisible())


def modelsPathDialog():
    dialog = AIModelsPathDialog(slicer.util.mainWindow())
    dialog.exec_()


def ltraceBugReport():
    dialog = BugReportDialog(slicer.util.mainWindow())
    dialog.exec_()


class ExpandToolbarActionNames:
    def __init__(self):
        self.__closeIcon = qt.QIcon((ICON_DIR / "svg" / "PanelLeftClose.svg").as_posix())
        self.__openIcon = qt.QIcon((ICON_DIR / "svg" / "PanelLeftOpen.svg").as_posix())

    def __call__(self, *args, **kwargs):
        modulebar = APP_TOOLBARS["ModuleToolBar"]
        if not modulebar.actions():
            logging.warning("No action found")
            showOnboardView(modulebar)
            return

        visible = not toolbarNamesVisible(modulebar)
        setToolbarNamesVisible(modulebar, visible)

        expander = APP_TOOLBARS["MainToolBar"].actions()[0]
        if visible:
            expander.setIcon(self.__closeIcon)
            expander.setToolTip("Collapse Menu")
            slicer.app.userSettings().setValue(f"{slicer.app.applicationName}/LeftDrawerVisible", True)
        else:
            expander.setIcon(self.__openIcon)
            expander.setToolTip("Expand Menu")
            slicer.app.userSettings().setValue(f"{slicer.app.applicationName}/LeftDrawerVisible", False)


def ui_Spacer(layoutType):
    spacer = qt.QWidget()
    spacer.setSizePolicy(qt.QSizePolicy.MinimumExpanding, qt.QSizePolicy.Expanding)
    layout = layoutType(spacer)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addStretch(1)
    return spacer


def installFonts():
    fontId = qt.QFontDatabase().addApplicationFont(
        APP_HOME / "LTrace" / "Resources" / "Fonts" / "Inter_18pt-SemiBold.ttf"
    )
    _fontstr = qt.QFontDatabase().applicationFontFamilies(fontId)[0]
    _font = qt.QFont(_fontstr, 9)
    slicer.app.setFont(_font)
    slicer.app.pythonConsole().setFont(_font)
    # userSettings.setValue("General/font", _font)
    # userSettings.setValue("Python/Font", _font)


def setDataProbeCollapsibleButton():
    dataProbeWidget = slicer.util.mainWindow().findChild(ctk.ctkCollapsibleButton, "DataProbeCollapsibleWidget")
    dataProbeWidget.collapsed = True
    dataProbeWidget.minimumWidth = 450


def setCustomDataProbeInfo():
    infoWidget = slicer.modules.DataProbeInstance.infoWidget

    def customized_describe_pixel(self, ijk, slicerLayerLogic):
        """
        Does not show pixel name if it is either 'invalid' or '(none)'. In
        such cases, show rest of the description (i.e., pixel value).
        """
        volumeNode = slicerLayerLogic.GetVolumeNode()
        if not volumeNode:
            return ""
        description = self.getPixelString(volumeNode, ijk)
        if description.startswith("invalid "):
            description = description[8:]
        elif description.startswith("(none) "):
            description = description[7:]
        return f"<b>{description}</b>"

    infoWidget.generateIJKPixelValueDescription = MethodType(customized_describe_pixel, infoWidget)


# enable/disable volume interpolation
def setVolumeInterpolation(v):
    def setInterpolationAll(v):
        for node in slicer.util.getNodes("*").values():
            if node.IsA("vtkMRMLScalarVolumeDisplayNode"):
                node.SetInterpolate(v)

    def interpolator(caller, event):
        setInterpolationAll(v)

    # set value for all current nodes:
    setInterpolationAll(v)
    # observe new volumes
    slicer.mrmlScene.AddObserver(slicer.mrmlScene.NodeAddedEvent, interpolator)


def setModuleSelectorToolBar():
    toolbar = slicer.util.mainWindow().moduleSelector()
    actions = toolbar.actions()
    actions[0].setVisible(False)
    actions[1].setVisible(False)
    actions[2].setVisible(False)
    actions[3].setVisible(False)

    try:
        spacer = ui_Spacer(layoutType=qt.QHBoxLayout)
        toolbar.addWidget(spacer)

        expandRightFunc = getAppContext().rightDrawer
        action = qt.QAction(expandRightFunc.closeIcon, "", toolbar)
        action.setToolTip("Expand Data")
        expandRightFunc.setAction(action)
        action.triggered.connect(expandRightFunc)
        toolbar.addAction(action)

        openDrawer = toBool(slicer.app.userSettings().value(f"{APP_NAME}/RighDrawerVisible", True))

        if openDrawer:
            expandRightFunc.show()
        else:
            expandRightFunc.hide()

        toolbar.setVisible(True)
    except Exception:
        traceback.print_exc()

    addEnvSelectorMenu()


def addEnvSelectorMenu():
    envButton = qt.QToolButton(APP_TOOLBARS["ModuleSelectorToolBar"])
    envButton.setText("Choose an environment")
    envButton.setToolTip("Change current environment")
    envButton.objectName = "environment Selector Menu"

    menu = qt.QMenu(envButton)

    for env, info in LOADERS.items():
        icon = qt.QIcon(info.icon)

        actione = qt.QAction(icon, env, APP_TOOLBARS["ModuleSelectorToolBar"])
        actione.triggered.connect(lambda _, info=info: loadEnvironment(APP_TOOLBARS["ModuleToolBar"], info))

        menu.addAction(actione)

    envButton.setMenu(menu)
    envButton.setPopupMode(qt.QToolButton.MenuButtonPopup)
    envButton.clicked.connect(lambda: envButton.showMenu())

    toolButtonAction = qt.QWidgetAction(APP_TOOLBARS["ModuleSelectorToolBar"])
    toolButtonAction.setDefaultWidget(envButton)

    beforeAction = APP_TOOLBARS["ModuleSelectorToolBar"].actions()[6]

    APP_TOOLBARS["ModuleSelectorToolBar"].insertAction(beforeAction, toolButtonAction)


def setModulesToolBar():
    toolbarArea = qt.Qt.LeftToolBarArea

    APP_TOOLBARS["ModuleToolBar"].clear()

    setToolbars(
        [
            APP_TOOLBARS["ModuleToolBar"],
        ],
        toolbarArea,
        qt.Qt.Vertical,
    )


def setMainToolBar():
    APP_TOOLBARS["MainToolBar"].clear()

    handler = ExpandToolbarActionNames()

    APP_TOOLBARS["MainToolBar"].addAction(
        qt.QIcon((ICON_DIR / "svg" / "PanelLeftOpen.svg").as_posix()), "Expand Menu", handler
    )

    APP_TOOLBARS["MainToolBar"].setVisible(True)


def setDialogToolBar():
    # os must be imported locally
    # qSlicerCorePythonManager::appendPythonPath runs `del os, sys`
    import os

    toolbarArea = qt.Qt.RightToolBarArea
    verticalToolBars = [
        "DialogToolBar",
    ]

    dialogToolBar = APP_TOOLBARS["DialogToolBar"]

    dialogToolBar.addAction(
        qt.QIcon((ICON_DIR / "svg" / "Bug.svg").as_posix()),
        "Bug Report",
        ltraceBugReport,
    )

    dialogToolBar.addAction(
        qt.QIcon((ICON_DIR / "svg" / "CloudJobs.svg").as_posix()),
        "Task Monitor",
        lambda clicked: getAppContext().rightDrawer.show(1),
    )

    dialogToolBar.addAction(
        qt.QIcon((ICON_DIR / "svg" / "Apps.svg").as_posix()),
        "Getting Started",
        lambda: showOnboardView(APP_TOOLBARS["ModuleToolBar"]),
    )

    dialogToolBar.addAction(
        qt.QIcon((ICON_DIR / "svg" / "Extensions.svg").as_posix()),
        "Module Manager",
        lambda: slicer.util.mainWindow().moduleSelector().selectModule("ModuleManager"),
    )

    dialogToolBar.addAction(
        qt.QIcon((ICON_DIR / "svg" / "Account.svg").as_posix()),
        "Accounts",
        partial(slicer.modules.RemoteServiceInstance.cli.initiateConnectionDialog, keepDialogOpen=True),
    )

    envModelDir = os.getenv("GEOSLICER_MODELS_DIR")
    if envModelDir is None:
        # Model directories are not configured by the environment
        # Allow user to edit model directories
        dialogToolBar.addAction(
            qt.QIcon((ICON_DIR / "svg" / "FolderPlus.svg").as_posix()),
            "Models Path",
            modelsPathDialog,
        )
    else:
        # Model directories are configured by the environment (i.e. Geoslicer Remote)
        model = AIModelsPathModel()

        # Clear first in case directory changes in the future
        model.clear()
        model.addPath(envModelDir)

    # dialogToolBar.addAction(
    #     qt.QIcon((ICON_DIR / "svg" / "Settings.svg").as_posix()),
    #     "Settings",
    #     lambda: None,
    # )

    setToolbars([APP_TOOLBARS[tb] for tb in verticalToolBars], toolbarArea, qt.Qt.Vertical)

    def findConsoleAction():
        for action in dialogToolBar.actions():
            if action.text == "&Python Console":
                return action
        return None

    action = findConsoleAction()
    if action:
        action.setIcon(helpers.svgToQIcon(ICON_DIR / "svg" / "Console.svg"))
        spacer = ui_Spacer(layoutType=qt.QVBoxLayout)
        spacer.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Expanding)
        dialogToolBar.insertWidget(action, spacer)


def setMarkupToolBar():
    toolbar = APP_TOOLBARS["MarkupsToolBar"]
    spacer = ui_Spacer(layoutType=qt.QHBoxLayout)
    firstAction = toolbar.actions()[0]
    toolbar.insertWidget(firstAction, spacer)


def setRightToolBar(visible):
    """
    Set docked toolbar on the right side of the main window
    """

    toolbarArea = qt.Qt.RightToolBarArea

    verticalToolBars = [
        "ViewToolBar",
        "ViewersToolBar",
        "MouseModeToolBar",
        "CaptureToolBar",
    ]

    setToolbars([APP_TOOLBARS[tb] for tb in verticalToolBars], toolbarArea, qt.Qt.Vertical)


def setToolbars(toolbars, area, orientation, iconSize: qt.QSize = None):
    for toolbar in toolbars:
        toolbar.setVisible(True)
        toolbar.setOrientation(orientation)
        if iconSize:
            toolbar.setIconSize(iconSize)
        slicer.util.mainWindow().addToolBar(area, toolbar)


def setCustomCaptureToolBar():
    from commons.screenshot.Screenshot import ScreenshotWidget

    # Add customized screenshot dialog
    captureToolBar = APP_TOOLBARS["CaptureToolBar"]

    for action in captureToolBar.actions():
        captureToolBar.removeAction(action)

    screenshotAction = captureToolBar.addAction(
        qt.QIcon((ICON_DIR / "png" / "ScreenShot.png").as_posix()),
        "",
        lambda: ScreenshotWidget().exec(),
    )
    screenshotAction.setToolTip("Capture a screenshot")


def setModulePanelVisible(visible):
    modulePanelDockWidget = slicer.util.mainWindow().findChildren("QDockWidget", "PanelDockWidget")[0]
    modulePanelDockWidget.setVisible(visible)


def setModulePanel():
    modulePanelDockWidget = slicer.util.mainWindow().findChild("QDockWidget", "PanelDockWidget")
    modulePanelDockWidget.setFeatures(qt.QDockWidget.NoDockWidgetFeatures)
    modulePanelDockWidget.setMinimumWidth(0)

    # make central panel widget ignore content width
    centralWidget = modulePanelDockWidget.widget()
    centralWidget.setSizePolicy(qt.QSizePolicy.Policy.Ignored, centralWidget.sizePolicy.verticalPolicy())

    # add a bounding qframe to make the title shrinkable
    moduleHeader = ModuleHeader()
    moduleHeader.setSizePolicy(qt.QSizePolicy.Policy.Ignored, moduleHeader.sizePolicy.verticalPolicy())
    titleFrame = qt.QFrame()
    titleLayout = qt.QVBoxLayout(titleFrame)
    titleLayout.setContentsMargins(0, 0, 0, 0)
    titleLayout.setSpacing(0)
    titleLayout.addWidget(moduleHeader)
    modulePanelDockWidget.setTitleBarWidget(titleFrame)

    # force content to be aligned to the right
    modulePanel = modulePanelDockWidget.findChild(slicer.qSlicerModulePanel, "ModulePanel")
    scrollArea = modulePanel.findChild("QScrollArea", "ScrollArea")
    scrollArea.setSizePolicy(qt.QSizePolicy.Policy.Ignored, scrollArea.sizePolicy.verticalPolicy())
    scrollBar = scrollArea.horizontalScrollBar()

    def sliderToMaximum(min: int, max: int):
        scrollBar.blockSignals(True)
        scrollBar.triggerAction(qt.QAbstractSlider.SliderToMaximum)
        scrollBar.blockSignals(False)

    scrollBar.rangeChanged.connect(sliderToMaximum)

    # handle module selection
    def handle(moduleName):
        try:
            if not hasattr(slicer.modules, f"{moduleName}Instance"):
                title = moduleName
                url = MANUAL_BASE_URL
            else:
                module = getattr(slicer.modules, f"{moduleName}Instance")
                url = module.helpUrl if hasattr(module, "helpUrl") else MANUAL_BASE_URL
                if isinstance(url, qt.QUrl):
                    url = url.toString()
                title = module.title() if hasattr(module, "title") else moduleName

            moduleHeader.update(title, url, moduleName)
        except Exception as e:
            logging.error(f"Failed to update module header: {e}.\n{traceback.format_exc()}")

        if modulePanelDockWidget.width < 400:
            slicer.util.mainWindow().resizeDocks([modulePanelDockWidget], [400], qt.Qt.Horizontal)

    slicer.util.moduleSelector().moduleSelected.connect(handle)


def updateFileMenu():
    fileMenu = slicer.util.mainWindow().findChild("QMenu", "FileMenu")
    actions = {action.text: action for action in fileMenu.actions()}

    def createIcon(fileName):
        return helpers.svgToQIcon((getResourcePath("Icons") / "svg" / fileName).as_posix())

    loadSceneAction = qt.QAction(createIcon("Load.svg"), "Load Scene", fileMenu)
    loadSceneAction.setToolTip("Load project/scene .mrml file")
    loadSceneAction.triggered.connect(getAppContext().projectEventsLogic.loadScene)

    # Save scene
    saveDataAction = actions["Save Data"]
    saveDataAction.setIcon(createIcon("Save.svg"))
    saveDataAction.triggered.disconnect()
    saveDataAction.triggered.connect(getAppContext().projectEventsLogic.saveScene)
    saveDataAction.setToolTip("Save the current and modified project/scene .mrml file")

    saveSceneAsAction = qt.QAction(createIcon("SaveAs.svg"), "Save Scene As", fileMenu)
    saveSceneAsAction.setShortcut(qt.QKeySequence("Ctrl+Shift+S"))
    saveSceneAsAction.triggered.connect(getAppContext().projectEventsLogic.saveSceneAs)
    saveSceneAsAction.setToolTip("Save the current and modified project/scene .mrml file into a new directory")

    closeSceneAction = actions["Close Scene"]
    closeSceneAction.setIcon(createIcon("Close.svg"))
    closeSceneAction.triggered.disconnect()  # Disconnect previous callback
    closeSceneAction.triggered.connect(getAppContext().projectEventsLogic.onCloseScene)
    closeSceneAction.setToolTip("Clear the current project/scene")

    order = [
        actions["&Add Data"],
        actions["Recent"],
        "Separator",
        loadSceneAction,
        saveDataAction,
        saveSceneAsAction,
        "Separator",
        closeSceneAction,
        "Separator",
        actions["E&xit"],
    ]

    [fileMenu.removeAction(action) for action in fileMenu.actions()]

    for action in order:
        if action == "Separator":
            fileMenu.addSeparator()
            continue

        fileMenu.addAction(action)

    actions["Save Data"].setText("Save Scene")
    actions["&Add Data"].setIcon(createIcon("AddData.svg"))


def updateEditMenu():
    editMenu = slicer.util.mainWindow().findChild("QMenu", "EditMenu")
    actions = {action.text: action for action in editMenu.actions()}

    def createIcon(fileName):
        return helpers.svgToQIcon((getResourcePath("Icons") / "svg" / fileName).as_posix())

    actions["Cut"].setIcon(createIcon("Cut.svg"))
    actions["Copy"].setIcon(createIcon("Copy.svg"))
    actions["Paste"].setIcon(createIcon("Paste.svg"))
    actions["Application Settings"].setIcon(createIcon("Preferences.svg"))


def updateViewMenu():
    viewMenu = slicer.util.mainWindow().findChild("QMenu", "ViewMenu")
    actions = {action.text: action for action in viewMenu.actions()}

    def createIcon(fileName):
        return helpers.svgToQIcon(getResourcePath("Icons") / "svg" / fileName)

    fuzzySearchAction = qt.QAction(createIcon("SearchCode.svg"), "Module Search", viewMenu)
    fuzzySearchAction.triggered.connect(showSearchPopup)

    order = [
        actions["Layout"],
        actions["&Toolbars"],
        actions["&Appearance"],
        "Separator",
        fuzzySearchAction,
        "Separator",
        actions["Module Finder"],
        actions["&Python Console"],
        actions["&Error Log"],
        actions["Home"],
    ]

    [viewMenu.removeAction(action) for action in viewMenu.actions()]

    for action in order:
        if action == "Separator":
            viewMenu.addSeparator()
            continue

        viewMenu.addAction(action)

    actions["Module Finder"].setIcon(createIcon("Search.svg"))
    actions["Module Finder"].setText("Legacy Module Finder")
    actions["Home"].setIcon(createIcon("Home.svg"))
    actions["&Python Console"].setIcon(createIcon("Console.svg"))


def updateHelpMenu():
    helpMenu = slicer.util.mainWindow().findChild("QMenu", "HelpMenu")

    def createIcon(fileName):
        return helpers.svgToQIcon((getResourcePath("Icons") / "svg" / fileName).as_posix())

    # Bug report
    bugReportAction = qt.QAction(createIcon("Bug.svg"), "Bug Report", helpMenu)
    bugReportAction.triggered.connect(ltraceBugReport)

    # About
    def __onAboutGeoSlicerClicked():
        AboutDialog(parent=slicer.util.mainWindow()).show()

    aboutAction = qt.QAction(createIcon("About.svg"), "About GeoSlicer", helpMenu)
    aboutAction.triggered.connect(__onAboutGeoSlicerClicked)

    # Manual
    def __openGeoslicerManual():
        qt.QDesktopServices.openUrl(qt.QUrl(MANUAL_BASE_URL))

    geoslicerIcon = helpers.svgToQIcon((getResourcePath("Icons") / "svg" / "CircleHelp.svg").as_posix())
    manualHelpAction = qt.QAction(geoslicerIcon, "Getting Started", helpMenu)
    manualHelpAction.triggered.connect(__openGeoslicerManual)

    order = [
        # actions["&Keyboard Shortcuts"],
        bugReportAction,
        "Separator",
        manualHelpAction,
        aboutAction,
    ]

    [helpMenu.removeAction(action) for action in helpMenu.actions()]

    for action in order:
        if action == "Separator":
            helpMenu.addSeparator()
            continue

        helpMenu.addAction(action)


def setMenu():
    updateFileMenu()
    updateEditMenu()
    updateViewMenu()
    updateHelpMenu()


def setExtentionManagerOff():
    window = slicer.util.mainWindow()
    window.findChild(qt.QMenu, "ViewMenu").actions()[5].visible = False
    # window.findChild(qt.QToolBar, "DialogToolBar").actions()[1].visible = False


def setStatusBar():
    statusBar = slicer.util.mainWindow().statusBar()
    statusBar.setVisible(True)

    statusBar.findChild(qt.QToolButton).setVisible(False)
    statusBar.setFixedHeight(20)

    progressBar = GlobalProgressBar.instance()
    progressBar.setObjectName("GlobalProgressBar")

    statusBar.addPermanentWidget(progressBar)

    ctx = getAppContext()
    ctx.memoryUsageWidget = MemoryUsageWidget()
    statusBar.addPermanentWidget(ctx.memoryUsageWidget)
    ctx.memoryUsageWidget.start()


def setColorNodeName():
    colorNode = slicer.util.getNode("GenericAnatomyColors")
    colorNode.SetName("GenericColors")


def setOrientationNames():
    """
    created by: Giulio Simão
    commit 14c032131ee0affb7ae2aa806250bae8d59bb575
    * PL-1387 Swapped strings, created function to change orientation names
    """
    sliceNodes = slicer.util.getNodesByClass("vtkMRMLSliceNode")
    sliceNodes.append(slicer.mrmlScene.GetDefaultNodeByClass("vtkMRMLSliceNode"))
    for sliceNode in sliceNodes:
        axialSliceToRas = sliceNode.GetSliceOrientationPreset("Axial")
        sliceNode.RemoveSliceOrientationPreset("Axial")
        sliceNode.AddSliceOrientationPreset("XY", axialSliceToRas)

        sagittalSliceToRas = sliceNode.GetSliceOrientationPreset("Sagittal")
        sliceNode.RemoveSliceOrientationPreset("Sagittal")
        sliceNode.AddSliceOrientationPreset("YZ", sagittalSliceToRas)

        coronalSliceToRas = sliceNode.GetSliceOrientationPreset("Coronal")
        sliceNode.RemoveSliceOrientationPreset("Coronal")
        sliceNode.AddSliceOrientationPreset("XZ", coronalSliceToRas)


def showHideAllVolumes(self, button):
    from Multicore import MulticoreLogic

    buttonText = button.text
    buttonToolTip = button.toolTip
    if "Show" in buttonText:
        button.setText(buttonText.replace("Show", "Hide"))
        button.setToolTip(buttonToolTip.replace("Show", "Hide"))
        show = True
    else:
        button.setText(buttonText.replace("Hide", "Show"))
        button.setToolTip(buttonToolTip.replace("Hide", "Show"))
        show = False

    viewNode = slicer.app.layoutManager().threeDWidget(0).mrmlViewNode()
    volumeRenderingLogic = slicer.modules.volumerendering.logic()
    multicoreLogic = MulticoreLogic()
    volumes = multicoreLogic.getVolumes()
    for volume in volumes:
        renderingNode = volumeRenderingLogic.GetVolumeRenderingDisplayNodeForViewNode(volume, viewNode)
        if renderingNode is None:
            renderingNode = volumeRenderingLogic.CreateDefaultVolumeRenderingNodes(volume)
        renderingNode.SetVisibility(show)


def linkAllVolumesRenderingDisplayProperties(volume_rendering_module):
    from Multicore import MulticoreLogic

    volumeNodeSelector = volume_rendering_module.findChild(qt.QObject, "VolumeNodeSelector")
    shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
    currentNode = shNode.GetItemDataNode(volumeNodeSelector.currentItem())
    volumeRenderingLogic = slicer.modules.volumerendering.logic()
    currentDisplayNode = volumeRenderingLogic.CreateDefaultVolumeRenderingNodes(currentNode)
    volumeRenderingLogic = slicer.modules.volumerendering.logic()
    multicoreLogic = MulticoreLogic()
    volumes = multicoreLogic.getVolumes()
    for volume in volumes:
        displayNode = volumeRenderingLogic.CreateDefaultVolumeRenderingNodes(volume)
        displayNode.SetAndObserveVolumePropertyNodeID(currentDisplayNode.GetVolumePropertyNodeID())


def onPresetComboBoxClicked(object, event):
    if isinstance(event, qt.QMouseEvent):
        if event.type() == qt.QEvent.MouseButtonPress:
            if event.button() == qt.Qt.LeftButton:
                volumeRenderingModule = slicer.modules.volumerendering.widgetRepresentation()
                synchronizeScalarDisplayNodeButton = volumeRenderingModule.findChild(
                    ctk.ctkCheckablePushButton, "SynchronizeScalarDisplayNodeButton"
                )
                if synchronizeScalarDisplayNodeButton.checked:
                    # Expanding advanced collapsible button
                    advancedCollapsibleButton = volumeRenderingModule.findChild(
                        ctk.ctkCollapsibleButton, "AdvancedCollapsibleButton"
                    )
                    advancedCollapsibleButton.collapsed = False

                    # Setting current tab to "Volume properties"
                    tabBar = volumeRenderingModule.findChild(qt.QTabBar, "qt_tabwidget_tabbar")
                    tabBar.setCurrentIndex(1)

                    # Unchecking Synchronize with Volumes module button
                    synchronizeScalarDisplayNodeButton.setChecked(False)

                    # Setting the style of the button to alert the user about the checked state change
                    synchronizeScalarDisplayNodeButton = volumeRenderingModule.findChild(
                        ctk.ctkCheckablePushButton, "SynchronizeScalarDisplayNodeButton"
                    )
                    synchronizeScalarDisplayNodeButton.setStyleSheet("color: red;")

                    # Resetting the style after a short time
                    qt.QTimer.singleShot(3000, lambda: synchronizeScalarDisplayNodeButton.setStyleSheet(None))


def setVolumeRenderingModule():
    volumeRenderingModule = slicer.modules.volumerendering.widgetRepresentation()
    qSlicerIconComboBox = volumeRenderingModule.findChild(qt.QObject, "PresetComboBox").children()[2].children()[-1]
    qSlicerIconComboBox.setItemText(0, "CT Carbonate")
    qSlicerIconComboBox.setItemIcon(0, qt.QIcon(ICON_DIR / "samples" / "Carbonate-CT.png"))
    qSlicerIconComboBox.setItemText(1, "CT Sandstone")
    qSlicerIconComboBox.setItemIcon(1, qt.QIcon(ICON_DIR / "samples" / "Sandstone-CT.png"))
    qSlicerIconComboBox.setItemText(2, "Grains")
    qSlicerIconComboBox.setItemIcon(2, qt.QIcon(ICON_DIR / "samples" / "small_Grains.png"))
    qSlicerIconComboBox.setItemText(3, "Pores")
    qSlicerIconComboBox.setItemIcon(3, qt.QIcon(ICON_DIR / "samples" / "small_Pores.png"))
    qSlicerIconComboBox.setItemText(4, "microCT")
    qSlicerIconComboBox.setItemIcon(4, qt.QIcon(ICON_DIR / "samples" / "small_mCT.png"))

    # Link all volumes display properties
    layout = volumeRenderingModule.findChild(qt.QObject, "DisplayCollapsibleButton").children()[0]
    button = qt.QPushButton("Link all volumes")
    button.setToolTip("Link all volumes rendering display properties")
    button.setFixedHeight(40)
    button.clicked.disconnect()
    button.clicked.connect(lambda: linkAllVolumesRenderingDisplayProperties(volumeRenderingModule))
    layout.addWidget(button)

    # Show/hide all volumes
    layout = volumeRenderingModule.findChild(qt.QObject, "DisplayCollapsibleButton").children()[0]
    button = qt.QPushButton("Show all volumes")
    button.setToolTip("Show all volumes on 3D scene")
    button.setFixedHeight(40)
    button.clicked.disconnect()
    button.clicked.connect(lambda: showHideAllVolumes(button))
    layout.addWidget(button)

    # Blocks commas from the X spin boxes
    advancedPropertyWidget = (
        volumeRenderingModule.findChild(ctk.ctkCollapsibleButton, "AdvancedCollapsibleButton")
        .findChild(qt.QTabWidget, "AdvancedTabWidget")
        .findChild(qt.QStackedWidget, "qt_tabwidget_stackedwidget")
        .findChild(qt.QWidget, "VolumePropertyTab")
        .findChild(slicer.qMRMLVolumePropertyNodeWidget, "VolumePropertyNodeWidget")
        .findChild(ctk.ctkVTKVolumePropertyWidget, "VolumePropertyWidget")
    )
    scalarOpacityXSpinBox = (
        advancedPropertyWidget.findChild(ctk.ctkCollapsibleGroupBox, "ScalarOpacityGroupBox")
        .findChild(ctk.ctkVTKScalarsToColorsWidget, "ScalarOpacityWidget")
        .findChild(qt.QDoubleSpinBox, "XSpinBox")
    )
    scalarColorXSpinBox = (
        advancedPropertyWidget.findChild(ctk.ctkCollapsibleGroupBox, "ScalarColorGroupBox")
        .findChild(ctk.ctkVTKScalarsToColorsWidget, "ScalarColorWidget")
        .findChild(qt.QDoubleSpinBox, "XSpinBox")
    )
    gradientXSpinBox = (
        advancedPropertyWidget.findChild(ctk.ctkCollapsibleGroupBox, "GradientGroupBox")
        .findChild(ctk.ctkVTKScalarsToColorsWidget, "GradientWidget")
        .findChild(qt.QDoubleSpinBox, "XSpinBox")
    )
    locale = qt.QLocale()
    locale.setNumberOptions(qt.QLocale.RejectGroupSeparator)
    opacityValidator = qt.QDoubleValidator(scalarOpacityXSpinBox.findChild(qt.QLineEdit))
    opacityValidator.setLocale(locale)
    scalarOpacityXSpinBox.findChild(qt.QLineEdit).setValidator(opacityValidator)
    colorValidator = qt.QDoubleValidator(scalarColorXSpinBox.findChild(qt.QLineEdit))
    scalarColorXSpinBox.findChild(qt.QLineEdit).setValidator(colorValidator)
    gradientValidator = qt.QDoubleValidator(gradientXSpinBox.findChild(qt.QLineEdit))
    gradientXSpinBox.findChild(qt.QLineEdit).setValidator(gradientValidator)

    # Detect clicking over the preset combo box to check for Synchronize with volumes button state, and act over
    presetComboBox = volumeRenderingModule.findChild(qt.QObject, "PresetComboBox")
    qSlicerIconComboBox = presetComboBox.children()[2].children()[-1]
    CustomEventFilter(onPresetComboBoxClicked, qSlicerIconComboBox).install()  # TODO generalize


def setPyQtGraph():
    import pyqtgraph as pg

    pg.setConfigOption("background", "w")
    pg.setConfigOption("foreground", "k")
    pg.setConfigOptions(antialias=True)

    def warning_wrap(func):
        def wrapped(*args, **kwargs):
            logging.warning(
                "WARNING: setting up pyqtgraph configurations globally may affect other modules.\n"
                "Customizer.setup_pyqtgraph_config() configures pyqtgraph during initialization."
            )
            return func(*args, **kwargs)

        return wrapped

    pg.setConfigOption = warning_wrap(pg.setConfigOption)
    pg.setConfigOptions = warning_wrap(pg.setConfigOptions)


# TODO relocate
def on_html_link_clicked(self, url):
    if not url.scheme():
        qt.QDesktopServices.openUrl(qt.QUrl("file:///" + slicer.app.applicationDirPath() + "/../" + str(url)))
    else:
        qt.QDesktopServices.openUrl(url)


def setHelpModule():
    main_window = slicer.util.mainWindow()
    module_panel = main_window.findChild(slicer.qSlicerModulePanel, "ModulePanel")
    help_label = module_panel.findChild(ctk.ctkFittedTextBrowser, "HelpLabel")
    help_label.setOpenLinks(False)
    help_label.anchorClicked.connect(on_html_link_clicked)


def registerDisplayOverridePlugin():
    """Install the global display-override provider for the SH Data tree.

    Sets a single scripted plugin as qSlicerSubjectHierarchyPluginHandler's display provider.
    The C++ model consults this provider for tooltip / icon / displayed-name / visibility-icon
    on every name-column and visibility-column refresh in every SH tree view.
    """
    import SubjectHierarchyPlugins.DisplayOverrideSubjectHierarchyPlugin as mod

    overridePlugin = slicer.qSlicerSubjectHierarchyScriptedPlugin(None)
    overridePlugin.setPythonSource(mod.DisplayOverrideSubjectHierarchyPlugin.filePath)
    slicer.qSlicerSubjectHierarchyPluginHandler().instance().setDisplayOverrideProvider(overridePlugin)


def registerEffects():
    """
    added by: Gabriel Muller
    commit 7930e1b6f6c8d8b1fc473670303bd10733c98979
    PL-1761 Register effects before seg editor configuration
    """

    slicer.modules.BoundaryRemovalEffectInstance.registerEditorEffect()
    slicer.modules.ColorThresholdEffectInstance.registerEditorEffect()
    slicer.modules.ConnectivityEffectInstance.registerEditorEffect()
    slicer.modules.CustomizedSmoothingEffectInstance.registerEditorEffect()
    slicer.modules.PeriodicLevelTracingEffectInstance.registerEditorEffect()
    slicer.modules.DepthRangeSegmenterEffectInstance.registerEditorEffect()
    slicer.modules.ExpandSegmentsEffectInstance.registerEditorEffect()
    slicer.modules.MaskVolumeEffectInstance.registerEditorEffect()
    slicer.modules.MultiThresholdEffectInstance.registerEditorEffect()
    slicer.modules.SampleSegmentationEffectInstance.registerEditorEffect()
    slicer.modules.SmartForegroundEffectInstance.registerEditorEffect()
    slicer.modules.QEMSCANMaskEffectInstance.registerEditorEffect()


def setGPUStatus():
    if os.name == "nt":
        try:
            from win32.win32api import GetFileVersionInfo, LOWORD, HIWORD

            def get_version_number(filename):
                info = GetFileVersionInfo(filename, "\\")
                ms = info["FileVersionMS"]
                ls = info["FileVersionLS"]
                return HIWORD(ms), LOWORD(ms), HIWORD(ls), LOWORD(ls)

            version = get_version_number(r"C:\Windows\System32\nvcuda.dll")
            if version[2] == 14 and version[3] < 5239 or version[2] < 14:
                raise Exception(
                    "Driver version not supported.\n Your system has version "
                    + str(version)
                    + ", but tensorflow needs version >= x.x.14.5239 (452.39)"
                )
        except Exception as e:
            qt.QSettings().setValue("TensorFlow/GPUEnabled", str(False))
            logging.warning(
                "Tensorflow GPU support disabled, please check your driver and make sure your system has a recent NVDIA GPU.\n"
                + str(e)
            )
            return
        qt.QSettings().setValue("TensorFlow/GPUEnabled", str(True))


# # TODO usar isso na hora da busca (os modulos)
# def setAllowedModules():
#     slicer_basic_modules = [
#         "Annotations",
#         "Data",
#         "Markups",
#         "Models",
#         "SceneViews",
#         "SegmentEditor",
#         "Segmentations",
#         "SubjectHierarchy",
#         "ViewControllers",
#         "VolumeRendering",
#         "Volumes",
#     ]
#
#     slicer_module_whitelist = [
#         "Tables",
#         "CropVolume",
#         "SegmentMesher",
#         "RawImageGuess",
#         "LandmarkRegistration",
#         "GradientAnisotropicDiffusion",
#         "CurvatureAnisotropicDiffusion",
#         "GaussianBlurImageFilter",
#         "MedianImageFilter",
#         "VectorToScalarVolume",
#         "ScreenCapture",
#         "SimpleFilters",
#         "SegmentStatistics",
#         "MONAILabel",
#         "MONAILabelReviewer",
#     ]
#
#     ltrace_module_whitelist = VISIBLE_LTRACE_PLUGINS
#     ltrace_module_whitelist.extend(slicer_basic_modules)
#     ltrace_module_whitelist.extend(slicer_module_whitelist)
#
#     category_use_count = defaultdict(lambda: 0)
#     module_selector = slicer.util.mainWindow().moduleSelector().modulesMenu()
#
#     for module_name in dir(slicer.moduleNames):
#         if module_name.startswith("_"):
#             # python attribute
#             continue
#
#         module = getattr(slicer.modules, module_name.lower(), None)
#         if module is None:
#             # Module is disabled
#             continue
#
#         if module_name not in slicer_basic_modules:
#             # ignore basic modules to avoid overcrowding menu
#             for category in module.categories:
#                 category_use_count[category] += 1
#                 # parent category must be counted also
#                 category_split = category.split(".")
#                 if len(category_split) > 1:
#                     category_use_count[category_split[0]] += 1
#
#         if module.name not in ltrace_module_whitelist:
#             module_selector.removeModule(module)
#             for category in module.categories:
#                 category_use_count[category] -= 1
#                 # parent category must be counted also
#                 category_split = category.split(".")
#                 if len(category_split) > 1:
#                     category_use_count[category_split[0]] -= 1
#
#     for category, count in category_use_count.items():
#         if count == 0:
#             module_selector.removeCategory(category)


def extraChangesOnMenu():
    # disable Ruler and change name of Line to Ruler
    sn = slicer.mrmlScene.GetNodeByID("vtkMRMLSelectionNodeSingleton")
    sn.RemovePlaceNodeClassNameFromList("vtkMRMLAnnotationRulerNode")
    cname = "vtkMRMLMarkupsLineNode"
    resource = ":/Icons/png/AnnotationDistance.png"
    iconName = "Ruler"
    sn.AddNewPlaceNodeClassNameToList(cname, resource, iconName)


def onImageLogViewSelected(self):
    widget = slicer.util.getModuleWidget("ImageLogEnv")
    if widget is None:
        logging.critical("ImageLogData module was not found!")
        return

    widget.imageLogDataWidget.self().logic.changeToLayout()


def setLayoutViews():

    slicer.modules.SideBySideLayoutViewInstance.sideBySideImageLayout()
    slicer.modules.SideBySideLayoutViewInstance.sideBySideSegmentationLayout()
    slicer.modules.SideBySideLayoutViewInstance.sideBySideDumbLayout()

    toolbar = APP_TOOLBARS["ViewToolBar"]
    layoutAction = toolbar.actions()[0]
    layoutButton = toolbar.widgetForAction(layoutAction)
    layoutMenu = layoutButton.menu()

    moved_itens_indexes = [1, 2, 4, 5, 6, 7, 8, 10, 11, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28]
    moved_itens = []
    for i in moved_itens_indexes:
        moved_itens.append(layoutMenu.actions()[i])

    layoutMenu.insertSeparator(layoutMenu.actions()[11])
    layoutMenu.insertSeparator(layoutMenu.actions()[16])
    layoutMenu.addSeparator()

    advancedMenu = qt.QMenu("More", slicer.util.mainWindow())

    for i in moved_itens:
        advancedMenu.addAction(i)
        layoutMenu.removeAction(i)

    layoutMenu.addMenu(advancedMenu)
    layoutMenu.setStyleSheet("QMenu::separator { height: 1px; background: gray; }")

    # # Slicer bug. It always start on this item, which is not selectable (it is a submenu)
    # if layoutAction.text == "Three over three Quantitative":
    #     default_action = layoutMenu.actions()[0]
    #     default_action.trigger()

    # layoutButton.setDefaultAction(layoutAction)

    # 0"Conventional"
    # 1"Conventional Widescreen"
    # 2"Conventional Plot"
    # 3"Four-Up"
    # 4"Four-Up Table"
    # 5"Four-Up Plot"
    # 6"Four-Up Quantitative"
    # 7"Dual 3D"
    # 8"Triple 3D"
    # 9"3D only"
    # 10"3D Table"
    # 11"Plot only"
    # 12"Red slice only"
    # 13"Yellow slice only"
    # 14"Green slice only"
    # 15"Tabbed 3D"
    # 16"Tabbed slice"
    # 17"Compare"
    # 18"Compare Widescreen"
    # 19"Compare Grid"
    # 20"Three over three"
    # 21"Three over three Plot"
    # 22"Four over four"
    # 23"Two over two"
    # 24"Side by side"
    # 25"Four by three slice"
    # 26"Four by two slice"
    # 27"Three by three slice"
    # 28"Red slice and 3D"
    # 29"Yellow slice and 3D"
    # 30"Green slice and 3D"
    # 31"Side by side"
    # 32"Side by side segmentation"

    # Add ImageLog view as option
    # imageLogLayoutViewAction = qt.QAction(qt.QIcon(self.IMAGELOG_ICON_PATH), "ImageLog View", toolbar)
    # imageLogLayoutViewAction.triggered.connect(onImageLogViewSelected)
    #
    # after3dOnlyAction = layoutMenu.actions()[3]
    # layoutMenu.insertAction(after3dOnlyAction, imageLogLayoutViewAction)

    # layoutMenu.triggered.connect(lambda action: self.__layout_menu.setActiveAction(action))


def expandSceneFolder():
    folder_tree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    scene_id = folder_tree.GetSceneItemID()
    dataWidget = slicer.modules.data.widgetRepresentation()
    shTreeView = slicer.util.findChild(dataWidget, name="SubjectHierarchyTreeView")
    shTreeView.expandItem(scene_id)


def removeDataStore():
    slicer.util.mainWindow().moduleSelector().modulesMenu().removeModule("DataStore")


def showSearchPopup():
    slicer.modules.AppContextInstance.fuzzySearch.exec_()


def setupShortcuts():

    mainWindow = getAppContext().mainWindow if getAppContext() else slicer.util.mainWindow()
    # # find buttons
    # widget = slicer.modules.SegmentEditorWidget.editor.findChild("QWidget", "EffectsGroupBox")
    # def addEffectShortcut(name, keysequence ):
    #     but = widget.findChild( 'QToolButton', name )
    #     shortcut = qt.QShortcut( mainWindow() ) # ^TODO: use SegmentEditorWidget for focused shortcut, does thtat work?
    #     shortcut.setKey( keysequence )
    #     shortcut.connect('activated()', lambda: but.click())
    # addEffectShortcut("NULL", qt.QKeySequence( 'Ctrl+Q'))
    # addEffectShortcut("Erase", qt.QKeySequence('Shift+F4'))
    # addEffectShortcut("Paint", qt.QKeySequence( 'Shift+F5'))
    # addEffectShortcut("Scissors", qt.QKeySequence( 'Shift+F6'))
    # add shortcut for brush size
    qt.QShortcut(qt.QKeySequence("Ctrl+Shift+o"), mainWindow).connect(
        "activated()", lambda: showOnboardView(APP_TOOLBARS["ModuleToolBar"])
    )

    mtoolbar = mainWindow.findChild(slicer.qSlicerModuleSelectorToolBar)

    for toolbutton in mtoolbar.findChildren(qt.QToolButton):
        for a in toolbutton.actions():
            if a.objectName == "ViewFindModuleAction":
                a.setShortcut(qt.QKeySequence("Ctrl+Shift+F"))

    def showSearchPopup():
        slicer.modules.AppContextInstance.fuzzySearch.exec_()

    qt.QShortcut(qt.QKeySequence("Ctrl+F"), mainWindow).connect("activated()", showSearchPopup)

    def resetMouseMode():
        """Reset the mode to 'View' in MouseModeToolBar."""
        mouseModeToolBar = APP_TOOLBARS.get("MouseModeToolBar")
        if not mouseModeToolBar:
            return

        for action in mouseModeToolBar.actions():
            if action.text == "View":
                action.trigger()
            else:
                action.setChecked(False)

    qt.QShortcut(qt.QKeySequence("Escape"), mainWindow).connect("activated()", resetMouseMode)


def updateModuleSelectorIcons() -> None:
    def createIcon(fileName):
        return helpers.svgToQIcon((getResourcePath("Icons") / "svg" / fileName).as_posix())

    icon_map = {"Next": "ArrowRight.svg", "Previous": "ArrowLeft.svg"}
    for child in slicer.util.mainWindow().moduleSelector().findChildren(qt.QToolButton):
        file_name = icon_map.get(child.text)
        if file_name is None:
            continue
        icon = createIcon(file_name)
        action = child.defaultAction()
        if action:
            action.setIcon(icon)
        else:
            child.setIcon(icon)


def disableThemeSelectorInSettings():
    styleBox = slicer.app.settingsDialog().findChild(qt.QComboBox, "StyleComboBox")
    styleBox.enabled = False
    styleBox.setToolTip("Light Mode support coming soon")


def updateLogConfiguration():
    qt.QSettings().setValue("LogFiles/NumberOfFilesToKeep", 20)
    qt.QSettings().sync()


def disableResetFieldOfViewOnShowVolume():
    qt.QSettings().setValue("SubjectHierarchy/ResetFieldOfViewOnShowVolume", False)
    qt.QSettings().setValue("SubjectHierarchy/ResetViewOrientationOnShowVolume", False)


def _autoStartWebServer():
    """Start the Slicer WebServer module programmatically in developer mode.

    Enables agent communication via http://localhost:2016/slicer/exec
    without requiring manual GUI interaction.
    """
    if not slicer_is_in_developer_mode():
        return

    try:
        if not hasattr(slicer.modules, "webserver"):
            logging.warning("WebServer module not available; agent API will not be accessible.")
            return

        widget = slicer.modules.webserver.widgetRepresentation()
        if widget is None:
            logging.warning("WebServer widget representation not available.")
            return

        webServerWidget = widget.self()
        if webServerWidget.logic.serverStarted:
            return

        webServerWidget.enableSlicerHandler.setChecked(True)
        webServerWidget.enableSlicerHandlerExec.setChecked(True)
        webServerWidget.startServer()
        logging.info(f"WebServer auto-started on port {webServerWidget.logic.port} for agent access.")
    except Exception as e:
        logging.warning(f"Failed to auto-start WebServer: {e}")


def applyWindowGeometry(mainWindow):
    """Maximize on the first launch, afterwards keep the geometry saved on the previous exit."""
    settings = slicer.app.userSettings()
    restoring = str(settings.value("MainWindow/RestoreGeometry", False)).lower() == "true"
    if restoring and settings.contains("MainWindow/geometry") and not mainWindow.isMaximized():
        return

    # A window restored as maximized keeps that flag even when clamped to a smaller rectangle,
    # and showMaximized() is a no-op while the flag is set, so drop to the normal state first.
    if mainWindow.isMaximized():
        mainWindow.showNormal()
    mainWindow.showMaximized()


def configure():
    mainWindow = getAppContext().mainWindow if getAppContext() else slicer.util.mainWindow()
    applyWindowGeometry(mainWindow)

    updateLogConfiguration()
    disableResetFieldOfViewOnShowVolume()
    setModulePanelVisible(False)
    slicer.app.setRenderPaused(True)

    modules = loadModuleIndex()

    registerEffects()
    registerDisplayOverridePlugin()

    appContext = getAppContext()
    if appContext:
        appContext.modules.initCache(modules)
    else:
        logging.error("AppContext is not initialized yet!")

    loadCustomModules()

    # Hide Data Store module
    removeDataStore()

    setPyQtGraph()
    # setGPUStatus()
    setColorNodeName()
    setOrientationNames()
    setVolumeInterpolation(False)

    slicer.util.setModuleHelpSectionVisible(False)
    slicer.util.setDataProbeVisible(True)
    slicer.util.setModulePanelTitleVisible(True)
    slicer.util.setModuleHelpSectionVisible(False)

    if getAppContext():
        mainWindow.addDockWidget(qt.Qt.RightDockWidgetArea, getAppContext().rightDrawer.widget())
    else:
        logging.error("AppContext is not initialized yet!")

    setExtentionManagerOff()
    setHelpModule()
    setStatusBar()
    setMenu()
    setModuleSelectorToolBar()
    setModulesToolBar()
    setMainToolBar()
    setMarkupToolBar()
    setCustomCaptureToolBar()
    setRightToolBar(True)
    setDialogToolBar()
    setDataProbeCollapsibleButton()
    setCustomDataProbeInfo()
    updateWindowTitle(getApplicationVersion())
    updateDICOMDatabasePath()

    # TODO move to function (lock moveble)
    for toolbar in APP_TOOLBARS.values():
        toolbar.setMovable(False)

    customizeExportToFile()
    setVolumeRenderingModule()
    setLayoutViews()
    extraChangesOnMenu()

    slicer.modules.AppContextInstance.setupObservers()

    customizeColorMaps()
    customize3DView()

    setModulePanel()
    updateModuleSelectorIcons()
    installFonts()

    disableThemeSelectorInSettings()

    setupShortcuts()
    with open(getResourcePath("Styles") / "StyleSheet-dark.qss", "r") as style:
        stylesheet = style.read()
        stylesheet = Template(stylesheet).substitute(iconPath=getResourcePath("Icons/widgets").as_posix())
        slicer.app.styleSheet = stylesheet
        slicer.app.pythonConsole().setStyleSheet("QTextEdit { background-color: #1e1e1e; }")

    # set default module: Data
    slicer.util.selectModule("CustomizedData")

    slicer.app.setRenderPaused(False)

    setModulePanelVisible(True)

    if getAppContext():
        mainWindow.addDockWidget(qt.Qt.RightDockWidgetArea, getAppContext().rightDrawer.widget())
    else:
        logging.error("AppContext is not initialized yet!")

    mainWindow.setAcceptDrops(True)
    import gc

    gc.disable()

    def _startEnv():
        ApplicationObservables().applicationLoadFinished.disconnect(_startEnv)
        gc.enable()
        _autoStartWebServer()
        shouldRunTests = slicer.app.userSettings().value("LTraceTestsWidget/RunOnStartup", None) is not None
        shouldSkipOnboarding = slicer.app.userSettings().value("GeoSlicer/AgentSkipOnboarding", None) is not None
        if shouldSkipOnboarding:
            slicer.app.userSettings().remove("GeoSlicer/AgentSkipOnboarding")
            slicer.app.userSettings().sync()

        preLoadEnvironment = getCustomArguments().preLoadEnvironment
        loaderInfo = [info for info in LOADERS.values() if info.environment == preLoadEnvironment]
        loaderInfo = loaderInfo[0] if loaderInfo else None

        if loaderInfo is None:
            if shouldRunTests:
                slicer.modules.AppContextInstance.runTest()
                return

            showOnboardView(APP_TOOLBARS["ModuleToolBar"])
            return

        loadEnvironment(APP_TOOLBARS["ModuleToolBar"], loaderInfo)
        if shouldRunTests:
            slicer.modules.AppContextInstance.runTest()

    ApplicationObservables().applicationLoadFinished.connect(_startEnv)

    slicer.modules.RemoteServiceInstance.setupRemoteService()

    expandSceneFolder()


def loadCustomModules():
    """Load modules from the user's module folders and from GEOSLICER_MODULE_PATHS, after disabling those that
    crashed GeoSlicer while loading in an earlier session."""
    recovery = recoverFromCrash()
    customModules().refresh()

    if recovery is not None:

        def _notify():
            ApplicationObservables().applicationLoadFinished.disconnect(_notify)
            showCrashRecoveryMessage(recovery)

        ApplicationObservables().applicationLoadFinished.connect(_notify)


def getCustomArguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GeoSlicer application custom arguments.")

    parser.add_argument("--preLoadEnvironment", default=None, help="Run test for SupervisedTrainingDataGenerator")

    args = parser.parse_args(slicer.app.commandOptions().unparsedArguments)

    return args


def loadModuleIndex():
    """The modules deployed with GeoSlicer, as indexed by the deploy script."""
    return {
        entry["key"]: ModuleInfo(str(APP_HOME / entry["path"]), entry["key"], entry["categories"], entry["hidden"])
        for entry in getJsonData()["GEOSLICER_MODULES"]
    }


def updateDICOMDatabasePath():
    """Update DICOM Database directory base path. This function helps old DICOM database files to be moved to the new desired location."""
    currentPath = (
        slicer.app.DICOMDatabaseDirectoryBasePath() if hasattr(slicer.app, "DICOMDatabaseDirectoryBasePath") else ""
    )
    desiredPath = Path(qt.QStandardPaths.writableLocation(qt.QStandardPaths.AppLocalDataLocation))

    if not currentPath:
        logging.info(
            f"The current DICOM Database directory base path is undefined. Defining default DICOM Database directory base path as '{str(desiredPath)}'"
        )
        slicer.app.userSettings().setValue("DICOM/DatabaseDirectoryBase", str(desiredPath))
        return

    currentPath = Path(currentPath)
    if not currentPath.exists():
        logging.info(
            f"The current DICOM Database directory base path '{str(currentPath)}' does not exist. Defining default DICOM Database directory base path as '{str(desiredPath)}'"
        )
        slicer.app.userSettings().setValue("DICOM/DatabaseDirectoryBase", str(desiredPath))
        return

    if currentPath == desiredPath:
        return

    try:
        isRelative = currentPath.is_relative_to(Path(slicer.app.slicerHome))
    except ValueError:
        isRelative = False

    if currentPath == Path(qt.QStandardPaths.writableLocation(qt.QStandardPaths.DocumentsLocation)) or isRelative:
        slicer.app.userSettings().setValue("DICOM/DatabaseDirectoryBase", str(desiredPath))
        logging.info(
            f"Updating the current DICOM Database directory base path to '{str(desiredPath)}'. Checking for existent DICOM Database files..."
        )

        dicomFilesWithSubs = [path for path in currentPath.rglob("*") if "dicom" in path.name.lower()]

        dicomFiles = []
        for path in dicomFilesWithSubs:
            isSubpath = any(path != otherPath and path.is_relative_to(otherPath) for otherPath in dicomFilesWithSubs)
            if not isSubpath:
                dicomFiles.append(path)

        for file in dicomFiles:
            try:
                relativePath = file.relative_to(currentPath)
                destination = desiredPath / relativePath
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(file, destination)
                logging.info(f"Moved DICOM Database file '{str(file)}' to '{str(destination)}'")
            except Exception as error:
                logging.warning(
                    f"Failed to update DICOM Database file '{str(file)}' to '{str(destination)}': {str(error)}"
                )

        logging.info("DICOM Database Migration completed.")


def init():
    os.chdir(slicer.app.slicerHome)

    # Slicer applies the style before this runs, so a changed style only comes back on the next start
    userSettings = slicer.app.userSettings()
    userSettings.setValue("Styles/Style", "Dark Slicer")
    userSettings.setValue("Modules/FavoriteModules", [])
    setUserPaths()

    configure()

    if getAppContext():
        getAppContext().appInitialized = True
    else:
        logging.error("AppContext is not initialized yet!")


def setUserPaths():
    """Keep temporary files, logs and saved scenes out of the installation, which may be read-only. Replace paths
    relative to an installation, which earlier versions saved to the settings that all installations share, and
    Slicer's fallback for when those weren't writable. Paths the user chose are kept."""
    # os must be imported locally, qSlicerCorePythonManager::appendPythonPath runs `del os, sys`
    import os

    userSettings = slicer.app.userSettings()

    # qSlicerCoreApplication::defaultTemporaryPath, which isn't available in Python
    slicerTemporaryPath = Path(qt.QDir.tempPath()) / (
        slicer.app.applicationName if os.name == "nt" else f"{slicer.app.applicationName}-{os.environ.get('USER', '')}"
    )
    temporaryPath = userSettings.value("TemporaryPath")
    if temporaryPath is None or not Path(temporaryPath).is_absolute() or Path(temporaryPath) == slicerTemporaryPath:
        appData = Path(qt.QStandardPaths.writableLocation(qt.QStandardPaths.AppLocalDataLocation))
        slicer.app.temporaryPath = (appData / "temp").as_posix()

    # Replace Slicer's default, Documents, which its settings panel saves at startup. Documents is often synced by
    # OneDrive, which can lock or restore the files a project deletes, and some Linux installations don't have it.
    # The home folder is a starting point to navigate from rather than a place to save in
    documents = Path(qt.QStandardPaths.writableLocation(qt.QStandardPaths.DocumentsLocation))
    scenePath = userSettings.value("DefaultScenePath")
    if scenePath is None or not Path(scenePath).is_absolute() or Path(scenePath) == documents:
        slicer.app.defaultScenePath = Path.home().as_posix()


def wasAppInitialized():
    if not getAppContext() or not hasattr(getAppContext(), "appInitialized"):
        return False

    return getAppContext().appInitialized


if not wasAppInitialized():
    # Condition to avoid the 'init()' call during the test environment
    init()
