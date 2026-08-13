import qt
import ctk
import slicer

from ltrace.slicer import ui, helpers

# from ltrace.slicer.widget.help_button import HelpButton
from typing import Callable
from pathlib import Path


# All parameter widgets should extend this class
class BaseForm(qt.QGroupBox):
    def __init__(self, title, warningLabel, parent=None) -> None:
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
            if expectedValue != str(value):
                self._addChangedLabelSpan(label)
                self._addModifiedLabel(label)
            else:
                self._removeChangedLabelSpan(label)
                self._removeModifiedLabel(label)

            # Show modified preset warning label if necessary
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

    def _checkModificationCheckBox(self, value, label, field, presetExpected: Callable, required=True) -> None:
        # Don't know why checkbox is yelding value 2 when checked...
        self._checkModification(int(value == 2), label, field, presetExpected, required)

    def _onFieldValueChanged(self, value, label, field, presetExpected: Callable, required=True) -> None:
        self._checkModification(value, label, field, presetExpected, required)

    def _onItemSelected(self, index, label, combobox, presetExpected: Callable) -> None:
        self._checkModification(combobox.currentData, label, combobox, presetExpected, False)

    def _getIntOrList(self, string):
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


#### Parameter Widgets ####


class PSDPerDepthPresetParameters(BaseForm):
    # Define custom signal
    presetValuesApplied = qt.Signal()

    def __init__(
        self,
        warningLabel,
        parent=None,
        onDepthIntervalsChanged=None,
        onNBinsSpinBoxChanged=None,
        onLogXAxisCheckBoxChange=None,
        setDefaultDepthIntervalM=None,
        onInternalBinningLogCheckBoxChange=None,
        onSmoothOnChange=None,
        onSmoothnessSliderReleased=None,
        constraintDepthInterval=None,
        porousAreaMM2=None,
    ) -> None:
        super().__init__(f"PSDPerDepth Parameters", warningLabel, parent)

        self.setDefaultDepthIntervalM = setDefaultDepthIntervalM
        self.constraintDepthInterval = constraintDepthInterval

        self.defaultNbinsSpinBox = 20
        self.defaultInternalBinningLogCheckBox = True
        self.defaultSmoothOn = False
        self.defaultAmountSlider = 3
        self.defaultLogXAxisCheckBox = False

        # Parameters

        self.depthIntervalLabel = qt.QLabel("Depth intervals (m): ")
        self._depthIntervalLimits = [0.01, 1000]  # in meters
        self.depthIntervalSpinBox = qt.QDoubleSpinBox()
        self.depthIntervalSpinBox.setRange(self._depthIntervalLimits[0], self._depthIntervalLimits[1])
        self.depthIntervalSpinBox.setSingleStep(0.5)
        self.depthIntervalSpinBox.setDecimals(3)
        self.depthIntervalSpinBox.setValue(setDefaultDepthIntervalM())
        self.depthIntervalSpinBox.valueChanged.connect(onDepthIntervalsChanged)
        self.depthIntervalSpinBox.objectName = "Depth Interval Spin Box"
        self.depthIntervalSpinBox.valueChanged.connect(
            lambda text: self._onFieldValueChanged(
                text,
                self.depthIntervalLabel,
                self.depthIntervalSpinBox,
                lambda: self.currentPreset.depthInterval,
                required=False,
            )
        )

        self.nbinsLabel = qt.QLabel("Number of histograms bins: ")
        self.nbinsSpinBox = qt.QSpinBox()
        self.nbinsSpinBox.setRange(10, 40)
        self.nbinsSpinBox.setSingleStep(5)
        self.nbinsSpinBox.setValue(self.defaultNbinsSpinBox)
        self.nbinsSpinBox.valueChanged.connect(onNBinsSpinBoxChanged)
        self.nbinsSpinBox.objectName = "Number of Histograms Bins Spin Box"
        self.nbinsSpinBox.valueChanged.connect(
            lambda text: self._onFieldValueChanged(
                text, self.nbinsLabel, self.nbinsSpinBox, lambda: self.currentPreset.nbins, required=False
            )
        )

        sliderStyle = """
        /* Left portion when Enabled */
        QSlider::sub-page:horizontal {
            background: #4CAF50;
            border-radius: 4px;
        }

        /* Left portion when Disabled */
        QSlider::sub-page:horizontal:disabled {
            background: #A0A0A0;
            border-radius: 4px;
        }

        /* Groove */
        QSlider::groove:horizontal {
            background: #D0D0D0;
            height: 4px;
            border-radius: 4px;
        }

        /* Handle when Enabled */
        QSlider::handle:horizontal {
            background: #F0F0F0;
            border: 1px solid #777;
            width: 18px;
            margin: -5px 0; /* Centraliza no trilho */
            border-radius: 9px;
        }

        /* Handle when Disabled */
        QSlider::handle:horizontal:disabled {
            background: #E0E0E0;
            border-color: #B0B0B0;
        }
        """

        self.smoothAmountLabel = qt.QLabel("Smooth degree: ")
        self.smoothAmountLimits = [1, 10]
        self.smoothAmountSlider = qt.QSlider(qt.Qt.Horizontal)
        self.smoothAmountSlider.setStyleSheet(sliderStyle)
        self.smoothAmountSlider.setMinimum(int(self.smoothAmountLimits[0]))
        self.smoothAmountSlider.setMaximum(int(self.smoothAmountLimits[1]))
        self.smoothAmountSlider.setSingleStep(1)
        self.smoothAmountSlider.setValue(self.defaultAmountSlider)
        self.smoothAmountSlider.setEnabled(self.defaultSmoothOn)
        self.smoothAmountSlider.objectName = "KDE Bandwidth Amount Slider"
        self.smoothAmountLabel.setText(f"Smooth degree: {self.defaultAmountSlider}")
        self.smoothAmountSlider.valueChanged.connect(
            lambda value: self._onFieldValueChanged(
                str(value),
                self.smoothAmountLabel,
                self.smoothAmountSlider,
                lambda: self.currentPreset.smoothAmount,
                required=False,
            )
        )
        self.smoothAmountSlider.sliderReleased.connect(onSmoothnessSliderReleased)
        self.smoothAmountSlider.valueChanged.connect(
            lambda: self.smoothAmountLabel.setText(f"Smooth degree: {self.smoothAmountSlider.value}")
        )

        self.smoothOnLabel = qt.QLabel("Smooth ON/OFF: ")
        self.smoothOn = qt.QCheckBox("")
        self.smoothOn.stateChanged.connect(onSmoothOnChange)
        self.smoothOn.setChecked(self.defaultSmoothOn)
        self.smoothOn.objectName = "Gaussian KDE On/Off Check Box"
        self.smoothOn.stateChanged.connect(
            lambda text: self._checkModificationCheckBox(
                text, self.logXAxisLabel, self.logXAxisCheckBox, lambda: self.currentPreset.logXAxis, required=False
            )
        )
        self.smoothOn.stateChanged.connect(self.smoothAmountSlider.setEnabled)

        self.logXAxisLabel = qt.QLabel("Log X axis (pore size, mm): ")
        self.logXAxisCheckBox = qt.QCheckBox("")
        self.logXAxisCheckBox.stateChanged.connect(onLogXAxisCheckBoxChange)
        self.logXAxisCheckBox.setChecked(self.defaultLogXAxisCheckBox)
        self.logXAxisCheckBox.objectName = "Log X Axis Check Box"
        self.logXAxisCheckBox.stateChanged.connect(
            lambda text: self._checkModificationCheckBox(
                text, self.logXAxisLabel, self.logXAxisCheckBox, lambda: self.currentPreset.logXAxis, required=False
            )
        )

        # Add here a checkbox "internal binning in log scale" inside a "Advanced" ctkCollapsibleButton
        self.advancedCollapsibleButton = ctk.ctkCollapsibleButton()
        self.advancedCollapsibleButton.setText("Advanced")
        self.layout().addWidget(self.advancedCollapsibleButton)

        self.internalBinningLogLabel = qt.QLabel("Internal binning in log scale: ")
        self.internalBinningLogCheckBox = qt.QCheckBox("")
        self.internalBinningLogCheckBox.setChecked(self.defaultInternalBinningLogCheckBox)
        self.internalBinningLogCheckBox.stateChanged.connect(onInternalBinningLogCheckBoxChange)
        self.internalBinningLogCheckBox.objectName = "Internal Binning Log Check Box"

        self.internalBinningLogCheckBox.stateChanged.connect(
            lambda text: self._checkModificationCheckBox(
                text,
                self.internalBinningLogLabel,
                self.internalBinningLogCheckBox,
                lambda: self.currentPreset.internalBinningLog,
                required=False,
            )
        )
        advancedLayout = qt.QFormLayout(self.advancedCollapsibleButton)
        self.advancedCollapsibleButton.layout().addRow(self.internalBinningLogLabel, self.internalBinningLogCheckBox)
        self.advancedCollapsibleButton.layout().addRow(self.nbinsLabel, self.nbinsSpinBox)

        # Update layout
        self.layout().setContentsMargins(6, 16, 6, 6)
        self.layout().addRow(self.depthIntervalLabel, self.depthIntervalSpinBox)
        self.layout().addRow(self.smoothOnLabel, self.smoothOn)
        self.layout().addRow(self.smoothAmountLabel, self.smoothAmountSlider)
        self.layout().addRow(self.logXAxisLabel, self.logXAxisCheckBox)
        self.layout().addRow(self.advancedCollapsibleButton)

    def blockSignalsFromUI(self, block):
        self.depthIntervalSpinBox.blockSignals(block)
        self.nbinsSpinBox.blockSignals(block)
        self.logXAxisCheckBox.blockSignals(block)
        self.smoothOn.blockSignals(block)
        self.smoothAmountSlider.blockSignals(block)
        self.internalBinningLogCheckBox.blockSignals(block)

    def resetDefaultValues(self):
        self.blockSignalsFromUI(True)
        self.depthIntervalSpinBox.setValue(self.setDefaultDepthIntervalM())
        self.nbinsSpinBox.setValue(self.defaultNbinsSpinBox)
        self.internalBinningLogCheckBox.setChecked(self.defaultInternalBinningLogCheckBox)
        self.smoothOn.setChecked(self.defaultSmoothOn)
        self.smoothAmountSlider.setValue(self.defaultAmountSlider)
        self.smoothAmountLabel.setText(f"Smooth degree: {self.defaultAmountSlider}")
        self.logXAxisCheckBox.setChecked(self.defaultLogXAxisCheckBox)
        self.blockSignalsFromUI(False)
        self.presetValuesApplied.emit()

    def presetToFields(self):
        if self.currentPreset:
            self.blockSignalsFromUI(True)
            self.depthIntervalSpinBox.setValue(self.constraintDepthInterval(float(self.currentPreset.depthInterval)))
            self.nbinsSpinBox.setValue(int(self.currentPreset.nbins))
            self.logXAxisCheckBox.setChecked(bool(int(self.currentPreset.logXAxis)))
            self.internalBinningLogCheckBox.setChecked(bool(int(self.currentPreset.internalBinningLog)))
            self.smoothOn.setChecked(bool(int(self.currentPreset.smoothOn)))
            self.smoothAmountSlider.setValue(float(self.currentPreset.smoothAmount))
            self.blockSignalsFromUI(False)
        self.presetValuesApplied.emit()

    def fieldsToPreset(self):
        self.currentPreset.depthInterval = str(self.depthIntervalSpinBox.value)
        self.currentPreset.nbins = str(self.nbinsSpinBox.value)
        self.currentPreset.logXAxis = "1" if self.logXAxisCheckBox.isChecked() else "0"
        self.currentPreset.smoothOn = "1" if self.smoothOn.isChecked() else "0"
        self.currentPreset.smoothAmount = str(self.smoothAmountSlider.value)
        self.currentPreset.internalBinningLog = "1" if self.internalBinningLogCheckBox.isChecked() else "0"

    def validateFields(self):
        errors = []

        if not self.depthIntervalSpinBox.text.strip():
            errors.append("Depth interval is required.")

        if not self.nbinsSpinBox.text.strip():
            errors.append("Number of bins is required.")

        return errors

    def getParameters(self):
        return {
            "depthInterval": float(self.currentPreset.depthInterval),
            "nbins": int(self.currentPreset.nbins),
            "logXAxis": bool(self.currentPreset.logXAxis),
            "smoothOn": bool(self.currentPreset.smoothOn),
            "smoothAmount": float(self.currentPreset.smoothAmount),
            "internalBinningLog": bool(self.currentPreset.internalBinningLog),
            "output_file_path": str(Path(slicer.app.temporaryPath).absolute() / "psdperdepth.csv"),
        }
