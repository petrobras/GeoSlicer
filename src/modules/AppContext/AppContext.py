import itertools
import logging
import shutil
import slicer
import qt
import vtk

from functools import partial
from ltrace.constants import SaveStatus
from ltrace.slicer.app import updateWindowTitle, getApplicationVersion, parseApplicationVersion, getJsonData
from ltrace.slicer.app.custom_3dview import customize_3d_view
from ltrace.slicer.app.custom_colormaps import customize_color_maps
from ltrace.slicer.app.drawer import ExpandDataDrawer
from ltrace.slicer.app.onboard import showDataLoaders, loadEnvironmentByName
from ltrace.slicer.application_observables import ApplicationObservables
from ltrace.slicer.custom_main_window_event_filter import CustomizerEventFilter
from ltrace.slicer.helpers import BlockSignals, svgToQIcon
from ltrace.slicer.lazy import lazy
from ltrace.slicer.module_info import ModuleInfo
from ltrace.slicer.module_utils import fetchModulesFrom, mapByCategory
from ltrace.slicer.project_manager import ProjectManager, handleCopySuffixOnClonedNodes
from ltrace.slicer.widget.custom_toolbar_buttons import addMenuRaw, addAction, addActionWidget
from ltrace.slicer.widget.docked_data import DockedData
from ltrace.slicer.widget.fuzzysearch import FuzzySearchDialog, LinearSearchModel
from ltrace.slicer_utils import LTracePlugin, getResourcePath
from ltrace.constants import ImageLogConst
from pathlib import Path
from typing import List, Any, Tuple, Dict

try:
    from ltrace.slicer.tracking.tracking_manager import TrackingManager
except ImportError:
    TrackingManager = lambda *args, **kwargs: None


toBool = slicer.util.toBool


class AppContext(LTracePlugin):
    SETTING_KEY = "AppContext"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "App Context"
        self.parent.categories = ["System"]
        self.parent.dependencies = []
        self.parent.hidden = True
        self.parent.contributors = []
        self.parent.helpText = ""
        self.parent.acknowledgementText = ""

        ####################################################################################
        # Custom properties
        ####################################################################################

        self.appData = getJsonData()

        self.__mainWindow = None
        self.appVersionString = parseApplicationVersion(self.appData)
        self.modulesDir = ""
        self.__imageLogLayoutId = ImageLogConst.DEFAULT_LAYOUT_ID_START_VALUE

        self.fuzzySearchModel = LinearSearchModel()
        self.fuzzySearch = FuzzySearchDialog(self.fuzzySearchModel, parent=self.mainWindow)

        self.__trackingManager = TrackingManager()

        self.___projectManager = ProjectManager(folderIconPath=getResourcePath("Icons") / "ProjectIcon.ico")

        self.projectEventsLogic = ProjectEventsLogic(self.___projectManager)

        self.modules = ModuleManager(self)

        self.rightDrawer = ExpandDataDrawer(DockedData())

    @property
    def imageLogLayoutId(self):
        return self.__imageLogLayoutId

    @imageLogLayoutId.setter
    def imageLogLayoutId(self, lid):
        self.__imageLogLayoutId = lid

    @property
    def mainWindow(self):
        if self.__mainWindow is None:
            self.__mainWindow = slicer.util.mainWindow()

        return self.__mainWindow

    def setupObservers(self):

        if self.__trackingManager:
            self.__trackingManager.installTrackers()

        self.projectEventsLogic.register()

        qt.QTimer.singleShot(500, lambda: ApplicationObservables().applicationLoadFinished.emit())

    def getTracker(self):
        return self.__trackingManager

    def getAboutGeoSlicer(self) -> str:
        """Returns the HTML string that describes GeoSlicer in the about dialog.

        Returns:
            str: An HTML-formatted string containing the GeoSlicer's description.
        """
        return """
            <br><br>
            GeoSlicer is an AI-powered digital rocks platform, developed in collaboration between LTrace, Petrobras, and Equinor. It provides an integrated computational environment for processing digital rocks at all scales, combining machine learning and advanced data processing tools to support geoscientific analysis.
            <br><br>
            Built on the open-source <a href=\"https://www.slicer.org//\">3DSlicer</a> platform and powered by the <a href=\"https://www.qt.io/\">Qt for Open Source Development</a>,
            <br><br>
            For more information, visit our <a href=\"https://www.ltrace.com.br/\">website</a> or contact us at <a href=\"mailto:contact@ltrace.com.br">contact@ltrace.com.br</a>.
            """


