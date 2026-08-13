import importlib
import sys
import ctk
import os
import qt
import slicer
from ltrace.slicer.widget.preset_widget import Preset, PresetWidget
from slicer.parameterNodeWrapper import parameterNodeWrapper, parameterPack
import logging
import pandas as pd
import numpy as np
import logging
import uuid
import json
import porespy as ps
from scipy.signal import savgol_filter

from ltrace.algorithms.measurements import GENERIC_PROPERTIES
from ltrace.slicer import ui
from ltrace.slicer.data_utils import dataFrameToTableNode
from ltrace.slicer.node_attributes import (
    HistogramGraphType,
    PlotScaleXAxisAttribute,
    TableType,
    TableDataOrientation,
    TableDataTypeAttribute,
)
from ltrace.slicer.helpers import (
    tryGetNode,
    arrayPartsFromNode,
    copy_subject_hierarchy_item_parent,
)
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, getResourcePath
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.slicer.metadata import Metadata
from PSDPerDepthParameterWidget.PSDPerDepthParameterWidget import PSDPerDepthPresetParameters
from pathlib import Path
import time
from threading import Thread

try:
    from Test.PSDPerDepthTest import PSDPerDepthTest
except ImportError:
    PSDPerDepthTest = None  # Tests are not available in the build


@parameterNodeWrapper
class PSDPerDepthParameterNode:
    """
    Class to store/retrieve UI parametes when the project is saved/loaded.
    """

    inputNodeID: str
    preset: str
    depthInterval: float
    nbins: int
    checkBoxLogX: bool
    internalBinningLog: bool
    smoothOn: bool
    smoothAmount: float

    tableNodeID: str
    outputPrefix: str


class PSDPerDepthPreset(Preset):
    def __init__(
        self,
        id=None,
        name=None,
        depthInterval=None,
        nbins=None,
        logXAxis=None,
        smoothOn=None,
        smoothAmount=None,
        internalBinningLog=None,
    ):
        super().__init__(id, name)

        self.depthInterval = depthInterval
        self.nbins = nbins
        self.logXAxis = logXAxis
        self.internalBinningLog = internalBinningLog
        self.smoothOn = smoothOn
        self.smoothAmount = smoothAmount


