import slicer
import qt
import numpy as np
import pandas as pd
import time

from PoreNetworkSimulation import OnePhaseSimulationLogic
from PoreNetworkSimulation import OnePhaseSimulationWidget
from PoreNetworkSimulationLib.constants import MICP, ONE_PHASE, TWO_PHASE, ONE_ANGLE, MULTI_ANGLE

from ltrace.workflow.workstep import Workstep, WorkstepWidget
from ltrace.slicer_utils import dataFrameToTableNode
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar

from .InputTablesListWidget import InputTablesListWidget, set_subres_model_and_params


class PoreNetworkSimOnePhase(Workstep):
    NAME = "Simulation: Pore Network Simulation (One-phase)"

    INPUT_TYPES = (slicer.vtkMRMLTableNode,)
    OUTPUT_TYPE = slicer.vtkMRMLTableNode

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.params = OnePhaseSimulationWidget.DEFAULT_VALUES
        self.pressure_tables = []
        self.compiled_table_name = "Permeability results"

    def run(self, table_nodes):
        progressBar = LocalProgressBar()
        logic = OnePhaseSimulationLogic(progressBar)
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        results = {"Name": [], "x [mD]": [], "y [mD]": [], "z [mD]": []}
        for idx, table_node in enumerate(table_nodes):
            self.finished = False

            params = self.params.copy()
            params["subresolution function call"] = lambda node: set_subres_model_and_params(
                node, idx, params, self.pressure_tables
            )
            params["subresolution function"] = params["subresolution function call"](table_node)

            logic.run_1phase(table_node, params, prefix=table_node.GetName(), callback=self.onFinish)

            while self.finished is False:
                time.sleep(0.2)
                slicer.app.processEvents()

            perm_table = slicer.util.getNode(logic.results["permeability"])
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

    def onFinish(self, state):
        self.finished = state

    def widget(self):
        return PoreNetworkSimOnePhaseWidget(self)


class PoreNetworkSimOnePhaseWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)
        form_layout = qt.QFormLayout()

        self.params_widget = OnePhaseSimulationWidget()
        self.params_widget.mercury_widget.micpCollapsibleButton.setVisible(False)
        form_layout.addRow(self.params_widget)

        self.queue_widget = InputTablesListWidget(self.params_widget.mercury_widget.subscaleModelWidget)
        form_layout.addRow(self.queue_widget)

        self.compiled_table_edit = qt.QLineEdit()
        form_layout.addRow("Compiled permeability table name:", self.compiled_table_edit)

        self.layout().addLayout(form_layout)
        self.layout().addStretch(1)

    def save(self):
        self.workstep.params.update(self.params_widget.getParams())
        del self.workstep.params["subresolution function call"]
        self.workstep.compiled_table_name = self.compiled_table_edit.text
        self.workstep.pressure_tables = self.queue_widget.write_qtable_to_list(self.queue_widget.queue)

    def load(self):
        self.params_widget.setParams(self.workstep.params)
        self.compiled_table_edit.text = self.workstep.compiled_table_name
