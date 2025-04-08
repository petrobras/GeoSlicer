import qt

from functools import partial
from ltrace.slicer import ui
from ltrace.slicer.node_attributes import TableType

from PoreNetworkSimulationLib.TwoPhaseSimulationWidget import TwoPhaseParametersEditDialog
from MercurySimulationLib.SubscaleModelWidget import SubscaleModelWidget


def generic_setter(widget, varname, value):
    if hasattr(widget, varname):
        setattr(widget, varname, max(getattr(widget, varname), value))
    else:
        setattr(widget, varname, value)


class BaseArgsForm(qt.QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        _ = qt.QFormLayout(self)
        self._args = []

    def addArg(self, text, widget, groups=None):
        label = qt.QLabel(text)
        self.layout().addRow(label, widget)
        self._args.append((label, widget, groups))

        return len(self._args) - 1

    def showOnly(self, tag):
        for label, widget, groups in self._args:
            if tag in groups:
                label.show()
                widget.show()
                if groups[tag] is None:
                    label.enabled = False
                    widget.enabled = False
                else:
                    label.enabled = True
                    widget.enabled = True
                    groups[tag]()
            else:
                label.hide()
                widget.hide()

    @classmethod
    def _createSetter(cls, widget, varname, groups):
        return {
            key: partial(generic_setter, widget, varname, groups[key]) if groups[key] is not None else None
            for key in groups
        }

    def params(self):
        return {}

    def reset(self):
        pass


class ReportForm(BaseArgsForm):
    def __init__(self, parent=None, initialTag="Local") -> None:
        super().__init__(parent)

        self.initialTag = initialTag

        self.parameterInputWidget = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLTableNode"],
            defaultText="Select node to load parameters from",
            hasNone=True,
        )
        self.parameterInputWidget.addNodeAttributeIncludeFilter(TableType.name(), TableType.PNM_INPUT_PARAMETERS.value)
        self.parameterInputWidget.objectName = "SensibilityTestComboBox"
        self.editParameterInput = qt.QPushButton("Edit")
        self.editParameterInput.clicked.connect(self.onParameterEdit)
        self.report_folder = None

        parameterWidget = qt.QWidget()
        parameterWidget.setFixedHeight(25)
        parameterInputLayout = qt.QHBoxLayout(parameterWidget)
        parameterInputLayout.setMargin(0)
        parameterInputLayout.addWidget(self.parameterInputWidget)
        parameterInputLayout.addWidget(self.editParameterInput)

        self.subscaleModelWidget = SubscaleModelWidget(parent)

        self.wellName = qt.QTextEdit()
        self.wellName.setFixedHeight(25)
        self.wellName.objectName = "WellNameTextEdit"

        self.addArg(
            "Sensibility Test Parameters: ",
            parameterWidget,
            BaseArgsForm._createSetter(self.parameterInputWidget, "setCurrentNode", {"Local": None, "Remote": None}),
        )

        self.addArg(
            "Subscale Pressure Model: ",
            self.subscaleModelWidget.microscale_model_dropdown,
            BaseArgsForm._createSetter(self.parameterInputWidget, "setCurrentNode", {"Local": None, "Remote": None}),
        )
        self.subscaleModelWidget.microscale_model_dropdown.objectName = "MicroscaleDropdown"

        for label, widget in self.subscaleModelWidget.parameter_widgets.items():
            self.layout().addRow(widget)

        self.addArg(
            "Well Name: ",
            self.wellName,
            BaseArgsForm._createSetter(self.wellName, "plainText", {"Local": "", "Remote": None}),
        )

    def onPathChanged(self, path):
        self.report_folder = path

    def onParameterEdit(self):
        node = self.parameterInputWidget.currentNode()
        status, parameterNode = TwoPhaseParametersEditDialog(node).show()
        if status:
            self.parameterInputWidget.setCurrentNode(parameterNode)

    def setup(self):
        self.showOnly(self.initialTag)

    def params(self):
        return {
            **super().params(),
            "sensibility_parameters_node": self.parameterInputWidget.currentNode(),
            "subscale_model_params": self.subscaleModelWidget.getParams(),
            "well_name": self.wellName.plainText,
            "report_folder": self.report_folder,
        }
