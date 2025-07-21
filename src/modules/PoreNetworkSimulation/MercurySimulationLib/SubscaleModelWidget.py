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
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.slicer_utils import dataframeFromTable
from ltrace.file_utils import read_csv
from ltrace.pore_networks.subres_models import MODEL_DICT


class SubscaleModelWidget(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = qt.QFormLayout(self)

        self.parameter_widgets = {}

        for widget in (
            FixedRadiusWidget,
            TruncatedGaussianWidget,
            LeverettNewWidget,
            LeverettOldWidget,
            PressureCurveWidget,
            ThroatRadiusCurveWidget,
        ):
            self.parameter_widgets[widget.STR] = widget()

        porositymodifier_helpbutton = HelpButton(
            "Modifies subscale porosity.\n"
            "Values lower than 1 increase subscale porosity.\n"
            "Values higher than 1 decrease subscale porosity.\n"
            'Considering an effective porosity "p*", a real'
            ' porosity "p" and a calibration factor "c":'
            " If c <= 1 :"
            "    p\\* = 1 - (1-p) \\* c"
            " If c > 1:"
            "    p\\* = p / c"
        )
        self.porositymodifier_edit = floatParam(1.0)
        hbox = qt.QHBoxLayout()
        hbox.addWidget(self.porositymodifier_edit)
        hbox.addWidget(porositymodifier_helpbutton)
        layout.addRow(
            "Capillary porosity modifier",
            hbox,
        )

        shapefactor_helpbutton = HelpButton(
            "Defines Shape factor of subresolution capillary elements.\n"
            "Values must be between 0.01 and 0.09.\n"
            "Values under or equal to 0.04 result in triangular cross"
            " section, values greater or equal than 0.071 result in circular"
            " cross section."
        )
        self.subresolution_shapefactor_edit = floatParam(0.040)
        hbox = qt.QHBoxLayout()
        hbox.addWidget(self.subresolution_shapefactor_edit)
        hbox.addWidget(shapefactor_helpbutton)
        layout.addRow(
            "Capillary pore shape factor",
            hbox,
        )

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
        subres_shape_factor = float(self.subresolution_shapefactor_edit.text)
        subres_porositymodifier = float(self.porositymodifier_edit.text)

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
            "subres_model_name": subres_model_name,
            "subres_params": subres_params_copy,
            "subres_shape_factor": subres_shape_factor,
            "subres_porositymodifier": subres_porositymodifier,
        }

    def setParams(self, params):
        self.microscale_model_dropdown.setCurrentText(params["subres_model_name"])


class FixedRadiusWidget(qt.QWidget):
    STR = "Fixed Radius"

    def __init__(self):
        super().__init__()
        layout = qt.QFormLayout(self)
        self.logic = MODEL_DICT[self.STR]

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
        func = self.logic.get_capillary_radius_function(params, pore_network, volume)
        return func


class TruncatedGaussianWidget(qt.QWidget):
    STR = "Truncated Gaussian"

    def __init__(self):
        super().__init__()
        layout = qt.QFormLayout(self)
        self.logic = MODEL_DICT[self.STR]

        self.mean_radius = ui.floatParam()
        self.mean_radius.text = 0.10
        layout.addRow("Mean radius (mm): ", self.mean_radius)

        self.micropore_std = ui.floatParam()
        self.micropore_std.text = 0.02
        layout.addRow("Radius standard deviation: ", self.micropore_std)

        self.minimum_radius = ui.floatParam()
        self.minimum_radius.text = 0.05
        layout.addRow("Min radius cutoff (mm): ", self.minimum_radius)

        self.maximum_radius = ui.floatParam()
        self.maximum_radius.text = 0.15
        layout.addRow("Max radius cutoff (mm): ", self.maximum_radius)

    def get_params(self):
        params = {
            "mean radius": float(self.mean_radius.text),
            "standard deviation": float(self.micropore_std.text),
            "min radius": float(self.minimum_radius.text),
            "max radius": float(self.maximum_radius.text),
        }
        return params

    def get_subradius_function(self, pore_network, volume):
        params = self.get_params()
        func = self.logic.get_capillary_radius_function(params, pore_network, volume)
        return func


class ThroatRadiusCurveWidget(qt.QWidget):
    STR = "Throat Radius Curve"

    def __init__(self):
        super().__init__()
        self.logic = MODEL_DICT[self.STR]
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
            "Volume Fraction Column": ["dsn", "Fvol", "Fração do Volume Poroso"],
            "Throat Radius Column": ["pore radii", "radii", "Rc", "Raio de garganta de Poros (mm)"],
        }

        self.cboxes = {}
        for cbox in (
            "Volume Fraction Column",
            "Throat Radius Column",
        ):
            self.cboxes[cbox] = qt.QComboBox()
            import_layout.addRow(cbox, self.cboxes[cbox])

        self.cutoffMultiplierEdit = floatParam(3.0)
        import_layout.addRow("Cutoff Multiplier", self.cutoffMultiplierEdit)

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
        cutoff_multiplier = float(self.cutoffMultiplierEdit.text)

        return {
            "throat radii": Rc,
            "capillary pressure": None,
            "dsn": Fvol,
            "smallest_raddi_multiplier": cutoff_multiplier,
        }

    def get_subradius_function(self, pore_network, volume):
        params = self.get_params()
        func = self.logic.get_capillary_radius_function(params, pore_network, volume)
        return func


class PressureCurveWidget(qt.QWidget):
    STR = "Pressure Curve"

    def __init__(self):
        super().__init__()
        self.logic = MODEL_DICT[self.STR]
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

        return {"throat radii": None, "capillary pressure": Pc, "dsn": Fvol, "smallest_raddi_multiplier": 2.0}

    def get_subradius_function(self, pore_network, volume):
        params = self.get_params()
        func = self.logic.get_capillary_radius_function(params, pore_network, volume)
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
        func = self.logic.get_capillary_radius_function(params, pore_network, volume)
        return func


class LeverettOldWidget(LeverettWidgetBase):
    STR = "Leverett Function - Permeability curve"

    def __init__(self):
        super().__init__()
        self.logic = MODEL_DICT[self.STR]

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
        self.logic = MODEL_DICT[self.STR]

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
