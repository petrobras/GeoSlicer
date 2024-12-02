import logging
import qt
import numpy as np

from ltrace.slicer import ui
from ltrace.slicer.helpers import themeIsDark


class MultistepEditWidget(qt.QBoxLayout):
    stepChanged = qt.Signal()
    valueChanged = qt.Signal()

    def __init__(self, **kwargs):
        super().__init__(qt.QBoxLayout.LeftToRight)
        self.parameter_name = kwargs["parameter_name"]
        self.conversion_factor = kwargs.get("conversion_factor", 1)
        self.step_spacing = kwargs.get("step_spacing", "linear")

        self.start = ui.floatParam()
        self.start.text = kwargs["default_value"]
        self.start.objectName = f"{self.parameter_name}_start"
        self.start.editingFinished.connect(self.onValueChanged)
        self.stop = ui.floatParam()
        self.stop.text = kwargs["default_value"] * 2
        self.stop.objectName = f"{self.parameter_name}_stop"
        self.stop.editingFinished.connect(self.onValueChanged)
        self.steps = ui.intParam()
        self.steps.text = 1
        self.steps.objectName = f"{self.parameter_name}_step"
        self.steps.editingFinished.connect(self.onStepEdited)
        self.steps.editingFinished.connect(self.onValueChanged)
        self.startLabel = qt.QLabel(" Value:")

        self.multiWidget = qt.QWidget()
        self.multiLayout = qt.QHBoxLayout(self.multiWidget)
        self.multiLayout.setContentsMargins(0, 0, 0, 0)
        self.multiLayout.addWidget(qt.QLabel(" Stop:"))
        self.multiLayout.addWidget(self.stop)
        self.multiLayout.addWidget(qt.QLabel(" Steps:"))
        self.multiLayout.addWidget(self.steps)
        self.multiWidget.setVisible(False)

        self.multiPushButton = qt.QPushButton("Multi")
        self.multiPushButton.setCheckable(True)
        self.multiPushButton.setChecked(False)
        self.multiPushButton.clicked.connect(self.onMultiPushButtonToggle)
        self.multiPushButton.clicked.connect(self.onValueChanged)

        self.addWidget(self.startLabel)
        self.addWidget(self.start)
        self.addWidget(self.multiWidget)
        self.addWidget(self.multiPushButton)

    def onMultiPushButtonToggle(self):
        visible = self.multiPushButton.isChecked()
        self.__enableMultiField(visible)
        self.steps.text = 1
        self.stepChanged.emit()

    def onValueChanged(self):
        self.valueChanged.emit()

    def onStepEdited(self):
        self.stepChanged.emit()

    def get_values(self):
        start = float(self.start.text)
        stop = float(self.stop.text)
        steps = int(self.steps.text)
        cf = self.conversion_factor
        if steps == 1:
            return {self.parameter_name: start * cf}
        else:
            if self.step_spacing == "logarithmic":
                values = np.geomspace(start, stop, steps)
            else:
                values = np.linspace(start, stop, steps)
            values = tuple(i * cf for i in values)
        return {self.parameter_name: values}

    def get_name(self):
        return self.parameter_name

    def get_start(self):
        try:
            return float(self.start.text)
        except ValueError:
            return None

    def get_stop(self):
        try:
            return float(self.stop.text)
        except ValueError:
            return None

    def get_steps(self):
        try:
            return int(float(self.steps.text))
        except ValueError:
            return None

    def set_value(self, start, stop):
        self.start.setText(str(start))
        self.stop.setText(str(stop))

    def set_steps(self, num_of_steps):
        num_of_steps_int = int(float(num_of_steps))
        self.__enableMultiField(num_of_steps_int != 1)
        self.steps.setText(str(num_of_steps_int))
        self.stepChanged.emit()

    def __enableMultiField(self, enable):
        self.multiWidget.setVisible(enable)
        if enable:
            self.startLabel.setText(" Start:")
        else:
            self.startLabel.setText(" Value:")


class SinglestepEditWidget(qt.QBoxLayout):
    def __init__(self, **kwargs):
        super().__init__(qt.QBoxLayout.LeftToRight)
        self.parameter_name = kwargs["parameter_name"]

        self.entry = ui.floatParam()
        self.entry.text = kwargs["default_value"]
        self.entry.objectName = f"{self.parameter_name}_entry"
        self.addWidget(self.entry)

    def get_values(self):
        return {self.parameter_name: float(self.entry.text)}

    def get_name(self):
        return self.parameter_name

    def get_value(self):
        return float(self.entry.text)

    def set_value(self, value: float):
        self.entry.text = str(value)


class SinglestepIntWidget(qt.QBoxLayout):
    def __init__(self, **kwargs):
        super().__init__(qt.QBoxLayout.LeftToRight)
        self.parameter_name = kwargs["parameter_name"]

        self.entry = ui.intParam()
        self.entry.text = str(int(kwargs["default_value"]))
        self.entry.objectName = f"{self.parameter_name}_entry"
        self.addWidget(self.entry)

    def get_values(self):
        return {self.parameter_name: int(self.entry.text)}

    def get_name(self):
        return self.parameter_name

    def get_value(self):
        return int(self.entry.text)

    def set_value(self, value: int):
        self.entry.text = str(int(float(value)))


