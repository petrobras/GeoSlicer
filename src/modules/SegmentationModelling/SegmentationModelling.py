import os
from pathlib import Path
from typing import List

import vtk, qt, ctk, slicer

from ltrace.slicer import ui, widgets, helpers
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from Methods.permeability import Permeability
from Methods.microporosity import MicroPorosity
from Methods.output_info import OutputInfo

try:
    from Test.SegmentationModellingTest import SegmentationModellingTest
except ImportError:
    SegmentationModellingTest = None  # tests not deployed to final version or closed source


class SegmentationModelling(LTracePlugin):
    SETTING_KEY = "SegmentationModelling"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Modelling"
        self.parent.categories = ["Segmentation", "MicroCT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = SegmentationModelling.help()
        self.setHelpUrl("Volumes/Microporosity/PorosityFromSegmentation.html")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class SegmentationModellingWidget(LTracePluginWidget):
    def __init__(self, parent) -> None:
        LTracePluginWidget.__init__(self, parent)
        self.logic = None
        self.onProcessEnded = lambda: None

    def setup(self):
        LTracePluginWidget.setup(self)

        # Method selector
        self.method_selector = ui.StackedSelector(text="Methods:")
        self.method_selector.selector.objectName = "Methods ComboBox"
        micro_porosity_widget = MicroPorosity(controller=self)
        permeability_widget = Permeability()

        # Add method widgets to the method selector
        self.method_selector.addWidget(micro_porosity_widget)
        self.method_selector.addWidget(permeability_widget)

        self.micro_porosity_widget = micro_porosity_widget
        self.permeability_widget = permeability_widget
        self.micro_porosity_widget.signal_quality_control_changed.connect(self.__handle_reset_output)

        methods_collapsible_button = ctk.ctkCollapsibleButton()
        methods_collapsible_button.text = "Methods"
        self.methods_collapsible_button = methods_collapsible_button
        self.layout.addWidget(methods_collapsible_button)
        methods_layout = qt.QVBoxLayout(methods_collapsible_button)
        methods_layout.addWidget(self.method_selector.selector)

        # Inputs
        inputs_collapsible_button = ctk.ctkCollapsibleButton()
        inputs_collapsible_button.text = "Inputs"
        self.inputs_collapsible_button = inputs_collapsible_button
        self.layout.addWidget(inputs_collapsible_button)

        self.stacked_input_widgets = qt.QStackedWidget()
        for index in range(self.method_selector.content.count):
            method_widget = self.method_selector.content.widget(index)
            inputWidget = method_widget.inputWidget
            self.stacked_input_widgets.addWidget(inputWidget)
            inputWidget.onMainSelectedSignal.connect(self.__on_input_selected)
            inputWidget.onSoiSelectedSignal.connect(self.__on_soi_selected)
            inputWidget.onReferenceSelectedSignal.connect(self.__on_reference_selected)
            # inputWidget.segmentsOff()

        self.inputWidget = self.method_selector.currentWidget().inputWidget
        inputs_layout = qt.QVBoxLayout(inputs_collapsible_button)
        inputs_layout.addWidget(self.stacked_input_widgets)

        self.method_selector.selector.currentIndexChanged.connect(self.__on_method_changed)

        # Parameters
        self.parameters_collapsible_button = ctk.ctkCollapsibleButton()
        self.parameters_collapsible_button.text = "Parameters"
        self.layout.addWidget(self.parameters_collapsible_button)

        parameters_form_layout = qt.QVBoxLayout(self.parameters_collapsible_button)
        parameters_form_layout.addWidget(self.method_selector.content)

        # Output
        output_collapsible_button = ctk.ctkCollapsibleButton()
        output_collapsible_button.text = "Output"
        self.layout.addWidget(output_collapsible_button)

        self.output_prefix_lineedit = qt.QLineEdit()
        self.output_prefix_lineedit.objectName = "Output Prefix Line Edit"
        self.output_prefix_lineedit.editingFinished.connect(self.__update_apply_button_state)

        self.output_form_layout = qt.QFormLayout(output_collapsible_button)
        self.output_form_layout.addRow("Output prefix: ", self.output_prefix_lineedit)

        # Apply
        self.apply_button = ui.ApplyButton(
            onClick=self.__on_apply_button_clicked, tooltip="Apply changes", enabled=True, object_name="Apply Button"
        )
        self.progress_bar = LocalProgressBar()
        self.layout.addWidget(self.apply_button)
        self.layout.addWidget(self.progress_bar)

        self.layout.addStretch(1)

        # Scene closed signal
        self.sceneObserver = slicer.mrmlScene.AddObserver(slicer.vtkMRMLScene.EndCloseEvent, self.__on_scene_closed)

    def cleanup(self):
        super().cleanup()
        slicer.mrmlScene.RemoveObserver(self.sceneObserver)

    def __draw_widget_content(self):
        next_input = self.method_selector.currentWidget().inputWidget
        next_inputs_are_valid = next_input.hasValidInputs()
        next_input.hideSegmentList(not next_inputs_are_valid)
        self.parameters_collapsible_button.collapsed = not next_inputs_are_valid  # close when invalid inputs

    def __on_method_changed(self, index):
        self.inputWidget = self.method_selector.currentWidget().inputWidget
        self.inputWidget.hideSegmentList(True)
        self.parameters_collapsible_button.collapsed = True  # close when invalid inputs
        self.stacked_input_widgets.setCurrentIndex(index)
        self.__draw_widget_content()
        self.__handle_reset_output()

    def __on_input_selected(self, node):
        if not (node and node.IsA("vtkMRMLSegmentationNode")):
            return

        self.method_selector.currentWidget().onSegmentationChanged(node)
        self.__update_apply_button_state()
        self.__draw_widget_content()

    def __on_soi_selected(self, node):
        self.method_selector.currentWidget().onSoiChanged(node)

    def __on_reference_selected(self, node):
        self.method_selector.currentWidget().onReferenceChanged(node, None)

        output_prefix = node.GetName() if node is not None else ""
        self.output_prefix_lineedit.setText(output_prefix)

        if node and node.IsA("vtkMRMLLabelMapVolumeNode"):
            self.method_selector.currentWidget().onSegmentationChanged(node)

        self.__update_apply_button_state()
        self.__draw_widget_content()

    def __handle_reset_output(self):
        self.__update_output_info([])
        self.__update_apply_button_state()

    def __on_scene_closed(self, caller, event):
        self.method_selector.currentWidget().clearPlotData()
        self.__handle_reset_output()

    def __on_apply_button_clicked(self, state):
        if not self.method_selector.currentWidget().validatePrerequisites():
            return
        try:
            method_logic = self.method_selector.currentWidget().apply(self.output_prefix_lineedit.text)
        except ValueError as e:
            slicer.util.errorDisplay(f"Please, initialize the range values on quality control panel before applying.")
            return
        except Exception as e:
            slicer.util.errorDisplay(f"Please, check the inputs. Error: {e}")
            return
        self.__update_output_info([])
        method_logic.signalProcessEnded.connect(self.__on_process_ended)

        self.logic = SegmentationModellingLogic(method_logic)
        self.logic.apply(progress_bar=self.progress_bar)

    def __update_apply_button_state(self):
        isPermeability = self.method_selector.currentWidget().DISPLAY_NAME == Permeability.DISPLAY_NAME
        self.apply_button.setEnabled(
            self.output_prefix_lineedit.text.strip()
            and self.inputWidget.referenceInput.currentNode() is not None
            and (self.inputWidget.mainInput.currentNode() is not None or isPermeability)
        )

    def __update_output_info(self, output_info_list: List[OutputInfo]):
        for i in range(1, self.output_form_layout.rowCount()):
            self.output_form_layout.removeRow(i)

        for output_info in output_info_list:
            value_label = qt.QLabel(output_info.value)
            value_label.objectName = "Segmentation Modelling Total Porosity Output Value"
            value_label.setToolTip(output_info.tooltip)
            self.output_form_layout.addRow(output_info.name, value_label)

    def __on_process_ended(self):
        self.__update_output_info(self.method_selector.currentWidget().getOutputInfo())
        self.onProcessEnded()


class SegmentationModellingLogic(LTracePluginLogic):
    def __init__(self, method_logic):
        LTracePluginLogic.__init__(self)
        self._method_logic = method_logic

    def apply(self, progress_bar=None):
        self._method_logic.apply(progress_bar)
