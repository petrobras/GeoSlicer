import datetime
from collections import defaultdict
from functools import partial
import os
from pathlib import Path
from __main__ import qt, slicer, ctk, vtk
import shutil
from ltrace.slicer.side_by_side_image_layout import SideBySideImageManager, setupViews
import psutil
import logging
from types import MethodType
import vtk
import logging
import slicer

from ltrace.slicer.lazy import lazy
from ltrace.slicer.helpers import themeIsDark, BlockSignals
from ltrace.slicer.modules_help_menu import ModulesHelpMenu
from ltrace.slicer.project_manager import ProjectManager, BUGFIX_handle_copy_suffix_on_cloned_nodes
from ltrace.slicer.application_observables import ApplicationObservables
from ltrace.slicer.custom_main_window_event_filter import CustomizerEventFilter
from ltrace.slicer.custom_export_to_file import customize_export_to_file
from ltrace.utils.custom_event_filter import CustomEventFilter
from ltrace.slicer_utils import (
    slicer_is_in_developer_mode,
    restartSlicerIn2s,
    get_json_data,
    LTracePluginTest,
    LTracePluginLogic,
    LTracePlugin,
    LTracePluginWidget,
)
from ltrace.slicer.widget.histogram_popup import HistogramPopupWidget
from ltrace.slicer.widget.global_progress_bar import GlobalProgressBar
from ltrace.slicer.color_map_customizer import customize_color_maps
from ltrace.screenshot.Screenshot import ScreenshotWidget
from string import Template

try:
    from ltrace.slicer.tracking.tracking_manager import TrackingManager
except ModuleNotFoundError:
    TrackingManager = None


# This line solve some problems with Geoslicer Restart when mmengine in installed because of a dependence on opencv, instead of opencv-headless, currently used in geoslicer. The problem and some solutions are described in this post: https://forum.qt.io/post/617768
os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)

JSON_DATA = get_json_data()
GEOSLICER_VERSION = JSON_DATA["GEOSLICER_VERSION"]
GEOSLICER_HASH = JSON_DATA["GEOSLICER_HASH"]
GEOSLICER_HASH_DIRTY = JSON_DATA["GEOSLICER_HASH_DIRTY"]
GEOSLICER_BUILD_TIME = datetime.datetime.strptime(JSON_DATA["GEOSLICER_BUILD_TIME"], "%Y-%m-%d %H:%M:%S.%f")
GEOSLICER_DEV_ENVIRONMENT = JSON_DATA["GEOSLICER_DEV_ENVIRONMENT"]
VISIBLE_LTRACE_PLUGINS = JSON_DATA["VISIBLE_LTRACE_PLUGINS"]
CUSTOM_REL_PATHS = JSON_DATA["CUSTOM_REL_PATHS"]

VIEW_2D_TEMPLATE = Template(
    """
<item splitSize="$size">
    <view class="vtkMRMLSliceNode" singletontag="$tag">
        <property name="orientation" action="default">$orientation</property>
        <property name="viewlabel" action="default">$label</property>
        <property name="viewcolor" action="default">$color</property>
    </view>
</item>"""
)

VIEW_2D_TEMPLATE_WITH_GROUP = Template(
    """
<item splitSize="$size">
    <view class="vtkMRMLSliceNode" singletontag="$tag">
        <property name="orientation" action="default">$orientation</property>
        <property name="viewlabel" action="default">$label</property>
        <property name="viewcolor" action="default">$color</property>
        <property name="viewgroup" action="default">$group</property>
    </view>
</item>"""
)

VIEW_3D_XML = """
<item splitSize="500">
    <view class="vtkMRMLViewNode" singletontag="1">
        <property name="viewlabel" action="default">1</property>
    </view>
</item>"""

LAYOUT_TEMPLATE = Template(
    """
<layout type="horizontal" split="true">
    $view1
    $view2
</layout>"""
)


