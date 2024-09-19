from functools import partial
import importlib
import json
import logging
import os
import uuid

import time
from pathlib import Path

import logging
import matplotlib.colors as mcolors

import numpy as np
import pandas as pd


import qt
import slicer
import vtk
import ctk

from slicer.util import VTKObservationMixin

from ltrace.algorithms.partition import InvalidSegmentError
from ltrace.slicer.node_attributes import Tag
from ltrace.slicer import ui, helpers, widgets
from ltrace.slicer.helpers import (
    tryGetNode,
    generateName,
    rand_cmap,
    extractLabels,
    createOutput,
    makeTemporaryNodePermanent,
    getCountForLabels,
    themeIsDark,
    isNodeImage2D,
)
from ltrace.slicer.ui import numberParam, fixedRangeNumberParam
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widgets import BaseSettingsWidget
from ltrace.slicer_utils import (
    LTracePlugin,
    LTracePluginWidget,
    LTracePluginLogic,
    dataFrameToTableNode,
)
from ltrace.algorithms.partition import runPartitioning, ResultInfo
from Output import SegmentInspectorVariablesOutput as SegmentInspectorVariablesOutputClass
from Output.SegmentInspectorVariablesOutput import SegmentInspectorVariablesOutput
from Output.BasicPetrophysicsOutput import generate_basic_petrophysics_output
from recordtype import recordtype  # mutable

from ltrace.slicer.throat_analysis.throat_analysis_generator import ThroatAnalysisGenerator

# Checks if closed source code is available
try:
    from Test.SegmentInspectorTest import SegmentInspectorTest
except ImportError:
    SegmentInspectorTest = None  # tests not deployed to final version or closed source


SegmentLabel = recordtype("SegmentLabel", ["name", "color", "id", "value", ("property", "Solid")])

TAB_COLORS = [name for name in mcolors.TABLEAU_COLORS]


class SegmentInspector(LTracePlugin):
    SETTING_KEY = "SegmentInspector"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Segment Inspector"
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]  # replace with "Firstname Lastname (Organization)"
        self.parent.helpText = SegmentInspector.help()
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = ""  # replace with organization, grant and thanks.

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


