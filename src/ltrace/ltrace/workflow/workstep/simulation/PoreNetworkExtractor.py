import qt
import slicer
import time

from PoreNetworkExtractor import PoreNetworkExtractorLogic, PoreNetworkExtractorParamsWidget, PoreNetworkExtractorError
from ltrace.workflow.workstep import Workstep, WorkstepWidget
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar


class PoreNetworkExtractor(Workstep):
    NAME = "Simulation: Pore Network Extraction"

    INPUT_TYPES = (slicer.vtkMRMLScalarVolumeNode,)
    OUTPUT_TYPE = slicer.vtkMRMLTableNode

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.method = "PoreSpy"
        self.delete_inputs = True

    def run(self, nodes):
        progressBar = LocalProgressBar()
        logic = PoreNetworkExtractorLogic(None, progressBar)

        for node in nodes:
            self.finished = False
            try:
                logic.extract(node, None, node.GetName(), self.method, self.onFinish)
            except PoreNetworkExtractorError:
                continue

            while self.finished is False:
                time.sleep(0.2)
                slicer.app.processEvents()

            self.discard_input(node)

            pore_table, throat_table = logic.results["pore_table"], logic.results["throat_table"]
            yield pore_table

    def onFinish(self, state):
        self.finished = state

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
