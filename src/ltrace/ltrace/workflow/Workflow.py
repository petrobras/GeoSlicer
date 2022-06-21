import collections
import ctk
import json
import numpy as np
import vtk

from Customizer import Customizer
from dataclasses import dataclass
from ltrace.utils.ProgressBarProc import ProgressBarProc
from ltrace.workflow.workstep import *
from ltrace.workflow.workstep.data import *
from ltrace.workflow.workstep.segmentation import *
from ltrace.workflow.workstep.simulation import *
from pathlib import Path

WORKSTEPS = {
    module.NAME: module
    for module in (
        Threshold,
        Islands,
        Smooth,
        Margin,
        Move,
        Export,
        ThinSectionLoader,
        BoundaryRemoval,
        MultipleThreshold,
        Watershed,
        NetCDFLoader,
        InspectorWatershed,
        PoreNetworkExtractor,
        PoreNetworkSimOnePhase,
        PoreNetworkSimTwoPhase,
    )
}
WORKSTEPS = collections.OrderedDict(sorted(WORKSTEPS.items()))  # Sorting by name

INPUT_NAMES = {
    (slicer.vtkMRMLLabelMapVolumeNode,): "label map",
    (slicer.vtkMRMLSegmentationNode,): "segmentation",
    (slicer.vtkMRMLVectorVolumeNode,): "RGB volume",
    (slicer.vtkMRMLTableNode,): "table",
    (slicer.vtkMRMLScalarVolumeNode,): "grayscale volume",
    (slicer.vtkMRMLSegmentationNode, slicer.vtkMRMLLabelMapVolumeNode): "segmentation or label map",
    (
        slicer.vtkMRMLScalarVolumeNode,
        slicer.vtkMRMLVectorVolumeNode,
    ): "volume",
    (
        slicer.vtkMRMLSegmentationNode,
        slicer.vtkMRMLScalarVolumeNode,
        slicer.vtkMRMLVectorVolumeNode,
    ): "segmentation or volume",
    (
        slicer.vtkMRMLSegmentationNode,
        slicer.vtkMRMLScalarVolumeNode,
        slicer.vtkMRMLVectorVolumeNode,
        slicer.vtkMRMLLabelMapVolumeNode,
        slicer.vtkMRMLTableNode,
    ): "anything",
    (Workstep.MIXED_TYPE,): "mixed",
    (type(None),): "nothing",
}


@dataclass
class WorkstepTypeError:
    name: str
    expected: any
    actual: any

    def __str__(self):
        expected = INPUT_NAMES[self.expected]
        actual = INPUT_NAMES[(self.actual,)]
        return f'Workstep "{self.name}" expects input to be {expected}, but current input is {actual}.'


