import slicer
import qt
import numpy as np
import pandas as pd
from PoreNetworkSimulation import PoreNetworkSimulationLogic
from PoreNetworkSimulation import OnePhaseSimulationWidget
from ltrace.workflow.workstep import Workstep, WorkstepWidget
from ltrace.slicer_utils import dataFrameToTableNode


class PoreNetworkSimOnePhase(Workstep):
    NAME = "Simulation: Pore Network Simulation (One-phase)"

    INPUT_TYPES = (slicer.vtkMRMLTableNode,)
    OUTPUT_TYPE = slicer.vtkMRMLTableNode

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.params = OnePhaseSimulationWidget.DEFAULT_VALUES
        self.compiled_table_name = "Permeability results"

    def run(self, table_nodes):
        logic = PoreNetworkSimulationLogic()
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        results = {"Name": [], "x [mD]": [], "y [mD]": [], "z [mD]": []}
        for table_node in table_nodes:
            perm_table = logic.run_1phase(table_node, self.params["model type"], table_node.GetName())
            perm_table.SetName(table_node.GetName() + " perm")
            itemTreeId = folderTree.GetItemByDataNode(perm_table)
            parentItemId = folderTree.GetItemParent(folderTree.GetItemParent(itemTreeId))
            name = folderTree.GetItemName(parentItemId)

            df = slicer.util.dataframeFromTable(perm_table)
            diag = np.diag(df)
            results["Name"].append(name)
            results["x [mD]"].append(diag[0])
            results["y [mD]"].append(diag[1])
            results["z [mD]"].append(diag[2])

            yield perm_table

        results_table = dataFrameToTableNode(pd.DataFrame(results))
        results_table.SetName(self.compiled_table_name)

    def widget(self):
        return PoreNetworkSimOnePhaseWidget(self)


class PoreNetworkSimOnePhaseWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)
        self.params_widget = OnePhaseSimulationWidget()
        self.compiled_table_edit = qt.QLineEdit()

        form_layout = qt.QFormLayout()
        form_layout.addRow(self.params_widget)
        form_layout.addRow("Compiled permeability table name:", self.compiled_table_edit)

        self.layout().addLayout(form_layout)
        self.layout().addStretch(1)

    def save(self):
        self.workstep.params = self.params_widget.getParams()
        self.workstep.compiled_table_name = self.compiled_table_edit.text

    def load(self):
        self.params_widget.setParams(self.workstep.params)
        self.compiled_table_edit.text = self.workstep.compiled_table_name