class IntegerSpinBoxWidget(qt.QBoxLayout):
    def __init__(self, **kwargs):
        super().__init__(qt.QBoxLayout.LeftToRight)
        self.parameter_name = kwargs["parameter_name"]

        self.entry = qt.QSpinBox()
        self.entry.minimum = kwargs["minimum_value"]
        self.entry.maximum = kwargs["maximum_value"]
        self.entry.value = kwargs["default_value"]
        self.entry.objectName = f"{self.parameter_name}_entry"
        self.addWidget(self.entry)

    def get_values(self):
        return {self.parameter_name: self.entry.value}

    def get_name(self):
        return self.parameter_name

    def get_value(self):
        return self.entry.value

    def set_value(self, value):
        self.entry.value = int(value)


class CheckboxWidget(qt.QGridLayout):
    def __init__(self, **kwargs):
        super().__init__()
        self.parameter_name = kwargs["parameter_name"]
        self.true_value = kwargs["true_value"]
        self.false_value = kwargs["false_value"]

        options_num = len(kwargs["default_values"])
        self.setColumnStretch(2, options_num)
        self.setHorizontalSpacing(50)
        self.checkboxes = {}
        for i, (name, default) in enumerate(kwargs["default_values"].items()):
            if name:
                self.addWidget(qt.QLabel(name), 0, i)
            self.checkboxes[name] = qt.QCheckBox()
            self.addWidget(self.checkboxes[name], 1, i)
            self.checkboxes[name].setChecked(default)
            self.checkboxes[name].objectName = f"{self.parameter_name}_{name}"

    def get_values(self):
        values = {}
        if len(self.checkboxes) == 1:
            for name, checkbox in self.checkboxes.items():
                values[f"{self.parameter_name}"] = self.true_value if checkbox.isChecked() else self.false_value
        else:
            for name, checkbox in self.checkboxes.items():
                values[f"{self.parameter_name}_{name}"] = self.true_value if checkbox.isChecked() else self.false_value
        return values

    def set_checked(self, new_state):
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(new_state)

    def setEnabled(self, new_state):
        for checkbox in self.checkboxes.values():
            checkbox.setEnabled(new_state)

    def get_name(self):
        return self.parameter_name

    def get_value(self):
        string_value = ""
        for checkbox in self.checkboxes.values():
            string_value += "1" if checkbox.isChecked() else "0"
        return string_value

    def set_value(self, string_value):
        for i, checkbox in enumerate(self.checkboxes.values()):
            if i < len(string_value):
                checkbox.setChecked(string_value[i] == "1")
            else:
                break


class SingleCheckboxWidget(qt.QCheckBox):
    def __init__(self, **kwargs):
        super().__init__()
        self.parameter_name = kwargs["parameter_name"]
        self.true_value = kwargs["true_value"]
        self.false_value = kwargs["false_value"]

        default = kwargs["default_value"]
        self.setChecked(default)
        self.objectName = f"{self.parameter_name}"

    def get_values(self):
        return {self.parameter_name: self.true_value if self.isChecked() else self.false_value}

    def get_name(self):
        return self.parameter_name

    def get_value(self):
        return self.true_value if self.isChecked() else self.false_value

    def set_value(self, checked):
        self.setChecked(checked == self.true_value)


class ComboboxWidget(qt.QBoxLayout):
    currentTextChanged = qt.Signal(str, str)

    def __init__(self, **kwargs):
        super().__init__(qt.QBoxLayout.LeftToRight)
        self.parameter_name = kwargs["parameter_name"]
        self.string_values = []
        self.combo_box = qt.QComboBox()

        for display_name, pnflow_string in kwargs["display_names"].items():
            self.string_values.append(pnflow_string)
            self.combo_box.addItem(display_name)
        self.addWidget(self.combo_box)
        self.combo_box.currentTextChanged.connect(self.onTextChanged)
        self.combo_box.setCurrentIndex(kwargs["default_value"])
        self.combo_box.objectName = f"{self.parameter_name}_cbox"

    def get_values(self):
        return {self.parameter_name: self.string_values[self.combo_box.currentIndex]}

    def get_text(self):
        return self.combo_box.currentText

    def get_name(self):
        return self.parameter_name

    def get_value(self):
        return self.string_values[self.combo_box.currentIndex]

    def set_value(self, value):
        try:
            self.combo_box.currentIndex = self.string_values.index(value)
        except ValueError:
            logging.error(f'Wrong value "{value}" for parameter {self.parameter_name}')

    def onTextChanged(self):
        self.currentTextChanged.emit(self.parameter_name, self.combo_box.currentText)

    def setEnabled(self, new_state):
        self.combo_box.setEnabled(new_state)


class TooltipLabel(qt.QLabel):
    def __init__(self, text):
        super().__init__(text)

        self.tooltip_text = ""
        underline_color = "white" if themeIsDark() else "black"
        self.setStyleSheet(
            f"""
            QLabel {{
                border: 0px;
                border-bottom: 1px dotted {underline_color};
                margin-bottom: -1px;
            }}
            """
        )

    def setToolTip(self, text):
        self.tooltip_text = text

    def enterEvent(self, event):
        qt.QToolTip.showText(event.globalPos(), self.tooltip_text)
