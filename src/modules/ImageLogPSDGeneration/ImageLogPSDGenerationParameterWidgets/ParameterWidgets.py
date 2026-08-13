import qt
import slicer

from ltrace.slicer import ui, helpers
from ltrace.constants import PSDLib
from ltrace.slicer.widget.help_button import HelpButton
from typing import Any, Callable
from pathlib import Path


# All parameter widgets should extend this class
class BaseForm(qt.QGroupBox):
    def __init__(self, title, warningLabel=None, objectName="", parent=None) -> None:
        super().__init__(parent)

        boxStyleSheet = """
            QGroupBox {
                border: 1px solid #999999;
                border-radius: 3px;
                margin-top: 7px; /* leave space at the top for the title */
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left; /* position at the top center */
                padding: 0 5px 0 0px;
                font-size: 13px;
            }
        """

        # Box config
        self.setTitle(title)
        self.setStyleSheet(boxStyleSheet)
        self.objectName = objectName

        # Layout
        qt.QFormLayout(self)

        # Modified presets wawrning label
        self.warningLabel = warningLabel

        # Control parameters
        self.currentPreset = None
        self.modified = []

    def _addChangedLabelSpan(self, label) -> None:
        span = "<span style='color: yellow;'>*</span>"
        labelText = label.text

        if span not in labelText:
            label.setText(f"{labelText}{span}")

    def _removeChangedLabelSpan(self, label) -> None:
        span = "<span style='color: yellow;'>*</span>"
        labelText = label.text

        if span in labelText:
            label.setText(labelText.replace(span, ""))

    def _addModifiedLabel(self, label) -> None:
        if label not in self.modified:
            self.modified.append(label)

    def _removeModifiedLabel(self, label) -> None:
        if label in self.modified:
            self.modified.remove(label)

    def _checkModification(self, value, label, field, presetExpected: Callable, required) -> None:
        # If a preset is selected, check if the parameter field values has been modified but not saved.
        if self.currentPreset:
            expectedValue = presetExpected()

            # If the value in the field is different from the one saved in the preset, add
            # a span mark in the label of the field
            if expectedValue != value:
                self._addChangedLabelSpan(label)
                self._addModifiedLabel(label)
            else:
                self._removeChangedLabelSpan(label)
                self._removeModifiedLabel(label)

            # Show modified preset warning label if necessary
            if self.warningLabel:
                if self.isModified():
                    self.warningLabel.show()
                else:
                    self.warningLabel.hide()

        if required:
            # If the field is empty, highlight the field
            if not value.strip():
                helpers.highlight_error(field)
            else:
                helpers.remove_highlight(field)

    def _onFieldValueChanged(self, value, label, field, presetExpected: Callable, required=True) -> None:
        self._checkModification(value, label, field, presetExpected, required)

    def _onItemSelected(self, index, label, combobox, presetExpected: Callable) -> None:
        self._checkModification(combobox.currentData, label, combobox, presetExpected, False)

    def _getIntOrList(self, string):
        if not string.strip():
            return None

        if "," in string:
            string = string.replace(" ", "").split(",")

            # If the string ends with a comma, eliminate the last empty element of the array
            if not string[-1]:
                del string[-1]

            string = list(map(int, string))

            # If the array contains only one element return it as an integer
            if len(string) == 1:
                string = string[0]
        else:
            string = int(string)

        return string

    def _toStrList(self, values):
        return ", ".join(str(v) for v in values)

    def removeAllModifiedSpans(self) -> None:
        for label in self.modified:
            self._removeChangedLabelSpan(label)

        self.modified.clear()

    def setCurrentPreset(self, preset, updateFields=True) -> None:
        self.currentPreset = preset

        if updateFields:
            self.presetToFields()

    def isModified(self) -> bool:
        return len(self.modified) > 0

    # Required functions
    def resetDefaultValues(self) -> None:
        pass

    def presetToFields(self) -> None:
        pass

    def fieldsToPreset(self):
        pass

    def validateFields(self) -> list[str]:
        pass

    def getParameters(self) -> dict[str, str]:
        pass

    def getMetadata(self) -> dict[str, Any]:
        pass


#### Parameter Widgets ####


class MicrotomParameters(BaseForm):
    def __init__(self, warningLabel=None, objectName="", parent=None) -> None:
        super().__init__(f"{PSDLib.MICROTOM.value} Parameters", warningLabel, objectName, parent)

        # Dfault values
        self.defaultSatRes = 0.03
        self.defaultRadRes = 0.05

        # Parameters
        self.satResLabel = qt.QLabel("Saturation Resolution: ")
        self.satResInput = ui.floatParam(value=self.defaultSatRes)
        self.satResInput.objectName = "Microtom Saturation Resolution"
        self.satResInput.textChanged.connect(
            lambda text: self._onFieldValueChanged(
                text, self.satResLabel, self.satResInput, lambda: self.currentPreset.satResMicrotom
            )
        )

        self.radResLabel = qt.QLabel("Radius Resolution: ")
        self.radResInput = ui.floatParam(value=self.defaultRadRes)
        self.radResInput.objectName = "Microrom Radius Resolution"
        self.radResInput.textChanged.connect(
            lambda text: self._onFieldValueChanged(
                text, self.radResLabel, self.radResInput, lambda: self.currentPreset.radResMicrotom
            )
        )

        # Update layout
        self.layout().setContentsMargins(6, 16, 6, 6)
        self.layout().addRow(self.satResLabel, self.satResInput)
        self.layout().addRow(self.radResLabel, self.radResInput)

    def resetDefaultValues(self):
        self.satResInput.text = str(self.defaultSatRes)
        self.radResInput.text = str(self.defaultRadRes)

    def presetToFields(self):
        if self.currentPreset:
            self.satResInput.text = self.currentPreset.satResMicrotom
            self.radResInput.text = self.currentPreset.radResMicrotom

    def fieldsToPreset(self):
        self.currentPreset.satResMicrotom = self.satResInput.text.strip()
        self.currentPreset.radResMicrotom = self.radResInput.text.strip()

    def validateFields(self):
        errors = []

        if not self.satResInput.text.strip():
            errors.append("Saturation Resolution is required.")

        if not self.radResInput.text.strip():
            errors.append("Radius Resolution is required.")

        return errors

    def getParameters(self):
        return {
            "sat_resolution": float(self.satResInput.text.strip()),
            "rad_resolution": float(self.radResInput.text.strip()),
            "output_file_path": str(Path(slicer.app.temporaryPath).absolute() / "psd.csv"),
        }

    def getMetadata(self):
        return {
            "saturation_resolution": str(self.satResInput.text.strip()),
            "radius_resolution": str(self.radResInput.text.strip()),
        }


