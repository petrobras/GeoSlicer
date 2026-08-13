import os
import slicer
import qt
import logging
import traceback

from pathlib import Path

from ltrace.slicer import helpers
from ltrace.slicer_utils import *

from CustomizedDataLib import *

# Checks if closed source code is available
try:
    from Test.CustomizedDataTest import CustomizedDataTest
except ImportError:
    CustomizedDataTest = None


class CustomizedData(LTracePlugin):
    SETTING_KEY = "CustomizedData"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Explorer"
        self.parent.categories = ["Project", "MicroCT", "Thin Section", "Core", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = CustomizedData.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class CustomizedDataWidget(LTracePluginWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.subjectHierarchyTreeView = None
        self.nodeMenu = None
        self.registerActions = []
        self.registerThisAction = None

    def onNodeMenuAboutToShow(self):
        for action in self.registerActions:
            if action is not self.registerThisAction:
                action.visible = False

    def setup(self):
        LTracePluginWidget.setup(self)
        # self.layout.addStretch(1)

        import SubjectHierarchyPlugins

        self.scriptedPlugin = slicer.qSlicerSubjectHierarchyScriptedPlugin(None)
        self.scriptedPlugin.setPythonSource(SubjectHierarchyPlugins.CenterSubjectHierarchyPlugin.filePath)

        self.dataWidget = slicer.modules.data.createNewWidgetRepresentation()
        tabWidgetStackedWidget = self.dataWidget.findChild(qt.QObject, "qt_tabwidget_stackedwidget")
        tabWidgetStackedWidget.findChild(qt.QObject, "SubjectHierarchyDisplayTransformsCheckBox").checked = False

        self.subjectHierarchyTreeView = self.dataWidget.findChild(qt.QObject, "SubjectHierarchyTreeView")
        self.subjectHierarchyTreeView.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)

        def showSearchPopup(current):
            if current.column() == 0:
                slicer.modules.AppContextInstance.fuzzySearch.exec_()

        self.subjectHierarchyTreeView.doubleClicked.connect(showSearchPopup)

        # Adds confirmation step before delete action
        self.nodeMenu = self.subjectHierarchyTreeView.findChild(qt.QMenu, "nodeMenuTreeView")
        self.nodeMenu.aboutToShow.connect(self.onNodeMenuAboutToShow)
        self.deleteAction = [action for action in self.nodeMenu.actions() if action.text == "Delete"][0]

        def confirmDeleteSelectedItems():
            message = "Are you sure you want to delete the selected nodes?"
            if slicer.util.confirmYesNoDisplay(message):
                SubjectHierarchyPlugins.CenterSubjectHierarchyPlugin(
                    self.scriptedPlugin
                ).find_and_remove_sequence_nodes()
                self.subjectHierarchyTreeView.deleteSelectedItems()

        self.deleteAction.triggered.disconnect()
        self.deleteAction.triggered.connect(confirmDeleteSelectedItems)

        # Replaces default clone action with a custom one that also copies attributes and references
        self.cloneAction = [
            action
            for action in self.nodeMenu.actions()
            if action.text == "Clone" and isinstance(action.parent(), slicer.qSlicerSubjectHierarchyCloneNodePlugin)
        ][0]

        self.cloneAction.triggered.disconnect()
        self.cloneAction.triggered.connect(
            SubjectHierarchyPlugins.CenterSubjectHierarchyPlugin(self.scriptedPlugin).find_and_clone_items
        )

        # Replaces default export visible segments to labl map action with a custom one that also sets referenceImageGeometryRef
        self.convertToLabelMapAction = [
            action for action in self.nodeMenu.actions() if action.text == "Export visible segments to binary labelmap"
        ][0]

        def customExportSegmentsToLabelMap():
            SubjectHierarchyPlugins.CenterSubjectHierarchyPlugin(
                self.scriptedPlugin
            ).find_and_create_labelmap_from_items()

        self.convertToLabelMapAction.triggered.disconnect()
        self.convertToLabelMapAction.triggered.connect(customExportSegmentsToLabelMap)

        self.registerActions = [
            action
            for action in self.nodeMenu.actions()
            if isinstance(action.parent(), slicer.qSlicerSubjectHierarchyRegisterPlugin)
        ]
        self.registerThisAction = [action for action in self.registerActions if action.text == "Register this..."][0]

        self.registerThisAction.triggered.disconnect()
        self.registerThisAction.triggered.connect(
            SubjectHierarchyPlugins.CenterSubjectHierarchyPlugin(self.scriptedPlugin).register_current_item
        )

        self.subjectHierarchyTreeView.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        self.infoFrame = qt.QFrame()
        self.infoFrameLayout = qt.QVBoxLayout(self.infoFrame)
        self.infoFrameLayout.setContentsMargins(0, 0, 0, 0)

        self.tabWidget = qt.QTabWidget()
        self.infoFrameLayout.addWidget(self.tabWidget)

        self.infoWidgetContainer = qt.QWidget()
        self.infoWidgetLayout = qt.QVBoxLayout(self.infoWidgetContainer)
        self.infoWidgetLayout.setContentsMargins(0, 0, 0, 0)
        self.tabWidget.addTab(self.infoWidgetContainer, "Info")
        self.scalarVolumeWidget = ScalarVolumeWidget(parent=self.infoWidgetContainer, isLabelMap=False)
        self.infoWidgetLayout.addWidget(self.scalarVolumeWidget)
        self.scalarVolumeWidget.setVisible(False)

        self.vectorVolumeWidget = VectorVolumeWidget(self.infoWidgetContainer)
        self.infoWidgetLayout.addWidget(self.vectorVolumeWidget)
        self.vectorVolumeWidget.setVisible(False)

        self.tableWidget = TableWidget()
        self.infoWidgetLayout.addWidget(self.tableWidget)
        self.tableWidget.setVisible(False)

        self.labelMapWidget = ScalarVolumeWidget(parent=self.infoWidgetContainer, isLabelMap=True)
        self.infoWidgetLayout.addWidget(self.labelMapWidget)
        self.labelMapWidget.setVisible(False)

        self.segmentationWidget = SegmentationWidget()
        self.infoWidgetLayout.addWidget(self.segmentationWidget)
        self.segmentationWidget.setVisible(False)

        self.textWidget = TextWidget()
        self.infoWidgetLayout.addWidget(self.textWidget)
        self.textWidget.setVisible(False)

        self.infoWidgetLayout.addStretch()

        self.attributesWidget = TextWidget()
        self.tabWidget.addTab(self.attributesWidget, "Attributes")

        self.tabWidget.setVisible(False)

        self.fullPanel = qt.QSplitter()
        self.fullPanel.setOrientation(qt.Qt.Vertical)
        self.fullPanel.setHandleWidth(1)
        self.fullPanel.setChildrenCollapsible(False)
        self.fullPanel.addWidget(self.subjectHierarchyTreeView)
        self.fullPanel.addWidget(self.infoFrame)

        self.subjectHierarchyTreeView.setMinimumHeight(384)

        self.fullPanel.setStretchFactor(0, 1)  # subjectHierarchyTreeView gets more space
        self.fullPanel.setStretchFactor(1, 0)  # infoFrame gets less space

        self.layout.addWidget(self.fullPanel)

        # hack to workaround currentItemChanged firing twice
        self.subjectHierarchyTreeView.currentItemsChanged.connect(self.currentItemChanged)

        # Add observer
        self.endSceneObserver = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.EndCloseEvent, lambda *args: self.currentItemChanged(None)
        )

    def currentItemChanged(self, itemID_bogus):
        # hack to workaround currentItemChanged firing twice
        itemID = self.subjectHierarchyTreeView.currentItem()
        self.scalarVolumeWidget.setVisible(False)
        self.vectorVolumeWidget.setVisible(False)
        self.tableWidget.setVisible(False)
        self.labelMapWidget.setVisible(False)
        self.segmentationWidget.setVisible(False)
        self.textWidget.setVisible(False)

        node = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene).GetItemDataNode(itemID)

        if itemID == 0 or not node:
            self.tabWidget.setVisible(False)
            return

        self.tabWidget.setVisible(True)

        # Handle attributes tab
        metadata_node_id = node.GetAttribute("MetadataNode")
        metadata_node = slicer.mrmlScene.GetNodeByID(metadata_node_id) if metadata_node_id else None
        if metadata_node:
            self.attributesWidget.setNode(metadata_node)
        else:
            self.attributesWidget.textEdit.setPlainText("")
            self.attributesWidget.highlightMatches()

        # Handle info tab
        try:
            if type(node) is slicer.vtkMRMLScalarVolumeNode:
                self.scalarVolumeWidget.setNode(node)
                self.scalarVolumeWidget.setVisible(True)
            elif type(node) is slicer.vtkMRMLVectorVolumeNode:
                self.vectorVolumeWidget.setNode(node)
                self.vectorVolumeWidget.setVisible(True)
            elif type(node) is slicer.vtkMRMLTableNode:
                if node.GetNumberOfRows() <= 3000:
                    self.tableWidget.setNode(node)
                    self.tableWidget.setVisible(True)
            elif type(node) is slicer.vtkMRMLLabelMapVolumeNode:
                srange = node.GetImageData().GetScalarRange()
                colors = srange[1] - srange[0] + 1
                self.labelMapWidget.setNode(node, hideTable=colors > 50)
                self.labelMapWidget.setVisible(True)
            elif type(node) is slicer.vtkMRMLSegmentationNode:
                if node.GetSegmentation().GetNumberOfSegments() <= 50:  # Performance reasons
                    self.segmentationWidget.setNode(node)
                    self.segmentationWidget.setVisible(True)
            elif type(node) is slicer.vtkMRMLTextNode:
                self.textWidget.setNode(node)
                self.textWidget.setVisible(True)
        except Exception as error:
            logging.info(f"{error}\n{traceback.print_exc()}")
            pass

    def cleanup(self):
        super().cleanup()
        self.subjectHierarchyTreeView.currentItemsChanged.disconnect()
        slicer.mrmlScene.RemoveObserver(self.endSceneObserver)
        self.nodeMenu.aboutToShow.disconnect(self.onNodeMenuAboutToShow)
        self.deleteAction.triggered.disconnect()
        self.cloneAction.triggered.disconnect()
        self.convertToLabelMapAction.triggered.disconnect()
        if self.registerThisAction is not None:
            self.registerThisAction.triggered.disconnect()
        self.scalarVolumeWidget.cleanup()
