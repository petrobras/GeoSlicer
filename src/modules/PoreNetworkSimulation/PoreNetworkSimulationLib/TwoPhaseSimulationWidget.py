import copy

import ctk
import numpy as np
import qt
import slicer

import ltrace.slicer.widget.simulation as simulation_widgets
from MercurySimulationLib.MercurySimulationWidget import MercurySimulationWidget
from ltrace.pore_networks.pnflow_parameter_defs import PARAMETERS
from ltrace.pore_networks.simulation_parameters_node import (
    parameter_node_to_dict,
    save_dict_to_parameter_node,
    TWO_PHASE_SIMULATION_TYPE,
)
from ltrace.pore_networks.simulation_parameters_widgets import LoadParamsLayout, SaveParamsLayout
from ltrace.pore_networks.subres_models import get_pore_network_volume_data
from ltrace.slicer.app import MANUAL_BASE_URL
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.slicer_utils import dataframeFromTable, slicer_is_in_developer_mode


class TwoPhaseParametersEditDialog:
    def __init__(self, node):
        self.node = node

    def show(self):
        dialog = qt.QDialog(slicer.modules.AppContextInstance.mainWindow)
        dialog.setWindowTitle("Sensibility Parameters Edit")
        dialog.setWindowFlags(dialog.windowFlags() & ~qt.Qt.WindowContextHelpButtonHint)

        formLayout = qt.QFormLayout()

        twoPhaseWidget = TwoPhaseSimulationWidget(hide_parameters_io=True)
        twoPhaseWidget.parameterInputWidget.setCurrentNode(self.node)
        twoPhaseWidget.onParameterInputLoad()

        scroll = qt.QScrollArea()
        scroll.setVerticalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOn)
        scroll.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)
        scroll.setWidget(twoPhaseWidget)
        scroll.setMinimumSize(800, 800)
        formLayout.addRow(scroll)

        buttonBox = qt.QDialogButtonBox(qt.Qt.Horizontal)
        buttonBox.setStandardButtons(qt.QDialogButtonBox.Cancel | qt.QDialogButtonBox.Ok)
        formLayout.addRow(buttonBox)

        buttonBox.accepted.connect(dialog.accept)
        buttonBox.rejected.connect(dialog.reject)

        dialog.setLayout(formLayout)

        status = dialog.exec()

        if status:
            parameterValues = twoPhaseWidget.getParams()

            if self.node:
                name = self.node.GetName()
                outNode = save_dict_to_parameter_node(
                    parameterValues, name, self.node, update_current_node=True, node_type=TWO_PHASE_SIMULATION_TYPE
                )
            else:
                name = "simulation_input_parameters"
                outNode = save_dict_to_parameter_node(
                    parameterValues, name, self.node, node_type=TWO_PHASE_SIMULATION_TYPE
                )

            outNode.SetName(name)
            return status, outNode

        return status, None