class Workflow:
    def __init__(self, updateStatusMessage=None, updateStatusError=None, updateProgress=None):
        self.worksteps = {}
        self.lastWorkstepId = -1
        self.lastSavedWorkflow = self.dump([])

        self.updateStatusMessage = updateStatusMessage or (lambda message: None)
        self.updateStatusError = updateStatusError or (lambda message: None)
        self.updateProgress = updateProgress or (lambda value: None)

    def addWorkstep(self, workstepClass):
        workstep = workstepClass()
        id_ = self.nextWorkstepId()
        self.worksteps[id_] = workstep
        return id_, workstep

    def nextWorkstepId(self):
        self.lastWorkstepId += 1
        return self.lastWorkstepId

    def typeCheck(self, selectedItems, workstepsIds):
        result = []
        nodes = list(self.getDataNodes(selectedItems))
        worksteps = [self.worksteps[workstepsId] for workstepsId in workstepsIds]

        if not worksteps:
            return result

        type_ = type(None)
        if nodes:
            type_ = type(nodes[0])
            for node in nodes:
                if type(node) != type_:
                    type_ = Workstep.MIXED_TYPE
                    break

        for workstep in worksteps:
            if type_ in workstep.input_types():
                result.append(None)
            else:
                error = WorkstepTypeError(name=workstep.NAME, expected=workstep.INPUT_TYPES, actual=type_)
                result.append(error)
            if workstep.output_type() == Workstep.MATCH_INPUT_TYPE:
                continue
            type_ = workstep.output_type()
        return result

    def validate(self, workstepsIds):
        result = []
        worksteps = [self.worksteps[workstepsId] for workstepsId in workstepsIds]
        for workstep in worksteps:
            result.append(workstep.validate())
        return result

    @staticmethod
    def processedNodeMessage(node):
        node_name = f"node {node.GetName()}" if isinstance(node, slicer.vtkMRMLNode) else node
        return f"Processed {node_name}"

    @staticmethod
    def hideOutput(nodes):
        for node in nodes:
            if isinstance(node, slicer.vtkMRMLSegmentationNode):
                node.SetDisplayVisibility(False)
            elif isinstance(node, slicer.vtkMRMLLabelMapVolumeNode):
                slicer.util.setSliceViewerLayers(label=None)
            elif isinstance(node, slicer.vtkMRMLScalarVolumeNode):
                slicer.util.setSliceViewerLayers(background=None)
            yield node

    @staticmethod
    def showOutput(nodes):
        for node in nodes:
            if isinstance(node, slicer.vtkMRMLSegmentationNode):
                node.SetDisplayVisibility(True)
            elif isinstance(node, slicer.vtkMRMLLabelMapVolumeNode):
                slicer.util.setSliceViewerLayers(label=node, fit=True)
            elif isinstance(node, slicer.vtkMRMLScalarVolumeNode):
                slicer.util.setSliceViewerLayers(background=node, fit=True)
            yield node

    def runNodeByNode(self, selectedItems, workstepsIds):
        self._stop = False

        nodes = list(self.getDataNodes(selectedItems))
        length = len(nodes)
        output = iter(nodes)

        for workstepsId in workstepsIds:
            workstep = self.worksteps[workstepsId]
            output = workstep.run(output)
            output = self.hideOutput(output)
            length = workstep.expected_length(length)
        output = self.showOutput(output)
        try:
            self.updateStatusMessage("Starting workflow")
            progress_step = 1 / length if length > 0 else 0.1
            progress = 0
            for node in output:
                if self._stop:
                    raise Exception("Workflow stopped")
                progress += progress_step
                self.updateProgress(min(1, progress))
                self.updateStatusMessage(self.processedNodeMessage(node))
            self.updateProgress(1)
            self.updateStatusMessage("Workflow finished successfully")
        except Exception as e:
            self.updateStatusError(str(e))
            raise

    def runStepByStep(self, selectedItems, workstepsIds):
        self._stop = False

        output = list(self.getDataNodes(selectedItems))
        length = len(output)
        try:
            self.updateStatusMessage("Starting workflow")

            for i, workstepsId in enumerate(workstepsIds):
                workstep = self.worksteps[workstepsId]
                self.updateStatusMessage(f'Processing workstep "{workstep.NAME}"')
                length = workstep.expected_length(length)
                output = workstep.run(output)
                output = self.hideOutput(output)

                next_output = []
                j = -1
                for j, node in enumerate(output):
                    if self._stop:
                        raise Exception("Workflow stopped")
                    self.updateProgress((i + j / length) / len(workstepsIds))
                    self.updateStatusMessage(self.processedNodeMessage(node))
                    next_output.append(node)
                output = next_output
                length = j + 1

            for _ in self.showOutput(output):
                pass

            self.updateStatusMessage("Workflow finished successfully")
            self.updateProgress(1)
        except Exception as e:
            self.updateStatusError(f"Error: {e}")
            raise e

    def stop(self):
        self._stop = True

    def dump(self, workstepsIds):
        return [self.worksteps[workstepsId].dump() for workstepsId in workstepsIds]

    def updateLastSavedWorkflow(self, workstepsIds):
        data = self.dump(workstepsIds)
        self.lastSavedWorkflow = data
        return data

    def save(self, workstepsIds, filePath):
        json.dump(self.updateLastSavedWorkflow(workstepsIds), open(filePath, "w"), indent=4)

    def getDataNodes(self, itemsIds):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemsIds = self.getItemsSubitemsIds(itemsIds)
        for itemId in itemsIds:
            dataNode = subjectHierarchyNode.GetItemDataNode(itemId)
            if dataNode is not None:
                yield dataNode

    def getItemsSubitemsIds(self, items):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        nodesIds = []
        numberOfIds = items.GetNumberOfIds()
        # if numberOfIds == 0:
        #     raise WorkflowInfo("There are no data selected.")
        for i in range(numberOfIds):
            itemId = items.GetId(i)
            if itemId == 3:  # when not selecting any item, it supposes entire scene, which we don't want
                break
            nodesIds.append(itemId)
            itemChildren = vtk.vtkIdList()
            subjectHierarchyNode.GetItemChildren(itemId, itemChildren, True)  # recursive
            for j in range(itemChildren.GetNumberOfIds()):
                childrenItemId = itemChildren.GetId(j)
                nodesIds.append(childrenItemId)
        return list(set(nodesIds))  # removing duplicate items


