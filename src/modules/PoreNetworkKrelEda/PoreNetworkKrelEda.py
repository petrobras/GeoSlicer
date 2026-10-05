import os
from pathlib import Path

import ctk
import numpy as np
import pandas as pd
import pyqtgraph as pg
import qt
import slicer

from ltrace.pore_networks.krel_result import KrelResult, KrelTables
from ltrace.slicer import ui
from ltrace.slicer.helpers import getPythonQtWidget
from ltrace.slicer_utils import (
    LTracePlugin,
    LTracePluginWidget,
    LTracePluginLogic,
    dataframeFromTable,
    dataFrameToTableNode,
    slicer_is_in_developer_mode,
    getResourcePath,
)
from ltrace.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import GraphicsLayoutWidget
from PoreNetworkKrelEdaLib.diagnostics_container import DiagnosticsContainerWidget
from PoreNetworkKrelEdaLib.export.PoreNetworkKrelEdaExport import PoreNetworkKrelEdaExportWidget
from PoreNetworkKrelEdaLib.visualization_widgets.crossed_plots import CrossedError, CrossedParameters
from PoreNetworkKrelEdaLib.visualization_widgets.curves_plot import CurvesPlot
from PoreNetworkKrelEdaLib.visualization_widgets.pressure_plot import PressurePlot
from PoreNetworkKrelEdaLib.visualization_widgets.ca_distribution_plot import CaDistributionPlot
from PoreNetworkKrelEdaLib.visualization_widgets.wettability_index_plot import WettabilityIndexPlot
from PoreNetworkKrelEdaLib.visualization_widgets.heatmap_plots import (
    ParameterErrorCorrelation,
    ParameterResultCorrelation,
    ResultSelfCorrelation,
    SecondOrderInteraction,
)
from PoreNetworkKrelEdaLib.visualization_widgets.plot_data import PlotData
from PoreNetworkKrelEdaLib.visualization_widgets.table_plots import SecondOrderInteractions, ThirdOrderInteractions

try:
    from Test.PoreNetworkKrelEdaTest import PoreNetworkKrelEdaTest
except ImportError:
    PoreNetworkKrelEdaTest = None  # tests not deployed to final version or closed source


AUTO_DETECT_STR = "Auto detect cycles"
SW_COLUMN_STR = "Saturation column"
KRW_COLUMN_STR = "Krw column"
KRO_COLUMN_STR = "Kro column"
CYCLE_COLUMN_STR = "Cycle column"


