import logging
import qt
import slicer

from ltrace.slicer.tests.constants import TestState
from ltrace.slicer.tests.ltrace_tests_model import LTraceTestsModel, TestSuiteData, TestCaseData, TestsSource
from ltrace.slicer.tests.utils import log
from pathlib import Path

RESOURCES_DIR = Path(__file__).parent / "resources"


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


class TestSuiteDataWidgetItem(qt.QTreeWidgetItem):
    def __init__(self, data: TestSuiteData, *args, **kwargs):
        qt.QTreeWidgetItem.__init__(self, *args, **kwargs)
        qt.QObject.__init__(self, *args, **kwargs)
        self.__test_suite_data = None
        self.__test_case_data_widget_list = []
        self.test_suite_data = data

    def __setup(self):
        self.setText(0, self.__test_suite_data.name)
        self.setFlags(self.flags() | qt.Qt.ItemIsUserCheckable | qt.Qt.ItemIsSelectable)
        check_state = qt.Qt.Checked if self.__test_suite_data.enabled else qt.Qt.Unchecked
        self.setCheckState(0, check_state)

    def set_check_box_enabled(self, state: bool):
        if state:
            self.setFlags(self.flags() | qt.Qt.ItemIsEnabled)
        else:
            self.setFlags(self.flags() & ~qt.Qt.ItemIsEnabled)

        for test_case_widget in self.__test_case_data_widget_list:
            test_case_widget.set_check_box_enabled(state)

    @property
    def test_case_data_widget_list(self):
        return self.__test_case_data_widget_list

    @property
    def test_suite_data(self):
        return self.__test_suite_data

    @test_suite_data.setter
    def test_suite_data(self, data: TestSuiteData):
        if self.__test_suite_data is not None:
            self.__test_suite_data.enablement_changed.disconnect(self.on_enablement_changed)

            for test_case_widget in self.__test_case_data_widget_list:
                test_case_widget.blockSignals(True)
                del test_case_widget

        for test_case_data in data.test_case_data_list:
            child_item = TestCaseDataWidgetItem(test_case_data)
            self.__test_case_data_widget_list.append(child_item)
            self.addChild(child_item)

        self.__test_suite_data = data
        self.__test_suite_data.enablement_changed.connect(self.on_enablement_changed)
        self.__setup()

    def on_enablement_changed(self, state):
        check_state = qt.Qt.Checked if state is True else qt.Qt.Unchecked
        self.setCheckState(0, check_state)
        self.setExpanded(state)


