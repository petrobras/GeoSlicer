import numpy as np
import pandas as pd
import slicer
import qt

import time

from MercurySimulationLib.MercurySimulationLogic import MercurySimulationLogic
from MercurySimulationLib.MercurySimulationLogic import estimate_radius
from MercurySimulationLib.MercurySimulationWidget import MercurySimulationWidget
from MercurySimulationLib.SubscaleModelWidget import SubscaleModelWidget

from ltrace.slicer_utils import dataFrameToTableNode, dataframeFromTable
from ltrace.workflow.workstep import Workstep, WorkstepWidget
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from .InputTablesListWidget import InputTablesListWidget, set_subres_model_and_params


class PoreNetworkSimMercury(Workstep):
    NAME = "Simulation: Pore Network Simulation (Mercury)"

    INPUT_TYPES = (slicer.vtkMRMLTableNode,)
    OUTPUT_TYPE = slicer.vtkMRMLTableNode

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.params = MercurySimulationWidget.DEFAULT_VALUES
        self.pressure_tables = []

    def run(self, table_nodes):
        progressBar = LocalProgressBar()
        logic = MercurySimulationLogic(None, progressBar)

        for idx, pore_node in enumerate(table_nodes):
            self.finished = False

            params = self.params.copy()
            params["subresolution function call"] = lambda node: set_subres_model_and_params(
                node, idx, params, self.pressure_tables
            )
            params["subresolution function"] = params["subresolution function call"](pore_node)

            logic.run_mercury(pore_node, params, pore_node.GetName(), self.onFinish)

            while self.finished is False:
                time.sleep(0.2)
                slicer.app.processEvents()

            micp_table = slicer.util.getNode(logic.results_node_id)

            yield micp_table

    def onFinish(self, state):
        self.finished = state

    def widget(self):
        return PoreNetworkSimMercuryWidget(self)


class PoreNetworkSimMercuryWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)
        self.params_widget = SubscaleModelWidget()
        self.layout().addWidget(self.params_widget)

        self.queue_widget = InputTablesListWidget(self.params_widget)
        self.layout().addWidget(self.queue_widget)

        self.layout().addStretch(1)

    def save(self):
        self.workstep.params.update(self.params_widget.getParams())
        self.workstep.pressure_tables = self.queue_widget.write_qtable_to_list(self.queue_widget.queue)

    def load(self):
        self.params_widget.setParams(self.workstep.params)
