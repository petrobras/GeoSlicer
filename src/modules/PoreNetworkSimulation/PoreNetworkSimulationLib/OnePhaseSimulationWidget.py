import qt

from MercurySimulationLib.MercurySimulationWidget import MercurySimulationWidget
from PoreNetworkSimulationLib.constants import *
from ltrace.slicer import ui

from ltrace.slicer.widget.help_button import HelpButton


class OnePhaseSimulationWidget(qt.QFrame):
    DEFAULT_VALUES = {
        "model type": VALVATNE_BLUNT,
        "simulation type": ONE_ANGLE,
        "rotation angles": 100,
        "keep_temporary": False,
        "subres_model_name": "Fixed Radius",
        "subres_params": {"radius": 0.1},
        "solver": "pypardiso",
        "solver_error": 1e-7,
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

        hbox = qt.QHBoxLayout()
        self.solverComboBox = qt.QComboBox()
        self.solverComboBox.addItems(["pypardiso", "pyflowsolver", "openpnm"])
        self.solverComboBox.setCurrentIndex(0)
        solverHelpButton = HelpButton(
            "'pypardiso' is the recomended solver, 'pyflowsolver' allows error tolerance control, but performance is usually lower than 'pypardiso', 'openpnm' is a legacy option"
        )
        hbox.addWidget(self.solverComboBox)
        hbox.addWidget(solverHelpButton)
        layout.addRow("Solver", hbox)

        hbox = qt.QHBoxLayout()
        self.errorLabel = qt.QLabel("Target error")
        self.errorEdit = ui.floatParam(1e-7)
        self.errorHelpButton = HelpButton("Error stopping criteria for the linear system solver")
        hbox.addWidget(self.errorEdit)
        hbox.addWidget(self.errorHelpButton)
        layout.addRow(self.errorLabel, hbox)

        self.preconditionerLabel = qt.QLabel("Preconditioner:")
        self.preconditionerComboBox = qt.QComboBox()
        self.preconditionerComboBox.addItems(
            [
                "inverse_diagonal",
            ]
        )
        self.preconditionerComboBox.setCurrentIndex(0)
        layout.addRow(self.preconditionerLabel, self.preconditionerComboBox)

        self.solverComboBox.currentTextChanged.connect(self.onSolverChanged)
        self.solverComboBox.currentTextChanged.emit(self.solverComboBox.currentText)

        hbox = qt.QHBoxLayout()
        self.clipCheck = qt.QCheckBox()
        clipCheckHelpButton = HelpButton(
            'If "clip high conductivities" is selected, high conductivities throats have their conductivities reduced to a cap of the lowest conductivity times the "maximum conductivity range" input. This should be used when convergence is not achieved in networks that percolate only on the subscale phase.'
        )
        hbox.addWidget(self.clipCheck)
        hbox.addWidget(clipCheckHelpButton)
        layout.addRow("Clip high conductivity values", hbox)
        self.clipEdit = ui.floatParam(1e10)
        layout.addRow("Maximum conductivity range", self.clipEdit)

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
        subres_model_name = self.mercury_widget.subscaleModelWidget.microscale_model_dropdown.currentText
        subres_params = self.mercury_widget.subscaleModelWidget.parameter_widgets[subres_model_name].get_params()

        if (subres_model_name == "Throat Radius Curve" or subres_model_name == "Pressure Curve") and subres_params:
            subres_params = {
                i: subres_params[i].tolist() if subres_params[i] is not None else None for i in subres_params.keys()
            }

        return {
            "model type": self.modelTypeComboBox.currentText,
            "simulation type": self.simulationTypeComboBox.currentText,
            "rotation angles": int(self.rotationAnglesEdit.text),
            "keep_temporary": False,
            "subresolution function call": self.mercury_widget.getFunction,
            "subres_model_name": subres_model_name,
            "subres_params": subres_params,
            "solver": self.solverComboBox.currentText,
            "solver_error": float(self.errorEdit.text),
            "preconditioner": self.preconditionerComboBox.currentText,
            "clip_check": self.clipCheck.isChecked(),
            "clip_value": float(self.clipEdit.text),
        }

    def onSolverChanged(self, text):
        self.errorLabel.setVisible(text == "pyflowsolver")
        self.errorEdit.setVisible(text == "pyflowsolver")
        self.errorHelpButton.setVisible(text == "pyflowsolver")
        self.preconditionerLabel.setVisible(text == "pyflowsolver")
        self.preconditionerComboBox.setVisible(text == "pyflowsolver")

    def onSimulationTypeChanged(self, text):
        self.rotationAnglesLabel.setVisible(text == "Multiple orientations")
        self.rotationAnglesEdit.setVisible(text == "Multiple orientations")

    def setParams(self, params):
        self.modelTypeComboBox.setCurrentText(params["model type"])
        self.modelTypeComboBox.setCurrentText(params["simulation type"])
        self.modelTypeComboBox.setCurrentText(params["rotation angles"])
        self.mercury_widget.subscaleModelWidget.microscale_model_dropdown.setCurrentText(params["subres_model_name"])