class TestCaseDataWidgetItem(qt.QTreeWidgetItem):
    def __init__(self, data: TestCaseData, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__test_case_data = None
        self.test_case_data = data

    def __setup(self):
        self.setText(0, self.__test_case_data.name)
        self.setFlags(self.flags() | qt.Qt.ItemIsUserCheckable | qt.Qt.ItemIsSelectable)
        check_state = qt.Qt.Checked if self.__test_case_data.enabled else qt.Qt.Unchecked
        self.setCheckState(0, check_state)
        self.setToolTip(0, self.__test_case_data.name)

    def set_check_box_enabled(self, state: bool):
        if state:
            self.setFlags(self.flags() | qt.Qt.ItemIsEnabled)
        else:
            self.setFlags(self.flags() & ~qt.Qt.ItemIsEnabled)

    @property
    def test_case_data(self):
        return self.__test_case_data

    @test_case_data.setter
    def test_case_data(self, data: TestCaseData):
        if self.__test_case_data is not None:
            self.__test_case_data.enablement_changed.disconnect(self.on_enablement_changed)

        self.__test_case_data = data
        self.__test_case_data.enablement_changed.connect(self.on_enablement_changed)
        self.__setup()

    def on_enablement_changed(self, state):
        check_state = qt.Qt.Checked if state is True else qt.Qt.Unchecked
        self.setCheckState(0, check_state)


class LTraceTestsWidget(qt.QDialog):
    def __init__(self, parent=None, current_module=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.__model = LTraceTestsModel(test_source=TestsSource.GEOSLICER)
        self.__test_suite_widget_list = []
        self.__generate_suite_widget_list = []
        self.__test_cases_count = 0
        self.__generate_cases_count = 0
        self.setup_ui()
        self.__install_logger_handler()
        self.__populate_tree()
        self.__select_current_module_tests(current_module)

    def __select_current_module_tests(self, current_module):
        if current_module is None or not hasattr(self, "tree_widget"):
            return

        for test_suite in self.__test_suite_widget_list:
            if current_module not in test_suite.test_suite_data.name:
                continue

            test_suite.test_suite_data.enabled = True
            self.tree_widget_tests.scrollToItem(test_suite)
            break

    def setup_ui(self):
        self.setMinimumSize(1080, 720)
        self.setWindowTitle("GeoSlicer Test GUI")
        self.setWindowFlags(self.windowFlags() & ~qt.Qt.WindowContextHelpButtonHint | qt.Qt.WindowMinMaxButtonsHint)

        # Options layout
        ## Test sources checkbox
        self.__geoslicer_test_source_check_box = qt.QCheckBox("GeoSlicer")
        self.__slicer_test_source_check_box = qt.QCheckBox("Slicer")
        self.__slicer_test_source_check_box.setEnabled(False)  # Disable it because its not functional yet
        test_source_layout = qt.QHBoxLayout()
        test_source_layout.addWidget(qt.QLabel("Source:"))
        test_source_layout.addSpacing(10)
        test_source_layout.addWidget(self.__geoslicer_test_source_check_box)
        test_source_layout.addWidget(self.__slicer_test_source_check_box)
        test_source_layout.addStretch()

        ## Select/Unselect tests cases buttons
        self.__select_all_items_button = qt.QPushButton("Select all")
        self.__unselect_all_items_button = qt.QPushButton("Unselect all")
        self.__total_tests_label = qt.QLabel(f"{self.test_cases_count}")

        select_buttons_layout = qt.QHBoxLayout()
        select_buttons_layout.addWidget(qt.QLabel("Total tests:"))
        select_buttons_layout.addSpacing(5)
        select_buttons_layout.addWidget(self.__total_tests_label)
        select_buttons_layout.addStretch()
        select_buttons_layout.addWidget(self.__select_all_items_button)
        select_buttons_layout.addWidget(self.__unselect_all_items_button)

        ## Checkboxes default values
        self.__geoslicer_test_source_check_box.setChecked(True)
        self.__slicer_test_source_check_box.setChecked(False)

        ## Tree widget of tests
        self.tree_widget_tests = qt.QTreeWidget()
        self.tree_widget_tests.setColumnCount(1)
        self.tree_widget_tests.setHeaderHidden(True)

        ## Tree widget of template generation
        self.tree_widget_generate = qt.QTreeWidget()
        self.tree_widget_generate.setColumnCount(1)
        self.tree_widget_generate.setHeaderHidden(True)

        self.tree_widget_tabs = qt.QTabWidget()
        self.tree_widget_tabs.addTab(self.tree_widget_tests, "Tests")
        self.tree_widget_tabs.addTab(self.tree_widget_generate, "Generate")
        self.tree_widget_tabs.currentChanged.connect(self.__on_tab_changed)

        ## Options group box
        options_form_layout = qt.QFormLayout()
        options_form_layout.setLabelAlignment(qt.Qt.AlignRight)

        self.__shuffle_check_box = qt.QCheckBox()
        self.__break_on_failure_check_box = qt.QCheckBox()
        self.__clear_scene_after_tests_check_box = qt.QCheckBox()

        self.__shuffle_check_box.setToolTip("Run tests cases in random order if activated.")
        self.__break_on_failure_check_box.setToolTip("Stop test run after an failure if activated")
        self.__clear_scene_after_tests_check_box.setToolTip(
            "Clear scene data after the last test run if activated. "
            + "When inactivated, it helps to analyse scene data when a failure occurs. "
            + "Works best with 'break on failure' option."
        )

        self.__shuffle_check_box.setChecked(qt.Qt.Checked)
        self.__break_on_failure_check_box.setChecked(qt.Qt.Unchecked)
        self.__clear_scene_after_tests_check_box.setChecked(qt.Qt.Checked)

        options_form_layout.addRow("Shuffle", self.__shuffle_check_box)
        options_form_layout.addRow("Break on failure", self.__break_on_failure_check_box)
        options_form_layout.addRow("Clear scene after test", self.__clear_scene_after_tests_check_box)

        options_group_box = qt.QGroupBox("Options")
        options_group_box.setAlignment(qt.Qt.AlignCenter)
        options_group_box.setLayout(options_form_layout)

        options_layout = qt.QVBoxLayout()
        options_layout.addLayout(test_source_layout, 1)
        options_layout.addLayout(select_buttons_layout, 1)
        options_layout.addWidget(self.tree_widget_tabs, 4)
        options_layout.addWidget(options_group_box, 1)

        # Logging layout
        self.__log_text_browser = qt.QTextBrowser()
        logging_layout = qt.QVBoxLayout()
        logging_layout.addWidget(self.__log_text_browser)
        logging_group_box = qt.QGroupBox("Logs")
        logging_group_box.setAlignment(qt.Qt.AlignCenter)
        logging_group_box.setLayout(logging_layout)

        # Run layout
        ## Progress bar
        self.__progress_bar = qt.QProgressBar()
        self.__progress_bar.setVisible(False)

        progress_bar_layout = qt.QVBoxLayout()
        progress_bar_layout.addWidget(self.__progress_bar)

        ## Run & Cancel button
        self.__run_button = qt.QPushButton("Run")
        self.__run_button.setIcon(qt.QIcon(str(RESOURCES_DIR / "play_button.png")))

        self.__cancel_button = qt.QPushButton("Cancel")
        self.__cancel_button.setIcon(qt.QIcon(str(RESOURCES_DIR / "stop_button.png")))
        self.__cancel_button.setVisible(False)

        run_cancel_button_layout = qt.QVBoxLayout()
        run_cancel_button_layout.addWidget(self.__run_button)
        run_cancel_button_layout.addWidget(self.__cancel_button)

        # Main layout
        layout = qt.QGridLayout()
        layout.addLayout(options_layout, 0, 0, 4, 2)
        layout.addWidget(logging_group_box, 0, 2, 4, 4)
        layout.addLayout(progress_bar_layout, 5, 0, 1, 6)
        layout.addLayout(run_cancel_button_layout, 6, 2, 1, 2)
        self.setLayout(layout)

        # connections
        self.__run_button.clicked.connect(self.__on_run_button_clicked)
        self.__cancel_button.clicked.connect(self.__on_cancel_button_clicked)
        self.tree_widget_tests.itemClicked.connect(self.__on_tree_widget_item_clicked)
        self.tree_widget_generate.itemClicked.connect(self.__on_tree_widget_item_clicked)
        self.__geoslicer_test_source_check_box.stateChanged.connect(self.__on_test_source_checkbox_changed)
        self.__slicer_test_source_check_box.stateChanged.connect(self.__on_test_source_checkbox_changed)
        self.__select_all_items_button.clicked.connect(self.__on_select_all_button_clicked)
        self.__unselect_all_items_button.clicked.connect(self.__on_unselect_all_button_clicked)

    def __on_tab_changed(self, state: bool):
        cases_count = self.__test_cases_count if state == 0 else self.__generate_cases_count
        self.__total_tests_label.setText(f"{cases_count}")

    def __set_all_tree_widget_item_enable(self, state: bool):
        tab_index = self.tree_widget_tabs.currentIndex
        widget_list = self.__test_suite_widget_list if tab_index == 0 else self.__generate_suite_widget_list
        for test_suite_widget in widget_list:
            test_suite_widget.set_check_box_enabled(state)

    def __on_select_all_button_clicked(self, state):
        tab_index = self.tree_widget_tabs.currentIndex
        widget_list = self.__test_suite_widget_list if tab_index == 0 else self.__generate_suite_widget_list
        for test_suite_widget in widget_list:
            test_suite_widget.test_suite_data.enabled = True

    def __on_unselect_all_button_clicked(self, state):
        tab_index = self.tree_widget_tabs.currentIndex
        widget_list = self.__test_suite_widget_list if tab_index == 0 else self.__generate_suite_widget_list
        for test_suite_widget in widget_list:
            test_suite_widget.test_suite_data.enabled = False

    @property
    def test_cases_count(self):
        return self.__test_cases_count

    @test_cases_count.setter
    def test_cases_count(self, value):
        self.__test_cases_count = value
        self.__total_tests_label.setText(f"{self.__test_cases_count}")

    @property
    def generate_cases_count(self):
        return self.__generate_cases_count

    @generate_cases_count.setter
    def generate_cases_count(self, value):
        self.__generate_cases_count = value
        self.__total_tests_label.setText(f"{self.__generate_cases_count}")

    def accept(self):
        qt.QDialog.accept(self)
        self.__uninstall_logger_handler()

    def reject(self):
        qt.QDialog.reject(self)
        self.__uninstall_logger_handler()

    def __logger_callback(self, message):
        if self.__log_text_browser is None:
            return

        self.__log_text_browser.insertPlainText(message)

    def __install_logger_handler(self):
        self.__logger_handler = LogWidgetHandler(callback=self.__logger_callback)
        logging.getLogger("tests_logger").addHandler(self.__logger_handler)

    def __uninstall_logger_handler(self):
        if not hasattr(self, "__logger_handler") or self.__logger_handler is None:
            return

        logging.getLogger("tests_logger").removeHandler(self.__logger_handler)

    def __populate_tree(self):
        self.tree_widget_tests.clear()
        self.tree_widget_generate.clear()
        self.__test_suite_widget_list.clear()
        self.__generate_suite_widget_list.clear()
        self.test_cases_count = 0
        self.generate_cases_count = 0

        for test_suite in self.__model.test_suite_list:
            test_suite_widget_item = TestSuiteDataWidgetItem(data=test_suite)
            test_suite_widget_item.test_suite_data.test_case_enablement_changed.connect(
                self.__on_test_case_enablement_changed
            )
            self.__test_suite_widget_list.append(test_suite_widget_item)
            self.tree_widget_tests.addTopLevelItem(test_suite_widget_item)

        for test_suite in self.__model.generate_suite_list:
            test_suite_widget_item = TestSuiteDataWidgetItem(data=test_suite)
            test_suite_widget_item.test_suite_data.test_case_enablement_changed.connect(
                self.__on_generate_case_enablement_changed
            )
            self.__generate_suite_widget_list.append(test_suite_widget_item)
            self.tree_widget_generate.addTopLevelItem(test_suite_widget_item)

    def __on_test_case_enablement_changed(self, state: bool):
        value = 1 if state else -1
        self.test_cases_count = self.test_cases_count + value

    def __on_generate_case_enablement_changed(self, state: bool):
        value = 1 if state else -1
        self.generate_cases_count = self.generate_cases_count + value

    def __on_test_source_checkbox_changed(self, state):
        selected_test_source = TestsSource.ANY
        if self.__geoslicer_test_source_check_box.isChecked() and not self.__slicer_test_source_check_box.isChecked():
            selected_test_source = TestsSource.GEOSLICER
        elif not self.__geoslicer_test_source_check_box.isChecked() and self.__slicer_test_source_check_box.isChecked():
            selected_test_source = TestsSource.SLICER

        if selected_test_source == self.__model.test_source:
            return

        self.__model.test_source = selected_test_source
        self.__populate_tree()

    def __on_run_button_clicked(self, state):
        if self.__model.is_running:
            return

        selected_tab = self.tree_widget_tabs.currentIndex

        if selected_tab == 0:
            cases_count = self.test_cases_count
        else:
            cases_count = self.generate_cases_count

        if cases_count <= 0:
            slicer.util.infoDisplay("Please select a test.", parent=self)
            return

        self.__log_text_browser.clear()

        # Disable widgets
        self.__set_all_tree_widget_item_enable(False)
        self.__run_button.setEnabled(False)
        qt.QTimer.singleShot(
            1000, lambda: self.__cancel_button.setEnabled(True)
        )  # Avoid missclick after starting the test process.
        self.__select_all_items_button.setEnabled(False)
        self.__unselect_all_items_button.setEnabled(False)
        self.__model.test_case_finished.connect(self.__on_test_case_finished)

        # Start progress bar
        self.__progress_bar.reset()
        self.__progress_bar.setRange(0, cases_count)
        self.__progress_bar.setValue(0)
        self.__progress_bar.setVisible(True)

        # Update run/cancel buttons
        self.__cancel_button.setVisible(True)
        self.__run_button.setVisible(False)

        # Start running tests
        self.__model.run_tests(
            suite_list=self.__model.test_suite_list if selected_tab == 0 else self.__model.generate_suite_list,
            shuffle=self.__shuffle_check_box.isChecked(),
            break_on_failure=self.__break_on_failure_check_box.isChecked(),
            after_clear=self.__clear_scene_after_tests_check_box.isChecked(),
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
        for test_suite_data in self.__model.test_suite_list:
            if warning_text := test_suite_data.warning_log_text:
                log(warning_text)
            if failure_text := test_suite_data.failure_log_text:
                log(failure_text)

        # Reset progress bar
        self.__progress_bar.setValue(cases_count)
        self.__progress_bar.setVisible(False)

        # Remove connections
        self.__model.test_case_finished.disconnect(self.__on_test_case_finished)

        # Re-enable widgets
        self.__set_all_tree_widget_item_enable(True)
        self.__cancel_button.setVisible(False)
        self.__cancel_button.setEnabled(False)
        self.__run_button.setEnabled(True)
        self.__run_button.setVisible(True)
        self.__select_all_items_button.setEnabled(True)
        self.__unselect_all_items_button.setEnabled(True)

    def __on_cancel_button_clicked(self, state):
        if not self.__model.is_running:
            return

        self.__cancel_button.setEnabled(False)
        self.__cancel_button.setText("Cancelling...")
        self.__model.tests_cancelled.connect(self.__on_test_cancelled)
        self.__model.cancel()

    def __on_test_cancelled(self):
        self.__cancel_button.setVisible(False)
        self.__cancel_button.setEnabled(False)
        self.__cancel_button.setText("Cancel")
        self.__run_button.setEnabled(True)
        self.__run_button.setVisible(True)
        self.__model.tests_cancelled.disconnect()

    def __on_test_case_finished(self, test_suite_data, test_case_data):
        self.__progress_bar.setValue(self.__progress_bar.value + 1)

    def __on_tree_widget_item_clicked(self, item, column):
        item_check_state = item.checkState(0)

        test_item = None
        for test_suite_widget in self.__test_suite_widget_list + self.__generate_suite_widget_list:
            if test_suite_widget == item:
                test_item = test_suite_widget
                break
            for test_case_widget in test_suite_widget.test_case_data_widget_list:
                if test_case_widget == item:
                    test_item = test_case_widget
                    break

        if test_item is None:
            raise RuntimeError("Selected item data wasn't found in current state. Please restart the application.")

        if isinstance(test_item, TestSuiteDataWidgetItem):
            test_item.test_suite_data.enabled = True if item_check_state == qt.Qt.Checked else False
        else:
            test_item.test_case_data.enabled = True if item_check_state == qt.Qt.Checked else False
