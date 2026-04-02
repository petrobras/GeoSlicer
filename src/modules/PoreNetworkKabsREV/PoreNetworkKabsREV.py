import json
import os
from pathlib import Path

import ctk
import pandas as pd
import qt
import slicer
import logging

from MercurySimulationLib.MercurySimulationWidget import MercurySimulationWidget
from ltrace.slicer import ui
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, dataFrameToTableNode
from ltrace.remote.handlers.PoreNetworkKabsREVHandler import PoreNetworkKabsREVHandler

try:
    from Test.PoreNetworkKabsREVTest import PoreNetworkKabsREVTest
except ImportError:
    PoreNetworkKabsREVTest = None  # tests not deployed to final version or closed source


class PoreNetworkKabsREV(LTracePlugin):
    SETTING_KEY = "PoreNetworkKabsREV"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Pore Network Kabs REV"
        self.parent.categories = ["MicroCT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = PoreNetworkKabsREV.help()
        self.setHelpUrl("Volumes/PNM/PNM.html#kabs-rev")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PoreNetworkKabsREVWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.progressBar = LocalProgressBar()

    def setup(self):
        LTracePluginWidget.setup(self)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.collapsed = False
        inputSection.text = "Input"

        self.__inputSelector = ui.hierarchyVolumeInput(
            hasNone=True, nodeTypes=["vtkMRMLLabelMapVolumeNode", "vtkMRMLScalarVolumeNode"]
        )
        self.__inputSelector.setToolTip("Select input (optional)")
        self.__inputSelector.objectName = "Input Selector"

        inputLayout = qt.QFormLayout(inputSection)
        inputLayout.addRow("Input:", self.__inputSelector)

        # Parameters section
        parametersSection = ctk.ctkCollapsibleButton()
        parametersSection.text = "Parameters"
        parametersSection.collapsed = False
        parametersSection.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        parametersLayout = qt.QFormLayout(parametersSection)

        self.executionTypeLocal = qt.QRadioButton("Local")
        self.executionTypeLocal.setChecked(True)
        self.executionTypeRemote = qt.QRadioButton("Remote")

        executionTypeLayout = qt.QHBoxLayout()
        executionTypeLayout.addWidget(self.executionTypeLocal)
        executionTypeLayout.addWidget(self.executionTypeRemote)
        parametersLayout.addRow("Execution type:", executionTypeLayout)

        self.fractionsSpinBox = qt.QSpinBox()
        self.fractionsSpinBox.setRange(3, 500)
        self.fractionsSpinBox.setValue(30)
        self.fractionsSpinBox.objectName = "Fractions SpinBox"
        parametersLayout.addRow("Number of lengths", self.fractionsSpinBox)

        self.minFraction = ui.floatParam()
        self.minFraction.text = 10
        self.minFraction.objectName = "Min Length Fraction"
        parametersLayout.addRow("Min. length fraction (%)", self.minFraction)

        self.modelTypeComboBox = qt.QComboBox()
        self.modelTypeComboBox.addItems(["Valvatne-Blunt"])
        self.modelTypeComboBox.setCurrentIndex(0)
        self.modelTypeComboBox.objectName = "Model Type ComboBox"
        parametersLayout.addRow("Pore Network model", self.modelTypeComboBox)

        hbox = qt.QHBoxLayout()
        self.solverComboBox = qt.QComboBox()
        self.solverComboBox.addItems(["pypardiso", "pyflowsolver", "openpnm"])
        self.solverComboBox.setCurrentIndex(0)
        self.solverComboBox.objectName = "Solver ComboBox"
        solverHelpButton = HelpButton(
            "'pypardiso' is the recomended solver, 'pyflowsolver' allows error tolerance control, but performance is usually lower than 'pypardiso', 'openpnm' is a legacy option"
        )
        hbox.addWidget(self.solverComboBox)
        hbox.addWidget(solverHelpButton)
        parametersLayout.addRow("Solver", hbox)

        self.pressureDropFloat = ui.floatParam(101325.0)
        parametersLayout.addRow("Pressure drop (Pa)", self.pressureDropFloat)

        self.fluidViscosityFloat = ui.floatParam(1.0)
        parametersLayout.addRow("Fluid viscosity (mPa.s)", self.fluidViscosityFloat)

        hbox = qt.QHBoxLayout()
        self.errorLabel = qt.QLabel("Target error")
        self.errorEdit = ui.floatParam(1e-7)
        self.errorHelpButton = HelpButton("Error stopping criteria for the linear system solver")
        hbox.addWidget(self.errorEdit)
        hbox.addWidget(self.errorHelpButton)
        parametersLayout.addRow(self.errorLabel, hbox)

        self.preconditionerLabel = qt.QLabel("Preconditioner:")
        self.preconditionerComboBox = qt.QComboBox()
        self.preconditionerComboBox.addItems(
            [
                "inverse_diagonal",
            ]
        )
        self.preconditionerComboBox.setCurrentIndex(0)
        parametersLayout.addRow(self.preconditionerLabel, self.preconditionerComboBox)

        self.solverComboBox.currentTextChanged.connect(self.__onSolverChanged)
        self.solverComboBox.currentTextChanged.emit(self.solverComboBox.currentText)

        hbox = qt.QHBoxLayout()
        self.clipCheck = qt.QCheckBox()
        clipCheckHelpButton = HelpButton(
            'If "clip high conductivities" is selected, high conductivities throats have their conductivities reduced to a cap of the lowest conductivity times the "maximum conductivity range" input. This should be used when convergence is not achieved in networks that percolate only on the subscale phase.'
        )
        hbox.addWidget(self.clipCheck)
        hbox.addWidget(clipCheckHelpButton)
        parametersLayout.addRow("Clip high conductivity values", hbox)
        self.clipEdit = ui.floatParam(1e10)
        parametersLayout.addRow("Maximum conductivity range", self.clipEdit)

        self.mercury_widget = MercurySimulationWidget()
        parametersLayout.addRow(self.mercury_widget)

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

        self.__cancelButton = qt.QPushButton("Cancel")
        self.__cancelButton.objectName = "Cancel Button"
        self.__cancelButton.setEnabled(False)
        self.__cancelButton.setSizePolicy(self.__applyButton.sizePolicy)

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.addWidget(self.__applyButton)
        buttonsLayout.addWidget(self.__cancelButton)

        self.__inputSelector.currentItemChanged.connect(self.__onInputSelectorChange)
        self.__cancelButton.clicked.connect(self.__onCancelButtonClicked)

        # Update layout
        self.layout.addWidget(inputSection)
        self.layout.addWidget(parametersSection)
        self.layout.addWidget(outputSection)
        self.layout.addLayout(buttonsLayout)
        self.layout.addWidget(self.progressBar)
        self.layout.addStretch(1)

    def __onInputSelectorChange(self):
        input_node = self.__inputSelector.currentNode()
        output_prefix = input_node.GetName() if input_node else ""
        self.__outputPrefixLineEdit.setText(output_prefix)
        self.mercury_widget.setVolumeNode(input_node)

    def __onSolverChanged(self, text):
        self.errorLabel.setVisible(text == "pyflowsolver")
        self.errorEdit.setVisible(text == "pyflowsolver")
        self.errorHelpButton.setVisible(text == "pyflowsolver")
        self.preconditionerLabel.setVisible(text == "pyflowsolver")
        self.preconditionerComboBox.setVisible(text == "pyflowsolver")

    def __onApplyButtonClicked(self, state):
        if self.__outputPrefixLineEdit.text.strip() == "":
            slicer.util.errorDisplay("Please type an output prefix.")
            return

        input_node = self.__inputSelector.currentNode()
        if input_node is None:
            slicer.util.errorDisplay("Please select an input node.")
            return

        self.__applyButton.enabled = False
        self.__cancelButton.enabled = True

        try:
            mercury_widget_params = self.mercury_widget.getParams(input_node)
            subres_model_name = mercury_widget_params["subres_model_name"]
            subres_params = mercury_widget_params["subres_params"]

            if (subres_model_name == "Throat Radius Curve" or subres_model_name == "Pressure Curve") and subres_params:
                subres_params = {i: v.tolist() if hasattr(v, "tolist") else v for i, v in subres_params.items()}
            mercury_widget_params["subres_params"] = subres_params

            params = {
                "solver": self.solverComboBox.currentText,
                "solver_error": float(self.errorEdit.text),
                "pressure_drop": float(self.pressureDropFloat.text),
                "fluid_viscosity": 0.001 * float(self.fluidViscosityFloat.text),  # converts from mPa.s to Pa.s
                "preconditioner": self.preconditionerComboBox.currentText,
                "clip_check": self.clipCheck.isChecked(),
                "clip_value": float(self.clipEdit.text),
                "number_of_fractions": int(self.fractionsSpinBox.value),
                "min_fraction": float(self.minFraction.text) / 100.0,
                "is_multiscale": not input_node.IsA("vtkMRMLLabelMapVolumeNode"),
            }
            params.update(mercury_widget_params)

            if self.executionTypeRemote.isChecked():
                handler = PoreNetworkKabsREVHandler(input_node.GetID(), params, self.__outputPrefixLineEdit.text)
                slicer.modules.RemoteServiceInstance.cli.run(
                    handler,
                    name=f"PNM Kabs REV: {self.__outputPrefixLineEdit.text}",
                    job_type="pnmkabsrev",
                    polling_enabled=True,
                )
                self.__onProcessFinished()
            else:
                self.logic = PoreNetworkKabsREVLogic(self.parent, self.progressBar)
                self.logic.processFinished.connect(self.__onProcessFinished)
                self.logic.apply(input_node, params, self.__outputPrefixLineEdit.text)
        except Exception as e:
            logging.error(f"An error occurred: {str(e)}")
            self.__onProcessFinished()

    def __onCancelButtonClicked(self):
        if hasattr(self, "logic") and self.logic:
            self.logic.cancel()

    def __onProcessFinished(self):
        self.__applyButton.enabled = True
        self.__cancelButton.enabled = False
        self.logic = None

    def __onInputNodeChanged(self, vtkId):
        node = self.__inputSelector.currentNode()
        if node is None:
            return

        self.__outputPrefixLineEdit.text = node.GetName()


class PoreNetworkKabsREVLogic(LTracePluginLogic):
    processFinished = qt.Signal()

    def __init__(self, parent, progressBar):
        LTracePluginLogic.__init__(self, parent)
        self.cliNode = None
        self.progressBar = progressBar
        self.cwd = None

    def cancel(self):
        if self.cliNode:
            self.cliNode.Cancel()

    def apply(self, node, params, prefix):
        self.cwd = Path(slicer.util.tempDirectory())

        folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()
        itemTreeId = folderTree.GetItemByDataNode(node)
        parentItemId = folderTree.GetItemParent(itemTreeId)
        self.rootDir = folderTree.CreateFolderItem(parentItemId, f"{prefix} Kabs REV Simulation")

        params["is_multiscale"] = not node.IsA("vtkMRMLLabelMapVolumeNode")

        cliParams = {
            "volume": node.GetID(),
            "cwd": str(self.cwd),
        }

        with open(str(self.cwd / "params_dict.json"), "w") as file:
            json.dump(params, file)

        self.cliNode = slicer.cli.run(slicer.modules.porenetworkkabsrevcli, None, cliParams)
        self.progressBar.setCommandLineModuleNode(self.cliNode)
        self.cliNode.AddObserver("ModifiedEvent", self.CLICallback)

    def CLICallback(self, caller, event):
        if caller is None:
            self.cliNode = None
            return
        if self.cliNode is None:
            return

        status = caller.GetStatusString()
        if status in ["Completed", "Cancelled", "Completed with errors"]:
            try:
                if status != "Cancelled":
                    self.onFinish()
                else:
                    folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()
                    folderTree.RemoveItem(self.rootDir)
            except Exception as e:
                logging.error(f"An error occurred while processing results: {str(e)}")
            finally:
                self.cliNode = None
                self.processFinished.emit()

    def onFinish(self):
        folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()
        # folderTree.RemoveItem(self.rootDir)
        tables = {}
        for i in "xyz":
            df = pd.read_pickle(str(self.cwd / f"kabs_rev_{i}.pd"))
            PermTableName = slicer.mrmlScene.GenerateUniqueName(f"kabs_rev_{i}")
            PermTable = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", PermTableName)
            _ = dataFrameToTableNode(df, PermTable)
            _ = folderTree.CreateItem(self.rootDir, PermTable)
            tables[i] = PermTable

        self.setChartNodes(tables)

    def setChartNodes(self, tables):
        folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()

        colorMap = {
            "x": (0.9, 0.1, 0.1),
            "y": (0.1, 0.9, 0.1),
            "z": (0.1, 0.1, 0.9),
        }

        for key, table in tables.items():
            seriesNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode", f"Kabs REV {key}")
            table.SetAttribute("kabs rev data", seriesNode.GetID())
            seriesNode.SetAndObserveTableNodeID(table.GetID())
            seriesNode.SetXColumnName("length (mm)")
            seriesNode.SetYColumnName("permeability (mD)")
            seriesNode.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter)
            seriesNode.SetLineStyle(slicer.vtkMRMLPlotSeriesNode.LineStyleSolid)
            seriesNode.SetMarkerStyle(slicer.vtkMRMLPlotSeriesNode.MarkerStyleCircle)
            seriesNode.SetColor(*colorMap[key])
            seriesNode.SetLineWidth(3)
            seriesNode.SetMarkerSize(7)
            folderTree.CreateItem(self.rootDir, seriesNode)
