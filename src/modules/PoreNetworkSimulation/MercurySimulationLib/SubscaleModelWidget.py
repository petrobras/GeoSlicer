from pathlib import Path

import qt
import slicer

import numpy as np
from ltrace.slicer import ui
from ltrace.slicer.ui import (
    hierarchyVolumeInput,
    DirOrFileWidget,
    floatParam,
)
from ltrace.slicer_utils import dataframeFromTable
from ltrace.file_utils import read_csv

from MercurySimulationLib import MercurySimulationLogic


class SubscaleModelWidget(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = qt.QFormLayout(self)

        self.parameter_widgets = {}

        for widget in (
            FixedRadiusWidget,
            LeverettNewWidget,
            LeverettOldWidget,
            PressureCurveWidget,
            ThroatRadiusCurveWidget,
        ):
            self.parameter_widgets[widget.STR] = widget()

        self.microscale_model_dropdown = qt.QComboBox()
        self.microscale_model_dropdown.objectName = "Subscale Model Selector"
        layout.addRow("Subscale entry pressure model:", self.microscale_model_dropdown)
        for label, widget in self.parameter_widgets.items():
            self.microscale_model_dropdown.addItem(label)
            layout.addRow(widget)
            widget.setVisible(False)

        self.parameter_widgets[self.microscale_model_dropdown.currentText].setVisible(True)

        self.microscale_model_dropdown.currentTextChanged.connect(self._onUnresolvedModelChange)

    def _onUnresolvedModelChange(self, new_text):
        for widget in self.parameter_widgets.values():
            widget.setVisible(False)
        self.parameter_widgets[new_text].setVisible(True)

    def getParams(self):
        subres_model_name = self.microscale_model_dropdown.currentText
        subres_params = self.parameter_widgets[subres_model_name].get_params()

        if (subres_model_name == "Throat Radius Curve" or subres_model_name == "Pressure Curve") and subres_params:
            subres_params = {
                i: subres_params[i].tolist() if subres_params[i] is not None else None for i in subres_params.keys()
            }

        return {
            "subres_model_name": subres_model_name,
            "subres_params": subres_params,
        }

    def setParams(self, params):
        self.microscale_model_dropdown.setCurrentText(params["subres_model_name"])


class FixedRadiusWidget(qt.QWidget):
    STR = "Fixed Radius"

    def __init__(self):
        super().__init__()
        layout = qt.QFormLayout(self)
        self.logic = MercurySimulationLogic.FixedRadiusLogic()

        self.micropore_radius = ui.floatParam()
        self.micropore_radius.text = 0.1
        self.auto_radius_btn = qt.QPushButton("Auto detect radius")

        layout.addRow("Micropore radius (mm): ", self.micropore_radius)
        layout.addRow(self.auto_radius_btn)

    def get_params(self):
        params = {
            "radius": float(self.micropore_radius.text),
        }
        return params

    def get_subradius_function(self, pore_network, volume):
        params = self.get_params()
        func = self.logic.get_capillary_pressure_function(params, pore_network, volume)
        return func


class ThroatRadiusCurveWidget(qt.QWidget):
    STR = "Throat Radius Curve"

    def __init__(self):
        super().__init__()
        self.logic = MercurySimulationLogic.PressureCurveLogic()
        import_layout = qt.QFormLayout(self)

        instructions_labels = qt.QLabel(
            "To import a pressure curve, first add it to the scene in File -> Advanced Add Data"
        )
        import_layout.addWidget(instructions_labels)

        self.throatRadiusSelector = hierarchyVolumeInput(hasNone=True, nodeTypes=["vtkMRMLTableNode"])
        self.throatRadiusSelector.setToolTip("Select input (optional)")
        self.throatRadiusSelector.clearSelection()
        self.throatRadiusSelector.setToolTip('Pick a Table node of type "pore_table".')
        self.throatRadiusSelector.objectName = "Throat Radius Curve Selector"
        import_layout.addRow("Throat Radius Table", self.throatRadiusSelector)
        self.throatRadiusSelector.currentItemChanged.connect(self.__change_import_table)

        self.default_options = {
            "Volume Fraction Column": ["dsn", "Fvol"],
            "Throat Radius Column": ["radii", "Rc", "Raio de garganta de Poros (mm)"],
        }

        self.cboxes = {}
        for cbox in (
            "Volume Fraction Column",
            "Throat Radius Column",
        ):
            self.cboxes[cbox] = qt.QComboBox()
            import_layout.addRow(cbox, self.cboxes[cbox])

    def __change_import_table(self, item):
        node = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(item)

        for cbox in self.cboxes.values():
            cbox.clear()

        if node is None:
            return

        columns = []
        for volume_index in range(node.GetNumberOfColumns()):
            columns.append(node.GetColumnName(volume_index))

        for key, cbox in self.cboxes.items():
            for column in columns:
                cbox.addItem(column)

        for key in self.default_options.keys():
            cbox = self.cboxes[key]
            options_found = [column for column in columns if column in self.default_options[key]]
            if options_found:
                cbox.setCurrentText(options_found[0])

    def get_params(self):
        if self.throatRadiusSelector.currentNode() is None:
            return

        df = dataframeFromTable(self.throatRadiusSelector.currentNode())
        df = df.replace("", np.nan)
        df = df.astype("float32")

        Rc = df[self.cboxes["Throat Radius Column"].currentText].to_numpy()
        Fvol = df[self.cboxes["Volume Fraction Column"].currentText].to_numpy()

        return {"throat radii": Rc, "capillary pressure": None, "dsn": Fvol}

    def get_subradius_function(self, pore_network, volume):
        params = self.get_params()
        func = self.logic.get_capillary_pressure_function(params, pore_network, volume)
        return func


class PressureCurveWidget(qt.QWidget):
    STR = "Pressure Curve"

    def __init__(self):
        super().__init__()
        self.logic = MercurySimulationLogic.PressureCurveLogic()
        import_layout = qt.QFormLayout(self)

        instructions_labels = qt.QLabel(
            "To import a pressure curve, first add it to the scene in File -> Advanced Add Data"
        )
        import_layout.addWidget(instructions_labels)

        self.pressureCurveSelector = hierarchyVolumeInput(hasNone=True, nodeTypes=["vtkMRMLTableNode"])
        self.pressureCurveSelector.setToolTip("Select input (optional)")
        self.pressureCurveSelector.clearSelection()
        self.pressureCurveSelector.setToolTip('Pick a Table node of type "pore_table".')
        self.pressureCurveSelector.objectName = "Pressure Curve Selector"
        import_layout.addRow("Pressure Curve Table", self.pressureCurveSelector)
        self.pressureCurveSelector.currentItemChanged.connect(self.__change_import_table)

        self.default_options = {
            "Volume Fraction Column": ["dsn", "Fvol", "Fração do Volume Poroso"],
            "Throat Pressure Column": ["pressure", "capillar pressure", "pc"],
        }

        self.cboxes = {}
        for cbox in (
            "Volume Fraction Column",
            "Throat Pressure Column",
        ):
            self.cboxes[cbox] = qt.QComboBox()
            import_layout.addRow(cbox, self.cboxes[cbox])

    def __change_import_table(self, item):
        node = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(item)

        for cbox in self.cboxes.values():
            cbox.clear()

        if node is None:
            return

        columns = []
        for volume_index in range(node.GetNumberOfColumns()):
            columns.append(node.GetColumnName(volume_index))

        for key, cbox in self.cboxes.items():
            for column in columns:
                cbox.addItem(column)

        for key in self.default_options.keys():
            cbox = self.cboxes[key]
            options_found = [column for column in columns if column in self.default_options[key]]
            if options_found:
                cbox.setCurrentText(options_found[0])

    def get_params(self):
        if self.pressureCurveSelector.currentNode() is None:
            return

        df = dataframeFromTable(self.pressureCurveSelector.currentNode())
        df = df.replace("", np.nan)
        df = df.astype("float32")

        Pc = df[self.cboxes["Throat Pressure Column"].currentText].to_numpy()
        Fvol = df[self.cboxes["Volume Fraction Column"].currentText].to_numpy()

        return {"throat radii": None, "capillary pressure": Pc, "dsn": Fvol}

    def get_subradius_function(self, pore_network, volume):
        params = self.get_params()
        func = self.logic.get_capillary_pressure_function(params, pore_network, volume)
        return func


class LeverettWidgetBase(qt.QWidget):
    STR = "Leverett Function - Permeability curve"

    def __init__(self):
        super().__init__()
        self.parameters_layout = qt.QFormLayout(self)
        self.logic = None

        self.j_input = DirOrFileWidget(
            settingKey="LeverettWidget/LastPath", filters="Any files (*)", fileCaption="Choose csv file"
        )
        self.j_input.chooseDirButton.setVisible(False)
        self.warningsLabel = qt.QLabel("")
        self.warningsLabel.setWordWrap(True)
        self.warningsLabel.setStyleSheet(
            "QLabel { color: red; font: bold 14px;" "background-color: black; padding: 6px;}"
        )

        self.parameters_layout.addRow("J Leverett function table: ", self.j_input)
        self.parameters_layout.addWidget(self.warningsLabel)

    def onLeverettTableSelect(self, path=None):
        if path == None:
            path = self.microporeJInput.path
        if (path == "") or (path == "."):
            error_text = "No table selected"
            return
        table = read_csv(Path(path), whitelist=[",", ";", ":", "|", "\t"])
        missing_variables = []
        if "J" not in table.columns:
            missing_variables.append("J")
        if "Sw" not in table.columns:
            missing_variables.append("Sw")
        if len(missing_variables) == 0:
            error_text = ""
        else:
            error_text = f"Missing variable(s): {', '.join(missing_variables)}"
            error_text += f"\nVariables found: {table.columns.values}".replace("\\t", " ")
            self.warningsLabel.setText(error_text)

    def load_j_table(self):
        path = self.j_input.path
        table = read_csv(Path(path), whitelist=[",", ";", ":", "|", "\t"])
        J = table["J"].astype(float).to_numpy()
        Sw = table["Sw"].astype(float).to_numpy()

        return {"J": J, "Sw": Sw}

    def get_subradius_function(self, pore_network, volume):
        params = self.get_params()
        func = self.logic.get_capillary_pressure_function(params, pore_network, volume)
        return func


class LeverettOldWidget(LeverettWidgetBase):
    STR = "Leverett Function - Permeability curve"

    def __init__(self):
        super().__init__()
        self.logic = MercurySimulationLogic.LeverettOldLogic()

        self.kModelCombo = qt.QComboBox()
        self.kModelCombo.addItems(("k = a * phi ** b",))
        self.kModelCombo.setCurrentIndex(0)
        self.kModelCombo.setToolTip("Choose Permeability model")
        self.kModelCombo.objectName = "Permeability Model Selector"
        self.kParameterA = floatParam(0.00001)
        self.kParameterB = floatParam(3.2)

        self.parameters_layout.addRow("Permeability Model: ", self.kModelCombo)
        self.parameters_layout.addRow("a: ", self.kParameterA)
        self.parameters_layout.addRow("b: ", self.kParameterB)

    def get_params(self):
        params = self.load_j_table()
        params.update(
            {
                "model": self.kModelCombo.currentText,
                "corey_a": float(self.kParameterA.text),
                "corey_b": float(self.kParameterB.text),
            }
        )
        return params


class LeverettNewWidget(LeverettWidgetBase):
    STR = "Leverett Function - Sample Permeability"

    def __init__(self):
        super().__init__()
        self.logic = MercurySimulationLogic.LeverettNewLogic()

        self.permeability_edit = floatParam(1.0)

        self.parameters_layout.addRow("Sample permeability [mD]: ", self.permeability_edit)

    def get_params(self):
        params = self.load_j_table()
        params.update(
            {
                "permeability": float(self.permeability_edit.text),
            }
        )
        return params


SubscaleLogicDict = {
    FixedRadiusWidget.STR: MercurySimulationLogic.FixedRadiusLogic,
    LeverettNewWidget.STR: MercurySimulationLogic.LeverettNewLogic,
    LeverettOldWidget.STR: MercurySimulationLogic.LeverettOldLogic,
    PressureCurveWidget.STR: MercurySimulationLogic.PressureCurveLogic,
    ThroatRadiusCurveWidget.STR: MercurySimulationLogic.PressureCurveLogic,
}
