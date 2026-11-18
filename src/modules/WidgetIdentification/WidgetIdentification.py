import os
from pathlib import Path

import ctk
import qt

from commons.slicer import ui, widgets
from commons.slicer_utils import LTracePlugin, LTracePluginWidget

try:
    from Test.WidgetIdentificationTest import WidgetIdentificationTest
except ImportError:
    WidgetIdentificationTest = None


class WidgetIdentification(LTracePlugin):
    SETTING_KEY = "WidgetIdentification"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "WidgetIdentification"
        self.parent.hidden = True
        self.parent.categories = ["Thin Section"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class WidgetIdentificationWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)

        widget = ctk.ctkCollapsibleButton()
        widget.text = "Test widgets"

        layout = qt.QFormLayout(widget)

        # radios in same row
        self.local_radio_button = qt.QRadioButton("Local")
        self.local_radio_button.objectName = "Local RadioButton"
        self.remote_radio_button = qt.QRadioButton("Remote")
        self.remote_radio_button.objectName = "Remote RadioButton"
        hbox = qt.QHBoxLayout(widget)
        hbox.addWidget(self.local_radio_button)
        hbox.addWidget(self.remote_radio_button)
        layout.addRow(hbox)

        # hierarchyVolumeInput
        self.hierarchy_volume_input = ui.hierarchyVolumeInput()
        self.hierarchy_volume_input.objectName = "Hierarchy Volume Input"
        layout.addRow("Hierarchy 1", self.hierarchy_volume_input)

        # SingleShot
        self.single_shot = widgets.SingleShotInputWidget(
            rowTitles={"main": "Annotations", "soi": "Region (SOI)", "reference": "Volume (PX)"},
            checkable=False,
            setDefaultMargins=False,
        )
        self.single_shot.segmentsContainerWidget.visible = False
        self.single_shot.mainInput.objectName = "Main ComboBox"
        self.single_shot.soiInput.objectName = "SOI ComboBox"
        self.single_shot.referenceInput.objectName = "Reference ComboBox"
        self.single_shot.mainInput.setCurrentNode(None)
        self.single_shot.soiInput.enabled = True
        self.single_shot.referenceInput.enabled = True
        layout.addWidget(self.single_shot)

        # combobox
        self.combo1 = qt.QComboBox()
        self.combo1.objectName = "First ComboBox"
        layout.addRow("Combo 1", self.combo1)

        # lineedit
        self.lineedit1 = qt.QLineEdit()
        self.lineedit1.objectName = "First LineEdit"
        layout.addRow("Line Edit 1", self.lineedit1)

        # pushbutton
        self.pushbutton1 = qt.QPushButton("Botão")
        self.pushbutton1.objectName = "First PushButton"
        layout.addWidget(self.pushbutton1)

        # spinbox
        self.spinbox1 = qt.QSpinBox()
        self.spinbox1.objectName = "First SpinBox"
        layout.addRow("Spin Box 1", self.spinbox1)

        # slider
        self.slider1 = qt.QSlider()
        self.slider1.objectName = "First Slider"
        layout.addRow("Slider 1", self.slider1)

        # without objectName
        self.combo2 = qt.QComboBox()
        layout.addRow("Combo Without ObjectName", self.combo2)

        # without buddy
        self.lineedit2label = qt.QLabel("Line Edit Without Buddy")
        self.lineedit2 = qt.QLineEdit()
        layout.addRow(self.lineedit2label, self.lineedit2)

        # collapsed ctk
        collapsible = ctk.ctkCollapsibleButton()
        collapsible.text = "Collapsed"
        collapsible.collapsed = True
        layout_collapsed = qt.QFormLayout(collapsible)
        self.combo3 = qt.QComboBox()
        layout_collapsed.addRow("Combo Collapsed", self.combo3)

        self.layout.addWidget(widget)
        self.layout.addWidget(collapsible)
        self.layout.addStretch(1)
