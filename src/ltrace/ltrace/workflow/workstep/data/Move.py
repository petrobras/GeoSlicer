import qt
import slicer
from SegmentEditorEffects import *
from ltrace.workflow.workstep import Workstep, WorkstepWidget


class Move(Workstep):
    NAME = "Data: Move"

    INPUT_TYPES = (slicer.vtkMRMLSegmentationNode, slicer.vtkMRMLScalarVolumeNode, slicer.vtkMRMLVectorVolumeNode)
    OUTPUT_TYPE = Workstep.MATCH_INPUT_TYPE

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.rootItem = 3  # 3 is the item root of the mrml scene
        self.additionalPath = ""
        self.ignoreFolderStructure = False

    def run(self, nodes):
        for node in nodes:
            subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()

            contentsFolder = self.rootItem

            if self.additionalPath.strip() != "":
                folders = self.additionalPath.split("/")
                folders = [s for s in folders if s]  # remove empty strings
                for folder in folders:
                    contentsFolder = self.getFolder(folder, contentsFolder)

            if not self.ignoreFolderStructure:
                nodePath = self.getNodePath(node)
                for folderName in nodePath:
                    contentsFolder = self.getFolder(folderName, contentsFolder)

            item = subjectHierarchyNode.GetItemByDataNode(node)
            subjectHierarchyNode.SetItemParent(item, contentsFolder)

            yield node

    def getFolder(self, folderName, folderParent):
        subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        items = vtk.vtkIdList()
        subjectHierarchyNode.GetItemsByName(folderName, items)

        # if there is not a folder under the folder parent item with the same name, create the folder
        if items.GetNumberOfIds() > 0:
            folderItem = items.GetId(items.GetNumberOfIds() - 1)
            if subjectHierarchyNode.GetItemParent(folderItem) == folderParent:
                return folderItem
        return subjectHierarchyNode.CreateFolderItem(folderParent, folderName)

    def getNodePath(self, node):
        path = []
        subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        item = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(node))
        while subjectHierarchyNode.GetItemName(item) != "Scene":
            path.append(subjectHierarchyNode.GetItemName(item))
            item = subjectHierarchyNode.GetItemParent(item)
        return path[::-1]

    def widget(self):
        return MoveWidget(self)


class MoveWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)

        self.formLayout = qt.QFormLayout()
        self.formLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.layout().addLayout(self.formLayout)

        self.formLayout.addRow(qt.QLabel("Select the destination:"))
        self.subjectHierarchyTreeView = slicer.qMRMLSubjectHierarchyTreeView()
        self.subjectHierarchyTreeView.setMRMLScene(slicer.app.mrmlScene())
        self.subjectHierarchyTreeView.header().setVisible(False)
        self.subjectHierarchyTreeView.hideColumn(2)
        self.subjectHierarchyTreeView.hideColumn(3)
        self.subjectHierarchyTreeView.hideColumn(4)
        self.subjectHierarchyTreeView.hideColumn(5)
        # self.subjectHierarchyTreeView.setEditMenuActionVisible(False)
        # self.subjectHierarchyTreeView.setContextMenuEnabled(False)
        self.subjectHierarchyTreeView.setDragEnabled(False)
        self.subjectHierarchyTreeView.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        self.subjectHierarchyTreeView.setFocusPolicy(qt.Qt.NoFocus)
        self.subjectHierarchyTreeView.setSelectionMode(qt.QAbstractItemView.SingleSelection)
        self.subjectHierarchyTreeView.showRootItem = True
        self.formLayout.addRow(self.subjectHierarchyTreeView)

        self.formLayout.addRow(" ", None)

        self.additionalPathLineEdit = qt.QLineEdit()
        self.additionalPathLineEdit.setToolTip("Move the contents to the selected destionation with this path added.")
        self.formLayout.addRow("Additional path:", self.additionalPathLineEdit)

        self.ignoreFolderStructureCheckbox = qt.QCheckBox()
        self.ignoreFolderStructureCheckbox.setToolTip("Move all data ignoring the folder structure.")
        self.formLayout.addRow("Ignore folder structure:", self.ignoreFolderStructureCheckbox)

    def save(self):
        selectedItems = vtk.vtkIdList()
        self.subjectHierarchyTreeView.currentItems(selectedItems)
        self.workstep.rootItem = selectedItems.GetId(0)
        self.workstep.additionalPath = self.additionalPathLineEdit.text
        self.workstep.ignoreFolderStructure = self.ignoreFolderStructureCheckbox.isChecked()

    def load(self):
        self.subjectHierarchyTreeView.setCurrentItem(self.workstep.rootItem)
        self.additionalPathLineEdit.text = self.workstep.additionalPath
        self.ignoreFolderStructureCheckbox.setChecked(self.workstep.ignoreFolderStructure)