class PoreNetworkKrelEda(LTracePlugin):
    SETTING_KEY = "PoreNetworkKrelEda"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "PNM Krel EDA"
        self.parent.categories = ["Tools", "MicroCT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.setHelpUrl("Volumes/PNM/PNM.html#krel-eda")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PoreNetworkKrelEdaWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)

        self.data_manager = PlotData()

        self.mainTab = qt.QTabWidget()
        self.layout.addWidget(self.mainTab)

        self.setup_eda()
        self.setup_import()
        self.setup_diagnostics()
        if slicer_is_in_developer_mode():
            self.mainTab.addTab(PoreNetworkKrelEdaExportWidget(), "Export")

        self.logic = PoreNetworkKrelEdaLogic()

    def setup_eda(self):
        # Input section
        input_section = ctk.ctkCollapsibleButton()
        input_section.collapsed = False
        input_section.text = "Input"

        self.__input_selector = ui.hierarchyVolumeInput(
            onChange=self.__on_input_node_changed,
            hasNone=True,
            nodeTypes=["vtkMRMLTableNode"],
        )
        self.__input_selector.objectName = "Input parameter table"
        self.__input_selector.showEmptyHierarchyItems = False
        self.__input_selector.addNodeAttributeIncludeFilter("table_type", "krel_simulation_results")
        self.__input_selector.setMRMLScene(slicer.mrmlScene)
        self.__input_selector.setToolTip("Pick a parameter table node")

        input_layout = qt.QFormLayout(input_section)
        input_layout.addRow("Input Parameter Table: ", self.__input_selector)

        # Visualization section
        visualization_section = ctk.ctkCollapsibleButton()
        visualization_section.text = "Visualization"
        visualization_section.collapsed = False

        self.__visualizationTypeSelector = ui.StackedSelector(text="Visualization type:")
        self.__visualizationTypeSelector.addWidget(CurvesPlot(data_manager=self.data_manager))
        self.__visualizationTypeSelector.addWidget(PressurePlot(data_manager=self.data_manager))
        self.__visualizationTypeSelector.addWidget(WettabilityIndexPlot(data_manager=self.data_manager))
        self.__visualizationTypeSelector.addWidget(CrossedError(data_manager=self.data_manager))
        self.__visualizationTypeSelector.addWidget(CrossedParameters(data_manager=self.data_manager))
        self.__visualizationTypeSelector.addWidget(ParameterResultCorrelation(data_manager=self.data_manager))
        self.__visualizationTypeSelector.addWidget(ParameterErrorCorrelation(data_manager=self.data_manager))
        self.__visualizationTypeSelector.addWidget(ResultSelfCorrelation(data_manager=self.data_manager))
        self.__visualizationTypeSelector.addWidget(SecondOrderInteraction(data_manager=self.data_manager))
        self.__visualizationTypeSelector.addWidget(SecondOrderInteractions(data_manager=self.data_manager))
        self.__visualizationTypeSelector.addWidget(ThirdOrderInteractions(data_manager=self.data_manager))
        self.__visualizationTypeSelector.addWidget(CaDistributionPlot(data_manager=self.data_manager))
        self.__visualizationTypeSelector.currentWidgetChanged.connect(self.__update_current_plot)
        self.__visualizationTypeSelector.objectName = "Visualization selector"
        self.__clear_plots()

        visualizationFormLayout = qt.QFormLayout(visualization_section)
        visualizationFormLayout.addRow(self.__visualizationTypeSelector)
        # visualizationFormLayout.addRow("Other Scale", PaintWidget())

        eda_layout = qt.QFormLayout()
        eda_layout.addWidget(input_section)
        eda_layout.addWidget(visualization_section)
        eda_container = qt.QWidget()
        eda_container.setLayout(eda_layout)
        # eda_layout.addStretch(1)
        self.mainTab.addTab(eda_container, "EDA")

    def setup_import(self):

        importLayout = qt.QFormLayout()

        import_csv_button = qt.QPushButton("Import from csv")
        import_csv_button.objectName = "Import from csv button"
        import_csv_button.connect("clicked(bool)", self.__import_from_csv)
        importLayout.addRow(import_csv_button)

        self.inputSelector = slicer.qMRMLNodeComboBox()
        self.inputSelector.objectName = "Krel table node selector"
        self.inputSelector.setMRMLScene(slicer.mrmlScene)
        self.inputSelector.selectNodeUponCreation = False
        self.inputSelector.addEnabled = False
        self.inputSelector.editEnabled = False
        self.inputSelector.removeEnabled = False
        self.inputSelector.renameEnabled = False
        self.inputSelector.noneEnabled = True
        self.inputSelector.showHidden = False
        self.inputSelector.nodeTypes = ["vtkMRMLTableNode"]
        importLayout.addRow("Krel Table Node", self.inputSelector)
        self.inputSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.__change_import_table)

        self.cboxes = {}
        for cbox in (
            SW_COLUMN_STR,
            KRW_COLUMN_STR,
            KRO_COLUMN_STR,
            CYCLE_COLUMN_STR,
        ):
            self.cboxes[cbox] = qt.QComboBox()
            self.cboxes[cbox].objectName = cbox
            importLayout.addRow(cbox, self.cboxes[cbox])
            self.cboxes[cbox].connect("currentIndexChanged(int)", self.__change_import_column)

        pg.setConfigOption("background", "w")
        pg.setConfigOption("foreground", "k")
        pg.setConfigOptions(antialias=True)
        self.graphicsLayoutWidget = GraphicsLayoutWidget()
        self.graphicsLayoutWidget.setFixedHeight(360)

        self.xLegendLabelItem = pg.LabelItem(angle=0)
        self.yLegendLabelItem = pg.LabelItem(angle=270)
        self.xLegendLabelItem.setText("Sw")
        self.yLegendLabelItem.setText("Krel")
        self.graphicsLayoutWidget.addItem(self.xLegendLabelItem, row=2, col=2, colspan=2)
        self.graphicsLayoutWidget.addItem(self.yLegendLabelItem, row=0, col=1, rowspan=2)
        self.plotItem = self.graphicsLayoutWidget.addPlot()

        pyqtGraphicsLayoutWidget = getPythonQtWidget(self.graphicsLayoutWidget)
        importLayout.addWidget(pyqtGraphicsLayoutWidget)

        self.outputPrefix = qt.QLineEdit()
        self.outputPrefix.objectName = "Krel import output name"
        importLayout.addRow("Table name: ", self.outputPrefix)
        save_button = qt.QPushButton("Save table")
        save_button.objectName = "Save Krel table button"
        save_button.connect("clicked(bool)", self.__click_import)
        importLayout.addWidget(save_button)

        self.spacerItem = qt.QSpacerItem(0, 0, qt.QSizePolicy.Minimum, qt.QSizePolicy.Expanding)
        importLayout.addItem(self.spacerItem)
        import_container = qt.QWidget()
        import_container.setLayout(importLayout)
        self.mainTab.addTab(import_container, "Import")

    def setup_diagnostics(self):
        self.diagnosticsContainer = DiagnosticsContainerWidget()
        self.mainTab.addTab(self.diagnosticsContainer, "Diagnostics")

    def __on_input_node_changed(self, vtkid=None):
        self.__clear_plots()

        currentNode = self.__input_selector.currentNode()
        self.data_manager.update_data(currentNode)
        self.__update_current_plot()

    def __update_current_plot(self, vtkid=None):
        currentWidget = self.__visualizationTypeSelector.currentWidget()

        curvesWidget = self.__visualizationTypeSelector.widget(0)
        pressureWidget = self.__visualizationTypeSelector.widget(1)
        distributionWidget = self.__visualizationTypeSelector.widget(11)
        number_of_simulations = self.data_manager.get_number_of_simulations()
        invalid_combination = (
            currentWidget != curvesWidget and currentWidget != pressureWidget and currentWidget != distributionWidget
        ) and number_of_simulations == 1

        if self.data_manager.is_valid() and not invalid_combination:
            currentWidget.setVisible(True)
            currentWidget.update()
        else:
            currentWidget.setVisible(False)

    def __clear_plots(self):
        for i in range(self.__visualizationTypeSelector.count()):
            self.__visualizationTypeSelector.widget(i).setVisible(False)
            self.__visualizationTypeSelector.widget(i).clear_saved_plots()

    def __import_from_csv(self):
        file_path = qt.QFileDialog.getOpenFileName(None, "Select Krel CSV file", "", "CSV Files (*.csv);;All Files (*)")
        if not file_path:
            return

        from ltrace.file_utils import load_and_parse_data

        df = load_and_parse_data(Path(file_path), filter_empty_columns=True)
        if df is None:
            slicer.util.errorDisplay(f"Failed to read csv file: {file_path}")
            return

        tableNode = dataFrameToTableNode(df)
        tableNode.SetName(slicer.mrmlScene.GenerateUniqueName(Path(file_path).stem))

        self.inputSelector.setCurrentNode(tableNode)

    def __change_import_table(self, node):
        input_node = node

        for cbox in self.cboxes.values():
            cbox.clear()

        if input_node is None:
            self.plotItem.clear()
            return

        self.cboxes["Cycle column"].addItem(AUTO_DETECT_STR)
        columns = []
        for volume_index in range(input_node.GetNumberOfColumns()):
            columns.append(input_node.GetColumnName(volume_index))

        for cbox in self.cboxes.values():
            for column in columns:
                cbox.addItem(column)
        self.outputPrefix.text = input_node.GetName() + "_Krel_Import"

        column_guesses = {
            SW_COLUMN_STR: ("sw", "saturation"),
            KRW_COLUMN_STR: ("krw",),
            KRO_COLUMN_STR: ("kro",),
        }
        for cbox_key, keywords in column_guesses.items():
            for column in reversed(columns):
                if any(keyword in column.lower() for keyword in keywords):
                    self.cboxes[cbox_key].currentText = column
                    break

    def __change_import_column(self):
        self.plotItem.clear()

        if self.inputSelector.currentNode() is None:
            return

        krel_df = dataframeFromTable(self.inputSelector.currentNode())
        krel_df = krel_df.replace("", np.nan)
        sw_string = self.cboxes[SW_COLUMN_STR].currentText
        kro_string = self.cboxes[KRO_COLUMN_STR].currentText
        krw_string = self.cboxes[KRW_COLUMN_STR].currentText
        cycle_string = self.cboxes[CYCLE_COLUMN_STR].currentText
        if not sw_string or not kro_string or not krw_string or not cycle_string:
            return

        columns_to_convert = [sw_string, kro_string, krw_string]
        if cycle_string != AUTO_DETECT_STR:
            columns_to_convert.append(cycle_string)
        for column_string in dict.fromkeys(columns_to_convert):
            krel_df[column_string] = krel_df[column_string].astype(np.float32)

        for column_string in (sw_string, kro_string, krw_string):
            if krel_df[column_string].max() > 1.5:
                krel_df[column_string] = krel_df[column_string] / 100.0

        if cycle_string == AUTO_DETECT_STR:
            cycle_list = self.__detect_cycles(krel_df, sw_string)
            cycle_string = "cycle"
            krel_df[cycle_string] = cycle_list

        # Separate dataframes by cycle
        cycle_krel_df_list = []
        for cycle in range(1, 3 + 1):
            cycle_krel_df_list.append(krel_df[krel_df[cycle_string] == cycle])

        # Add last point of previous cycle to the next
        for i in range(1, len(cycle_krel_df_list)):
            if cycle_krel_df_list[i].shape[0] == 0 or cycle_krel_df_list[i - 1].shape[0] == 0:
                continue
            df = cycle_krel_df_list[i].copy()
            df.loc[-1] = cycle_krel_df_list[i - 1].iloc[-1]
            df.index = df.index + 1
            cycle_krel_df_list[i] = df.sort_index()

        for i, cycle in enumerate(range(3)):
            if cycle >= len(cycle_krel_df_list):
                continue
            cycle_krel_df = cycle_krel_df_list[cycle]
            kro_plot = self.plotItem.plot(pen=pg.mkPen((255, i * 85, 0), width=2), name=f"Kro cycle {cycle + 1}")
            krw_plot = self.plotItem.plot(pen=pg.mkPen((0, i * 85, 255), width=2), name=f"Krw cycle {cycle + 1}")
            kro_plot.setData(cycle_krel_df[sw_string].array, cycle_krel_df[kro_string].array)
            krw_plot.setData(cycle_krel_df[sw_string].array, cycle_krel_df[krw_string].array)
        self.plotItem.addLegend()

        self.krel_df = krel_df

    def __click_import(self):
        cycle_column_name = self.cboxes[CYCLE_COLUMN_STR].currentText
        self.logic.createKrelResult(
            self.outputPrefix.text,
            self.inputSelector.currentNode(),
            self.krel_df,
            self.cboxes[SW_COLUMN_STR].currentText,
            self.cboxes[KRW_COLUMN_STR].currentText,
            self.cboxes[KRO_COLUMN_STR].currentText,
            cycle_column_name if cycle_column_name != AUTO_DETECT_STR else "cycle",
        )

    def __detect_cycles(self, krel_df, sw_string):
        previous_sw = None
        cycle = 1 if krel_df[sw_string].iloc[1] <= krel_df[sw_string].iloc[0] else 2
        cycle_list = []
        for i, sw in enumerate(krel_df[sw_string]):
            if previous_sw:
                if cycle == 1 and sw >= previous_sw:
                    cycle += 1
                elif cycle == 2 and sw <= previous_sw:
                    cycle += 1
            previous_sw = sw
            cycle_list.append(cycle)
        return cycle_list


class PoreNetworkKrelEdaLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def apply(self, data):
        pass

    def createKrelResult(
        self, outputName, inputNode, krelDataFrame, swColumnName, krwColumnName, kroColumnName, cycleColumnName
    ):
        krelResult = KrelResult()
        df = krelDataFrame
        df = df.rename(
            columns={swColumnName: "Sw", krwColumnName: "Krw", kroColumnName: "Kro", cycleColumnName: "cycle"}
        )
        df = df[["Sw", "Krw", "Kro", "cycle"]]
        df["Sw"] = df["Sw"].astype(float)
        df["Krw"] = df["Krw"].astype(float)
        df["Kro"] = df["Kro"].astype(float)
        df["cycle"] = df["cycle"].astype(int)
        krelResult.add_table_result(df)

        subjectHierarchy = slicer.mrmlScene.GetSubjectHierarchyNode()
        parentNodeId = subjectHierarchy.GetItemByDataNode(inputNode)
        parentItemId = subjectHierarchy.GetItemParent(parentNodeId)
        folderItemId = subjectHierarchy.CreateFolderItem(parentItemId, slicer.mrmlScene.GenerateUniqueName(outputName))

        tableNode = dataFrameToTableNode(krelResult.to_dataframe())
        tableNode.SetName(slicer.mrmlScene.GenerateUniqueName("Krel_results"))
        tableNode.SetAttribute("table_type", "krel_simulation_results")

        tablesFolderItemId = subjectHierarchy.CreateFolderItem(
            folderItemId, slicer.mrmlScene.GenerateUniqueName("Tables")
        )
        subjectHierarchy.SetItemExpanded(tablesFolderItemId, False)
        dfCycleResults = pd.DataFrame(KrelTables.get_complete_dict(krelResult.krel_tables))
        for cycle in range(1, 4):
            cycleDataFrame = dfCycleResults[dfCycleResults["cycle"] == cycle]
            cycleTableNode = dataFrameToTableNode(cycleDataFrame)
            cycleTableNode.SetName(slicer.mrmlScene.GenerateUniqueName(f"krel_table_cycle{cycle}"))
            cycleTableNode.SetAttribute("table_type", "relative_permeability")
            tableNode.SetAttribute(f"cycle_table_{cycle}_id", cycleTableNode.GetID())
            subjectHierarchy.CreateItem(tablesFolderItemId, cycleTableNode)
        subjectHierarchy.CreateItem(folderItemId, tableNode)