#
# SegmentInspectorWidget
#
class SegmentInspectorWidget(LTracePluginWidget, VTKObservationMixin):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

        self.modeSelectors = {}
        self.modeWidgets = {}

        self.selectedProducts = set(["all"])

        self.currentMode = widgets.SingleShotInputWidget.MODE_NAME

        self.logic = SegmentInspectorLogic()

        self.filterUpdateThread = None
        self.blockVisibilityChanges = False
        self.supports3D = True

    def onReload(self) -> None:
        LTracePluginWidget.onReload(self)
        importlib.reload(helpers)
        importlib.reload(SegmentInspectorVariablesOutputClass)
        importlib.reload(widgets)
        importlib.reload(ui)

    def onSceneEndClose(self, caller, event):
        try:
            self.modeWidgets[widgets.SingleShotInputWidget.MODE_NAME].fullResetUI()
        except Exception as e:
            import traceback

            traceback.print_exc()
            pass

    def setup(self):
        LTracePluginWidget.setup(self)

        self.MODES = [widgets.SingleShotInputWidget, widgets.BatchInputWidget]

        self.layout.addWidget(self._setupInputsSection())
        self.layout.addWidget(self._setupSettingsSection())
        self.layout.addWidget(self._setupOutputSection())
        self.layout.addWidget(self._setupApplySection())

        self.modeSelectors[widgets.SingleShotInputWidget.MODE_NAME].setChecked(True)

        # Add vertical spacer
        self.layout.addStretch(1)

        # Setup handlers
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

    def _setupInputsSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Inputs"
        layout = qt.QVBoxLayout(widget)

        optionsLayout = qt.QHBoxLayout()
        self.optionsStack = qt.QStackedWidget()

        btn1 = qt.QRadioButton(widgets.SingleShotInputWidget.MODE_NAME)
        self.modeSelectors[widgets.SingleShotInputWidget.MODE_NAME] = btn1
        optionsLayout.addWidget(btn1)
        btn1.toggled.connect(self._onModeClicked)
        panel1 = widgets.SingleShotInputWidget()
        panel1.onMainSelectedSignal.connect(self._onInputSelected)
        panel1.onReferenceSelectedSignal.connect(self._onReferenceSelected)
        self.modeWidgets[widgets.SingleShotInputWidget.MODE_NAME] = panel1
        self.optionsStack.addWidget(self.modeWidgets[widgets.SingleShotInputWidget.MODE_NAME])

        btn2 = qt.QRadioButton(widgets.BatchInputWidget.MODE_NAME)
        self.modeSelectors[widgets.BatchInputWidget.MODE_NAME] = btn2
        optionsLayout.addWidget(btn2)
        btn2.toggled.connect(self._onModeClicked)
        panel2 = widgets.BatchInputWidget(settingKey="SegmentInspector")
        panel2.onDirSelected = self._onInputSelected
        self.modeWidgets[widgets.BatchInputWidget.MODE_NAME] = panel2
        self.optionsStack.addWidget(self.modeWidgets[widgets.BatchInputWidget.MODE_NAME])

        layout.addLayout(optionsLayout)
        layout.addWidget(self.optionsStack)

        return widget

    def _setupSettingsSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Parameters"

        formLayout = qt.QFormLayout(widget)

        self.methodSelector = ui.StackedSelector(text="Methods:")
        oswsw = OSWatershedSettingsWidget(
            voxelSizeGetter=lambda: self.modeWidgets[self.currentMode].inputVoxelSize,
            onSelect=lambda: self.modeWidgets[self.currentMode].segmentsOn(),
        )
        self.methodSelector.addWidget(oswsw)
        self.methodSelector.addWidget(
            IslandsSettingsWidget(
                voxelSizeGetter=lambda: self.modeWidgets[self.currentMode].inputVoxelSize,
                onSelect=lambda: self.modeWidgets[self.currentMode].segmentsOn(),
            )
        )
        if self.supports3D:
            self.methodSelector.addWidget(
                MedialSurfaceSettingsWidget(
                    voxelSizeGetter=lambda: self.modeWidgets[self.currentMode].inputVoxelSize,
                    onSelect=lambda: self.modeWidgets[self.currentMode].segmentsOn(),
                )
            )
        self.methodSelector.addWidget(
            DeepWatershedSettingsWidget(
                voxelSizeGetter=lambda: self.modeWidgets[self.currentMode].inputVoxelSize,
                onSelect=lambda: self.modeWidgets[self.currentMode].segmentsOn(),
            )
        )
        self.methodSelector.addWidget(
            MineralogySettingsWidget(onSelect=lambda: self.modeWidgets[self.currentMode].segmentsOff())
        )
        self.methodSelector.addWidget(
            BasePetrophysicsSettingsWidget(onSelect=lambda: self.modeWidgets[self.currentMode].segmentsOff())
        )
        self.methodSelector.objectName = "Methods Selector"
        self.methodSelector.selector.objectName = "Methods ComboBox"

        formLayout.addRow(self.methodSelector)

        return widget

    def _setupOutputSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Output"

        # TODO enable when paths are created for enter pre partitoned data on input
        # def onOptionToggled(state, option="all"):
        #     if state == qt.Qt.Checked:
        #         if option == "all":
        #             self.selectedProducts = set(["partitions", "report"])
        #         elif "all" in self.selectedProducts:
        #             self.selectedProducts = set(["partitions", "report"])
        #         else:
        #             self.selectedProducts.add(option)
        #     else:
        #         if option == "all":
        #             self.selectedProducts = set([])
        #         elif "all" in self.selectedProducts:
        #             self.selectedProducts = set(["partitions", "report"])
        #             self.selectedProducts.remove(option)
        #         else:
        #             self.selectedProducts.remove(option)

        # optionsBox = qt.QHBoxLayout()

        # partOption = qt.QCheckBox("Partitioning")
        # partOption.setChecked(True)
        # partOption.stateChanged.connect(partial(onOptionToggled, option="partitions"))

        # characOption = qt.QCheckBox("Characterization Reports")
        # characOption.setChecked(True)
        # characOption.stateChanged.connect(partial(onOptionToggled, option="report"))

        # optionsBox.addWidget(partOption)
        # optionsBox.addWidget(characOption)
        # optionsBox.addStretch(1)

        self.outputPrefix = qt.QLineEdit()

        self.outputFormLayout = qt.QFormLayout(widget)
        # self.outputFormLayout.addRow(optionsBox)
        self.outputFormLayout.addRow("Output Prefix: ", self.outputPrefix)
        self.outputPrefix.setToolTip("Type the prefix text to be used as the name of the output nodes/data.")
        self.outputPrefix.objectName = "Output Prefix Line Edit"
        self.outputPrefix.textChanged.connect(self.__on_output_prefix_changed)

        return widget

    def _setupApplySection(self):
        widget = qt.QWidget()
        vlayout = qt.QVBoxLayout(widget)

        self.applyButton = ui.ApplyButton(
            onClick=self._onApplyClicked, tooltip="Run pore analysis on input data limited by ROI", enabled=False
        )

        self.applyButton.objectName = "Apply Button"

        self.logic.inspectorProcessStarted.connect(lambda: self.applyButton.setEnabled(False))
        self.logic.inspector_process_finished.connect(lambda: self.applyButton.setEnabled(True))

        self.progressBar = LocalProgressBar()
        self.logic.progressBar = self.progressBar

        hlayout = qt.QHBoxLayout()
        hlayout.addWidget(self.applyButton)
        hlayout.setContentsMargins(0, 8, 0, 8)

        vlayout.addLayout(hlayout)
        vlayout.addWidget(self.progressBar)

        return widget

    def _onModeClicked(self):
        for index, mode in enumerate(self.MODES):
            try:
                if self.modeSelectors[mode.MODE_NAME].isChecked():
                    self.currentMode = mode.MODE_NAME
                    self.optionsStack.setCurrentIndex(index)

                    for i in range(self.methodSelector.count()):
                        self.methodSelector.widget(i).onModeChanged(self.currentMode)

                    break
            except KeyError as ke:
                # happens only during initialization
                pass

    def enter(self) -> None:
        super().enter()

    def exit(self):
        pass

    def cleanup(self):
        super().cleanup()
        self.removeObservers()
        del self.logic

    def _onInputSelected(self, node):
        self.__update_apply_button_state()

        for i in range(self.methodSelector.count()):
            self.methodSelector.widget(i).onSegmentationChanged(node)

        if node is None:
            return

        self.outputPrefix.setText(f"{node.GetName()}_Inspector")

    def _onReferenceSelected(self, node):
        self.__update_apply_button_state()

        for i in range(self.methodSelector.count()):
            self.methodSelector.widget(i).onReferenceChanged(node, False)

    def _callSingleShot(self):
        modeWidget: widgets.SingleShotInputWidget = self.modeWidgets[self.currentMode]

        prefix = self.outputPrefix.text + "_{type}"

        products = list(self.selectedProducts)

        referenceVolumeNode = modeWidget.referenceInput.currentNode()  ## Can be null

        segmentationNode = modeWidget.mainInput.currentNode()
        # doing this with an if because when setting the visibility it messes with the imagelog viewer
        if not self.blockVisibilityChanges:
            segmentationNode.GetDisplayNode().SetVisibility(False)

        roiSegNode = modeWidget.soiInput.currentNode()
        if roiSegNode and not self.blockVisibilityChanges:
            roiSegNode.GetDisplayNode().SetVisibility(False)

        try:
            params = self.methodSelector.currentWidget().toJson()

            cli = self.logic.runSelectedMethod(
                segmentationNode,
                segments=modeWidget.getSelectedSegments(),
                outputPrefix=prefix,
                params=params,
                products=products,
                referenceNode=referenceVolumeNode,
                soiNode=roiSegNode,
            )

            self.progressBar.setCommandLineModuleNode(cli)
        except InvalidSegmentError as e:
            slicer.util.warningDisplay(str(e))
        except AttributeError as ve:
            modeWidget.checkSelection()
        except Exception:
            import traceback

            traceback.print_exc()
            slicer.util.errorDisplay(
                "Failed to execute the selected method. Check the terminal or the erro log for more information."
            )

    def _callBatchRun(self):
        modeWidget: widgets.BatchInputWidget = self.modeWidgets[self.currentMode]

        batchDir = modeWidget.ioFileInputLineEdit.currentPath
        helpers.save_path(modeWidget.ioFileInputLineEdit)
        outputPrefix = self.outputPrefix.text + "_{type}"
        segTag = modeWidget.ioBatchSegTagPattern.text
        roiTag = modeWidget.ioBatchROITagPattern.text
        valTag = modeWidget.ioBatchValTagPattern.text
        labelTag = modeWidget.ioBatchLabelPattern.text

        for cli in self.logic.runBatchpartitioning(
            batchDir,
            outputPrefix,
            segTag=segTag,
            roiTag=roiTag,
            valuesTag=valTag,
            labelTag=labelTag,
        ):
            self.progressBar.setCommandLineModuleNode(cli)
            while cli.IsBusy():
                time.sleep(0.200)
                slicer.app.processEvents()

    def _onApplyClicked(self):
        if not self.methodSelector.currentWidget().validatePrerequisites():
            return

        if self.currentMode == widgets.SingleShotInputWidget.MODE_NAME:
            self._callSingleShot()

        elif self.currentMode == widgets.BatchInputWidget.MODE_NAME:
            self._callBatchRun()
        self.runningMode = self.currentMode

    def __update_apply_button_state(self):
        valid_output_prefix = self.outputPrefix.text.replace(" ", "") != ""
        valid_input_config = False
        input_mode_widget = self.modeWidgets[self.currentMode]

        if self.currentMode == widgets.SingleShotInputWidget.MODE_NAME:
            valid_input_config = (
                input_mode_widget.mainInput.currentNode() is not None
                and input_mode_widget.referenceInput.currentNode() is not None
            )
        elif self.currentMode == widgets.BatchInputWidget.MODE_NAME:
            valid_input_config = input_mode_widget.ioFileInputLineEdit.currentPath != ""

        self.applyButton.enabled = valid_output_prefix and valid_input_config

    def __on_output_prefix_changed(self, text):
        modeWidget: widgets.SingleShotInputWidget = self.modeWidgets[self.currentMode]
        segmentationNode = modeWidget.mainInput.currentNode()
        if segmentationNode is not None and text.replace(" ", "") == "":
            self.outputPrefix.setText(segmentationNode.GetName() + "_Inspector")

        self.__update_apply_button_state()


