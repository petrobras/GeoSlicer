import ctk
import os
import qt
import slicer

from ltrace.slicer import ui
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from pathlib import Path

try:
    from Test.WidgetTrackingTest import WidgetTrackingTest
except ImportError:
    WidgetTrackingTest = None  # tests not deployed to final version or closed source


class WidgetTracking(LTracePlugin):
    SETTING_KEY = "WidgetTracking"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Widget Tracking"
        self.parent.categories = ["Tools"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = WidgetTracking.help()
        self.parent.hidden = True

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class WidgetTrackingWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def buttonsWidget(self) -> qt.QWidget:
        mainWidget = qt.QWidget()
        mainLayout = qt.QVBoxLayout()
        mainWidget.setLayout(mainLayout)

        # Button
        self._button1 = qt.QPushButton("Button 1")
        self._button2 = qt.QPushButton("Button")
        self._button2.objectName = "Button Object Name"
        self._button3 = qt.QToolButton(mainWidget)
        self._button3.setText("Tool Button Text")
        self._button3.objectName = "Tool Button Object Name"

        self._collapsibleButton = ctk.ctkCollapsibleButton()
        self._collapsibleButton.collapsed = False
        self._collapsibleButton.text = "Collapsible"
        self._collapsibleButton.objectName = "Collapsible Object Name"

        parametersLayout = qt.QFormLayout(self._collapsibleButton)
        parametersLayout.addRow("A Label:", qt.QLabel("Other Label"))

        mainLayout.addWidget(self._button1)
        mainLayout.addWidget(self._button2)
        mainLayout.addWidget(self._button3)
        mainLayout.addWidget(self._collapsibleButton)

        return mainWidget

    def spinBoxesWidget(self) -> qt.QWidget:
        mainWidget = qt.QWidget()
        mainLayout = qt.QVBoxLayout()
        mainWidget.setLayout(mainLayout)

        # Button
        self._spinBox = qt.QSpinBox()
        self._spinBox2 = qt.QSpinBox()
        self._doubleSpinBox = qt.QDoubleSpinBox()
        self._doubleSpinBox2 = qt.QDoubleSpinBox()

        self._spinBox.objectName = "SpinBox Object Name"
        self._doubleSpinBox.objectName = "Double SpinBox Object Name"

        # with buddy
        formLayout = qt.QFormLayout()
        formLayout.addRow("SpinBox Label", self._spinBox2)

        # label beside the widget but not buddy
        hLayout = qt.QHBoxLayout()
        hLayout.addWidget(qt.QLabel("Double SpinBox Label"))
        hLayout.addWidget(self._doubleSpinBox2)

        mainLayout.addWidget(self._spinBox)
        mainLayout.addWidget(self._doubleSpinBox)
        mainLayout.addLayout(formLayout)
        mainLayout.addLayout(hLayout)

        return mainWidget

    def checkBoxesWidget(self) -> qt.QWidget:
        mainWidget = qt.QWidget()
        mainLayout = qt.QVBoxLayout()
        mainWidget.setLayout(mainLayout)

        # Check Boxes
        self._checkBoxChecked = qt.QCheckBox("Checked Box")
        self._checkBoxChecked.setCheckState(qt.Qt.Checked)
        self._checkBoxUnchecked = qt.QCheckBox("Unchecked Box")
        self._checkBoxUnchecked.setCheckState(qt.Qt.Unchecked)
        self._checkBoxUnlabeled = qt.QCheckBox()
        self._checkBoxUnlabeled2 = qt.QCheckBox()

        hLayout = qt.QHBoxLayout()
        hLayout.addWidget(qt.QLabel("Unlabeled Check Box Label"))
        hLayout.addWidget(self._checkBoxUnlabeled)

        formLayout = qt.QFormLayout()
        formLayout.addRow("Unlabeled Check Box Buddy Label", self._checkBoxUnlabeled2)

        # Radio Boxes
        self._radioButton1 = qt.QRadioButton("Radio Button 1")
        self._radioButton1.setChecked(True)
        self._radioButton2 = qt.QRadioButton("Radio Button 2")
        self._radioButton2.setChecked(False)

        hLayout2 = qt.QHBoxLayout()
        hLayout2.addWidget(self._radioButton1)
        hLayout2.addWidget(self._radioButton2)

        mainLayout.addWidget(self._checkBoxChecked)
        mainLayout.addWidget(self._checkBoxUnchecked)
        mainLayout.addLayout(hLayout)
        mainLayout.addLayout(formLayout)
        mainLayout.addLayout(hLayout2)

        return mainWidget

    def lineEditsWidget(self) -> qt.QWidget:
        mainWidget = qt.QWidget()
        mainLayout = qt.QVBoxLayout()
        mainWidget.setLayout(mainLayout)

        # Button
        self._lineEdit1 = qt.QLineEdit("Line Edit 1 Text")
        self._lineEdit1.objectName = "Line Edit 1 Object Name"
        self._lineEdit2 = qt.QLineEdit("Line Edit 2 Text")
        self._lineEdit3 = qt.QLineEdit("Line Edit 3 Text")

        # with buddy
        formLayout = qt.QFormLayout()
        formLayout.addRow("Line Edit 2 Buddy Label", self._lineEdit2)

        # label beside the widget but not buddy
        hLayout = qt.QHBoxLayout()
        hLayout.addWidget(qt.QLabel("Line Edit 3 Label"))
        hLayout.addWidget(self._lineEdit3)

        mainLayout.addWidget(self._lineEdit1)
        mainLayout.addLayout(formLayout)
        mainLayout.addLayout(hLayout)

        return mainWidget

    def comboBoxesWidget(self) -> qt.QWidget:
        mainWidget = qt.QWidget()
        mainLayout = qt.QVBoxLayout()
        mainWidget.setLayout(mainLayout)

        # Button
        self._comboBox1 = qt.QComboBox()
        self._comboBox1.objectName = "Combo Box 1 Object Name"
        self._comboBox2 = qt.QComboBox()
        self._comboBox3 = qt.QComboBox()

        for comboBox in [self._comboBox1, self._comboBox2, self._comboBox3]:
            comboBox.addItems(["Item1", "Item2"])

        # with buddy
        formLayout = qt.QFormLayout()
        formLayout.addRow("Combo Box 2 Buddy Label", self._comboBox2)

        self._hierarchyComboBox = ui.hierarchyVolumeInput(
            hasNone=True,
        )
        self._hierarchyComboBox.objectName = "Hierarchy Combo Box Object Name"

        # label beside the widget but not buddy
        hLayout = qt.QHBoxLayout()
        hLayout.addWidget(qt.QLabel("Combo Box 3 Label"))
        hLayout.addWidget(self._comboBox3)

        mainLayout.addWidget(self._comboBox1)
        mainLayout.addLayout(formLayout)
        mainLayout.addLayout(hLayout)
        mainLayout.addWidget(self._hierarchyComboBox)

        return mainWidget

    def listsWidget(self) -> qt.QWidget:
        mainWidget = qt.QWidget()
        mainLayout = qt.QVBoxLayout()
        mainWidget.setLayout(mainLayout)

        # List with object name
        self._listWidget1 = qt.QListWidget()
        self._listWidget1.objectName = "List Widget 1 Object Name"

        # Lists with buddy label
        self._listWidget2 = qt.QListWidget()
        formLayout = qt.QFormLayout()
        formLayout.addRow("List Widget 2 Buddy Label", self._listWidget2)

        # Lists with not-buddy label
        self._listWidget3 = qt.QListWidget()

        # Add items to the lists
        for idx, listWidget in enumerate([self._listWidget1, self._listWidget2, self._listWidget3]):
            listWidgetItem1 = qt.QListWidgetItem(f"List Widget {idx+1} Item 1")
            listWidgetItem2 = qt.QListWidgetItem(f"List Widget {idx+1} Item 2")
            listWidgetItem2.setFlags(listWidgetItem2.flags() | qt.Qt.ItemIsUserCheckable | qt.Qt.ItemIsSelectable)
            listWidgetItem2.setCheckState(qt.Qt.Unchecked)
            listWidget.addItem(listWidgetItem1)
            listWidget.addItem(listWidgetItem2)

        hLayout = qt.QHBoxLayout()
        hLayout.addWidget(qt.QLabel("List Widget 2 Label"))
        hLayout.addWidget(self._listWidget3)

        mainLayout.addWidget(self._listWidget1)
        mainLayout.addLayout(formLayout)
        mainLayout.addLayout(hLayout)

        return mainWidget

    def tablesWidget(self) -> qt.QWidget:
        mainWidget = qt.QWidget()
        mainLayout = qt.QVBoxLayout()
        mainWidget.setLayout(mainLayout)

        # List with object name
        self._tableWidget1 = qt.QTableWidget()
        self._tableWidget1.objectName = "Table Widget 1 Object Name"
        self._tableWidget1.setColumnCount(2)
        self._tableWidget1.setHorizontalHeaderLabels(["Column 1", "Column 2"])

        # Lists with buddy label
        self._tableWidget2 = qt.QTableWidget()
        self._tableWidget2.setRowCount(1)
        self._tableWidget2.setColumnCount(2)
        self._tableWidget2.setVerticalHeaderLabels(["Row 1", "Row 2"])
        formLayout = qt.QFormLayout()
        formLayout.addRow("Table Widget 2 Buddy Label", self._tableWidget2)

        # Lists with not-buddy label
        self._tableWidget3 = qt.QTableWidget()
        self._tableWidget3.setColumnCount(2)

        # Add items to the lists
        for idx, tableWidget in enumerate([self._tableWidget1, self._tableWidget2, self._tableWidget3]):
            tableWidgetItem1 = qt.QTableWidgetItem(f"Table Widget {idx+1} Item 1")
            tableWidgetItem2 = qt.QTableWidgetItem(f"Table Widget {idx+1} Item 2")

            tableWidget.setRowCount(1)
            tableWidget.setItem(0, 0, tableWidgetItem1)
            tableWidget.setItem(0, 1, tableWidgetItem2)

        hLayout = qt.QHBoxLayout()
        hLayout.addWidget(qt.QLabel("Table Widget 2 Label"))
        hLayout.addWidget(self._tableWidget3)

        mainLayout.addWidget(self._tableWidget1)
        mainLayout.addLayout(formLayout)
        mainLayout.addLayout(hLayout)

        return mainWidget

    def slidersWidget(self) -> qt.QWidget:
        mainWidget = qt.QWidget()
        mainLayout = qt.QFormLayout()
        mainWidget.setLayout(mainLayout)

        rangeWidget = ctk.ctkRangeWidget()
        rangeWidget.objectName = "CTK Range Widget"

        windowLevelWidget = slicer.qMRMLWindowLevelWidget()
        windowLevelWidget.objectName = "Window Level Widget"

        mainLayout.addRow("Window Level:", windowLevelWidget)
        mainLayout.addRow("Range:", rangeWidget)

        return mainWidget

    def setup(self):
        LTracePluginWidget.setup(self)

        self.buttonsWidgetTab = self.buttonsWidget()
        self.buttonsWidgetTab.objectName = "Buttons Tab"

        self.spinBoxesWidgetTab = self.spinBoxesWidget()
        self.spinBoxesWidgetTab.objectName = "SpinBoxes Tab"

        self.checkBoxesWidgetTab = self.checkBoxesWidget()
        self.checkBoxesWidgetTab.objectName = "CheckBoxes Tab"

        self.lineEditWidgetTab = self.lineEditsWidget()
        self.lineEditWidgetTab.objectName = "LineEdits Tab"

        self.comboBoxesWidgetTab = self.comboBoxesWidget()
        self.comboBoxesWidgetTab.objectName = "ComboBoxes Tab"

        self.listsWidgetTab = self.listsWidget()
        self.listsWidgetTab.objectName = "Lists Tab"

        self.tablesWidgetTab = self.tablesWidget()
        self.tablesWidgetTab.objectName = "Tables Tab"

        self.slidersWidgetTab = self.slidersWidget()
        self.slidersWidgetTab.objectName = "Sliders Tab"

        self.mainTab = qt.QTabWidget()
        self.mainTab.objectName = "Main Tab"
        self.mainTab.addTab(self.buttonsWidgetTab, "Buttons")
        self.mainTab.addTab(self.spinBoxesWidgetTab, "SpinBoxes")
        self.mainTab.addTab(self.checkBoxesWidgetTab, "CheckBoxes")
        self.mainTab.addTab(self.lineEditWidgetTab, "LineEdits")
        self.mainTab.addTab(self.comboBoxesWidgetTab, "ComboBoxes")
        self.mainTab.addTab(self.listsWidgetTab, "Lists")
        self.mainTab.addTab(self.tablesWidgetTab, "Tables")
        self.mainTab.addTab(self.slidersWidgetTab, "Sliders")

        # Update layout
        self.layout.addWidget(self.mainTab)
        self.layout.addStretch(1)
