import qt

import numpy as np
from .constants import *
from ltrace.slicer import ui

from ltrace.slicer.widget.help_button import HelpButton

from MercurySimulationLib.MercurySimulationWidget import MercurySimulationWidget


class OnePhaseSimulationWidget(qt.QFrame):
    DEFAULT_VALUES = {
        "model type": VALVATNE_BLUNT,
        "simulation type": ONE_ANGLE,
        "rotation angles": 100,
        "keep_temporary": False,
        "subres_model_name": "Fixed Radius",
        "subres_params": {"radius": 0.1},
        "subres_shape_factor": 0.04,
        "subres_porositymodifier": 1.0,
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

        self.generateVisualizationCheckbox = qt.QCheckBox()
        self.generateVisualizationCheckbox.setToolTip(
            "Enable to generate visualization model nodes. Note: For large projects, the generated model nodes may consume significant disk space when saved."
        )
        self.generateVisualizationCheckbox.objectName = "Visualization checkbox"
        layout.addRow("Generate visualization:", self.generateVisualizationCheckbox)

        self.simulationTypeComboBox.currentTextChanged.connect(self.onSimulationTypeChanged)
        self.simulationTypeComboBox.currentTextChanged.emit(self.simulationTypeComboBox.currentText)

        self.mercury_widget = MercurySimulationWidget()
        layout.addRow(self.mercury_widget)

    def getParams(self):
        subres_model_name = self.mercury_widget.subscaleModelWidget.microscale_model_dropdown.currentText
        subres_params = self.mercury_widget.subscaleModelWidget.parameter_widgets[subres_model_name].get_params()
        subres_porositymodifier = self.mercury_widget.getParams()["subres_porositymodifier"]
        shape_factor = self.mercury_widget.getParams()["subres_shape_factor"]

        subres_params_copy = {}
        if (subres_model_name == "Throat Radius Curve" or subres_model_name == "Pressure Curve") and subres_params:
            for i in subres_params.keys():
                if subres_params[i] is not None:
                    if isinstance(subres_params[i], np.ndarray):
                        subres_params_copy.update({i: subres_params[i].tolist()})
                    else:
                        subres_params_copy.update({i: subres_params[i]})
                else:
                    subres_params_copy.update({i: None})
        else:
            subres_params_copy = subres_params

        return {
            "model type": self.modelTypeComboBox.currentText,
            "simulation type": self.simulationTypeComboBox.currentText,
            "rotation angles": int(self.rotationAnglesEdit.text),
            "keep_temporary": False,
            "subresolution function call": self.mercury_widget.getFunction,
            "subres_porositymodifier": subres_porositymodifier,
            "subres_shape_factor": shape_factor,
            "subres_model_name": subres_model_name,
            "subres_params": subres_params_copy,
            "solver": self.solverComboBox.currentText,
            "solver_error": float(self.errorEdit.text),
            "preconditioner": self.preconditionerComboBox.currentText,
            "clip_check": self.clipCheck.isChecked(),
            "clip_value": float(self.clipEdit.text),
            "visualization": self.generateVisualizationCheckbox.isChecked(),
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
        self.modelTypeComboBox.setCurrentText(params.get("model type"))
        self.modelTypeComboBox.setCurrentText(params.get("simulation type"))
        self.modelTypeComboBox.setCurrentText(params.get("rotation angles"))
        mercury_params = {
            "subres_model_name": params.get("subres_model_name"),
            "subres_params": params.get("subres_params"),
            "subres_porositymodifier": params.get("subres_porositymodifier"),
            "subres_shape_factor": params.get("subres_shape_factor"),
        }
        self.mercury_widget.setParams(mercury_params)