class PSDPerDepth(LTracePlugin):
    SETTING_KEY = "PSDPerDepth"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    PRESETS_PATH = Path(slicer.app.slicerUserSettingsFilePath).parent / "PSDPerDepthPresets.json"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Histogram Per Depth"
        self.parent.categories = ["ImageLog"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.setHelpUrl("ImageLog/PoreSizeDistribution/PoreSizeDistribution.html#image-log-psd-per-depth")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PSDPerDepthWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self._observerTags = {}
        self.parameterNode = None
        self.presetsFilePath = PSDPerDepth.PRESETS_PATH
        self.exportPresetsPath = os.path.join(slicer.mrmlScene.GetRootDirectory(), "PSDPerDepthPresets.json")
        self.importPresetsPath = slicer.mrmlScene.GetRootDirectory()
        # self.presets: Dict[uuid.UUID, PSDLib] = {} ??
        self.presets = None

    def setup(self):
        LTracePluginWidget.setup(self)

        self.logic = PSDPerDepthLogic(widget=self)

        # Init presets
        self.presets = self.logic.getPresets(self.presetsFilePath)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.collapsed = False
        inputSection.text = "Input PSD Image"

        self.inputSelector = slicer.qMRMLNodeComboBox()
        self.inputSelector.nodeTypes = [
            "vtkMRMLScalarVolumeNode",
        ]
        self.inputSelector.currentNodeChanged.connect(self.onInputNodeChanged)
        self.inputSelector.noneEnabled = True
        self.inputSelector.addEnabled = False
        self.inputSelector.editEnabled = False
        self.inputSelector.removeEnabled = False
        self.inputSelector.renameEnabled = False
        self.inputSelector.setMRMLScene(slicer.mrmlScene)
        self.inputSelector.setToolTip("Pick a PSD image")
        self.inputSelector.objectName = "Input PSD Volume Selector"
        self.inputSelector.setCurrentNode(None)

        inputLayout = qt.QFormLayout(inputSection)
        inputLayout.addRow("Input:", self.inputSelector)

        # Preset section
        presetHelpText = (
            "You can save the parameters for later use.\n\n"
            "**Create:** Create a preset with the current parameters.<br>"
            "**Rename:** Rename a preset.<br>"
            "**Save:** Saves the current parameters in the selected preset.<br>"
            "**Delete:** Delete the selected preset.<br>\n\n"
            "You can also import and export presets in JSON format. When importing, the selected presets in the file "
            "will be added to the existing presets. If a preset with the same name already exists, a unique suffix "
            "will be added to the name of the imported preset."
        )

        self.presetWidget = PresetWidget(
            onPresetSelected=self._onPresetSelected,
            onCreatePresetClicked=self._onCreatePresetClicked,
            onRenamePresetClicked=self._onRenamePresetClicked,
            onSavePresetClicked=self._onSavePresetClicked,
            onDeletePresetClicked=self._onDeletePresetClicked,
            onExportPresetClicked=self._onExportPresetClicked,
            onImportPresetClicked=self._onImportPresetClicked,
            helpText=presetHelpText,
            styledBox=True,
            parent=self.layout.parentWidget(),
        )

        # Warning label of modified presets
        self.warningLabel = qt.QLabel(
            "Warning: Parameters marked with (*) have been modified and are not \nyet saved in the selected preset."
        )
        self.warningLabel.setStyleSheet("QLabel { color : yellow; }")
        self.warningLabel.hide()

        # Parameters section
        parametersSection = ctk.ctkCollapsibleButton()
        parametersSection.text = "Parameters"
        parametersSection.collapsed = False
        parametersSection.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        self.presetParameters = PSDPerDepthPresetParameters(
            self.warningLabel,
            onDepthIntervalsChanged=self.onDepthIntervalsChanged,
            onNBinsSpinBoxChanged=self.onSpinBoxChange,
            onLogXAxisCheckBoxChange=self.onLogXAxisCheckBoxChange,
            onSmoothOnChange=self.onSmoothOnChange,
            onInternalBinningLogCheckBoxChange=self.onInternalBinningLogCheckBoxChange,
            onSmoothnessSliderReleased=self.onSmoothnessSliderReleased,
            setDefaultDepthIntervalM=self.defaultDepthIntervalM,
            constraintDepthInterval=self.constraintDepthInterval,
            parent=self.layout.parentWidget(),
        )

        self.presetParameters.presetValuesApplied.connect(self.tryApply)

        self.parametersWidget = qt.QStackedWidget()
        self.parametersWidget.setContentsMargins(6, 0, 6, 0)
        self.parametersWidget.addWidget(self.presetParameters)

        # Reset buttons
        self.resetPresetBtn = ui.ButtonWidget(
            text="Reload Preset Values",
            onClick=self._onResetPresetClicked,
            object_name="Reset Parameters Preset",
            tooltip="Reset parameters with the preset values",
        )

        self.resetParametersBtn = ui.ButtonWidget(
            text="Reload Default Values",
            onClick=self._onResetParametersClicked,
            object_name="Reset Parameters Default",
            tooltip="Reset parameters with default values",
        )

        buttonLayout = qt.QHBoxLayout()
        buttonLayout.setContentsMargins(0, 6, 6, 0)
        buttonLayout.addStretch(1)
        buttonLayout.addWidget(self.resetPresetBtn)
        buttonLayout.addWidget(self.resetParametersBtn)

        # Parameters section widget
        parametersLayout = qt.QFormLayout(parametersSection)
        parametersLayout.addRow(self.presetWidget)  # presetInputWidget
        parametersLayout.addRow(self.parametersWidget)
        parametersLayout.addRow(self.warningLabel)
        parametersLayout.addRow(buttonLayout)

        # Output section
        outputSection = ctk.ctkCollapsibleButton()
        outputSection.text = "Output"
        outputSection.collapsed = False

        self.outputPrefixLineEdit = qt.QLineEdit()
        self.outputPrefixLineEdit.objectName = "Output Prefix Line Edit"
        outputFormLayout = qt.QFormLayout(outputSection)
        outputFormLayout.addRow("Output prefix:", self.outputPrefixLineEdit)

        # Apply buttons
        applyWidget = qt.QWidget()
        applyLayout = qt.QHBoxLayout(applyWidget)
        self.applyButton = ui.ApplyButton(onClick=self.onApplyButtonClicked, tooltip="Apply changes", enabled=True)
        self.applyButton.objectName = "Apply Button"
        self.applyButton.setEnabled(False)

        self.applyNewButton = ui.ApplyButton(
            onClick=self.onApplyToNewTable,
            text="Create New",
            tooltip="Create new table of histograms from the actual parameters",
            enabled=True,
        )
        self.applyNewButton.objectName = "Apply New Button"
        self.applyNewButton.setEnabled(False)

        applyLayout.addWidget(self.applyButton)
        applyLayout.addWidget(self.applyNewButton)

        self.progressBar = qt.QProgressBar()
        self.progressBar.objectName = "Progress Bar"
        self.progressBar.setValue(0)
        self.progressBar.hide()

        # Update layout
        self.layout.addWidget(inputSection)
        self.layout.addWidget(parametersSection)
        self.layout.addWidget(outputSection)
        self.layout.addWidget(applyWidget)
        self.layout.addWidget(self.progressBar)

        self.layout.addStretch(1)

        self.tableViewsanityEnforcer = None
        self.runsanityEnforce = -1

        self.initParameterNode()
        self.presetWidget.loadData(self.presets.values())

    def fillParameterNodeFromUI(self):
        self.parameterNode.depthInterval = self.presetParameters.depthIntervalSpinBox.value
        self.parameterNode.nbins = self.presetParameters.nbinsSpinBox.value
        self.parameterNode.inputNodeID = (
            self.inputSelector.currentNode().GetID() if self.inputSelector.currentNode() else ""
        )
        self.parameterNode.checkBoxLogX = self.presetParameters.logXAxisCheckBox.isChecked()
        self.parameterNode.smoothOn = self.presetParameters.smoothOn.isChecked()
        self.parameterNode.smoothAmount = self.presetParameters.smoothAmountSlider.value
        self.parameterNode.internalBinningLog = self.presetParameters.internalBinningLogCheckBox.isChecked()
        if self.presetWidget.presetComboBox.currentIndex >= 0 and self.presetWidget.presetComboBox.currentData:
            self.parameterNode.preset = self.presetWidget.presetComboBox.currentData  # currentData is the selected key
        else:
            self.parameterNode.preset = ""
        self.parameterNode.tableNodeID = ""
        for v, view in enumerate(slicer.modules.AppContextInstance.imageLogDataLogic.imageLogViewList):
            if view == self.logic.associatedView:
                self.parameterNode.tableNodeID = (
                    slicer.modules.AppContextInstance.imageLogDataLogic.viewControllerWidget_PrimaryNodeComboBox(v)
                    .currentNode()
                    .GetID()
                )
                break
        self.parameterNode.outputPrefix = self.outputPrefixLineEdit.text

    def onSaveSceneStart(self, caller, event):
        self.fillParameterNodeFromUI()

    def fillUIFromParameterNode(self):
        if self.parameterNode:  # and self.parameterNode.inputNodeID:
            if self.parameterNode.inputNodeID:
                node = slicer.util.getNode(self.parameterNode.inputNodeID)
                self.SetInputNodeWithoutCallbacks(node)
                self.tryAddNodeToNewView(node)
            else:
                self.inputSelector.setCurrentNode(None)

            self.presetParameters.depthIntervalSpinBox.blockSignals(True)
            self.presetParameters.depthIntervalSpinBox.value = self.parameterNode.depthInterval
            self.presetParameters.depthIntervalSpinBox.blockSignals(False)

            self.presetParameters.nbinsSpinBox.blockSignals(True)
            self.presetParameters.nbinsSpinBox.value = self.parameterNode.nbins
            self.presetParameters.nbinsSpinBox.blockSignals(False)

            self.outputPrefixLineEdit.text = self.parameterNode.outputPrefix

            if self.parameterNode.tableNodeID:
                node = slicer.util.getNode(self.parameterNode.tableNodeID)
                # If the node is being visualized in a view, set self.logic.associatedView
                self.logic.associatedView = None
                for c, vcw in enumerate(slicer.modules.AppContextInstance.imageLogDataLogic.viewControllerWidgets):
                    if (
                        node
                        == slicer.modules.AppContextInstance.imageLogDataLogic.viewControllerWidget_PrimaryNodeComboBox(
                            c
                        ).currentNode()
                    ):
                        self.logic.associatedView = (
                            slicer.modules.AppContextInstance.imageLogDataLogic.imageLogViewList[c]
                        )
                        break

            self.presetParameters.logXAxisCheckBox.setChecked(self.parameterNode.checkBoxLogX)

            self.presetParameters.smoothOn.blockSignals(True)
            self.presetParameters.smoothOn.setChecked(self.parameterNode.smoothOn)
            self.presetParameters.smoothOn.blockSignals(False)
            self.presetParameters.smoothAmountSlider.blockSignals(True)
            self.presetParameters.smoothAmountSlider.setValue(self.parameterNode.smoothAmount)
            self.presetParameters.smoothAmountSlider.blockSignals(False)
            self.presetParameters.smoothAmountSlider.setEnabled(self.parameterNode.smoothOn)

            self.presetParameters.internalBinningLogCheckBox.blockSignals(True)
            self.presetParameters.internalBinningLogCheckBox.setChecked(self.parameterNode.internalBinningLog)
            self.presetParameters.internalBinningLogCheckBox.blockSignals(False)

            if self.parameterNode.preset:
                index = self.presetWidget.presetComboBox.findData(self.parameterNode.preset)
                if index >= 0:
                    self.presetWidget.setCurrentIndex(index)
                else:
                    self.presetWidget.setCurrentIndex(0)
            else:
                self.presetWidget.setCurrentIndex(0)

    def onImportSceneEnd(self, caller, event):
        self.fillUIFromParameterNode()
        self.checkApplyButtonsState()

    def delayedAddNodeToView(self, node):
        self.logic.associatedView = slicer.modules.AppContextInstance.imageLogDataLogic.imageLogViewList[-1]

    def SetInputNodeWithoutCallbacks(self, node):
        self.inputSelector.blockSignals(True)
        self.inputSelector.setCurrentNode(node)
        self.inputSelector.blockSignals(False)
        self.checkApplyButtonsState()

    def getDepthIntervalLimits(self):
        return self.presetParameters._depthIntervalLimits

    def waitForViewWidget(self, view, timeout_seconds=10):
        start_time = time.time()
        while not view.widget:
            if time.time() - start_time > timeout_seconds:
                logging.error(f"PSDPerDepthWidget: Time out waiting view's widget to be ready!")
                break
            qt.QApplication.processEvents()
            time.sleep(0.1)

    def _updateParametersCurrentPreset(self, preset, updateFields=True):
        self.presetParameters.setCurrentPreset(preset, updateFields)

    def _onResetPresetClicked(self, state):
        if self.presetWidget.getCurrentData() is None:
            return

        self.presetParameters.presetToFields()

    def _onResetParametersClicked(self, state):
        self.presetParameters.resetDefaultValues()

    def _onPresetSelected(self, index):
        if index == 0:
            return
        if self.presetWidget.getCurrentData() is None or not self.presets or index == 0:
            return

        presetId = self.presetWidget.getCurrentData()

        if presetId is None or not self.presets:
            self.resetPresetBtn.enabled = False
            self._updateParametersCurrentPreset(None)

            self.presetParameters.removeAllModifiedSpans()

            self._checkShowWarning()
            return

        self.resetPresetBtn.enabled = True

        self._updateParametersCurrentPreset(self.presets[presetId])

    def createPreset(self, name):
        preset = PSDPerDepthPreset()
        preset.name = slicer.mrmlScene.GenerateUniqueName(name)

        self._updateParametersCurrentPreset(preset, False)

        # Update preset with the parameters values
        self.presetParameters.fieldsToPreset()

        self.presets[preset.id] = preset

        self.presetWidget.addItem(preset)

        self.logic.savePresets(self.presetsFilePath, self.presets)

        slicer.util.showStatusMessage("Preset Created", 2000)

    def _onCreatePresetClicked(self, state):
        errors = self.presetParameters.validateFields()
        if errors:
            slicer.util.errorDisplay("\n".join(errors), "Missing Data")
            return

        name = self.presetWidget.execCreateDialog()
        if name:
            self.createPreset(name)

    def renamePreset(self, presetId, name):
        presetName = slicer.mrmlScene.GenerateUniqueName(name)

        preset = self.presets[presetId]
        preset.name = presetName

        self.presets[presetId] = preset
        self.presetWidget.updateItem(preset)

        self.logic.savePresets(self.presetsFilePath, self.presets)

        slicer.util.showStatusMessage("Preset Renamed", 2000)

    def _onRenamePresetClicked(self, state):
        presetId = self.presetWidget.getCurrentData()

        if presetId is None:
            return

        name = self.presetWidget.execRenameDialog()

        if name:
            self.renamePreset(presetId, name)

    def _onSavePresetClicked(self, state):
        presetId = self.presetWidget.getCurrentData()

        if presetId is None:
            return

        errors = self.presetParameters.validateFields()

        if errors:
            slicer.util.errorDisplay("\n".join(errors), "Missing Data")
            return False

        self.presetParameters.fieldsToPreset()
        self.presetParameters.removeAllModifiedSpans()

        self._checkShowWarning()

        self.logic.savePresets(self.presetsFilePath, self.presets)

        slicer.util.showStatusMessage("Preset Saved", 2000)

    def deletePreset(self, presetId, path):
        self.presetWidget.removeItem(self.presets[presetId])
        del self.presets[presetId]

        # self.presetParameters.resetDefaultValues()

        self.logic.savePresets(path, self.presets)

        slicer.util.showStatusMessage("Preset Deleted", 2000)

    def _onDeletePresetClicked(self, state):
        presetId = self.presetWidget.getCurrentData()

        if presetId is None:
            return

        isAccepted = self.presetWidget.execDeleteDialog()

        if isAccepted:
            self.deletePreset(presetId, self.presetsFilePath)

    def _onExportPresetClicked(self, state):
        selectedPresets = self.presetWidget.execExportDialog(data=self.presets.values())

        if selectedPresets:
            filePath = self.presetWidget.execGetSaveFileDialog(directory=self.exportPresetsPath)

            if filePath:
                presets = {key: self.presets[key] for key in selectedPresets}
                self.logic.exportPreset(filePath, presets)

                slicer.util.showStatusMessage("Presets exported successfully.", 2000)

    def _onImportPresetClicked(self, state):
        file = self.presetWidget.execGetOpenFileDialog(directory=self.importPresetsPath)

        if file:
            importedPresets = self.logic.importPreset(file)

            selectedPresets = self.presetWidget.execImportDialog(data=importedPresets.values())

            if selectedPresets:
                conflictPresets = []
                newPresets = []

                for presetId in selectedPresets:
                    if presetId in self.presets:
                        conflictPresets.append(presetId)
                    else:
                        newPresets.append(presetId)

                if conflictPresets:
                    conflicts = [importedPresets[presetId] for presetId in conflictPresets]
                    message = (
                        "The following presets have already been installed on your device. "
                        "Please select the presets that you would like to replace.<br/><span style='color: yellow;'>"
                        "Obs: Please be advised that certain imported presets may possess updated values while "
                        "retaining the same ID.</span>"
                    )
                    selectedConflictPresets = self.presetWidget.execConflictDialog(
                        title="Import Presets", data=conflicts, message=message
                    )

                    if selectedConflictPresets:
                        newPresets = newPresets + selectedConflictPresets

                if newPresets:
                    presetsToAdd = {key: importedPresets[key] for key in newPresets}
                    self.presets.update(presetsToAdd)
                    self.presetWidget.loadData(self.presets.values())

                    self.logic.savePresets(self.presetsFilePath, self.presets)

                slicer.util.showStatusMessage("Presets imported successfully.", 2000)

    def _checkShowWarning(self):
        if self.presetParameters.isModified():
            self.warningLabel.show()
        else:
            self.warningLabel.hide()

    def onApply(self, newTable):
        def ensureTableViewSanity(x_range, y_range, logx_state):
            while self.runsanityEnforce != 1:
                if (
                    not self.presetParameters.logXAxisCheckBox
                ):  # if the widgets have been disposed, the thread shouldn't be alive
                    self.runsanityEnforce = 1
                if self.runsanityEnforce < 0:
                    if self.logic.associatedView:
                        if self.logic.associatedView.widget:
                            # If the view got closed, associatedView is not valid
                            if (
                                self.logic.associatedView
                                in slicer.modules.AppContextInstance.imageLogDataLogic.imageLogViewList
                            ):
                                # Enforcing logx checkboxes synchronization between the module and the view
                                viewCheckBoxChecked = (
                                    self.logic.associatedView.widget.getPlot()
                                    .get_plot_item()
                                    .ctrl.logXCheck.isChecked()
                                )
                                moduleCheckBoxChecked = self.presetParameters.logXAxisCheckBox.isChecked()
                                if viewCheckBoxChecked != moduleCheckBoxChecked:
                                    self.logic.associatedView.widget.getPlot().setUpdateRangesFlag(True)  # reset scale
                                    self.logic.associatedView.widget.getPlot().blockSignals(True)
                                    self.logic.associatedView.widget.getPlot().get_plot_item().ctrl.logXCheck.setChecked(
                                        self.presetParameters.logXAxisCheckBox.isChecked()
                                    )
                                    self.logic.associatedView.widget.getPlot().blockSignals(True)
                                    self.logic.associatedView.widget.getPlot().setUpdateRangesFlag(False)
                                    time.sleep(0.1)
                                    continue

                                if not x_range:
                                    time.sleep(0.1)
                                    continue

                                # Enforce the view's ranges to be the same as stored at sanityEnforce thread launch
                                # After met, self.runsanityEnforce => 0 - the thread stops checking anything, til next launch
                                plot_item = self.logic.associatedView.widget.getPlot().get_plot_item()
                                view_box = plot_item.getViewBox()
                                actual_x_range, actual_y_range = view_box.viewRange()
                                if (
                                    not np.isclose(actual_x_range, x_range).any()
                                    or not np.isclose(actual_y_range, y_range).any()
                                ):
                                    self.runsanityEnforce = -1
                                    self.logic.associatedView.widget.getPlot().get_plot_item().blockSignals(True)
                                    self.logic.associatedView.widget.getPlot().get_plot_item().setXRange(
                                        x_range[0], x_range[1]
                                    )
                                    self.logic.associatedView.widget.getPlot().get_plot_item().setYRange(
                                        y_range[0], y_range[1]
                                    )
                                    self.logic.associatedView.widget.getPlot().get_plot_item().blockSignals(False)
                                else:
                                    self.runsanityEnforce = 0
                time.sleep(0.1)

        x_range = None
        y_range = None
        logx_state = None
        if self.logic.associatedView and self.logic.associatedView.widget:
            plot_item = self.logic.associatedView.widget.getPlot().get_plot_item()
            view_box = plot_item.getViewBox()
            x_range, y_range = view_box.viewRange()
            logx_state = self.logic.associatedView.widget.getPlot().get_plot_item().ctrl.logXCheck.isChecked()

        self.progressBar.setValue(4)
        self.progressBar.show()

        if self.logic.associatedView and self.logic.associatedView.widget:
            self.logic.associatedView.widget.getPlot().setUpdateRangesFlag(False)

        priorAssociatedView = self.logic.associatedView

        if newTable:
            self.outputPrefixLineEdit.text = slicer.mrmlScene.GenerateUniqueName(self.outputPrefixLineEdit.text)

        try:
            self.logic.apply(
                inputNode=self.inputSelector.currentNode(),
                depthHop=self.presetParameters.depthIntervalSpinBox.value,
                nbins=self.presetParameters.nbinsSpinBox.value,
                tableName=self.outputPrefixLineEdit.text,
                logXScale=self.presetParameters.internalBinningLogCheckBox.isChecked(),
                smooth=self.presetParameters.smoothOn.isChecked(),
                smoothAmount=self.presetParameters.smoothAmountSlider.value,
                progressBar=self.progressBar,
            )
        except ValueError:
            slicer.util.errorDisplay(
                f"An issue occurred during execution. Check if '{self.inputSelector.currentNode().GetName()}' table has enough data and if its correct."
            )
            self.progressBar.hide()

        # Wait until the associated view's widget is available...
        self.waitForViewWidget(self.logic.associatedView, timeout_seconds=10)
        # ... then set callback to update self.presetParameters.logXAxisCheckBox ...
        self.logic.associatedView.widget.getPlot().get_plot_item().ctrl.logXCheck.toggled.connect(
            self.presetParameters.logXAxisCheckBox.setChecked
        )
        # ... and callbacks at table view updates on ranges, to renew the ranges enforced by the tableViewsanityEnforcer
        self.logic.associatedView.widget.getPlot().signal_x_range_changed.connect(self.onTableViewRangeUpdate)
        self.logic.associatedView.widget.getPlot().signal_y_range_changed.connect(self.onTableViewRangeUpdate)

        # Workaround: For some reason, the previous view x axis is reverted to linear when we Create New
        if newTable:
            priorAssociatedView.widget.getPlot().get_plot_item().ctrl.logXCheck.setChecked(
                self.presetParameters.logXAxisCheckBox.isChecked()
            )

        if not self.tableViewsanityEnforcer or not self.tableViewsanityEnforcer.is_alive():
            self.runsanityEnforce = -1
            self.tableViewsanityEnforcer = Thread(
                target=ensureTableViewSanity, args=(x_range, y_range, logx_state), daemon=True
            )
            self.tableViewsanityEnforcer.start()

    def onApplyButtonClicked(self):
        self.onApply(newTable=False)

    def onApplyToNewTable(self):
        self.onApply(newTable=True)

    # Callback from histogram_in_depth_view_widget
    def onTableViewRangeUpdate(self):
        if self.logic and self.logic.associatedView and self.logic.associatedView.widget:
            plot_item = self.logic.associatedView.widget.getPlot().get_plot_item()
            logx_state = plot_item.ctrl.logXCheck.isChecked()
            if self.presetParameters.logXAxisCheckBox.isChecked() != logx_state:
                plot_item.ctrl.logXCheck.setChecked(self.presetParameters.logXAxisCheckBox.isChecked())

    def defaultDepthIntervalM(self):
        # We could return for example, 1/20 of the depth range, but for now we just set to 1.0
        # - or to the vertical voxel size if it's bigger than 1.0
        node = self.inputSelector.currentNode()
        if node:
            voxelVerticalM = node.GetSpacing()[2] / 1000.0
            return voxelVerticalM if voxelVerticalM > 1.0 else 1.0
        else:
            return 1.0

    def tryAddNodeToNewView(self, node):
        # Check if the node is being visualized in a view. If not, open it in a new view
        viewIndex = -1
        for c, vcw in enumerate(slicer.modules.AppContextInstance.imageLogDataLogic.viewControllerWidgets):
            if (
                node
                == slicer.modules.AppContextInstance.imageLogDataLogic.viewControllerWidget_PrimaryNodeComboBox(
                    c
                ).currentNode()
            ):
                viewIndex = c
                break
        if viewIndex == -1:
            try:
                slicer.modules.AppContextInstance.imageLogDataLogic.addView(node)
            except Exception as e:
                logging.error(f"Error occurred while adding node to new view: {e}")

    def onInputNodeChanged(self):
        node = self.inputSelector.currentNode()
        if node is not None:
            self.tryAddNodeToNewView(node)
            self.presetParameters.depthIntervalSpinBox.blockSignals(True)
            self.presetParameters.depthIntervalSpinBox.setValue(
                self.constraintDepthInterval(self.defaultDepthIntervalM())
            )
            self.presetParameters.depthIntervalSpinBox.blockSignals(False)

        try:
            if node is not None:
                self.outputPrefixLineEdit.text = f"{node.GetName()}_PSDPerDepth"
            else:
                self.outputPrefixLineEdit.text = ""
            self.checkApplyButtonsState()
        except Exception as e:
            logging.error(f"")

    def tryApply(self):
        node = self.inputSelector.currentNode()
        if node is not None:
            self.onApplyButtonClicked()

    def onSpinBoxChange(self):
        node = self.inputSelector.currentNode()
        if node is not None:
            self.tryApply()

    # Between the voxel size in Z and the depth range of the image (both in meters)
    def constraintDepthInterval(self, value):
        node = self.inputSelector.currentNode()
        if node is not None:
            spacingZM = node.GetSpacing()[2] / 1000.0
            # 0.999 to avoid precision issues with the limits
            return min(max(value, 10 * spacingZM), 0.999 * spacingZM * node.GetImageData().GetDimensions()[2])
        else:
            return value

    def onDepthIntervalsChanged(self, value):
        node = self.inputSelector.currentNode()
        if node is not None:
            self.presetParameters.depthIntervalSpinBox.blockSignals(True)
            self.presetParameters.depthIntervalSpinBox.setValue(self.constraintDepthInterval(value))
            self.presetParameters.depthIntervalSpinBox.blockSignals(False)
            self.tryApply()

    def onLogXAxisCheckBoxChange(self):
        if self.logic.associatedView:
            self.logic.associatedView.widget.getPlot().get_plot_item().setLogMode(
                x=self.presetParameters.logXAxisCheckBox.isChecked(), y=False
            )
            # self.tryApply()

    def onSmoothOnChange(self):
        self.tryApply()

    def onSmoothnessSliderReleased(self):
        self.tryApply()

    def onInternalBinningLogCheckBoxChange(self):
        self.tryApply()

    def checkApplyButtonsState(self):
        self.applyButton.setEnabled(False)
        self.applyNewButton.setEnabled(False)

        if self.inputSelector.currentNode() is None:
            return

        if self.outputPrefixLineEdit.text.strip() == "":
            return

        self.applyButton.setEnabled(True)
        self.applyNewButton.setEnabled(True)

    def onReload(self):
        importlib.reload(sys.modules["ImageLogDataLib.viewwidgets.histogram_in_depth_view_widget"])
        importlib.reload(sys.modules["Plots.HistogramInDepthPlot.HistogramInDepthPlotWidgetModel"])
        importlib.reload(sys.modules["Test.PSDPerDepthTest"])
        super().onReload()
        self.logic = PSDPerDepthLogic(widget=self)
        self.checkApplyButtonsState()

    def initParameterNode(self):
        self.parameterNode = self.logic.getParameterNode()
        self.fillParameterNodeFromUI()

    def initObservers(self):
        if len(self._observerTags) != 0:
            self.removeObservers()

        self._observerTags[slicer.mrmlScene] = [
            slicer.mrmlScene.AddObserver(slicer.mrmlScene.StartSaveEvent, self.onSaveSceneStart),
            slicer.mrmlScene.AddObserver(slicer.mrmlScene.EndImportEvent, self.onImportSceneEnd),
        ]

    def removeObservers(self):
        for handler in self._observerTags:
            if type(self._observerTags[handler]) == list:
                for tag in self._observerTags[handler]:
                    handler.RemoveObserver(tag)
            else:
                handler.RemoveObserver(self._observerTags[handler])

        self._observerTags = {}

    def enter(self):
        super().enter()
        self.initObservers()

        self.onImportSceneEnd(None, None)  # Update UI according to parameterNode value

    def exit(self):
        self.removeObservers()
        self.parameterNode = None
        self.runsanityEnforce = 1  # Exit sanity check thread loop...
        if self.tableViewsanityEnforcer:
            self.tableViewsanityEnforcer.join()  # ... and wait for thread to finish

    def cleanup(self):
        super().cleanup()
        self.removeObservers()
        self.parameterNode = None
        self.runsanityEnforce = 1  # Exit sanity check thread loop...
        if self.tableViewsanityEnforcer:
            self.tableViewsanityEnforcer.join()  # ... and wait for thread to finish
        if self.logic:
            self.logic.cleanup()
            self.logic.deleteLater()
            self.logic = None


class PSDPerDepthLogic(LTracePluginLogic):
    def __init__(self, parent=None, widget=None):
        LTracePluginLogic.__init__(self, parent)
        self.associatedView = None
        self.widget = widget

    def setMetadataFromParameters(self, tableNode):
        Metadata(tableNode)["nbins"] = str(self.widget.presetParameters.nbinsSpinBox.value)
        Metadata(tableNode)["depth_intervals"] = str(self.widget.presetParameters.depthIntervalSpinBox.value)
        Metadata(tableNode)["source_psd_node_name"] = str(self.widget.inputSelector.currentNode().GetName())

    def apply(
        self,
        inputNode,
        depthHop,
        nbins,
        tableName,
        logXScale,  # NOTE - This is the scale of the calculations, not the scale of the visualization
        smooth=True,
        smoothAmount=1.0,
        progressBar=None,
    ):

        if not inputNode:
            return

        originalDepths, _ = arrayPartsFromNode(inputNode)
        self.depthHop = depthHop

        progressBar.setValue(10)

        groupedDepths = self._createGroupedDepths(originalDepths, depthHop)

        progressBar.setValue(30)

        if not len(groupedDepths):
            logging.warning(
                f"Warning: An issue occurred with the '{inputNode.GetName()}' input during the grouping by depth operation. Please verify the label map's data integrity and if it is correct."
            )
            raise ValueError("Expected non-empty DataFrame, but got an empty one.")

        originalDepths, ltData = arrayPartsFromNode(inputNode)

        progressBar.setValue(60)

        pixToMM = inputNode.GetSpacing()[0]

        _, psdDF = self._createPSDTable(
            originalDepths,
            groupedDepths,
            ltData,
            nbins,
            pixToMM,
            logXScale,
            smooth,
            smoothAmount,
        )

        progressBar.setValue(90)

        tableNode = tryGetNode(tableName)
        newTableNode = tableNode is None

        if newTableNode:
            tableNode = dataFrameToTableNode(psdDF)
            tableNode.SetAttribute(TableType.name(), TableType.HISTOGRAM_IN_DEPTH.value)
            tableNode.SetAttribute(TableDataTypeAttribute.name(), TableDataTypeAttribute.IMAGE_2D.value)
            tableNode.SetAttribute(TableDataOrientation.name(), TableDataOrientation.ROW.value)
            tableNode.SetAttribute(HistogramGraphType.name(), HistogramGraphType.MULTI_HISTOGRAM.value)
            tableNode.SetAttribute(PlotScaleXAxisAttribute.name(), PlotScaleXAxisAttribute.LINEAR_SCALE.value)
            tableNode.SetUseFirstColumnAsRowHeader(True)
            tableNode.SetUseColumnNameAsColumnHeader(True)
            tableNode.SetAttribute("Property", "Pore size (mm)")  # This is mandatory...
            tableNode.SetName(tableName)
        else:
            dataFrameToTableNode(psdDF, tableNode, replace=True)

        self.setMetadataFromParameters(tableNode)

        copy_subject_hierarchy_item_parent(inputNode, tableNode)

        isOpenInView = False
        for c, vcw in enumerate(slicer.modules.AppContextInstance.imageLogDataLogic.viewControllerWidgets):
            if (
                tableNode
                == slicer.modules.AppContextInstance.imageLogDataLogic.viewControllerWidget_PrimaryNodeComboBox(
                    c
                ).currentNode()
            ):
                self.associatedView = slicer.modules.AppContextInstance.imageLogDataLogic.imageLogViewList[c]
                isOpenInView = True
                break

        if not isOpenInView:
            self.widget.tryAddNodeToNewView(tableNode)
            time.sleep(0.2)
            self.associatedView = slicer.modules.AppContextInstance.imageLogDataLogic.imageLogViewList[-1]

        progressBar.setValue(100)

    def _createGroupedDepths(self, originaldepths, depthHop):
        startDepth = originaldepths[0]
        endDepth = startDepth + depthHop
        depthsList = []
        while startDepth <= originaldepths[-1]:
            depthsList.append(startDepth)
            startDepth = endDepth
            endDepth = startDepth + depthHop

        return depthsList

    def _createPSDTable(
        self,
        originaldepths,
        groupedDepths,
        im,
        nbins,
        pixToMM,
        logXScale,
        smooth,
        smoothAmount,
    ):

        input_df = pd.DataFrame(im)
        input_df.insert(0, "depth (m)", originaldepths)

        psdList = []
        binCentersList = []  # in pixels

        startDepth = groupedDepths[0]
        endDepth = startDepth + self.depthHop
        minBin = 1000000
        maxBin = 0
        for index, depth in enumerate(groupedDepths):
            sub_df = input_df[(input_df["depth (m)"] >= startDepth) & (input_df["depth (m)"] < endDepth)]
            binCenters, psd = self._psd(np.array(sub_df.iloc[:, 1:]), nbins, logXScale)
            psdList.append(psd)
            binCentersList.append(binCenters)
            minBin = min(minBin, min(binCenters))
            maxBin = max(maxBin, max(binCenters))
            startDepth = endDepth
            endDepth = startDepth + self.depthHop

        # Every PSD has a different binning, so we interpolate them to a common xGrid

        maxPoreSizeMM = 1000.0
        minPoreSizeMM = 6.0
        if not logXScale:
            maxBin = min(
                maxBin, maxPoreSizeMM / pixToMM
            )  # both /pixToMM because we are in pixels yet. Afterwards we'll xGrid *= pixToMM
            minBin = max(minBin, minPoreSizeMM / pixToMM)
            nbinsXGrid = 2 * (int(maxBin - minBin) + 1)
            xGrid = np.linspace(minBin, maxBin, nbinsXGrid)
        else:
            #  We calculated the psds in log scale to improve resolution at the smaller range,
            # and also will create the commom xGrid at positions exponentially spaced.
            # But note that we'll express xGrid in base 10
            maxBinLinear = min(
                10**maxBin, maxPoreSizeMM / pixToMM
            )  # both /pixToMM because we are in pixels yet. Afterwards we'll xGrid *= pixToMM
            minBinLinear = max(10**minBin, minPoreSizeMM / pixToMM)
            range = maxBin - minBin
            linearRange = maxBinLinear - minBinLinear

            # (logspace already returns the values in normal scale (although start and stop params are in log))
            xGrid1 = np.logspace(
                minBin, maxBin - range / 4, int(4 * linearRange) + 1, endpoint=False
            )  # first portion log-spaced (more points)
            xGrid2 = np.linspace(
                10 ** (maxBin - range / 4), maxBinLinear, int(linearRange)
            )  # last portion linearly spaced (few, but not that few points)
            xGrid = np.concatenate((xGrid1, xGrid2))
            # let's not forget the binCenters
            binCentersList = [10**binCenters for binCenters in binCentersList]

        psdList_newGrid = []
        for i, psds in enumerate(psdList):
            if not smooth:
                psdList_newGrid.append(np.interp(xGrid, binCentersList[i], psds, left=0, right=0))
            else:
                linearInterp = np.interp(xGrid, binCentersList[i], psds, left=0, right=0)
                result = savgol_filter(linearInterp, window_length=max(3, int(pixToMM * smoothAmount * 2)), polyorder=2)
                result = [0 if y < 0 else y for y in result]  # remove negative values of result that savgol overshoots
                psdList_newGrid.append(result)

        xGrid *= pixToMM
        psdDF_newGrid = pd.DataFrame(psdList_newGrid, index=groupedDepths, columns=xGrid)
        psdDF_newGrid.columns.name = "Pore size (mm)"
        # Not sure why we have to insert another depths column, but histogram_in_depth_view.py seems to expect it
        psdDF_newGrid.insert(0, "DEPTH(m)", [x * 1000 for x in psdDF_newGrid.index.tolist()])

        return xGrid, psdDF_newGrid

    def _psd(self, data, nbins, logXScale):
        psd = ps.metrics.pore_size_distribution(data, log=logXScale, bins=nbins)
        return psd.bin_centers, psd.pdf

    def _createGroupedTable(self, df, depthRange, measurement):
        groupedData = []
        startDepth = df["depth (m)"].iloc[0]
        endDepth = startDepth + depthRange
        depthsList = []

        while startDepth <= df["depth (m)"].iloc[-1]:
            group = df[(df["depth (m)"] >= startDepth) & (df["depth (m)"] < endDepth)]

            measurementValues = group[measurement].values
            groupedData.append(measurementValues)

            startDepth = endDepth
            endDepth = startDepth + depthRange

            depthsList.append(startDepth)

        groupedDF = pd.DataFrame(groupedData)
        groupedDF.index = depthsList

        return groupedDF

    def getParameterNode(self):
        return PSDPerDepthParameterNode(super().getParameterNode())

    def cleanup(self):
        self.widget = None

    def exportPreset(self, filePath, presets):
        try:
            presetsData = {id: vars(preset) for id, preset in presets.items()}

            with open(filePath, "w") as f:
                json.dump(presetsData, f, indent=2)
        except Exception as e:
            logging.error(repr(e))
            slicer.util.errorDisplay("An error occurred while exporting presets.", "Export Error")

    def importPreset(self, filePath):
        try:
            with open(filePath, "r") as f:
                presetsData = json.load(f)

            presets = {key: PSDPerDepthPreset(**value) for key, value in presetsData.items()}

            return presets
        except Exception as e:
            logging.error(repr(e))
            slicer.util.errorDisplay("An error occurred while importing presets.", "Import Error")

    def getPresets(self, filePath):
        try:
            if os.path.isfile(filePath):
                with open(filePath, "r") as f:
                    presetsData = json.load(f)
            else:
                presetsData = {}

                with open(filePath, "w") as f:
                    json.dump(presetsData, f, indent=2)

            presets = {id: PSDPerDepthPreset(**preset) for id, preset in presetsData.items()}

            return presets
        except Exception as e:
            logging.error(repr(e))
            slicer.util.errorDisplay("An error occurred while getting presets.", "Error")

    def savePresets(self, filePath, presets):
        try:
            presetsData = {id: vars(preset) for id, preset in presets.items()}

            with open(filePath, "w") as f:
                json.dump(presetsData, f, indent=2)
        except Exception as e:
            logging.error(repr(e))
            slicer.util.errorDisplay("An error occurred while saving presets.", "Error")
