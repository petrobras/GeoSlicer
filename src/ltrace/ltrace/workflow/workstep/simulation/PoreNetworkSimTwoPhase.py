import slicer
from PoreNetworkSimulation import PoreNetworkSimulationLogic
from PoreNetworkSimulation import TwoPhaseSimulationWidget
from ltrace.workflow.workstep import Workstep, WorkstepWidget


class PoreNetworkSimTwoPhase(Workstep):
    NAME = "Simulation: Pore Network Simulation (Two-phase)"

    INPUT_TYPES = (slicer.vtkMRMLTableNode,)
    OUTPUT_TYPE = type(None)

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.params = TwoPhaseSimulationWidget.DEFAULT_VALUES

    def run(self, table_nodes):
        logic = PoreNetworkSimulationLogic()

        for table_node in table_nodes:
            logic.run_2phase(table_node, self.params, table_node.GetName())
            yield f"two-phase simulation of {table_node.GetName()}"

    def widget(self):
        return PoreNetworkSimTwoPhaseWidget(self)


class PoreNetworkSimTwoPhaseWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)
        self.params_widget = TwoPhaseSimulationWidget()
        self.layout().addWidget(self.params_widget)
        self.layout().addStretch(1)

    def save(self):
        self.workstep.params = self.params_widget.getParams()

    def load(self):
        self.params_widget.setParams(self.workstep.params)
