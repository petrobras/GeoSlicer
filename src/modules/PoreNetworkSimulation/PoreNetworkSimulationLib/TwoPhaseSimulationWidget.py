import ctk
import qt
import slicer
import numpy as np

from MercurySimulationLib.MercurySimulationWidget import MercurySimulationWidget

from ltrace.pore_networks.pnflow_parameter_defs import PARAMETERS
from ltrace.pore_networks.simulation_parameters_node import dict_to_parameter_node, parameter_node_to_dict
from ltrace.slicer import ui, helpers
from ltrace.slicer.node_attributes import TableType
from ltrace.slicer_utils import getResourcePath, slicer_is_in_developer_mode
import ltrace.slicer.widget.simulation as simulation_widgets
from ltrace.slicer.widget.help_button import HelpButton


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
            parameterValues, invalidParameter = twoPhaseWidget.getFormParams()
            if parameterValues is None:
                slicer.util.errorDisplay(f"Could not save parameter input. {invalidParameter} has invalid value.")
                return 0, None

            if self.node:
                name = self.node.GetName()
                outNode = dict_to_parameter_node(parameterValues, name, self.node, update_current_node=True)
            else:
                name = "simulation_input_parameters"
                outNode = dict_to_parameter_node(parameterValues, name, self.node)

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
        "subres_params": {"radius": 0.1},
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

        self.parameterInputLoadCollapsible = ctk.ctkCollapsibleButton()
        self.parameterInputLoadCollapsible.text = "Load parameters"
        self.parameterInputLoadCollapsible.collapsed = True
        self.parameterInputWidget = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLTableNode"],
            defaultText="Select node to load parameters from",
        )
        self.parameterInputWidget.objectName = "Parameter input"
        self.parameterInputWidget.addNodeAttributeIncludeFilter(TableType.name(), TableType.PNM_INPUT_PARAMETERS.value)
        self.parameterInputWidget.showEmptyHierarchyItems = False
        parameterInputLoadButton = qt.QPushButton("Load parameters")
        parameterInputLoadButton.objectName = "Parameter input load button"
        parameterInputLoadButton.clicked.connect(self.onParameterInputLoad)
        parameterInputLayout = qt.QFormLayout(self.parameterInputLoadCollapsible)
        parameterInputLayout.addRow("Input parameter node:", self.parameterInputWidget)
        parameterInputLayout.addRow(parameterInputLoadButton)
        parameterInputLoadIcon = qt.QLabel()
        parameterInputLoadIcon.setPixmap(qt.QIcon(getResourcePath("Icons") / "Load.png").pixmap(qt.QSize(13, 13)))
        if not hide_parameters_io:
            layout.addRow(parameterInputLoadIcon, self.parameterInputLoadCollapsible)

        ### Two-phase fluids properties inputs

        # Fluid Properties
        fluidPropertiesBox = qt.QGroupBox()
        fluidPropertiesBox.setTitle("Fluid properties      ")
        help_button = HelpButton(
            f"### [Fluid properties](file:///{getResourcePath('manual')}/Modules/PNM/PNSimulation.html#fluid-properties) section of GeoSlicer Manual."
        )
        help_button.setFixedSize(20, 20)
        help_button.setParent(fluidPropertiesBox)
        help_button.move(103, 0)

        fluidPropertiesLayout = qt.QFormLayout(fluidPropertiesBox)
        fluidPropertiesLayout.setContentsMargins(11, 9, 11, 5)
        layout.addRow(fluidPropertiesBox)

        for layout_name, display_string in (
            ("water_parameters", "Water parameters"),
            ("oil_parameters", "Oil parameters"),
            # ("clay_parameters", "Clay parameters"), # Temporarilly supressed by PL-2002,
            # client will probably request this feature back in the future
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
        help_button = HelpButton(
            f"### [Contact angle options](file:///{getResourcePath('manual')}/Modules/PNM/PNSimulation.html#contact-angle-options) section of GeoSlicer Manual."
        )
        help_button.setFixedSize(20, 20)
        help_button.setParent(self.contactAngleBox)
        help_button.move(142, 0)
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
        help_button = HelpButton(
            f"### [Simulation options](file:///{getResourcePath('manual')}/Modules/PNM/PNSimulation.html#simulation-options) section of GeoSlicer Manual."
        )
        help_button.setFixedSize(20, 20)
        help_button.setParent(self.simulationOptionsBox)
        help_button.move(122, 0)
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

        # self.contactSensitivityBox.setStyleSheet(style_sheet)
        fluidPropertiesBox.setStyleSheet(style_sheet)
        self.contactAngleBox.setStyleSheet(style_sheet)
        self.simulationOptionsBox.setStyleSheet(style_sheet)

        # self.createSequenceCheck.connect("clicked(bool)", self.onAnimationCheckChange)
        # self.contactSensitivityBox.connect("toggled(bool)", self.onSensitivityCheckChange)
        # self.onSensitivityCheckChange()

        self.infoLabel = qt.QLabel()
        layout.addRow(self.infoLabel)

        parameterInputSaveCollapsible = ctk.ctkCollapsibleButton()
        parameterInputSaveCollapsible.text = "Save parameters"
        parameterInputSaveCollapsible.collapsed = True
        self.parameterInputLineEdit = qt.QLineEdit("simulation_input_parameters")
        parameterInputSaveButton = qt.QPushButton("Save parameters")
        parameterInputSaveButton.clicked.connect(self.onParameterInputSave)
        parameterInputLayout = qt.QFormLayout(parameterInputSaveCollapsible)
        parameterInputLayout.addRow("Output parameter node name:", self.parameterInputLineEdit)
        parameterInputLayout.addRow(parameterInputSaveButton)
        parameterInputSaveIcon = qt.QLabel()
        parameterInputSaveIcon.setPixmap(qt.QIcon(getResourcePath("Icons") / "Save.png").pixmap(qt.QSize(13, 13)))
        if not hide_parameters_io:
            layout.addRow(parameterInputSaveIcon, parameterInputSaveCollapsible)

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
            new_widget = self.create_custom_widget(widget_name, widget_params)
            new_label = qt.QLabel(widget_params["display_name"])
            if "enabled" in widget_params:
                enable = widget_params["enabled"]
                new_label.setEnabled(enable)
                new_widget.setEnabled(enable)
            if "tooltip" in widget_params:
                new_label = simulation_widgets.TooltipLabel(widget_params["display_name"])
                new_label.setToolTip(widget_params["tooltip"])
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
        """
        This function is a callback that enable/disable items for the second distribution
        as the Fraction parameter is available.
        """
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

    def getParams(self):
        params = {}

        subres_model_name = self.mercury_widget.subscaleModelWidget.microscale_model_dropdown.currentText
        subres_params = self.mercury_widget.subscaleModelWidget.parameter_widgets[subres_model_name].get_params()
        shape_factor = self.mercury_widget.getParams()["subres_shape_factor"]
        subres_porositymodifier = self.mercury_widget.getParams()["subres_porositymodifier"]

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
        params["simulator"] = self.simulator_combo_box.currentText
        geo_display_direction = self.direction_combo_box.currentText
        if geo_display_direction == "X":
            numpy_direction = "z"
        if geo_display_direction == "Y":
            numpy_direction = "y"
        if geo_display_direction == "Z":
            numpy_direction = "x"
        params["direction"] = numpy_direction

        for widget in self.widgets.values():
            params.update(widget.get_values())

        params["subresolution function call"] = self.mercury_widget.getFunction
        params["subres_model_name"] = subres_model_name
        params["subres_params"] = subres_params_copy
        params["subres_shape_factor"] = shape_factor
        params["subres_porositymodifier"] = subres_porositymodifier
        params["skip_imbibition"] = False
        params["remote_execution"] = "T" if self.remoteQRadioButton.isChecked() else "F"

        return params

    def setParams(self, params):
        mercury_params = {
            "subres_model_name": params.get("subres_model_name"),
            "subres_params": params.get("subres_params"),
            "subres_porositymodifier": params.get("subres_porositymodifier"),
            "subres_shape_factor": params.get("subres_shape_factor"),
        }
        self.mercury_widget.setParams(mercury_params)

    def getFormParams(self):
        """
        Get a dictionary with the value of all parameter values.

        Return:
            dict: With all values, None if there's a invalid value
            error: None if everything is ok. String with parameters name if invalid.
        """
        parameters_dict = {}

        for widget in self.widgets.values():
            if isinstance(widget, simulation_widgets.MultistepEditWidget):
                parameter_name = widget.get_name()
                if widget.get_start() is None:
                    return None, f"{parameter_name} start"
                elif widget.get_stop() is None:
                    return None, f"{parameter_name} stop"
                elif widget.get_steps() is None:
                    return None, f"{parameter_name} steps"

                parameter = f"input-{parameter_name}"
                if parameter not in parameters_dict:
                    parameters_dict[parameter] = {}
                parameters_dict[parameter]["start"] = widget.get_start()
                parameters_dict[parameter]["stop"] = widget.get_stop()
                parameters_dict[parameter]["steps"] = widget.get_steps()
            else:
                parameter_name = widget.get_name()
                parameter = f"input-{parameter_name}"
                if parameter not in parameters_dict:
                    parameters_dict[parameter] = {}
                parameters_dict[parameter]["start"] = widget.get_value()
                parameters_dict[parameter]["stop"] = widget.get_value()
                parameters_dict[parameter]["steps"] = 1
        return parameters_dict, None

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
            for name, widget in self.widgets.items():
                if name in parameters_dict:
                    if isinstance(widget, simulation_widgets.MultistepEditWidget):
                        values = parameters_dict[name]
                        widget.set_value(values["start"] or "", values["stop"] or "")
                        widget.set_steps(values["steps"] or "")
                    else:
                        values = parameters_dict[name]
                        widget.set_value(values["start"] or "")
            self.parameterInputLoadCollapsible.collapsed = True
        self.updateFieldsActivation()

    def onParameterInputSave(self):
        parameterValues, invalidParameter = self.getFormParams()
        if parameterValues is None:
            slicer.util.errorDisplay(f"Could not save parameter input. {invalidParameter} has invalid value.")
            return
        parameterNode = dict_to_parameter_node(parameterValues, self.parameterInputLineEdit.text, self.currentNode)
        slicer.app.applicationLogic().GetSelectionNode().SetActiveTableID(parameterNode.GetID())
        slicer.app.applicationLogic().PropagateTableSelection()