class PorespyParameters(BaseForm):
    def __init__(self, warningLabel=None, objectName="", parent=None):
        super().__init__(f"{PSDLib.PORESPY.value} Parameters", warningLabel, objectName, parent)

        # Dfault values
        self.defaultSizes = [25]
        self.defaultSmooth = True
        self.defaultMethod = "dt"

        self.sizesLabel = qt.QLabel("Sizes: ")
        self.sizesInput = ui.intListParam(values=self.defaultSizes)
        self.sizesInput.objectName = "Porespy Sizes"
        self.sizesInput.textChanged.connect(
            lambda text: self._onFieldValueChanged(
                text, self.sizesLabel, self.sizesInput, lambda: self.currentPreset.sizesPorespy, False
            )
        )

        sizesPorespyHelpBtn = HelpButton("This input can be an integer or a list of integers. Ex: `25` or `1, 2, 3, 4`")

        self.smoothLabel = qt.QLabel("Smooth: ")
        self.smoothInput = qt.QCheckBox()
        self.smoothInput.checked = self.defaultSmooth
        self.smoothInput.objectName = "Porespy Smooth"
        self.smoothInput.connect(
            "toggled ( bool )",
            lambda state: self._onFieldValueChanged(
                state, self.smoothLabel, self.smoothInput, lambda: self.currentPreset.smoothPorespy, False
            ),
        )

        self.methodLabel = qt.QLabel("Method: ")
        self.methodComboBox = qt.QComboBox()
        self.methodComboBox.objectName = "Porespy Method"
        self.methodComboBox.addItem("Distance Transform", "dt")
        self.methodComboBox.addItem("Brute Force", "bf")
        self.methodComboBox.addItem("ImageJ", "imj")
        self.methodComboBox.addItem("Convolution", "conv")
        self.methodComboBox.currentIndexChanged.connect(
            lambda index: self._onItemSelected(
                index, self.methodLabel, self.methodComboBox, lambda: self.currentPreset.methodPorespy
            )
        )

        sizesWidget = qt.QWidget()
        sizesLayout = qt.QHBoxLayout(sizesWidget)
        sizesLayout.setContentsMargins(0, 0, 0, 0)
        sizesLayout.addWidget(self.sizesLabel)
        sizesLayout.addWidget(self.sizesInput)
        sizesLayout.addWidget(sizesPorespyHelpBtn)

        smoothWidget = qt.QWidget()
        smoothLayout = qt.QHBoxLayout(smoothWidget)
        smoothLayout.setAlignment(qt.Qt.AlignLeft)
        smoothLayout.setContentsMargins(0, 0, 0, 0)
        smoothLayout.addWidget(self.smoothLabel)
        smoothLayout.addWidget(self.smoothInput)

        self.layout().setContentsMargins(6, 16, 6, 12)
        self.layout().addRow(sizesWidget)
        self.layout().addRow(self.methodLabel, self.methodComboBox)
        self.layout().addRow(smoothWidget)

    def resetDefaultValues(self):
        self.sizesInput.text = self._toStrList(self.defaultSizes)
        self.smoothInput.checked = self.defaultSmooth
        self.methodComboBox.setCurrentIndex(self.methodComboBox.findData(self.defaultMethod))

    def presetToFields(self):
        if self.currentPreset:
            self.sizesInput.text = self.currentPreset.sizesPorespy
            self.smoothInput.checked = self.currentPreset.smoothPorespy
            self.methodComboBox.setCurrentIndex(self.methodComboBox.findData(self.currentPreset.methodPorespy))

    def fieldsToPreset(self):
        self.currentPreset.sizesPorespy = self.sizesInput.text.strip()
        self.currentPreset.smoothPorespy = self.smoothInput.checked
        self.currentPreset.methodPorespy = self.methodComboBox.currentData

    def validateFields(self):
        return []

    def getParameters(self):
        return {
            "sizes": self._getIntOrList(self.sizesInput.text.strip()),
            "smooth": self.smoothInput.checked,
            "method": self.methodComboBox.currentData,
        }

    def getMetadata(self):
        return {
            "sizes": str(self.sizesInput.text.strip()),
            "smooth": str(self.smoothInput.checked),
            "method": str(self.methodComboBox.currentData),
        }
