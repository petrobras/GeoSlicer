import PySide2
import shiboken2
import slicer
import ctk
import vtk
import qt
import logging
import json
import math
import numpy as np
import os
import pyqtgraph as pg
import traceback

from ltrace.slicer.application_observables import ApplicationObservables
from ltrace.slicer.debounce_caller import DebounceCaller
from ltrace.slicer.widget.depth_overview_axis_item import DepthOverviewAxisItem
from ltrace.slicer_utils import *
from ltrace.slicer_utils import getResourcePath
from ltrace.constants import ImageLogConst
from pathlib import Path
from slicer.util import VTKObservationMixin
from ltrace.slicer.helpers import tryGetNode, getCurrentEnvironment

from CustomizedData import CustomizedDataWidget
from CustomizedDataLib.LabelMap import LabelMapWidget
from CustomizedDataLib.Segmentation import SegmentationWidget
from CustomizedDataLib.Table import TableWidget
from ImageLogDataLib.treeview import *
from ImageLogDataLib.view import *
from ImageLogDataLib.view.image_log_view import ImageLogView
from ImageLogDataLib.viewcontroller import *
from ImageLogDataLib.viewdata import *
from ImageLogDataLib.treeview.SubjectHierarchyTreeViewFilter import SubjectHierarchyTreeViewFilter
from ImageLogDataLib.mouse_event_filter import MouseEventFilter

# Checks if closed source code is available
try:
    from Test.ImageLogDataTest import ImageLogDataTest
except ImportError:
    ImageLogDataTest = None  # tests not deployed to final version or closed source


class ImageLogData(LTracePlugin):
    SETTING_KEY = "ImageLogData"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Explorer"
        self.parent.categories = ["Tools", "ImageLog", "Thin Section", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ImageLogData.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ImageLogDataWidget(CustomizedDataWidget):
    # Global shared logic for all widget instances
    logic = None

    def __init__(self, parent):
        super().__init__(parent)

    def setup(self):
        super().setup()
        if hasattr(slicer.modules.AppContextInstance, "imageLogDataLogic"):
            self.logic = ImageLogDataWidget.logic = slicer.modules.AppContextInstance.imageLogDataLogic
        else:
            self.logic = (
                ImageLogDataWidget.logic
            ) = slicer.modules.AppContextInstance.imageLogDataLogic = ImageLogDataLogic(
                slicer.modules.AppContextInstance.mainWindow
            )

        ## Add custom context menu actions
        self.subjectHierarchyTreeView.setMRMLScene(slicer.app.mrmlScene())
        self.subjectHierarchyTreeView.header().setVisible(False)
        self.subjectHierarchyTreeView.hideColumn(2)
        self.subjectHierarchyTreeView.hideColumn(3)
        self.subjectHierarchyTreeView.hideColumn(4)
        self.subjectHierarchyTreeView.hideColumn(5)
        self.subjectHierarchyTreeView.setEditMenuActionVisible(False)
        self.subjectHierarchyTreeView.setFocusPolicy(qt.Qt.NoFocus)

        infoFrameLayout = self.infoFrame.layout()
        self.trackImageWidget = TrackImageWidget()
        infoFrameLayout.addWidget(self.trackImageWidget)
        self.trackImageWidget.setVisible(False)

        self.tableWidget = TableWidget()
        infoFrameLayout.addWidget(self.tableWidget)
        self.tableWidget.setVisible(False)

        self.labelMapWidget = LabelMapWidget()
        infoFrameLayout.addWidget(self.labelMapWidget)
        self.labelMapWidget.setVisible(False)

        self.segmentationWidget = SegmentationWidget()
        infoFrameLayout.addWidget(self.segmentationWidget)
        self.segmentationWidget.setVisible(False)

        # Settings section
        self.settingsCollapsibleButton = ctk.ctkCollapsibleButton()
        self.settingsCollapsibleButton.setText("Settings")
        self.settingsCollapsibleButton.collapsed = True
        infoFrameLayout.addWidget(self.settingsCollapsibleButton)
        settingsFormLayout = qt.QFormLayout(self.settingsCollapsibleButton)
        settingsFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        # Views
        viewsGroupBox = qt.QGroupBox("Views:")
        viewsGroupBoxLayout = qt.QFormLayout(viewsGroupBox)
        viewsGroupBoxLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.translationSpeed = slicer.qMRMLSliderWidget()
        self.translationSpeed.toolTip = (
            "Increase/decrease this value to allow a faster/smoother translation in the track views."
        )
        self.translationSpeed.maximum = 5
        self.translationSpeed.minimum = 1
        self.translationSpeed.decimals = 1
        self.translationSpeed.singleStep = 0.1
        self.translationSpeed.value = 4
        self.translationSpeed.valueChanged.connect(self.translationSpeedChanged)
        viewsGroupBoxLayout.addRow("Translation speed: ", self.translationSpeed)

        self.scalingSpeed = slicer.qMRMLSliderWidget()
        self.scalingSpeed.toolTip = (
            "Increase/decrease this value to allow a faster/smoother scaling in the track views."
        )
        self.scalingSpeed.maximum = 5
        self.scalingSpeed.minimum = 1
        self.scalingSpeed.decimals = 1
        self.scalingSpeed.singleStep = 0.1
        self.scalingSpeed.value = 4
        self.scalingSpeed.valueChanged.connect(self.scalingSpeedChanged)
        viewsGroupBoxLayout.addRow("Scaling speed: ", self.scalingSpeed)

        settingsFormLayout.addRow(viewsGroupBox)

        self.logic.addViewClicked.disconnect()
        self.logic.addViewClicked.connect(self.addView)

        self.filter = SubjectHierarchyTreeViewFilter(dataWidget=self)
        self.subjectHierarchyTreeView.installEventFilter(self.filter)

    def translationSpeedChanged(self, value):
        self.logic.translationSpeedChanged(value)

    def scalingSpeedChanged(self, value):
        self.logic.scalingSpeedChanged(value)

    def onReload(self) -> None:
        logic = ImageLogDataWidget.logic
        oldDockedWidget = None
        if hasattr(slicer.modules, "ImageLogDataDockedWidget") and slicer.modules.ImageLogDataWidget is not self:
            oldWidget = slicer.modules.ImageLogDataWidget
            oldDockedWidget = slicer.modules.ImageLogDataDockedWidget

        self.cleanup()
        super().onReload()

        self.logic.onSlicerLayoutChanged(slicer.app.layoutManager().layout)

        if oldDockedWidget is not None:
            newDockedWidget = slicer.util.getModuleWidget("ImageLogData")
            slicer.modules.ImageLogDataWidget = oldWidget
            slicer.modules.ImageLogDataDockedWidget = newDockedWidget

        ImageLogDataWidget.logic = logic
        ImageLogDataWidget.logic.setParent(slicer.util.getModuleWidget("ImageLogData").parent)

    def addView(self):
        def nodeFromSubjectItemId(itemId):
            return self.subjectHierarchyTreeView.subjectHierarchyNode().GetItemDataNode(itemId)

        if not hasattr(slicer.modules, "ImageLogDataDockedWidget"):
            selectedNodeIdInTree = self.subjectHierarchyTreeView.currentItem()
            selectedNode = nodeFromSubjectItemId(selectedNodeIdInTree)
            self.subjectHierarchyTreeView.setCurrentItems(vtk.vtkIdList())
        else:  # Handling both explorers. The left panel is preffered.
            leftPanelSelectedNode = slicer.modules.ImageLogDataWidget.subjectHierarchyTreeView.currentItem()
            rightPanelSelectedNode = slicer.modules.ImageLogDataDockedWidget.subjectHierarchyTreeView.currentItem()
            selectedNode = nodeFromSubjectItemId(leftPanelSelectedNode) or nodeFromSubjectItemId(rightPanelSelectedNode)
            slicer.modules.ImageLogDataWidget.subjectHierarchyTreeView.setCurrentItems(vtk.vtkIdList())
            slicer.modules.ImageLogDataDockedWidget.subjectHierarchyTreeView.setCurrentItems(vtk.vtkIdList())

        try:
            self.logic.addView(selectedNode)
        except ImageLogDataInfo as e:
            slicer.util.infoDisplay(str(e))

    def currentItemChanged(self, itemID_bogus):
        # hack to workaround currentItemChanged firing twice
        itemID = self.subjectHierarchyTreeView.currentItem()
        self.trackImageWidget.setVisible(False)
        self.tableWidget.setVisible(False)
        self.labelMapWidget.setVisible(False)
        self.segmentationWidget.setVisible(False)

        node = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(itemID)
        try:
            if type(node) is slicer.vtkMRMLScalarVolumeNode or type(node) is slicer.vtkMRMLVectorVolumeNode:
                self.trackImageWidget.setNode(node)
                self.trackImageWidget.setVisible(True)
            elif type(node) is slicer.vtkMRMLTableNode:
                if node.GetNumberOfRows() <= 3000:
                    self.tableWidget.setNode(node)
                    self.tableWidget.setVisible(True)
            elif type(node) is slicer.vtkMRMLLabelMapVolumeNode:
                self.labelMapWidget.setNode(node)
                self.labelMapWidget.setVisible(True)
            elif type(node) is slicer.vtkMRMLSegmentationNode:
                if node.GetSegmentation().GetNumberOfSegments() <= 50:  # Performance reasons
                    self.segmentationWidget.setNode(node)
                    self.segmentationWidget.setVisible(True)
        except Exception as error:
            # In case of a problematic node
            logging.warning(f"{error}\n{traceback.print_exc()}")

    def exit(self):
        self.logic.exit()

    def cleanup(self):
        super().cleanup()
        self.subjectHierarchyTreeView.removeEventFilter(self.filter)
        self.logic.addViewClicked.disconnect(self.addView)
        self.logic.imageLogViewList.clear()
        self.logic.refreshViews()

    def getVisibleViews(self):
        identifiers = self.logic.getViewDataListIdentifiers()
        views = {}
        for id in identifiers:
            viewData = self.logic.imageLogViewList[id].viewData
            viewControllerWidget = self.logic.viewControllerWidgets[id]
            viewLabel = viewControllerWidget.findChild(qt.QLabel, "viewLabel" + str(id))
            name = viewLabel.text
            views[id] = {"type": type(viewData).__name__, "name": name}

        return views

    def getGraphicViewPlotItem(self, viewIdentifier: int) -> pg.PlotItem:
        if not isinstance(viewIdentifier, int):
            return

        if isinstance(self.logic.imageLogViewList[viewIdentifier].viewData, GraphicViewData):
            curvePlot = self.logic.imageLogViewList[viewIdentifier].widget.getPlot()
            return curvePlot.get_plot_item()


class ViewDataEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, SliceViewData):
            return obj.to_json()
        elif isinstance(obj, GraphicViewData):
            return obj.to_json()
        elif isinstance(obj, EmptyViewData):
            return obj.to_json()
        return super().default(obj)


