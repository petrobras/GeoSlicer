import slicer
from PoreNetworkSimulation import TwoPhaseSimulationLogic
from PoreNetworkSimulation import TwoPhaseSimulationWidget
from ltrace.workflow.workstep import Workstep, WorkstepWidget
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar

from .InputTablesListWidget import InputTablesListWidget, set_subres_model_and_params


class PoreNetworkSimTwoPhase(Workstep):
    NAME = "Simulation: Pore Network Simulation (Two-phase)"

    INPUT_TYPES = (slicer.vtkMRMLTableNode,)
    OUTPUT_TYPE = slicer.vtkMRMLTableNode

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.params = TwoPhaseSimulationWidget.DEFAULT_VALUES
        self.pressure_tables = []

    def run(self, table_nodes):
        progressBar = LocalProgressBar()
        logic = TwoPhaseSimulationLogic(progressBar)

        for idx, table_node in enumerate(table_nodes):
            params = self.params.copy()
            params["subresolution function call"] = lambda node: set_subres_model_and_params(
                node, idx, params, self.pressure_tables
            )
            params["subresolution function"] = params["subresolution function call"](table_node)

            logic.run_2phase(table_node, params, prefix=table_node.GetName(), callback=lambda _: True, wait=True)
            yield f"two-phase simulation of {table_node.GetName()}"

    def widget(self):
        return PoreNetworkSimTwoPhaseWidget(self)


class PoreNetworkSimTwoPhaseWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)

        self.params_widget = TwoPhaseSimulationWidget()
        self.params_widget.mercury_widget.micpCollapsibleButton.setVisible(False)
        self.layout().addWidget(self.params_widget)

        self.queue_widget = InputTablesListWidget(self.params_widget.mercury_widget.subscaleModelWidget)
        self.layout().addWidget(self.queue_widget)

        self.layout().addStretch(1)

    def save(self):
        self.workstep.params = self.params_widget.getParams()
        del self.workstep.params["subresolution function call"]
        self.workstep.pressure_tables = self.queue_widget.write_qtable_to_list(self.queue_widget.queue)

    def load(self):
        self.params_widget.setParams(self.workstep.params)
