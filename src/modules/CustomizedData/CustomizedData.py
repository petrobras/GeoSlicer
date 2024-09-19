import os
import vtk
import slicer
import qt
import logging
import traceback

from pathlib import Path

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
        self.parent.title = "Customized Data"
        self.parent.categories = ["LTrace Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = CustomizedData.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class CustomizedDataWidget(LTracePluginWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.formLayout = None
        self.subjectHierarchyTreeView = None

    def setup(self):
        LTracePluginWidget.setup(self)

        frame = qt.QFrame()
        self.formLayout = qt.QFormLayout(frame)
        self.formLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.formLayout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(frame)
        self.layout.addStretch(1)

        import SubjectHierarchyPlugins

        scriptedPlugin = slicer.qSlicerSubjectHierarchyScriptedPlugin(None)
        scriptedPlugin.setPythonSource(SubjectHierarchyPlugins.CenterSubjectHierarchyPlugin.filePath)

        dataWidget = slicer.modules.data.createNewWidgetRepresentation()
        tabWidgetStackedWidget = dataWidget.findChild(qt.QObject, "qt_tabwidget_stackedwidget")
        tabWidgetStackedWidget.findChild(qt.QObject, "SubjectHierarchyDisplayTransformsCheckBox").checked = False

        self.subjectHierarchyTreeView = dataWidget.findChild(qt.QObject, "SubjectHierarchyTreeView")
        self.subjectHierarchyTreeView.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        self.subjectHierarchyTreeView.hideColumn(3)

        # Adds confirmation step before delete action
        nodeMenu = self.subjectHierarchyTreeView.findChild(qt.QMenu, "nodeMenuTreeView")
        self.deleteAction = nodeMenu.actions()[3]  # Delete

        def confirmDeleteSelectedItems():
            message = "Are you sure you want to delete the selected nodes?"
            if slicer.util.confirmYesNoDisplay(message):
                selected_items = vtk.vtkIdList()
                self.subjectHierarchyTreeView.currentItems(selected_items)
                SubjectHierarchyPlugins.CenterSubjectHierarchyPlugin(scriptedPlugin).find_and_remove_sequence_nodes(
                    selected_items
                )
                self.subjectHierarchyTreeView.deleteSelectedItems()

        self.deleteAction.triggered.disconnect()
        self.deleteAction.triggered.connect(confirmDeleteSelectedItems)

        # hack to workaround currentItemChanged firing twice
        self.subjectHierarchyTreeView.currentItemsChanged.connect(self.currentItemChanged)

        # Add observer
        self.endSceneObserver = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.EndCloseEvent, lambda *args: self.currentItemChanged(None)
        )

        self.subjectHierarchyTreeView.setMinimumHeight(310)
        self.subjectHierarchyTreeView.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Minimum)
        self.formLayout.addRow(self.subjectHierarchyTreeView)

        self.scalarVolumeWidget = ScalarVolumeWidget(isLabelMap=False)
        self.formLayout.addRow(self.scalarVolumeWidget)
        self.scalarVolumeWidget.setVisible(False)

        self.vectorVolumeWidget = VectorVolumeWidget()
        self.formLayout.addRow(self.vectorVolumeWidget)
        self.vectorVolumeWidget.setVisible(False)

        self.tableWidget = TableWidget()
        self.formLayout.addRow(self.tableWidget)
        self.tableWidget.setVisible(False)

        self.labelMapWidget = ScalarVolumeWidget(isLabelMap=True)
        self.formLayout.addRow(self.labelMapWidget)
        self.labelMapWidget.setVisible(False)

        self.segmentationWidget = SegmentationWidget()
        self.formLayout.addRow(self.segmentationWidget)
        self.segmentationWidget.setVisible(False)

    def currentItemChanged(self, itemID_bogus):
        # hack to workaround currentItemChanged firing twice
        itemID = self.subjectHierarchyTreeView.currentItem()
        self.scalarVolumeWidget.setVisible(False)
        self.vectorVolumeWidget.setVisible(False)
        self.tableWidget.setVisible(False)
        self.labelMapWidget.setVisible(False)
        self.segmentationWidget.setVisible(False)

        if itemID == 0:
            return

        node = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene).GetItemDataNode(itemID)
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
                self.labelMapWidget.setNode(node)
                self.labelMapWidget.setVisible(True)
            elif type(node) is slicer.vtkMRMLSegmentationNode:
                if node.GetSegmentation().GetNumberOfSegments() <= 50:  # Performance reasons
                    self.segmentationWidget.setNode(node)
                    self.segmentationWidget.setVisible(True)
        except Exception as error:
            logging.info(f"{error}\n{traceback.print_exc()}")
            pass

    def cleanup(self):
        super().cleanup()
        self.subjectHierarchyTreeView.currentItemsChanged.disconnect()
        slicer.mrmlScene.RemoveObserver(self.endSceneObserver)
        self.deleteAction.triggered.disconnect()
        self.scalarVolumeWidget.cleanup()