class BasePetrophysicsSettingsWidget(BaseSettingsWidget):
    METHOD = "basic_petrophysics"
    DISPLAY_NAME = "Basic Petrophysics"

    def __init__(self, onSelect=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.onSelect = onSelect or (lambda: None)
        self.setup()

    def setup(self):
        formLayout = qt.QFormLayout(self)
        # self.includeBackgroundCheckBox = qt.QCheckBox("Include Background")
        # self.includeBackgroundCheckBox.setToolTip(
        #     "Select this to include the background information in the output table."
        # )
        # self.includeBackgroundCheckBox.setChecked(False)
        # self.includeBackgroundCheckBox.objectName = "Include Background CheckBox"
        # formLayout.addRow(self.includeBackgroundCheckBox)

    def toJson(self):
        return {
            "method": self.METHOD,
        }

    def validatePrerequisites(self):
        return True


class MineralogySettingsWidget(BaseSettingsWidget):
    METHOD = "mineralogy"
    DISPLAY_NAME = "Transition analysis"

    def __init__(self, onSelect=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.onSelect = onSelect or (lambda: None)
        self.setup()

    def setup(self):
        formLayout = qt.QFormLayout(self)
        self.includeBackgroundCheckBox = qt.QCheckBox("Include Background")
        self.includeBackgroundCheckBox.setToolTip(
            "Select this to include the background information in the output table."
        )
        self.includeBackgroundCheckBox.setChecked(False)
        self.includeBackgroundCheckBox.objectName = "Include Background CheckBox"
        formLayout.addRow(self.includeBackgroundCheckBox)

    def toJson(self):
        labelBlackList = None if self.includeBackgroundCheckBox.isChecked() else [0, "0", "Background"]
        return {
            "method": self.METHOD,
            "asPercent": True,
            "allowNaN": False,
            "allowSelfCount": False,
            "labelBlackList": labelBlackList,
        }

    def validatePrerequisites(self):
        return True


class OSWatershedSettingsWidget(BaseSettingsWidget):
    METHOD = "snow"
    DISPLAY_NAME = "Over-Segmented Watershed"

    def __init__(self, voxelSizeGetter=None, onSelect=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.showPxOnly = voxelSizeGetter == None
        self.userUnit = "px" if self.showPxOnly else "mm"
        self.voxeSizeGetter = voxelSizeGetter or (lambda: 1)

        self.onSelect = onSelect or (lambda: None)
        self.__currentReferenceNodeId = None
        self.setup()

    def setup(self):
        formLayout = qt.QFormLayout(self)

        sizeFilterBox = qt.QHBoxLayout()
        step = 1 if self.showPxOnly else 0.001
        self.sizeFilterThreshold = numberParam((0.0, 99999.0), value=0, step=step, decimals=4)
        self.sizeFilterThreshold.setToolTip(
            "Filter spurious partitions with major axis (feret_max) smaller than Size Filter value."
        )
        self.sizeFilterThreshold.objectName = "Watershed Size Filter SpinBox"
        self.sizeFilterPixelLabel = qt.QLabel("  0 px")
        sizeFilterBox.addWidget(self.sizeFilterThreshold)
        sizeFilterBox.addWidget(self.sizeFilterPixelLabel)

        self.throatWidgetsLayout = qt.QHBoxLayout()
        self.throatAnalysisCheckBox = qt.QCheckBox()
        self.throatAnalysisCheckBox.setToolTip("Select this to include the throat analysis to the report output")
        self.throatAnalysisCheckBox.setChecked(False)
        self.throatAnalysisCheckBox.objectName = "2D Throat analysis CheckBox on Watershed"

        self.throatWarningLabel = qt.QLabel("Available only for 2D Images")
        self.throatWarningLabel.setVisible(False)

        self.throatOptionLabel = qt.QLabel("2D Throat analysis (beta):")

        self.throatWidgetsLayout.addWidget(self.throatAnalysisCheckBox)
        self.throatWidgetsLayout.addSpacing(10)
        self.throatWidgetsLayout.addWidget(self.throatWarningLabel)
        self.throatWidgetsLayout.addStretch(1)

        formLayout.addRow(f"Size Filter ({self.userUnit}): ", sizeFilterBox)
        formLayout.addRow(self.throatOptionLabel, self.throatWidgetsLayout)

        # Set sizeFilterPixelLabel visibility only after parent realocation
        # to avoid widget blinking during plugin' setup.
        self.sizeFilterPixelLabel.setVisible(not self.showPxOnly)

        advancedSection = ctk.ctkCollapsibleButton()
        advancedSection.text = "Advanced"
        advancedSection.flat = True
        advancedSection.collapsed = True

        advancedFormLayout = qt.QFormLayout(advancedSection)

        smoothFactorBox = qt.QHBoxLayout()
        step = 1 if self.showPxOnly else 0.001
        self.smoothFactor = numberParam((0.0, 99999.0), value=0, step=step, decimals=4)
        self.smoothFactor.setToolTip(
            "Smooth Factor being the standard deviation of the Gaussian filter applied to distance transform. "
            "As Smooth Factor increases less partitions will be created. Use small values for more reliable results."
        )

        self.smoothFactor.objectName = "Smooth Factor SpinBox"
        self.smoothFactorPixelLabel = qt.QLabel("  0 px")
        self.smoothFactorPixelLabel = qt.QLabel("  0 px")

        smoothFactorBox.addWidget(self.smoothFactor)
        smoothFactorBox.addWidget(self.smoothFactorPixelLabel)

        minDistBox = qt.QHBoxLayout()
        self.minimumDistance = fixedRangeNumberParam(2, 30, value=5)
        self.minimumDistance.setToolTip(
            "Minimum distance separating peaks in a region of 2 * min_distance + 1 "
            "(i.e. peaks are separated by at least min_distance). To found the maximum number of partitions, "
            "use min_distance = 0."
        )
        self.minimumDistance.objectName = "Minimum Distance SpinBox"
        self.minDistPixelLabel = qt.QLabel("  0 px")
        minDistBox.addWidget(self.minimumDistance)
        minDistBox.addWidget(self.minDistPixelLabel)
        self.minDistWarning = qt.QLabel("High minimum distance values can greatly increase processing time.")
        self.minDistWarning.setStyleSheet("QLabel {color: red;}")
        self.minDistWarning.setVisible(False)

        self.orientationInput = ui.volumeInput(hasNone=True, nodeTypes=["vtkMRMLMarkupsLineNode"])
        self.orientationInput.addEnabled = False
        self.orientationInput.removeEnabled = False
        self.orientationInput.objectName = "Orientation line ComboBox"

        advancedFormLayout.addRow(f"Smooth Factor ({self.userUnit}): ", smoothFactorBox)
        advancedFormLayout.addRow("Minimum Distance: ", minDistBox)
        advancedFormLayout.addRow("Orientation Line: ", self.orientationInput)
        advancedFormLayout.addWidget(self.minDistWarning)

        formLayout.addRow(advancedSection)

        self.sizeFilterThreshold.valueChanged.connect(
            lambda v, w=self.sizeFilterPixelLabel: self._onPixelArgumentChanged(v, w)
        )
        self.smoothFactor.valueChanged.connect(
            lambda v, w=self.smoothFactorPixelLabel: self._onPixelArgumentChanged(v, w)
        )
        self.minimumDistance.valueChanged.connect(
            lambda v, w=self.minDistPixelLabel: self._onPixelArgumentChanged2(v, w)
        )

        slicer.app.processEvents(1000)
        self._onPixelArgumentChanged2(self.minimumDistance.value, self.minDistPixelLabel)

    def _onPixelArgumentChanged(self, value, labelWidget):
        voxelSize = self.voxeSizeGetter()
        pixel = int(np.round(value / voxelSize))
        labelWidget.setText(f"  {pixel} px")

    def _onPixelArgumentChanged2(self, value, labelWidget):
        voxelSize = self.voxeSizeGetter()
        unpx = np.round(value * voxelSize, decimals=5)
        if self.showPxOnly:
            labelWidget.setText(f" {int(value)} px")
        else:
            labelWidget.setText(f" {int(value)} px ({unpx} mm)")

        if value <= 6:
            color = "white" if themeIsDark() else "black"
            labelWidget.setStyleSheet(f"QLabel {{color: {color};}}")
            self.minDistWarning.setVisible(False)
        elif 6 < value < 8:
            color = "yellow" if themeIsDark() else "orange"
            labelWidget.setStyleSheet(f"QLabel {{color: {color};}}")
            self.minDistWarning.setVisible(False)
        else:
            labelWidget.setStyleSheet("QLabel {color: red;}")
            self.minDistWarning.setVisible(True)

    def toJson(self):
        minDist = self.minimumDistance.value

        return {
            "method": self.METHOD,
            "sigma": float(self.smoothFactor.value),
            "d_min_filter": float(minDist),
            "size_min_threshold": float(self.sizeFilterThreshold.value),
            "direction": self.orientationInput.currentNode(),
            "generate_throat_analysis": self.throatAnalysisCheckBox.isChecked(),
            "voxel_size": 1.0 if self.showPxOnly else None,
        }

    def fromJson(self, json):
        self.smoothFactor.value = json["sigma"]
        self.minimumDistance.value = json["d_min_filter"]
        self.sizeFilterThreshold.value = json["size_min_threshold"]
        self.orientationInput.setCurrentNode(json["direction"])
        self.throatAnalysisCheckBox.setChecked(json["generate_throat_analysis"])

    def onReferenceChanged(self, node, selected):
        self.__currentReferenceNodeId = node.GetID() if node is not None else None
        if node is None:
            return

        voxelSize = self.voxeSizeGetter()
        self.smoothFactor.value = voxelSize * 0.5
        self._onPixelArgumentChanged2(self.minimumDistance.value, self.minDistPixelLabel)

        # Enables throat option if reference image is 2D
        is_2d_image = isNodeImage2D(self.__currentReferenceNodeId)

        if not is_2d_image:
            self.smoothFactor.setRange(0.0 * voxelSize, 30.0 * voxelSize)
        else:
            self.smoothFactor.setRange(0.0, 99999.0)

        self.throatAnalysisCheckBox.setEnabled(is_2d_image)
        self.throatAnalysisCheckBox.setVisible(is_2d_image)
        self.throatOptionLabel.setVisible(is_2d_image)
        if self.throatAnalysisCheckBox.isChecked() and is_2d_image == False:
            self.throatAnalysisCheckBox.setChecked(False)

    def onModeChanged(self, mode):
        if mode == widgets.BatchInputWidget.MODE_NAME:
            self.throatWarningLabel.setVisible(True)
            self.throatAnalysisCheckBox.setEnabled(True)
            self.throatAnalysisCheckBox.setVisible(True)
            self.throatOptionLabel.setVisible(True)
        else:
            self.throatWarningLabel.setVisible(False)
            mode = isNodeImage2D(self.__currentReferenceNodeId)
            self.throatAnalysisCheckBox.setEnabled(mode)
            self.throatAnalysisCheckBox.setVisible(mode)
            self.throatOptionLabel.setVisible(mode)

    def validatePrerequisites(self):
        return True


class IslandsSettingsWidget(BaseSettingsWidget):
    METHOD = "islands"
    DISPLAY_NAME = "Islands"

    def __init__(self, voxelSizeGetter=None, onSelect=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.voxeSizeGetter = voxelSizeGetter or (lambda: 1)
        self.onSelect = onSelect or (lambda: None)

        self.setup()

    def setup(self):
        formLayout = qt.QFormLayout(self)

        sizeFilterBox = qt.QHBoxLayout()
        self.sizeFilterThreshold = numberParam((0.0, 99999.0), value=0, step=0.001, decimals=4)
        self.sizeFilterThreshold.setToolTip(
            "Filter spurious partitions with major axis (feret_max) smaller than Size Filter value."
        )
        self.sizeFilterThreshold.objectName = "Islands Size Filter SpinBox"
        self.sizeFilterPixelLabel = qt.QLabel("  0 px")
        sizeFilterBox.addWidget(self.sizeFilterThreshold)
        sizeFilterBox.addWidget(self.sizeFilterPixelLabel)

        advancedSection = ctk.ctkCollapsibleButton()
        advancedSection.text = "Advanced"
        advancedSection.flat = True
        advancedSection.collapsed = True

        advancedFormLayout = qt.QFormLayout(advancedSection)

        self.orientationInput = ui.volumeInput(hasNone=True, nodeTypes=["vtkMRMLMarkupsLineNode"])
        self.orientationInput.addEnabled = False
        self.orientationInput.removeEnabled = False

        advancedFormLayout.addRow("Orientation Line: ", self.orientationInput)

        formLayout.addRow("Size Filter (mm): ", sizeFilterBox)
        formLayout.addRow(advancedSection)

        self.sizeFilterThreshold.valueChanged.connect(
            lambda v, w=self.sizeFilterPixelLabel: self._onPixelArgumentChanged(v, w)
        )

    def _onPixelArgumentChanged(self, value, labelWidget):
        voxelSize = self.voxeSizeGetter()
        pixel = int(np.round(value / voxelSize))
        labelWidget.setText(f"  {pixel} px")

    def toJson(self):
        return {
            "method": self.METHOD,
            "size_min_threshold": float(self.sizeFilterThreshold.value),
            "direction": self.orientationInput.currentNode(),
        }

    def fromJson(self, json):
        self.sizeFilterThreshold.value = json["size_min_threshold"]
        self.orientationInput.setCurrentNode(json["direction"])

    def validatePrerequisites(self):
        return True


class MedialSurfaceSettingsWidget(BaseSettingsWidget):
    METHOD = "medial surface"
    DISPLAY_NAME = "Medial surface segmentation"

    def __init__(self, voxelSizeGetter=None, onSelect=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.voxeSizeGetter = voxelSizeGetter or (lambda: 1)
        self.onSelect = onSelect or (lambda: None)

        self.setup()

    def setup(self):
        formLayout = qt.QFormLayout(self)

        smoothFilterSigmaBox = qt.QHBoxLayout()
        self.smoothFilterSigma = numberParam((0.0, 99999.0), value=0, step=0.001, decimals=4)
        self.smoothFilterSigma.setToolTip("Smooth label interfaces.")
        self.smoothFilterSigma.objectName = "Smooth Filter Sigma SpinBox"
        self.smoothFilterSigmaPixelLabel = qt.QLabel("  0 px")
        smoothFilterSigmaBox.addWidget(self.smoothFilterSigma)
        smoothFilterSigmaBox.addWidget(self.smoothFilterSigmaPixelLabel)

        numProcessesBox = qt.QHBoxLayout()
        self.numProcesses = numberParam((1, 64), value=8, step=1, decimals=0)
        self.numProcesses.setToolTip("Number of processes to use during some parts of the execution.")
        self.numProcesses.objectName = "Number Processes SpinBox"
        numProcessesBox.addWidget(self.numProcesses)
        numProcessesBox.addWidget(qt.QLabel(""))

        formLayout.addRow("Smooth Filter Sigma (mm): ", smoothFilterSigmaBox)
        formLayout.addRow("Number of processes: ", numProcessesBox)

        self.smoothFilterSigma.valueChanged.connect(
            lambda v, w=self.smoothFilterSigmaPixelLabel: self._onPixelArgumentChanged(v, w)
        )

    def _onPixelArgumentChanged(self, value, labelWidget):
        voxelSize = self.voxeSizeGetter()
        pixel = int(np.round(value / voxelSize))
        labelWidget.setText(f"  {pixel} px")

    def toJson(self):
        smoothFilterSigma = int(np.round(self.smoothFilterSigma.value / self.voxeSizeGetter()))
        return {
            "method": self.METHOD,
            "smooth_filter_sigma": smoothFilterSigma,
            "num_processes": self.numProcesses.value,
        }

    def validatePrerequisites(self):
        return True


class DeepWatershedSettingsWidget(BaseSettingsWidget):
    METHOD = "deep watershed"
    DISPLAY_NAME = "Deep watershed"

    def __init__(self, voxelSizeGetter=None, onSelect=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.showPxOnly = voxelSizeGetter == None
        self.userUnit = "px" if self.showPxOnly else "mm"
        self.voxeSizeGetter = voxelSizeGetter or (lambda: 1)

        self.onSelect = onSelect or (lambda: None)
        self.__currentReferenceNodeId = None
        self.setup()

    def setup(self):
        formLayout = qt.QFormLayout(self)

        ThresholdSplitBox = qt.QHBoxLayout()
        step = 1 if self.showPxOnly else 0.001
        self.ThresholdSplit = numberParam((0.0, 1.0), value=0.95, step=step, decimals=4)
        SplitThresholdTooltip = "Threshold used to split regions"
        self.ThresholdSplit.setToolTip(SplitThresholdTooltip)
        self.ThresholdSplit.objectName = "Deep Watershed Split Threshold SpinBox"
        ThresholdSplitBox.addWidget(self.ThresholdSplit)

        self.throatWidgetsLayout = qt.QHBoxLayout()
        self.throatAnalysisCheckBox = qt.QCheckBox()
        self.throatAnalysisCheckBox.setToolTip("Select this to include the throat analysis to the report output")
        self.throatAnalysisCheckBox.setChecked(False)
        self.throatAnalysisCheckBox.objectName = "2D Throat analysis CheckBox"

        self.throatWarningLabel = qt.QLabel("Available only for 2D Images")
        self.throatWarningLabel.setVisible(False)

        self.throatOptionLabel = qt.QLabel("2D Throat analysis (beta):")

        self.throatWidgetsLayout.addWidget(self.throatAnalysisCheckBox)
        self.throatWidgetsLayout.addSpacing(10)
        self.throatWidgetsLayout.addWidget(self.throatWarningLabel)
        self.throatWidgetsLayout.addStretch(1)

        self.tslabel = qt.QLabel(f"Split Threshold (0-1): ")
        self.tslabel.setToolTip(SplitThresholdTooltip)
        formLayout.addRow(self.tslabel, ThresholdSplitBox)

        formLayout.addRow(self.throatOptionLabel, self.throatWidgetsLayout)

        advancedSection = ctk.ctkCollapsibleButton()
        advancedSection.text = "Advanced"
        advancedSection.flat = True
        advancedSection.collapsed = True

        advancedFormLayout = qt.QFormLayout(advancedSection)

        baseVolumeBox = qt.QHBoxLayout()
        step = 1
        self.baseVolume = numberParam((0.0, 99999.0), value=150, step=step, decimals=0)
        baseVolumeTooltip = (
            "Initial value that will be used to split the input volume into smaller patches for inferece"
        )
        self.baseVolume.setToolTip(baseVolumeTooltip)

        self.baseVolume.objectName = "Base Volume SpinBox"
        baseVolumeBox.addWidget(self.baseVolume)

        intersectionBox = qt.QHBoxLayout()
        step = 1
        self.intersection = numberParam((0.0, 99999.0), value=60, step=step, decimals=0)
        intersectionTooltip = "Intersection between inferences"
        self.intersection.setToolTip(intersectionTooltip)

        self.intersection.objectName = "Intersection SpinBox"
        intersectionBox.addWidget(self.intersection)

        borderBox = qt.QHBoxLayout()
        step = 1
        self.border = numberParam((0.0, 99999.0), value=40, step=step, decimals=0)
        borderTooltip = "Border to be cut from inferences"
        self.border.setToolTip(borderTooltip)

        self.border.objectName = "Border SpinBox"
        borderBox.addWidget(self.border)

        ThresholdBackgroundBox = qt.QHBoxLayout()
        step = 1 if self.showPxOnly else 0.001
        self.ThresholdBackground = numberParam((0.0, 1.0), value=0.05, step=step, decimals=4)
        ThresholdBackgroundTooltip = "Threshold used to remove the background (pore/non-pore segmentation)"
        self.ThresholdBackground.setToolTip(ThresholdBackgroundTooltip)
        self.ThresholdBackground.objectName = "Deep Watershed Background Threshold SpinBox"
        ThresholdBackgroundBox.addWidget(self.ThresholdBackground)

        self.bvlabel = qt.QLabel(f"Base Volume (px): ")
        self.bvlabel.setToolTip(baseVolumeTooltip)
        advancedFormLayout.addRow(self.bvlabel, baseVolumeBox)

        self.itlabel = qt.QLabel(f"Intersection (px): ")
        self.itlabel.setToolTip(intersectionTooltip)
        advancedFormLayout.addRow(self.itlabel, intersectionBox)

        self.bdlabel = qt.QLabel(f"Border (px): ")
        self.bdlabel.setToolTip(borderTooltip)
        advancedFormLayout.addRow(self.bdlabel, borderBox)

        self.tblabel = qt.QLabel(f"Background Threshold (0-1): ")
        self.tblabel.setToolTip(ThresholdBackgroundTooltip)
        advancedFormLayout.addRow(self.tblabel, ThresholdBackgroundBox)

        formLayout.addRow(advancedSection)

    def _onPixelArgumentChanged(self, value, labelWidget):
        voxelSize = self.voxeSizeGetter()
        pixel = int(np.round(value / voxelSize))
        labelWidget.setText(f"  {pixel} px")

    def _onPixelArgumentChanged2(self, value, labelWidget):
        voxelSize = self.voxeSizeGetter()
        unpx = np.round(value * voxelSize, decimals=5)
        if self.showPxOnly:
            labelWidget.setText(f" {int(value)} px")
        else:
            labelWidget.setText(f" {int(value)} px ({unpx} mm)")

        if value <= 6:
            labelWidget.setStyleSheet("QLabel {color: white;}")
        elif 6 < value < 8:
            labelWidget.setStyleSheet("QLabel {color: yellow;}")
        else:
            labelWidget.setStyleSheet("QLabel {color: red;}")

    def toJson(self):
        return {
            "method": self.METHOD,
            "base_volume": int(self.baseVolume.value),
            "intersection": int(self.intersection.value),
            "border": int(self.border.value),
            "background_threshold": float(self.ThresholdBackground.value),
            "split_threshold": float(self.ThresholdSplit.value),
            "generate_throat_analysis": self.throatAnalysisCheckBox.isChecked(),
            "voxel_size": 1.0 if self.showPxOnly else None,
        }

    def fromJson(self, json):
        self.baseVolume.value = json["base_volume"]
        self.intersection.value = json["intersection"]
        self.border.value = json["border"]
        self.ThresholdBackground.value = json["background_threshold"]
        self.ThresholdSplit.value = json["split_threshold"]
        self.throatAnalysisCheckBox.setChecked(json["generate_throat_analysis"])

    def onReferenceChanged(self, node, selected):
        self.__currentReferenceNodeId = node.GetID() if node is not None else None
        if node is None:
            return

        # Enables throat option if reference image is 2D
        is_2d_image = isNodeImage2D(self.__currentReferenceNodeId)

        self.throatAnalysisCheckBox.setEnabled(is_2d_image)
        self.throatAnalysisCheckBox.setVisible(is_2d_image)
        self.throatOptionLabel.setVisible(is_2d_image)
        if self.throatAnalysisCheckBox.isChecked() and is_2d_image == False:
            self.throatAnalysisCheckBox.setChecked(False)

    def onModeChanged(self, mode):
        if mode == widgets.BatchInputWidget.MODE_NAME:
            self.throatWarningLabel.setVisible(True)
            self.throatAnalysisCheckBox.setEnabled(True)
            self.throatAnalysisCheckBox.setVisible(True)
            self.throatOptionLabel.setVisible(True)
        else:
            self.throatWarningLabel.setVisible(False)
            mode = isNodeImage2D(self.__currentReferenceNodeId)
            self.throatAnalysisCheckBox.setEnabled(mode)
            self.throatAnalysisCheckBox.setVisible(mode)
            self.throatOptionLabel.setVisible(mode)

    def validatePrerequisites(self):
        return True


#
# SegmentInspectorLogic
#
class SegmentInspectorLogic(LTracePluginLogic):
    inspectorProcessStarted = qt.Signal()
    inspector_process_finished = qt.Signal()

    def __init__(self, parent=None, results_queue=None):
        super().__init__(parent)

        self.tag = None
        self.progressUpdate = lambda value: None
        self.cliNode = None
        self.__cliNodeModifiedObserver = None
        self.progressBar = None
        self.__throatAnalysisGenerator = None
        self.results_queue = results_queue

    def runBatchpartitioning(self, batchDirectory, outputPrefixTemplate, **kwargs):
        segTag = kwargs.get("segTag", "SEG")
        roiTag = kwargs.get("roiTag", "ROI")
        valuesTag = kwargs.get("valuesTag", "")
        labelTag = kwargs.get("labelTag", "Pore")

        params = kwargs.get("params")

        for dirname in os.listdir(batchDirectory):
            epath = Path(batchDirectory) / dirname
            if epath.exists() and epath.is_dir():
                segmentationNode = None
                valuesNode = None
                roiNode = None

                allNodesFound = lambda: not (segmentationNode is None or valuesNode is None)

                for file in os.listdir(epath):
                    if file.endswith(".mrml"):
                        try:
                            slicer.util.loadScene(str(epath / file))
                        except Exception as e:
                            logging.warning(f"Failed to load {dirname} project. Cause: {repr(e)}")
                            continue

                        segmentationNode = tryGetNode(*[f"{tag}*" for tag in segTag.split("|")])
                        valuesNode = tryGetNode(f"{valuesTag}*")
                        roiNode = tryGetNode(f"{roiTag}*")

                        if allNodesFound():
                            break

                if not allNodesFound():
                    logging.warning(f"Missing Nodes on {dirname}, continue...")
                    slicer.mrmlScene.Clear(0)
                    continue

                # segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(valuesNode)

                try:
                    outputPrefix = outputPrefixTemplate.replace("{name}", segmentationNode.GetName())

                    extra = {}
                    referenceVolumeNode = valuesNode
                    if referenceVolumeNode:
                        extra["referenceNode"] = referenceVolumeNode

                    segmentation = segmentationNode.GetSegmentation()
                    segments = []
                    for index in range(segmentation.GetNumberOfSegments()):
                        segment = segmentation.GetNthSegment(index)
                        if labelTag in segment.GetName():
                            segments.append(index)

                    if roiNode:
                        extra["soiNode"] = roiNode

                    extra["params"] = params
                    extra["saveTo"] = str(epath)

                    yield self.runSelectedMethod(segmentationNode, segments, outputPrefix, **extra)

                except AttributeError as ve:
                    return
                except Exception:
                    slicer.mrmlScene.Clear(0)
                    continue

    def runSelectedMethod(self, segmentationNode, segments, outputPrefix, **kwargs):
        self.tag = Tag(value=str(uuid.uuid4()))

        try:
            return self.__callSelectedMethod(segmentationNode, segments, outputPrefix, **kwargs)
        except InvalidSegmentError as e:
            logging.warning(repr(e))
            raise
        except Exception as e:
            helpers.removeTemporaryNodes(environment=self.tag)
            print(repr(e))
            raise

    def __callSelectedMethod(self, segmentationNode, segments, outputPrefix, **kwargs):
        params = kwargs.get("params")
        products = kwargs.get("products", "all")

        referenceNode = kwargs["referenceNode"]

        # Setup Outputs -----------------------------------------------------------------------------
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        itemTreeId = folderTree.GetItemByDataNode(segmentationNode)
        parentItemId = folderTree.GetItemParent(itemTreeId)

        # End Setup Outputs -----------------------------------------------------------------------------
        try:
            if params["method"] == "mineralogy":
                targetLabels = extractLabels(segmentationNode)
                targetLabels[0] = "Background"
                labelMapNode, _ = helpers.createLabelmapInput(
                    segmentationNode=segmentationNode,
                    name=outputPrefix + "_MOCK_INPUT",
                    tag=self.tag,
                    referenceNode=referenceNode,
                    soiNode=kwargs["soiNode"],
                    topSegments=[s + 1 for s in segments],
                )

                cliNode, resultInfo = runMineralogy(
                    labelMapNode,
                    targetLabels,
                    outputPrefix,
                    params,
                    parentItemId,
                    segmentationNode,
                    roiNode=kwargs["soiNode"],
                    tag=self.tag,
                )
            elif params["method"] in ["snow", "islands", "deep watershed", "medial surface"]:
                targetLabels = extractLabels(segmentationNode, segments)
                if len(targetLabels) == 0:
                    slicer.util.errorDisplay(
                        "Please, select at least one segment by checking the segment box on the segment list."
                    )
                    helpers.removeTemporaryNodes(environment=self.tag)
                    # folderTree.RemoveItem(currentDir)
                    raise AttributeError("Please select at least one segment to be partitioned")

                labelMapNode, _ = helpers.createLabelmapInput(
                    segmentationNode=segmentationNode,
                    name=outputPrefix + "_MOCK_INPUT",
                    tag=self.tag,
                    referenceNode=referenceNode,
                    soiNode=kwargs["soiNode"],
                    topSegments=[s + 1 for s in segments],
                )

                if params["method"] == "medial surface":
                    array = slicer.util.arrayFromVolume(labelMapNode)
                    ndim = np.squeeze(array).ndim
                    if ndim != 3:
                        msg = "Medial surface segmentation is only available for 3D images."
                        slicer.util.errorDisplay(msg)
                        helpers.removeTemporaryNodes(environment=self.tag)
                        raise AttributeError(msg)

                if params.get("generate_throat_analysis", False) == True:
                    self.__throatAnalysisGenerator = ThroatAnalysisGenerator(
                        input_node_id=None,
                        base_name=outputPrefix,
                        hierarchy_folder=parentItemId,
                        direction=params.get("direction", None),
                    )
                    self.__throatAnalysisGenerator.create_output_nodes()

                    params["throatOutputReport"] = self.__throatAnalysisGenerator.throat_table_output_path
                    params["throatOutputLabelVolume"] = self.__throatAnalysisGenerator.throat_label_map_node_id

                cliNode, resultInfo = runPartitioning(
                    labelMapNode,
                    targetLabels,
                    outputPrefix,
                    params,
                    parentItemId,
                    products=products,
                    saveTo=kwargs.get("saveTo", None),
                    referenceNode=referenceNode,
                    roiNode=kwargs["soiNode"],
                    tag=self.tag,
                    inputNode=segmentationNode,
                    wait=kwargs.get("wait", False),
                )
            elif params["method"] == "basic_petrophysics":
                targetLabels = extractLabels(segmentationNode)
                targetLabels[0] = "Background"
                labelMapNode, _ = helpers.createLabelmapInput(
                    segmentationNode=segmentationNode,
                    name=outputPrefix + "_MOCK_INPUT",
                    tag=self.tag,
                    referenceNode=referenceNode,
                    soiNode=kwargs["soiNode"],
                    topSegments=[s + 1 for s in segments],
                )

                cliNode, resultInfo = runBasicPetrophysics(
                    labelMapNode,
                    targetLabels,
                    outputPrefix,
                    params,
                    parentItemId,
                    segmentationNode,
                    roiNode=kwargs["soiNode"],
                    tag=self.tag,
                )
            else:
                raise RuntimeError(f'Partition method {params.get("method", None)} not found')

            self.cliNode = cliNode
            self.__cliNodeModifiedObserver = self.cliNode.AddObserver(
                "ModifiedEvent", lambda c, ev, p=resultInfo: self.eventHandler(c, ev, p)
            )
            self.inspectorProcessStarted.emit()
            return self.cliNode
        except (RuntimeError, AttributeError) as e:
            print(f"An error occurred: {e}")

    def __createVariablesOutputNode(
        self,
        inputNode,
        labels,
        params,
        reportData,
        targetLabels=None,
        roiNode=None,
        segmentMap=None,
        prefix="",
        where=None,
    ):
        report = SegmentInspectorVariablesOutput(
            label_map_node=inputNode,
            labels=labels,
            params=params,
            roi_node=roiNode,
            report_data=reportData,
            target_labels=targetLabels,
            segment_map=segmentMap,
        )
        varNode = createOutput(
            prefix=prefix,
            ntype="Variables",
            where=where,
            builder=lambda n, hidden=False: helpers.createTemporaryNode(
                slicer.vtkMRMLTableNode, n, environment=self.tag, hidden=hidden
            ),
        )

        dataFrameToTableNode(report.data, tableNode=varNode)
        makeTemporaryNodePermanent(varNode)

    def __createBasicPetrophysicsOutputNode(self, labels, targetLabels, segmentMap, prefix="", where=None):
        try:
            report: pd.DataFrame = generate_basic_petrophysics_output(
                targetLabels, all_labels=labels, segment_map=segmentMap
            )

            varNode = createOutput(
                prefix=prefix,
                ntype="Basic_Petrophysics",
                where=where,
                builder=lambda n, hidden=False: helpers.createTemporaryNode(
                    slicer.vtkMRMLTableNode, n, environment=self.tag, hidden=hidden
                ),
            )

            dataFrameToTableNode(report, tableNode=varNode)
            makeTemporaryNodePermanent(varNode)
        except Exception as e:
            logging.warning(f"Tried to generate petrophysics output but failed due to: {repr(e)}")

    def distributions(self, labelmapVoxelArray, labels):
        bins = np.bincount(labelmapVoxelArray.ravel())
        segmentsInfo = []
        for label, _ in labels:
            voxelcount = bins[label]
            segmentsInfo.append(voxelcount)

        segmentedVoxelCount = sum([it for it in segmentsInfo])

        return segmentedVoxelCount, segmentsInfo

    def createResultArtifacts(self, info, caller=None):
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        method = info.params.get("method", "")
        methodName = (method if method != "snow" else "watershed").capitalize()
        outputDir = folderTree.CreateFolderItem(info.currentDir, generateName(folderTree, f"{methodName} Results"))

        self.progressUpdate(0)

        resultNode = None
        if info.outputVolume:
            resultNode = (
                info.outputVolume if not isinstance(info.outputVolume, str) else helpers.tryGetNode(info.outputVolume)
            )

        output_report_data = None
        segmentMap = None

        if info.outputReport:
            reportNode = info.reportNode

            if method == "mineralogy":
                outputReportNode = tryGetNode(info.outputReport)
                makeTemporaryNodePermanent(outputReportNode, show=True)
                helpers.moveNodeTo(outputDir, outputReportNode, dirTree=folderTree)
                if outputReportNode is not None:
                    outputReportNode.SetAttribute("ReferenceVolumeNode", info.referenceNode)
            elif method in ["snow", "islands", "deep watershed", "medial surface"]:
                if reportNode and resultNode:
                    helpers.moveNodeTo(outputDir, reportNode, dirTree=folderTree)

                    if info.params.get("generate_throat_analysis") == True:
                        self.__throatAnalysisGenerator.handle_process_completed()

                        throatTableNode = tryGetNode(self.__throatAnalysisGenerator.throat_table_node_id)
                        throatLabelMapNode = tryGetNode(self.__throatAnalysisGenerator.throat_label_map_node_id)

                        helpers.moveNodeTo(outputDir, throatTableNode, dirTree=folderTree)
                        helpers.moveNodeTo(
                            outputDir,
                            throatLabelMapNode,
                            dirTree=folderTree,
                        )

                        del self.__throatAnalysisGenerator
                        self.__throatAnalysisGenerator = None

                    dpath = Path(info.outputReport)
                    if dpath.exists():
                        output_report_data = pd.read_pickle(str(info.outputReport))
                        if len(output_report_data.index) > 0:
                            makeTemporaryNodePermanent(reportNode, show=True)
                            reportNode.SetAttribute("ReferenceVolumeNode", resultNode.GetID())
                            resultNode.SetAttribute("ResultReport", reportNode.GetID())  # não existia
                            dataFrameToTableNode(output_report_data, tableNode=reportNode)

                        dpath.unlink(missing_ok=True)

                segmentMap = getCountForLabels(info.sourceLabelMapNode, info.roiNode)
                self.__createBasicPetrophysicsOutputNode(
                    info.allLabels,  # force all targets here
                    info.allLabels,
                    segmentMap=dict(segmentMap),
                    prefix=info.outputPrefix,
                    where=outputDir,
                )

        if method == "basic_petrophysics":
            segmentMap = getCountForLabels(info.sourceLabelMapNode, info.roiNode)
            self.__createBasicPetrophysicsOutputNode(
                info.targetLabels,
                info.allLabels,
                segmentMap=dict(segmentMap),
                prefix=info.outputPrefix,
                where=outputDir,
            )

        # Create variables output
        self.__createVariablesOutputNode(
            inputNode=info.sourceLabelMapNode,
            labels=info.allLabels,
            params=info.params,
            roiNode=info.roiNode,
            prefix=info.outputPrefix,
            where=outputDir,
            reportData=output_report_data,
            targetLabels=info.targetLabels,
            segmentMap=segmentMap,
        )

        self.progressUpdate(0.6)

        if resultNode and caller:
            helpers.moveNodeTo(outputDir, resultNode, dirTree=folderTree)
            makeTemporaryNodePermanent(resultNode, show=True)
            if resultNode.IsA("vtkMRMLLabelMapVolumeNode"):
                nsegments = int(caller.GetParameterAsString("number_of_partitions"))
                colors = rand_cmap(nsegments)
                colorTableNode = helpers.create_color_table(
                    node_name=f"{resultNode.GetName()}_ColorMap",
                    colors=colors,
                    color_names=[str(i) for i in range(1, len(colors) + 1)],
                    add_background=True,
                )

                resultNode.GetDisplayNode().SetAndObserveColorNodeID(colorTableNode.GetID())

                if info.referenceNode:
                    slicer.util.setSliceViewerLayers(background=info.referenceNode, fit=True)  # NEEDED?
                self.outLabelMapId = resultNode.GetID()
            else:
                slicer.util.setSliceViewerLayers(background=resultNode, fit=True)

        self.progressUpdate(0.9)

        if info.saveOutput:
            dirpath = Path(info.saveOutput)
            result = dirpath.parent / f"Processed_{dirpath.name}/"
            result.mkdir(parents=True, exist_ok=True)
            helpers.removeTemporaryNodes(environment=self.tag)
            slicer.util.saveScene(str(result))
            slicer.mrmlScene.Clear(0)

    def eventHandler(self, caller, event, info: ResultInfo):
        if caller is None:
            self.cliNode = None
            return

        try:
            if caller.GetStatusString() == "Completed":
                if self.results_queue is not None:
                    print("Sending results to queue")
                    self.results_queue.append(info)

                self.createResultArtifacts(info, caller)

            elif caller.GetStatusString() == "Completed with errors":
                if self.results_queue is not None:
                    self.results_queue.append(None)
        except Exception as e:
            import traceback

            traceback.print_exc()
        finally:
            if not caller.IsBusy():
                if self.__cliNodeModifiedObserver is not None:
                    self.cliNode.RemoveObserver(self.__cliNodeModifiedObserver)
                    del self.__cliNodeModifiedObserver
                    self.__cliNodeModifiedObserver = None

                del self.cliNode
                self.cliNode = None

                print("ExecCmd CLI %s" % caller.GetStatusString())
                helpers.removeTemporaryNodes(environment=self.tag)
                self.inspector_process_finished.emit()
                self.progressUpdate(1.0)


def runMineralogy(labelMapNode, labels, outputPrefix, params, currentDir, referenceNode, roiNode, tag=None):
    reportNode = createOutput(
        prefix=outputPrefix,
        where=currentDir,
        ntype="Transitions",
        builder=lambda n, hidden=True: helpers.createTemporaryNode(
            slicer.vtkMRMLTableNode, n, environment=tag, hidden=hidden
        ),
    )

    cliConf = dict(
        params=json.dumps(params),
        labelVolume=labelMapNode,
        outputReport=reportNode.GetID(),
        pixelLabels=json.dumps(labels),
    )

    cliNode = slicer.cli.run(slicer.modules.mineralogycli, None, cliConf, wait_for_completion=False)

    sourceLabelMapNode = helpers.createTemporaryVolumeNode(
        slicer.vtkMRMLLabelMapVolumeNode, name="Source Inspector LabelMap", environment=tag, content=labelMapNode
    )

    resultInfo = ResultInfo(
        sourceLabelMapNode=sourceLabelMapNode,
        outputVolume=None,
        outputReport=cliConf["outputReport"],
        reportNode=None,
        outputPrefix=outputPrefix,
        allLabels=labels,
        targetLabels=labels,
        saveOutput=None,
        referenceNode=referenceNode.GetID(),
        params=params,
        currentDir=currentDir,
        inputNode=labelMapNode,
        roiNode=roiNode,
    )

    return cliNode, resultInfo


def runBasicPetrophysics(labelMapNode, labels, outputPrefix, params, currentDir, referenceNode, roiNode, tag=None):
    cliConf = dict(
        params=json.dumps(params),
    )

    cliNode = slicer.cli.run(slicer.modules.segmentinspectorcli, None, cliConf, wait_for_completion=False)

    resultInfo = ResultInfo(
        sourceLabelMapNode=labelMapNode,
        outputVolume=None,
        outputReport=None,
        reportNode=None,
        outputPrefix=outputPrefix,
        allLabels=labels,
        targetLabels=labels,
        saveOutput=None,
        referenceNode=referenceNode.GetID(),
        params=params,
        currentDir=currentDir,
        inputNode=labelMapNode,
        roiNode=roiNode,
    )

    return cliNode, resultInfo