class ImageLogDataLogic(LTracePluginLogic, VTKObservationMixin):
    CONFIGURATION_SINGLETON_TAG = "ImageLogConfiguration"
    MAXIMUM_NUMBER_OF_VIEWS = 5
    ALLOWED_ENVIRONMENTS_FOR_LAYOUT = "ImageLogEnv", "MultiscaleEnv", "ThinSectionEnv"

    """
    Do not lower this time unless it is all tested (a lower delay time results in a faster interface response but tends to cause many 
    interface problems, some subtle, like the incorrect synchronization of the range in each of the views).
    """
    REFRESH_DELAY = 50

    layoutViewOpened = qt.Signal()
    layoutViewClosed = qt.Signal()
    viewsRefreshed = qt.Signal()
    addViewClicked = qt.Signal(bool)

    def __init__(self, parent):
        LTracePluginLogic.__init__(self, parent)
        VTKObservationMixin.__init__(self)

        self.imageLogViewList = []  # Stores ViewData objects, containing all the data and metadata regarding a view
        self.viewControllerWidgets = []  # Stores view controller widgets (follows viewDataList order)
        self.viewColorBarWidgets = []  # Stores view color bar widgets (follows viewDataList order)
        self.viewWidgets = []  # Stores view widgets (follows viewDataList order)
        self.viewSpacerWidgets = []  # Stores spacer widgets at the bottom of the view (follows viewDataList order)
        self.curvePlotWidgets = []  # Stores curve plot widgets (follows viewDataList order)
        self.containerWidgets = {}  # Other layout widgets (axis, spacers, etc)
        self.observedDisplayNodes = []
        self.observedPrimaryNodes = []
        self.observedInteractors = []
        self.currentRange = (
            None  # This is the current range of the tracks. [bottom depth, top depth] where bottom depth > top depth
        )
        self.translationSpeed = 3
        self.scalingSpeed = 3
        self.segmentationOpacity = 0.5  # Maintains opacity value between all segmentation nodes
        self.nodeAboutToBeRemoved = False  # To avoid calling primaryNodeChanged function when a node is removed
        self.debug = False  # Set true to track some function calls origin
        self.delayedAdjustViewsVisibleRegion = DebounceCaller(
            self, intervalMs=self.REFRESH_DELAY, callback=self.adjustViewsVisibleRegion
        )
        self.__delayedRefreshViews = DebounceCaller(self, intervalMs=self.REFRESH_DELAY, callback=self.__refreshViews)

        slicer.app.layoutManager().layoutChanged.connect(self.onSlicerLayoutChanged)
        self.__layoutViewOpen = False
        self.__observerHandlers = []
        self.layoutManagerViewPort = slicer.app.layoutManager().viewport()  # Central widget
        self.mouseEventFilter = MouseEventFilter(self)
        self.saveObserver = None
        self.configurationsNode = None
        self.imageLogLayoutViewAction = None
        self.__addImageLogViewOption()
        ApplicationObservables().environmentChanged.connect(self.__updateImageLogLayoutActionVisibility)

    def loadConfiguration(self):
        slicer.app.processEvents()
        qt.QTimer.singleShot(500, self.delayedLoadConfiguration)
        slicer.app.processEvents()

    def delayedLoadConfiguration(self):
        # The configuration was not loaded yet
        if self.configurationsNode is None:
            self.configurationsNode = slicer.mrmlScene.GetSingletonNode(
                self.CONFIGURATION_SINGLETON_TAG, "vtkMRMLScriptedModuleNode"
            )

            if self.configurationsNode is None:
                self.configurationsNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScriptedModuleNode")
                self.configurationsNode.SetName(self.CONFIGURATION_SINGLETON_TAG)
                self.configurationsNode.SetSingletonOn()
                self.configurationsNode.SetSingletonTag(self.CONFIGURATION_SINGLETON_TAG)
                self.configurationsNode.SetParameter("ImagLogViews", json.dumps([]))
            viewsJson = self.configurationsNode.GetParameter("ImagLogViews")
            if viewsJson:
                viewsList = json.loads(viewsJson)
                if viewsList:
                    self.__loadViewFromList(viewsList)

    def __loadViewFromList(self, viewList):
        self.imageLogViewList.clear()
        self.cleanUp()

        for identifier, viewData in viewList[: self.MAXIMUM_NUMBER_OF_VIEWS - 1]:
            if "primaryNodeId" in viewData:
                if viewData["primaryNodeId"] is None:
                    # Add EmptyViewData
                    self.imageLogViewList.append(ImageLogView(None))
                else:
                    self.addSliceViewData(viewData, identifier)
            if "primaryTableNodeColumnList" in viewData:
                self.addGraphicViewData(viewData)

        self.refreshViews("loadViewFromList")

    def addSliceViewData(self, viewData, identifier):
        primaryNode = tryGetNode(viewData["primaryNodeId"])
        if "segmentationNodeId" in viewData:
            segNode = tryGetNode(viewData["segmentationNodeId"])
        self.imageLogViewList.append(ImageLogView(primaryNode, segNode))
        if viewData["proportionsNodeHidden"] == False:
            self.__refreshViews("LoadView")
            viewControllerWidget = self.viewControllerWidgets[identifier]
            showHideProportionsNodeButton = viewControllerWidget.findChild(
                qt.QPushButton, "showHideProportionsNodeButton" + str(identifier)
            )
            showHideProportionsNodeButton.click()

    def addGraphicViewData(self, viewData):
        for node in slicer.mrmlScene.GetNodesByClass("vtkMRMLTableNode"):
            if node.GetName() == viewData["primaryTableNodeColumnList"][0]:
                self.imageLogViewList.append(ImageLogView(node))

    def saveConfiguration(self):
        if not self.configurationsNode:
            return

        viewsList = []
        for identifier in self.getViewDataListIdentifiers():
            viewData = self.imageLogViewList[identifier].viewData
            viewsList.append((identifier, viewData))

        viewsJson = json.dumps(viewsList, cls=ViewDataEncoder)
        self.configurationsNode.SetParameter("ImagLogViews", viewsJson)

    def onSceneStartSave(self, *args):
        self.saveConfiguration()

    def changeToLayout(self):
        if self.__layoutViewOpen is True:
            return

        # If layout view is not initialized yet, then create it
        if slicer.modules.AppContextInstance.imageLogLayoutId == ImageLogConst.DEFAULT_LAYOUT_ID_START_VALUE:
            self.refreshViews("changeToLayout")
        else:
            slicer.app.layoutManager().setLayout(slicer.modules.AppContextInstance.imageLogLayoutId)

    def onSlicerLayoutChanged(self, layoutId):
        self.__updateImageLogLayoutActionVisibility()
        if ImageLogConst.DEFAULT_LAYOUT_ID_START_VALUE <= layoutId < 16000:
            if self.__layoutViewOpen is True:
                return

            self.updateViewsAxis()

            slicer.modules.AppContextInstance.mainWindow.installEventFilter(self.mouseEventFilter)
            self.layoutViewOpened.emit()
            self.__layoutViewOpen = True
            self.refreshViews("EnterEvent")
            self.installObservers()

        else:
            if self.__layoutViewOpen is False:
                return

            slicer.modules.AppContextInstance.mainWindow.removeEventFilter(self.mouseEventFilter)

            self.layoutViewClosed.emit()
            self.__layoutViewOpen = False
            self.exit()
            self.uninstallObservers()

    ########################################################################################################################################
    # Layout
    ########################################################################################################################################

    def generateLayout(self):
        """
        Uses the viewDataList to build a layout with views in the correct order and types.
        """
        layout = """<layout type="vertical">"""
        layout += """<item><toolBarWidget></toolBarWidget></item>"""
        layout += """<item><layout type="horizontal">"""
        layout += """<item><axisWidget></axisWidget></item>"""

        for identifier in self.getViewDataListIdentifiers():
            viewLayout = self.generateViewLayout(identifier)
            layout += viewLayout

        layout += """<item><spacerWidget></spacerWidget></item>"""
        layout += """</layout></item>"""
        layout += """</layout>"""
        return layout

    def generateViewLayout(self, identifier):
        """
        Generates a layout item with type (SliceView or GraphicView) depending on the viewData.
        """
        viewLayout = """<item><layout type="vertical">"""

        viewControllerName = self.getViewControllerName(identifier)
        viewLayout += f"""<item><{viewControllerName}></{viewControllerName}></item>"""
        viewColorBarName = self.getViewColorBarName(identifier)
        viewLayout += f"""<item><{viewColorBarName}></{viewColorBarName}></item>"""
        viewName = self.getViewName(identifier)

        if type(self.imageLogViewList[identifier].viewData) is SliceViewData:
            viewLayout += f"""
                <item>
                    <view class="vtkMRMLSliceNode" singletontag="{viewName}">
                         <property name="orientation" action="default">XZ</property>
                    </view>
                </item>
                """
        else:
            viewLayout += f"""<item><{viewName}></{viewName}></item>"""

        viewSpacerName = self.getViewSpacerName(identifier)
        viewLayout += f"""<item><{viewSpacerName}></{viewSpacerName}></item>"""

        viewLayout += """</layout></item>"""
        return viewLayout

    def registerLayout(self, layout):
        """
        Register the layout on Slicer's layout manager and saves the views widgets for later access.
        """
        slicer.modules.AppContextInstance.imageLogLayoutId += 1

        viewDataListIdentifiers = self.getViewDataListIdentifiers()

        # Registering non-view widgets
        self.containerWidgets = {}
        for containerWidgetTag in ["toolBarWidget", "axisWidget", "spacerWidget"]:
            self.containerWidgets[containerWidgetTag] = self.registerLayoutItem(containerWidgetTag)

        # Bottom view spacers
        self.viewSpacerWidgets = []
        for identifier in viewDataListIdentifiers:
            self.viewSpacerWidgets.append(self.registerLayoutItem(self.getViewSpacerName(identifier)))

        # Registering view controller widgets
        self.viewControllerWidgets = []
        for identifier in viewDataListIdentifiers:
            self.viewControllerWidgets.append(self.registerLayoutItem(self.getViewControllerName(identifier)))

        # Registering view color bar widgets
        self.viewColorBarWidgets = []
        for identifier in viewDataListIdentifiers:
            self.viewColorBarWidgets.append(self.registerLayoutItem(self.getViewColorBarName(identifier)))

        # Registering views other than slice views
        self.viewWidgets = [None] * len(
            self.imageLogViewList
        )  # Pre initialization of the slots to put the items in the desired order
        for identifier in viewDataListIdentifiers:
            viewDataType = type(self.imageLogViewList[identifier].viewData)
            if viewDataType is GraphicViewData or viewDataType is EmptyViewData:
                self.viewWidgets[identifier] = self.registerLayoutItem(self.getViewName(identifier))

        # Registering the layout and activating it
        layoutManager = slicer.app.layoutManager()
        layoutManager.layoutLogic().GetLayoutNode().AddLayoutDescription(
            slicer.modules.AppContextInstance.imageLogLayoutId, layout
        )
        slicer.app.layoutManager().setLayout(slicer.modules.AppContextInstance.imageLogLayoutId)

        # And now we can save the slice views references
        for identifier in viewDataListIdentifiers:
            viewDataType = type(self.imageLogViewList[identifier].viewData)
            if viewDataType is SliceViewData:
                viewName = self.getViewName(identifier)
                viewWidget = slicer.app.layoutManager().sliceWidget(viewName)
                viewWidget.setObjectName(viewName)
                self.viewWidgets[identifier] = viewWidget

        # Stretch factors
        centralWidgetLayoutFrame = slicer.modules.AppContextInstance.mainWindow.findChild(
            qt.QFrame, "CentralWidgetLayoutFrame"
        )
        centralWidgetLayoutFrameLayout = centralWidgetLayoutFrame.layout()
        if centralWidgetLayoutFrameLayout and centralWidgetLayoutFrameLayout.count() >= 2:
            layout = centralWidgetLayoutFrameLayout.itemAt(1).layout()
            count = layout.count()
            # Setting the same stretch factor for all views (skipping axis widget and spacer widget)
            if count > 3:
                for i in range(1, count - 1):
                    layout.setStretch(i, 1)

        # To save the plot widgets and access them later
        self.curvePlotWidgets = [None] * len(viewDataListIdentifiers)

    def registerLayoutItem(self, tag):
        """
        Register a layout item (as a QWidget) to be filled with other interface items later on.
        """
        viewFactory = slicer.qSlicerSingletonViewFactory()
        viewFactory.setTagName(tag)
        slicer.app.layoutManager().registerViewFactory(viewFactory)
        widget = qt.QWidget()
        widget.setAutoFillBackground(True)
        widget.setObjectName(tag)
        viewFactory.setWidget(widget)
        return widget

    ########################################################################################################################################
    # Widgets setup
    ########################################################################################################################################

    def setupViewControllerWidgets(self):
        for identifier in self.getViewDataListIdentifiers():
            viewControllerWidget = self.viewControllerWidgets[identifier]
            viewControllerWidgetLayout = qt.QVBoxLayout(viewControllerWidget)
            viewControllerWidgetLayout.setContentsMargins(0, 0, 0, 0)

            # Necessary to listen horizontal resize events (only once, in the first view)
            if identifier == 0:
                customResizeWidget = CustomResizeWidget(self.customResizeWidgetCallback)
                customResizeWidget.setFixedHeight(0)
                viewControllerWidgetLayout.addWidget(customResizeWidget)
            else:
                # Just to maintain the same height to all view controllers
                dummyWidget = qt.QWidget()
                dummyWidget.setFixedHeight(0)
                viewControllerWidgetLayout.addWidget(dummyWidget)

            controlsFrame = qt.QFrame()
            controlsLayout = qt.QHBoxLayout(controlsFrame)
            controlsLayout.setContentsMargins(0, 0, 0, 0)
            viewControllerWidgetLayout.addWidget(controlsFrame)

            viewData = self.imageLogViewList[identifier].viewData
            if type(viewData) is EmptyViewData:
                emptyViewControllerWidget = EmptyViewControllerWidget(self, identifier)
                controlsLayout.addWidget(emptyViewControllerWidget)
            elif type(viewData) is SliceViewData:
                sliceViewControllerWidget = SliceViewControllerWidget(self, identifier)
                controlsLayout.addWidget(sliceViewControllerWidget)
            elif type(viewData) is GraphicViewData:
                graphicViewControllerWidget = GraphicViewControllerWidget(self, identifier)
                controlsLayout.addWidget(graphicViewControllerWidget)

    def setupViewWidgets(self):
        for identifier in self.getViewDataListIdentifiers():
            viewData = self.imageLogViewList[identifier].viewData
            if type(viewData) is EmptyViewData:
                self.setupEmptyViewWidget(identifier)
            elif type(viewData) is SliceViewData:
                self.setupSliceViewWidget(identifier)
            elif (
                type(viewData) is GraphicViewData
                and viewData.primaryTableNodeColumn == ""
                and viewData.secondaryTableNodeColumn == ""
            ):
                self.setupEmptyViewWidget(identifier)
            elif type(viewData) is GraphicViewData and (
                viewData.primaryTableNodeColumn != "" or viewData.secondaryTableNodeColumn != ""
            ):
                self.setupGraphicViewWidget(identifier)

    # def setupViewSpacerWidgets(self):
    #     for identifier in self.getViewDataListIdentifiers():
    #         viewData = self.imageLogViewList[identifier].viewData
    #         if type(viewData) is SliceViewData:
    #             viewSpacerWidget = self.viewSpacerWidgets[identifier]
    #             viewSpacerWidgetLayout = qt.QVBoxLayout(viewSpacerWidget)
    #             viewSpacerWidgetLayout.setContentsMargins(0, 0, 0, 0)
    #             viewSpacerWidgetLayout.addSpacerItem(qt.QSpacerItem(0, 20))
    #         # else:
    #         #     self.viewSpacerWidgets[identifier].deleteLater()  # Not used in other views

    def setupGraphicViewWidget(self, identifier):
        viewWidget = self.viewWidgets[identifier]

    def setupEmptyViewWidget(self, identifier):
        viewWidget = self.viewWidgets[identifier]
        viewWidgetLayout = qt.QVBoxLayout(viewWidget)
        viewWidgetLayout.addStretch()

    def setupSliceViewWidget(self, identifier):
        sliceViewWidget = self.viewWidgets[identifier]
        sliceController = sliceViewWidget.sliceController()
        sliceController.setVisible(False)
        sliceController.setSliceVisible(False)

        sliceView = sliceViewWidget.sliceView()
        sliceViewInteractorStyle = (
            sliceView.interactorObserver()
            if hasattr(sliceView, "interactorObserver")
            else sliceView.sliceViewInteractorStyle()
        )
        sliceViewInteractorStyle.SetActionEnabled(sliceViewInteractorStyle.Translate, False)
        sliceViewInteractorStyle.SetActionEnabled(sliceViewInteractorStyle.Zoom, False)
        sliceViewInteractorStyle.SetActionEnabled(sliceViewInteractorStyle.Rotate, False)
        sliceViewInteractorStyle.SetActionEnabled(sliceViewInteractorStyle.Blend, False)
        sliceViewInteractorStyle.SetActionEnabled(sliceViewInteractorStyle.BrowseSlice, False)
        sliceViewInteractorStyle.SetActionEnabled(sliceViewInteractorStyle.AdjustWindowLevelBackground, True)

        sliceViewInteractorStyle.RemoveAllObservers()
        interactor = sliceViewInteractorStyle.GetInteractor()

        self.observedInteractors.append(
            (interactor, interactor.AddObserver(vtk.vtkCommand.MouseWheelForwardEvent, self._on_scroll_forward))
        )

        self.observedInteractors.append(
            (interactor, interactor.AddObserver(vtk.vtkCommand.MouseWheelBackwardEvent, self._on_scroll_backwards))
        )

        sliceNode = sliceViewWidget.sliceLogic().GetSliceNode()
        sliceNode.SetRulerType(1)

        sliceNode.SetRulerColor(slicer.vtkMRMLAbstractViewNode.RulerColorBlack)
        viewName = self.getViewName(identifier)
        sliceView = slicer.app.layoutManager().sliceWidget(viewName).sliceView()
        sliceView.setBackgroundColor(qt.QColor("white"))

        # Disabling right-click mouse interaction on image log views
        displayableManager = sliceView.displayableManagerByClassName("vtkMRMLCrosshairDisplayableManager")
        sliceIntersectionWidget = displayableManager.GetSliceIntersectionWidget()
        sliceIntersectionWidget.SetEventTranslation(
            sliceIntersectionWidget.WidgetStateAny,
            slicer.vtkMRMLInteractionEventData.RightButtonClickEvent,
            vtk.vtkEvent.NoModifier,
            vtk.vtkWidgetEvent.NoEvent,
        )

        # Disabling the double left click event for slice view maximization
        sliceIntersectionWidget.SetEventTranslation(
            sliceIntersectionWidget.WidgetStateIdle,
            vtk.vtkCommand.LeftButtonDoubleClickEvent,
            vtk.vtkEvent.NoModifier,
            vtk.vtkWidgetEvent.NoEvent,
        )

    def setupAxisWidget(self):
        axisWidget = self.containerWidgets["axisWidget"]

        axisWidgetVerticalLayout = qt.QVBoxLayout(axisWidget)
        axisWidgetVerticalLayout.setContentsMargins(0, 40, 0, 0)
        axisWidgetVerticalLayout.setSpacing(0)

        scaleFrame = qt.QFrame()
        scaleLayout = qt.QHBoxLayout(scaleFrame)
        scaleLayout.setContentsMargins(0, 0, 0, 0)
        scaleLayout.setSpacing(0)
        scaleLabel = qt.QLabel("Scale: 1 /")
        scaleLabel.setFixedHeight(18)
        scaleLabel.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)
        scaleLayout.addWidget(scaleLabel)
        scaleInput = qt.QDoubleSpinBox()
        scaleInput.setObjectName("scaleInput")
        scaleInput.setRange(0.01, 100000)
        scaleInput.setValue(1)
        scaleInput.singleStep = 0.01
        scaleInput.setFixedWidth(90)
        scaleInput.setToolTip("Ratio of horizontal and vertical scale (View 1 as reference).")
        scaleInput.valueChanged.connect(self.onScaleInputValueChanged)
        scaleLayout.addWidget(scaleInput)
        axisWidgetVerticalLayout.addWidget(scaleFrame)

        axisWidgetFrame = qt.QFrame()
        axisWidgetLayout = qt.QHBoxLayout(axisWidgetFrame)
        axisWidgetLayout.setSpacing(0)
        axisWidgetVerticalLayout.addWidget(axisWidgetFrame)

        pysideQHBoxLayout = shiboken2.wrapInstance(hash(axisWidgetLayout), PySide2.QtWidgets.QHBoxLayout)
        pysideQHBoxLayout.setContentsMargins(0, 10, 0, 0)

        self.depthOverview = pg.GraphicsLayoutWidget()
        self.depthOverview.setBackground("#FFFFFF")
        pysideQHBoxLayout.addWidget(self.depthOverview, 0, PySide2.QtCore.Qt.AlignRight)

        self.depthOverviewAxisItem = DepthOverviewAxisItem()
        self.depthOverviewAxisItem.setStyle(tickTextOffset=2, autoReduceTextSpace=True, tickLength=-7, tickAlpha=128)
        self.depthOverviewAxisItem.setPen(color=(0, 0, 0))
        self.depthOverviewAxisItem.setTextPen(color=(0, 0, 0))
        self.depthOverviewRegion = pg.LinearRegionItem(orientation="horizontal")
        self.depthOverviewRegion.sigRegionChanged.connect(self.onDepthOverviewRegionChanged)
        self.depthOverviewPlot = pg.PlotItem(axisItems={"left": self.depthOverviewAxisItem}, enableMenu=False)
        self.depthOverviewPlot.addItem(self.depthOverviewRegion)
        self.depthOverviewPlot.setMouseEnabled(False, False)
        self.depthOverviewPlot.hideAxis("bottom")
        self.depthOverviewPlot.hideButtons()
        self.depthOverviewPlot.getViewBox().invertY(True)
        self.depthOverview.addItem(self.depthOverviewPlot)

        self.graphicsLayoutWidget = pg.GraphicsLayoutWidget()
        self.graphicsLayoutWidget.setBackground("#FFFFFF")
        pysideQHBoxLayout.addWidget(self.graphicsLayoutWidget, 0, PySide2.QtCore.Qt.AlignRight)
        self.axisItem = CustomAxisItem(self.delayedAdjustViewsVisibleRegion)
        self.axisItem.setStyle(tickTextOffset=4, tickLength=30)
        self.axisItem.setPen(color=(0, 0, 0))
        self.axisItem.setTextPen(color=(0, 0, 0))
        self.graphicsLayoutWidget.addItem(self.axisItem)
        axisWidget.setVisible(False)

    def setupViewColorBarWidgets(self):
        for identifier in self.getViewDataListIdentifiers():
            viewData = self.imageLogViewList[identifier].viewData
            primaryNode = self.getNodeById(viewData.primaryNodeId)

            viewColorBarWidget = self.viewColorBarWidgets[identifier]
            viewColorBarWidgetLayout = qt.QHBoxLayout(viewColorBarWidget)
            viewColorBarWidgetLayout.setContentsMargins(0, 0, 0, 0)

            if primaryNode is not None:
                if type(primaryNode) is slicer.vtkMRMLScalarVolumeNode:
                    colorBarWidget = ColorBarWidget()
                    colorBarWidget.setObjectName("colorBarWidget" + str(identifier))
                    viewColorBarWidgetLayout.addWidget(colorBarWidget)
                    if primaryNode.GetDisplayNode() is None:
                        primaryNode.CreateDefaultDisplayNodes()
                    displayNode = primaryNode.GetDisplayNode()
                    observerID = displayNode.AddObserver(
                        "ModifiedEvent", lambda display, event, identifier_=identifier: self.updateColorBar(identifier_)
                    )
                    self.observedDisplayNodes.append([displayNode, observerID])
                    colorBarWidget.setColorTableNode(displayNode.GetColorNode())
                    displayNode.Modified()  # To update the color bar

                elif type(primaryNode) is slicer.vtkMRMLLabelMapVolumeNode:
                    viewColorBarWidgetLayout.addSpacerItem(qt.QSpacerItem(0, 41))

                elif viewData.secondaryTableNodeColumn == "" or viewData.primaryTableHistogram:
                    viewColorBarWidgetLayout.addSpacerItem(qt.QSpacerItem(0, 20))

    ########################################################################################################################################
    # Widgets populate
    ########################################################################################################################################

    def populateViewsInterface(self):
        self.populateViewControllerWidgets()
        self.populateViewWidgets()

    def populateViewControllerWidgets(self):
        """
        Populates view controllers with already filled data.
        """
        for identifier in self.getViewDataListIdentifiers():
            viewData = self.imageLogViewList[identifier].viewData

            if identifier >= len(self.viewControllerWidgets):
                continue

            viewControllerWidget = self.viewControllerWidgets[identifier]
            viewLabel = viewControllerWidget.findChild(qt.QLabel, "viewLabel" + str(identifier))
            primaryNode = self.getNodeById(viewData.primaryNodeId)
            if primaryNode is not None:
                if type(viewData) is GraphicViewData and self.getNodeById(viewData.secondaryTableNodeId):
                    viewLabel.setText(
                        f"{primaryNode.GetName()} / {self.getNodeById(viewData.secondaryTableNodeId).GetName()}"
                    )
                else:
                    viewLabel.setText(primaryNode.GetName())

            settingsToolButton = viewControllerWidget.findChild(qt.QToolButton, "settingsToolButton" + str(identifier))
            settingsToolButton.setChecked(viewData.viewControllerSettingsToolButtonToggled)

            settingsPopup = viewControllerWidget.findChild(ctk.ctkPopupWidget, "settingsPopup" + str(identifier))
            settingsPopup.setVisible(viewData.viewControllerSettingsToolButtonToggled)

        self.populatePrimaryNodeInterfaceItems()
        self.populateSegmentationNodeInterfaceItems()
        self.populateProportionsNodeInterfaceItems()
        self.populateSecondaryTableNodeInterfaceItems()

    def populateViewWidgets(self):
        """
        Populates views with already filled data.
        """
        self.configureSliceViewsAllowedSegmentationNodes()

        self.updateScaleRatio()

        for identifier in self.getViewDataListIdentifiers():
            view = self.imageLogViewList[identifier]
            viewData = view.viewData
            viewWidget = self.viewWidgets[identifier]
            primaryNode = self.getNodeById(viewData.primaryNodeId)
            if primaryNode is None:
                continue

            view.setup_widget(viewWidget)
            view.widget.signalUpdated.connect(self.refreshViews)
            if isinstance(viewData, GraphicViewData):
                self.curvePlotWidgets[identifier] = view.widget.getPlot()

    def populatePrimaryNodeInterfaceItems(self):
        for identifier in self.getViewDataListIdentifiers():
            viewData = self.imageLogViewList[identifier].viewData
            viewControllerWidget = self.viewControllerWidgets[identifier]

            from ltrace.slicer.widget.filtered_node_combo_box import FilteredNodeComboBox

            primaryNodeComboBox = viewControllerWidget.findChild(
                FilteredNodeComboBox, "primaryNodeComboBox" + str(identifier)
            )
            primaryNodeComboBox.blockSignals(True)
            primaryNodeComboBox.setCurrentNodeID(viewData.primaryNodeId)
            primaryNodeComboBox.blockSignals(False)

            # Show/hide button state
            showHidePrimaryNodeButton = viewControllerWidget.findChild(
                qt.QPushButton, "showHidePrimaryNodeButton" + str(identifier)
            )
            if showHidePrimaryNodeButton is not None:
                showHidePrimaryNodeButton.blockSignals(True)
                if viewData.primaryNodeHidden:
                    showHidePrimaryNodeButton.setChecked(True)
                    showHidePrimaryNodeButton.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeClosed.png"))
                else:
                    showHidePrimaryNodeButton.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeOpen.png"))
                showHidePrimaryNodeButton.blockSignals(False)

            primaryTableNodeColumnComboBox = viewControllerWidget.findChild(
                qt.QComboBox, "primaryTableNodeColumnComboBox" + str(identifier)
            )
            if primaryTableNodeColumnComboBox is not None:
                primaryTableNode = self.getNodeById(viewData.primaryNodeId)
                primaryTableNodeColumnComboBox.blockSignals(True)
                primaryTableNodeColumnComboBox.addItem("")
                primaryTableNodeColumnComboBox.addItems(viewData.primaryTableNodeColumnList)
                primaryTableNodeColumnComboBox.setCurrentText(viewData.primaryTableNodeColumn)
                primaryTableNodeColumnComboBox.blockSignals(False)

            primaryTableNodePlotTypeComboBox = viewControllerWidget.findChild(
                qt.QComboBox, "primaryTableNodePlotTypeComboBox" + str(identifier)
            )
            if primaryTableNodePlotTypeComboBox is not None:
                primaryTableNodePlotTypeComboBox.blockSignals(True)
                for key, value in PLOT_TYPE_SYMBOLS.items():
                    primaryTableNodePlotTypeComboBox.addItem(key, value)
                self.setComboBoxIndexByData(primaryTableNodePlotTypeComboBox, viewData.primaryTableNodePlotType)
                if viewData.primaryTableHistogram:
                    primaryTableNodePlotTypeComboBox.setDisabled(True)
                primaryTableNodePlotTypeComboBox.blockSignals(False)

            primaryTableNodePlotColorPicker = viewControllerWidget.findChild(
                ColorPickerCell, "primaryTableNodePlotColorPicker" + str(identifier)
            )
            if primaryTableNodePlotColorPicker is not None:
                primaryTableNodeColumnComboBox.blockSignals(True)
                primaryTableNodePlotColorPicker.setColor(viewData.primaryTableNodePlotColor)
                if viewData.primaryTableHistogram:
                    primaryTableNodePlotColorPicker.setHistogramScaleValue(viewData.primaryTableScaleHistogram)
                    primaryTableNodePlotColorPicker.setHistogramMode(True)
                primaryTableNodeColumnComboBox.blockSignals(False)

    def populateSecondaryTableNodeInterfaceItems(self):
        for identifier in self.getViewDataListIdentifiers():
            viewData = self.imageLogViewList[identifier].viewData
            viewControllerWidget = self.viewControllerWidgets[identifier]

            from ltrace.slicer.widget.filtered_node_combo_box import FilteredNodeComboBox

            secondaryTableNodeComboBox = viewControllerWidget.findChild(
                FilteredNodeComboBox, "secondaryTableNodeComboBox" + str(identifier)
            )
            if secondaryTableNodeComboBox is not None:
                secondaryTableNodeComboBox.blockSignals(True)
                secondaryTableNodeComboBox.setCurrentNodeID(viewData.secondaryTableNodeId)
                secondaryTableNodeComboBox.blockSignals(False)

            secondaryTableNodeColumnComboBox = viewControllerWidget.findChild(
                qt.QComboBox, "secondaryTableNodeColumnComboBox" + str(identifier)
            )
            if secondaryTableNodeColumnComboBox is not None:
                secondaryTableNode = self.getNodeById(viewData.secondaryTableNodeId)
                if secondaryTableNode is not None:
                    secondaryTableNodeColumnComboBox.blockSignals(True)
                    secondaryTableNodeColumnComboBox.addItem("")
                    secondaryTableNodeColumnComboBox.addItems(viewData.secondaryTableNodeColumnList)
                    secondaryTableNodeColumnComboBox.setCurrentText(viewData.secondaryTableNodeColumn)
                    secondaryTableNodeColumnComboBox.blockSignals(False)

            secondaryTableNodePlotTypeComboBox = viewControllerWidget.findChild(
                qt.QComboBox, "secondaryTableNodePlotTypeComboBox" + str(identifier)
            )
            if secondaryTableNodePlotTypeComboBox is not None:
                secondaryTableNodePlotTypeComboBox.blockSignals(True)
                for key, value in PLOT_TYPE_SYMBOLS.items():
                    secondaryTableNodePlotTypeComboBox.addItem(key, value)
                self.setComboBoxIndexByData(secondaryTableNodePlotTypeComboBox, viewData.secondaryTableNodePlotType)
                secondaryTableNodePlotTypeComboBox.blockSignals(False)

            secondaryTableNodePlotColorPicker = viewControllerWidget.findChild(
                ColorPickerCell, "secondaryTableNodePlotColorPicker" + str(identifier)
            )
            if secondaryTableNodePlotColorPicker is not None:
                secondaryTableNodeColumnComboBox.blockSignals(True)
                secondaryTableNodePlotColorPicker.setColor(viewData.secondaryTableNodePlotColor)
                secondaryTableNodeColumnComboBox.blockSignals(False)

    def populateSegmentationNodeInterfaceItems(self):
        for identifier in self.getViewDataListIdentifiers():
            viewData = self.imageLogViewList[identifier].viewData
            viewControllerWidget = self.viewControllerWidgets[identifier]
            segmentationNodeComboBox = viewControllerWidget.findChild(
                slicer.qMRMLNodeComboBox, "segmentationNodeComboBox" + str(identifier)
            )
            if segmentationNodeComboBox is not None:
                segmentationNodeComboBox.blockSignals(True)
                segmentationNodeComboBox.setCurrentNode(self.getNodeById(viewData.segmentationNodeId))
                segmentationNodeComboBox.blockSignals(False)

            # Show/hide button state
            showHideSegmentationNodeButton = viewControllerWidget.findChild(
                qt.QToolButton, "showHideSegmentationNodeButton" + str(identifier)
            )
            if showHideSegmentationNodeButton is not None:
                showHideSegmentationNodeButton.blockSignals(True)
                if viewData.segmentationNodeHidden:
                    showHideSegmentationNodeButton.setChecked(True)
                    showHideSegmentationNodeButton.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeClosed.png"))
                else:
                    showHideSegmentationNodeButton.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeOpen.png"))
                showHideSegmentationNodeButton.blockSignals(False)

    def populateProportionsNodeInterfaceItems(self):
        for identifier in self.getViewDataListIdentifiers():
            viewData = self.imageLogViewList[identifier].viewData
            if type(viewData) is SliceViewData:
                viewControllerWidget = self.viewControllerWidgets[identifier]
                proportionsNodeLineEdit = viewControllerWidget.findChild(
                    qt.QLineEdit, "proportionsNodeLineEdit" + str(identifier)
                )

                proportionsNode = self.getNodeById(self.imageLogViewList[identifier].viewData.proportionsNodeId)
                if proportionsNode is not None:
                    proportionsNodeLineEdit.setText(proportionsNode.GetName())
                else:
                    proportionsNodeLineEdit.setText("None")

                # Show/hide button state
                showHideProportionsNodeButton = viewControllerWidget.findChild(
                    qt.QPushButton, "showHideProportionsNodeButton" + str(identifier)
                )
                if showHideProportionsNodeButton is not None:
                    showHideProportionsNodeButton.blockSignals(True)
                    if viewData.proportionsNodeHidden:
                        showHideProportionsNodeButton.setChecked(True)
                        showHideProportionsNodeButton.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeClosed.png"))
                    else:
                        showHideProportionsNodeButton.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeOpen.png"))
                    showHideProportionsNodeButton.blockSignals(False)

    ########################################################################################################################################
    # Other
    ########################################################################################################################################

    def refreshViews(self, source=None, interval_ms=50):
        """
        Handles timer to refresh views.
        """
        env = getCurrentEnvironment()
        if self.debug:
            print("refreshViews:", source, env)
        if env.value not in self.ALLOWED_ENVIRONMENTS_FOR_LAYOUT:
            return

        self.__delayedRefreshViews()

    def __refreshViews(self, source=None):
        """
        Refreshes all the views with the current data.
        Don't call this method directly. Use the 'refreshViews' method instead.
        """
        self.cleanUp()
        self.registerLayout(self.generateLayout())
        self.setupToolBar()
        self.setupViewControllerWidgets()
        self.setupViewWidgets()
        # self.setupViewSpacerWidgets()
        self.populateViewsInterface()
        self.setupAxisWidget()
        self.setupViewColorBarWidgets()
        self.setupSpacerWidget()
        self.delayedAdjustViewsVisibleRegion()
        self.delayedReloadImageLogSegmentEditorEffect()
        self.delayedAddGraphicViewsConnections()
        self.delayedAddPrimaryNodeObservers()
        self.updateDepthOverviewScale()
        self.__updateToolBarVisibility()
        self.imageLogLayoutViewAction.setData(slicer.modules.AppContextInstance.imageLogLayoutId)
        self.viewsRefreshed.emit()

    def setupToolBar(self):
        toolBarWidget = self.containerWidgets["toolBarWidget"]
        layout = qt.QHBoxLayout(toolBarWidget)
        layout.setContentsMargins(0, 2, 0, 0)

        # Fit button
        fitButton = qt.QPushButton()
        fitButton.setObjectName("Fit All Button")
        fitButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Fit.png"))
        fitButton.clicked.connect(self.fit)
        fitButton.setFixedWidth(25)
        fitButton.setToolTip("Reset the views to fit all data.")

        # Adjust to real aspect ratio button
        fitRealAspectRatio = qt.QPushButton()
        fitRealAspectRatio.setObjectName("Fit Real Button")
        fitRealAspectRatio.setIcon(qt.QIcon(getResourcePath("Icons") / "FitRealAspectRatio.png"))
        fitRealAspectRatio.clicked.connect(lambda state: self.fitToAspectRatio())
        fitRealAspectRatio.setFixedWidth(25)
        fitRealAspectRatio.setToolTip("Adjust the views to their real aspect ratio.")

        # Add view button
        addViewButton = qt.QPushButton("Add view")
        addViewButton.setObjectName("Add view button")
        addViewButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Add.png"))
        addViewButton.clicked.connect(self.addViewClicked)

        # Mouse physical coordinates on Slice/Graphic view
        label = qt.QLabel()
        label.setObjectName("MousePhysicalCoordinates")

        layout.addWidget(fitButton, 0, qt.Qt.AlignTop | qt.Qt.AlignLeft)
        layout.addWidget(fitRealAspectRatio, 0, qt.Qt.AlignTop | qt.Qt.AlignLeft)
        layout.addWidget(addViewButton, 0, qt.Qt.AlignTop | qt.Qt.AlignLeft)
        layout.addWidget(label, 0, qt.Qt.AlignTop | qt.Qt.AlignLeft)
        layout.addStretch(1)

    def setupSpacerWidget(self):
        """Setup auxiliary widget to organize the slice views display."""
        spacerWidget = self.containerWidgets["spacerWidget"]
        layout = qt.QHBoxLayout(spacerWidget)
        layout.setContentsMargins(0, 0, 0, 0)
        totalViews = len(self.imageLogViewList)
        if totalViews < 2:
            layout.addStretch(1)

    def delayedAddPrimaryNodeObservers(self):
        qt.QTimer.singleShot(self.REFRESH_DELAY, self.addPrimaryNodeObservers)

    def addPrimaryNodeObservers(self):
        for identifier in self.getViewDataListIdentifiers():
            viewData = self.imageLogViewList[identifier].viewData
            primaryNode = self.getNodeById(viewData.primaryNodeId)
            if primaryNode is not None:
                observerID = primaryNode.AddObserver(
                    "ModifiedEvent", lambda display, event, identifier_=identifier: self.updateViewLabel(identifier_)
                )
                self.observedPrimaryNodes.append([primaryNode, observerID])

    def updateViewLabel(self, identifier):
        if identifier >= len(self.imageLogViewList) or identifier >= len(self.viewControllerWidgets):
            return

        view = self.imageLogViewList[identifier]
        if view is None:
            return

        viewData = view.viewData
        viewControllerWidget = self.viewControllerWidgets[identifier]
        viewLabel = viewControllerWidget.findChild(qt.QLabel, "viewLabel" + str(identifier))
        primaryNode = self.getNodeById(viewData.primaryNodeId)
        if primaryNode is not None:
            viewLabel.setText(primaryNode.GetName())

    def delayedAddGraphicViewsConnections(self):
        qt.QTimer.singleShot(self.REFRESH_DELAY, self.addGraphicViewsConnections)

    def addGraphicViewsConnections(self):
        for curvePlotWidget in self.curvePlotWidgets:
            if curvePlotWidget is not None:
                curvePlotWidget.blockSignals(True)
                if isinstance(curvePlotWidget, CurvePlot):
                    # self.currentRange works with bottom depth and top depth, so reverse the order from [y_min,y_max] to [y_max,y_min]
                    curvePlotWidget.signal_range_changed_manually.connect(
                        lambda view_range: self.onGraphicViewRangeChange(view_range[::-1])
                    )
                curvePlotWidget.signal_y_range_changed.connect(
                    lambda _, view_range: self.onGraphicViewRangeChange(view_range[::-1])
                )
        for curvePlotWidget in self.curvePlotWidgets:
            if curvePlotWidget is not None:
                curvePlotWidget.blockSignals(False)

    def delayedReloadImageLogSegmentEditorEffect(self):
        qt.QTimer.singleShot(self.REFRESH_DELAY, self.reloadImageLogSegmentEditorEffect)

    def reloadImageLogSegmentEditorEffect(self):
        """
        Reloads the effect to avoid a bug related to the effect activation on the new segmentation and/or master volume.
        """
        if not hasattr(self, "ImageLogSegmentEditorWidget"):
            return

        try:
            segmentEditorWidget = slicer.util.getModuleWidget("ImageLogSegmentEditor").segmentEditorWidget
        except ValueError:
            # ImageLogSegmentEditorWidget was deleted
            return
        activeEffect = segmentEditorWidget.activeEffect()
        segmentEditorWidget.setActiveEffectByName("None")
        segmentEditorWidget.setActiveEffect(activeEffect)

    def cleanUp(self):
        if len(self.imageLogViewList) == 0:
            self.currentRange = None

        self.removeAllObservers()
        self.nodeAboutToBeRemoved = False
        for viewControllerWidget in self.viewControllerWidgets:
            self.deleteWidget(viewControllerWidget)
        for viewColorBarWidget in self.viewColorBarWidgets:
            self.deleteWidget(viewColorBarWidget)
        # TODO (PL-1944): Fix crashes with Histogram in Depth plot. The code below is commented to avoid the application' crash.
        # for viewWidget in self.viewWidgets:
        #     if type(viewWidget) is not slicer.qMRMLSliceWidget:
        #         self.deleteWidget(viewWidget)
        # for viewSpacerWidget in self.viewSpacerWidgets:
        #     self.deleteWidget(viewSpacerWidget)
        # for curvePlotWidget in self.curvePlotWidgets:
        #     self.deleteWidget(curvePlotWidget)
        # for containerWidget in self.containerWidgets:
        #     self.deleteWidget(containerWidget)

    def deleteWidget(self, widget):
        try:
            widget.delete()
        except Exception as error:
            logging.debug(error)

    def removeAllObservers(self) -> None:
        for observerList in [self.observedDisplayNodes, self.observedPrimaryNodes, self.observedInteractors]:
            for obj, tag in observerList:
                obj.RemoveObserver(tag)

            observerList.clear()

    def updateColorBar(self, identifier):
        displayNode = self.getViewPrimaryNode(identifier).GetDisplayNode()
        viewColorBarWidget = self.viewColorBarWidgets[identifier]
        colorBarWidget = viewColorBarWidget.findChild(ColorBarWidget, "colorBarWidget" + str(identifier))
        if colorBarWidget is not None:
            colorBarWidget.updateInformation(displayNode.GetWindow(), displayNode.GetLevel())
            colorBarWidget.setColorTableNode(displayNode.GetColorNode())

    def addView(self, selectedNode=None):
        nodeName = selectedNode.GetName() if selectedNode is not None else "None"
        if len(self.imageLogViewList) >= self.MAXIMUM_NUMBER_OF_VIEWS:
            slicer.app.layoutManager().setLayout(
                slicer.modules.AppContextInstance.imageLogLayoutId
            )  # In case there is other layout selected
            raise ImageLogDataInfo("The maximum number of views was reached.")

        # defaults
        isVolumeNode = False
        isSegmentationNode = False
        isTableNode = False

        if selectedNode is not None:
            isVolumeNode = isinstance(selectedNode, slicer.vtkMRMLVolumeNode)
            isSegmentationNode = isinstance(selectedNode, slicer.vtkMRMLSegmentationNode)
            isTableNode = isinstance(selectedNode, slicer.vtkMRMLTableNode)

        self.imageLogViewList.append(None)
        identifier = len(self.imageLogViewList) - 1
        if isVolumeNode or isTableNode:
            self.imageLogViewList[identifier] = ImageLogView(selectedNode)

        elif isSegmentationNode:
            primaryNode = selectedNode.GetNodeReference("referenceImageGeometryRef")
            self.imageLogViewList[identifier] = ImageLogView(primaryNode)
            self.imageLogViewList[identifier].set_new_segmentation_node(selectedNode)
        else:
            # creates everything else and refreshs
            self.imageLogViewList[identifier] = ImageLogView(selectedNode)

        if self.imageLogViewList[identifier] is None:
            self.imageLogViewList[identifier] = ImageLogView(None)

        self.refreshViews("AddView")

    def removeViewFromPrimaryNode(self, nodeId: str) -> None:
        if nodeId is None:
            return

        viewRemoved = False

        for identifier in self.getViewDataListIdentifiers()[::-1]:
            view = self.imageLogViewList[identifier]
            if view is None:
                continue

            viewData = view.viewData
            primaryNodeId = viewData.primaryNodeId
            if primaryNodeId != nodeId:
                continue

            viewRemoved = True
            self.removeView(identifier, refresh=False)

        if viewRemoved:
            self.refreshViews("removeViewFromPrimaryNode")

    def removeView(self, identifier, refresh=True):
        if identifier < len(self.imageLogViewList):
            del self.imageLogViewList[identifier]

        if refresh:
            self.refreshViews("removeView")

    def primaryNodeChanged(self, identifier, node):
        """The first node combo box of a view determines the primary node. The primary node type determines the type of the view."""
        if not self.nodeAboutToBeRemoved:
            if identifier < len(self.imageLogViewList):
                self.imageLogViewList[identifier] = ImageLogView(node)
            self.refreshViews("primaryNodeChanged")

    def secondaryTableNodeChanged(self, identifier, node):
        if not self.nodeAboutToBeRemoved:
            if identifier < len(self.imageLogViewList):
                self.imageLogViewList[identifier].set_new_secondary_node(node)
            self.refreshViews("secondaryTableNodeChanged")

    def segmentationNodeChanged(self, identifier, segmentationNode):
        if not self.nodeAboutToBeRemoved:
            if identifier < len(self.imageLogViewList):
                self.imageLogViewList[identifier].set_new_segmentation_node(segmentationNode)
            self.refreshViews("segmentationNodeChanged")

    def primaryTableNodeColumnChanged(self, identifier):
        if identifier < len(self.imageLogViewList):
            viewData = self.imageLogViewList[identifier].viewData
            viewControllerWidget = self.viewControllerWidgets[identifier]
            primaryTableNodeColumnComboBox = viewControllerWidget.findChild(
                qt.QComboBox, "primaryTableNodeColumnComboBox" + str(identifier)
            )
            viewData.primaryTableNodeColumn = primaryTableNodeColumnComboBox.currentText
        self.refreshViews("primaryTableNodeColumnChanged")

    def primaryTableNodePlotColorChanged(self, identifier, color, scaleHistogram=None):
        if identifier < len(self.imageLogViewList):
            viewData = self.imageLogViewList[identifier].viewData
            viewData.primaryTableNodePlotColor = color
            viewData.primaryTableScaleHistogram = scaleHistogram
        self.refreshViews("primaryTableNodePlotColorChanged")

    def primaryTableNodePlotTypeChanged(self, identifier):
        if identifier < len(self.imageLogViewList):
            viewData = self.imageLogViewList[identifier].viewData
            viewControllerWidget = self.viewControllerWidgets[identifier]
            primaryTableNodePlotTypeComboBox = viewControllerWidget.findChild(
                qt.QComboBox, "primaryTableNodePlotTypeComboBox" + str(identifier)
            )
            viewData.primaryTableNodePlotType = primaryTableNodePlotTypeComboBox.currentData
        self.refreshViews("primaryTableNodePlotTypeChanged")

    def secondaryTableNodeColumnChanged(self, identifier):
        if identifier < len(self.imageLogViewList):
            viewData = self.imageLogViewList[identifier].viewData
            viewControllerWidget = self.viewControllerWidgets[identifier]
            secondaryTableNodeColumnComboBox = viewControllerWidget.findChild(
                qt.QComboBox, "secondaryTableNodeColumnComboBox" + str(identifier)
            )
            viewData.secondaryTableNodeColumn = secondaryTableNodeColumnComboBox.currentText
        self.refreshViews("secondaryTableNodeColumnChanged")

    def secondaryTableNodePlotColorChanged(self, identifier, color):
        if identifier < len(self.imageLogViewList):
            viewData = self.imageLogViewList[identifier].viewData
            viewData.secondaryTableNodePlotColor = color
        self.refreshViews("secondaryTableNodePlotColorChanged")

    def secondaryTableNodePlotTypeChanged(self, identifier):
        if identifier < len(self.imageLogViewList):
            viewData = self.imageLogViewList[identifier].viewData
            viewControllerWidget = self.viewControllerWidgets[identifier]
            secondaryTableNodePlotTypeComboBox = viewControllerWidget.findChild(
                qt.QComboBox, "secondaryTableNodePlotTypeComboBox" + str(identifier)
            )
            viewData.secondaryTableNodePlotType = secondaryTableNodePlotTypeComboBox.currentData
        self.refreshViews("secondaryTableNodePlotTypeChanged")

    def configureSliceViewsAllowedSegmentationNodes(self):
        # Removing all view node ids from the image log segmentation nodes
        segmentationNodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
        for segmentationNode in segmentationNodes:
            if segmentationNode.GetAttribute("ImageLogSegmentation") == "True":
                segmentationNode.CreateDefaultDisplayNodes()
                displayNode = segmentationNode.GetDisplayNode()
                displayNode.RemoveAllViewNodeIDs()
                displayNode.AddViewNodeID("NoViews")

        for identifier in self.getViewDataListIdentifiers():
            viewData = self.imageLogViewList[identifier].viewData
            if type(viewData) is SliceViewData:
                segmentationNode = self.getNodeById(viewData.segmentationNodeId)
                if segmentationNode is not None and viewData.segmentationNodeHidden == False:
                    displayNode = segmentationNode.GetDisplayNode()
                    displayNode.AddViewNodeID(self.viewWidgets[identifier].sliceLogic().GetSliceNode().GetID())

    def segmentationNodeOrSourceVolumeNodeChanged(self, segmentationNode=None, sourceVolumeNode=None):
        self.configureSliceViewsAllowedSegmentationNodes()

        # Preparing basic views when initializing a segmentation, if no views are present
        prepareBasicViews = False
        if segmentationNode is None or sourceVolumeNode is None:
            return

        if len(self.imageLogViewList) == 0:
            prepareBasicViews = True

        if not prepareBasicViews:
            msg_box = qt.QMessageBox(slicer.modules.AppContextInstance.mainWindow)
            msg_box.setIcon(qt.QMessageBox.Question)
            msg_box.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.No)
            msg_box.setDefaultButton(qt.QMessageBox.Yes)

            msg_box.text = (
                "Would you like to edit the segmentation in a 3-view layout? This will reset any current views."
            )
            msg_box.setWindowTitle("Reset layout")
            result = msg_box.exec()
            prepareBasicViews = result == qt.QMessageBox.Yes

        # Three basic views, one with primary node and segmentation, one with segmentation only and one with segmentation proportions
        if prepareBasicViews:
            self.imageLogViewList.clear()
            for i in range(3):
                self.imageLogViewList.append(ImageLogView(sourceVolumeNode, segmentationNode))
            self.__refreshViews("segmentationNodeOrSourceVolumeNodeChanged")
            slicer.app.processEvents(1000)
            identifier = 1
            viewControllerWidget = self.viewControllerWidgets[identifier]
            showHidePrimaryNodeButton = viewControllerWidget.findChild(
                qt.QPushButton, "showHidePrimaryNodeButton" + str(identifier)
            )
            showHidePrimaryNodeButton.click()
            slicer.app.processEvents(1000)
            identifier = 2
            # Hack - click 3 times
            for i in range(3):
                viewControllerWidget = self.viewControllerWidgets[identifier]
                showHideProportionsNodeButton = viewControllerWidget.findChild(
                    qt.QPushButton, "showHideProportionsNodeButton" + str(identifier)
                )
                showHideProportionsNodeButton.click()
                slicer.app.processEvents(1000)

    def addInpaintView(self, segmentationNode1=None, segmentationNode2=None, sourceVolumeNode=None):
        self.configureSliceViewsAllowedSegmentationNodes()

        if len(self.imageLogViewList) != 2:
            for id in range(len(self.imageLogViewList) - 1, -1, -1):
                self.removeView(id)

            self.imageLogViewList.append(ImageLogView(sourceVolumeNode, segmentationNode1))
            self.imageLogViewList.append(ImageLogView(sourceVolumeNode, segmentationNode2))
        else:
            self.imageLogViewList[0] = ImageLogView(sourceVolumeNode, segmentationNode1)
            self.imageLogViewList[1] = ImageLogView(sourceVolumeNode, segmentationNode2)

        self.__refreshViews("addInpaintView")

        viewControllerWidget = self.viewControllerWidgets[1]

        showHidePrimaryNodeButton = viewControllerWidget.findChild(qt.QPushButton, "showHidePrimaryNodeButton" + str(1))
        showHidePrimaryNodeButton.click()

    def getViewName(self, identifier):
        return self.imageLogViewList[identifier].viewData.VIEW_NAME_PREFIX + str(identifier)

    def getViewControllerName(self, identifier):
        return self.imageLogViewList[identifier].viewData.VIEW_NAME_PREFIX + "Controller" + str(identifier)

    def getViewColorBarName(self, identifier):
        return self.imageLogViewList[identifier].viewData.VIEW_NAME_PREFIX + "ColorBar" + str(identifier)

    def getViewSpacerName(self, identifier):
        return self.imageLogViewList[identifier].viewData.VIEW_NAME_PREFIX + "Spacer" + str(identifier)

    def getViewDataListIdentifiers(self):
        return [i for i in range(len(self.imageLogViewList))]

    def getViewPrimaryNode(self, identifier):
        return self.getNodeById(self.imageLogViewList[identifier].viewData.primaryNodeId)

    def adjustViewsVisibleRegion(self):
        """
        Iterates through the viewDataList and sets currentRange to the full data if it is None, or set the corresponding view range to
        currentRange.
        """
        for identifier in self.getViewDataListIdentifiers():
            if identifier >= len(self.imageLogViewList) or identifier >= len(self.viewWidgets):
                continue

            imageLogView = self.imageLogViewList[identifier]
            if imageLogView is None or imageLogView.widget is None:
                continue

            if self.currentRange is None:
                bounds = imageLogView.widget.getBounds()
                self.currentRange = [-1 * bounds[0], -1 * bounds[1]]

            imageLogView.widget.set_range(self.currentRange)
        self.updateViewsAxis("adjustViewsVisibleRegion")

    def _on_scroll_forward(self, interactorStyle, *args):
        if interactorStyle.GetControlKey():
            self.scaleSliceFieldOfViewForAllViews(-1)
        else:
            self.translateSliceOriginForAllViews(1)

    def _on_scroll_backwards(self, interactorStyle, *args):
        if interactorStyle.GetControlKey():
            self.scaleSliceFieldOfViewForAllViews(1)
        else:
            self.translateSliceOriginForAllViews(-1)

    def onGraphicViewRangeChange(self, range):
        # if a method passes the top depth greater than the bottom depth, it is invalid, return
        if range[1] > range[0]:
            return
        # prevent multiple updates if the values are close
        if self.currentRange is not None and np.allclose(self.currentRange, range, 1e-10):
            return
        self.currentRange = list(range)
        self.updateViewsAxis("onGraphicViewRangeChange")
        for identifier in self.getViewDataListIdentifiers():
            imageLogView = self.imageLogViewList[identifier]
            if imageLogView is None or imageLogView.widget is None:
                continue
            self.imageLogViewList[identifier].widget.set_range(self.currentRange)
        self.updateScaleRatio()

    def onScaleInputValueChanged(self, value):
        self.fitToAspectRatio(1 / value)

    def fitToAspectRatio(self, aspectRatio=1):
        for viewWidget in self.viewWidgets:
            if type(viewWidget) is slicer.qMRMLSliceWidget:
                sliceLogic = viewWidget.sliceLogic()
                sliceNode = sliceLogic.GetSliceNode()
                fieldOfView = sliceNode.GetFieldOfView()
                windowSizeFactor = sliceNode.GetDimensions()[0] / sliceNode.GetDimensions()[1]
                if windowSizeFactor == 0 or aspectRatio == 0:
                    continue

                sliceNode.SetFieldOfView(fieldOfView[0], (fieldOfView[0] / windowSizeFactor) / aspectRatio, 1)
                xyToRAS = sliceNode.GetXYToRAS()
                dimensions = sliceNode.GetDimensions()
                bottom = -1 * xyToRAS.MultiplyPoint((0, 0, 0, 1))[2]
                top = -1 * xyToRAS.MultiplyPoint((dimensions[0], dimensions[1], 0, 1))[2]
                self.currentRange = [bottom, top]
                break
        self.delayedAdjustViewsVisibleRegion()

    def updateScaleRatio(self):
        for viewWidget in self.viewWidgets:
            if type(viewWidget) is slicer.qMRMLSliceWidget:
                sliceLogic = viewWidget.sliceLogic()
                sliceNode = sliceLogic.GetSliceNode()
                dimensions = sliceNode.GetDimensions()
                fov = sliceNode.GetFieldOfView()
                windowSizeFactor = dimensions[0] / dimensions[1] if dimensions[1] != 0 else 1
                scaleRatioDenominator = windowSizeFactor / (fov[0] / fov[1]) if 0 not in fov else 0
                sliceLogic.SetAspectRatio(1 / scaleRatioDenominator)
                axisWidget = self.containerWidgets["axisWidget"]
                scaleInput = axisWidget.findChild(qt.QDoubleSpinBox, "scaleInput")
                if scaleInput:
                    # progammatically updating the gui information about the scale, no need to send signals.
                    scaleInput.blockSignals(True)
                    scaleInput.setValue(scaleRatioDenominator)
                    scaleInput.blockSignals(False)
                break

    def setDepth(self, depth):
        if self.currentRange is not None:
            fieldOfView = self.currentRange[0] - self.currentRange[1]
            top = depth - fieldOfView / 2
            bottom = depth + fieldOfView / 2
            self.onGraphicViewRangeChange((bottom, top))

    def translateSliceOriginForAllViews(self, direction):
        field_of_view = self.currentRange[0] - self.currentRange[1]
        offset = -1 * direction * (field_of_view / 500) * self.translationSpeed**3
        bottom = self.currentRange[0] + offset
        top = self.currentRange[1] + offset
        self.onGraphicViewRangeChange((bottom, top))

    def scaleSliceFieldOfViewForAllViews(self, direction):
        field_of_view = self.currentRange[0] - self.currentRange[1]
        mid_point = self.currentRange[1] + field_of_view / 2
        field_of_view = field_of_view * (1 + direction * 0.01 * self.scalingSpeed**2)
        bottom = mid_point + field_of_view / 2
        top = mid_point - field_of_view / 2
        self.onGraphicViewRangeChange((bottom, top))

    def updateViewsAxis(self, source=None):
        if self.debug:
            print("updateViewsAxis:", source)

        # Only show axis if there is data visible (slice view or graphic view)
        contentViewDataPresent = False
        for imageLogView in self.imageLogViewList:
            if imageLogView is None:
                continue

            viewData = imageLogView.viewData
            if viewData.primaryNodeId is not None:
                if type(viewData) is SliceViewData:
                    contentViewDataPresent = True
                elif type(viewData) is GraphicViewData and (
                    viewData.primaryTableNodeColumn != "" or viewData.secondaryTableNodeColumn != ""
                ):
                    contentViewDataPresent = True

        if self.currentRange is not None and contentViewDataPresent:
            size = 20 + int(self.graphicsLayoutWidget.fontMetrics().width("+0000.0 m"))
            self.graphicsLayoutWidget.setMinimumWidth(size)
            self.graphicsLayoutWidget.setMaximumWidth(size)
            self.containerWidgets["axisWidget"].setVisible(True)

            bottom = self.currentRange[0] / 1000
            top = self.currentRange[1] / 1000
            try:
                log = math.floor(math.log(bottom - top, 5))
                interval = 5 ** (log - 1)
            except ValueError:
                interval = 0.01

            convertion = 1
            unit = "m"
            if interval < 0.1:
                convertion = 100
                unit = "cm"

            # int(x * 10**N) / 10**N to remove decimal digits past the Nth (N >= 2)
            rounding_digits = max(2, math.ceil(-math.log(interval, 10)))
            rounder = 10**rounding_digits

            start = int(math.ceil(top / interval) * interval * rounder) / rounder
            end = int(math.floor(bottom / interval) * interval * rounder) / rounder
            n_of_ticks = max(round((end - start) / interval) + 1, 5)

            ticks = np.linspace(end, start, num=n_of_ticks)
            dx = [(value, "{:.2f} {:}".format(value * convertion, unit)) for value in ticks]
            self.axisItem.setTicks([dx, []])
            self.axisItem.setRange(bottom, top)
            self.setDepthOverviewRegion((bottom, top))

            depth_overview_width = 38 + self.depthOverview.fontMetrics().width("0000")
            self.depthOverview.setMinimumWidth(depth_overview_width)
            self.depthOverview.setMaximumWidth(depth_overview_width)

        self.updateScaleRatio()

    def showHidePrimaryNode(self, identifier):
        viewData = self.imageLogViewList[identifier].viewData
        viewController = self.viewControllerWidgets[identifier]
        sliceCompositeNode = self.viewWidgets[identifier].sliceLogic().GetSliceCompositeNode()
        showHidePrimaryNodeButton = viewController.findChild(
            qt.QPushButton, "showHidePrimaryNodeButton" + str(identifier)
        )
        if showHidePrimaryNodeButton.checked:
            showHidePrimaryNodeButton.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeClosed.png"))
            sliceCompositeNode.SetBackgroundOpacity(0)
            viewData.primaryNodeHidden = True
        else:
            showHidePrimaryNodeButton.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeOpen.png"))
            sliceCompositeNode.SetBackgroundOpacity(1)
            viewData.primaryNodeHidden = False

            # Disabling the proportions from the slice view
            showHideProportionsNodeButton = viewController.findChild(
                qt.QPushButton, "showHideProportionsNodeButton" + str(identifier)
            )
            if not showHideProportionsNodeButton.checked:
                showHideProportionsNodeButton.click()

    def showHideSegmentationNode(self, identifier):
        viewData = self.imageLogViewList[identifier].viewData
        sliceCompositeNode = self.viewWidgets[identifier].sliceLogic().GetSliceCompositeNode()
        viewController = self.viewControllerWidgets[identifier]
        viewId = self.viewWidgets[identifier].sliceLogic().GetSliceNode().GetID()
        segmentationNode = self.getNodeById(viewData.segmentationNodeId)
        showHideSegmentationNodeButton = viewController.findChild(
            qt.QToolButton, "showHideSegmentationNodeButton" + str(identifier)
        )
        if showHideSegmentationNodeButton.checked:
            showHideSegmentationNodeButton.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeClosed.png"))
            if segmentationNode is not None:
                if type(segmentationNode) is slicer.vtkMRMLSegmentationNode:
                    segmentationNode.GetDisplayNode().RemoveViewNodeID(viewId)
                elif type(segmentationNode) is slicer.vtkMRMLLabelMapVolumeNode:
                    sliceCompositeNode.SetLabelVolumeID(None)
            viewData.segmentationNodeHidden = True
        else:
            showHideSegmentationNodeButton.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeOpen.png"))
            if segmentationNode is not None:
                if type(segmentationNode) is slicer.vtkMRMLSegmentationNode:
                    segmentationNode.GetDisplayNode().AddViewNodeID(viewId)
                elif type(segmentationNode) is slicer.vtkMRMLLabelMapVolumeNode:
                    sliceCompositeNode.SetLabelVolumeID(viewData.segmentationNodeId)
            viewData.segmentationNodeHidden = False

            # Disabling the proportions from the slice view
            showHideProportionsNodeButton = viewController.findChild(
                qt.QPushButton, "showHideProportionsNodeButton" + str(identifier)
            )
            if not showHideProportionsNodeButton.checked:
                showHideProportionsNodeButton.click()

        # "Reloads" the active effect to enable it in the views when the user change the view segmentation
        segmentEditorWidget = slicer.util.getModuleWidget("ImageLogSegmentEditor").segmentEditorWidget
        activeEffect = segmentEditorWidget.activeEffect()
        segmentEditorWidget.setActiveEffectByName("None")
        segmentEditorWidget.setActiveEffect(activeEffect)

    def changeOpacitySegmentationNode(self, identifier, value):
        self.segmentationOpacity = value
        viewData = self.imageLogViewList[identifier].viewData
        segmentationNode = self.getNodeById(viewData.segmentationNodeId)
        sliceCompositeNode = self.viewWidgets[identifier].sliceLogic().GetSliceCompositeNode()

        identifiers = self.getViewDataListIdentifiers()
        identifiers.remove(identifier)
        for i in identifiers:
            viewController = self.viewControllerWidgets[i]
            segmentationOpacitySlider = viewController.findChild(
                ctk.ctkSliderWidget, "segmentationOpacitySlider" + str(i)
            )
            try:
                doubleSlider = segmentationOpacitySlider.children()[1]
                doubleSlider.setValue(value)
            except AttributeError as e:  # In case other controllers haven't been initialized yet
                logging.debug(e)
                pass
        if segmentationNode:
            if type(segmentationNode) is slicer.vtkMRMLSegmentationNode:
                segmentationDisplayNode = segmentationNode.GetDisplayNode()
                if segmentationDisplayNode is not None:
                    segmentationDisplayNode.SetOpacity(value)
            elif type(segmentationNode) is slicer.vtkMRMLLabelMapVolumeNode:
                sliceCompositeNode.SetLabelOpacity(value)

    def showHideProportionsNode(self, identifier):
        viewData = self.imageLogViewList[identifier].viewData
        viewController = self.viewControllerWidgets[identifier]
        sliceCompositeNode = self.viewWidgets[identifier].sliceLogic().GetSliceCompositeNode()
        showHideProportionsNodeButton = viewController.findChild(
            qt.QPushButton, "showHideProportionsNodeButton" + str(identifier)
        )
        if showHideProportionsNodeButton.checked:
            showHideProportionsNodeButton.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeClosed.png"))
            sliceCompositeNode.SetLabelVolumeID(None)
            viewData.proportionsNodeHidden = True
        else:
            proportionsNodeId = self.imageLogViewList[identifier].viewData.proportionsNodeId
            showHideProportionsNodeButton.setIcon(qt.QIcon(getResourcePath("Icons") / "EyeOpen.png"))
            if proportionsNodeId is not None:
                sliceCompositeNode.SetLabelVolumeID(proportionsNodeId)
            viewData.proportionsNodeHidden = False

            # Disabling the background and segmentation from the slice view
            showHidePrimaryNodeButton = viewController.findChild(
                qt.QPushButton, "showHidePrimaryNodeButton" + str(identifier)
            )
            if not showHidePrimaryNodeButton.checked:
                showHidePrimaryNodeButton.click()
            showHideSegmentationNodeButton = viewController.findChild(
                qt.QToolButton, "showHideSegmentationNodeButton" + str(identifier)
            )
            if not showHideSegmentationNodeButton.checked:
                showHideSegmentationNodeButton.click()

    def customResizeWidgetCallback(self, width):
        self.delayedAdjustViewsVisibleRegion()
        self.updateViewColorBarWidgetsWidth(width)

        for viewControllerWidget in self.viewControllerWidgets:
            settingsPopup = viewControllerWidget.findChild(ctk.ctkPopupWidget)
            if settingsPopup is not None:
                settingsPopup.setFixedWidth(width - 8)

    def updateViewColorBarWidgetsWidth(self, width):
        for identifier in self.getViewDataListIdentifiers():
            if identifier >= len(self.viewColorBarWidgets):
                continue

            viewColorBarWidget = self.viewColorBarWidgets[identifier]
            colorBarWidget = viewColorBarWidget.findChild(ColorBarWidget, "colorBarWidget" + str(identifier))
            if colorBarWidget is not None:
                colorBarWidget.updateWidth(width)

    def setColorBarWidgetColorTableNode(self, colorBarWidget, colorTableNode):
        colorBarWidget.setColorTableNode(colorTableNode)

    def viewControllerSettingsToolButtonToggled(self, identifier):
        viewControllerWidget = self.viewControllerWidgets[identifier]
        settingsToolButton = viewControllerWidget.findChild(qt.QToolButton, "settingsToolButton" + str(identifier))
        self.imageLogViewList[
            identifier
        ].viewData.viewControllerSettingsToolButtonToggled = settingsToolButton.isChecked()

    def onNodeAboutToBeRemoved(self, identifier, node):
        """
        When a node is deleted, update the view data and refresh the views.
        """
        refresh = False
        self.nodeAboutToBeRemoved = True
        if len(self.imageLogViewList) > 0 and identifier < len(self.imageLogViewList):
            viewData = self.imageLogViewList[identifier].viewData
            if node is self.getNodeById(viewData.primaryNodeId):
                self.imageLogViewList[identifier] = ImageLogView(None)
                refresh = True
            elif type(viewData) is SliceViewData and node is self.getNodeById(viewData.segmentationNodeId):
                viewData.segmentationNodeId = None
                viewData.proportionsNodeId = None
                refresh = True
            if refresh:
                self.refreshViews("onNodeAboutToBeRemoved")

    def translationSpeedChanged(self, value):
        self.translationSpeed = value
        for curvePlotWidget in self.curvePlotWidgets:
            if curvePlotWidget is not None:
                curvePlotWidget.setTranslationSpeed(value)

    def scalingSpeedChanged(self, value):
        self.scalingSpeed = value
        for curvePlotWidget in self.curvePlotWidgets:
            if curvePlotWidget is not None:
                curvePlotWidget.setScalingSpeed(value)

    def exit(self):
        pass

    def installObservers(self):
        self.__observerHandlers.append(
            (slicer.mrmlScene, slicer.mrmlScene.AddObserver(slicer.mrmlScene.NodeAddedEvent, self.onNodeAdded))
        )
        self.__observerHandlers.append(
            (slicer.mrmlScene, slicer.mrmlScene.AddObserver(slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose))
        )
        self.__observerHandlers.append(
            (slicer.mrmlScene, slicer.mrmlScene.AddObserver(slicer.mrmlScene.StartCloseEvent, self.onSceneStartImport))
        )
        self.__observerHandlers.append(
            (slicer.mrmlScene, slicer.mrmlScene.AddObserver(slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose))
        )
        self.__observerHandlers.append(
            (slicer.mrmlScene, slicer.mrmlScene.AddObserver(slicer.mrmlScene.EndImportEvent, self.onSceneEndImport))
        )
        self.__observerHandlers.append(
            (slicer.mrmlScene, slicer.mrmlScene.AddObserver(slicer.mrmlScene.StartSaveEvent, self.onSceneStartSave))
        )

    def uninstallObservers(self):
        for object, tag in self.__observerHandlers:
            object.RemoveObserver(tag)

        self.__observerHandlers.clear()

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def onNodeAdded(self, caller, event, node):
        if node.GetHideFromEditors():
            # Non-data nodes such as segment editors should not trigger a refresh
            return
        self.blockAllViewControllerSignals(True)
        self.refreshViews("onNodeAdded")

    def onSceneStartClose(self, caller, event):
        self.imageLogViewList = []
        self.blockAllViewControllerSignals(True)
        self.refreshViews("onSceneStartClose")
        qt.QTimer.singleShot(1000, lambda: self.blockAllViewControllerSignals(False))

    def onSceneStartImport(self, caller, event):
        self.blockAllViewControllerSignals(True)
        self.refreshViews("onSceneStartImport")

    def onSceneEndClose(self, caller, event):
        pass

    def onSceneEndImport(self, caller, event):
        self.refreshViews("onSceneEndImport")
        qt.QTimer.singleShot(1000, lambda: self.blockAllViewControllerSignals(False))

    def blockAllViewControllerSignals(self, mode=True):
        for viewControllerWidget in self.viewControllerWidgets:
            try:
                comboBoxes = viewControllerWidget.findChildren(slicer.qMRMLNodeComboBox)
            except ValueError:  # Widget has been deleted
                continue

            for comboBox in comboBoxes:
                comboBox.blockSignals(mode)

    def getNodeById(self, nodeId):
        if nodeId is not None:
            return slicer.mrmlScene.GetNodeByID(nodeId)
        return None

    def setComboBoxIndexByData(self, comboBox, data):
        for i in range(comboBox.count):
            comboBox.setCurrentIndex(i)
            if comboBox.currentData == data:
                return

    def logMode(self, identifier, activated):
        self.imageLogViewList[identifier].viewData.logMode = activated
        self.refreshViews("logMode")

    def fit(self):
        self.findMaximumCurrentRange()
        self.delayedAdjustViewsVisibleRegion()

    def findMaximumCurrentRange(self):
        """
        Find the maximum current range that fits all data.
        """
        lowest_bound, highest_bound = self.getMaximumCurrentRange()
        if self.currentRange is None:
            self.currentRange = [0] * 2
        self.currentRange[0] = lowest_bound
        self.currentRange[1] = highest_bound

    def isImageVisible(self, node):
        if not node:
            return None

        id_ = node.GetID()

        for imageLogView in self.imageLogViewList:
            viewData = imageLogView.viewData
            if not isinstance(viewData, SliceViewData):
                continue
            if viewData.primaryNodeId == id_:
                return True
            if viewData.segmentationNodeId == id_:
                return True

        return False

    def onDepthOverviewRegionChanged(self):
        top, bottom = self.depthOverviewRegion.getRegion()
        # prevent updating if the current range is too close to the new range
        if np.allclose(self.currentRange, [1000 * bottom, 1000 * top], 1e-10):
            return
        self.currentRange = [1000 * bottom, 1000 * top]
        self.adjustViewsVisibleRegion()

    def setDepthOverviewRegion(self, region):
        # if top depth is greater than bottom, return. Invalid inputs
        if region[1] > region[0]:
            return
        current_region = self.depthOverviewRegion.getRegion()
        # prevent an update if the values are too close
        if not np.allclose(np.flip(current_region), region, 1e-10):
            self.depthOverviewRegion.setRegion(region)

    def updateDepthOverviewScale(self):
        lowest_bound, highest_bound = self.getMaximumCurrentRange()
        if lowest_bound is not None and highest_bound is not None:
            self.depthOverviewPlot.setYRange(lowest_bound / 1000, highest_bound / 1000)

    def getMaximumCurrentRange(self):
        lowest_bound = None
        highest_bound = None
        for identifier in self.getViewDataListIdentifiers():
            if self.imageLogViewList[identifier].widget is None:
                continue
            bottom_bound, up_bound = self.imageLogViewList[identifier].widget.getBounds()
            lowest_bound = min(lowest_bound, bottom_bound) if lowest_bound is not None else bottom_bound
            highest_bound = max(highest_bound, up_bound) if highest_bound is not None else up_bound
        if lowest_bound is not None and highest_bound is not None:
            return -1 * lowest_bound, -1 * highest_bound
        else:
            return None, None

    def __updateToolBarVisibility(self) -> None:
        widget = self.containerWidgets.get("toolBarWidget")
        if widget is None:
            return

        for wid in widget.children():
            if hasattr(wid, "setVisible"):
                wid.setVisible(True)

            wid.update()

    def __addImageLogViewOption(self):
        if self.imageLogLayoutViewAction is not None:
            return

        viewToolBar = slicer.modules.AppContextInstance.mainWindow.findChild("QToolBar", "ViewToolBar")
        layoutMenu = viewToolBar.widgetForAction(viewToolBar.actions()[0]).menu()

        imageLogActionText = "ImageLog View"
        layoutActions = {action.text: action for action in layoutMenu.actions()}
        imageLogActionInMenu = imageLogActionText in layoutActions.keys()

        if not imageLogActionInMenu:
            self.imageLogLayoutViewAction = qt.QAction("ImageLog View")
            self.imageLogLayoutViewAction.setIcon(qt.QIcon(getResourcePath("Icons") / "ImageLog.png"))
            self.imageLogLayoutViewAction.triggered.connect(self.__onImagelogLayoutViewActionClicked)

            after3DOnlyActionIndex = next(
                (i for i, action in enumerate(layoutMenu.actions()) if action.text == "3D only"), None
            )
            layoutMenu.insertAction(
                layoutMenu.actions()[after3DOnlyActionIndex + 1], self.imageLogLayoutViewAction
            )  # insert new action before reference
        else:
            self.imageLogLayoutViewAction = layoutActions["ImageLog View"]

    def __onImagelogLayoutViewActionClicked(self):
        slicer.util.getModuleLogic("ImageLogData").changeToLayout()
        self.imageLogLayoutViewAction.setData(slicer.modules.AppContextInstance.imageLogLayoutId)

    def __updateImageLogLayoutActionVisibility(self):
        currentEnvironment = getCurrentEnvironment()
        isEnvironmentValid = currentEnvironment.value in self.ALLOWED_ENVIRONMENTS_FOR_LAYOUT
        if not isEnvironmentValid and slicer.app.layoutManager().layout >= ImageLogConst.DEFAULT_LAYOUT_ID_START_VALUE:
            viewToolBar = slicer.modules.AppContextInstance.mainWindow.findChild("QToolBar", "ViewToolBar")
            layoutMenu = viewToolBar.widgetForAction(viewToolBar.actions()[0]).menu()
            layoutMenu.actions()[0].triggered()  # Force triggering action to update menu icon

        self.imageLogLayoutViewAction.setVisible(isEnvironmentValid)


class ImageLogDataInfo(RuntimeError):
    pass
