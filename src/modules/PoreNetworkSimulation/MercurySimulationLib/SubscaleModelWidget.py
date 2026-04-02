import ast
import logging
from pathlib import Path

import ctk
import numpy as np
import pandas as pd
import qt
import slicer

from ltrace.file_utils import read_csv
from ltrace.pore_networks.simulation_parameters_node import parameter_node_to_dict
from ltrace.pore_networks.subres_models import MODEL_DICT, estimate_radius, estimate_pressure
from ltrace.pore_networks.subres_models import get_pore_network_volume_data
from ltrace.pore_networks.subres_models import normalize_psd
from ltrace.slicer import ui
from ltrace.slicer.app import MANUAL_BASE_URL
from ltrace.slicer.data_utils import dataFrameToTableNode
from ltrace.slicer.node_attributes import TableType
from ltrace.slicer.ui import (
    hierarchyVolumeInput,
    DirOrFileWidget,
    floatParam,
)
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.slicer_utils import dataframeFromTable, getResourcePath, slicer_is_in_developer_mode

MICRON_TO_MM = 0.001

# Heuristics for auto-parameter detection relative to voxel spacing
SPACING_TO_MEAN_RADIUS = 0.5
SPACING_TO_STD_DEV = 0.5
SPACING_TO_MIN_RADIUS = 0.05
SPACING_TO_MAX_RADIUS = 5.0
SPACING_TO_CUTOFF_RADIUS = 2.0


def get_volume_min_spacing_microns(volume_node):
    if volume_node.GetAttribute("x_spacing") is None and hasattr(volume_node, "GetSpacing"):
        spacing = volume_node.GetSpacing()
        min_spacing = min(spacing[0], spacing[1], spacing[2])
    else:
        scalar_volume_data = get_pore_network_volume_data(volume_node)
        min_spacing = min(
            scalar_volume_data["spacing"]["x"],
            scalar_volume_data["spacing"]["y"],
            scalar_volume_data["spacing"]["z"],
        )
    return min_spacing * 1000


