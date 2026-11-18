import tempfile
import shutil
import logging
import slicer
import qt
import numpy as np

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import wait
from pathlib import Path
from typing import List


def readLog(linesWithText: Path) -> List[str]:
    with open(linesWithText, "r", encoding="utf-8") as log_file:
        return log_file.readlines()


class WidgetTrackingTest(LTracePluginTest):
    def pre_setup(self) -> None:
        # Create the temporary directory used to store the test files
        self.__tempProjectDirPath = Path(tempfile.mkdtemp()).resolve()
        self.__tempLogFilePath = self.__tempProjectDirPath / "tracking.log"

        # Add temporary file handler to the tracking logger
        self.__logger = logging.getLogger("tracking")
        self.__fileHandler = logging.FileHandler(self.__tempLogFilePath, mode="a")
        self.__logger.addHandler(self.__fileHandler)

    def _click(self, widget=None, objectName=None, position: qt.QPoint = None, relativePosition: bool = False):
        if not widget and not objectName:
            raise ValueError("widget and objectName cannot be None at the same time")

        if not widget:
            widget = self.find_widget(objectName)
            assert widget is not None
            assert widget.text == objectName or widget.objectName == objectName

        if position is None:
            centerPos = widget.geometry.center()
            centerPosF = qt.QPointF(centerPos)
            centerGlobalPosF = qt.QPointF(self._module_widget.parent.mapToGlobal(centerPos))
        else:
            if relativePosition:
                centerPosF = centerGlobalPosF = qt.QPointF(position)
            else:
                centerPosF = qt.QPointF(position)
                centerGlobalPosF = qt.QPointF(self._module_widget.parent.mapToGlobal(position))

        # Move
        event = qt.QMouseEvent(
            qt.QEvent.MouseMove, centerPosF, centerGlobalPosF, qt.Qt.NoButton, qt.Qt.NoButton, qt.Qt.NoModifier
        )
        slicer.app.sendEvent(widget, event)

        # Press
        event = qt.QMouseEvent(
            qt.QEvent.MouseButtonPress,
            centerPosF,
            centerGlobalPosF,
            qt.Qt.LeftButton,
            qt.Qt.LeftButton,
            qt.Qt.NoModifier,
        )
        slicer.app.sendEvent(widget, event)

        # Release
        event = qt.QMouseEvent(
            qt.QEvent.MouseButtonRelease,
            centerPosF,
            centerGlobalPosF,
            qt.Qt.LeftButton,
            qt.Qt.LeftButton,
            qt.Qt.NoModifier,
        )
        slicer.app.sendEvent(widget, event)
        wait(0.1)

    def simulateMouseWheel(
        self, widget=None, delta: int = 200, position: qt.QPoint = None, relativePosition: bool = False
    ) -> None:
        centerPosF = centerGlobalPosF = qt.QPointF(0, 0)
        if not widget:
            raise ValueError("Invalid widget")

        if position is None:
            centerPos = widget.geometry.center()
            centerPosF = qt.QPointF(centerPos)
            centerGlobalPosF = qt.QPointF(self._module_widget.parent.mapToGlobal(centerPos))
        else:
            if relativePosition:
                centerPosF = centerGlobalPosF = qt.QPointF(position)
            else:
                centerPosF = qt.QPointF(position)
                centerGlobalPosF = qt.QPointF(self._module_widget.parent.mapToGlobal(position))

        # Move
        event = qt.QMouseEvent(
            qt.QEvent.MouseMove, centerPosF, centerGlobalPosF, qt.Qt.NoButton, qt.Qt.NoButton, qt.Qt.NoModifier
        )
        slicer.app.sendEvent(widget, event)

        wait(0.1)

        event = qt.QWheelEvent(centerPosF, centerGlobalPosF, delta, qt.Qt.NoModifier, qt.Qt.NoModifier, qt.Qt.Vertical)
        # Wheel
        slicer.app.sendEvent(widget, event)

        wait(0.1)

    def _checkLogOccurrences(self, text, logLines):
        lines_with_text = [line for line in logLines if text.lower() in line.lower()]
        return len(lines_with_text) > 0

    def post_setup(self) -> None:
        self._widgets = {
            "main_tab": self.find_widget("Main Tab"),
            "buttons_tab": self.find_widget("Buttons Tab"),
            "spinboxes_tab": self.find_widget("SpinBoxes Tab"),
            "checkboxes_tab": self.find_widget("CheckBoxes Tab"),
            "linedits_tab": self.find_widget("LineEdits Tab"),
            "comboboxes_tab": self.find_widget("ComboBoxes Tab"),
            "lists_tab": self.find_widget("Lists Tab"),
            "tables_tab": self.find_widget("Tables Tab"),
            "sliders_tab": self.find_widget("Sliders Tab"),
        }

        for widget in self._widgets:
            assert widget is not None, f"Failed to find widget: {widget}"

        self._tabPosition = {}
        mainTab = self._widgets["main_tab"]
        tabBar = mainTab.tabBar()
        for idx in range(mainTab.count):
            tab = mainTab.widget(idx)
            tabRect = tabBar.tabRect(idx)
            relativePos = qt.QPoint(tabRect.x(), tabRect.y())
            self._tabPosition[tab.name] = relativePos

    def tear_down(self) -> None:
        # Remove temporary file handler to the tracking logger
        self.__fileHandler.close()
        self.__logger.removeHandler(self.__fileHandler)

        # Remove the temporary directory used to store the test files
        if self.__tempProjectDirPath.exists():
            shutil.rmtree(self.__tempProjectDirPath)

    def test_button_tracking(self) -> None:
        # Select buttons tab
        mainTab = self._widgets["main_tab"]
        buttonsTab = self._widgets["buttons_tab"]

        mainTab.setCurrentWidget(buttonsTab)

        assert mainTab.tabText(mainTab.currentIndex) == "Buttons", (
            f"Selected tab: {mainTab.tabText(mainTab.currentIndex)}"
        )

        # Click on buttons
        self._click(objectName="Button 1")
        self._click(objectName="Button Object Name")
        self._click(objectName="Tool Button Object Name")
        self._click(objectName="Collapsible Object Name")

        # Read log
        logLines = readLog(self.__tempLogFilePath)

        # Assert log occurrences
        assert self._checkLogOccurrences("Button clicked: {'name': 'Button 1', 'isChecked': False}", logLines), (
            f"This log message is missing. Logs:\n{logLines}"
        )
        assert self._checkLogOccurrences(
            "Button clicked: {'name': 'Button Object Name', 'isChecked': False}", logLines
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "Button clicked: {'name': 'Tool Button Object Name', 'isChecked': False", logLines
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "Collapsible button clicked: {'name': 'Collapsible Object Name', 'collapsed': False}", logLines
        ), f"This log message is missing. Logs:\n{logLines}"
        assert len(logLines) == 5, f"Expected 5 log lines, got {len(logLines)}. Log:\n{logLines}"

    def test_spin_boxes_tracking(self) -> None:
        # Select SpinBoxes tab
        mainTab = self._widgets["main_tab"]
        spinBoxesTab = self._widgets["spinboxes_tab"]

        mainTab.setCurrentWidget(spinBoxesTab)
        assert mainTab.tabText(mainTab.currentIndex) == "SpinBoxes", (
            f"Selected tab: {mainTab.tabText(mainTab.currentIndex)}"
        )

        # Click on spin boxes
        self._click(objectName="SpinBox Object Name")
        self._click(objectName="Double SpinBox Object Name")
        self._click(widget=self._module_widget._spinBox2)
        self._click(widget=self._module_widget._doubleSpinBox2)

        # Read log
        logLines = readLog(self.__tempLogFilePath)

        # Assert log occurrences
        assert self._checkLogOccurrences("Spin box clicked: {'name': 'SpinBox Object Name', 'value': 0}", logLines), (
            f"This log message is missing. Logs:\n{logLines}"
        )
        assert self._checkLogOccurrences(
            "Spin box clicked: {'name': 'Double SpinBox Object Name', 'value': 0.0}", logLines
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences("Spin box clicked: {'name': 'SpinBox Label', 'value': 0}", logLines), (
            f"This log message is missing. Logs:\n{logLines}"
        )
        assert self._checkLogOccurrences(
            "Spin box clicked: {'name': 'Double SpinBox Label', 'value': 0.0}", logLines
        ), f"This log message is missing. Logs:\n{logLines}"
        assert len(logLines) == 5, f"Expected 5 log lines, got {len(logLines)}. Log:\n{logLines}"

    def test_tab_tracking(self) -> None:
        mainTab = self._widgets["main_tab"].tabBar()  # use QTabBar instead because it handles the mouse events
        # Click on the tabs
        tabSpinboxesPos = self._tabPosition["SpinBoxes Tab"]
        self._click(widget=mainTab, position=tabSpinboxesPos, relativePosition=True)

        tabButtonsPos = self._tabPosition["Buttons Tab"]
        self._click(widget=mainTab, position=tabButtonsPos, relativePosition=True)

        # Read log
        logLines = readLog(self.__tempLogFilePath)

        # Assert log occurrences
        assert self._checkLogOccurrences("Tab clicked: {'text': 'Buttons'}", logLines), (
            f"This log message is missing. Logs:\n{logLines}"
        )
        assert self._checkLogOccurrences("Tab clicked: {'text': 'SpinBoxes'}", logLines), (
            f"This log message is missing. Logs:\n{logLines}"
        )
        assert len(logLines) == 3, f"Expected 3 log lines, got {len(logLines)}. Log:\n{logLines}"

    def test_check_boxes_tracking(self) -> None:
        # Select CheckBoxes tab
        mainTab = self._widgets["main_tab"]
        spinBoxesTab = self._widgets["checkboxes_tab"]

        mainTab.setCurrentWidget(spinBoxesTab)
        assert mainTab.tabText(mainTab.currentIndex) == "CheckBoxes", (
            f"Selected tab: {mainTab.tabText(mainTab.currentIndex)}"
        )

        # Click on the buttons
        self._click(
            objectName="Checked Box", position=qt.QPoint(2, 2), relativePosition=True
        )  # Now it will be unchecked
        self._click(
            objectName="Unchecked Box", position=qt.QPoint(2, 2), relativePosition=True
        )  # Now it will be checked
        self._click(widget=self._module_widget._checkBoxUnlabeled, position=qt.QPoint(2, 2), relativePosition=True)
        self._click(widget=self._module_widget._checkBoxUnlabeled2, position=qt.QPoint(2, 2), relativePosition=True)
        self._click(
            objectName="Radio Button 2", position=qt.QPoint(2, 2), relativePosition=True
        )  # Select radio button 2 and unselect radio button 1
        wait(0.1)
        self._click(
            objectName="Radio Button 1", position=qt.QPoint(2, 2), relativePosition=True
        )  # Select radio button 1 and unselect radio button 2

        wait(0.1)

        # Read log
        logLines = readLog(self.__tempLogFilePath)

        # Assert log occurrences
        assert self._checkLogOccurrences("Check box toggled: {'name': 'Checked Box', 'checked': False}", logLines), (
            f"This log message is missing. Logs:\n{logLines}"
        )
        assert self._checkLogOccurrences("Check box toggled: {'name': 'Unchecked Box', 'checked': True}", logLines), (
            f"This log message is missing. Logs:\n{logLines}"
        )
        assert self._checkLogOccurrences(
            "Check box toggled: {'name': 'Unlabeled Check Box Label', 'checked': True}", logLines
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "Check box toggled: {'name': 'Unlabeled Check Box Buddy Label', 'checked': True}", logLines
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences("Check box toggled: {'name': 'Radio Button 2', 'checked': True}", logLines), (
            f"This log message is missing. Logs:\n{logLines}"
        )
        assert self._checkLogOccurrences("Check box toggled: {'name': 'Radio Button 1', 'checked': True}", logLines), (
            f"This log message is missing. Logs:\n{logLines}"
        )
        assert len(logLines) == 7, f"Expected 3 log lines, got {len(logLines)}. Log:\n{logLines}"

    def test_line_edits_tracking(self) -> None:
        # Select LineEdits tab
        mainTab = self._widgets["main_tab"]
        lineEditsTab = self._widgets["linedits_tab"]

        mainTab.setCurrentWidget(lineEditsTab)
        assert mainTab.tabText(mainTab.currentIndex) == "LineEdits", (
            f"Selected tab: {mainTab.tabText(mainTab.currentIndex)}"
        )

        # Get widgets
        lineEdit1 = self.find_widget("Line Edit 1 Object Name")
        assert lineEdit1 is not None, "Line edit 1 not found"

        lineEdit2 = self.find_widget("Line Edit 2 Buddy Label")
        assert lineEdit2 is not None, "Line edit 2 not found"

        lineEdit3 = self.find_widget("Line Edit 3 Label")
        assert lineEdit3 is not None, "Line edit 3 not found"

        # Click on the line edits
        for widget in [lineEdit1, lineEdit2, lineEdit3]:
            self._click(widget=widget)
            widget.editingFinished.emit()

        # Change line edit 3 text
        self._click(widget=lineEdit3)
        lineEdit3.setText("New Line Edit 3 Text")
        lineEdit3.editingFinished.emit()

        # Read log
        logLines = readLog(self.__tempLogFilePath)

        # Assert log occurrences
        assert self._checkLogOccurrences(
            "Line edit changed: {'name': 'Line Edit 1 Object Name', 'text': 'Line Edit 1 Text'}", logLines
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "Line edit changed: {'name': 'Line Edit 2 Buddy Label', 'text': 'Line Edit 2 Text'}", logLines
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "Line edit changed: {'name': 'Line Edit 3 Label', 'text': 'Line Edit 3 Text'}", logLines
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "Line edit changed: {'name': 'Line Edit 3 Label', 'text': 'New Line Edit 3 Text'}", logLines
        ), f"This log message is missing. Logs:\n{logLines}"
        assert len(logLines) == 5, f"Expected 6 log lines, got {len(logLines)}. Log:\n{logLines}"

    def test_combo_boxes_tracking(self) -> None:
        # Select ComboBoxes tab
        mainTab = self._widgets["main_tab"]
        comboBoxesTab = self._widgets["comboboxes_tab"]

        mainTab.setCurrentWidget(comboBoxesTab)
        assert mainTab.tabText(mainTab.currentIndex) == "ComboBoxes", (
            f"Selected tab: {mainTab.tabText(mainTab.currentIndex)}"
        )

        # Get widgets
        comboBox1 = self._module_widget._comboBox1
        comboBox2 = self._module_widget._comboBox2
        comboBox3 = self._module_widget._comboBox3
        hierarchyComboBox = self._module_widget._hierarchyComboBox
        treeView = hierarchyComboBox.findChild("qMRMLSubjectHierarchyTreeView")

        # Click on the combo boxes to trigger tracking event and change the selected item
        for widget in [comboBox1, comboBox2, comboBox3]:
            self._click(widget=widget)
            widget.setCurrentIndex(1)  # Item 2

        # Create node for hierarchy combo box
        node = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLLabelMapVolumeNode.__name__, "TestNode")

        # Simulate click in hierarchy combobox viewport
        # First should be 'None' and the second onde should be related to the node
        hierarchyComboBox.setCurrentNode(None)
        wait(0.2)
        index1 = treeView.indexAt(qt.QPoint(10, 10))

        item1Rect = treeView.visualRect(index1)
        item1Pos = item1Rect.topLeft()
        self._click(widget=treeView.viewport(), position=item1Pos, relativePosition=True)
        wait(0.2)

        index2 = treeView.indexBelow(index1)
        item2Rect = treeView.visualRect(index2)
        item2Pos = item2Rect.topLeft()
        self._click(widget=treeView.viewport(), position=item2Pos, relativePosition=True)

        hierarchyComboBox.setCurrentNode(node)

        wait(0.2)

        # Read log
        logLines = readLog(self.__tempLogFilePath)

        currentNode = hierarchyComboBox.currentNode()
        assert hierarchyComboBox.currentNode() == node, (
            f"logLines {logLines}\nhierarchyComboBox current node is {currentNode.GetName() if currentNode is not None else 'None'}"
        )

        # Assert log occurrences
        assert self._checkLogOccurrences(
            "Combo box changed: {'name': 'Combo Box 1 Object Name', 'text': 'Item2'}", logLines
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "Combo box changed: {'name': 'Combo Box 2 Buddy Label', 'text': 'Item2'}", logLines
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "Combo box changed: {'name': 'Combo Box 3 Label', 'text': 'Item2'}", logLines
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            f"'name': 'Hierarchy Combo Box Object Name', 'selectedNodeName': '{node.GetName()}', 'selectedNodeId': '{node.GetID()}'",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"
        assert len(logLines) == 6, f"Expected 6 log lines, got {len(logLines)}. Log:\n{logLines}"

    def test_lists_tracking(self) -> None:
        # Select Lists tab
        mainTab = self._widgets["main_tab"]
        listsTab = self._widgets["lists_tab"]

        mainTab.setCurrentWidget(listsTab)
        assert mainTab.tabText(mainTab.currentIndex) == "Lists", (
            f"Selected tab: {mainTab.tabText(mainTab.currentIndex)}"
        )

        # Get widgets
        listWidget1 = self._module_widget._listWidget1
        listWidget2 = self._module_widget._listWidget2
        listWidget3 = self._module_widget._listWidget3

        # Click on the list widgets items
        for listWidget in [listWidget1, listWidget2, listWidget3]:
            # Click item #1'
            item1 = listWidget.item(0)
            item1Rect = listWidget.visualItemRect(item1)
            item1Pos = listWidget.viewport().mapToParent(item1Rect.center())
            self._click(widget=listWidget.viewport(), position=item1Pos, relativePosition=True)

            # Select item #2 checkbox'
            item2 = listWidget.item(1)
            item2Rect = listWidget.visualItemRect(item2)
            item2Pos = listWidget.viewport().mapToParent(item2Rect.topLeft() + qt.QPoint(5, 0))
            self._click(widget=listWidget.viewport(), position=item2Pos, relativePosition=True)

        # Read log
        logLines = readLog(self.__tempLogFilePath)

        # Assert log occurrences
        assert self._checkLogOccurrences(
            "List Item clicked: {'name': 'List Widget 1 Object Name', 'itemText': 'List Widget 1 Item 1', 'checked': False, 'selected': True}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "List Item clicked: {'name': 'List Widget 1 Object Name', 'itemText': 'List Widget 1 Item 2', 'checked': True, 'selected': False}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "List Item clicked: {'name': 'List Widget 2 Buddy Label', 'itemText': 'List Widget 2 Item 1', 'checked': False, 'selected': True}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "List Item clicked: {'name': 'List Widget 2 Buddy Label', 'itemText': 'List Widget 2 Item 2', 'checked': True, 'selected': False}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "List Item clicked: {'name': 'List Widget 2 Label', 'itemText': 'List Widget 3 Item 1', 'checked': False, 'selected': True}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "List Item clicked: {'name': 'List Widget 2 Label', 'itemText': 'List Widget 3 Item 2', 'checked': True, 'selected': False}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"
        assert len(logLines) == 7, f"Expected 7 log lines, got {len(logLines)}. Log:\n{logLines}"

    def test_tables_tracking(self) -> None:
        # Select Tables tab
        mainTab = self._widgets["main_tab"]
        tablesTab = self._widgets["tables_tab"]

        mainTab.setCurrentWidget(tablesTab)
        assert mainTab.tabText(mainTab.currentIndex) == "Tables", (
            f"Selected tab: {mainTab.tabText(mainTab.currentIndex)}"
        )

        # Get widgets
        tableWidget1 = self._module_widget._tableWidget1
        tableWidget2 = self._module_widget._tableWidget2
        tableWidget3 = self._module_widget._tableWidget3

        # Click on the table cells
        for tableWidget in [tableWidget1, tableWidget2, tableWidget3]:
            # Select column #1
            item1 = tableWidget.item(0, 0)
            item1Rect = tableWidget.visualItemRect(item1)
            item1Pos = tableWidget.viewport().mapToParent(item1Rect.topLeft())

            # Click column #1
            self._click(widget=tableWidget.viewport(), position=item1Pos, relativePosition=True)

            # Select column #2
            item2 = tableWidget.item(0, 1)
            item2Rect = tableWidget.visualItemRect(item2)
            item2Pos = tableWidget.viewport().mapToParent(item2Rect.topLeft())

            # Click column #2
            self._click(widget=tableWidget.viewport(), position=item2Pos, relativePosition=True)

        # Read log
        logLines = readLog(self.__tempLogFilePath)

        # Assert log occurrences
        assert self._checkLogOccurrences(
            "Table cell clicked: {'name': 'Table Widget 1 Object Name', 'itemText': 'Table Widget 1 Item 1', 'row': 0, 'column': 'Column 1'}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "Table cell clicked: {'name': 'Table Widget 1 Object Name', 'itemText': 'Table Widget 1 Item 2', 'row': 0, 'column': 'Column 2'}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "Table cell clicked: {'name': 'Table Widget 2 Buddy Label', 'itemText': 'Table Widget 2 Item 1', 'row': 'Row 1', 'column': 0}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "Table cell clicked: {'name': 'Table Widget 2 Buddy Label', 'itemText': 'Table Widget 2 Item 2', 'row': 'Row 1', 'column': 1}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "Table cell clicked: {'name': 'Table Widget 2 Label', 'itemText': 'Table Widget 3 Item 1', 'row': 0, 'column': 0}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"
        assert self._checkLogOccurrences(
            "Table cell clicked: {'name': 'Table Widget 2 Label', 'itemText': 'Table Widget 3 Item 2', 'row': 0, 'column': 1}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"
        assert len(logLines) == 7, f"Expected 7 log lines, got {len(logLines)}. Log:\n{logLines}"

    def test_main_window_menu_tracking(self) -> None:
        def __searchAction(menu, text):
            for action in menu.actions():
                if action.text == text:
                    return action

            return None

        mainWindow = slicer.modules.AppContextInstance.mainWindow
        fileMenu = mainWindow.findChild("QMenu", "FileMenu")
        closeSceneAction = __searchAction(menu=fileMenu, text="Close Scene")
        assert closeSceneAction is not None

        actionGeometry = fileMenu.actionGeometry(closeSceneAction)
        actionPos = qt.QPoint(actionGeometry.x(), actionGeometry.y())

        self._click(widget=fileMenu, position=actionPos, relativePosition=True)

        # Read log
        logLines = readLog(self.__tempLogFilePath)

        # Assert log occurrences
        assert self._checkLogOccurrences("Menu action clicked: {'name': '&File'", logLines), (
            f"This log message is missing. Logs:\n{logLines}"
        )
        assert len(logLines) == 2, f"Expected 2 log lines, got {len(logLines)}. Log:\n{logLines}"

    def test_sliders_range_widget_tracking(self) -> None:
        # Select Tables tab
        mainTab = self._widgets["main_tab"]
        slidersTab = self._widgets["sliders_tab"]

        mainTab.setCurrentWidget(slidersTab)
        assert mainTab.tabText(mainTab.currentIndex) == "Sliders", (
            f"Selected tab: {mainTab.tabText(mainTab.currentIndex)}"
        )

        # Get widgets
        rangeWidget = self.find_widget("CTK Range Widget")

        assert rangeWidget is not None, "Widget 'CTK Range Widget' not found"

        # range widget children
        minimumSpinBox = self.find_widget("MinimumSpinBox", obj=rangeWidget)
        maximumSpinBox = self.find_widget("MaximumSpinBox", obj=rangeWidget)

        assert minimumSpinBox is not None, "Widget 'MinimumSpinBox' not found"
        assert maximumSpinBox is not None, "Widget 'MaximumSpinBox' not found"

        maximumSpinBoxPrivate = maximumSpinBox.children()[0]
        minimumSpinBoxPrivate = minimumSpinBox.children()[0]

        self.simulateMouseWheel(widget=maximumSpinBoxPrivate, delta=-1000)
        self.simulateMouseWheel(widget=minimumSpinBoxPrivate, delta=1000)

        wait(0.2)

        # Read log
        logLines = readLog(self.__tempLogFilePath)

        # Assert log occurrences
        assert self._checkLogOccurrences(
            "Range changed {'name': 'CTK Range Widget', 'minimumValue': 0.0, 'maximumValue': 91.0}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"

        assert self._checkLogOccurrences(
            "Range changed {'name': 'CTK Range Widget', 'minimumValue': 8.0, 'maximumValue': 91.0}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"

    def test_sliders_window_level_widget_tracking(self) -> None:
        # Select Tables tab
        mainTab = self._widgets["main_tab"]
        slidersTab = self._widgets["sliders_tab"]

        mainTab.setCurrentWidget(slidersTab)
        assert mainTab.tabText(mainTab.currentIndex) == "Sliders", (
            f"Selected tab: {mainTab.tabText(mainTab.currentIndex)}"
        )

        # Get widget
        windowLevelWidget = self.find_widget("Window Level Widget")

        assert windowLevelWidget is not None, "Widget 'Window Level Widget' not found"

        # window level widget children
        windowSpinBox = self.find_widget("WindowSpinBox", obj=windowLevelWidget)
        levelSpinBox = self.find_widget("LevelSpinBox", obj=windowLevelWidget)

        assert windowSpinBox is not None, "Widget 'WindowSpinBox' not found"
        assert levelSpinBox is not None, "Widget 'LevelSpinBox' not found"

        # Create dummy node to enable widgets to interact with
        node = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLScalarVolumeNode.__name__, "TestNode")
        array = np.random.randint(3, size=(16, 16, 16))
        slicer.util.updateVolumeFromArray(node, array.astype(np.int32))

        windowLevelWidget.setMRMLVolumeNode(node)
        slicer.util.setSliceViewerLayers(background=node, fit=True)

        # Get private reference from the ctk widgets
        windowSpinBoxPrivate = windowSpinBox.children()[0]
        levelSpinBoxPrivate = levelSpinBox.children()[0]

        self.simulateMouseWheel(widget=windowSpinBoxPrivate, delta=-1000)
        self.simulateMouseWheel(widget=levelSpinBoxPrivate, delta=1000)

        # Get min/max spin box references from sub menu
        menu = windowLevelWidget.findChild(qt.QMenu)
        assert menu is not None, "Menu from 'Window Level Widget' not found"

        toolButton = windowLevelWidget.findChild(qt.QToolButton)

        def action() -> None:
            # Couldn't find a qt event that actually update this value from the window level widget
            # that simulates the user changing the spin boxes.
            windowLevelWidget.setMinimumBound(0.3)
            windowLevelWidget.setMaximumBound(0.5)

            # Click in other widget to force the menu to close
            self._click(widget=menu)

        qt.QTimer.singleShot(1000, action)
        self._click(widget=menu)
        toolButton.click()

        wait(0.2)
        # Read log
        logLines = readLog(self.__tempLogFilePath)

        # Assert log occurrences
        assert self._checkLogOccurrences(
            "Window/Level value changed: {'name': 'Window Level Widget', 'minimumBound': -0.1, 'maximumBound': 1.1, 'window': 0.92, 'level': 0.5}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"

        assert self._checkLogOccurrences(
            "Window/Level value changed: {'name': 'Window Level Widget', 'minimumBound': -0.1, 'maximumBound': 1.1, 'window': 0.92, 'level': 0.58}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"

        assert self._checkLogOccurrences(
            "Window/Level value changed: {'name': 'Window Level Widget', 'minimumBound': 0.3, 'maximumBound': 0.5, 'window': 0.2, 'level': 0.4}",
            logLines,
        ), f"This log message is missing. Logs:\n{logLines}"