class ModuleManager:
    def __init__(self, context):
        self.__ctx = context
        self.groups = {}
        self.availableModules = {}
        self.currentWorkingDataType = None

    def initCache(self, modules):
        logging.info(f"Found {len(modules)} available LTrace's modules to load.")
        self.availableModules = modules
        logging.info("Building reverse index...")
        self.groups = mapByCategory(modules.values())  # replace this with the movel below
        self.__ctx.fuzzySearchModel.setDataSource(modules)

    def setEnvironment(self, environment: Tuple[str, Any]):
        if self.currentWorkingDataType == environment:
            return

        self.currentWorkingDataType = environment
        ApplicationObservables().environmentChanged.emit()

    def fetchByCategory(self, query, intersectWith=None) -> Dict[str, ModuleInfo]:
        if intersectWith:
            result = set(self.groups.get(intersectWith, []))
            for category in query:
                result.intersection_update(self.groups.get(category, []))

        else:
            result = set(self.groups.get(query[0], []))
            for category in query[1:]:
                result.update(self.groups.get(category, []))

        return {m.key: m for m in result}

    def addToolsMenu(self, toolbar):
        tools = [
            "VolumeCalculator",
            "CustomizedTables",
            "TableFilter",
            "Charts",
        ]

        toolModules = [self.availableModules[m] for m in tools]

        addMenuRaw(
            svgToQIcon(getResourcePath("Icons") / "IconSet-dark" / "Table.svg"),
            "More tools",
            toolModules,
            toolbar,
        )

    def addLoadersMenu(self, toolbar):

        loaders = [
            "BIAEPBrowser",
            "OpenRockData",
            "NetCDF",
        ]

        toolModules = []

        for m in loaders:
            if m in self.availableModules:
                toolModules.append(self.availableModules[m])

        addMenuRaw(
            svgToQIcon(getResourcePath("Icons") / "IconSet-dark" / "Database.svg"),
            "Import",
            toolModules,
            toolbar,
        )

    def showDataLoaders(self, toolbar):
        showDataLoaders(toolbar)

    def loadEnvironmentByName(self, toolbar, displayName):
        loadEnvironmentByName(toolbar, displayName)


