import logging
import qt
import slicer

from ltrace.slicer.tests.constants import TestState
from ltrace.slicer.tests.ltrace_tests_model import LTraceTestsModel, TestSuiteData, TestCaseData, TestsSource
from ltrace.slicer.tests.utils import log, loadAllModules
from pathlib import Path
from typing import List, Union

RESOURCES_DIR = Path(__file__).parent / "resources"


class ASortFilterProxyModel(qt.QSortFilterProxyModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sort(0, qt.Qt.AscendingOrder)
        self.setSortCaseSensitivity(qt.Qt.CaseInsensitive)
        self.setFilterCaseSensitivity(qt.Qt.CaseInsensitive)

    def filterAcceptsRow(self, sourceRow, sourceParent):
        if self.sourceModel is None:
            return True

        model = sourceParent.model()
        if model is not None:
            parentItem = model.item(sourceParent.row())

            if parentItem.isEnabled():
                return True

        return qt.QSortFilterProxyModel.filterAcceptsRow(self, sourceRow, sourceParent)


class ATreeViewItem(qt.QStandardItem):
    def __init__(self, data: Union[TestCaseData, TestSuiteData], *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert data is not None
        self._testData = None
        self.testData = data

    @property
    def testData(self):
        return self._testData

    @testData.setter
    def testData(self, data):
        if self._testData is not None:
            self._testData.enablement_changed.disconnect(self.onEnablementChanged)

        self._testData = data
        self._testData.enablement_changed.connect(self.onEnablementChanged)

        self._setup()

    def _setup(self):
        self.setEditable(False)
        self.setText(self.testData.name)
        checkState = qt.Qt.Checked if self.testData.enabled else qt.Qt.Unchecked
        self.setFlags(self.flags() | qt.Qt.ItemIsUserCheckable | qt.Qt.ItemIsSelectable)
        self.setCheckState(checkState)

    def setCheckBoxEnabled(self, state: bool):
        if state:
            self.setFlags(self.flags() | qt.Qt.ItemIsEnabled)
        else:
            self.setFlags(self.flags() & ~qt.Qt.ItemIsEnabled)

    def onEnablementChanged(self, state: bool):
        checkState = qt.Qt.Checked if state is True else qt.Qt.Unchecked
        self.setCheckState(checkState)


class ATreeView(qt.QTreeView):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setHeaderHidden(True)
        self.standardItemModel = qt.QStandardItemModel()
        self.sortModel = ASortFilterProxyModel(self)
        self.sortModel.setSourceModel(self.standardItemModel)
        self.setModel(self.sortModel)
        self.standardItemModel.itemChanged.connect(self.__onTreeViewItemClicked)

    def clear(self) -> None:
        self.standardItemModel.clear()

    def setFilterRegularExpression(self, text) -> None:
        self.sortModel.setFilterRegularExpression(text)

    def appendItem(self, item: ATreeViewItem) -> None:
        self.standardItemModel.invisibleRootItem().appendRow(item)

    def selectAll(self) -> None:
        for item in self.__items():
            item.testData.enabled = True

    def unselectAll(self) -> None:
        for item in self.__items():
            item.testData.enabled = False

    def __items(self):
        totalRowsDisplayed = self.sortModel.rowCount()

        for i in range(totalRowsDisplayed):
            modelIndex = self.sortModel.index(i, 0)
            modelIndex2 = self.sortModel.mapToSource(modelIndex)
            item = self.standardItemModel.itemFromIndex(modelIndex2)
            if item is None:
                continue

            yield item

    def __onTreeViewItemClicked(self, item):
        itemCheckState = item.checkState()

        if item is None:
            raise RuntimeError("Selected item data wasn't found in the current list. Please restart the application.")

        item.testData.enabled = True if itemCheckState == qt.Qt.Checked else False

    def filteredItemsCount(self):
        return self.sortModel.rowCount()


class TestCaseTreeViewItem(ATreeViewItem):
    def __init__(self, data: TestCaseData, *args, **kwargs):
        super().__init__(data, *args, **kwargs)


class TestSuiteTreeViewItem(ATreeViewItem):
    def __init__(self, data: TestSuiteData, *args, **kwargs):
        super().__init__(data, *args, **kwargs)

    @ATreeViewItem.testData.setter
    def testData(self, data: TestSuiteData):
        if self._testData is not None:
            self._testData.enablement_changed.disconnect(self.onEnablementChanged)

        self.removeRows(0, self.rowCount())

        for testCaseData in data.test_case_data_list:
            childItem = TestCaseTreeViewItem(testCaseData)
            self.appendRow(childItem)

        self._testData = data
        self._testData.enablement_changed.connect(self.onEnablementChanged)
        self._setup()


class LogWidgetHandler(logging.Handler):
    """Custom logging handler for showing log in text browser widget."""

    def __init__(self, callback, *args, **kwargs):
        super().__init__(*args, **kwargs)
        formatter = logging.Formatter("%(message)s%(end)s")
        self.setFormatter(formatter)
        self.__callback = callback

    def emit(self, record):
        message = self.format(record)

        if hasattr(self, "end"):
            self.terminator = ""

        if self.__callback is not None:
            self.__callback(message)


class LTraceTestsWidget(qt.QDialog):
    TEST_TAB = 0
    GENERATE_TAB = 1

    def __init__(self, parent=None, currentModule=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        loadAllModules()
        self.__model = LTraceTestsModel(test_source=TestsSource.GEOSLICER)
        self.__testSuiteItemList: List[TestSuiteTreeViewItem] = []
        self.__generateSuiteItemList: List[TestCaseTreeViewItem] = []
        self.__testCasesCount = 0
        self.__generateCasesCount = 0
        self.__setupUi()
        self.__installLoggerHandler()
        self.__populateTree()
        self.__selectCurrentModuleTests(currentModule)

    def __selectCurrentModuleTests(self, currentModule):
        if currentModule is None or not hasattr(self, "testTreeView"):
            return

        for testSuiteItem in self.__testSuiteItemList:
            if currentModule not in testSuiteItem.testData.name:
                continue

            testSuiteItem.testData.enabled = True
            self.__testTreeView.scrollTo(testSuiteItem.index())
            break

    def __setupUi(self):
        self.setMinimumSize(1080, 720)
        self.setWindowTitle("GeoSlicer Test GUI")
        self.setWindowFlags(self.windowFlags() & ~qt.Qt.WindowContextHelpButtonHint | qt.Qt.WindowMinMaxButtonsHint)

        # Options layout
        self.__searchLineEdit = qt.QLineEdit()
        self.__searchLineEdit.setPlaceholderText("Search")

        ## Select/Unselect tests cases buttons
        self.__selectAllItemsButton = qt.QPushButton("Select all")
        self.__unselectAllItemsButton = qt.QPushButton("Unselect all")
        self.__totalTestsLabel = qt.QLabel(f"{self.testCasesCount}")

        selectButtonsLayout = qt.QHBoxLayout()
        selectButtonsLayout.addWidget(qt.QLabel("Total tests:"))
        selectButtonsLayout.addSpacing(5)
        selectButtonsLayout.addWidget(self.__totalTestsLabel)
        selectButtonsLayout.addStretch()
        selectButtonsLayout.addWidget(self.__selectAllItemsButton)
        selectButtonsLayout.addWidget(self.__unselectAllItemsButton)

        ## Tree widget of tests
        self.__testTreeView = ATreeView()
        self.__generateTreeView = ATreeView()

        self.__treeWidgetTabs = qt.QTabWidget()
        self.__treeWidgetTabs.addTab(self.__testTreeView, "Tests")
        self.__treeWidgetTabs.addTab(self.__generateTreeView, "Generate")
        self.__treeWidgetTabs.setEnabled(True)

        ## Options group box
        optionsFormLayout = qt.QFormLayout()
        optionsFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.__shuffleCheckBox = qt.QCheckBox()
        self.__breakOnFailureCheckBox = qt.QCheckBox()
        self.__clearSceneAfterTestsCheckBox = qt.QCheckBox()

        self.__shuffleCheckBox.setToolTip("Run tests cases in random order if activated.")
        self.__breakOnFailureCheckBox.setToolTip("Stop test run after an failure if activated")
        self.__clearSceneAfterTestsCheckBox.setToolTip(
            "Clear scene data after the last test run if activated. "
            + "When inactivated, it helps to analyse scene data when a failure occurs. "
            + "Works best with 'break on failure' option."
        )

        self.__shuffleCheckBox.setChecked(qt.Qt.Checked)
        self.__breakOnFailureCheckBox.setChecked(qt.Qt.Unchecked)
        self.__clearSceneAfterTestsCheckBox.setChecked(qt.Qt.Checked)

        optionsFormLayout.addRow("Shuffle", self.__shuffleCheckBox)
        optionsFormLayout.addRow("Break on failure", self.__breakOnFailureCheckBox)
        optionsFormLayout.addRow("Clear scene after test", self.__clearSceneAfterTestsCheckBox)

        optionsGroupBox = qt.QGroupBox("Options")
        optionsGroupBox.setAlignment(qt.Qt.AlignHCenter)
        optionsGroupBox.setLayout(optionsFormLayout)

        optionsLayout = qt.QVBoxLayout()
        optionsLayout.addLayout(selectButtonsLayout, 1)
        optionsLayout.addWidget(self.__searchLineEdit, 4)
        optionsLayout.addWidget(self.__treeWidgetTabs, 4)
        optionsLayout.addWidget(optionsGroupBox, 1)

        # Logging layout
        self.__logTextBrowser = qt.QTextBrowser()
        loggingLayout = qt.QVBoxLayout()
        loggingLayout.addWidget(self.__logTextBrowser)
        loggingGroupBox = qt.QGroupBox("Logs")
        loggingGroupBox.setAlignment(qt.Qt.AlignCenter)
        loggingGroupBox.setLayout(loggingLayout)

        # Run layout
        ## Progress bar
        self.__progressBar = qt.QProgressBar()
        self.__progressBar.setVisible(False)

        progressBarLayout = qt.QVBoxLayout()
        progressBarLayout.addWidget(self.__progressBar)

        ## Run & Cancel button
        self.__runButton = qt.QPushButton("Run")
        self.__runButton.setIcon(qt.QIcon(str(RESOURCES_DIR / "play_button.png")))

        self.__cancelButton = qt.QPushButton("Cancel")
        self.__cancelButton.setIcon(qt.QIcon(str(RESOURCES_DIR / "stop_button.png")))
        self.__cancelButton.setVisible(False)

        runCancelButtonLayout = qt.QVBoxLayout()
        runCancelButtonLayout.addWidget(self.__runButton)
        runCancelButtonLayout.addWidget(self.__cancelButton)

        # Main layout
        layout = qt.QGridLayout()
        layout.addLayout(optionsLayout, 0, 0, 4, 2)
        layout.addWidget(loggingGroupBox, 0, 2, 4, 4)
        layout.addLayout(progressBarLayout, 5, 0, 1, 6)
        layout.addLayout(runCancelButtonLayout, 6, 2, 1, 2)
        self.setLayout(layout)

        # connections
        self.__runButton.clicked.connect(self.__onRunButtonClicked)
        self.__cancelButton.clicked.connect(self.__onCancelButtonClicked)
        self.__selectAllItemsButton.clicked.connect(self.__onSelectAllButtonClicked)
        self.__unselectAllItemsButton.clicked.connect(self.__onUnselectAllButtonClicked)
        self.__searchLineEdit.textChanged.connect(self.__onSearchTextChanged)
        self.__treeWidgetTabs.currentChanged.connect(self.__onTabChanged)

        # Update search input based on the last stored value
        lastSearchInput = slicer.app.settings().value("LTraceTestsWidget/LastSearch", "")
        if lastSearchInput:
            self.__searchLineEdit.setText(lastSearchInput)

    def __onSearchTextChanged(self, text):
        self.__testTreeView.setFilterRegularExpression(text)
        self.__generateTreeView.setFilterRegularExpression(text)

        isValid = self.__testTreeView.filteredItemsCount() > 0 or self.__generateTreeView.filteredItemsCount() > 0
        searchQuery = text if isValid else ""
        slicer.app.settings().setValue("LTraceTestsWidget/LastSearch", searchQuery)

    def __onTabChanged(self, state: bool):
        casesCount = self.__testCasesCount if state == self.TEST_TAB else self.__generateCasesCount
        self.__totalTestsLabel.setText(f"{casesCount}")

    def __setAllTreeWidgetItemEnable(self, state: bool):
        tabIndex = self.__treeWidgetTabs.currentIndex
        suiteItemList = self.__testSuiteItemList if tabIndex == self.TEST_TAB else self.__generateSuiteItemList
        for testSuiteItem in suiteItemList:
            testSuiteItem.setCheckBoxEnabled(state)

    def __onSelectAllButtonClicked(self, state):
        tree = self.__getCurrentTree()
        tree.selectAll()

    def __onUnselectAllButtonClicked(self, state):
        tree = self.__getCurrentTree()
        tree.unselectAll()

    def __getCurrentTree(self) -> ATreeView:
        return self.__testTreeView if self.__treeWidgetTabs.currentIndex == self.TEST_TAB else self.__generateTreeView

    @property
    def testCasesCount(self):
        return self.__testCasesCount

    @testCasesCount.setter
    def testCasesCount(self, value):
        self.__testCasesCount = value
        self.__totalTestsLabel.setText(f"{self.__testCasesCount}")

    @property
    def generateCasesCount(self):
        return self.__generateCasesCount

    @generateCasesCount.setter
    def generateCasesCount(self, value):
        self.__generateCasesCount = value
        self.__totalTestsLabel.setText(f"{self.__generateCasesCount}")

    def accept(self):
        qt.QDialog.accept(self)
        self.uninstallLoggerHandler()

    def reject(self):
        qt.QDialog.reject(self)
        self.uninstallLoggerHandler()

    def loggerCallback(self, message):
        if self.__logTextBrowser is None:
            return

        self.__logTextBrowser.insertPlainText(message)

    def __installLoggerHandler(self):
        self.loggerHandler = LogWidgetHandler(callback=self.loggerCallback)
        logging.getLogger("tests_logger").addHandler(self.loggerHandler)

    def uninstallLoggerHandler(self):
        if not hasattr(self, "loggerHandler") or self.loggerHandler is None:
            return

        logging.getLogger("tests_logger").removeHandler(self.loggerHandler)

    def __populateTree(self):
        self.__testTreeView.clear()
        self.__generateTreeView.clear()
        self.__testSuiteItemList.clear()
        self.__generateSuiteItemList.clear()
        self.testCasesCount = 0
        self.generateCasesCount = 0

        for test_suite in self.__model.test_suite_list:
            testSuiteItem = TestSuiteTreeViewItem(data=test_suite)
            testSuiteItem.testData.test_case_enablement_changed.connect(self.__onTestCaseEnablementChanged)
            self.__testSuiteItemList.append(testSuiteItem)

            self.__testTreeView.appendItem(testSuiteItem)

        for test_suite in self.__model.generate_suite_list:
            testSuiteItem = TestSuiteTreeViewItem(data=test_suite)
            testSuiteItem.testData.test_case_enablement_changed.connect(self.__onGenerateCaseEnablementChanged)
            self.__generateSuiteItemList.append(testSuiteItem)

            self.__generateTreeView.appendItem(testSuiteItem)

    def __onTestCaseEnablementChanged(self, state: bool):
        value = 1 if state else -1
        self.testCasesCount = self.testCasesCount + value

    def __onGenerateCaseEnablementChanged(self, state: bool):
        value = 1 if state else -1
        self.generateCasesCount = self.generateCasesCount + value

    def __onRunButtonClicked(self, state):
        if self.__model.is_running:
            return

        selectedTab = self.__treeWidgetTabs.currentIndex
        casesCount = self.testCasesCount if selectedTab == self.TEST_TAB else self.generateCasesCount

        if casesCount <= 0:
            slicer.util.infoDisplay("Please select a test.", parent=self)
            return

        self.__logTextBrowser.clear()

        # Disable widgets
        self.__setAllTreeWidgetItemEnable(False)
        self.__runButton.setEnabled(False)
        qt.QTimer.singleShot(
            1000, lambda: self.__cancelButton.setEnabled(True)
        )  # Avoid missclick after starting the test process.
        self.__selectAllItemsButton.setEnabled(False)
        self.__unselectAllItemsButton.setEnabled(False)
        self.__model.test_case_finished.connect(self.__onTestCaseFinished)

        # Start progress bar
        self.__progressBar.reset()
        self.__progressBar.setRange(0, casesCount)
        self.__progressBar.setValue(0)
        self.__progressBar.setVisible(True)

        # Update run/cancel buttons
        self.__cancelButton.setVisible(True)
        self.__runButton.setVisible(False)
        self.__treeWidgetTabs.setEnabled(False)

        suiteList = self.__model.test_suite_list if selectedTab == self.TEST_TAB else self.__model.generate_suite_list
        # Disable cases from the other suite list (other tab)
        otherSuiteList = (
            self.__model.test_suite_list if selectedTab != self.TEST_TAB else self.__model.generate_suite_list
        )
        for suiteData in otherSuiteList:
            suiteData.enabled = False

        # Start running tests
        self.__model.run_tests(
            suite_list=suiteList,
            shuffle=self.__shuffleCheckBox.isChecked(),
            break_on_failure=self.__breakOnFailureCheckBox.isChecked(),
            after_clear=self.__clearSceneAfterTestsCheckBox.isChecked(),
        )
        test_process_result = self.__model.result()

        if test_process_result == TestState.FAILED:
            slicer.util.infoDisplay("Some tests have failed. Please check the logs.", parent=self)
        elif test_process_result == TestState.SUCCEED:
            slicer.util.infoDisplay("All tests passed successfully!", parent=self)
        else:
            slicer.util.infoDisplay(
                "Unexpected behavior. Please check the logs and inform the development team.", parent=self
            )

        # User feedback
        for test_suite_data in self.__model.test_suite_list + self.__model.generate_suite_list:
            if warning_text := test_suite_data.warning_log_text:
                log(warning_text)
            if failure_text := test_suite_data.failure_log_text:
                log(failure_text)

        # Reset progress bar
        self.__progressBar.setValue(casesCount)
        self.__progressBar.setVisible(False)

        # Remove connections
        self.__model.test_case_finished.disconnect(self.__onTestCaseFinished)

        # Re-enable widgets
        self.__setAllTreeWidgetItemEnable(True)
        self.__cancelButton.setVisible(False)
        self.__cancelButton.setEnabled(False)
        self.__runButton.setEnabled(True)
        self.__runButton.setVisible(True)
        self.__selectAllItemsButton.setEnabled(True)
        self.__unselectAllItemsButton.setEnabled(True)
        self.__treeWidgetTabs.setEnabled(True)

    def __onCancelButtonClicked(self, state):
        if not self.__model.is_running:
            return

        self.__cancelButton.setEnabled(False)
        self.__cancelButton.setText("Cancelling...")
        self.__model.tests_cancelled.connect(self.onTestCancelled)
        self.__model.cancel()

    def onTestCancelled(self):
        self.__cancelButton.setVisible(False)
        self.__cancelButton.setEnabled(False)
        self.__cancelButton.setText("Cancel")
        self.__runButton.setEnabled(True)
        self.__runButton.setVisible(True)
        self.__model.tests_cancelled.disconnect()

    def __onTestCaseFinished(self, testSuiteData, testCaseData):
        self.__progressBar.setValue(self.__progressBar.value + 1)