class SubscaleModelWidget(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = qt.QFormLayout(self)

        style_sheet = """
            QGroupBox {
                border: 1px solid #999999;
                border-radius: 3px;
                margin-top: 7px;  /*leave space at the top for the title */
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;    /* position at the top center */
                padding: 0 5px 0 0px;
                font-size: 13px;
            }
        """

        subscaleBox = qt.QGroupBox()
        subscaleBox.setTitle("Subscale properties      ")
        subscaleBox.setStyleSheet(style_sheet)
        manualUrl = MANUAL_BASE_URL + "Volumes/PNM/PNM.html#simulation"
        helpButton = HelpButton(f"### [Subscale properties]({manualUrl}) section of GeoSlicer Manual.")
        helpButton.setFixedSize(20, 20)
        helpButton.setParent(subscaleBox)
        helpButton.move(130, 0)

        formLayout = qt.QFormLayout()

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

        # Parameter input
        self.parameterInputLoadCollapsible = ctk.ctkCollapsibleButton()
        self.parameterInputLoadCollapsible.text = "Load subscale parameters"
        self.parameterInputLoadCollapsible.collapsed = True
        self.parameterInputLoadCollapsible.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Fixed)

        self.parameterInputSelector = ui.hierarchyVolumeInput(hasNone=True, nodeTypes=["vtkMRMLTextNode"])
        self.parameterInputSelector.addNodeAttributeIncludeFilter("table_type", TableType.PNM_INPUT_PARAMETERS.value)
        self.parameterInputSelector.setToolTip("Select a table node containing simulation parameters.")
        self.parameterInputSelector.objectName = "Subscale inputs"

        self.parameterInputLoadButton = qt.QPushButton("Load")
        self.parameterInputLoadButton.setObjectName("Subscale input load button")
        self.parameterInputLoadButton.clicked.connect(self.onParameterInputLoadButtonClicked)

        parameterInputLayout = qt.QFormLayout(self.parameterInputLoadCollapsible)
        parameterInputLayout.addRow("Subscale parameters node:", self.parameterInputSelector)
        parameterInputLayout.addRow(self.parameterInputLoadButton)

        parameterInputLoadIcon = qt.QLabel()
        parameterInputLoadIcon.setPixmap(
            qt.QIcon(getResourcePath("Icons") / "png" / "Load.png").pixmap(qt.QSize(13, 13))
        )
        parameterInputLoadIcon.setSizePolicy(qt.QSizePolicy.Fixed, qt.QSizePolicy.Fixed)
        parameterInputLoadIcon.setContentsMargins(0, 5, 0, 0)

        iconLayout = qt.QVBoxLayout()
        iconLayout.addWidget(parameterInputLoadIcon)
        iconLayout.addStretch()

        hbox = qt.QHBoxLayout()
        hbox.addLayout(iconLayout)
        hbox.setContentsMargins(0, 10, 0, 0)
        hbox.addWidget(self.parameterInputLoadCollapsible)

        formLayout.addRow(hbox)

        self.importSIRRButton = qt.QPushButton("Load SIRR results")
        self.importSIRRButton.setToolTip("Import SIRR CSV file.")
        self.importSIRRButton.clicked.connect(self._onImportSIRRClicked)
        formLayout.addRow(self.importSIRRButton)

        ## parameters
        porositymodifierHelpbutton = HelpButton(
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
        hbox.addWidget(porositymodifierHelpbutton)
        if slicer_is_in_developer_mode():
            formLayout.addRow(
                "Capillary porosity modifier",
                hbox,
            )

        shapefactorHelpbutton = HelpButton(
            "Defines Shape factor of subresolution capillary elements.\n"
            "Values must be between 0.01 and 0.09.\n"
            "Values under or equal to 0.04 result in triangular cross"
            " section, values greater or equal than 0.071 result in circular"
            " cross section."
        )
        self.subresolution_shapefactor_edit = floatParam(0.040)
        hbox = qt.QHBoxLayout()
        hbox.addWidget(self.subresolution_shapefactor_edit)
        hbox.addWidget(shapefactorHelpbutton)
        formLayout.addRow(
            "Capillary pore shape factor",
            hbox,
        )

        self.microscale_model_dropdown = qt.QComboBox()
        self.microscale_model_dropdown.objectName = "Subscale Model Selector"
        formLayout.addRow("Subscale entry pressure model:", self.microscale_model_dropdown)
        for label, widget in self.parameter_widgets.items():
            self.microscale_model_dropdown.addItem(label)
            formLayout.addRow(widget)
            widget.setVisible(False)

        self.parameter_widgets[self.microscale_model_dropdown.currentText].setVisible(True)

        self.microscale_model_dropdown.currentTextChanged.connect(self._onUnresolvedModelChange)

        self.resolution_limit_label = qt.QLabel("Image resolution limit: N/A")
        self.resolution_limit_label.setStyleSheet("font-weight: bold; margin-top: 5px;")

        formLayout.addRow(self.resolution_limit_label)

        subscaleBox.setLayout(formLayout)
        layout.addRow(subscaleBox)

    def _onImportSIRRClicked(self):
        mercury_simulation_widget = self.parent()
        sirr_input_selector = mercury_simulation_widget.getSirrSelector()
        onImportSIRRClicked(self.parameter_widgets, sirr_input_selector)

    def _onUnresolvedModelChange(self, new_text):
        for widget in self.parameter_widgets.values():
            widget.setVisible(False)
        self.parameter_widgets[new_text].setVisible(True)

    def onParameterInputLoadButtonClicked(self):
        parameter_node = self.parameterInputSelector.currentNode()
        if parameter_node is None:
            slicer.util.warningDisplay("No parameter table node selected.")
            return

        parameters_dict = parameter_node_to_dict(parameter_node)
        self.setParams(parameters_dict)

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
        self.subresolution_shapefactor_edit.text = params["subres_shape_factor"]
        self.porositymodifier_edit.text = params["subres_porositymodifier"]

        self.microscale_model_dropdown.setCurrentText(params["subres_model_name"])
        subscale_widget = self.parameter_widgets[params["subres_model_name"]]
        subscale_widget.set_params(params["subres_params"])

    def setVolumeNode(self, volume_node):
        for widget in self.parameter_widgets.values():
            if hasattr(widget, "set_volume_node"):
                widget.set_volume_node(volume_node)

        if volume_node:
            try:
                min_spacing = get_volume_min_spacing_microns(volume_node)
                pressure = estimate_pressure(min_spacing / 1000.0)
                self.resolution_limit_label.text = f"Image resolution limit: {min_spacing:.2f} µm ({pressure:.2f} Pa)"
            except Exception:
                self.resolution_limit_label.text = "Image resolution limit: Error"
        else:
            self.resolution_limit_label.text = "Image resolution limit: N/A"


class FixedRadiusWidget(qt.QWidget):
    STR = "Fixed Radius"

    def __init__(self):
        super().__init__()
        layout = qt.QFormLayout(self)
        self.logic = MODEL_DICT[self.STR]
        self.volume_node = None

        self.micropore_radius = ui.floatParam()
        self.micropore_radius.text = 1

        layout.addRow("Micropore radius (µm): ", self.micropore_radius)

        self.estimate_button = qt.QPushButton("Estimate from input volume")
        self.estimate_button.clicked.connect(self.on_estimate_clicked)
        layout.addRow(self.estimate_button)

    def get_params(self):
        params = {
            "radius": float(self.micropore_radius.text) * MICRON_TO_MM,
        }
        return params

    def set_params(self, params):
        if isinstance(params, str):
            params = ast.literal_eval(params)

        self.micropore_radius.text = str(params["radius"])

    def set_volume_node(self, volume_node):
        self.volume_node = volume_node

    def on_estimate_clicked(self):
        if not self.volume_node:
            return
        try:
            min_spacing_microns = get_volume_min_spacing_microns(self.volume_node)
            self.micropore_radius.text = str(round(min_spacing_microns * SPACING_TO_MEAN_RADIUS, 6))
        except Exception as e:
            logging.debug(f"FixedRadiusWidget: Could not auto-update parameters from volume: {e}")

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
        self.mean_radius.text = 1
        layout.addRow("Mean radius (µm): ", self.mean_radius)

        self.micropore_std = ui.floatParam()
        self.micropore_std.text = 1
        layout.addRow("Radius standard deviation (µm): ", self.micropore_std)

        self.minimum_radius = ui.floatParam()
        self.minimum_radius.text = 0.1
        layout.addRow("Min radius cutoff (µm): ", self.minimum_radius)

        self.maximum_radius = ui.floatParam()
        self.maximum_radius.text = 5
        layout.addRow("Max radius cutoff (µm): ", self.maximum_radius)

        self.volume_node = None
        self.estimate_button = qt.QPushButton("Estimate from input volume")
        self.estimate_button.clicked.connect(self.on_estimate_clicked)
        layout.addRow(self.estimate_button)

    def get_params(self):
        params = {
            "mean radius": float(self.mean_radius.text) * MICRON_TO_MM,
            "standard deviation": float(self.micropore_std.text) * MICRON_TO_MM,
            "min radius": float(self.minimum_radius.text) * MICRON_TO_MM,
            "max radius": float(self.maximum_radius.text) * MICRON_TO_MM,
        }
        return params

    def set_params(self, params):
        if isinstance(params, str):
            params = ast.literal_eval(params)

        self.mean_radius.text = params["mean radius"]
        self.micropore_std.text = params["standard deviation"]
        self.minimum_radius.text = params["min radius"]
        self.maximum_radius.text = params["max radius"]

    def set_volume_node(self, volume_node):
        self.volume_node = volume_node

    def on_estimate_clicked(self):
        if not self.volume_node:
            return
        try:
            min_spacing_microns = get_volume_min_spacing_microns(self.volume_node)
            self.mean_radius.text = str(round(min_spacing_microns * SPACING_TO_MEAN_RADIUS, 6))
            self.micropore_std.text = str(round(min_spacing_microns * SPACING_TO_STD_DEV, 6))
            self.minimum_radius.text = str(round(min_spacing_microns * SPACING_TO_MIN_RADIUS, 6))
            self.maximum_radius.text = str(round(min_spacing_microns * SPACING_TO_MAX_RADIUS, 6))
        except Exception as e:
            logging.debug(f"TruncatedGaussianWidget: Could not auto-update parameters from volume: {e}")

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

        self.subresCutoff = floatParam(1.0)
        import_layout.addRow("Subresolution cutoff radius (µm)", self.subresCutoff)

        self.volume_node = None
        self.estimate_button = qt.QPushButton("Estimate from input volume")
        self.estimate_button.clicked.connect(self.on_estimate_clicked)
        import_layout.addRow(self.estimate_button)

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
        cutoff_radius = float(self.subresCutoff.text) * MICRON_TO_MM

        return {
            "node id": self.throatRadiusSelector.currentNode().GetID(),
            "throat radii": Rc,
            "capillary pressure": None,
            "dsn": Fvol,
            "radii_cutoff_mm": cutoff_radius,
        }

    def set_params(self, params):
        if isinstance(params, str):
            params = ast.literal_eval(params)

        throatRadiusNode = slicer.mrmlScene.GetNodeByID(params["node id"])
        self.throatRadiusSelector.setCurrentNode(throatRadiusNode)
        self.cboxes["Throat Radius Column"].setCurrentText(params["throat radii"])
        self.cboxes["Volume Fraction Column"].setCurrentText(params["dsn"])
        self.subresCutoff.text = params["radii_cutoff_mm"] * 1000

    def set_volume_node(self, volume_node):
        self.volume_node = volume_node

    def on_estimate_clicked(self):
        if not self.volume_node:
            return
        try:
            min_spacing_microns = get_volume_min_spacing_microns(self.volume_node)
            self.subresCutoff.text = str(round(min_spacing_microns * SPACING_TO_CUTOFF_RADIUS, 6))
        except Exception as e:
            logging.debug(f"ThroatRadiusCurveWidget: Could not auto-update parameters from volume: {e}")

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

        return {
            "node id": self.pressureCurveSelector.currentNode().GetID(),
            "throat radii": None,
            "capillary pressure": Pc,
            "dsn": Fvol,
            "radii_cutoff_mm": 1.0,
        }

    def set_params(self, params):
        if isinstance(params, str):
            params = ast.literal_eval(params)

        pressureCurveNode = slicer.mrmlScene.GetNodeByID(params["node id"])
        self.pressureCurveSelector.setCurrentNode(pressureCurveNode)
        self.cboxes["Throat Pressure Column"].setCurrentText(params["capillary pressure"])
        self.cboxes["Volume Fraction Column"].setCurrentText(params["dsn"])

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

    def set_params(self, params):
        if isinstance(params, str):
            params = ast.literal_eval(params)

        self.kModelCombo.text = params["model"]
        self.kParameterA.text = params["corey_a"]
        self.kParameterB.text = params["corey_b"]


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

    def set_params(self, params):
        pass


def onImportSIRRClicked(parameter_widgets, sirr_input_selector):
    file_path = qt.QFileDialog.getOpenFileName(
        None, "Select SIRR CSV file", "", "Data Files (*.csv *.xlsx);;CSV Files (*.csv);;Excel Files (*.xlsx)"
    )
    if not file_path:
        return
    importSIRR(file_path, parameter_widgets, sirr_input_selector)


def importSIRR(file_path, parameter_widgets, sirr_input_selector):
    from ltrace.file_utils import load_and_parse_data

    try:
        loaded_df = load_and_parse_data(Path(file_path), filter_empty_columns=True)
        pc_col = loaded_df["Pressão capilar(psi)"] * 6894.75729  # convert psi → Pa
        df = pd.DataFrame({"pc": pc_col})
        df["snwp"] = loaded_df["Saturação de Hg (%)"] / 100
        df["dsn"] = np.diff(df["snwp"], n=1, prepend=0)
        df["radii"] = estimate_radius(df["pc"])

        tableNode = dataFrameToTableNode(df)
        tableNode.SetName("SIRR imported MICP")
        tableNode.SetAttribute("table_type", "micp")

        normalized_psd_x, normalized_psd_y = normalize_psd(df["pc"].to_numpy(), df["dsn"].to_numpy())
        normalized_psd = pd.DataFrame({"pc": normalized_psd_y, "dsn": normalized_psd_x})
        normPcTableName = slicer.mrmlScene.GenerateUniqueName("Normalized Pressure")
        normPcTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", normPcTableName)
        normPcTable.SetAttribute("table_type", "norm_pc")
        norm_pc_table_id = normPcTable.GetID()
        tableNode.SetAttribute("pc_table_id", norm_pc_table_id)
        _ = dataFrameToTableNode(normalized_psd, normPcTable)

        normalized_radii_x, normalized_radii_y = normalize_psd(df["radii"].to_numpy(), df["dsn"].to_numpy())
        normalized_radius = pd.DataFrame({"radius": normalized_radii_y, "dsn": normalized_radii_x})
        normRadTableName = slicer.mrmlScene.GenerateUniqueName("Normalized Radius")
        normRadTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", normRadTableName)
        normRadTable.SetAttribute("table_type", "norm_radius")
        norm_radius_table_id = normRadTable.GetID()
        tableNode.SetAttribute("radius_table_id", norm_radius_table_id)
        _ = dataFrameToTableNode(normalized_radius, normRadTable)

        if "Throat Radius Curve" in parameter_widgets:
            parameter_widgets["Throat Radius Curve"].throatRadiusSelector.setCurrentNode(tableNode)

        if "Pressure Curve" in parameter_widgets:
            parameter_widgets["Pressure Curve"].pressureCurveSelector.setCurrentNode(tableNode)

        sirr_input_selector.setCurrentNode(tableNode)
    except Exception as e:
        logging.error(f"Failed to import SIRR file: {e}")
