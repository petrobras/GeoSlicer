import qt
import slicer

from PoreNetworkExtractor import PoreNetworkExtractorLogic, PoreNetworkExtractorParamsWidget, PoreNetworkExtractorError
from ltrace.workflow.workstep import Workstep, WorkstepWidget


class PoreNetworkExtractor(Workstep):
    NAME = "Simulation: Pore Network Extraction"

    INPUT_TYPES = (slicer.vtkMRMLLabelMapVolumeNode,)
    OUTPUT_TYPE = slicer.vtkMRMLTableNode

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.method = "PoreSpy"
        self.delete_inputs = True

    def run(self, label_map_nodes):
        logic = PoreNetworkExtractorLogic()

        for label_map_node in label_map_nodes:
            try:
                extract_result = logic.extract(label_map_node, label_map_node.GetName(), self.method)
            except PoreNetworkExtractorError:
                continue
            finally:
                self.discard_input(label_map_node)
            pore_table, throat_table = extract_result
            yield pore_table

    def widget(self):
        return PoreNetworkExtractorWidget(self)


class PoreNetworkExtractorWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)
        self.params_widget = PoreNetworkExtractorParamsWidget()
        self.layout().addWidget(self.params_widget)

        self.delete_inputs_checkbox = qt.QCheckBox("Remove input images from project after extraction")
        self.delete_inputs_checkbox.setToolTip(
            "Remove input images from project as soon as they are no longer needed in order to reduce memory usage."
        )
        self.layout().addWidget(self.delete_inputs_checkbox)

        self.layout().addStretch(1)

    def save(self):
        self.workstep.method = self.params_widget.methodSelector.currentText
        self.workstep.delete_inputs = self.delete_inputs_checkbox.isChecked()

    def load(self):
        self.params_widget.methodSelector.setCurrentText(self.workstep.method)
        self.delete_inputs_checkbox.setChecked(self.workstep.delete_inputs)