class Customizer(LTracePlugin):
    SETTING_KEY = "Customizer"
    RESOURCES_PATH = Path(__file__).absolute().with_name("Resources")
    CARBONATE_CT_ICON_PATH = RESOURCES_PATH / "Carbonate-CT.png"
    SANDSTONE_CT_ICON_PATH = RESOURCES_PATH / "Sandstone-CT.png"
    GRAINS_ICON_PATH = RESOURCES_PATH / "grains_menor.png"
    PORES_ICON_PATH = RESOURCES_PATH / "Pores_menor.png"
    MICROTOM_ICON_PATH = RESOURCES_PATH / "MicroTom_menor.png"
    RED_3D_CUSTOM_LAYOUT_ICON_PATH = RESOURCES_PATH / "Red3dCustomLayoutIcon.png"
    YELLOW_3D_CUSTOM_LAYOUT_ICON_PATH = RESOURCES_PATH / "Yellow3dCustomLayoutIcon.png"
    GREEN_3D_CUSTOM_LAYOUT_ICON_PATH = RESOURCES_PATH / "Green3dCustomLayoutIcon.png"
    SIDE_BY_SIDE_IMAGE_LAYOUT_ICON = RESOURCES_PATH / "SideBySideImageIcon.png"
    SIDE_BY_SIDE_SEGMENTATION_LAYOUT_ICON = RESOURCES_PATH / "SideBySideSegmentationIcon.png"
    GEOSLICER_LOGO_ICON_PATH = RESOURCES_PATH / "GeoSlicer-logo.png"
    BUG_REPORT_ICON_PATH = RESOURCES_PATH / "BugReport.png"
    LOAD_SCENE_ICON_PATH = RESOURCES_PATH / "LoadSceneIcon.png"
    UNDO_ICON_PATH = RESOURCES_PATH / "UndoIcon.png"
    REDO_ICON_PATH = RESOURCES_PATH / "RedoIcon.png"
    APPLY_ICON_PATH = RESOURCES_PATH / "ApplyIcon.png"
    RESET_ICON_PATH = RESOURCES_PATH / "ResetIcon.png"
    CANCEL_ICON_PATH = RESOURCES_PATH / "CancelIcon.png"
    SAVE_ICON_PATH = RESOURCES_PATH / "SaveIcon.png"
    LOAD_ICON_PATH = RESOURCES_PATH / "LoadIcon.png"
    MOVE_UP_ICON_PATH = RESOURCES_PATH / "MoveUpIcon.png"
    MOVE_DOWN_ICON_PATH = RESOURCES_PATH / "MoveDownIcon.png"
    ADD_ICON_PATH = RESOURCES_PATH / "AddIcon.png"
    EDIT_ICON_PATH = RESOURCES_PATH / "EditIcon.png"
    EDIT_ADD_ICON_PATH = RESOURCES_PATH / "EditAddIcon.png"
    FIT_ICON_PATH = RESOURCES_PATH / "FitIcon.png"
    FIT_REAL_ASPECT_RATIO_ICON_PATH = RESOURCES_PATH / "FitRealAspectRatioIcon.png"
    DELETE_ICON_PATH = RESOURCES_PATH / "DeleteIcon.png"
    CLONE_ICON_PATH = RESOURCES_PATH / "CloneIcon.png"
    RUN_ICON_PATH = RESOURCES_PATH / "RunIcon.png"
    STOP_ICON_PATH = RESOURCES_PATH / "StopIcon.png"
    EMPTY_CIRCLE_ICON_PATH = RESOURCES_PATH / "EmptyCircleIcon.png"
    FILLED_CIRCLE_ICON_PATH = RESOURCES_PATH / "FilledCircleIcon.png"
    CHECK_CIRCLE_ICON_PATH = RESOURCES_PATH / "GreenCheckCircle.png"
    ERROR_CIRCLE_ICON_PATH = RESOURCES_PATH / "RedBangCircle.png"
    OPEN_EYE_ICON_PATH = RESOURCES_PATH / "OpenEye.png"
    CLOSED_EYE_ICON_PATH = RESOURCES_PATH / "ClosedEye.png"
    SAVE_AS_ICON_PATH = RESOURCES_PATH / "SaveAsIcon.png"
    FOLDER_ICON_PATH = RESOURCES_PATH / "ProjectIcon.ico"
    LTRACE_ICON_PATH = RESOURCES_PATH / "LTraceIcon.png"
    PUSH_PIN_IN_ICON_PATH = RESOURCES_PATH / "PushPinIn.png"
    PUSH_PIN_OUT_ICON_PATH = RESOURCES_PATH / "PushPinOut.png"
    SCREENSHOT_ICON_PATH = RESOURCES_PATH / "ScreenshotIcon.png"
    ANNOTATION_DISTANCE_ICON_PATH = RESOURCES_PATH / "AnnotationDistance.png"
    HISTOGRAM_POPUP_ICON_PATH = RESOURCES_PATH / "HistNoColor.png"
    JOBMONITOR_ICON_PATH = RESOURCES_PATH / "JobMonitor.png"
    ACCOUNTS_ICON_PATH = RESOURCES_PATH / "Accounts.png"
    EXPLORER_ICON_PATH = RESOURCES_PATH / "Explorer.png"

    GEOSLICER_MANUAL_PATH = RESOURCES_PATH / "manual" / "index.html"

    IMAGELOG_ICON_PATH = RESOURCES_PATH / "../ImageLogEnv/Resources/Icons/ImageLogEnv.png"

    SIDE_BY_SIDE_IMAGE_LAYOUT_ID = 200
    SIDE_BY_SIDE_SEGMENTATION_LAYOUT_ID = 201
    SIDE_BY_SIDE_IMAGE_GROUP = 70
    SIDE_BY_SIDE_SEGMENTATION_GROUP = 71

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Customizer"
        self.parent.categories = ["Customizer"]
        self.parent.dependencies = []
        self.parent.hidden = True
        self.parent.contributors = []
        self.parent.helpText = ""
        self.parent.acknowledgementText = ""
        self.ltraceBugReportDialog = None
        self.__project_manager = ProjectManager(folder_icon_path=self.FOLDER_ICON_PATH)
        self.__layout_menu = None

        self.popup_widget = None

        if not slicer.app.commandOptions().noMainWindow:
            self.logic = CustomizerLogic()
            slicer.app.startupCompleted.connect(self.on_load_finished)

        self.mainWindowCache = None
        self.originalMainWindow = slicer.util.mainWindow
        slicer.util.mainWindow = self.cachedMainWindow
        self.__trackingManager = TrackingManager() if TrackingManager is not None else None

    def cachedMainWindow(self):
        self.mainWindowCache = self.mainWindowCache or self.originalMainWindow()
        return self.mainWindowCache

    def register_all_effects(self):
        slicer.modules.BoundaryRemovalEffectInstance.registerEditorEffect()
        slicer.modules.ColorThresholdEffectInstance.registerEditorEffect()
        slicer.modules.ConnectivityEffectInstance.registerEditorEffect()
        slicer.modules.CustomizedSmoothingEffectInstance.registerEditorEffect()
        slicer.modules.DepthRangeSegmenterEffectInstance.registerEditorEffect()
        slicer.modules.ExpandSegmentsEffectInstance.registerEditorEffect()
        slicer.modules.MaskVolumeEffectInstance.registerEditorEffect()
        slicer.modules.MultiThresholdEffectInstance.registerEditorEffect()
        slicer.modules.SampleSegmentationEffectInstance.registerEditorEffect()

    def on_load_finished(self):
        slicer.app.setRenderPaused(True)
        self.set_style()
        self.migrate_settings()
        if self.needs_to_set_modules_path():
            self.configure_environment_first_start()
        else:  # This runs every start after configuring the environment
            self.register_all_effects()
            self.pre_load_environments()

        self.configure_environment_every_start()
        slicer.app.setRenderPaused(False)
        slicer.app.startupCompleted.disconnect(self.on_load_finished)
        qt.QTimer.singleShot(500, lambda: ApplicationObservables().applicationLoadFinished.emit())
        if self.__trackingManager:
            qt.QTimer.singleShot(550, lambda: self.__trackingManager.installTrackers())

    def configure_environment_first_start(self):
        self.set_paths()
        self.set_home_module()
        self.set_favorite_modules()
        self.set_console_log_level()
        self.set_gpu_rendering()
        try:
            self.set_git_petro()
        except:
            logging.warning("Petrobras GeoSlicer plugins not installed")
        restartSlicerIn2s()

    def set_git_petro(self):
        import getpass

        if not slicer_is_in_developer_mode():
            from ltrace.slicer.helpers import install_git_module

            install_git_module("https://git.ep.petrobras.com.br/DRP/geoslicer_plugins.git")

    def test_gpu_cuda(self):
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

    def configure_environment_every_start(self):
        self.set_default_segmentation_terminology()
        self.startCloseSceneObserverHandler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.StartCloseEvent, self.startCloseScene
        )
        self.endCloseSceneObserverHandler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.EndCloseEvent, self.endCloseScene
        )

        self.nodeAddedObserverHandler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.NodeAddedEvent, self.__on_node_added
        )

        self.customize_data_probe_collapsible_button()
        self.customize_status_bar()
        self.hide_ltrace_hidden_category()

        self.enable_subject_hierarchy_options()
        self.customize_3d_view()
        # self.replace_slicer_logo()
        self.replaceOrientationNames()
        self.replace_color_names()
        self.redSliceAnd3DCustomLayout()
        self.yellowSliceAnd3DCustomLayout()
        self.greenSliceAnd3DCustomLayout()
        self.sideBySideImageLayout()
        self.sideBySideSegmentationLayout()
        self.customizeCloseApplicationEvent()
        self.setup_extension_manager()
        self.setup_pyqtgraph_config()
        self.test_gpu_cuda()
        # Hide Data Store module
        slicer.util.mainWindow().moduleSelector().modulesMenu().removeModule("DataStore")

        if not slicer_is_in_developer_mode():
            self.hide_unnecessary_modules()

        # Slicer first loads all plugins then runs the qt event loop.
        # By scheduling a timer to as soon as the event loop is available, we make sure all plugins are loaded.
        qt.QTimer.singleShot(0, self.configure_environment_after_all_plugins_are_loaded)
        customize_color_maps()

        self.customize_module_help()
        customize_export_to_file()

    @staticmethod
    def migrate_settings():
        # Transition from legacy settings to unified settings
        # The code below can be removed in a later version, after all users have migrated to unified settings.
        legacy_settings = qt.QSettings("LTrace", "Slicer")
        settings = slicer.app.settings()
        for key in legacy_settings.allKeys():
            settings.setValue(key, legacy_settings.value(key))
            legacy_settings.remove(key)

    def initialize_reload_widget_cache(self):
        slicer.reloadingWidget = {}

    def pre_load_environments(self):
        """The method widgetRepresentation returns the related module widget object, but if the object doesn't exists, it creates and store the object information for further use.
        This pre-loading process avoid the user experience problems related to application freezing for a brief time after the user selects an environments for the first time.
        """
        slicer.modules.coreenv.widgetRepresentation()
        slicer.modules.thinsectionenv.widgetRepresentation()
        slicer.modules.imagelogenv.widgetRepresentation()
        slicer.modules.microctenv.widgetRepresentation()

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def __on_node_added(self, caller, eventId, callData):
        if isinstance(callData, slicer.vtkMRMLSegmentationDisplayNode):
            display_node = callData
            display_node.SetOpacity(0.50)
            display_node.SetOpacity2DFill(1.00)
            display_node.Visibility2DOutlineOff()
            display_node.SetOpacity2DOutline(0.00)
            display_node.SetOpacity3D(1.00)
        self.noInterpolate()

        if callData and callData.IsA("vtkMRMLVolumeArchetypeStorageNode"):
            BUGFIX_handle_copy_suffix_on_cloned_nodes(callData)

    # disable interpolation of the volumes by default
    def noInterpolate(self, *args):
        for node in slicer.util.getNodes("*").values():
            if node.IsA("vtkMRMLScalarVolumeDisplayNode") or node.IsA("vtkMRMLVectorVolumeDisplayNode"):
                node.SetInterpolate(0)

    def startCloseScene(self, *args):
        selectedModule = slicer.util.moduleSelector().selectedModule

        if selectedModule == "SegmentInspector":
            return

        # Switch to another module so exit() gets called for the current module
        # and then switch back to the original module and restore layout
        layout = slicer.app.layoutManager().layout
        slicer.util.selectModule("WelcomeGeoSlicer")
        slicer.util.selectModule(selectedModule)
        slicer.app.layoutManager().setLayout(layout)

    def endCloseScene(self, *args):
        if slicer.util.moduleSelector().selectedModule == "SegmentInspector":
            return

        self.customize_3d_view()
        customize_color_maps()

    def configure_environment_after_all_plugins_are_loaded(self):
        # TODO(PL-1448): Enhance 'About' window version information
        slicer.app.applicationVersion = self.__get_application_version()
        self.__update_window_title()
        self.customize_volume_rendering_module()
        self.customize_menu()
        self.customize_toolbar()
        self.customize_panel_dock_widget()
        self.customize_data_probe_info()
        self.initialize_reload_widget_cache()

        self.__project_manager.setup()
        self.__project_manager.projectChangedSignal.connect(self.__update_window_title)

        lazy.register_eye_event()
        self.__project_manager.projectChangedSignal.connect(lazy.register_eye_event)

        # Expand scene folder
        folder_tree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        scene_id = folder_tree.GetSceneItemID()
        dataWidget = slicer.modules.data.widgetRepresentation()
        shTreeView = slicer.util.findChild(dataWidget, name="SubjectHierarchyTreeView")
        shTreeView.expandItem(scene_id)

    def customize_data_probe_collapsible_button(self):
        dataProbeWidget = slicer.util.mainWindow().findChild(ctk.ctkCollapsibleButton, "DataProbeCollapsibleWidget")
        dataProbeWidget.collapsed = True
        dataProbeWidget.minimumWidth = 450

    def customize_data_probe_info(self):
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

    def customize_panel_dock_widget(self):
        panelDockWidget = slicer.util.mainWindow().findChild(qt.QWidget, "PanelDockWidget")
        # Setting the left margin so that some contents are not directly glued to the left side of the screen
        panelDockWidget.setContentsMargins(5, 0, 0, 0)

    def customize_menu(self):
        fileMenu = slicer.util.mainWindow().findChild("QMenu", "FileMenu")
        helpMenu = slicer.util.mainWindow().findChild("QMenu", "HelpMenu")
        mainToolBar = slicer.util.mainWindow().findChild(qt.QToolBar, "MainToolBar")
        dialogToolBar = slicer.util.mainWindow().findChild(qt.QToolBar, "DialogToolBar")

        for action in fileMenu.actions():
            if action.text == "DICOM":
                action.setVisible(False)
            elif action.text == "Recently Loaded" and not slicer_is_in_developer_mode():
                action.setVisible(False)
            elif action.text == "&Add Data":
                action.setText("Advanced Add Data")
            elif action.text == "Save Data":
                action.setText("Save Scene")
                saveDataAction = action  # Saving action to use later

        for action in mainToolBar.actions():
            if action.text == "Load Data":  # This is the Add Data action
                action.setVisible(False)

        for action in helpMenu.actions():
            if action.text == "Browse tutorials":
                action.setVisible(False)
            elif action.text == "Slicer Publications":
                action.setVisible(False)
            elif action.text == "Visual Blog":
                action.setVisible(False)
            elif action.text == "Report a bug":
                action.setVisible(False)

        self.dockedDataAction = self.__createDocketDataAction()
        dialogToolBar.addAction(self.dockedDataAction)

        self.ltraceBugReportAction = qt.QAction("Generate a bug report")
        self.ltraceBugReportAction.setIcon(qt.QIcon(str(self.BUG_REPORT_ICON_PATH)))
        self.ltraceBugReportAction.triggered.connect(self.ltraceBugReport)
        helpMenu.addAction(self.ltraceBugReportAction)
        dialogToolBar.addAction(self.ltraceBugReportAction)

        self.__ltraceModulesHelpMenu = ModulesHelpMenu(ltrace_icon_path=self.LTRACE_ICON_PATH)
        helpMenu.addMenu(self.__ltraceModulesHelpMenu)

        self.manual_help_action = qt.QAction("GeoSlicer manual")
        self.manual_help_action.setIcon(qt.QIcon(str(self.GEOSLICER_LOGO_ICON_PATH)))
        self.manual_help_action.triggered.connect(self.open_geoslicer_manual)
        helpMenu.addAction(self.manual_help_action)

        # Load scene action
        self.loadSceneAction = qt.QAction("Load Scene")
        self.loadSceneAction.setIcon(qt.QIcon(str(self.LOAD_SCENE_ICON_PATH)))
        self.loadSceneAction.triggered.connect(self.load_scene)
        self.loadSceneAction.setToolTip("Load project/scene .mrml file")
        fileMenu.insertAction(saveDataAction, self.loadSceneAction)
        mainToolBar.insertAction(saveDataAction, self.loadSceneAction)

        # Save scene
        saveDataAction.triggered.disconnect()
        saveDataAction.triggered.connect(self._saveScene)
        saveDataAction.setToolTip("Save the current and modified project/scene .mrml file")

        # Save scene As action
        self.saveSceneAsAction = qt.QAction("Save Scene As")
        self.saveSceneAsAction.setShortcut(qt.QKeySequence("Ctrl+Shift+S"))
        self.saveSceneAsAction.setIcon(qt.QIcon(str(self.SAVE_AS_ICON_PATH)))
        self.saveSceneAsAction.triggered.connect(self._saveSceneAs)
        self.saveSceneAsAction.setToolTip("Save project/scene as...")

        self.closeSceneAction = self.__searchAction(menu=fileMenu, text="Close Scene")
        self.closeSceneAction.triggered.disconnect()  # Disconnect previous callback
        self.closeSceneAction.triggered.connect(self._onCloseScene)

        recentlyOpenedAction = fileMenu.actions()[4]
        fileMenu.insertAction(recentlyOpenedAction, self.saveSceneAsAction)
        mainToolBar.insertAction(None, self.saveSceneAsAction)

        self.ltraceMonitorAction = qt.QAction("Open Job Monitor")
        self.ltraceMonitorAction.setIcon(qt.QIcon(str(self.JOBMONITOR_ICON_PATH)))
        self.ltraceMonitorAction.triggered.connect(self.ltraceMonitor)
        dialogToolBar.addAction(self.ltraceMonitorAction)

        self.manageAccountsAction = qt.QAction("Manage Accounts")
        self.manageAccountsAction.setIcon(qt.QIcon(str(self.ACCOUNTS_ICON_PATH)))
        self.manageAccountsAction.triggered.connect(self.manageAccounts)
        dialogToolBar.addAction(self.manageAccountsAction)

        # Memory used
        dialogToolBar.setStyleSheet(
            "QToolBar::separator {background-color:#505050; width:1px; margin-left:4px; margin-right:4px;}"
        )
        dialogToolBar.addSeparator()
        self.memoryUsedLabel = qt.QLabel("  Memory used:")
        self.memoryUsedProgressBar = qt.QProgressBar()
        self.memoryUsedProgressBar.setFixedWidth(100)
        dialogToolBar.addWidget(self.memoryUsedLabel)
        dialogToolBar.addWidget(self.memoryUsedProgressBar)
        self.memoryUsedTimer = qt.QTimer()
        self.memoryUsedTimer.setInterval(1000)
        self.memoryUsedTimer.connect("timeout()", self.updateMemoryUsedProgressBar)
        self.memoryUsedTimer.start()

    @staticmethod
    def setup_pyqtgraph_config():
        import pyqtgraph as pg

        pg.setConfigOption("background", "w")
        pg.setConfigOption("foreground", "k")
        pg.setConfigOptions(antialias=True)

        def warning_wrap(func):
            def wrapped(*args, **kwargs):
                print(
                    "WARNING: setting up pyqtgraph configurations globally may affect other modules.\n"
                    "Customizer.setup_pyqtgraph_config() configures pyqtgraph during initialization."
                )
                return func(*args, **kwargs)

            return wrapped

        pg.setConfigOption = warning_wrap(pg.setConfigOption)
        pg.setConfigOptions = warning_wrap(pg.setConfigOptions)

    def _saveScene(self):
        import shutil

        """Save current scene/project

        Returns:
            bool: True if scene was saved successfully, otherwise returns False
        """
        url = slicer.mrmlScene.GetURL()
        if url == "":
            return self._saveSceneAs()

        if not self.__project_manager.save(url):
            qt.QMessageBox.critical(
                slicer.util.mainWindow(),
                "Failed to save project",
                "A problem occurred during project's saving process. Please, check Geoslicer log file for more information.",
            )

        return True

    def _saveSceneAs(self):
        """Shows 'save as' dialog to user"""
        return self.__onSaveButtonClicked()

    def __onSaveButtonClicked(self):
        """Handles save button clicked on save scene as dialog"""
        # Save directory
        path = qt.QFileDialog.getSaveFileName(
            slicer.util.mainWindow(),
            "Save project",
            slicer.app.defaultScenePath,
            "GeoSlicer project folder (*)",
            "",
            qt.QFileDialog.DontConfirmOverwrite,
        )
        if not path:
            return
        try:
            self.__project_manager.save_as(path)

        except Exception as error:
            qt.QMessageBox.critical(
                slicer.util.mainWindow(),
                "Failed to save project",
                "A problem occurred during project's saving process. Please, check Geoslicer log file for more information.",
            )

    def saveSceneDirectorySelected(self, directoryPath):
        self.directoryButton.text = directoryPath

    def updateMemoryUsedProgressBar(self):
        self.memoryUsedProgressBar.setValue(psutil.virtual_memory().percent)
        used_gb = psutil.virtual_memory().used / (1024**3)
        total_gb = psutil.virtual_memory().total / (1024**3)
        self.memoryUsedProgressBar.setToolTip(
            "Used: " + "{:.2f}".format(used_gb) + " GiB\nTotal: " + "{:.2f}".format(total_gb) + " GiB"
        )

    def load_scene(self):
        fileDialog = qt.QFileDialog(
            slicer.util.mainWindow(),
            "Load a scene",
            "",
            "GeoSlicer scene file (*.mrml)",
        )
        if fileDialog.exec():
            paths = fileDialog.selectedFiles()
            projectFilePath = paths[0]
            self.__project_manager.load(projectFilePath)

    def ltraceMonitor(self):
        slicer.util.selectModule("JobMonitor")
        # mainWindow = slicer.util.mainWindow()

        # jobsWidget = slicer.modules.jobmonitor.widgetRepresentation()
        # # jobsWidget = slicer.modules.RemoteServiceInstance.getMonitorScreen()

        # taskMonitorDockWidget = qt.QDockWidget("Task Monitor", mainWindow)
        # taskMonitorDockWidget.setFeatures(
        #     qt.QDockWidget.DockWidgetClosable + qt.QDockWidget.DockWidgetMovable + qt.QDockWidget.DockWidgetFloatable
        # )
        # taskMonitorDockWidget.setWidget(jobsWidget)

        # mainWindow.addDockWidget(qt.Qt.RightDockWidgetArea, taskMonitorDockWidget)

    def manageAccounts(self):
        slicer.modules.RemoteServiceInstance.cli.initiateConnectionDialog(keepDialogOpen=True)

    def ltraceBugReport(self):
        if not self.ltraceBugReportDialog:
            self.ltraceBugReportDialog = qt.QDialog(slicer.util.mainWindow())
            self.ltraceBugReportDialog.setWindowTitle("Generate a bug report")
            self.ltraceBugReportDialog.setMinimumSize(600, 400)
            layout = qt.QFormLayout(self.ltraceBugReportDialog)
            layout.setLabelAlignment(qt.Qt.AlignRight)

            layout.addRow("Please describe the problem in the area bellow:", None)
            self.errorDescriptionArea = qt.QPlainTextEdit()
            layout.addRow(self.errorDescriptionArea)
            layout.addRow(" ", None)

            self.ltraceBugReportDirectoryButton = ctk.ctkDirectoryButton()
            self.ltraceBugReportDirectoryButton.caption = "Select a directory to save the report"
            layout.addRow("Report destination directory:", None)
            layout.addRow(self.ltraceBugReportDirectoryButton)
            layout.addRow(" ", None)

            buttonsLayout = qt.QHBoxLayout()
            generateButton = qt.QPushButton("Generate report")
            generateButton.setFixedHeight(40)
            buttonsLayout.addWidget(generateButton)
            cancelButton = qt.QPushButton("Cancel")
            cancelButton.setFixedHeight(40)
            buttonsLayout.addWidget(cancelButton)
            layout.addRow(buttonsLayout)

            generateButton.clicked.connect(self.ltraceBugReportGenerate)
            cancelButton.connect("clicked()", self.ltraceBugReportDialog.hide)

        self.ltraceBugReportDialog.show()

    def ltraceBugReportGenerate(self):
        reportPath = Path(self.ltraceBugReportDirectoryButton.directory).absolute() / "GeoSlicerBugReport"
        reportPath.mkdir(parents=True, exist_ok=True)

        geoslicerLogFiles = list(slicer.app.recentLogFiles())
        trackingLogFiles = self.__trackingManager.getRecentLogs() if self.__trackingManager else []

        for file in geoslicerLogFiles + trackingLogFiles:
            try:
                shutil.copy2(file, str(reportPath))
            except FileNotFoundError:
                pass

        Path(reportPath / "bug_description.txt").write_text(self.errorDescriptionArea.toPlainText())
        shutil.make_archive(reportPath, "zip", reportPath)

        try:
            shutil.rmtree(str(reportPath))
        except OSError as e:
            # If for some reason can't delete the directory
            pass

        self.errorDescriptionArea.setPlainText("")
        self.ltraceBugReportDialog.hide()

    def open_geoslicer_manual(self):
        qt.QDesktopServices.openUrl(qt.QUrl("file:///" + str(self.GEOSLICER_MANUAL_PATH)))

    def customize_volume_rendering_module(self):
        volumeRenderingModule = slicer.modules.volumerendering.widgetRepresentation()
        qSlicerIconComboBox = volumeRenderingModule.findChild(qt.QObject, "PresetComboBox").children()[2].children()[-1]
        qSlicerIconComboBox.setItemText(0, "CT Carbonate")
        qSlicerIconComboBox.setItemIcon(0, qt.QIcon(str(self.CARBONATE_CT_ICON_PATH)))
        qSlicerIconComboBox.setItemText(1, "CT Sandstone")
        qSlicerIconComboBox.setItemIcon(1, qt.QIcon(str(self.SANDSTONE_CT_ICON_PATH)))
        qSlicerIconComboBox.setItemText(2, "Grains")
        qSlicerIconComboBox.setItemIcon(2, qt.QIcon(str(self.GRAINS_ICON_PATH)))
        qSlicerIconComboBox.setItemText(3, "Pores")
        qSlicerIconComboBox.setItemIcon(3, qt.QIcon(str(self.PORES_ICON_PATH)))
        qSlicerIconComboBox.setItemText(4, "MicroTom")
        qSlicerIconComboBox.setItemIcon(4, qt.QIcon(str(self.MICROTOM_ICON_PATH)))

        # Link all volumes display properties
        layout = volumeRenderingModule.findChild(qt.QObject, "DisplayCollapsibleButton").children()[0]
        button = qt.QPushButton("Link all volumes")
        button.setToolTip("Link all volumes rendering display properties")
        button.setFixedHeight(40)
        button.clicked.disconnect()
        button.clicked.connect(lambda: self.linkAllVolumesRenderingDisplayProperties(volumeRenderingModule))
        layout.addWidget(button)

        # Show/hide all volumes
        layout = volumeRenderingModule.findChild(qt.QObject, "DisplayCollapsibleButton").children()[0]
        button = qt.QPushButton("Show all volumes")
        button.setToolTip("Show all volumes on 3D scene")
        button.setFixedHeight(40)
        button.clicked.disconnect()
        button.clicked.connect(lambda: self.showHideAllVolumes(button))
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
        self.eventFilter = CustomEventFilter(self.onPresetComboBoxClicked, qSlicerIconComboBox)
        self.eventFilter.install()

    def onPresetComboBoxClicked(self, object, event):
        if type(event) == qt.QMouseEvent:
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

    def linkAllVolumesRenderingDisplayProperties(self, volume_rendering_module):
        from Multicore import MulticoreLogic

        volumeNodeComboBox = volume_rendering_module.findChild(qt.QObject, "VolumeNodeComboBox")
        currentNode = volumeNodeComboBox.currentNode()
        volumeRenderingLogic = slicer.modules.volumerendering.logic()
        currentDisplayNode = volumeRenderingLogic.CreateDefaultVolumeRenderingNodes(currentNode)
        volumeRenderingLogic = slicer.modules.volumerendering.logic()
        multicoreLogic = MulticoreLogic()
        volumes = multicoreLogic.getVolumes()
        for volume in volumes:
            displayNode = volumeRenderingLogic.CreateDefaultVolumeRenderingNodes(volume)
            displayNode.SetAndObserveVolumePropertyNodeID(currentDisplayNode.GetVolumePropertyNodeID())

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

    def replace_color_names(self):
        colorNode = slicer.util.getNode("GenericAnatomyColors")
        colorNode.SetName("RockColors")

    def customize_3d_view(self):
        viewWidget = slicer.app.layoutManager().threeDWidget(0)
        viewNode = viewWidget.mrmlViewNode()
        if themeIsDark():
            viewNode.SetBackgroundColor(0, 0, 0)
            viewNode.SetBackgroundColor2(0, 0, 0)
        # Hiding the purple 3D boundary box
        viewNode.SetBoxVisible(False)

        viewNode.SetAxisLabelsVisible(False)
        viewNode.SetOrientationMarkerType(slicer.vtkMRMLViewNode.OrientationMarkerTypeAxes)

        orientationMenu = viewWidget.findChild(qt.QMenu, "orientationMarkerMenu")
        for action in orientationMenu.actions():
            if action.text in ["Cube", "Human"]:
                orientationMenu.removeAction(action)

    def replace_slicer_logo(self):
        dockWidgetContents = slicer.util.mainWindow().findChild(qt.QObject, "dockWidgetContents")
        slicerLogoLabel = dockWidgetContents.findChild(qt.QLabel, "LogoLabel")
        dockWidgetContents.layout().setAlignment(slicerLogoLabel, qt.Qt.AlignCenter)
        slicerLogoLabel.setPixmap(qt.QPixmap(self.RESOURCES_PATH.joinpath("LTrace-logo.png").as_posix()))

        icon = qt.QIcon(self.GEOSLICER_LOGO_ICON_PATH)
        slicer.util.mainWindow().setWindowIcon(icon)

    def customize_status_bar(self):
        statusBar = slicer.util.mainWindow().findChild(qt.QObject, "StatusBar")
        statusBar.setVisible(True)

        statusBar.findChild(qt.QToolButton).setVisible(False)

        progressBar = GlobalProgressBar.instance()
        progressBar.setObjectName("GlobalProgressBar")

        statusBar.addPermanentWidget(progressBar)

    def enable_subject_hierarchy_options(self):
        slicer.app.userSettings().setValue("SubjectHierarchy/ResetFieldOfViewOnShowVolume", True)
        slicer.app.userSettings().setValue("SubjectHierarchy/ResetViewOrientationOnShowVolume", False)

    def __get_application_version(self):
        if GEOSLICER_VERSION is not None:
            major, minor, revision = GEOSLICER_VERSION

            if revision:
                version_string = "{}.{}.{}".format(major, minor, revision)
            else:
                version_string = "{}.{}".format(major, minor)
        else:
            hash_ = GEOSLICER_HASH[:8] + "*" if GEOSLICER_HASH_DIRTY else ""
            date = GEOSLICER_BUILD_TIME.strftime("%Y-%m-%d")
            version_string = "{} {}".format(hash_, date)

        return version_string

    def __update_window_title(self):
        """Updates main window's title according to the current project"""

        projectString = "Untitled project"
        projectURL = slicer.mrmlScene.GetURL()
        if projectURL != "":
            projectString = os.path.dirname(projectURL)

        version_string = self.__get_application_version()
        window_title = "GeoSlicer {} - {} [*]".format(version_string, projectString)
        slicer.util.mainWindow().setWindowTitle(window_title)

    def hide_ltrace_hidden_category(self):
        module_selector = slicer.util.mainWindow().moduleSelector().modulesMenu()
        module_selector.removeCategory("LTRACE_HIDDEN_EXTRAS")

    def hide_unnecessary_modules(self):
        slicer_basic_modules = [
            "Annotations",
            "Data",
            "Markups",
            "Models",
            "SceneViews",
            "SegmentEditor",
            "Segmentations",
            "SubjectHierarchy",
            "ViewControllers",
            "VolumeRendering",
            "Volumes",
        ]

        slicer_module_whitelist = [
            "Tables",
            "CropVolume",
            "SegmentMesher",
            "RawImageGuess",
            "LandmarkRegistration",
            "GradientAnisotropicDiffusion",
            "CurvatureAnisotropicDiffusion",
            "GaussianBlurImageFilter",
            "MedianImageFilter",
            "VectorToScalarVolume",
            "ScreenCapture",
            "SimpleFilters",
            "SegmentStatistics",
            "MONAILabel",
            "MONAILabelReviewer",
        ]

        ltrace_module_whitelist = VISIBLE_LTRACE_PLUGINS
        ltrace_module_whitelist.extend(slicer_basic_modules)
        ltrace_module_whitelist.extend(slicer_module_whitelist)

        category_use_count = defaultdict(lambda: 0)
        module_selector = slicer.util.mainWindow().moduleSelector().modulesMenu()

        for module_name in dir(slicer.moduleNames):
            if module_name.startswith("_"):
                # python attribute
                continue

            module = getattr(slicer.modules, module_name.lower(), None)
            if module is None:
                # Module is disabled
                continue

            if module_name not in slicer_basic_modules:
                # ignore basic modules to avoid overcrowding menu
                for category in module.categories:
                    category_use_count[category] += 1
                    # parent category must be counted also
                    category_split = category.split(".")
                    if len(category_split) > 1:
                        category_use_count[category_split[0]] += 1

            if module.name not in ltrace_module_whitelist:
                module_selector.removeModule(module)
                for category in module.categories:
                    category_use_count[category] -= 1
                    # parent category must be counted also
                    category_split = category.split(".")
                    if len(category_split) > 1:
                        category_use_count[category_split[0]] -= 1

        for category, count in category_use_count.items():
            if count == 0:
                module_selector.removeCategory(category)

    def needs_to_set_modules_path(self):
        user_settings = slicer.app.userSettings()
        if user_settings.value("Modules/HomeModule") != "WelcomeGeoSlicer":
            return True

        revision_settings = slicer.app.revisionUserSettings()
        current_saved_paths = set(os.path.abspath(i) for i in revision_settings.value("Modules/AdditionalPaths"))
        ltrace_paths = set(os.path.abspath(i) for i in self.get_module_paths())

        return not ltrace_paths.issubset(current_saved_paths)

    def set_paths(self):
        required_paths = self.get_module_paths()

        revision_settings = slicer.app.revisionUserSettings()
        revision_settings.setValue("Modules/AdditionalPaths", required_paths)

        revision_settings.beginWriteArray("PYTHONPATH", len(required_paths))
        for index, required_path in enumerate(required_paths):
            revision_settings.setArrayIndex(index)
            revision_settings.setValue("path", required_path)

        revision_settings.endArray()
        Path(slicer.app.toSlicerHomeAbsolutePath("LTrace/saved_scenes")).mkdir(parents=True, exist_ok=True)
        slicer.app.defaultScenePath = slicer.app.toSlicerHomeAbsolutePath("LTrace/saved_scenes")
        Path(slicer.app.toSlicerHomeAbsolutePath("LTrace/temp")).mkdir(parents=True, exist_ok=True)
        slicer.app.temporaryPath = slicer.app.toSlicerHomeAbsolutePath("LTrace/temp")

    def set_home_module(self):
        slicer.app.userSettings().setValue("Modules/HomeModule", "WelcomeGeoSlicer")

    def set_favorite_modules(self):
        slicer.app.userSettings().setValue(
            "Modules/FavoriteModules",
            [
                "WelcomeGeoSlicer",
                "ImageLogEnv",
                "CoreEnv",
                "MicroCTEnv",
                "ThinSectionEnv",
                "CustomizedData",
                "VolumeRendering",
                "VolumeCalculator",
                "CustomizedTables",
                "SegmentationEnv",
                "TableFilter",
                "NetCDF",
                "Charts",
            ],
        )

    def set_console_log_level(self):
        slicer.app.userSettings().setValue("Python/ConsoleLogLevel", "None")

    def set_gpu_rendering(self):
        slicer.app.userSettings().setValue(
            "VolumeRendering/RenderingMethod",
            "vtkMRMLGPURayCastVolumeRenderingDisplayNode",
        )

    def set_default_segmentation_terminology(self):
        terminology = [
            ("Segmentation category and type - DICOM master list",),
            ("SCT", "85756011", "Other"),
            ("SCT", "5000", "Default Terminology"),
            ("", "", ""),
            ("Anatomic codes - DICOM master list",),
            ("", "", ""),
            ("", "", ""),
        ]
        terminology_string = "~".join(["^".join(i) for i in terminology]) + "|"
        slicer.app.userSettings().setValue("Segmentations/DefaultTerminologyEntry", terminology_string)

    def setup_extension_manager(self):
        slicer.app.revisionUserSettings().setValue("Extensions/ManagerEnabled", False)
        window = slicer.util.mainWindow()
        window.findChild(qt.QMenu, "ViewMenu").actions()[5].visible = False
        window.findChild(qt.QToolBar, "DialogToolBar").actions()[0].visible = False

    def set_style(self):
        style = slicer.app.userSettings().value("Styles/Style")
        slicer.app.setStyle(style)

        layout = slicer.app.layoutManager()

        def onLayoutChanged(_):
            for name in layout.sliceViewNames():
                sliceView = layout.sliceWidget(name).sliceView()
                darkColor = qt.QColor.fromRgbF(0, 0, 0)
                lightColor = qt.QColor.fromRgbF(0.88, 0.88, 0.93)
                sliceView.setBackgroundColor(darkColor if themeIsDark() else lightColor)
                sliceView.forceRender()

        layout.layoutChanged.connect(onLayoutChanged)

    def get_module_paths(self):
        paths = CUSTOM_REL_PATHS

        return [str(Path(p).as_posix()) for p in paths]

    def read_modules(self):
        pass

    def replaceOrientationNames(self):
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

    def redSliceAnd3DCustomLayout(self):
        layoutXML = LAYOUT_TEMPLATE.substitute(
            view1=VIEW_2D_TEMPLATE.substitute(
                size="300",
                tag="Red",
                orientation="XY",
                label="R",
                color="#F34A33",
            ),
            view2=VIEW_3D_XML,
        )
        self.customLayout(100, layoutXML, "Red slice and 3D", self.RED_3D_CUSTOM_LAYOUT_ICON_PATH)

    def yellowSliceAnd3DCustomLayout(self):
        layoutXML = LAYOUT_TEMPLATE.substitute(
            view1=VIEW_2D_TEMPLATE.substitute(
                size="300",
                tag="Yellow",
                orientation="YZ",
                label="Y",
                color="#F34A33",
            ),
            view2=VIEW_3D_XML,
        )
        self.customLayout(101, layoutXML, "Yellow slice and 3D", self.YELLOW_3D_CUSTOM_LAYOUT_ICON_PATH)

    def greenSliceAnd3DCustomLayout(self):
        layoutXML = LAYOUT_TEMPLATE.substitute(
            view1=VIEW_2D_TEMPLATE.substitute(
                size="300",
                tag="Green",
                orientation="XZ",
                label="G",
                color="#F34A33",
            ),
            view2=VIEW_3D_XML,
        )
        self.customLayout(102, layoutXML, "Green slice and 3D", self.GREEN_3D_CUSTOM_LAYOUT_ICON_PATH)

    def sideBySideImageLayout(self):
        layoutXML = LAYOUT_TEMPLATE.substitute(
            view1=VIEW_2D_TEMPLATE_WITH_GROUP.substitute(
                size="500",
                tag="SideBySideSlice1",
                orientation="XY",
                label="1",
                color="#EEEEEE",
                group=self.SIDE_BY_SIDE_IMAGE_GROUP,
            ),
            view2=VIEW_2D_TEMPLATE_WITH_GROUP.substitute(
                size="500",
                tag="SideBySideSlice2",
                orientation="XY",
                label="2",
                color="#EEEEEE",
                group=self.SIDE_BY_SIDE_IMAGE_GROUP,
            ),
        )
        self.customLayout(
            self.SIDE_BY_SIDE_IMAGE_LAYOUT_ID,
            layoutXML,
            "Side by side",
            self.SIDE_BY_SIDE_IMAGE_LAYOUT_ICON,
        )
        self.sideBySideImageManager = None
        self.sideBySideSegmentationSetupComplete = False

    def sideBySideSegmentationLayout(self):
        layoutXML = LAYOUT_TEMPLATE.substitute(
            view1=VIEW_2D_TEMPLATE_WITH_GROUP.substitute(
                size="500",
                tag="SideBySideImageSlice",
                orientation="XY",
                label="I",
                color="#EEEEEE",
                group=self.SIDE_BY_SIDE_SEGMENTATION_GROUP,
            ),
            view2=VIEW_2D_TEMPLATE_WITH_GROUP.substitute(
                size="500",
                tag="SideBySideSegmentationSlice",
                orientation="XY",
                label="S",
                color="#CCCCCC",
                group=self.SIDE_BY_SIDE_SEGMENTATION_GROUP,
            ),
        )
        self.customLayout(
            self.SIDE_BY_SIDE_SEGMENTATION_LAYOUT_ID,
            layoutXML,
            "Side by side segmentation",
            self.SIDE_BY_SIDE_SEGMENTATION_LAYOUT_ICON,
        )

        layout = slicer.app.layoutManager()

        def onLayoutChanged(id_):
            if id_ == self.SIDE_BY_SIDE_SEGMENTATION_LAYOUT_ID:
                self.updateSideBySideSegmentation()
                Customizer._linkViews(("SideBySideSegmentationSlice", "SideBySideImageSlice"))
                Customizer._useSameBackgroundAs("Red", "SideBySideImageSlice")
                Customizer._useSameForegroundAs("Red", "SideBySideImageSlice")
                Customizer._useSameBackgroundAs("Red", "SideBySideSegmentationSlice", opacity=0)
                Customizer._useSameForegroundAs("Red", "SideBySideSegmentationSlice", opacity=0)

                if not self.sideBySideSegmentationSetupComplete:
                    setupViews("SideBySideImageSlice", "SideBySideSegmentationSlice")
                    self.sideBySideSegmentationSetupComplete = True

                # These are necessary despite also being called inside _useSameBackgroundAs and _useSameForegroundAs
                slicer.app.processEvents(1000)
                layout.sliceWidget("SideBySideImageSlice").sliceLogic().FitSliceToAll()
                layout.sliceWidget("SideBySideSegmentationSlice").sliceLogic().FitSliceToAll()
            else:
                self.exitSideBySideSegmentation()

            if id_ == self.SIDE_BY_SIDE_IMAGE_LAYOUT_ID:
                Customizer._linkViews(("SideBySideSlice1", "SideBySideSlice2"))
                Customizer._useSameBackgroundAs("Red", "SideBySideSlice1")
                Customizer._useSameBackgroundAs("Red", "SideBySideSlice2")

                if not self.sideBySideImageManager:
                    self.sideBySideImageManager = SideBySideImageManager()
                    setupViews("SideBySideSlice1", "SideBySideSlice2")
                self.sideBySideImageManager.enterLayout()
            elif self.sideBySideImageManager:
                self.sideBySideImageManager.exitLayout()

        @vtk.calldata_type(vtk.VTK_OBJECT)
        def onNodeAdded(caller, event, callData):
            if (
                isinstance(callData, slicer.vtkMRMLSegmentationNode)
                and layout.layout == self.SIDE_BY_SIDE_SEGMENTATION_LAYOUT_ID
            ):
                self.updateSideBySideSegmentation()

        layout.layoutChanged.connect(onLayoutChanged)

        slicer.mrmlScene.AddObserver(slicer.mrmlScene.NodeAddedEvent, onNodeAdded)

    @staticmethod
    def _linkViews(viewNames):
        for viewName in viewNames:
            slicer.app.layoutManager().sliceWidget(viewName).sliceLogic().GetSliceCompositeNode().SetLinkedControl(1)

    @staticmethod
    def _useSameBackgroundAs(fromSlice, toSlice, opacity=-1):
        layout = slicer.app.layoutManager()
        toLogic = layout.sliceWidget(toSlice).sliceLogic()
        toComposite = toLogic.GetSliceCompositeNode()
        if toComposite.GetBackgroundVolumeID() != None:
            # This slice already has a background, don't change it
            return
        fromLogic = layout.sliceWidget(fromSlice).sliceLogic()
        fromComposite = fromLogic.GetSliceCompositeNode()

        toComposite.SetBackgroundVolumeID(fromComposite.GetBackgroundVolumeID())
        if opacity < 0:
            opacity = fromComposite.GetBackgroundOpacity()
        toComposite.SetBackgroundOpacity(opacity)

        fromLogic.FitSliceToAll()
        toLogic.FitSliceToAll()

    @staticmethod
    def _useSameForegroundAs(fromSlice, toSlice, opacity=-1):
        layout = slicer.app.layoutManager()
        toLogic = layout.sliceWidget(toSlice).sliceLogic()
        toComposite = toLogic.GetSliceCompositeNode()
        if toComposite.GetForegroundVolumeID() != None:
            # This slice already has a foreground, don't change it
            return
        fromLogic = layout.sliceWidget(fromSlice).sliceLogic()
        fromComposite = fromLogic.GetSliceCompositeNode()

        toComposite.SetForegroundVolumeID(fromComposite.GetForegroundVolumeID())
        if opacity < 0:
            opacity = fromComposite.GetForegroundOpacity()
        toComposite.SetForegroundOpacity(opacity)

        fromLogic.FitSliceToAll()
        toLogic.FitSliceToAll()

    def updateSideBySideSegmentation(self):
        sliceWidget = slicer.app.layoutManager().sliceWidget("SideBySideSegmentationSlice")
        if not sliceWidget or slicer.mrmlScene.IsImporting():
            # Project is loading, will update later when layout is changed
            return
        segSliceLogic = sliceWidget.sliceLogic()
        segCompositeNode = segSliceLogic.GetSliceCompositeNode()

        # Hide image but still keep it as background for segmentation logic to work
        segCompositeNode.SetBackgroundOpacity(0)

        segSliceId = segSliceLogic.GetSliceNode().GetID()
        segNodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
        for segNode in segNodes:
            # Image log has its own handling of segmentation visibility
            if not segNode.GetAttribute("ImageLogSegmentation"):
                segNode.CreateDefaultDisplayNodes()
                displayNode = segNode.GetDisplayNode()
                displayNode.SetOpacity(1)

                # Show segmentation on 'S' slice view only
                displayNode.AddViewNodeID(segSliceId)

    def exitSideBySideSegmentation(self):
        segNodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
        for segNode in segNodes:
            # Image log has its own handling of segmentation visibility
            if not segNode.GetAttribute("ImageLogSegmentation"):
                displayNode = segNode.GetDisplayNode()
                if displayNode is None:
                    continue

                displayNode.SetOpacity(0.5)
                # Show segmentation on any view
                displayNode.RemoveAllViewNodeIDs()

    def customLayout(self, layoutID, layoutXML, name, iconPath):
        layoutManager = slicer.app.layoutManager()
        layoutManager.layoutLogic().GetLayoutNode().AddLayoutDescription(layoutID, layoutXML)

        # Add button to layout selector toolbar for this custom layout
        viewToolBar = slicer.util.mainWindow().findChild("QToolBar", "ViewToolBar")
        layoutMenu = viewToolBar.widgetForAction(viewToolBar.actions()[0]).menu()
        layoutSwitchActionParent = layoutMenu
        layoutSwitchAction = layoutSwitchActionParent.addAction(name)  # add inside layout list
        layoutSwitchAction.setData(layoutID)
        layoutSwitchAction.setIcon(qt.QIcon(str(iconPath)))
        layoutSwitchAction.connect(
            "triggered()",
            lambda layoutId=layoutID: slicer.app.layoutManager().setLayout(layoutId),
        )

    def customize_toolbar(self):
        # disable dicom load button
        mt = slicer.util.mainWindow().findChild("QToolBar", "MainToolBar")
        mt.actions()[1].setVisible(False)

        # disable Ruler and change name of Line to Ruler
        sn = slicer.mrmlScene.GetNodeByID("vtkMRMLSelectionNodeSingleton")
        sn.RemovePlaceNodeClassNameFromList("vtkMRMLAnnotationRulerNode")
        cname = "vtkMRMLMarkupsLineNode"
        resource = ":/Icons/AnnotationDistanceWithArrow.png"
        iconName = "Ruler"
        sn.AddNewPlaceNodeClassNameToList(cname, resource, iconName)

        # move non essential views to advanced views menu
        viewToolBar = slicer.util.mainWindow().findChild("QToolBar", "ViewToolBar")
        layoutButton = viewToolBar.widgetForAction(viewToolBar.actions()[0])
        self.__layout_menu = layoutMenu = layoutButton.menu()
        default_action = layoutButton.defaultAction()

        # initialize the histogram pop-up beforehand
        self.popup_widget = HistogramPopupWidget(slicer.util.mainWindow())
        self.popup_widget.hide()

        # create button for showing the histogram pop-up and put it on the toolbar
        self.histogram_button = qt.QAction("Histogram")
        self.histogram_button.setIcon(qt.QIcon(self.HISTOGRAM_POPUP_ICON_PATH))
        viewToolBar.addAction(self.histogram_button)
        self.histogram_button.triggered.connect(self.popup_action_clicked)

        # connect the red slice to the histogram pop-up
        slicer.app.layoutManager().sliceWidget("Red").sliceLogic().AddObserver(
            vtk.vtkCommand.ModifiedEvent, self.red_slice_modified
        )

        # Add customized screenshot dialog
        captureToolBar = slicer.util.mainWindow().findChild("QToolBar", "CaptureToolBar")

        for action in captureToolBar.actions():
            captureToolBar.removeAction(action)

        screenshotAction = captureToolBar.addAction(
            qt.QIcon(self.SCREENSHOT_ICON_PATH),
            "",
            lambda: ScreenshotWidget(icon=self.SCREENSHOT_ICON_PATH).exec(),
        )

        advanced_menu = qt.QMenu("Advanced views...", slicer.util.mainWindow())

        moved_itens_indexes = [
            1,
            2,
            4,
            5,
            6,
            7,
            8,
            10,
            11,
            15,
            16,
            17,
            18,
            19,
            20,
            21,
            22,
            23,
            24,
            25,
            26,
            27,
        ]
        moved_itens = list()
        for i in moved_itens_indexes:
            moved_itens.append(layoutMenu.actions()[i])

        layoutMenu.insertSeparator(layoutMenu.actions()[11])
        layoutMenu.insertSeparator(layoutMenu.actions()[16])
        layoutMenu.addSeparator()

        for i in moved_itens:
            advanced_menu.addAction(i)
            layoutMenu.removeAction(i)

        layoutMenu.addMenu(advanced_menu)
        layoutMenu.setStyleSheet("QMenu::separator { height: 1px; background: gray; }")

        # Slicer bug. It always start on this item, which is not selectable (it is a submenu)
        if default_action.text == "Three over three Quantitative":
            default_action = layoutMenu.actions()[0]
            default_action.trigger()

        layoutButton.setDefaultAction(default_action)

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
        self.imageLogLayoutViewAction = qt.QAction("ImageLog View")
        self.imageLogLayoutViewAction.setIcon(qt.QIcon(self.IMAGELOG_ICON_PATH))
        self.imageLogLayoutViewAction.triggered.connect(self.__on_imagelog_layout_view_action_clicked)

        after_3d_only_action = layoutMenu.actions()[3]
        layoutMenu.insertAction(after_3d_only_action, self.imageLogLayoutViewAction)
        # layoutMenu.triggered.connect(lambda action: self.__layout_menu.setActiveAction(action))

    def customizeCloseApplicationEvent(self):
        self.__customizerEventFilter = CustomizerEventFilter(saveSceneCallback=self._saveScene)
        slicer.util.mainWindow().installEventFilter(self.__customizerEventFilter)

    def customize_module_help(self):
        main_window = slicer.util.mainWindow()
        module_panel = main_window.findChild(slicer.qSlicerModulePanel, "ModulePanel")
        help_label = module_panel.findChild(ctk.ctkFittedTextBrowser, "HelpLabel")
        help_label.setOpenLinks(False)
        help_label.anchorClicked.connect(self._on_html_link_clicked)

    def red_slice_modified(self, red_slice_logic, _):
        new_node = red_slice_logic.GetLayerVolumeNode(0)
        if new_node is self.popup_widget.node:
            return
        if self.popup_widget is not None:
            self.popup_widget.mainInput.setCurrentNode(new_node)

    def red_slice_combobox_modified(self, new_node):
        self.popup_widget.mainInput.setCurrentNode(new_node)

    def popup_action_clicked(self):
        red_slice_volume = slicer.app.layoutManager().sliceWidget("Red").sliceLogic().GetLayerVolumeNode(0)
        self.popup_widget.mainInput.setCurrentNode(red_slice_volume)
        self.popup_widget.show()

    def _on_html_link_clicked(self, url):
        if not url.scheme():
            qt.QDesktopServices.openUrl(qt.QUrl("file:///" + slicer.app.applicationDirPath() + "/../" + str(url)))
        else:
            qt.QDesktopServices.openUrl(url)

    def __on_imagelog_layout_view_action_clicked(self):
        widget = slicer.util.getModuleWidget("ImageLogEnv")
        if widget is None:
            logging.critical("ImageLogData module was not found!")
            return

        widget.imageLogDataWidget.self().logic.changeToLayout()

    def __onDockedDataToggled(self, checked):
        """Handle docked data visibility.

        Args:
            checked (bool): the visibility state.
        """
        if not self.dockedDataAction or not self.dockedData:
            return

        settings = slicer.app.userSettings()
        settings.setValue("Explorer/Visible", str(checked))
        with BlockSignals(self.dockedDataAction):
            self.dockedData.setVisible(checked)

    def __createDocketDataAction(self) -> "qt.QAction":
        """Create and configure docked data action

        Returns:
            qt.QAction: the QAction object related to docked data.
        """
        from ltrace.slicer.widget.docked_data import DockedData

        self.dockedData = DockedData()

        self.dockedDataAction = qt.QAction("Explorer")
        self.dockedDataAction.setToolTip("Show/hide Explorer")
        self.dockedDataAction.setIcon(qt.QIcon(str(self.EXPLORER_ICON_PATH)))
        self.dockedDataAction.setCheckable(True)
        self.dockedDataAction.setChecked(slicer.app.userSettings().value("Explorer/Visible", "True") == "True")
        self.__onDockedDataToggled(self.dockedDataAction.isChecked())
        self.dockedDataAction.toggled.connect(self.__onDockedDataToggled)
        self.dockedData.visibilityChanged.connect(self.dockedDataAction.setChecked)

        return self.dockedDataAction

    def _onCloseScene(self):
        """Handle close scene event"""

        def wrapper(save=False):
            if save and not self._saveScene():
                return

            slicer.mrmlScene.Clear(0)
            slicer.mrmlScene.SetURL("")
            self.__update_window_title()

        mainWindow = slicer.util.mainWindow()
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
        if messageBox.clickedButton() == saveButton:
            wrapper(save=True)
            return
        elif messageBox.clickedButton() == dismissButton:
            wrapper(save=False)
            return

    def __searchAction(self, menu, text):
        for action in menu.actions():
            if action.text == text:
                return action

        return None


class CustomizerWidget(LTracePluginWidget):
    def setup(self):
        pass


class CustomizerLogic(LTracePluginLogic):
    pass
