import qt
import slicer

from ltrace.slicer_utils import getResourcePath


class TableWidget(qt.QWidget):
    def __init__(self, logic):
        super().__init__()
        self.thinSectionInstanceEditorLogic = logic
        self.tableView = None

    def setup(self):
        self.setLayout(qt.QFormLayout())
        self.layout().setLabelAlignment(qt.Qt.AlignRight)
        self.layout().setContentsMargins(0, 0, 0, 0)

        self.tableView = qt.QTableView()
        self.tableView.setEditTriggers(qt.QTableView.NoEditTriggers)
        self.tableView.setSelectionBehavior(qt.QTableView.SelectRows)
        self.tableView.setSelectionMode(qt.QTableView.SingleSelection)
        horizontalHeader = self.tableView.horizontalHeader()
        horizontalHeader.setSectionResizeMode(qt.QHeaderView.ResizeToContents)
        # horizontalHeader.setSectionResizeMode(qt.QHeaderView.Stretch)
        self.tableView.verticalHeader().hide()
        # self.tableView.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)
        self.tableView.horizontalHeader().setSortIndicator(0, qt.Qt.AscendingOrder)
        self.tableView.setSortingEnabled(True)
        self.layout().addRow(self.tableView)

        self.previousButton = qt.QPushButton("Previous")
        self.previousButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Undo.png"))
        self.previousButton.clicked.connect(self.onPreviousButtonClicked)

        self.nextButton = qt.QPushButton("Next")
        self.nextButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Redo.png"))
        self.nextButton.clicked.connect(self.onNextButtonClicked)

        self.resetFiltersButton = qt.QPushButton("Reset filters")
        self.resetFiltersButton.setIcon(qt.QIcon(getResourcePath("Icons") / "Reset.png"))
        self.resetFiltersButton.clicked.connect(lambda: self.setAllRangeWidgetValues(resetValues=True))

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.addWidget(self.previousButton)
        buttonsLayout.addWidget(self.nextButton)
        buttonsLayout.addWidget(self.resetFiltersButton)

        self.layout().addRow(buttonsLayout)

    def tableViewSelectionChanged(self, selected, deselected):
        selectedIndexes = selected.indexes()
        if len(selectedIndexes) > 0:
            currentlyLabelID = slicer.mrmlScene.GetNthNodeByClass(0, "vtkMRMLSliceCompositeNode").GetLabelVolumeID()
            if currentlyLabelID:
                currentlySelectedLabelMap = slicer.util.getNode(currentlyLabelID)
                correspondingTableNodeID = currentlySelectedLabelMap.GetAttribute("ThinSectionInstanceTableNode")
                currentTableNode = self.thinSectionInstanceEditorLogic.tableNodeID

                if correspondingTableNodeID == currentTableNode:
                    label = int(float(selectedIndexes[0].data()))
                    self.thinSectionInstanceEditorLogic.centerToLabel(label)
                else:
                    slicer.util.infoDisplay("Current report do not correspond to the selected class.")

    def onPreviousButtonClicked(self):
        self.nextPreviousItem(-1)

    def onNextButtonClicked(self):
        self.nextPreviousItem(1)

    def nextPreviousItem(self, direction):
        selectedIndexes = self.tableView.selectedIndexes()
        if len(selectedIndexes) == 0:
            row = 0
        else:
            rowCount = self.tableView.model().rowCount()
            row = selectedIndexes[0].row()
            row = (row + direction) % rowCount
        modelIndex = self.tableView.model().index(row, 0)
        self.tableView.setCurrentIndex(modelIndex)

    def reselectCurrentItem(self):
        self.onNextButtonClicked()
        self.onPreviousButtonClicked()

    def filterValuesChanged(self, *args):
        excludingDataFrame = self.createExcludingDataFrame()
        self.tableView.model().setFilteredLabels(excludingDataFrame["label"].values)

    def createExcludingDataFrame(self):
        raise NotImplementedError

    def setRangeWidgetValues(self, dataFrame, rangeWidget, column, resetValues=True, minVal=None, maxVal=None):
        if len(dataFrame.index) > 0:
            # we subtract/add these small values so that the spinbox reaches the min and max
            minimumValue = min(dataFrame[column]) - rangeWidget.singleStep
            maximumValue = max(dataFrame[column]) + rangeWidget.singleStep
            minimumValue = minVal if minVal is not None else minimumValue
            maximumValue = maxVal if maxVal is not None else maximumValue
            rangeWidget.blockSignals(True)
            rangeWidget.setRange(minimumValue, maximumValue)
            rangeWidget.blockSignals(False)
            if resetValues:
                rangeWidget.blockSignals(True)
                rangeWidget.setRange(minimumValue, maximumValue)
                rangeWidget.minimumValue = minimumValue
                rangeWidget.maximumValue = maximumValue
                rangeWidget.blockSignals(False)
