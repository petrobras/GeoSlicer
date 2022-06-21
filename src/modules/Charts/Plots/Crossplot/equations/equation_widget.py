import decimal

import qt


class ParametersFrame(qt.QFrame):
    signal_parameter_changed = qt.Signal(str, float, bool)
    refit_button_pressed = qt.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class EquationWidget:
    DISPLAY_NAME = ""
    EQUATION_TEXT = ""
    PARAMETERS = []

    def __init__(self, enable_fit_widgets=True):
        self.enable_fit_widgets = enable_fit_widgets
        self.__widget = self.__create_widget()

    def get_widget(self):
        return self.__widget

    def update(self, fit_data):
        for parameter_name, parameter_widget in self.__parameter_widgets.items():
            parameter_widget[0].setText(fit_data.parameters[parameter_name])
            if self.enable_fit_widgets:
                parameter_widget[1].checked = parameter_name in fit_data.fixed_parameters
                if fit_data.custom_bounds:
                    lower_bound, upper_bound = fit_data.custom_bounds[self.PARAMETERS.index(parameter_name)]
                    if lower_bound:
                        parameter_widget[2].text = lower_bound
                    if upper_bound:
                        parameter_widget[3].text = upper_bound
        if self.enable_fit_widgets:
            self.r_squared_widget.text = fit_data.r_squared

    def clear(self):
        for parameter_widget in self.__parameter_widgets.values():
            parameter_widget[0].setText("")
            if self.enable_fit_widgets:
                parameter_widget[1].checked = False
                parameter_widget[2].setText("")
                parameter_widget[3].setText("")
        if self.enable_fit_widgets:
            self.r_squared_widget.text = ""

    def get_fixed_values(self):
        fixed_values = []
        for parameter in self.__parameter_widgets.values():
            if parameter[1].isChecked():
                try:
                    fixed_values.append(float(parameter[0].text))
                except ValueError:
                    fixed_values.append(None)
            else:
                fixed_values.append(None)
        return fixed_values

    def get_custom_bounds(self):
        custom_bounds = []
        for parameter in self.__parameter_widgets.values():
            try:
                lower_bound = float(parameter[2].text)
            except ValueError:
                lower_bound = None
            try:
                upper_bound = float(parameter[3].text)
            except ValueError:
                upper_bound = None
            custom_bounds.append((lower_bound, upper_bound))
        return custom_bounds

    def __create_widget(self):
        self.__parameter_widgets = {}

        parameters_layout = qt.QFormLayout()
        parameters_layout.addRow("Model:", qt.QLabel(self.EQUATION_TEXT))

        parameters_frame = ParametersFrame()
        parameters_frame.setLayout(parameters_layout)

        for parameter in self.PARAMETERS:
            if self.enable_fit_widgets:
                bounds_frame = qt.QFrame()
                lower_bound_label = qt.QLabel("Min/max: ")
                lower_bound_value = qt.QLineEdit()
                lower_bound_value.setValidator(qt.QDoubleValidator(bounds_frame))
                upper_bound_label = qt.QLabel(":")
                upper_bound_value = qt.QLineEdit()
                upper_bound_value.setValidator(qt.QDoubleValidator(bounds_frame))

                lower_bound_value.editingFinished.connect(
                    self.__create_lower_bound_edited_callback(lower_bound_value, upper_bound_value)
                )
                upper_bound_value.editingFinished.connect(
                    self.__create_upper_bound_edited_callback(upper_bound_value, lower_bound_value)
                )

                bounds_layout = qt.QHBoxLayout(bounds_frame)
                bounds_layout.setMargin(0)
                bounds_layout.addWidget(lower_bound_value)
                bounds_layout.addWidget(upper_bound_label)
                bounds_layout.addWidget(upper_bound_value)
            else:
                lower_bound_value = None
                upper_bound_value = None

            new_parameter_widget = qt.QLineEdit()
            new_parameter_widget.setValidator(qt.QDoubleValidator(new_parameter_widget))
            if self.enable_fit_widgets:
                fix_checkbox = qt.QCheckBox("Fix")
                fix_checkbox.stateChanged.connect(self.__create_fix_checkbox_changed_callback(bounds_frame))
                new_parameter_widget.textEdited.connect(self.__create_editing_parameter_callback(fix_checkbox))
            else:
                fix_checkbox = None
            new_parameter_widget.editingFinished.connect(
                self.__create_parameter_changed_emiter(parameters_frame, parameter, new_parameter_widget, fix_checkbox)
            )

            parameter_layout = qt.QHBoxLayout()
            parameter_layout.addWidget(new_parameter_widget, 2)
            if self.enable_fit_widgets:
                parameter_layout.addWidget(fix_checkbox)

            parameters_layout.addRow(parameter, parameter_layout)
            if self.enable_fit_widgets:
                parameters_layout.addRow(lower_bound_label, bounds_frame)
            self.__parameter_widgets[parameter] = (
                new_parameter_widget,
                fix_checkbox,
                lower_bound_value,
                upper_bound_value,
            )

            if self.enable_fit_widgets:
                line = qt.QFrame()
                line.setFrameShape(qt.QFrame.HLine)
                line.setFrameShadow(qt.QFrame.Sunken)
                parameters_layout.addRow(line)

        if self.enable_fit_widgets:
            r_squared_layout = qt.QHBoxLayout()
            self.r_squared_widget = qt.QLineEdit()
            self.r_squared_widget.setReadOnly(True)
            self.refit_button = qt.QPushButton("Refit")
            self.refit_button.setFocusPolicy(qt.Qt.NoFocus)
            self.refit_button.clicked.connect(lambda _: parameters_frame.refit_button_pressed.emit())
            r_squared_layout.addWidget(self.r_squared_widget)
            r_squared_layout.addWidget(self.refit_button)
            parameters_layout.addRow("R²: ", r_squared_layout)

        return parameters_frame

    def update_refit_button_state(self, state):
        if self.enable_fit_widgets:
            self.refit_button.enabled = state

    @staticmethod
    def __create_editing_parameter_callback(fix_checkbox):
        def callback():
            fix_checkbox.checked = True

        return callback

    @staticmethod
    def __create_parameter_changed_emiter(parameters_frame, changed_parameter, changed_parameter_widget, fix_checkbox):
        def emmiter():
            if not changed_parameter_widget.isModified():
                return
            changed_parameter_widget.setModified(False)
            parameters_frame.signal_parameter_changed.emit(
                changed_parameter, float(changed_parameter_widget.text), fix_checkbox.checked if fix_checkbox else False
            )

        return emmiter

    @staticmethod
    def __create_fix_checkbox_changed_callback(bounds_frame):
        def callback(fix_checkbox_state):
            bounds_frame.enabled = fix_checkbox_state == 0

        return callback

    @staticmethod
    def __create_lower_bound_edited_callback(lower_bound_lineedit, upper_bound_lineedit):
        def callback():
            if lower_bound_lineedit.text != "" and upper_bound_lineedit.text != "":
                if float(lower_bound_lineedit.text) >= float(upper_bound_lineedit.text):
                    exponent = decimal.Decimal(upper_bound_lineedit.text).as_tuple().exponent
                    exponent = exponent if exponent < 0 else 0
                    decimal_places = abs(exponent)
                    lower_bound_lineedit.text = f"%.{decimal_places}f" % (
                        float(upper_bound_lineedit.text) - 10**exponent
                    )

        return callback

    @staticmethod
    def __create_upper_bound_edited_callback(upper_bound_lineedit, lower_bound_lineedit):
        def callback():
            if upper_bound_lineedit.text != "" and lower_bound_lineedit.text != "":
                if float(upper_bound_lineedit.text) <= float(lower_bound_lineedit.text):
                    exponent = decimal.Decimal(lower_bound_lineedit.text).as_tuple().exponent
                    exponent = exponent if exponent < 0 else 0
                    decimal_places = abs(exponent)
                    upper_bound_lineedit.text = f"%.{decimal_places}f" % (
                        float(lower_bound_lineedit.text) + 10**exponent
                    )

        return callback