class WorkflowInfo(RuntimeError):
    pass


class CustomizedQListWidget(qt.QListWidget):
    def __init__(self, workflowWidget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workflowWidget = workflowWidget


class WorkflowWidget(qt.QDialog):
    PANEL_TITLE_STYLE_SHEET = "QLabel {font-size: 14px; font-weight: bold;}"
    WINDOW_TITLE_PREFIX = "Workflow (Beta) - "

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workflow = None
        self.newWorkflowDialog = None
        self.addWorkstepDialog = None
        self.workflow = Workflow(self.onStatusMessage, self.onStatusError, self.onProgress)
        self.setup()
        self.setLastSavedPath(None)

    def setup(self):
        self.setMinimumSize(1400, 700)
        self.setWindowFlags(self.windowFlags() | qt.Qt.WindowMinimizeButtonHint | qt.Qt.WindowMaximizeButtonHint)

        windowLayout = qt.QVBoxLayout(self)
        windowLayout.setContentsMargins(0, 0, 0, 0)
        windowLayout.addWidget(self.menuBarInterface())
        windowLayout.addWidget(self.toolBarInterface())

        mainPanelsSplitter = qt.QSplitter()
        mainPanelsSplitter.setContentsMargins(0, 0, 0, 0)
        mainPanelsSplitter.setHandleWidth(26)
        mainPanelsSplitter.addWidget(self.dataPanel())
        mainPanelsSplitter.addWidget(self.workflowPanel())
        mainPanelsSplitter.addWidget(self.workstepPanel())

        contentsSplitter = qt.QSplitter(qt.Qt.Vertical)
        contentsSplitter.setObjectName("contentsSplitter")
        contentsSplitter.setContentsMargins(10, 10, 10, 10)
        contentsSplitter.setHandleWidth(26)
        contentsSplitter.addWidget(mainPanelsSplitter)
        contentsSplitter.addWidget(self.statusPanel())
        contentsSplitter.setStretchFactor(0, 9)
        contentsSplitter.setStretchFactor(1, 1)

        windowLayout.addWidget(contentsSplitter, 1)

    def setLastSavedPath(self, path):
        self.lastSavedPath = path
        name = "Unnamed workflow" if path is None else Path(path).name
        self.setWindowTitle(self.WINDOW_TITLE_PREFIX + name)

    def menuBarInterface(self):
        menuBar = qt.QMenuBar()
        fileMenu = menuBar.addMenu("&File")
        optionsMenu = menuBar.addMenu("&Options")
        helpMenu = menuBar.addMenu("&Help")

        loadWorkflowAction = qt.QAction(qt.QIcon(str(Customizer.LOAD_ICON_PATH)), "&Load...", fileMenu)
        saveWorkflowAction = qt.QAction(qt.QIcon(str(Customizer.SAVE_ICON_PATH)), "&Save", fileMenu)
        saveAsWorkflowAction = qt.QAction("Save as...", fileMenu)
        closeWorkflowAction = qt.QAction("&Close", fileMenu)
        exitWorkflowAction = qt.QAction("E&xit", fileMenu)

        self.runStepByStepAction = qt.QAction("Run step by step", optionsMenu)
        self.runStepByStepAction.setCheckable(True)

        fileMenu.addAction(loadWorkflowAction)
        fileMenu.addAction(saveWorkflowAction)
        fileMenu.addAction(saveAsWorkflowAction)
        fileMenu.addAction(closeWorkflowAction)
        fileMenu.addSeparator()
        fileMenu.addAction(exitWorkflowAction)

        optionsMenu.addAction(self.runStepByStepAction)

        # Connections
        closeWorkflowAction.triggered.connect(self.closeWorkflow)
        exitWorkflowAction.triggered.connect(self.exitWorkflow)
        saveWorkflowAction.triggered.connect(self.saveWorkflow)
        saveAsWorkflowAction.triggered.connect(self.saveAsWorkflow)
        loadWorkflowAction.triggered.connect(self.loadWorkflow)

        return menuBar

    def saveToLastPath(self):
        self.workflow.save(self.getWorkstepsIds(), self.lastSavedPath)

    def saveWorkflow(self):
        if self.lastSavedPath:
            self.saveToLastPath()
        else:
            self.saveAsWorkflow()

    def saveAsWorkflow(self):
        filePath = qt.QFileDialog.getSaveFileName(self, "Save workflow as...", "", "JSON files (*.json)")
        if filePath:
            self.setLastSavedPath(filePath)
            self.saveToLastPath()

    def loadWorkflow(self):
        filePath = qt.QFileDialog.getOpenFileName(self, "Load workflow", "", "JSON files (*.json)")
        if not filePath:
            return
        if not self.closeWorkflow():
            return
        for workstepData in json.load(open(filePath, "r")):
            className = workstepData.pop("workstepName")
            self.addWorkstep(className, workstepData)
        self.setLastSavedPath(filePath)
        self.workflow.updateLastSavedWorkflow(self.getWorkstepsIds())

    def toolBarInterface(self):
        toolBar = qt.QToolBar()
        toolBar.setObjectName("toolBar")
        toolBar.setToolButtonStyle(qt.Qt.ToolButtonTextBesideIcon)
        toolBar.setStyleSheet("QToolBar {border-top: 1px solid gray; border-bottom: 1px solid gray;}")
        runWorkflowAction = qt.QAction(qt.QIcon(str(Customizer.RUN_ICON_PATH)), "Run workflow", toolBar)
        toolBar.addAction(runWorkflowAction)
        stopWorkflowAction = qt.QAction(qt.QIcon(str(Customizer.STOP_ICON_PATH)), "Stop workflow", toolBar)
        toolBar.addAction(stopWorkflowAction)

        runWorkflowAction.triggered.connect(self.run)
        stopWorkflowAction.triggered.connect(self.stop)

        return toolBar

    def exitWorkflow(self):
        if self.closeWorkflow():
            self.hide()

    def closeEvent(self, event):
        if self.closeWorkflow():
            self.hide()
        else:
            event.ignore()

    def closeWorkflow(self):
        closeWorkflow = True
        self.currentWorkstepWidget.save()

        jsonNormalize = lambda data: json.loads(json.dumps(data))
        lastSave = jsonNormalize(self.workflow.lastSavedWorkflow)
        currentSave = jsonNormalize(self.workflow.dump(self.getWorkstepsIds()))

        if currentSave != lastSave:
            closeWorkflow = slicer.util.confirmYesNoDisplay(
                "Any unsaved changes will be lost. Are you sure?", "GeoSlicer - Workflow"
            )
        if closeWorkflow:
            self.setLastSavedPath(None)
            self.workstepsListWidget.clear()
            self.workflow = Workflow(self.onStatusMessage, self.onStatusError, self.onProgress)
        return closeWorkflow

    def dataPanel(self):
        dataLayout = qt.QVBoxLayout()
        dataLayout.setContentsMargins(0, 0, 0, 0)
        nodesLabel = qt.QLabel("Data")
        nodesLabel.setStyleSheet(self.PANEL_TITLE_STYLE_SHEET)
        dataLayout.addWidget(nodesLabel)
        self.subjectHierarchyTreeView = slicer.qMRMLSubjectHierarchyTreeView()
        self.subjectHierarchyTreeView.setMRMLScene(slicer.app.mrmlScene())
        self.subjectHierarchyTreeView.header().setVisible(False)
        self.subjectHierarchyTreeView.hideColumn(3)
        self.subjectHierarchyTreeView.hideColumn(4)
        self.subjectHierarchyTreeView.hideColumn(5)
        self.subjectHierarchyTreeView.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        self.subjectHierarchyTreeView.setFocusPolicy(qt.Qt.NoFocus)
        # self.subjectHierarchyTreeView.showRootItem = True
        dataLayout.addWidget(self.subjectHierarchyTreeView)

        # Data types
        dataTypesCollapsibleButton = ctk.ctkCollapsibleButton()
        dataTypesCollapsibleButton.setText("Data types")
        dataTypesCollapsibleButton.collapsed = True
        dataTypesCollapsibleButton.collapsedHeight = 8
        dataTypesLayout = qt.QGridLayout(dataTypesCollapsibleButton)
        dataTypesLayout.setContentsMargins(5, 5, 5, 5)
        self.scalarVolumeDataTypeCheckbox = qt.QCheckBox("Scalar volumes")
        # self.scalarVolumeDataTypeCheckbox.setChecked(self.getScalarVolumeDataType() == "True")
        dataTypesLayout.addWidget(self.scalarVolumeDataTypeCheckbox, 0, 0)
        self.imageDataTypeCheckbox = qt.QCheckBox("Images")
        # self.imageDataTypeCheckbox.setChecked(self.getImageDataType() == "True")
        dataTypesLayout.addWidget(self.imageDataTypeCheckbox, 1, 0)
        self.labelMapDataTypeCheckbox = qt.QCheckBox("Label maps")
        # self.labelMapDataTypeCheckbox.setChecked(self.getLabelMapDataType() == "True")
        dataTypesLayout.addWidget(self.labelMapDataTypeCheckbox, 0, 1)
        self.segmentationDataTypeCheckbox = qt.QCheckBox("Segmentations")
        # self.segmentationDataTypeCheckbox.setChecked(self.getSegmentationDataType() == "True")
        dataTypesLayout.addWidget(self.segmentationDataTypeCheckbox, 1, 1)
        self.tableDataTypeCheckbox = qt.QCheckBox("Tables")
        # self.tableDataTypeCheckbox.setChecked(self.getTableDataType() == "True")
        dataTypesLayout.addWidget(self.tableDataTypeCheckbox, 0, 2)
        dataLayout.addWidget(dataTypesCollapsibleButton)

        frame = qt.QFrame()
        frame.setLayout(dataLayout)
        return frame

    def workflowPanel(self):
        workflowLayout = qt.QVBoxLayout()
        workflowLayout.setContentsMargins(0, 0, 0, 0)
        worksflowLabel = qt.QLabel("Workflow")
        worksflowLabel.setStyleSheet(self.PANEL_TITLE_STYLE_SHEET)
        workflowLayout.addWidget(worksflowLabel)
        self.workstepsListWidget = CustomizedQListWidget(self)
        self.workstepsListWidget.setStyleSheet("QListWidget {font-size: 11px; font-weight: bold;}")
        self.workstepsListWidget.setDragDropMode(qt.QAbstractItemView.InternalMove)
        self.workstepsListWidget.setFocusPolicy(qt.Qt.NoFocus)
        model = self.workstepsListWidget.model()
        model.rowsMoved.connect(lambda parent, start, end, destination, row: self.validateWorkflow())
        model.rowsInserted.connect(lambda parent, first, last: self.validateWorkflow())
        model.rowsRemoved.connect(lambda parent, first, last: self.validateWorkflow())

        # self.timer = qt.QTimer()
        # self.timer.timeout.connect(self.validateWorkflow)
        # self.timer.start(1000)

        workflowLayout.addWidget(self.workstepsListWidget)

        addCloneDeleteWorkstepsButtonsLayout = qt.QHBoxLayout()
        addCloneDeleteWorkstepsButtonsLayout.addWidget(qt.QWidget())
        addWorkstepButton = qt.QPushButton("Add workstep")
        addWorkstepButton.setAutoDefault(False)
        addWorkstepButton.setIcon(qt.QIcon(str(Customizer.ADD_ICON_PATH)))
        addCloneDeleteWorkstepsButtonsLayout.addWidget(addWorkstepButton)
        self.deleteWorkstepButton = qt.QPushButton("Delete workstep")
        self.deleteWorkstepButton.setIcon(qt.QIcon(str(Customizer.DELETE_ICON_PATH)))
        self.deleteWorkstepButton.setEnabled(False)
        self.deleteWorkstepButton.setAutoDefault(False)
        addCloneDeleteWorkstepsButtonsLayout.addWidget(self.deleteWorkstepButton)
        addCloneDeleteWorkstepsButtonsLayout.addWidget(qt.QWidget())
        workflowLayout.addLayout(addCloneDeleteWorkstepsButtonsLayout)

        # Connections
        addWorkstepButton.clicked.connect(self.onAddWorkstep)
        self.workstepsListWidget.itemSelectionChanged.connect(self.showSelectedWorkstep)
        self.deleteWorkstepButton.clicked.connect(self.deleteWorkstep)

        frame = qt.QFrame()
        frame.setLayout(workflowLayout)
        return frame

    def showSelectedWorkstep(self):
        listWidgetItem = self.workstepsListWidget.selectedItems()
        if len(listWidgetItem) == 0:
            self.setWorkstepWidget(self.blankWorkstepWidget())
            self.deleteWorkstepButton.setEnabled(False)
            self.workstepLabel.setText("Workstep")
            return
        workstepId = listWidgetItem[0].data(qt.Qt.UserRole)
        workstep = self.workflow.worksteps[workstepId]
        workstepWidget = workstep.widget()
        self.setWorkstepWidget(workstepWidget)
        self.deleteWorkstepButton.setEnabled(True)
        self.workstepLabel.setText("Workstep - " + listWidgetItem[0].text())
        self.currentListWidgetItem = listWidgetItem[0]

    def deleteWorkstep(self):
        currentListWidgetItem = self.workstepsListWidget.selectedItems()[0]
        currentListWidgetItemRow = self.workstepsListWidget.row(currentListWidgetItem)
        self.workstepsListWidget.takeItem(currentListWidgetItemRow)

        # Block bellow is to solve an interface bug
        if currentListWidgetItemRow > 0:
            try:
                self.workstepsListWidget.item(currentListWidgetItemRow).setSelected(True)
            except:
                self.workstepsListWidget.item(currentListWidgetItemRow - 1).setSelected(True)
        self.deleteWorkstepButton.setFocus(True)

    def blankWorkstepWidget(self):
        return Blank().widget()

    def onAddWorkstep(self):
        self.currentWorkstepWidget.save()
        if self.addWorkstepDialog is None:
            self.addWorkstepDialog = qt.QDialog()
            self.addWorkstepDialog.setWindowTitle("Add workstep")
            self.addWorkstepDialog.setModal(True)

            windowLayout = qt.QVBoxLayout(self.addWorkstepDialog)
            windowLayout.setContentsMargins(10, 10, 10, 10)
            contentsLayout = qt.QFormLayout()
            contentsLayout.setLabelAlignment(qt.Qt.AlignRight)

            workstepsComboBox = qt.QComboBox()
            workstepsComboBox.setObjectName("workstepsComboBox")
            for workstepName, _ in WORKSTEPS.items():
                workstepsComboBox.addItem(workstepName)
            workstepsComboBox.setToolTip("Select a workstep.")
            contentsLayout.addRow("Workstep:", workstepsComboBox)
            contentsLayout.addRow(" ", None)
            windowLayout.addLayout(contentsLayout)
            windowLayout.addStretch(1)

            buttonsLayout = qt.QHBoxLayout()
            buttonsLayout.addStretch(1)
            okButton = qt.QPushButton("OK")
            okButton.setMinimumWidth(120)
            buttonsLayout.addWidget(okButton)
            cancelButton = qt.QPushButton("Cancel")
            cancelButton.setMinimumWidth(120)
            buttonsLayout.addWidget(cancelButton)
            windowLayout.addLayout(buttonsLayout)

            self.addWorkstepDialog.setFixedSize(windowLayout.sizeHint())  # Fit contents

            # Connections
            okButton.clicked.connect(lambda: self.onConfirmAddWorkstep(workstepsComboBox.currentText))
            cancelButton.clicked.connect(self.cancelAddWorkstep)
        else:
            self.addWorkstepDialog.findChild(qt.QComboBox, "workstepsComboBox").setCurrentIndex(0)
        self.addWorkstepDialog.show()

    def cancelAddWorkstep(self):
        self.addWorkstepDialog.hide()

    def onConfirmAddWorkstep(self, workstepName):
        self.addWorkstepDialog.hide()
        self.addWorkstep(workstepName)

    def addWorkstep(self, workstepName, workstepData=None):
        id_, workstep = self.workflow.addWorkstep(WORKSTEPS[workstepName])
        selectedIndexes = self.workstepsListWidget.selectedIndexes()
        if len(selectedIndexes) == 0:
            selectedIndex = self.workstepsListWidget.count
        else:
            selectedIndex = selectedIndexes[0].row() + 1
        listWidgetItem = qt.QListWidgetItem(workstepName)

        listWidgetItem.setData(qt.Qt.UserRole, id_)  # Saving a unique ID for this workstep
        self.workstepsListWidget.insertItem(selectedIndex, listWidgetItem)
        if workstepData is not None:
            workstep.load(workstepData)
        listWidgetItem.setSelected(True)
        self.currentListWidgetItem = listWidgetItem

        return workstep

    def workstepPanel(self):
        workstepLayout = qt.QVBoxLayout()
        workstepLayout.setContentsMargins(0, 0, 0, 0)
        self.workstepLabel = qt.QLabel("Workstep")
        self.workstepLabel.setStyleSheet(self.PANEL_TITLE_STYLE_SHEET)
        workstepLayout.addWidget(self.workstepLabel)

        workstepWidgetFrame = qt.QFrame()
        workstepWidgetFrame.setObjectName("workstepWidgetFrame")
        self.workstepWidgetLayout = qt.QVBoxLayout(workstepWidgetFrame)
        self.currentWorkstepWidget = self.blankWorkstepWidget()
        self.workstepWidgetLayout.addWidget(self.currentWorkstepWidget)

        scrollArea = qt.QScrollArea()
        scrollArea.setWidget(workstepWidgetFrame)
        scrollArea.setWidgetResizable(True)
        workstepLayout.addWidget(scrollArea)

        workstepStateButtonsLayout = qt.QHBoxLayout()
        workstepStateButtonsLayout.addWidget(qt.QWidget())
        resetWorkstepButton = qt.QPushButton("Reset to default")
        resetWorkstepButton.setIcon(qt.QIcon(str(Customizer.RESET_ICON_PATH)))
        workstepStateButtonsLayout.addWidget(resetWorkstepButton)
        workstepStateButtonsLayout.addWidget(qt.QWidget())
        workstepLayout.addLayout(workstepStateButtonsLayout)

        # Connections
        resetWorkstepButton.clicked.connect(self.resetWorkstep)

        frame = qt.QFrame()
        frame.setLayout(workstepLayout)
        return frame

    def resetWorkstep(self):
        self.currentWorkstepWidget.reset()

    def setWorkstepWidget(self, workstepWidget):
        self.workstepWidgetLayout.replaceWidget(self.currentWorkstepWidget, workstepWidget)
        self.currentWorkstepWidget.save()
        self.currentWorkstepWidget.delete()
        self.currentWorkstepWidget = workstepWidget
        self.currentWorkstepWidget.load()

    def statusPanel(self):
        statusLayout = qt.QVBoxLayout()
        statusLayout.setContentsMargins(0, 0, 0, 0)

        self.workflowProgressBar = qt.QProgressBar()
        self.workflowProgressBar.setRange(0, 100)
        self.workflowProgressBar.setFormat("Workflow: %v%")
        self.workflowProgressBar.setValue(0)
        statusLayout.addWidget(self.workflowProgressBar)

        self.statusTextEdit = qt.QPlainTextEdit()
        self.statusTextEdit.setReadOnly(True)
        statusLayout.addWidget(self.statusTextEdit)

        frame = qt.QFrame()
        frame.setLayout(statusLayout)
        return frame

    def run(self):
        if not self.validateWorkflow():
            slicer.util.warningDisplay("All workflow errors must be resolved before running the workflow.")
            return

        selectedItems = vtk.vtkIdList()
        self.subjectHierarchyTreeView.currentItems(selectedItems)
        try:
            if self.workstepsListWidget.count == 0:
                raise WorkflowInfo("There are no worksteps to be run.")
            runWorkflow = (
                self.workflow.runStepByStep if self.runStepByStepAction.isChecked() else self.workflow.runNodeByNode
            )
            with ProgressBarProc() as pb:
                pb.setTitle("Running workflow")
                self.progressBarProc = pb
                runWorkflow(selectedItems, self.getWorkstepsIds())
        except WorkflowInfo as e:
            slicer.util.infoDisplay(str(e))
            return

    def stop(self):
        self.workflow.stop()

    def getWorkstepsIds(self):
        workstepIds = []
        for i in range(self.workstepsListWidget.count):
            workstepIds.append(self.workstepsListWidget.item(i).data(qt.Qt.UserRole))
        return workstepIds

    def validateWorkflow(self):
        self.currentWorkstepWidget.save()
        selectedItems = vtk.vtkIdList()
        self.subjectHierarchyTreeView.currentItems(selectedItems)
        workstepsIds = self.getWorkstepsIds()
        typeErrors = self.workflow.typeCheck(selectedItems, workstepsIds)
        validationErrors = self.workflow.validate(workstepsIds)

        ok = True
        for i in range(self.workstepsListWidget.count):
            widget = self.workstepsListWidget.item(i)
            typeError = typeErrors[i]
            validationError = validationErrors[i]
            widget.setIcon(
                qt.QIcon(
                    str(
                        Workstep.ERROR_ICON_PATH if typeError or (validationError != True) else Workstep.CHECK_ICON_PATH
                    )
                )
            )
            errors = []
            if isinstance(validationError, str):
                errors.append(f"{widget.text()}: {validationError}")
            if typeError:
                errors.append(str(typeError))

            if errors:
                ok = False

            errorText = "\n".join(errors)
            widget.setToolTip(errorText)
        return ok

    def onStatusMessage(self, message):
        self.statusTextEdit.setPlainText(message)
        self.statusTextEdit.setStyleSheet("")
        self.progressBarProc.setMessage(message)
        slicer.app.processEvents()

    def onStatusError(self, message):
        self.statusTextEdit.setPlainText(message)
        self.statusTextEdit.setStyleSheet("color: red")
        self.progressBarProc.setMessage(message)
        slicer.app.processEvents()

    def onProgress(self, progress):
        progress *= 100
        self.workflowProgressBar.setValue(progress)
        self.progressBarProc.setProgress(progress)
        slicer.app.processEvents()