class ProjectEventsLogic:
    def __init__(self, projectManager):
        self.__projectManager = projectManager
        self.__customizerEventFilter = None

        self.startCloseSceneObserverHandler = None
        self.endCloseSceneObserverHandler = None
        self.nodeAddedObserverHandler = None

    def __del__(self):
        slicer.mrmlScene.RemoveObserver(self.startCloseSceneObserverHandler)
        slicer.mrmlScene.RemoveObserver(self.endCloseSceneObserverHandler)
        slicer.mrmlScene.RemoveObserver(self.nodeAddedObserverHandler)

    def register(self):
        self.__projectManager.setup()
        self.__projectManager.projectChangedSignal.connect(
            partial(updateWindowTitle, versionString=getApplicationVersion())
        )

        self.__customizerEventFilter = CustomizerEventFilter(saveSceneCallback=self.saveScene)
        slicer.modules.AppContextInstance.mainWindow.installEventFilter(self.__customizerEventFilter)

        self.startCloseSceneObserverHandler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.StartCloseEvent, self.__beginSceneClosing
        )
        self.endCloseSceneObserverHandler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.EndCloseEvent, self.__endSceneClosing
        )

        self.nodeAddedObserverHandler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.NodeAddedEvent, self.__onNodeAdded
        )

        self.endImportSceneObserverHandler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.EndImportEvent, self.__onEndImportEvent
        )

        lazy.register_eye_event()
        self.__projectManager.projectChangedSignal.connect(lazy.register_eye_event)

        self.setupRecentlyLoadedMenu()

    def loadScene(self):
        fileDialog = qt.QFileDialog(
            slicer.modules.AppContextInstance.mainWindow,
            "Load a scene",
            "",
            "GeoSlicer scene file (*.mrml)",
        )
        try:
            if fileDialog.exec():
                paths = fileDialog.selectedFiles()
                projectFilePath = paths[0]
                status = self.__projectManager.load(projectFilePath)
                if not status:
                    slicer.util.errorDisplay(
                        "An error occurred while loading the project. Please check the GeoSlicer log file.",
                        "Failed to load project",
                    )
                self.setupRecentlyLoadedMenu()
                return True
            return False
        finally:
            fileDialog.deleteLater()

    def saveScene(self):
        """Save current scene/project

        Returns:
            bool: True if scene was saved successfully, otherwise returns False
        """
        url = slicer.mrmlScene.GetURL()
        if url == "":
            return self.saveSceneAs()

        status = self.__projectManager.save(url)

        if status == SaveStatus.FAILED:
            slicer.util.errorDisplay(
                "An error occurred while saving the project. Please check the following:\n\n"
                + "1. Ensure that there is sufficient disk space available.\n"
                + "2. Verify that you have the necessary file writing permissions.\n\n"
                + "For further details, please consult the GeoSlicer log file. If the problem persists, consider reaching out to support.",
                "Failed to save project",
            )

        return status

    def saveSceneAs(self):
        """Handles save button clicked on save scene as dialog"""
        # Save directory
        path = qt.QFileDialog.getSaveFileName(
            slicer.modules.AppContextInstance.mainWindow,
            "Save project",
            slicer.app.defaultScenePath,
            "GeoSlicer project folder (*)",
            "",
            qt.QFileDialog.DontConfirmOverwrite,
        )

        if not path:
            return SaveStatus.CANCELLED  # Nothing to do

        status = self.__projectManager.saveAs(path)

        if status == SaveStatus.FAILED:
            slicer.util.errorDisplay(
                "An error occurred while saving the project. Please check the following:\n\n"
                + "1. Ensure that there is sufficient disk space available.\n"
                + "2. Verify that you have the necessary file writing permissions.\n\n"
                + "For further details, please consult the GeoSlicer log file. If the problem persists, consider reaching out to support.",
                "Failed to save project",
            )

            failedProjectpath = Path(path)
            if failedProjectpath.exists():
                shutil.rmtree(failedProjectpath, ignore_errors=True)

        return status

    def onCloseScene(self):
        """Handle close scene event"""

        def wrapper(save=False):
            if save:
                status = self.saveScene()
                if status != SaveStatus.SUCCEED:
                    # saveScene handles possible errors and warns the user
                    return

                if status == SaveStatus.IN_PROGRESS:
                    logging.debug("Unexpected state from the saving process.")
                    return

            self.__projectManager.close()
            updateWindowTitle(versionString=getApplicationVersion())

        mainWindow = slicer.modules.AppContextInstance.mainWindow
        isModified = mainWindow.isWindowModified()
        if not isModified:
            wrapper(save=False)
            return

        messageBox = qt.QMessageBox(mainWindow)
        messageBox.setWindowTitle("Close scene")
        messageBox.setIcon(messageBox.Warning)
        messageBox.setText("Save the changes before closing the scene?")
        saveButton = messageBox.addButton("&Save and Close", qt.QMessageBox.AcceptRole)
        dismissButton = messageBox.addButton("Close &without Saving", qt.QMessageBox.RejectRole)
        cancelButton = messageBox.addButton("&Cancel", qt.QMessageBox.ResetRole)
        messageBox.exec_()

        if messageBox.clickedButton() == cancelButton:
            return

        shouldSave = messageBox.clickedButton() == saveButton
        wrapper(save=shouldSave)

    def __beginSceneClosing(self, *args):
        """Handle the beginning of the scene closing process"""

        selectedModule = slicer.util.moduleSelector().selectedModule

        # Switch to another module so exit() gets called for the current module
        # and then switch back to the original module and restore layout
        layout = slicer.app.layoutManager().layout
        slicer.util.selectModule(selectedModule)
        slicer.app.layoutManager().setLayout(layout)

    def __endSceneClosing(self, *args):
        """Handle the end of the scene closing process"""

        customize_3d_view()
        customize_color_maps()

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def __onNodeAdded(self, caller, eventId, callData):
        if isinstance(callData, slicer.vtkMRMLSegmentationDisplayNode):
            display_node = callData
            display_node.SetOpacity(0.50)
            display_node.SetOpacity2DFill(1.00)
            display_node.Visibility2DOutlineOff()
            display_node.SetOpacity2DOutline(0.00)
            display_node.SetOpacity3D(1.00)
        self.__noInterpolate()

        if callData and callData.IsA("vtkMRMLVolumeArchetypeStorageNode"):
            handleCopySuffixOnClonedNodes(callData)

    def __noInterpolate(self, *args):
        for node in slicer.util.getNodes("*").values():
            if node.IsA("vtkMRMLScalarVolumeDisplayNode") or node.IsA("vtkMRMLVectorVolumeDisplayNode"):
                node.SetInterpolate(0)

    def onRecentLoadedActionTriggered(self, sender: qt.QAction, state: bool) -> None:
        fileParameters = sender.property("fileParameters")
        fileType = fileParameters.get("fileType")
        fileName = fileParameters.get("fileName")

        if not fileName:
            return

        status = self.__projectManager.load(fileName)
        if not status:
            slicer.util.errorDisplay(
                "An error occurred while loading the project. Please check the GeoSlicer log file.",
                "Failed to load project",
            )
        self.setupRecentlyLoadedMenu()

    def setupRecentlyLoadedMenu(self) -> None:
        """Method to install project manager load method into the recently loaded project actions."""
        fileMenu = slicer.modules.AppContextInstance.mainWindow.findChild("QMenu", "FileMenu")
        recentMenu = fileMenu.findChild("QMenu", "RecentlyLoadedMenu")

        for action in recentMenu.actions():
            if action.text == "Clear History":
                continue

            try:
                action.triggered.disconnect()
                action.triggered.connect(partial(self.onRecentLoadedActionTriggered, action))
            except Exception as error:
                logging.error(error)

    def __onEndImportEvent(self, *args, **kwargs) -> None:
        # Assure method is called after the file history update from the last project load.
        qt.QTimer.singleShot(10, self.setupRecentlyLoadedMenu)
