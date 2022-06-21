import pandas as pd
import qt
import slicer

from ltrace.pore_networks.simulation_parameters_node import dict_to_parameter_node
from ltrace.slicer import ui
from ltrace.slicer_utils import dataFrameToTableNode
from PoreNetworkKrelEdaLib.visualization_widgets.plot_data import KrelResultCurves


class PoreNetworkKrelEdaExportWidget(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.logic = PoreNetworkKrelEdaExportLogic()

        layout = qt.QFormLayout(self)

        self.__inputSelector = ui.hierarchyVolumeInput(
            onChange=self.__onInputNodeChanged,
            hasNone=True,
            nodeTypes=["vtkMRMLTableNode"],
        )
        self.__inputSelector.objectName = "Export - Input parameter table"
        self.__inputSelector.showEmptyHierarchyItems = False
        self.__inputSelector.addNodeAttributeIncludeFilter("table_type", "krel_simulation_results")
        self.__inputSelector.setMRMLScene(slicer.mrmlScene)
        self.__inputSelector.setToolTip("Pick a parameter table node")

        self.__simulationSelectionCombobox = qt.QComboBox()

        self.__exportFormatCombobox = qt.QComboBox()
        self.__exportFormatCombobox.addItem("CSV file")
        self.__exportFormatCombobox.addItem("GeoSlicer nodes")
        self.__exportFormatCombobox.addItem("Parameter node")

        self.__outputNameWidget = qt.QLineEdit()

        self.__exportButton = qt.QPushButton("Export simulation")
        self.__exportButton.clicked.connect(self.__onExportClicked)

        layout.addRow("Input Parameter Table: ", self.__inputSelector)
        layout.addRow("Simulation to export: ", self.__simulationSelectionCombobox)
        layout.addRow("Format: ", self.__exportFormatCombobox)
        layout.addRow("Output name:", self.__outputNameWidget)
        layout.addRow(self.__exportButton)

    def __onInputNodeChanged(self, selectedItem):
        self.logic.update_node(self.__inputSelector.currentNode())
        number_of_simulations = self.logic.get_number_of_simulations()

        outputName = (
            self.__inputSelector.currentNode().GetName() if self.__inputSelector.currentNode() is not None else ""
        )
        self.__outputNameWidget.setText(outputName)
        self.__simulationSelectionCombobox.clear()
        self.__simulationSelectionCombobox.addItems(list(range(number_of_simulations)))

    def __onExportClicked(self):
        if self.__exportFormatCombobox.currentText == "CSV file":
            self.logic.export_simulation_to_csv(
                int(self.__simulationSelectionCombobox.currentText), self.__outputNameWidget.text
            )
        elif self.__exportFormatCombobox.currentText == "GeoSlicer nodes":
            self.logic.export_simulation_to_nodes(
                int(self.__simulationSelectionCombobox.currentText), self.__outputNameWidget.text
            )
        else:
            self.logic.export_simulation_parameter_node(
                int(self.__simulationSelectionCombobox.currentText), self.__outputNameWidget.text
            )


class PoreNetworkKrelEdaExportLogic:
    def __init__(self):
        self.krel_result = None

    def update_node(self, selected_node):
        self.krel_result = KrelResultCurves(selected_node)

    def get_number_of_simulations(self):
        if self.krel_result is None:
            return None

        return self.krel_result.get_number_of_simulations()

    def export_simulation_to_csv(self, simulation_id, output_name):
        if self.krel_result is None:
            return

        export_dict = {"Cycle": [], "Sw": [], "Kro": [], "Krw": []}
        for cycle in range(1, 4):
            cycle_curves = self.krel_result.get_cycle(cycle)
            sw_data = cycle_curves.get_sw_data()
            krw_data = cycle_curves.get_krw_data(simulation_id)
            kro_data = cycle_curves.get_kro_data(simulation_id)
            cycle_data = [cycle] * len(sw_data)

            export_dict["Cycle"].extend(cycle_data)
            export_dict["Sw"].extend(sw_data)
            export_dict["Kro"].extend(kro_data)
            export_dict["Krw"].extend(krw_data)

        pd.DataFrame(export_dict).to_csv(f"{output_name}.csv", index=False)

    def export_simulation_to_nodes(self, simulation_id, output_name):
        df = pd.DataFrame(self.krel_result.get_parameters_df().iloc[[simulation_id]])
        subject_hierarchy = slicer.mrmlScene.GetSubjectHierarchyNode()
        folder_item_id = subject_hierarchy.CreateFolderItem(
            subject_hierarchy.GetSceneItemID(), slicer.mrmlScene.GenerateUniqueName(output_name)
        )
        tables_folder_item_id = subject_hierarchy.CreateFolderItem(
            folder_item_id, slicer.mrmlScene.GenerateUniqueName("Tables")
        )
        krel_result_node = dataFrameToTableNode(df)
        krel_result_node.SetName(slicer.mrmlScene.GenerateUniqueName("Krel_results"))
        krel_result_node.SetAttribute("table_type", "krel_simulation_results")
        subject_hierarchy.CreateItem(folder_item_id, krel_result_node)
        for cycle in range(1, 4):
            cycle_df = self.krel_result.get_cycle_df(cycle)
            cycle_df = pd.DataFrame(
                cycle_df[["cycle", "Sw", f"Pc_{simulation_id}", f"Krw_{simulation_id}", f"Kro_{simulation_id}"]]
            )
            cycle_df = cycle_df.rename(
                columns={
                    f"Pc_{simulation_id}": f"Pc_0",
                    f"Krw_{simulation_id}": f"Krw_0",
                    f"Kro_{simulation_id}": f"Kro_0",
                }
            )
            krel_table_node = dataFrameToTableNode(cycle_df)
            krel_table_node.SetAttribute("table_type", "relative_permeability")
            krel_table_node.SetName(slicer.mrmlScene.GenerateUniqueName(f"krel_table_cycle{cycle}"))
            krel_result_node.SetAttribute(f"cycle_table_{cycle}_id", krel_table_node.GetID())
            subject_hierarchy.CreateItem(tables_folder_item_id, krel_table_node)

    def export_simulation_parameter_node(self, simulation_id, output_name):
        df = pd.DataFrame(self.krel_result.get_parameters_df().iloc[[simulation_id]].filter(like="input-"))
        parameters_dict = {}
        for column in df.columns:
            value = df[column].iloc[0]

            parameters_dict[column] = {}
            parameters_dict[column]["start"] = value
            parameters_dict[column]["stop"] = value
            parameters_dict[column]["steps"] = 1

        dict_to_parameter_node(parameters_dict, output_name)
