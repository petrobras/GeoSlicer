import importlib
import sys
import ctk
import os
import qt
import slicer
import logging
import pandas as pd
import numpy as np

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
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from pathlib import Path
from scipy.stats import gaussian_kde, norm

try:
    from Test.InstanceKDETest import InstanceKDETest
except ImportError:
    InstanceKDETest = None  # tests not deployed to final version or closed source


class InstanceKDE(LTracePlugin):
    SETTING_KEY = "InstanceKDE"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "KDE Of Instance Measurements"
        self.parent.categories = ["ImageLog"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.setHelpUrl("ImageLog/Processing/Processing.html#kde-of-instance-measurements")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class InstanceKDEWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.collapsed = False
        inputSection.text = "Input"

        self.inputSelector = ui.hierarchyVolumeInput(
            onChange=self.onInputNodeChanged,
            hasNone=True,
            nodeTypes=["vtkMRMLTableNode"],
        )
        self.inputSelector.setMRMLScene(slicer.mrmlScene)
        self.inputSelector.setToolTip("Pick a instance report table")
        self.inputSelector.objectName = "Instance Report Table Selector"

        self.propertyComboBox = qt.QComboBox()
        self.propertyComboBox.currentIndexChanged.connect(self.onPropertyChange)
        self.propertyComboBox.objectName = "Property Combo Box"

        inputLayout = qt.QFormLayout(inputSection)
        inputLayout.addRow("Input:", self.inputSelector)
        inputLayout.addRow("Measurement:", self.propertyComboBox)

        # Parameters section
        parametersSection = ctk.ctkCollapsibleButton()
        parametersSection.text = "Parameters"
        parametersSection.collapsed = False
        parametersSection.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        self.depthRangeSpinBox = qt.QDoubleSpinBox()
        self.depthRangeSpinBox.setRange(0.05, 10)
        self.depthRangeSpinBox.setSingleStep(0.1)
        self.depthRangeSpinBox.setValue(0.1)
        self.depthRangeSpinBox.valueChanged.connect(self.onSpinBoxChange)
        self.depthRangeSpinBox.objectName = "Depth Spin Box"

        self.bandwithSpinBox = qt.QDoubleSpinBox()
        self.bandwithSpinBox.setRange(0.01, 1)
        self.bandwithSpinBox.setSingleStep(0.05)
        self.bandwithSpinBox.setValue(0.2)
        self.bandwithSpinBox.valueChanged.connect(self.onSpinBoxChange)
        self.bandwithSpinBox.objectName = "Bandwith Spin Box"

        parametersLayout = qt.QFormLayout(parametersSection)
        parametersLayout.addRow("Depth interval (m):", self.depthRangeSpinBox)
        parametersLayout.addRow("KDE Bandwith:", self.bandwithSpinBox)

        # Output section
        outputSection = ctk.ctkCollapsibleButton()
        outputSection.text = "Output"
        outputSection.collapsed = False

        self.outputPrefixLineEdit = qt.QLineEdit()
        self.outputPrefixLineEdit.objectName = "Output Prefix Line Edit"
        outputFormLayout = qt.QFormLayout(outputSection)
        outputFormLayout.addRow("Output prefix:", self.outputPrefixLineEdit)

        # Apply button
        self.applyButton = ui.ApplyButton(onClick=self.onApplyButtonClicked, tooltip="Apply changes", enabled=True)
        self.applyButton.objectName = "Apply Button"
        self.applyButton.setEnabled(False)

        # Update layout
        self.layout.addWidget(inputSection)
        self.layout.addWidget(parametersSection)
        self.layout.addWidget(outputSection)
        self.layout.addWidget(self.applyButton)
        self.layout.addStretch(1)

    def onApplyButtonClicked(self):
        logic = InstanceKDELogic()
        try:
            logic.apply(
                self.inputSelector.currentNode(),
                self.propertyComboBox.currentText,
                self.depthRangeSpinBox.value,
                self.bandwithSpinBox.value,
                self.outputPrefixLineEdit.text,
            )
        except ValueError:
            slicer.util.errorDisplay(
                f"An issue occurred during execution. Check if '{self.inputSelector.currentNode().GetName()}' table has enough data and if its correct."
            )

    def onInputNodeChanged(self):
        self.updatePropertyOptions()
        self.updateOutputName()

    def onSpinBoxChange(self):
        self.updateOutputName()

    def onPropertyChange(self):
        self.updateOutputName()

    def updatePropertyOptions(self):
        self.propertyComboBox.clear()
        node = self.inputSelector.currentNode()
        if node is not None:
            for column in [node.GetColumnName(i) for i in range(node.GetNumberOfColumns())]:
                if column in GENERIC_PROPERTIES:
                    self.propertyComboBox.addItem(column)

    def updateOutputName(self):
        node = self.inputSelector.currentNode()
        if node is not None:
            self.outputPrefixLineEdit.text = f"{node.GetName()}_KDE_{self.propertyComboBox.currentText}_{round(self.depthRangeSpinBox.value, 2)}_{round(self.bandwithSpinBox.value, 2)}"
        else:
            self.outputPrefixLineEdit.text = ""

        self.checkApplyButtonState()

    def checkApplyButtonState(self):
        self.applyButton.setEnabled(False)

        if self.inputSelector.currentNode() is None:
            return

        if self.outputPrefixLineEdit.text.strip() == "":
            return

        self.applyButton.setEnabled(True)

    def onReload(self):
        importlib.reload(sys.modules["ImageLogDataLib.viewwidgets.histogram_in_depth_view_widget"])
        importlib.reload(sys.modules["Plots.HistogramInDepthPlot.HistogramInDepthPlotWidgetModel"])
        importlib.reload(sys.modules["Test.InstanceKDETest"])
        super().onReload()


class InstanceKDELogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def apply(self, reportTable, property, depthRange, bandwith, tableName):
        reportDF = slicer.util.dataframeFromTable(reportTable)
        groupedDF = self._createGroupedTable(reportDF, depthRange, property)
        if groupedDF.empty:
            logging.warning(
                f"Warning: An issue occurred with the '{reportTable.GetName()}' table during the label grouping by depth operation. Please verify the table's data integrity and if it is correct."
            )
            raise ValueError("Expected non-empty DataFrame, but got an empty one.")

        kdeDF = self._creatKDETable(groupedDF, property, bandwith)

        tableNode = dataFrameToTableNode(kdeDF)
        tableNode.SetAttribute(TableType.name(), TableType.HISTOGRAM_IN_DEPTH.value)
        tableNode.SetAttribute(TableDataTypeAttribute.name(), TableDataTypeAttribute.IMAGE_2D.value)
        tableNode.SetAttribute(TableDataOrientation.name(), TableDataOrientation.ROW.value)
        tableNode.SetAttribute(HistogramGraphType.name(), HistogramGraphType.MULTI_HISTOGRAM.value)
        tableNode.SetAttribute(PlotScaleXAxisAttribute.name(), PlotScaleXAxisAttribute.LINEAR_SCALE.value)
        tableNode.AddNodeReferenceID("InstanceReportTable", reportTable.GetID())
        tableNode.SetUseFirstColumnAsRowHeader(True)
        tableNode.SetUseColumnNameAsColumnHeader(True)
        tableNode.SetAttribute("Property", property)
        tableNode.SetName(tableName)

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

    def _creatKDETable(self, groupedDF, measurement, bandwith):
        xGrid = self._instanceMeasurementsLimits(np.array(groupedDF), measurement)

        kdeList = []

        for index, row in groupedDF.iterrows():
            kdeList.append(self._kde(np.array(row), xGrid, bandwith))

        kdeDF = pd.DataFrame(kdeList)
        kdeDF.index = groupedDF.index
        kdeDF.dropna(how="all", inplace=True)
        kdeDF.insert(0, "DEPTH(m)", [x * 1000 for x in kdeDF.index.tolist()])

        return kdeDF

    def _kde(self, data, xGrid, bandwith):
        cleanData = data[~np.isnan(data)]
        if cleanData.size == 0:
            return []

        if len(cleanData) == 1 or len(np.unique(cleanData)) == 1:
            normalDist = norm(loc=cleanData[0], scale=0.01)
            result = list(normalDist.pdf(xGrid))

        else:
            kde = gaussian_kde(cleanData, bw_method=bandwith)
            result = list(kde(xGrid))

        return result

    def _instanceMeasurementsLimits(self, data, measurement):
        if measurement == "Circularity":
            xGrid = np.linspace(0, 1, 200)
        elif measurement == "azimuth (°)":
            xGrid = np.linspace(0, 360, 200)
        else:
            if np.nanmin(data) == np.nanmax(data):
                logging.warning(
                    f"Warning: Cannot calculate KDE: the minimum ({np.nanmin(data)}) and maximum ({np.nanmax(data)}) values of '{measurement}' are identical."
                )
                raise ValueError(
                    f"Cannot calculate KDE: the minimum ({np.nanmin(data)}) and maximum ({np.nanmax(data)}) values of '{measurement}' are identical."
                )
            xGrid = np.linspace(np.nanmin(data), np.nanmax(data), 200)

        return xGrid
