from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest


class WidgetIdentificationTest(LTracePluginTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def retrieve_widgets_template_dicts(self):
        OBJECT_NAMES = {
            "Local RadioButton": self._module_widget.local_radio_button,
            "Remote RadioButton": self._module_widget.remote_radio_button,
            "Hierarchy Volume Input": self._module_widget.hierarchy_volume_input,
            "Main ComboBox": self._module_widget.single_shot.mainInput,
            "SOI ComboBox": self._module_widget.single_shot.soiInput,
            "Reference ComboBox": self._module_widget.single_shot.referenceInput,
            "First ComboBox": self._module_widget.combo1,
            "First LineEdit": self._module_widget.lineedit1,
            "First PushButton": self._module_widget.pushbutton1,
            "First SpinBox": self._module_widget.spinbox1,
            "First Slider": self._module_widget.slider1,
        }

        GUESSED_NAMES = {
            "Local": self._module_widget.local_radio_button,
            "Remote": self._module_widget.remote_radio_button,
            "Hierarchy 1": self._module_widget.hierarchy_volume_input,
            "Annotations": self._module_widget.single_shot.mainInput,
            "SOI ComboBox": self._module_widget.single_shot.soiInput,
            "Reference ComboBox": self._module_widget.single_shot.referenceInput,
            "First ComboBox": self._module_widget.combo1,
            "First LineEdit": self._module_widget.lineedit1,
            "First PushButton": self._module_widget.pushbutton1,
            "First SpinBox": self._module_widget.spinbox1,
            "First Slider": self._module_widget.slider1,
            "Combo Without ObjectName": self._module_widget.combo2,
            "Line Edit Without Buddy": self._module_widget.lineedit2,
            "Combo Collapsed": self._module_widget.combo3,
        }

        return OBJECT_NAMES, GUESSED_NAMES

    def check_find_widget_function(self, widgets_dict: dict):
        self.found_widgets = {}
        for name, widget in widgets_dict.items():
            self.found_widgets[name] = self.find_widget(name)
            assert self.found_widgets[name] is not None, f"widget related to the identifier '{name}' is None!"

        for name, found_widget in self.found_widgets.items():
            assert found_widget == widgets_dict[name], (
                f"widget identified with the identifier '{name}':'{found_widget}' do not correspond to the right widget '{widgets_dict[name]}'!"
            )

    def test_automatic_widgets_assignment(self):
        OBJECT_NAMES, GUESSED_NAMES = self.retrieve_widgets_template_dicts()
        widgets_dict = OBJECT_NAMES | GUESSED_NAMES

        for name, widget in widgets_dict.items():
            assert self.widgets[name] is not None, f"widget related to the identifier '{name}' is None!"
            assert self.widgets[name] == widget, (
                f"widget identified with the identifier '{name}':'{self.widgets[name]}' do not correspond to the right widget '{widgets_dict[name]}'!"
            )

    def test_find_widget_by_object_name(self):
        OBJECT_NAMES, _ = self.retrieve_widgets_template_dicts()
        self.check_find_widget_function(OBJECT_NAMES)

    def test_find_widget_by_guessed_name(self):
        _, GUESSED_NAMES = self.retrieve_widgets_template_dicts()
        self.check_find_widget_function(GUESSED_NAMES)
