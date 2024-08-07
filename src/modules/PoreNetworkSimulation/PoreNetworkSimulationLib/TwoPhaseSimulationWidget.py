import ctk
import qt
import slicer

from Customizer import Customizer
from MercurySimulationLib.MercurySimulationWidget import MercurySimulationWidget
from PoreNetworkSimulationLib.widgets import *
from ltrace.slicer import ui
from ltrace.slicer.node_attributes import TableType
from ltrace.pore_networks.pnflow_parameter_defs import PARAMETERS
from ltrace.pore_networks.simulation_parameters_node import dict_to_parameter_node, parameter_node_to_dict


class TwoPhaseParametersEditDialog:
    def __init__(self, node):
        self.node = node

    def show(self):
        dialog = qt.QDialog(slicer.util.mainWindow())
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
            name = self.node.GetName()
            outNode = dict_to_parameter_node(parameterValues, name, self.node, update_current_node=True)
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
    }

    WIDGET_TYPES = {
        "singlefloat": SinglestepEditWidget,
        "multifloat": MultistepEditWidget,
        "checkbox": CheckboxWidget,
        "singlecheckbox": SingleCheckboxWidget,
        "combobox": ComboboxWidget,
        "integerspinbox": IntegerSpinBoxWidget,
    }

    def __init__(self, hide_parameters_io=False):
        super().__init__()
        layout = qt.QFormLayout(self)
        self.widgets = {}

        self.parameterInputLoadCollapsible = ctk.ctkCollapsibleButton()
        self.parameterInputLoadCollapsible.text = "Load parameters"
        self.parameterInputLoadCollapsible.collapsed = True
        self.parameterInputWidget = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLTableNode"],
            defaultText="Select node to load parameters from",
        )
        self.parameterInputWidget.objectName = "Parameter input"
        self.parameterInputWidget.addNodeAttributeIncludeFilter(TableType.name(), TableType.PNM_INPUT_PARAMETERS.value)
        parameterInputLoadButton = qt.QPushButton("Load parameters")
        parameterInputLoadButton.objectName = "Parameter input load button"
        parameterInputLoadButton.clicked.connect(self.onParameterInputLoad)
        parameterInputLayout = qt.QFormLayout(self.parameterInputLoadCollapsible)
        parameterInputLayout.addRow("Input parameter node:", self.parameterInputWidget)
        parameterInputLayout.addRow(parameterInputLoadButton)
        parameterInputLoadIcon = qt.QLabel()
        parameterInputLoadIcon.setPixmap(qt.QIcon(str(Customizer.LOAD_ICON_PATH)).pixmap(qt.QSize(13, 13)))
        if not hide_parameters_io:
            layout.addRow(parameterInputLoadIcon, self.parameterInputLoadCollapsible)

        ### Two-phase fluids properties inputs

        # Fluid Properties
        fluidPropertiesBox = qt.QGroupBox()
        fluidPropertiesBox.setTitle("Fluid properties")
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
            )
            fluidPropertiesLayout.addRow(collapsible)

        self.add_widgets(
            target_layout=fluidPropertiesLayout,
            source_layout_name="fluid_properties",
            widgets_list=self.widgets,
        )

        # contact angle
        self.contactAngleBox = qt.QGroupBox()
        self.contactAngleBox.setTitle("Contact angle options")
        self.contactAngleLayout = qt.QFormLayout(self.contactAngleBox)
        self.contactAngleLayout.setContentsMargins(11, 9, 11, 5)
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
            )
            self.contactAngleLayout.addRow(collapsible)
        self.add_widgets(
            target_layout=self.contactAngleLayout,
            source_layout_name="contact_angle_options",
            widgets_list=self.widgets,
        )

        # simulation options
        self.simulationOptionsBox = qt.QGroupBox()
        self.simulationOptionsBox.setTitle("Simulation options")
        self.simulationOptionsLayout = qt.QFormLayout(self.simulationOptionsBox)
        self.simulationOptionsLayout.setContentsMargins(11, 9, 11, 5)
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
            )
            self.simulationOptionsLayout.addRow(collapsible)
        self.add_widgets(
            target_layout=self.simulationOptionsLayout,
            source_layout_name="options",
            widgets_list=self.widgets,
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
        parameterInputSaveIcon.setPixmap(qt.QIcon(str(Customizer.SAVE_ICON_PATH)).pixmap(qt.QSize(13, 13)))
        if not hide_parameters_io:
            layout.addRow(parameterInputSaveIcon, parameterInputSaveCollapsible)

        self.widgets["create_sequence"].stateChanged.connect(self.onCreateSequenceChecked)

        for key in ["frac_contact_angle_fraction", "second_contact_fraction"]:
            self.widgets[key].fractionChanged.connect(self.onUpdateFraction)
            self.widgets[key].onFractionChanged()

        for key, widget in self.widgets.items():
            if isinstance(widget, MultistepEditWidget):
                widget.stepChanged.connect(self.updateSimulationCount)

            if isinstance(widget, ComboboxWidget):
                if key in ["init_contact_model", "equil_contact_model"]:
                    widget.currentTextChanged.connect(self.onChangedContactModel)
                    widget.onTextChanged()

        self.updateSimulationCount()

        self.mercury_widget = MercurySimulationWidget()
        if not hide_parameters_io:
            layout.addRow(self.mercury_widget)

    def create_custom_widget(self, name, params):
        full_params = params.copy()
        full_params["parameter_name"] = name
        new_widget = self.WIDGET_TYPES[params["dtype"]](**full_params)
        return new_widget

    def add_widgets(self, target_layout, source_layout_name, widgets_list):
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
                new_label = TooltipLabel(widget_params["display_name"])
                new_label.setToolTip(widget_params["tooltip"])
            target_layout.addRow(new_label, new_widget)
            widgets_list[widget_name] = new_widget

    def onChangedContactModel(self, name, text):
        prefix = name.split("_")[0]
        if text != "Model 2 (constant difference)":
            self.widgets[f"{prefix}_contact_angle_separation"].steps.setText("1")
        for i in range(self.widgets[f"{prefix}_contact_angle_separation"].count()):
            widget = self.widgets[f"{prefix}_contact_angle_separation"].itemAt(i).widget()
            widget.setEnabled(text == "Model 2 (constant difference)")

    def onUpdateFraction(self, name, state):
        """
        This function is a callback that enable/disable items for the second distribution
        as the Fraction parameter is available.
        """
        prefix = name.split("_")[0]
        filt_widgets = {k: v for k, v in self.widgets.items() if k.startswith(f"{prefix}_") and k != name}
        for widget in filt_widgets.values():
            for i in range(widget.count()):
                widget.itemAt(i).widget().setEnabled(state)

    def setCurrentNode(self, currentNode):
        self.currentNode = currentNode

    def getParams(self):
        params = {}

        subres_model_name = self.mercury_widget.subscaleModelWidget.microscale_model_dropdown.currentText
        subres_params = self.mercury_widget.subscaleModelWidget.parameter_widgets[subres_model_name].get_params()

        if (subres_model_name == "Throat Radius Curve" or subres_model_name == "Pressure Curve") and subres_params:
            subres_params = {
                i: subres_params[i].tolist() if subres_params[i] is not None else None for i in subres_params.keys()
            }

        for widget in self.widgets.values():
            params.update(widget.get_values())

        params["subresolution function call"] = self.mercury_widget.getFunction
        params["subres_model_name"] = subres_model_name
        params["subres_params"] = subres_params

        return params

    def setParams(self, params):
        self.mercury_widget.subscaleModelWidget.microscale_model_dropdown.setCurrentText(params["subres_model_name"])

    def getFormParams(self):
        """
        Get a dictionary with the value of all parameter values.

        Return:
            dict: With all values, None if there's a invalid value
            error: None if everything is ok. String with parameters name if invalid.
        """
        parameters_dict = {}

        for widget in self.widgets.values():
            if isinstance(widget, MultistepEditWidget):
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
            if isinstance(widget, MultistepEditWidget):
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
                    if isinstance(widget, MultistepEditWidget):
                        values = parameters_dict[name]
                        widget.set_value(values["start"] or "", values["stop"] or "")
                        widget.set_steps(values["steps"] or "")
                    else:
                        values = parameters_dict[name]
                        widget.set_value(values["start"] or "")
            self.parameterInputLoadCollapsible.collapsed = True

    def onParameterInputSave(self):
        parameterValues, invalidParameter = self.getFormParams()
        if parameterValues is None:
            slicer.util.errorDisplay(f"Could not save parameter input. {invalidParameter} has invalid value.")
            return
        parameterNode = dict_to_parameter_node(parameterValues, self.parameterInputLineEdit.text, self.currentNode)
        slicer.app.applicationLogic().GetSelectionNode().SetActiveTableID(parameterNode.GetID())
        slicer.app.applicationLogic().PropagateTableSelection()
