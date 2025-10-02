import ctk
import os
import qt
import slicer

from ltrace.slicer import ui
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from pathlib import Path

try:
    from Test.{{name}}Test import {{name}}Test
except ImportError:
    {{name}}Test = None  # tests not deployed to final version or closed source


class {{name}}(LTracePlugin):
    SETTING_KEY = "{{name}}"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "{{title}}"
        self.parent.categories = ["{{category}}"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = "/Environment/{{name}}.html"

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class {{name}}Widget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.collapsed = False
        inputSection.text = "Input"

        self.__inputSelector = ui.hierarchyVolumeInput(
            onChange=self.__onInputNodeChanged,
            hasNone=True,
            nodeTypes=["vtkMRMLLabelMapVolumeNode"],
        )
        self.__inputSelector.setMRMLScene(slicer.mrmlScene)
        self.__inputSelector.setToolTip("Pick a labeled volume node")

        inputLayout = qt.QFormLayout(inputSection)
        inputLayout.addRow("Input:", self.__inputSelector)

        # Parameters section
        parametersSection = ctk.ctkCollapsibleButton()
        parametersSection.text = "Parameters"
        parametersSection.collapsed = False
        parametersSection.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        self.__multiplierSpinBox = qt.QDoubleSpinBox()
        self.__multiplierSpinBox.setRange(0, 10)
        parametersLayout = qt.QFormLayout(parametersSection)
        parametersLayout.addRow("Multiplier:", self.__multiplierSpinBox)

        # Output section
        outputSection = ctk.ctkCollapsibleButton()
        outputSection.text = "Output"
        outputSection.collapsed = False

        self.__outputPrefixLineEdit = qt.QLineEdit()
        self.__outputPrefixLineEdit.objectName = "Output Prefix Line Edit"
        outputFormLayout = qt.QFormLayout(outputSection)
        outputFormLayout.addRow("Output prefix:", self.__outputPrefixLineEdit)

        # Apply button
        self.__applyButton = ui.ApplyButton(onClick=self.__onApplyButtonClicked, tooltip="Apply changes", enabled=True)
        self.__applyButton.objectName = "Apply Button"

        # Update layout
        self.layout.addWidget(inputSection)
        self.layout.addWidget(parametersSection)
        self.layout.addWidget(outputSection)
        self.layout.addWidget(self.__applyButton)
        self.layout.addStretch(1)

    def __onApplyButtonClicked(self, state):
        if self.__outputPrefixLineEdit.text.strip() == "":
            slicer.util.errorDisplay("Please type an output prefix.")
            return

        if self.__inputSelector.currentNode() is None:
            slicer.util.errorDisplay("Please select an input node.")
            return

        data = {
            "inputNode": self.__inputSelector.currentNode(),
            "multiplier": self.__multiplierSpinBox.value,
            "outputPrefix": self.__outputPrefixLineEdit.text,
        }

        logic = {{name}}Logic()
        logic.apply(data=data)

    def __onInputNodeChanged(self, vtkId):
        node = self.__inputSelector.currentNode()
        if node is None:
            return

        self.__outputPrefixLineEdit.text = node.GetName()


class {{name}}Logic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def apply(self, data):
        pass
