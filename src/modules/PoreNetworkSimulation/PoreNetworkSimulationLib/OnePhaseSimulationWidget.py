import qt

from MercurySimulationLib.MercurySimulationWidget import MercurySimulationWidget
from PoreNetworkSimulationLib.constants import *
from ltrace.slicer import ui


class OnePhaseSimulationWidget(qt.QFrame):
    DEFAULT_VALUES = {
        "model type": VALVATNE_BLUNT,
        "simulation type": ONE_ANGLE,
        "rotation angles": 100,
    }

    def __init__(self):
        super().__init__()
        layout = qt.QFormLayout(self)

        # Pore-throat model selector
        pn_models = [
            VALVATNE_BLUNT,
        ]
        self.modelTypeComboBox = qt.QComboBox()
        self.modelTypeComboBox.addItems(pn_models)
        self.modelTypeComboBox.setCurrentIndex(0)
        layout.addRow("Pore Network model", self.modelTypeComboBox)

        simulation_types = [ONE_ANGLE, MULTI_ANGLE]
        self.simulationTypeComboBox = qt.QComboBox()
        self.simulationTypeComboBox.addItems(simulation_types)
        self.simulationTypeComboBox.setCurrentIndex(0)
        self.simulationTypeComboBox.objectName = "Kabs multiangle"
        layout.addRow("Orientation scheme", self.simulationTypeComboBox)

        self.rotationAnglesLabel = qt.QLabel("Rotation angles")
        self.rotationAnglesEdit = ui.intParam(100)
        self.rotationAnglesEdit.objectName = "Multiangle Steps"
        layout.addRow(self.rotationAnglesLabel, self.rotationAnglesEdit)

        self.simulationTypeComboBox.currentTextChanged.connect(self.onSimulationTypeChanged)
        self.simulationTypeComboBox.currentTextChanged.emit(self.simulationTypeComboBox.currentText)

        self.mercury_widget = MercurySimulationWidget()
        layout.addRow(self.mercury_widget)

    def getParams(self):
        return {
            "model type": self.modelTypeComboBox.currentText,
            "simulation type": self.simulationTypeComboBox.currentText,
            "rotation angles": int(self.rotationAnglesEdit.text),
            "subresolution function call": self.mercury_widget.getFunction,
        }

    def onSimulationTypeChanged(self, text):
        self.rotationAnglesLabel.setVisible(text == "Multiple orientations")
        self.rotationAnglesEdit.setVisible(text == "Multiple orientations")

    def setParams(self, params):
        self.modelTypeComboBox.setCurrentText(params["model type"])
        self.modelTypeComboBox.setCurrentText(params["simulation type"])
        self.modelTypeComboBox.setCurrentText(params["rotation angles"])