class TwoPhaseSimulationWidget(qt.QFrame):
    DEFAULT_VALUES = {
        "sensibility test": False,
        "final angle": 160,
        "angle steps": 5,
        "keep_temporary": False,
        "create_sequence": False,
        "subres_model_name": "Fixed Radius",
        "subres_params": {"radius": 1.0},
        "subres_shape_factor": 0.04,
        "subres_porositymodifier": 1.0,
    }

    WIDGET_TYPES = {
        "singleint": simulation_widgets.SinglestepIntWidget,
        "singlefloat": simulation_widgets.SinglestepEditWidget,
        "multifloat": simulation_widgets.MultistepEditWidget,
        "checkbox": simulation_widgets.CheckboxWidget,
        "singlecheckbox": simulation_widgets.SingleCheckboxWidget,
        "combobox": simulation_widgets.ComboboxWidget,
        "integerspinbox": simulation_widgets.IntegerSpinBoxWidget,
    }

    def __init__(self, hide_parameters_io=False):
        super().__init__()
        layout = qt.QFormLayout(self)
        self.widgets = {}
        self.labels = {}
        self.currentNode = None

        # Parameters Input/Output Sections
        self.loadParamsLayout = LoadParamsLayout(TWO_PHASE_SIMULATION_TYPE, self.onParameterInputLoad)
        self.parameterInputLoadCollapsible = self.loadParamsLayout.collapsible
        self.parameterInputWidget = self.loadParamsLayout.parameterInputWidget

        self.saveParamsLayout = SaveParamsLayout("two_phase_sim_input_parameters", self.onParameterInputSave)
        self.parameterInputLineEdit = self.saveParamsLayout.lineEdit

        if not hide_parameters_io:
            layout.addRow(self.loadParamsLayout)
            layout.addRow(self.saveParamsLayout)

        # Execution mode
        optionsLayout = qt.QHBoxLayout()
        optionsLayout.setAlignment(qt.Qt.AlignLeft)
        optionsLayout.setContentsMargins(0, 0, 0, 0)
        self.localQRadioButton = qt.QRadioButton("Local")
        self.remoteQRadioButton = qt.QRadioButton("Remote")
        optionsLayout.addWidget(self.localQRadioButton, 0, qt.Qt.AlignCenter)
        optionsLayout.addWidget(self.remoteQRadioButton, 0, qt.Qt.AlignCenter)
        self.localQRadioButton.setChecked(True)
        layout.addRow("Execution Mode:", optionsLayout)
        layout.addRow(" ", None)

        self.simulator_combo_box = qt.QComboBox()
        self.simulator_combo_box.objectName = "Simulator Selector"
        self.simulator_combo_box.addItem("py_pore_flow")
        self.simulator_combo_box.addItem("pnflow")
        self.simulator_combo_box.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)
        self.simulator_combo_box.currentTextChanged.connect(self.onChangedSimulator)
        simulator_label = qt.QLabel("Simulator:")
        simulator_layout = qt.QHBoxLayout()
        simulator_layout.addWidget(simulator_label)
        simulator_layout.addWidget(self.simulator_combo_box)
        layout.addRow(simulator_layout)

        self.direction_combo_box = qt.QComboBox()
        self.direction_combo_box.objectName = "Simulation Direction"
        self.direction_combo_box.addItem("Z")
        self.direction_combo_box.addItem("Y")
        self.direction_combo_box.addItem("X")
        self.direction_combo_box.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)
        direction_label = qt.QLabel("Simulation Direction:")
        direction_layout = qt.QHBoxLayout()
        direction_layout.addWidget(direction_label)
        direction_layout.addWidget(self.direction_combo_box)
        layout.addRow(direction_layout)

        ### Two-phase fluids properties inputs

        # Fluid Properties
        fluidPropertiesBox = qt.QGroupBox()
        fluidPropertiesBox.setTitle("Fluid properties      ")
        manualUrl = MANUAL_BASE_URL + "Volumes/PNM/PNM.html#fluid-properties"
        helpButton = HelpButton(f"### [Fluid properties]({manualUrl}) section of GeoSlicer Manual.")
        helpButton.setFixedSize(20, 20)
        helpButton.setParent(fluidPropertiesBox)
        helpButton.move(103, 0)

        fluidPropertiesLayout = qt.QFormLayout(fluidPropertiesBox)
        fluidPropertiesLayout.setContentsMargins(11, 9, 11, 5)
        layout.addRow(fluidPropertiesBox)

        for layout_name, display_string in (
            ("water_parameters", "Water parameters"),
            ("oil_parameters", "Oil parameters"),
        ):
            collapsible = ctk.ctkCollapsibleButton()
            collapsible.text = display_string
            collapsible.flat = True
            collapsible.collapsed = False
            new_layout = qt.QFormLayout(collapsible)
            self.add_widgets(
                target_layout=new_layout,
                source_layout_name=layout_name,
                widgets_list=self.widgets,
                label_list=self.labels,
            )
            fluidPropertiesLayout.addRow(collapsible)

        self.add_widgets(
            target_layout=fluidPropertiesLayout,
            source_layout_name="fluid_properties",
            widgets_list=self.widgets,
            label_list=self.labels,
        )

        # contact angle
        self.contactAngleBox = qt.QGroupBox()
        self.contactAngleBox.setTitle("Contact angle options      ")
        self.contactAngleLayout = qt.QFormLayout(self.contactAngleBox)
        self.contactAngleLayout.setContentsMargins(11, 9, 11, 5)
        manualUrl = MANUAL_BASE_URL + "Volumes/PNM/PNM.html#contact-angle-options"
        helpButton = HelpButton(f"### [Contact angle options]({manualUrl}) section of GeoSlicer Manual.")
        helpButton.setFixedSize(20, 20)
        helpButton.setParent(self.contactAngleBox)
        helpButton.move(142, 0)
        layout.addRow(self.contactAngleBox)

        for layout_name, display_string in (
            ("label", "Drainage contact angle"),
            ("init", "Initial Contact Angle"),
            ("second", "Initial Contact Angle - Second distribution"),
            ("label", "Imbibition contact angle"),
            ("equil", "Equilibrium Contact angle"),
            ("frac", "Equilibrium Contact Angle - Second distribution"),
        ):
            if layout_name == "label":
                q_label = qt.QLabel(display_string)
                self.contactAngleLayout.addRow(q_label)
                continue
            collapsible = ctk.ctkCollapsibleButton()
            collapsible.text = display_string
            collapsible.flat = True
            collapsible.collapsed = True
            new_layout = qt.QFormLayout(collapsible)
            self.add_widgets(
                target_layout=new_layout,
                source_layout_name=layout_name,
                widgets_list=self.widgets,
                label_list=self.labels,
            )
            self.contactAngleLayout.addRow(collapsible)
        self.add_widgets(
            target_layout=self.contactAngleLayout,
            source_layout_name="contact_angle_options",
            widgets_list=self.widgets,
            label_list=self.labels,
        )

        # simulation options
        self.simulationOptionsBox = qt.QGroupBox()
        self.simulationOptionsBox.setTitle("Simulation options      ")
        self.simulationOptionsLayout = qt.QFormLayout(self.simulationOptionsBox)
        self.simulationOptionsLayout.setContentsMargins(11, 9, 11, 5)
        manualUrl = MANUAL_BASE_URL + "Volumes/PNM/PNM.html#simulation-options"
        helpButton = HelpButton(f"### [Simulation options]({manualUrl}) section of GeoSlicer Manual.")
        helpButton.setFixedSize(20, 20)
        helpButton.setParent(self.simulationOptionsBox)
        helpButton.move(122, 0)
        layout.addRow(self.simulationOptionsBox)
        for layout_name, display_string in (
            ("cycle_1", "Drainage"),
            ("cycle_2", "Imbibition"),
            ("pore_fill", "Pore fill"),
        ):
            collapsible = ctk.ctkCollapsibleButton()
            collapsible.text = display_string
            collapsible.flat = True
            collapsible.collapsed = True
            new_layout = qt.QFormLayout(collapsible)
            self.add_widgets(
                target_layout=new_layout,
                source_layout_name=layout_name,
                widgets_list=self.widgets,
                label_list=self.labels,
            )
            self.simulationOptionsLayout.addRow(collapsible)
        self.add_widgets(
            target_layout=self.simulationOptionsLayout,
            source_layout_name="options",
            widgets_list=self.widgets,
            label_list=self.labels,
        )

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

        fluidPropertiesBox.setStyleSheet(style_sheet)
        self.contactAngleBox.setStyleSheet(style_sheet)
        self.simulationOptionsBox.setStyleSheet(style_sheet)

        self.infoLabel = qt.QLabel()
        layout.addRow(self.infoLabel)

        self.widgets["create_sequence"].stateChanged.connect(self.onCreateSequenceChecked)

        for key, widget in self.widgets.items():
            if isinstance(widget, simulation_widgets.MultistepEditWidget):
                widget.stepChanged.connect(self.updateSimulationCount)

        self.updateSimulationCount()

        self.mercury_widget = MercurySimulationWidget()
        if not hide_parameters_io:
            layout.addRow(self.mercury_widget)

        self.widgets["init_contact_distribution"].currentTextChanged.connect(
            lambda: self.onChangedContactDistrib("init_contact_distribution")
        )
        self.widgets["equil_contact_distribution"].currentTextChanged.connect(
            lambda: self.onChangedContactDistrib("equil_contact_distribution")
        )
        self.widgets["init_contact_model"].currentTextChanged.connect(
            lambda: self.onChangedContactModel("init_contact_model")
        )
        self.widgets["equil_contact_model"].currentTextChanged.connect(
            lambda: self.onChangedContactModel("equil_contact_model")
        )
        self.widgets["second_contact_fraction"].valueChanged.connect(
            lambda: self.onChangedFraction("second_contact_fraction")
        )
        self.widgets["frac_contact_angle_fraction"].valueChanged.connect(
            lambda: self.onChangedFraction("frac_contact_angle_fraction")
        )
        self.widgets["frac_contact_method"].currentTextChanged.connect(
            lambda: self.onChangedFraction("frac_contact_angle_fraction")
        )
        self.updateFieldsActivation()

        if not slicer_is_in_developer_mode():
            self.labels["create_drainage_snapshot"].setVisible(False)
            self.widgets["create_drainage_snapshot"].setVisible(False)

    def create_custom_widget(self, name, params):
        full_params = params.copy()
        full_params["parameter_name"] = name
        new_widget = self.WIDGET_TYPES[params["dtype"]](**full_params)
        return new_widget

    def add_widgets(self, target_layout, source_layout_name, widgets_list, label_list):
        for widget_name, widget_params in (i for i in PARAMETERS.items() if i[1]["layout"] == source_layout_name):
            if widget_params.get("hidden", False):
                continue

            _widget_params = widget_params
            if widget_name == "batch_invasions" and slicer_is_in_developer_mode():
                _widget_params = copy.deepcopy(widget_params)
                _widget_params["display_names"]["Full"] = "full"

            new_widget = self.create_custom_widget(widget_name, _widget_params)
            new_label = qt.QLabel(_widget_params["display_name"])
            if "enabled" in _widget_params:
                enable = _widget_params["enabled"]
                new_label.setEnabled(enable)
                new_widget.setEnabled(enable)
            if "tooltip" in _widget_params:
                new_label = simulation_widgets.TooltipLabel(_widget_params["display_name"])
                new_label.setToolTip(_widget_params["tooltip"])
            target_layout.addRow(new_label, new_widget)
            widgets_list[widget_name] = new_widget
            label_list[widget_name] = new_label

    def updateFieldsActivation(self):
        self.onChangedContactDistrib("init_contact_distribution")
        self.onChangedContactDistrib("equil_contact_distribution")
        self.onChangedContactModel("init_contact_model")
        self.onChangedContactModel("equil_contact_model")
        self.onChangedFraction("second_contact_fraction")
        self.onChangedFraction("frac_contact_angle_fraction")

    def onChangedSimulator(self, simulator):
        if simulator == "pnflow":
            for stage in ["init", "equil", "frac", "second"]:
                self.widgets[f"{stage}_contact_distribution"].combo_box.setCurrentText("Weibull")
                self.widgets[f"{stage}_contact_distribution"].setEnabled(False)
        else:
            for stage in ["init", "equil", "frac", "second"]:
                self.widgets[f"{stage}_contact_distribution"].setEnabled(True)

    def onChangedContactDistrib(self, name):
        text = self.widgets[name].get_text()
        prefix = name.split("_")[0]
        for i in range(self.widgets[f"{prefix}_contact_angle_eta"].count()):
            widget = self.widgets[f"{prefix}_contact_angle_eta"].itemAt(i).widget()
            widget.setEnabled(text == "Weibull")
        for i in range(self.widgets[f"{prefix}_contact_angle_del"].count()):
            widget = self.widgets[f"{prefix}_contact_angle_del"].itemAt(i).widget()
            widget.setEnabled(text == "Weibull")
        for i in range(self.widgets[f"{prefix}_contact_angle_sig"].count()):
            widget = self.widgets[f"{prefix}_contact_angle_sig"].itemAt(i).widget()
            widget.setEnabled(text == "Gaussian")

    def onChangedContactModel(self, name):
        text = self.widgets[name].get_text()
        prefix = name.split("_")[0]
        if text != "Model 2 (constant difference)":
            self.widgets[f"{prefix}_contact_angle_separation"].steps.setText("1")
        for i in range(self.widgets[f"{prefix}_contact_angle_separation"].count()):
            widget = self.widgets[f"{prefix}_contact_angle_separation"].itemAt(i).widget()
            widget.setEnabled(text == "Model 2 (constant difference)")

    def onChangedFraction(self, name):
        fracion_widget = self.widgets[name]
        if fracion_widget.get_steps() >= 1 and (fracion_widget.get_start() > 0.0 or fracion_widget.get_stop() > 0.0):
            state = True
        else:
            state = False

        prefix = name.split("_")[0]

        filt_widgets = {k: v for k, v in self.widgets.items() if k.startswith(f"{prefix}_") and k != name}
        for widget_name, widget in filt_widgets.items():
            enable_widget = state
            if widget_name.startswith("frac_cluster_"):
                if self.widgets["frac_contact_method"].get_value() != "corr":
                    enable_widget = False
            for i in range(widget.count()):
                widget.itemAt(i).widget().setEnabled(enable_widget)

        if prefix == "frac":
            enable_widget = state
            if self.widgets["frac_contact_method"].get_value() != "corr":
                enable_widget = False
            self.widgets["oilInWCluster"].setEnabled(enable_widget)

    def setCurrentNode(self, currentNode):
        self.currentNode = currentNode
        self.mercury_widget.setVolumeNode(currentNode)

    def setParams(self, params):
        mercury_params = {
            "subres_model_name": params.get("subres_model_name"),
            "subres_params": params.get("subres_params"),
            "subres_porositymodifier": params.get("subres_porositymodifier"),
            "subres_shape_factor": params.get("subres_shape_factor"),
        }
        self.mercury_widget.setParams(mercury_params)

    def getParams(self, pore_table_node=None):
        parameters_dict = {}

        for widget in self.widgets.values():
            parameter = widget.get_name()
            if parameter not in parameters_dict:
                parameters_dict[parameter] = {}
            if isinstance(widget, simulation_widgets.MultistepEditWidget):
                parameters_dict[parameter]["start"] = widget.get_start()
                parameters_dict[parameter]["stop"] = widget.get_stop()
                parameters_dict[parameter]["steps"] = widget.get_steps()
                parameters_dict[parameter]["conversion_factor"] = widget.get_conversion_factor()
                if widget.step_spacing == "logarithmic":
                    parameters_dict[parameter]["step_spacing"] = widget.step_spacing
            else:
                parameters_dict[parameter] = widget.get_value()

        parameters_dict["simulator"] = self.simulator_combo_box.currentText

        geo_display_direction = self.direction_combo_box.currentText
        if geo_display_direction == "X":
            numpy_direction = "z"
        elif geo_display_direction == "Y":
            numpy_direction = "y"
        elif geo_display_direction == "Z":
            numpy_direction = "x"
        else:
            numpy_direction = geo_display_direction
        parameters_dict["direction"] = numpy_direction

        subres_model_name = self.mercury_widget.subscaleModelWidget.microscale_model_dropdown.currentText
        raw_subres_params = self.mercury_widget.subscaleModelWidget.parameter_widgets[subres_model_name].get_params()
        subres_params = raw_subres_params
        if (subres_model_name in ("Throat Radius Curve", "Pressure Curve")) and raw_subres_params:
            node = slicer.mrmlScene.GetNodeByID(raw_subres_params["node id"])
            if node is not None:
                df = dataframeFromTable(node)
                df = df.replace("", np.nan)
                df = df.astype("float32")
                subres_params = dict(raw_subres_params)
                if subres_model_name == "Throat Radius Curve":
                    subres_params["throat radii"] = df[raw_subres_params["throat radii"]].tolist()
                    subres_params["dsn"] = df[raw_subres_params["dsn"]].tolist()
                else:
                    subres_params["capillary pressure"] = df[raw_subres_params["capillary pressure"]].tolist()
                    subres_params["dsn"] = df[raw_subres_params["dsn"]].tolist()

        parameters_dict["subres_model_name"] = subres_model_name
        parameters_dict["subres_params"] = subres_params

        mercury_widget_params = self.mercury_widget.getParams(pore_table_node)
        shape_factor = mercury_widget_params["subres_shape_factor"]
        subres_porositymodifier = mercury_widget_params["subres_porositymodifier"]
        parameters_dict["subres_shape_factor"] = shape_factor
        parameters_dict["subres_porositymodifier"] = subres_porositymodifier

        parameters_dict["skip_imbibition"] = False
        parameters_dict["remote_execution"] = "T" if self.remoteQRadioButton.isChecked() else "F"

        if pore_table_node:
            scalar_volume_data = get_pore_network_volume_data(pore_table_node)
            parameters_dict.update(scalar_volume_data)

        parameters_dict["save_tables"] = slicer_is_in_developer_mode()

        return parameters_dict

    def onCreateSequenceChecked(self, state):
        self.updateSimulationCount()

    def updateSimulationCount(self):
        simulation_count = 1
        for widget in self.widgets.values():
            if isinstance(widget, simulation_widgets.MultistepEditWidget):
                simulation_count *= widget.get_steps()

        sequence_widget = self.widgets["create_sequence"]
        if sequence_widget.checked and simulation_count >= 10:
            self.displayInfo(
                f"Simulations to be run: {simulation_count}. One animation will be generated for each simulation. This may take a very long time.",
                warning=True,
            )
            sequence_widget.setStyleSheet(
                """QCheckBox {
                    color: yellow;
                }"""
            )
        else:
            self.displayInfo(f"Simulations to be run: {simulation_count}")
            sequence_widget.setStyleSheet("")

    def displayInfo(self, text, warning=False):
        self.infoLabel.setText(text)
        if warning:
            self.infoLabel.setStyleSheet("color: yellow;")
        else:
            self.infoLabel.setStyleSheet("")

    def onParameterInputLoad(self):
        selectedNode = self.parameterInputWidget.currentNode()
        if selectedNode:
            parameters_dict = parameter_node_to_dict(selectedNode)

            if "batch_invasions" in parameters_dict:
                if parameters_dict["batch_invasions"] in ("T", True):
                    parameters_dict["batch_invasions"] = "partial"
                elif parameters_dict["batch_invasions"] in ("F", False):
                    parameters_dict["batch_invasions"] = "none"

            for name, widget in self.widgets.items():
                if name in parameters_dict:
                    if isinstance(widget, simulation_widgets.MultistepEditWidget):
                        values = parameters_dict[name]
                        widget.set_value(values["start"], values["stop"])
                        widget.set_steps(values["steps"])
                    else:
                        value = parameters_dict[name]
                        widget.set_value(value)

            self.mercury_widget.subscaleModelWidget.setParams(parameters_dict)

            self.parameterInputLoadCollapsible.collapsed = True
            self.updateFieldsActivation()

    def onParameterInputSave(self):
        parameterValues = self.getParams(self.currentNode)
        parameterNode = save_dict_to_parameter_node(
            parameterValues, self.parameterInputLineEdit.text, self.currentNode, node_type=TWO_PHASE_SIMULATION_TYPE
        )
        slicer.app.applicationLogic().GetSelectionNode().SetActiveTableID(parameterNode.GetID())
        slicer.app.applicationLogic().PropagateTableSelection()

    def uncheckCreateSnapshot(self):
        self.widgets["create_drainage_snapshot"].set_value("F")
