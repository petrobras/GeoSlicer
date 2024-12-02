import ctk
import pyqtgraph as pg
import qt
import slicer
import importlib
import os
import sys

from MercurySimulationLib.MercurySimulationLogic import MercurySimulationLogic
from MercurySimulationLib.MercurySimulationWidget import MercurySimulationWidget
from PoreNetworkSimulationLib.OnePhaseSimulationWidget import OnePhaseSimulationWidget
from PoreNetworkSimulationLib.PoreNetworkSimulationLogic import OnePhaseSimulationLogic, TwoPhaseSimulationLogic
from PoreNetworkSimulationLib.TwoPhaseSimulationWidget import TwoPhaseSimulationWidget
from PoreNetworkSimulationLib.constants import MICP, ONE_PHASE, TWO_PHASE

from pathlib import Path
from ltrace.slicer import ui
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer_utils import (
    LTracePlugin,
    LTracePluginWidget,
    getResourcePath,
)

try:
    from Test.PoreNetworkSimulationTest import PoreNetworkSimulationTest
except ImportError:
    PoreNetworkSimulationTest = None  # tests not deployed to final version or closed source

pg.setConfigOptions(antialias=True)


class PoreNetworkSimulation(LTracePlugin):
    SETTING_KEY = "PoreNetworkSimulator"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "PNM Simulation"
        self.parent.categories = ["MicroCT", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = f"file:///{(getResourcePath('manual') / 'Modules/PNM/PNSimulation.html').as_posix()}"
        self.parent.acknowledgementText = ""

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PoreNetworkSimulationWidget(LTracePluginWidget):
    def setup(self):
        LTracePluginWidget.setup(self)
        self.progressBar = LocalProgressBar()
        self.logic = None

        #
        # Input Area: inputFormLayout
        #
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.text = "Input"
        self.layout.addWidget(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)

        # input table selector
        self.inputSelector = ui.hierarchyVolumeInput(hasNone=True, nodeTypes=["vtkMRMLTableNode"])
        self.inputSelector.addNodeAttributeIncludeFilter("table_type", "pore_table")
        self.inputSelector.setToolTip("Select input (optional)")
        self.inputSelector.clearSelection()
        self.inputSelector.setToolTip('Pick a Table node of type "pore_table".')
        self.inputSelector.objectName = "Input Selector"
        self.inputSelector.showEmptyHierarchyItems = False
        labelWidget = qt.QLabel("Input Pore Table: ")
        inputFormLayout.addRow(labelWidget, self.inputSelector)

        #
        # Parameters Area: parametersFormLayout
        #
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Parameters"
        self.layout.addWidget(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

        # Simulation Selection
        self.simulationSelector = qt.QComboBox()
        self.simulationSelector.addItems((ONE_PHASE, TWO_PHASE, MICP))
        self.simulationSelector.setCurrentIndex(0)
        self.simulationSelector.setToolTip("Choose simulation")
        self.simulationSelector.objectName = "Simulation Selector"
        parametersFormLayout.addRow("Simulation: ", self.simulationSelector)

        self.onePhaseSimWidget = OnePhaseSimulationWidget()
        self.onePhaseSimWidget.setParams(OnePhaseSimulationWidget.DEFAULT_VALUES)
        parametersFormLayout.addRow(self.onePhaseSimWidget)

        self.twoPhaseSimWidget = TwoPhaseSimulationWidget()
        parametersFormLayout.addRow(self.twoPhaseSimWidget)

        self.mercurySimWidget = MercurySimulationWidget()
        parametersFormLayout.addRow(self.mercurySimWidget)

        #
        # Output Area: outputFormLayout
        #
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.text = "Output"
        self.layout.addWidget(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)

        self.outputPrefix = qt.QLineEdit()
        self.outputPrefix.setObjectName("Output Prefix")
        outputFormLayout.addRow("Output Prefix: ", self.outputPrefix)
        self.outputPrefix.setToolTip("Select prefix text to be used as the name of the output nodes/data.")
        self.outputPrefix.setText("")

        #
        # Apply/Cancel Buttons
        #
        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setObjectName("Apply Button")
        self.applyButton.setFixedHeight(40)
        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.setFixedHeight(40)
        self.applyButtonEnabled(True)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.applyButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        self.layout.addLayout(buttonsHBoxLayout)

        self.layout.addWidget(self.progressBar)

        #
        # Connections
        #
        self.inputSelector.currentItemChanged.connect(self.onInputSelectorChange)
        self.simulationSelector.currentIndexChanged.connect(self.onChangeModel)
        self.applyButton.clicked.connect(self.onApplyButtonClicked)
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)
        self.onChangeModel()
        self.onInputSelectorChange()

        # Add vertical spacer
        self.layout.addStretch(1)

    def onReload(self):
        importlib.reload(sys.modules["ltrace.slicer.widget.simulation"])
        importlib.reload(sys.modules["PoreNetworkSimulationLib.TwoPhaseSimulationWidget"])
        importlib.reload(sys.modules["PoreNetworkSimulationLib.OnePhaseSimulationWidget"])
        importlib.reload(sys.modules["MercurySimulationLib.MercurySimulationWidget"])
        importlib.reload(sys.modules["MercurySimulationLib.SubscaleModelWidget"])
        importlib.reload(sys.modules["ltrace.pore_networks.pnflow_parameter_defs"])
        super().onReload()

    def onCancelButtonClicked(self):
        simulation = self.simulationSelector.currentText
        self.logic.cancel()
        self.applyButtonEnabled(True)

    def applyButtonEnabled(self, enabled):
        self.applyButton.setEnabled(enabled)
        self.cancelButton.setEnabled(not enabled)

    def onChangeModel(self):
        simulation = self.simulationSelector.currentText

        self.onePhaseSimWidget.setVisible(simulation == ONE_PHASE)
        self.twoPhaseSimWidget.setVisible(simulation == TWO_PHASE)
        self.mercurySimWidget.setVisible(simulation == MICP)

        if simulation == ONE_PHASE:
            self.logic = OnePhaseSimulationLogic(self.progressBar)
        elif simulation == TWO_PHASE:
            self.logic = TwoPhaseSimulationLogic(self.progressBar)
        elif simulation == MICP:
            self.logic = MercurySimulationLogic(self.progressBar)

    def onInputSelectorChange(self):
        input_node = self.inputSelector.currentNode()
        self.twoPhaseSimWidget.setCurrentNode(input_node)
        output_prefix = input_node.GetName() if input_node else ""
        self.outputPrefix.setText(output_prefix)

    def onApplyButtonClicked(self):
        pore_node = self.inputSelector.currentNode()
        if pore_node is None:
            slicer.util.warningDisplay("No valid node selected")
            return

        simulation = self.simulationSelector.currentText

        if simulation == ONE_PHASE:
            self.runOnePhaseSimulation(pore_node)
        elif simulation == TWO_PHASE:
            self.runTwoPhaseSimulation(pore_node)
        elif simulation == MICP:
            self.runMICPSimulation(pore_node)

    def runOnePhaseSimulation(self, pore_node):
        self.applyButtonEnabled(False)
        slicer.app.processEvents()
        params = self.onePhaseSimWidget.getParams()
        params["subresolution function"] = params["subresolution function call"](pore_node)
        self.logic.run_1phase(
            pore_node,
            params,
            prefix=self.outputPrefix.text,
            callback=self.applyButtonEnabled,
        )

    def runTwoPhaseSimulation(self, pore_node):
        self.applyButtonEnabled(False)
        slicer.app.processEvents()
        params = self.twoPhaseSimWidget.getParams()
        params["subresolution function"] = params["subresolution function call"](pore_node)
        self.logic.run_2phase(
            pore_node,
            params,
            prefix=self.outputPrefix.text,
            callback=self.applyButtonEnabled,
        )

    def runMICPSimulation(self, pore_node):
        self.applyButtonEnabled(False)
        slicer.app.processEvents()
        params = self.mercurySimWidget.getParams()
        params["subresolution function"] = params["subresolution function call"](pore_node)
        self.logic.run_mercury(
            pore_node,
            params,
            prefix=self.outputPrefix.text,
            callback=self.applyButtonEnabled,
        )
