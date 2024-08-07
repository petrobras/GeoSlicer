import qt
import slicer
import ctk
import vtk
import importlib
import json
import logging
import nrrd
import numpy as np
import os
import pandas as pd
import random
import re
import signal
import shutil
import string
import subprocess
import time
import uuid
import psutil

from collections import defaultdict
from functools import partial
from ltrace.pore_networks.functions import geo2spy
from ltrace.readers.microtom import KrelCompiler, PorosimetryCompiler, StokesKabsCompiler
from ltrace.slicer import ui, helpers, widgets, data_utils as du
from ltrace.slicer.node_attributes import Tag, NodeEnvironment, TableType
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer.project_manager import ProjectManager
from ltrace.utils.ProgressBarProc import ProgressBarProc
from pathlib import Path

from PoreNetworkExtractor import PoreNetworkExtractorLogic
from PoreNetworkProduction import PoreNetworkProductionLogic
from PoreNetworkSimulationLib.OnePhaseSimulationWidget import OnePhaseSimulationWidget
from PoreNetworkSimulationLib.TwoPhaseSimulationWidget import TwoPhaseSimulationWidget, TwoPhaseParametersEditDialog
from PoreNetworkSimulationLib.PoreNetworkSimulationLogic import OnePhaseSimulationLogic, TwoPhaseSimulationLogic
from MercurySimulationLib.MercurySimulationWidget import MercurySimulationWidget, MercurySimulationLogic
from MercurySimulationLib.SubscaleModelWidget import SubscaleModelWidget, SubscaleLogicDict
from ltrace.pore_networks.simulation_parameters_node import dict_to_parameter_node
from RemoteTasks.OneResultSlurm import OneResultSlurmHandler

try:
    from StreamlitManager.StreamlitServerManager import StreamlitServerManager
except ImportError:
    StreamlitServerManager = None

# Checks if closed source code is available
try:
    from Test.MicrotomRemoteTest import MicrotomRemoteTest
except ImportError:
    MicrotomRemoteTest = None  # tests not deployed to final version or closed source

try:
    from Test.PoreNetworkReportTest import PoreNetworkReportTest
except ImportError:
    PoreNetworkReportTest = None  # tests not deployed to final version or closed source

WORKSPACES_REPO = "workspaces"


def generic_setter(widget, varname, value):
    setattr(widget, varname, max(getattr(widget, varname), value))


class SaturationCorrectionWidget(ctk.ctkCollapsibleButton):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.text = "Saturation correction (optional)"
        self.collapsed = True
        self.flat = True
        layout = qt.QFormLayout(self)
        self._correction = None

        self._por_map_table = ui.hierarchyVolumeInput(onChange=self.onSelect, hasNone=True)
        self._por_map_table.setNodeTypes(["vtkMRMLTableNode"])
        self._por_map_table.addNodeAttributeIncludeFilter("NodeEnvironment", "PorosityMap")
        self._total_micro_porosity_label = qt.QLabel()
        self._total_porosity_label = qt.QLabel()
        self._total_macro_porosity_label = qt.QLabel()

        layout.addRow("Porosity map table   ", self._por_map_table)
        layout.addRow("Total Microporosity  ", self._total_micro_porosity_label)
        layout.addRow("Total Macroporosity  ", self._total_macro_porosity_label)
        layout.addRow("Total Porosity  ", self._total_porosity_label)

    def reset(self):
        self._por_map_table.setCurrentNode(None)

    def onSelect(self, node):
        table_node = self._por_map_table.currentNode()

        self._correction = None
        self._total_micro_porosity_label.setText("")
        self._total_porosity_label.setText("")
        self._total_macro_porosity_label.setText("")

        if table_node is not None:
            try:
                df = slicer.util.dataframeFromTable(table_node)
                assert df.Property is not None
                assert df.Value is not None
                total_micropor_row = df.loc[df.Property == "Total Microporosity (%)"]
                total_porosity_row = df.loc[df.Property == "Total Porosity (Micro+Macro) (%)"]
                macro_por_row = df.loc[df.Property == "Macroporosity Segment (%)"]

                if len(total_micropor_row) == 1 and len(total_porosity_row) == 1 and len(macro_por_row) == 1:
                    total_micropor = float(total_micropor_row.values[0, 1])
                    self._total_micro_porosity_label.setText("{:05.2f} %".format(total_micropor))

                    total_porosity = float(total_porosity_row.values[0, 1])
                    self._total_porosity_label.setText("{:05.2f} %".format(total_porosity))

                    macro_por = float(macro_por_row.values[0, 1])
                    self._total_macro_porosity_label.setText("{:05.2f} %".format(macro_por))

                    self._correction = total_micropor / total_porosity
                else:
                    raise Exception()
            except:
                slicer.util.errorDisplay(
                    "Table needs the following rows:\nTotal Microporosity (%)\nTotal Porosity (Micro+Macro) (%)\nMacroporosity Segment (%)"
                )

    def vfrac(self):
        return self._correction


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


class CommonArgsForm(BaseArgsForm):
    def __init__(self, parent=None, availableDirections="all") -> None:
        super().__init__(parent)

        self.direction = qt.QComboBox()

        if availableDirections == "axis":
            self.direction.addItem("z")
            self.direction.addItem("y")
            self.direction.addItem("x")
        elif availableDirections == "all":
            self.direction.addItem("z")
            self.direction.addItem("z-")
            self.direction.addItem("z+")
            self.direction.addItem("y")
            self.direction.addItem("y-")
            self.direction.addItem("y+")
            self.direction.addItem("x")
            self.direction.addItem("x-")
            self.direction.addItem("x+")
            self.direction.addItem("all")
        else:
            raise ValueError(
                f"Invalid value for available directions. Expected 'axis', 'all' or True, got: {availableDirections}"
            )

        self.addArg(
            "Direction: ",
            self.direction,
            BaseArgsForm._createSetter(self.direction, "currentText", {"Local": "z", "Remote": "z"}),
        )

    def params(self):
        dirParam = {"direction": self.direction.currentText} if self.direction is not None else {}
        return dirParam


class DistributionsForm(BaseArgsForm):
    def __init__(self, parent=None, hasSatCorrection=False, hasResolutionConfig=False, initialTag="Local") -> None:
        super().__init__(parent)

        self.initialTag = initialTag

        if hasResolutionConfig:
            defaultSatRes = 0.03
            self.saturationResInput = ui.floatParam(value=defaultSatRes)
            self.addArg(
                "Saturation Resolution: ",
                self.saturationResInput,
                BaseArgsForm._createSetter(
                    self.saturationResInput, "text", {"Local": str(defaultSatRes), "Remote": str(defaultSatRes)}
                ),
            )

            defaultRadRes = 0.5
            self.radiusResInput = ui.floatParam(value=defaultRadRes)
            self.addArg(
                "Radius Resolution: ",
                self.radiusResInput,
                BaseArgsForm._createSetter(
                    self.radiusResInput, "text", {"Local": str(defaultRadRes), "Remote": str(defaultRadRes)}
                ),
            )

        if hasSatCorrection:
            self.saturation_correction = SaturationCorrectionWidget()
            self.layout().addRow(self.saturation_correction)

        self.nThreadsInput = ui.numberParam((2, 4096), 2, step=1, decimals=0)

        self.addArg(
            "Number of Threads: ",
            self.nThreadsInput,
            BaseArgsForm._createSetter(self.nThreadsInput, "value", {"Local": None, "Remote": 40}),
        )

    def setup(self):
        self.showOnly(self.initialTag)

    def params(self):
        nthreads = int(self.nThreadsInput.value) or 2
        satParam = {"vfrac": self.saturation_correction.vfrac()} if hasattr(self, "saturation_correction") else {}
        satResParam = (
            {"sat_resolution": float(self.saturationResInput.text)} if hasattr(self, "saturationResInput") else {}
        )
        radResParam = {"rad_resolution": float(self.radiusResInput.text)} if hasattr(self, "radiusResInput") else {}
        return (
            {**super().params(), "n_threads_per_node": nthreads, "verbose": True} | satParam | satResParam | radResParam
        )

    def reset(self):
        if hasattr(self, "saturation_correction"):
            self.saturation_correction.reset()


class DirectedDistributionForm(DistributionsForm, CommonArgsForm):
    def __init__(self, parent=None, initialTag="Local") -> None:
        super().__init__(parent, hasSatCorrection=True, hasResolutionConfig=True, initialTag=initialTag)


class RemoteSimulationForm(CommonArgsForm):
    def __init__(self, parent=None, initialTag="Remote") -> None:
        super().__init__(parent, availableDirections="axis")

        self.initialTag = initialTag

        self.nThreadsInput = ui.numberParam((1, 4096), 1, step=1, decimals=0)

        self.addArg(
            "Number of Threads: ",
            self.nThreadsInput,
            BaseArgsForm._createSetter(self.nThreadsInput, "value", {"Local": None, "Remote": 40}),
        )

    def setup(self):
        self.showOnly(self.initialTag)

    def params(self):
        nthreads = int(self.nThreadsInput.value) or 1
        return {**super().params(), "n_threads": nthreads, "verbose": False}


class KabsForm(RemoteSimulationForm):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.nNodesInput = ui.numberParam((1, 64), 1, step=1, decimals=0)

        self.addArg(
            "Number of Nodes: ",
            self.nNodesInput,
            BaseArgsForm._createSetter(self.nNodesInput, "value", {"Local": None, "Remote": 1}),
        )

    def params(self):
        nNodes = int(self.nNodesInput.value) or 1
        return {**super().params(), "verbose": False, "n_nodes": nNodes}


class DarcyKabsForm(RemoteSimulationForm):
    def params(self):
        return super().params() | {"verbose": False}


class KabsRevForm(KabsForm):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.nSamplesInput = ui.numberParam((2, 64), 2, step=1, decimals=0)
        self.addArg(
            "Number of Samples: ",
            self.nSamplesInput,
            BaseArgsForm._createSetter(self.nSamplesInput, "value", {"Local": None, "Remote": 2}),
        )

    def params(self):
        nNodes = int(self.nNodesInput.value) or 1
        nSamples = int(self.nSamplesInput.value) or 2

        return {
            **super().params(),
            "n_nodes": nNodes,
            "n_samples": nSamples,
        }


class KrelForm(KabsForm):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        grammar = qt.QRegularExpression(r"\s*(\d+(\.\d*)?)(,\s*(\d+(\.\d*)?)\s*)*\s*")
        valid = qt.QRegularExpressionValidator(grammar, self)

        self.diametersInputList = qt.QLineEdit()
        self.diametersInputList.setValidator(valid)
        self.nstepsInput = ui.numberParam((1, 20000000), 4000, step=1, decimals=0)
        self.alphaInput = ui.floatParam(value=0.1)
        self.betaInput = ui.floatParam(value=0.9)
        self.tauSymNWInput = ui.floatParam(value=1.0)
        self.tauSymWInput = ui.floatParam(value=1.0)
        self.wallConcentrationInput = ui.floatParam(value=0.2)
        self.dpInput = ui.floatParam(value=0.006)
        self.saturationStarter = qt.QComboBox()
        self.saturationStarter.addItem("Pore Size Distribution", "psd")
        self.saturationStarter.addItem("Hierarquical Pore Size Distribution", "hpsd")
        self.saturationStarter.addItem("Mercury Injection Capillary Pressure", "micp")

        self.addArg(
            "Number of Steps: ",
            self.nstepsInput,
            BaseArgsForm._createSetter(self.nstepsInput, "value", {"Local": None, "Remote": 4000}),
        )

        self.addArg(
            "Diameters: ",
            self.diametersInputList,
            BaseArgsForm._createSetter(self.diametersInputList, "text", {"Local": None, "Remote": ""}),
        )

        self.addArg(
            "Alpha: ",
            self.alphaInput,
            BaseArgsForm._createSetter(self.alphaInput, "text", {"Local": None, "Remote": "0.1"}),
        )

        self.addArg(
            "Beta: ",
            self.betaInput,
            BaseArgsForm._createSetter(self.betaInput, "text", {"Local": None, "Remote": "0.9"}),
        )

        self.addArg(
            "Tau Symmetric NW: ",
            self.tauSymNWInput,
            BaseArgsForm._createSetter(self.tauSymNWInput, "text", {"Local": None, "Remote": "1.0"}),
        )

        self.addArg(
            "Tau Symmetric W: ",
            self.tauSymWInput,
            BaseArgsForm._createSetter(self.tauSymWInput, "text", {"Local": None, "Remote": "1.0"}),
        )

        self.addArg(
            "Wall Concentration: ",
            self.wallConcentrationInput,
            BaseArgsForm._createSetter(self.wallConcentrationInput, "text", {"Local": None, "Remote": "0.2"}),
        )

        self.addArg(
            "DP: ",
            self.dpInput,
            BaseArgsForm._createSetter(self.dpInput, "text", {"Local": None, "Remote": "0.006"}),
        )

        self.addArg(
            "Saturation Data: ",
            self.saturationStarter,
            BaseArgsForm._createSetter(self.saturationStarter, "currentText", {"Local": None, "Remote": "psd"}),
        )

    def setup(self):
        self.showOnly("Remote")

    def params(self):
        diameters = self.diametersInputList.text
        return {
            **super().params(),
            "cluster": "atena",
            "diameters": rf"[{diameters}]",
            "number_of_steps": int(self.nstepsInput.value),
            "alpha": float(self.alphaInput.text),
            "beta": float(self.betaInput.text),
            "tau_symmetric_nw": float(self.tauSymNWInput.text),
            "tau_symmetric_w": float(self.tauSymWInput.text),
            "wall_concentration": float(self.wallConcentrationInput.text),
            "dp": float(self.dpInput.text),
            "saturation_data": self.saturationStarter.currentData,
        }


class PNMReportForm(BaseArgsForm):
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
            BaseArgsForm._createSetter(self.parameterInputWidget, "currentText", {"Local": "none", "Remote": None}),
        )

        self.addArg(
            "Subscale Pressure Model: ",
            self.subscaleModelWidget.microscale_model_dropdown,
            BaseArgsForm._createSetter(self.parameterInputWidget, "currentText", {"Local": "none", "Remote": None}),
        )
        self.subscaleModelWidget.microscale_model_dropdown.objectName = "MicroscaleDropdown"

        for label, widget in self.subscaleModelWidget.parameter_widgets.items():
            self.layout().addRow(widget)

        self.addArg(
            "Well Name: ",
            self.wellName,
            BaseArgsForm._createSetter(self.wellName, "plainText", {"Local": "", "Remote": None}),
        )

    def onParameterEdit(self):
        node = self.parameterInputWidget.currentNode()
        if not node:
            slicer.util.infoDisplay("Please, select a node to be edited.")
            return

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
        }


#
# MicrotomRemote
#
class MicrotomRemote(LTracePlugin):
    SETTING_KEY = "MicrotomRemote"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    FORMATS = {
        ".nc": "NetCDF4 (.nc)",
        ".raw": "Binary (.raw)",
        ".vtk": "VTK (.vtk)",
        ".h5": "HDF5 (.h5)",
        ".tar": "TAR (.tar)",
        ".tif": "TIFF (.tif)",
    }

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Microtom Remote"
        self.parent.categories = ["Micro CT"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]  # replace with "Firstname Lastname (Organization)"
        self.parent.helpText = ""
        self.parent.helpText += MicrotomRemote.help()
        self.parent.acknowledgementText = ""

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


#
# MicrotomRemoteWidget
#


class MicrotomRemoteWidget(LTracePluginWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.logic = None
        self.loadedFiles = None

        self.chosenExecutionMode = "Local"

        self.currentMode = ""
        self.logicType = MicrotomRemoteLogic

    def _createLogic(self, logicCls: LTracePluginLogic):
        if self.logic is not None and isinstance(self.logic, logicCls):
            return self.logic

        if self.logic is not None:
            del self.logic

        self.logic = logicCls(self.parent, self.progressBar)
        self.logic.processFinished.connect(self.restartApplyButton)

        return self.logic

    def setup(self):
        LTracePluginWidget.setup(self)

        importlib.reload(widgets)

        self.MODES = [widgets.SingleShotInputWidget, widgets.BatchInputWidget]

        self.loadedFiles = {}

        self.modeSelectors = {}
        self.modeWidgets = {}

        # Instantiate and connect widgets ...
        self.layout.addWidget(self._setupMethodsSection())
        self.layout.addWidget(self._setupInputsSection())
        self.layout.addWidget(self._setupConfigSection())
        self.layout.addWidget(self._setupOutput())
        self.serverManager = self._setupServerManager()
        self.layout.addWidget(self.serverManager)

        def resetAll():
            for i in range(self.configWidget.count):
                self.configWidget.widget(i).reset()

        self.modeWidgets[widgets.SingleShotInputWidget.MODE_NAME].segmentListUpdated.connect(resetAll)

        self.modeSelectors[widgets.SingleShotInputWidget.MODE_NAME].setChecked(True)

        self.simBtn.enabled = False
        self.canBtn.enabled = False
        self.canBtn.hide()

        self.serverManager.hide()

        # Add vertical spacer
        self.layout.addStretch(1)

        self._onSimulSelected(0)

        self._createLogic(logicCls=MicrotomRemoteLogic)

    def _setupMethodsSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Methods"
        layout = qt.QVBoxLayout(widget)
        methodsLayout = qt.QFormLayout()

        self.simOptions = qt.QComboBox()
        self.simOptions.addItem("PNM Complete Workflow", "pnm")
        self.simOptions.addItem("---------")
        self.simOptions.addItem("Pore Size Distribution", "psd")
        self.simOptions.addItem("Hierarquical Pore Size Distribution", "hpsd")
        self.simOptions.addItem("Mercury Injection Capillary Pressure", "micp")
        self.simOptions.addItem("Incompressible Drainage Capillary Pressure", "drainage_incompressible")
        self.simOptions.addItem("Imbibition Capillary Pressure", "imbibition_compressible")
        self.simOptions.addItem("Incompressible Imbibition Capillary Pressure", "imbibition_incompressible")
        self.simOptions.addItem("Absolute Permeability", "stokes_kabs")
        self.simOptions.addItem("Absolute Permeability - Representative Elementary Volume", "stokes_kabs_rev")
        self.simOptions.addItem("Absolute Permeability - Darcy FOAM", "darcy_kabs_foam")
        self.simOptions.addItem("Relative Permeability", "krel")

        combo_model = self.simOptions.model()
        separator_index = combo_model.index(1, 0)
        separator_item = combo_model.itemFromIndex(separator_index)
        separator_item.setFlags(separator_item.flags() & ~qt.Qt.ItemIsSelectable & ~qt.Qt.ItemIsEnabled)

        self.simOptions.setToolTip("Select a simulation MicroTom method.")
        self.simOptions.currentIndexChanged.connect(self._onSimulSelected)
        self.simOptions.objectName = "SimulationComboBox"
        methodsLayout.addRow("Select a Simulation: ", self.simOptions)
        layout.addLayout(methodsLayout)
        return widget

    def _setupInputsSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Inputs"
        layout = qt.QVBoxLayout(widget)

        optionsLayout = qt.QHBoxLayout()
        optionsLayout.setAlignment(qt.Qt.AlignLeft)
        optionsLayout.setContentsMargins(0, 0, 0, 0)
        self.optionsStack = qt.QStackedWidget()

        self.mode_label = qt.QLabel("Select input mode:")
        optionsLayout.addWidget(self.mode_label)

        btn1 = qt.QRadioButton(widgets.SingleShotInputWidget.MODE_NAME)
        btn1.objectName = "Single Shot Mode Radio Button"
        self.modeSelectors[widgets.SingleShotInputWidget.MODE_NAME] = btn1
        optionsLayout.addWidget(btn1)
        btn1.toggled.connect(self._onModeClicked)
        panel1 = widgets.SingleShotInputWidget(dimensionsUnits={"px": True, "mm": True})
        panel1.objectName = "SingleShotInputWidget"

        panel1.onMainSelectedSignal.connect(self._onInputSelected)
        panel1.onReferenceSelectedSignal.connect(self._onReferenceSelected)
        self.modeWidgets[widgets.SingleShotInputWidget.MODE_NAME] = panel1
        self.optionsStack.addWidget(self.modeWidgets[widgets.SingleShotInputWidget.MODE_NAME])

        # This will be hidden when the method input is a scalar with a SOI
        # currently only for darcy
        self.hideWhenInputIsScalar = [
            panel1.segmentationLabel,
            panel1.mainInput,
            panel1.segmentsContainerWidget,
        ]

        btn2 = qt.QRadioButton(widgets.BatchInputWidget.MODE_NAME)
        btn2.objectName = "Batch Mode Radio Button"

        self.modeSelectors[widgets.BatchInputWidget.MODE_NAME] = btn2
        optionsLayout.addWidget(btn2)
        btn2.toggled.connect(self._onModeClicked)
        panel2 = widgets.BatchInputWidget(objectNamePrefix="Microtom Remote Batch")
        panel2.onDirSelected = self._onInputSelected
        self.modeWidgets[widgets.BatchInputWidget.MODE_NAME] = panel2
        self.optionsStack.addWidget(self.modeWidgets[widgets.BatchInputWidget.MODE_NAME])

        self.mode_label.hide()
        btn1.hide()
        btn2.hide()

        layout.addLayout(optionsLayout)
        layout.addWidget(self.optionsStack)

        return widget

    def _setupConfigSection(self):
        # def buildVarList():
        #     hBox = qt.QHBoxLayout()
        #     self.ioFileVariablesList = qt.QListWidget()
        #     self.ioFileVariablesList.selectionMode = qt.QAbstractItemView.ExtendedSelection
        #     hBox.addWidget(self.ioFileVariablesList)
        #     return hBox

        ioPage = ctk.ctkCollapsibleButton()
        ioPage.text = "Parameters"
        ioPageLayout = qt.QVBoxLayout(ioPage)

        self.ioFileNameLabel = qt.QLabel("")
        self.ioFileExtLabel = qt.QLabel("")
        self.ioFileSizeLabel = qt.QLabel("")

        self.warningLabel = qt.QLabel(
            "Warning: To use remote execution you must guarantee that your Host is accessible, \n"
            "'Number of Threads' parameter must not be greater than the Host's number of cores and \n"
            "has Microtom pre-installed."
        )
        self.warningLabel.setStyleSheet("QLabel { color : yellow; }")
        self.warningLabel.hide()

        self.nThreadsInput = ui.numberParam((1, 4096), 1, step=1, decimals=0)
        self.nThreadsInput.enabled = False

        self.nNodesInput = ui.numberParam((1, 64), 1, step=1, decimals=0)
        self.nNodesInput.enabled = False

        self.nSamplesInput = ui.numberParam((2, 64), 2, step=1, decimals=0)

        self.krelSettings = self._setupKrelParameters()
        self.krelSettings.hide()

        self.configWidget = qt.QStackedWidget()

        self.psdConfigWidget = DistributionsForm(hasSatCorrection=True, hasResolutionConfig=True)
        self.hpsdConfigWidget = DistributionsForm(hasSatCorrection=True, hasResolutionConfig=False)
        self.distribWidget = DirectedDistributionForm()
        self.pnmReportWidget = PNMReportForm()
        self.pnmReportWidget.objectName = "PNMReportForm"

        self.configWidget.addWidget(self.pnmReportWidget)
        self.configWidget.addWidget(self.psdConfigWidget)
        self.configWidget.addWidget(self.hpsdConfigWidget)
        self.configWidget.addWidget(self.distribWidget)
        self.configWidget.addWidget(KabsForm())
        self.configWidget.addWidget(KabsRevForm())
        self.configWidget.addWidget(DarcyKabsForm())
        self.configWidget.addWidget(KrelForm())

        for i in range(self.configWidget.count):
            self.configWidget.widget(i).setup()

        self.ioFileExecDataSetButton = self._setupExecEnv()
        self.ioFileExecDataSetButton.setToolTip("Select how the algorithm will run, locally or remotely")

        ioPageFormLayout = qt.QFormLayout()

        ioPageFormLayout.addRow("Execution Mode: ", self.ioFileExecDataSetButton)
        ioPageFormLayout.addRow(self.warningLabel)
        ioPageFormLayout.addRow(self.configWidget)
        # ioPageFormLayout.addRow("Number of Threads: ", self.nThreadsInput)
        # ioPageFormLayout.addRow("Number of Nodes: ", self.nNodesInput)
        ioPageFormLayout.addRow("Number of Samples: ", self.nSamplesInput)
        self.nSamplesInputLabel = ioPageFormLayout.labelForField(self.nSamplesInput)
        self.nSamplesInputLabel.hide()
        self.nSamplesInput.hide()

        ioPageLayout.addLayout(ioPageFormLayout)
        ioPageLayout.addWidget(self.krelSettings)

        return ioPage

    def _setupExecEnv(self):
        self.execOptions = {"Local": None, "Remote": None}

        parent = qt.QWidget()

        optionsLayout = qt.QHBoxLayout(parent)
        optionsLayout.setAlignment(qt.Qt.AlignLeft)
        optionsLayout.setContentsMargins(0, 0, 0, 0)
        for option in self.execOptions:
            btn1 = qt.QRadioButton(option)
            optionsLayout.addWidget(btn1, 0, qt.Qt.AlignCenter)
            btn1.toggled.connect(lambda toggle, opt=option: self.onLocationToggled(opt, toggle))
            self.execOptions[option] = btn1

        # optionsLayout.itemAt(0).widget().setChecked(True)
        self.execOptions["Local"].setChecked(True)

        return parent

    def _setupKrelParameters(self):
        widget = qt.QWidget()
        formBox = qt.QFormLayout(widget)

        grammar = qt.QRegularExpression(r"\s*(\d+(\.\d*)?)(,\s*(\d+(\.\d*)?)\s*)*\s*")
        valid = qt.QRegularExpressionValidator(grammar, widget)

        self.diametersInputList = qt.QLineEdit()
        self.diametersInputList.setValidator(valid)
        self.nstepsInput = ui.numberParam((1, 20000000), 4000, step=1, decimals=0)
        self.alphaInput = ui.floatParam(value=0.1)
        self.betaInput = ui.floatParam(value=0.9)
        self.tauSymNWInput = ui.floatParam(value=1.0)
        self.tauSymWInput = ui.floatParam(value=1.0)
        self.wallConcentrationInput = ui.floatParam(value=0.2)
        self.dpInput = ui.floatParam(value=0.006)
        self.saturationStarter = qt.QComboBox()
        self.saturationStarter.addItem("Pore Size Distribution", "psd")
        self.saturationStarter.addItem("Hierarquical Pore Size Distribution", "hpsd")
        self.saturationStarter.addItem("Mercury Injection Capillary Pressure", "micp")

        formBox.addRow("Number of steps: ", self.nstepsInput)
        formBox.addRow("Diameters: ", self.diametersInputList)
        formBox.addRow("Alpha: ", self.alphaInput)
        formBox.addRow("Beta: ", self.betaInput)
        formBox.addRow("Tau Symmetric NW: ", self.tauSymNWInput)
        formBox.addRow("Tau Symmetric W: ", self.tauSymWInput)
        formBox.addRow("Wall Concentration: ", self.wallConcentrationInput)
        formBox.addRow("DP: ", self.dpInput)
        formBox.addRow("Saturation Data: ", self.saturationStarter)

        return widget

    def _setupOutput(self):
        ioSection = ctk.ctkCollapsibleButton()
        ioSection.text = "Output"
        ioPageLayout = qt.QVBoxLayout(ioSection)

        self.ioFileOutputLineEdit = ctk.ctkPathLineEdit()
        self.ioFileOutputLineEdit.setToolTip("Location to store downloaded .nc files. (defaults to temporary file)")
        self.ioFileOutputLineEdit.filters = ctk.ctkPathLineEdit.Dirs
        self.ioFileOutputLineEdit.settingKey = "ioFileoutputMicrotom"

        self.outputPrefix = qt.QLineEdit()
        self.outputPrefix.objectName = "Output Prefix Line Edit"

        self.simBtn = qt.QPushButton("Apply")
        self.simBtn.setStyleSheet("QPushButton {font-size: 11px; font-weight: bold; padding: 8px; margin: 4px}")
        self.simBtn.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Preferred)
        self.simBtn.objectName = "Apply PushButton"

        self.simBtn.clicked.connect(self.onExecuteClicked)

        self.canBtn = qt.QPushButton("Cancel")
        self.canBtn.setStyleSheet("QPushButton {font-size: 11px; font-weight: bold; padding: 8px; margin: 4px}")
        self.canBtn.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Preferred)
        self.canBtn.objectName = "CancelButton"
        self.canBtn.clicked.connect(self.onCancelClicked)

        self.dialogShowWidget = self.showThreads()

        self.ioResultsComboBox = qt.QHBoxLayout()
        # self.ioThreadsLabel = qt.QLabel("You have 0 job(s) running")
        self.ioThreadsButton = qt.QPushButton("Show")
        self.ioThreadsButton.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Preferred)
        self.ioResultsComboBox.addStretch(1)
        # self.ioResultsComboBox.addWidget(self.ioThreadsLabel)
        self.ioResultsComboBox.addWidget(self.ioThreadsButton)

        self.progressBar = LocalProgressBar()
        self.ioThreadsButton.clicked.connect(lambda: slicer.util.selectModule("JobMonitor"))

        ioPageFormLayout = qt.QFormLayout()
        # ioPageFormLayout.addRow('Store result at (optional) : ', self.ioFileOutputLineEdit)
        ioPageFormLayout.addRow("Output Prefix: ", self.outputPrefix)

        ioPageLayout.addLayout(ioPageFormLayout)

        hbox = qt.QHBoxLayout()
        hbox.addWidget(self.simBtn)
        hbox.addWidget(self.canBtn)
        ioPageLayout.addLayout(hbox)

        ioPageLayout.addLayout(self.ioResultsComboBox)

        ioPageLayout.addWidget(self.progressBar)

        ioPageLayout.addStretch(1)

        return ioSection

    def _setupServerManager(self):
        ioSection = ctk.ctkCollapsibleButton()
        ioSection.text = "Server Management"
        ioPageLayout = qt.QVBoxLayout(ioSection)

        self.toggleServerButton = qt.QPushButton("Start Streamlit Server")
        self.toggleServerButton.setStyleSheet("")
        self.toggleServerButton.objectName = "ToggleServerButton"

        self.serverStatus = qt.QLabel("Stopped")
        self.serverStatus.setFixedHeight(25)
        self.serverStatus.setOpenExternalLinks(True)
        self.serverStatus.objectName = "ServerStatusLabel"

        if StreamlitServerManager is not None:
            self.server = StreamlitServerManager(self.simOptions, self.serverStatus, self.toggleServerButton)
            self.server.objectName = "Streamlit Server Manager"
        else:
            self.server = None
            self.toggleServerButton.clicked.connect(self.onStreamlitServerUnavailable)

        ioPageFormLayout = qt.QFormLayout()
        ioPageFormLayout.addRow("Streamlit Server: ", self.toggleServerButton)
        ioPageFormLayout.addRow("Streamlit Server Status: ", self.serverStatus)
        ioPageLayout.addLayout(ioPageFormLayout)

        ioPageLayout.addStretch(1)

        LOCK_FILE = f"{slicer.app.slicerHome}/LTrace/streamlit_server.lock"
        if Path(LOCK_FILE).exists():
            try:
                lock_file = open(Path(LOCK_FILE), "r")
                line = lock_file.readline()
                self.server.pid = int(line.split("=")[1])
                line = lock_file.readline()
                self.server.ip_addr = line.split("=")[1][:-1]
                lock_file.close()

                if self.server.ip_addr is not None:
                    self.toggleServerButton.setStyleSheet("QPushButton {color: #00FF00}")
                    self.toggleServerButton.text = "Stop Streamlit Server"
                    self.serverStatus.text = f'Running in <a href="{self.ip_addr}">{self.ip_addr}</a>'
                else:
                    slicer.util.errorDisplay(
                        "Error in retrieving ip address from server, try again, or check if the port 8501 is available and if has a already running instance of streamlit."
                    )
                    self.server.killStreamlitServer()
            except Exception as e:
                os.remove(Path(LOCK_FILE))
                import traceback

                traceback.print_exc()

        return ioSection

    def onStreamlitServerUnavailable(self):
        slicer.util.errorDisplay("Server unavailable at this version.")

    def showThreads(self):
        dialogWidget = qt.QDialog(self.parent)
        dialogWidget.setModal(True)
        dialogWidget.setWindowTitle("Running Jobs")

        bodyLayout = qt.QVBoxLayout(dialogWidget)

        self.ioRunningComboBox = qt.QListWidget()
        self.ioRunningComboBox.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Preferred)
        bodyLayout.addWidget(self.ioRunningComboBox)
        self.cliCancelButton = qt.QPushButton("Stop")
        self.cliCancelButton.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Preferred)
        self.cliCancelButton.enabled = False
        bodyLayout.addWidget(self.cliCancelButton)

        def onSelectionChanged():
            self.cliCancelButton.enabled = True

        self.ioRunningComboBox.itemSelectionChanged.connect(onSelectionChanged)
        self.cliCancelButton.clicked.connect(self.onCLICancelCLicked)

        return dialogWidget

    def onLocationToggled(self, option, toggle):
        if toggle:
            self.chosenExecutionMode = option
            self.configWidget.currentWidget().showOnly(option)

            self.warningLabel.visible = self.chosenExecutionMode == "Remote"

    def _disableSwitchFor(self, btn, keep):
        self.execOptions[btn].enabled = False
        self.execOptions[keep].enabled = True
        self.execOptions[keep].setChecked(True)
        self.onLocationToggled(keep, True)

    def _enableAllSwitches(self):
        prev = "Local"
        for sw in self.execOptions:
            if self.execOptions[sw].isChecked():
                prev = sw

            self.execOptions[sw].enabled = True
        self.onLocationToggled(prev, True)
        self.execOptions[prev].setChecked(True)

    def _onSimulSelected(self, index):
        self.modeSelectors[widgets.SingleShotInputWidget.MODE_NAME].setChecked(True)

        self.mode_label.hide()
        for key, widget in self.modeSelectors.items():
            widget.hide()

        self.canBtn.hide()

        self.serverManager.hide()

        modeWidget = self.modeWidgets[widgets.SingleShotInputWidget.MODE_NAME]
        batchWidget = self.modeWidgets[widgets.BatchInputWidget.MODE_NAME]
        if "darcy_kabs_foam" in self.simOptions.currentData:
            self.logicType = MicrotomRemoteLogic

            for widget in self.hideWhenInputIsScalar:
                widget.visible = False
            modeWidget.mainInput.setCurrentNode(None)
            modeWidget.mainInput.visible = False
            modeWidget.soiInput.enabled = True
            modeWidget.referenceInput.enabled = True
        if "pnm" in self.simOptions.currentData:
            self.serverManager.show()

            self.mode_label.show()
            for key, widget in self.modeSelectors.items():
                widget.show()
            self.canBtn.show()
            self.logicType = PNMLogic

            for widget in self.hideWhenInputIsScalar:
                widget.visible = False
            modeWidget.mainInput.setCurrentNode(None)
            modeWidget.mainInput.visible = False
            modeWidget.soiInput.setCurrentNode(None)
            modeWidget.soiLabel.visible = False
            modeWidget.soiInput.visible = False
            modeWidget.referenceInput.enabled = True

            batchWidget.ioBatchValTagLabel.text = "Image Suffix:"
            batchWidget.ioBatchValTagPattern.text = ".nrrd"
            batchWidget.ioBatchROITagLabel.visible = False
            batchWidget.ioBatchSegTagLabel.visible = False
            batchWidget.ioBatchLabelLabel.visible = False
            batchWidget.ioBatchROITagPattern.visible = False
            batchWidget.ioBatchSegTagPattern.visible = False
            batchWidget.ioBatchLabelPattern.visible = False
        else:
            self.logicType = MicrotomRemoteLogic

            for widget in self.hideWhenInputIsScalar:
                widget.visible = True
            modeWidget.mainInput.visible = True
            if modeWidget.mainInput.currentNode() is None:
                modeWidget.referenceInput.setCurrentNode(None)

        if "krel" in self.simOptions.currentData:
            self.configWidget.setCurrentIndex(7)
            self._disableSwitchFor("Local", keep="Remote")
        elif "darcy" in self.simOptions.currentData:
            self.configWidget.setCurrentIndex(6)
            self._disableSwitchFor("Local", keep="Remote")
        elif "kabs_rev" in self.simOptions.currentData:
            self.configWidget.setCurrentIndex(5)
            self._disableSwitchFor("Local", keep="Remote")
        elif "kabs" in self.simOptions.currentData:
            self.configWidget.setCurrentIndex(4)
            self._disableSwitchFor("Local", keep="Remote")
        elif "hpsd" in self.simOptions.currentData:
            self.configWidget.setCurrentIndex(2)
            self._enableAllSwitches()
        elif "psd" in self.simOptions.currentData:
            self.configWidget.setCurrentIndex(1)
            self._enableAllSwitches()
        elif "pnm" in self.simOptions.currentData:
            self.configWidget.setCurrentIndex(0)
            self._disableSwitchFor("Remote", keep="Local")
        else:
            self.configWidget.setCurrentIndex(3)
            self._enableAllSwitches()

    def _onModeClicked(self):
        for index, mode in enumerate(self.MODES):
            try:
                if self.modeSelectors[mode.MODE_NAME].isChecked():
                    self.currentMode = mode.MODE_NAME
                    self.optionsStack.setCurrentIndex(index)
                    break
            except KeyError as ke:
                # happens only during initialization
                pass

    def _onInputSelected(self, node):
        self.simBtn.enabled = node is not None
        self.canBtn.enabled = False

        if node is None or isinstance(node, str):
            return

        # Get name first to avoid using reference node name
        nodeName = node.GetName()

        if node.IsA("vtkMRMLSegmentationNode"):
            node = helpers.getSourceVolume(node)
            if node is None:
                return

        self.outputPrefix.setText(nodeName)

    def _onReferenceSelected(self, node):

        if "darcy_kabs_foam" in self.simOptions.currentData:
            self.simBtn.enabled = node is not None

            if node is None:
                return

            self.canBtn.enabled = False
            nodeName = node.GetName()
            tokens = nodeName.split("_")
            if len(tokens) < 4:
                arr = slicer.util.arrayFromVolume(node).astype(np.float64)
                image_type = "KABS"

                shape = ["{:04d}".format(int(d)) for d in arr.shape[::-1]]
                res = min([v for v in node.GetSpacing()])

                nodeName = "_".join([*tokens, image_type, *shape, "{:05d}".format(int(round(res * 1e6))) + "nm"])

            self.outputPrefix.setText(nodeName)
        elif "pnm" in self.simOptions.currentData:
            self.simBtn.enabled = node is not None
            self.canBtn.enabled = False

            if node is None:
                return

            nodeName = node.GetName()
            tokens = nodeName.split("_")
            if len(tokens) < 4:
                arr = slicer.util.arrayFromVolume(node).astype(np.float64)  # TODO Precisa converter para array?
                image_type = "PNM"

                shape = ["{:04d}".format(int(d)) for d in arr.shape[::-1]]
                res = min([v for v in node.GetSpacing()])

                nodeName = "_".join([*tokens, image_type, *shape, "{:05d}".format(int(round(res * 1e6))) + "nm"])

            self.outputPrefix.setText(nodeName)
            self.pnmReportWidget.wellName.setText(nodeName)

    def onSelectionChanged(self):
        items = self.ioFileVariablesList.selectedItems()
        self.ioFileLoadDataSetButton.enabled = len(items) > 0

    def onCLICancelCLicked(self):
        try:
            text = self.ioRunningComboBox.currentItem().text()
            amatch = re.search(r"\[(.*)\]", text)
            if amatch:
                workspace = amatch.group(1)
                logging.debug(f"Cancelling {workspace}")
                self.logic.cancelRemoteExecution(workspace)
        except Exception as e:
            pass

    def onPathChanged(self, pathstring: str):
        if len(pathstring) == 0:
            slicer.util.errorDisplay("Empty path. Please, review your entry.")
            return

        selectedPath = Path(pathstring)
        if not selectedPath.exists():
            slicer.util.errorDisplay("Invalid path. Please, review your entry.")
            return

        self.ioFileNameLabel.setText(selectedPath.name)
        self.ioFileExtLabel.setText(
            MicrotomRemote.FORMATS.get(
                selectedPath.suffix,
                f'<div><div>{selectedPath.suffix}</div> <div style="color:red">not supported</div></div>',
            )
        )

        szInBytes = selectedPath.stat().st_size
        szInKBytes = szInBytes // 1024
        self.ioFileSizeLabel.setText(f"{szInKBytes} KB")

        if selectedPath.suffix not in MicrotomRemote.FORMATS:
            slicer.util.errorDisplay(
                "This file format is not supported by the current implementation. Please, review your entry."
            )
            return

    def showJobs(self):
        """this function open a dialog to confirm and if yes, emit the signal to delete the results"""
        msg = qt.QMessageBox()
        msg.setIcon(qt.QMessageBox.Warning)
        msg.setText("Your job was succesfully scheduled on cluster. Do you want to move to job monitor view?")
        msg.setWindowTitle("Show jobs")
        msg.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.No)
        msg.setDefaultButton(qt.QMessageBox.No)
        if msg.exec_() == qt.QMessageBox.Yes:
            slicer.util.selectModule("JobMonitor")

    def onExecuteClicked(self):
        try:
            self._createLogic(logicCls=self.logicType)
            self.simBtn.enabled = False
            self.simBtn.blockSignals(True)
            self.canBtn.enabled = True
            self.canBtn.blockSignals(False)
            slicer.app.processEvents()

            modeWidget = self.modeWidgets[self.currentMode]

            if self.currentMode == widgets.BatchInputWidget.MODE_NAME:
                inputNode = None
                batchDir = modeWidget.ioFileInputLineEdit.currentPath
                segTag = modeWidget.ioBatchSegTagPattern.text
                roiTag = modeWidget.ioBatchROITagPattern.text
                valTag = modeWidget.ioBatchValTagPattern.text
                labelTag = modeWidget.ioBatchLabelPattern.text
            else:
                inputNode = modeWidget.mainInput.currentNode()
                roiNode = modeWidget.soiInput.currentNode()
                refNode = modeWidget.referenceInput.currentNode()

            outputPathStr = self.ioFileOutputLineEdit.currentPath
            if outputPathStr:
                if Path(outputPathStr).exists():
                    outputPath = self.ioFileOutputLineEdit.currentPath
                    helpers.save_path(self.ioFileOutputLineEdit)
                else:
                    slicer.util.errorDisplay("Invalid output path. Please, review your entry.")
                    return
            else:
                outputPath = None

            if inputNode is not None:
                selection = modeWidget.getSelectedSegments()
                if inputNode.IsA("vtkMRMLSegmentationNode"):
                    segmap = helpers.segmentListAndProportionsFromSegmentation(inputNode, roiNode)
                else:
                    segmap = helpers.segmentProportionFromLabelMap(inputNode, roiNode)

                labels = sorted(v for v in segmap if v != "total")
                labelselection = [labels[i] for i in selection]
            else:
                labelselection = None

            params = self.configWidget.currentWidget().params()

            if self.currentMode == widgets.BatchInputWidget.MODE_NAME:
                uid = self.logic.runInBatch(
                    self.simOptions.currentData,
                    inputNode,
                    batchDir,
                    segTag,
                    roiTag,
                    valTag,
                    labelTag,
                    output_path=outputPath,
                    mode=self.chosenExecutionMode,
                    outputPrefix=self.outputPrefix.text,
                    params=params,
                )
            else:
                uid = self.logic.run(
                    self.simOptions.currentData,
                    inputNode,
                    refNode,
                    labels=labelselection,
                    roiNode=roiNode,
                    output_path=outputPath,
                    mode=self.chosenExecutionMode,
                    outputPrefix=self.outputPrefix.text,
                    params=params,
                )

            if self.chosenExecutionMode == "Remote" and uid:
                self.showJobs()

        except Exception as e:
            print(repr(e))

    def restartApplyButton(self):
        slicer.app.processEvents()
        self.simBtn.blockSignals(False)
        self.simBtn.enabled = True
        self.canBtn.blockSignals(True)
        self.canBtn.enabled = False

    def onCancelClicked(self):
        self.logic.cancel()
        self.restartApplyButton()


class MicrotomRemoteLogicBase(LTracePluginLogic):
    processFinished = qt.Signal()

    def __init__(self, parent, progressBar):
        LTracePluginLogic.__init__(self, parent)
        self.progressBar = progressBar
        self.cliNode = None
        self._cliNodeObserver = None


#
# PNMLogic
#
class PNMQueue(qt.QObject):
    simChanged = qt.Signal()


class PNMLogic(MicrotomRemoteLogicBase):
    def __init__(self, parent, progressBar):
        super().__init__(parent, None)
        self.folder = None
        self.params = None

        self.extractState = False
        self.kabsOneAngleState = False
        self.kabsMultiAngleState = False
        self.sensibilityState = False
        self.MICPState = False
        self.finished = False
        self.batchExecution = False

        self.logic_models = SubscaleLogicDict

    def set_subres_model(self, table_node, params):
        pore_network = geo2spy(table_node)
        x_size = float(table_node.GetAttribute("x_size"))
        y_size = float(table_node.GetAttribute("y_size"))
        z_size = float(table_node.GetAttribute("z_size"))
        volume = x_size * y_size * z_size

        subres_model = params["subres_model_name"]
        subres_params = params["subres_params"]
        if (subres_model == "Throat Radius Curve" or subres_model == "Pressure Curve") and subres_params:
            subres_params = {
                i: np.asarray(subres_params[i]) if subres_params[i] is not None else None for i in subres_params.keys()
            }

        subresolution_logic = self.logic_models[subres_model]
        subresolution_function = subresolution_logic().get_capillary_pressure_function(
            subres_params, pore_network, volume
        )

        return subresolution_function

    def deleteSubjectHierarchyFolder(self, folderName):
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        folderItemID = shNode.GetItemByName(folderName)
        if folderItemID:
            folderNode = shNode.GetItemDataNode(folderItemID)
            if folderNode:
                slicer.mrmlScene.RemoveNode(folderNode)
            shNode.RemoveItem(folderItemID)
        slicer.app.processEvents()

    def runInBatch(
        self,
        simulator,
        inputNode,
        batchDir,
        segTag,
        roiTag,
        valTag,
        labelTag,
        output_path=None,
        mode="Local",
        outputPrefix="",
        params=None,
    ):
        self.simulator = simulator
        self.params = params
        self.output_path = output_path
        self.outputPrefix = outputPrefix
        self.mode = mode
        self.rootDir = None
        self.progressBar = None
        self.finished = False
        self.cancelled = False
        projectManager = ProjectManager()

        slicer.app.processEvents()
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        allItemIDs = vtk.vtkIdList()
        shNode.GetItemChildren(shNode.GetSceneItemID(), allItemIDs, True)

        batch_images = [Path(batchDir) / file for file in os.listdir(batchDir) if file.endswith(valTag)]
        for filepath in batch_images:
            if filepath and os.path.isfile(filepath):
                data, header = nrrd.read(filepath)
                del data
                if header["type"] == "int":
                    volume_node = slicer.util.loadLabelVolume(filepath)
                else:
                    volume_node = slicer.util.loadVolume(filepath)
            else:
                logging.debug(f"Error at loading {filepath}, file not exists")
                break

            params["well_name"] = Path(filepath).stem

            folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            itemTreeId = folderTree.GetSceneItemID()
            rootDir = folderTree.CreateFolderItem(itemTreeId, f"{params['well_name']} Report")
            folderTree.CreateItem(rootDir, volume_node)
            slicer.app.processEvents()

            self.finished = False

            self.run(
                simulator,
                inputNode,
                volume_node,
                labels=None,
                roiNode=None,
                output_path=output_path,
                mode=mode,
                outputPrefix=params["well_name"],
                params=params,
                isBatch=True,
            )

            while self.finished is False:
                time.sleep(0.2)
                slicer.app.processEvents()

            if self.cancelled is True:
                break

            self.deleteSubjectHierarchyFolder(f"{params['well_name']} Report")

        self.processFinished.emit()
        slicer.app.processEvents()

    def run(
        self,
        simulator,
        segmentationNode,
        referenceNode,
        labels,
        roiNode=None,
        output_path=None,
        mode="Local",
        outputPrefix="",
        params=None,
        isBatch=False,
    ):
        if referenceNode is None:
            return

        self.referenceNode = referenceNode
        self.params = params
        self.outputPrefix = outputPrefix
        self.json_entry_node_ids = {}
        self.pnm_report = {
            "well": None,
            "porosity": None,
            "permeability": None,
            "residual_So": None,
            "realistic_production": None,
        }
        if self.progressBar is None:
            self.progressBar = ProgressBarProc()
        self.cancelled = False

        self.pnm_report["well"] = params["well_name"]

        self.json_entry_node_ids["volume"] = referenceNode.GetID()
        if referenceNode.GetClassName() == "vtkMRMLLabelMapVolumeNode":
            self.pnm_report["porosity"] = (slicer.util.arrayFromVolume(referenceNode) > 0).mean()
        else:
            self.pnm_report["porosity"] = slicer.util.arrayFromVolume(referenceNode).mean()

        local_progress_bar = LocalProgressBar()
        self.extractor_logic = PoreNetworkExtractorLogic(local_progress_bar)
        self.one_phase_logic = OnePhaseSimulationLogic(local_progress_bar)
        self.two_phase_logic = TwoPhaseSimulationLogic(local_progress_bar)
        self.micp_logic = MercurySimulationLogic(local_progress_bar)

        # Set subresolution model
        if "subscale_model_params" in params:
            self.subresolution_function = lambda node: self.set_subres_model(node, params["subscale_model_params"])
            self.subres_model_name = params["subscale_model_params"]["subres_model_name"]
            self.subres_params = params["subscale_model_params"]["subres_params"]
        else:
            kabs_params = OnePhaseSimulationWidget().getParams()
            self.subresolution_function = kabs_params["subresolution function call"]
            self.subres_model_name = kabs_params["subres_model_name"]
            self.subres_params = kabs_params["subres_params"]

        # Queue with simulations
        self.sim_index = 0
        self.sim_queue = {
            "extraction": self.run_extract,
            "one-phase sim w/ one angle": self.run_1phase_one_angle,
            "one-phase sim w/ multi angle": self.run_1phase_multi_angle,
            "MICP sim": self.run_micp,
        }
        if params.get("sensibility_parameters_node") is not None:
            self.sim_queue.update({"sensibility test simulations": self.run_sensibility})

        self.batchExecution = isBatch

        self.controlSims = PNMQueue()
        self.controlSims.simChanged.connect(self.run_next_simulation)
        self.controlSims.simChanged.emit()

    def cancel(self):
        if self.progressBar:
            self.progressBar.nextStep(99, f"Stopping simulation on {self.referenceNode.GetName()}")
        self.extractor_logic.cancel()
        self.one_phase_logic.cancel()
        self.two_phase_logic.cancel()
        self.micp_logic.cancel()

        self.cancelled = True
        self.finished = True
        if self.progressBar:
            self.progressBar.nextStep(100, "Cancelled")
            self.progressBar.__exit__(None, None, None)
            self.progressBar = None

    def run_next_simulation(self):
        if self.cancelled:
            return

        sim_keys = list(self.sim_queue.keys())
        sim_list = list(self.sim_queue.values())

        progressStep = self.sim_index * 100.0 / len(self.sim_queue)
        self.progressBar.nextStep(progressStep, f"Running {sim_keys[self.sim_index]} on {self.referenceNode.GetName()}")

        sim_list[self.sim_index]()
        self.sim_index += 1

    def run_extract(self):
        self.extractor_logic.extract(
            self.referenceNode,
            None,
            self.outputPrefix,
            "PoreSpy",
            self.extract_callback(self.extractor_logic),
        )

    def extract_callback(self, logic):
        def onFinishExtract(state):
            if state:
                if logic.results:
                    self.pore_table = logic.results["pore_table"]
                    self.throat_table = logic.results["throat_table"]
                else:
                    logging.debug("No connected network was identified. Possible cause: unsegmented pore space.")
                    return

                self.json_entry_node_ids["pore_table"] = self.pore_table.GetID()
                self.json_entry_node_ids["throat_table"] = self.throat_table.GetID()

                model_nodes = logic.results["model_nodes"]
                for i, node in enumerate(model_nodes["pores_nodes"]):
                    self.json_entry_node_ids[f"pore_polydata_{i}"] = node.GetID()
                for i, node in enumerate(model_nodes["throats_nodes"]):
                    self.json_entry_node_ids[f"throat_polydata_{i}"] = node.GetID()

                folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()
                itemTreeId = folderTree.GetItemByDataNode(self.pore_table)
                parentItemId = folderTree.GetItemParent(itemTreeId)
                folderTree.SetItemExpanded(parentItemId, False)

                self.extractState = True

                slicer.app.processEvents()
                self.checkFinish()

        return onFinishExtract

    # Kabs One-angle
    def run_1phase_one_angle(self):
        kabs_params = OnePhaseSimulationWidget().getParams()
        kabs_params["keep_temporary"] = True
        kabs_params["subresolution function call"] = self.subresolution_function
        kabs_params["subresolution function"] = kabs_params["subresolution function call"](self.pore_table)
        kabs_params["subres_model_name"] = self.subres_model_name
        kabs_params["subres_params"] = self.subres_params
        try:
            self.one_phase_logic.run_1phase(
                self.pore_table,
                kabs_params,
                prefix=self.outputPrefix,
                callback=self.kabs_oneangle_callback(self.one_phase_logic),
            )
        except Exception as error:
            logging.error("Error occured in one-phase one-angle simulation.")
            import traceback

            traceback.print_exc()

    def kabs_oneangle_callback(self, logic):
        def onFinishKabs(state):
            if state:
                if "flow_rate" in logic.results:
                    flow_rate_node = slicer.util.getNode(logic.results["flow_rate"])
                    self.json_entry_node_ids["flow_rate"] = flow_rate_node.GetID()

                if "permeability" in logic.results:
                    perm_node = slicer.util.getNode(logic.results["permeability"])
                    self.json_entry_node_ids["perm_node"] = perm_node.GetID()

                    perm_df = slicer.util.dataframeFromTable(perm_node)
                    self.pnm_report["permeability"] = np.diag(perm_df).mean()

                self.kabsOneAngleState = True

                slicer.app.processEvents()
                self.checkFinish()

        return onFinishKabs

    # Kabs Multi-angle
    def run_1phase_multi_angle(self):
        kabs_params = OnePhaseSimulationWidget().getParams()
        kabs_params["simulation type"] = "Multiple orientations"
        kabs_params["rotation angles"] = 100
        kabs_params["keep_temporary"] = True
        kabs_params["subresolution function call"] = self.subresolution_function
        kabs_params["subresolution function"] = kabs_params["subresolution function call"](self.pore_table)
        kabs_params["subres_model_name"] = self.subres_model_name
        kabs_params["subres_params"] = self.subres_params
        try:
            self.one_phase_logic.run_1phase(
                self.pore_table,
                kabs_params,
                prefix=self.outputPrefix,
                callback=self.kabs_multiangle_callback(self.one_phase_logic),
            )
        except Exception as e:
            logging.error("Error occured in one-phase multi-angle simulation.")
            import traceback

            traceback.print_exc()

    def kabs_multiangle_callback(self, logic):
        def onFinishKabs(state):
            if state:
                if all(v in logic.results for v in ["model", "arrow", "plane", "sphere"]):
                    model_node = slicer.util.getNode(logic.results["model"])
                    arrow_node = slicer.util.getNode(logic.results["arrow"])
                    plane_node = slicer.util.getNode(logic.results["plane"])
                    sphere_node = slicer.util.getNode(logic.results["sphere"])
                else:
                    return

                self.json_entry_node_ids["multiangle_model"] = model_node.GetID()
                self.json_entry_node_ids["multiangle_arrow_model"] = arrow_node.GetID()
                self.json_entry_node_ids["multiangle_plane_model"] = plane_node.GetID()
                self.json_entry_node_ids["multiangle_sphere_model"] = sphere_node.GetID()

                # measure angles
                plane_node = slicer.util.getNode(logic.results["plane"])
                plane_points = plane_node.GetPolyData().GetPoints()
                plane_v1 = np.array(plane_points.GetPoint(1)) - np.array(plane_points.GetPoint(0))
                plane_v2 = np.array(plane_points.GetPoint(2)) - np.array(plane_points.GetPoint(0))
                plane_normal = np.cross(plane_v2, plane_v1)

                direction = logic.results["direction"]
                angle_with_plane = np.pi / 2.0 - np.arccos(
                    np.dot(direction, plane_normal) / (np.linalg.norm(direction) * np.linalg.norm(plane_normal))
                )

                projection = direction - np.dot(direction, plane_normal) / np.linalg.norm(plane_normal)
                projection_angle_with_z = np.arccos(
                    np.dot(projection, np.array([0, 0, 1])) / np.linalg.norm(projection)
                )

                # measure min, max, mean, desvio padrão dos valores
                permeabilities = logic.results["permeabilities"]
                perm_stats = pd.DataFrame(permeabilities[:, 3]).describe()

                df = pd.DataFrame(
                    {
                        "Angle with plane (º)": angle_with_plane * 180 / np.pi,
                        "Projection angle with z-axis (º)": projection_angle_with_z * 180 / np.pi,
                        "Average Permeability (mD)": 1000 * perm_stats.loc["mean"].tolist()[0],
                        "Standard Deviation Permeability (mD)": 1000 * perm_stats.loc["std"].tolist()[0],
                        "Min. Permeability (mD)": 1000 * perm_stats.loc["min"].tolist()[0],
                        "Max. Permeability (mD)": 1000 * perm_stats.loc["max"].tolist()[0],
                    },
                    index=[0],
                )
                table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
                table.SetName("multiangle_statistics")
                du.dataFrameToTableNode(df, table)
                folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()
                itemTreeId = folderTree.GetItemByDataNode(self.referenceNode)
                parentItemId = folderTree.GetItemParent(itemTreeId)
                folderTree.CreateItem(parentItemId, table)
                self.json_entry_node_ids["multiangle_statistics"] = table.GetID()

                self.kabsMultiAngleState = True

                slicer.app.processEvents()
                self.checkFinish()

        return onFinishKabs

    # Sensibilidade
    def run_sensibility(self):
        twoPhaseWidget = TwoPhaseSimulationWidget()
        twoPhaseWidget.parameterInputWidget.setCurrentNode(self.params["sensibility_parameters_node"])
        twoPhaseWidget.onParameterInputLoad()
        krel_params = twoPhaseWidget.getParams()
        krel_params["subresolution function call"] = self.subresolution_function
        krel_params["subresolution function"] = krel_params["subresolution function call"](self.pore_table)
        krel_params["subres_model_name"] = self.subres_model_name
        krel_params["subres_params"] = self.subres_params
        try:
            self.two_phase_logic.run_2phase(
                self.pore_table,
                krel_params,
                prefix=self.outputPrefix,
                callback=self.sensibility_callback(self.two_phase_logic),
            )
        except Exception as e:
            logging.debug("Error occured in two-phase sensibility simulation.")
            import traceback

            traceback.print_exc()

    def sensibility_callback(self, logic):
        def onFinishKrel(state):
            if state:
                try:
                    krelResultsTableNode = slicer.util.getNode(logic.krelResultsTableNodeId)
                    krelResultsTableNode.SetName("Sensibility")
                    self.json_entry_node_ids["sensibility"] = krelResultsTableNode.GetID()

                    krel_df = slicer.util.dataframeFromTable(krelResultsTableNode)
                    swr = krel_df["result-swr"]
                    self.pnm_report["residual_So"] = np.median(1 - swr)

                    for i in range(3):
                        krelCycleTableNode = slicer.util.getNode(logic.krelCycleTableNodesId[i])
                        krelCycleTableNode.SetName(f"Sensibility cycle {i}")
                        self.json_entry_node_ids[f"sensibility_cycle{i}"] = krelCycleTableNode.GetID()

                    # Production
                    pnm_production_logic = PoreNetworkProductionLogic()
                    water_viscosity = 0.001
                    oil_viscosity = 0.01
                    krel_smoothing = 2.0
                    simulation = 0
                    sensibility = True
                    production_table = pnm_production_logic.run(
                        krelResultsTableNode,
                        water_viscosity,
                        oil_viscosity,
                        krel_smoothing,
                        sensibility,
                        simulation,
                    )
                    self.json_entry_node_ids["production"] = production_table.GetID()

                    npd_points_vtk_array = production_table.GetTable().GetColumnByName("realistic_NpD")
                    npd_points = vtk.util.numpy_support.vtk_to_numpy(npd_points_vtk_array)
                    self.pnm_report["realistic_production"] = np.median(npd_points)

                    self.sensibilityState = True
                except Exception as e:
                    self.json_entry_node_ids["sensibility"] = None
                    self.json_entry_node_ids["production"] = None
                    for i in range(3):
                        self.json_entry_node_ids[f"sensibility_cycle{i}"] = None

                    self.pnm_report["residual_So"] = None
                    self.pnm_report["realistic_production"] = None

                    logging.error("Error on sensibility callback.")
                    import traceback

                    traceback.print_exc()

                slicer.app.processEvents()
                self.checkFinish()

        return onFinishKrel

    # MICP
    def run_micp(self):
        micp_params = MercurySimulationWidget().getParams()
        micp_params["subresolution function call"] = self.subresolution_function
        micp_params["subresolution function"] = micp_params["subresolution function call"](self.pore_table)
        micp_params["subres_model_name"] = self.subres_model_name
        micp_params["subres_params"] = self.subres_params
        try:
            self.micp_logic.run_mercury(
                self.pore_table,
                micp_params,
                prefix=self.outputPrefix,
                callback=self.micp_callback(self.micp_logic),
            )
        except Exception as e:
            logging.error("Error occured in micp simulation.")
            import traceback

            traceback.print_exc()

    def micp_callback(self, logic):
        def onFinishMICP(state):
            if state:
                micp_results_node_id = logic.results_node_id
                if micp_results_node_id:
                    micp_results = slicer.util.getNode(micp_results_node_id)
                    self.json_entry_node_ids["micp"] = micp_results.GetID()

                self.MICPState = True

                slicer.app.processEvents()
                self.checkFinish()

        return onFinishMICP

    # Check for finish or send another simulation in queue
    def checkFinish(self):
        if self.sim_index < len(self.sim_queue):
            self.controlSims.simChanged.emit()
        else:
            if not self.referenceNode:
                return

            self.progressBar.nextStep(99, f"Saving report")

            folder = Path(slicer.app.slicerHome) / "LTrace" / "stprojects"
            folder.mkdir(parents=True, exist_ok=True)

            projects_path = folder / "projects.json"
            pnm_report_path = folder / "folder_report.csv"

            pnm_report_df = pd.DataFrame(self.pnm_report, index=[0])

            if pnm_report_path.exists():
                existing_df = pd.read_csv(pnm_report_path, index_col=0)
                updated_df = pd.concat([existing_df, pnm_report_df], ignore_index=True)
            else:
                updated_df = pnm_report_df

            updated_df.index.name = "index"
            updated_df.to_csv(pnm_report_path, index=True, mode="w")

            if not projects_path.exists():
                with open(projects_path, "w") as f:
                    f.write("")

            with open(projects_path, "r") as f:
                projects_dict = json.load(f) if projects_path.stat().st_size != 0 else {}

            if (folder / self.outputPrefix).exists():
                shutil.rmtree(folder / self.outputPrefix)

            os.mkdir(folder / self.outputPrefix)

            self.json_entry = {}
            for key, node_id in self.json_entry_node_ids.items():
                node = slicer.mrmlScene.GetNodeByID(node_id) if node_id else None
                if node is None:
                    continue

                if isinstance(node, slicer.vtkMRMLScalarVolumeNode) or isinstance(
                    node, slicer.vtkMRMLLabelMapVolumeNode
                ):
                    name = f"{folder}/{self.outputPrefix}/{key}.nrrd"
                elif isinstance(node, slicer.vtkMRMLTableNode):
                    name = f"{folder}/{self.outputPrefix}/{key}.tsv"
                elif isinstance(node, slicer.vtkMRMLModelNode):
                    name = f"{folder}/{self.outputPrefix}/{key}.vtk"

                slicer.util.saveNode(node, name)

                self.json_entry[key] = os.path.basename(name) if node else None

            projects_dict[self.outputPrefix] = self.json_entry

            with open(projects_path, "w") as f:
                json.dump(projects_dict, f)

            self.finished = True

            self.progressBar.nextStep(100, "Completed")
            self.progressBar.__exit__(None, None, None)
            self.progressBar = None

            if not self.batchExecution:
                self.processFinished.emit()

            slicer.app.processEvents()


#
# MicrotomRemoteLogic
#


class MicrotomRemoteLogic(MicrotomRemoteLogicBase):
    def loadDataset(self, ds, key, name, refNode=None):
        ds_ref = ds[key]
        volumeArray = ds_ref.data
        volumeSpacing = ds.attrs["resolution"]

        volumeNode = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLScalarVolumeNode.__name__, name)
        volumeNode.CreateDefaultDisplayNodes()

        if refNode:
            volumeNode.CopyOrientation(refNode)
        # Write selected xarray.Dataset content to GeoSlicer Node
        slicer.util.updateVolumeFromArray(volumeNode, volumeArray)
        volumeNode.SetSpacing(volumeSpacing, volumeSpacing, volumeSpacing)

        return volumeNode

    @classmethod
    def renderVolume(cls, volumeNode):
        volumeRenderingLogic = slicer.modules.volumerendering.logic()
        displayNode = volumeRenderingLogic.CreateDefaultVolumeRenderingNodes(volumeNode)
        displayNode.SetVisibility(True)

    @classmethod
    def setWindowLevel(cls, volumeNode):
        slicer.util.setSliceViewerLayers(background=volumeNode)
        slicer.util.resetSliceViews()

        displayNode = volumeNode.GetDisplayNode()
        displayNode.SetVisibility(True)

        if displayNode.IsA("vtkMRMLLabelMapVolumeDisplayNode"):
            return

        displayNode.AutoWindowLevelOff()

        widget = slicer.vtkMRMLWindowLevelWidget()
        widget.SetSliceNode(slicer.util.getNode("vtkMRMLSliceNodeGreen"))
        widget.SetMRMLApplicationLogic(slicer.app.applicationLogic())
        widget.UpdateWindowLevelFromRectangle(0, [0, 0], [10**6, 10**6])
        window = displayNode.GetWindow()
        level = displayNode.GetLevel()

        displayNode.SetWindowLevel(window, level)

    @staticmethod
    def writeTable(columns, columns_names, title=None):
        tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", f"Table_{title}")
        table = tableNode.GetTable()

        for name in columns_names:
            arr = vtk.vtkFloatArray()
            arr.SetName(name)
            table.AddColumn(arr)

        numPoints = max([len(d) for d in columns])
        table.SetNumberOfRows(numPoints)

        for i in range(numPoints):
            for c in range(len(columns_names)):
                v = float(columns[c][i]) if len(columns[c]) > i else 0.0
                table.SetValue(i, c, v)

        return tableNode

    def getNodeFromEnv(self, name, workspace):
        nodes = slicer.util.getNodes(name, useLists=True)
        for n in nodes.get(name, []):
            if n.GetAttribute(NodeEnvironment.name()) == str(workspace):
                return n
        return None

    def addNodesToScene(self, nodes):
        colormapNodeID = slicer.util.getNode("Viridis").GetID()

        for node in nodes:
            try:
                if node.IsA("vtkMRMLTableNode"):
                    helpers.makeTemporaryNodePermanent(node, show=True)
                    helpers.autoDetectColumnType(node)
                else:
                    node.GetDisplayNode().SetAndObserveColorNodeID(colormapNodeID)
                    node.GetDisplayNode().ScalarVisibilityOn()
                    helpers.makeTemporaryNodePermanent(node, show=True)
                    node.GetDisplayNode().SetVisibility(True)

            except Exception as e:
                slicer.util.errorDisplay(f"Failed to load the results.")
                logging.error(f"ERROR :: Cause: {repr(e)}")

    def setNodesHierarchy(self, nodes, referenceNode, projectDirName=None):
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        parentItemId = folderTree.GetSceneItemID()
        if referenceNode:
            itemTreeId = folderTree.GetItemByDataNode(referenceNode)
            parentItemId = folderTree.GetItemParent(itemTreeId)

        dirLabel = "Microtom Results"
        foundResultDir = folderTree.GetItemByName(dirLabel)
        if not foundResultDir:
            foundResultDir = folderTree.CreateFolderItem(parentItemId, dirLabel)

        if projectDirName:  # override foundResultDir
            foundResultDir = folderTree.CreateFolderItem(foundResultDir, projectDirName)

        for node in nodes:
            folderTree.CreateItem(foundResultDir, node)

    def showMissingResults(self, missingResults):
        if not missingResults:
            return
        missing = "\n".join([f" - {ifile} ({errmsg})" for ifile, errmsg in missingResults])
        slicer.util.infoDisplay(f"Failed to load the following results:\n{missing}")

    def _writeOutputs(self, jsonDict, nth_run):
        simulator = jsonDict["simulator"]
        workspace = jsonDict["workspace"]

        if "error" in jsonDict:
            slicer.util.errorDisplay(jsonDict["error"])
            return

        if "warning" in jsonDict:
            # Show warnings as info to avoid causing users to panic
            slicer.util.infoDisplay(jsonDict["warning"])

        file = nth_run["nodename"]

        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        referenceNode = helpers.tryGetNode(nth_run["inputNodeID"])
        itemTreeId = folderTree.GetItemByDataNode(referenceNode)
        parentItemId = folderTree.GetItemParent(itemTreeId)

        foundResultDir = folderTree.GetItemByName("Microtom Results")
        if not foundResultDir:
            foundResultDir = folderTree.CreateFolderItem(parentItemId, "Microtom Results")

        if simulator in ["stokes_kabs", "darcy_kabs_foam"]:
            nodesToCreate = ["Pressure", "Velocity"]
            if simulator == "stokes_kabs":
                nodesToCreate.append("BIN")
            for nodesuffix in nodesToCreate:
                try:
                    volumeNode = self.getNodeFromEnv(f"SIMULATOR_OUTPUT_TMP_NODE_{nodesuffix}", workspace)
                    volumeNode.GetDisplayNode().SetAndObserveColorNodeID(slicer.util.getNode("Viridis").GetID())
                    volumeNode.GetDisplayNode().ScalarVisibilityOn()
                    helpers.makeTemporaryNodePermanent(volumeNode, show=True)
                    volumeNodeName = slicer.mrmlScene.GenerateUniqueName(f"{file}_{simulator.upper()}_{nodesuffix}")
                    volumeNode.SetName(volumeNodeName)
                    volumeNode.GetDisplayNode().SetVisibility(True)

                    folderTree.CreateItem(foundResultDir, volumeNode)

                except Exception as e:
                    slicer.util.errorDisplay(f"Failed to adjust output display. Cause: {repr(e)}")
        elif simulator not in ["krel", "stokes_kabs_rev"]:
            try:
                volumeNode = self.getNodeFromEnv("SIMULATOR_OUTPUT_TMP_NODE", workspace)
                volumeNode.GetDisplayNode().SetAndObserveColorNodeID(slicer.util.getNode("Viridis").GetID())
                volumeNode.GetDisplayNode().ScalarVisibilityOn()
                helpers.makeTemporaryNodePermanent(volumeNode, show=True)
                volumeNodeName = slicer.mrmlScene.GenerateUniqueName(f"{file}_{simulator.upper()}_Output")
                volumeNode.SetName(volumeNodeName)

                folderTree.CreateItem(foundResultDir, volumeNode)

            except Exception as e:
                slicer.util.errorDisplay(f"Failed to adjust output display. Cause: {repr(e)}")

        if simulator != "krel":
            try:
                tableNode = self.getNodeFromEnv("SIMULATOR_OUTPUT_TMP_TABLE", workspace)
                helpers.makeTemporaryNodePermanent(tableNode, show=True)
                tableNodeName = slicer.mrmlScene.GenerateUniqueName(f"{file}_{simulator.upper()}_Variables")
                tableNode.SetName(tableNodeName)
                helpers.autoDetectColumnType(tableNode)
                folderTree.CreateItem(foundResultDir, tableNode)
            except Exception as e:
                slicer.util.errorDisplay(f"Failed to load output table. Cause: {repr(e)}")

    def findSequenceAndAddNode(self, name, nodes, sequenceIndex):
        browserNode = helpers.tryGetNode(name.replace("_Proxy", "_Browser"))
        if not browserNode:
            browserNode = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLSequenceBrowserNode", name.replace("_Proxy", "_Browser")
            )
            browserNode.SetIndexDisplayFormat("%.0f")

            sequenceOutputNode = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLSequenceNode", name.replace("_Proxy", "_Sequence")
            )
            sequenceVariablesNode = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLSequenceNode",
                name.replace("_Output_", "_Variables_").replace("_Proxy", "_Sequence"),
            )
            sequenceRunTimeNode = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLSequenceNode",
                name.replace("_Output_", "_Runtime_Log_").replace("_Proxy", "_Sequence"),
            )

        else:
            sequenceOutputNode = helpers.tryGetNode(name.replace("_Proxy", "_Sequence"))
            sequenceVariablesNode = helpers.tryGetNode(
                name.replace("_Output_", "_Variables_").replace("_Proxy", "_Sequence")
            )
            sequenceRunTimeNode = helpers.tryGetNode(
                name.replace("_Output_", "_Runtime_Log_").replace("_Proxy", "_Sequence")
            )

        for node in nodes:
            isRunTimeNode = node.GetName().endswith("_Runtime_Log")
            if node.IsA("vtkMRMLTableNode"):
                helpers.autoDetectColumnType(node)
                if isRunTimeNode:
                    if sequenceIndex > 0:
                        helpers.makeNodeTemporary(node, hide=True)
                    self.addNodeToSequence(node, sequenceRunTimeNode, browserNode, sequenceIndex, name, "RunTime_Log")
                else:
                    self.addNodeToSequence(node, sequenceVariablesNode, browserNode, sequenceIndex, name, "Data")
            else:
                self.addNodeToSequence(node, sequenceOutputNode, browserNode, sequenceIndex, name)

    def addNodeToSequence(self, node, sequenceNode, browserNode, index, name, outputType=""):
        if index > 0:
            node.SetName(f"Realization_{index}")
        elif outputType:
            node.SetName(name.replace("_Output_Proxy", f"_{outputType}_Proxy"))
        else:
            node.SetName(name)
        sequenceNode.SetDataNodeAtValue(node, str(index))
        if index == 0:
            sequenceNode.SetIndexUnit("")
            sequenceNode.SetIndexName("Realization")
            browserNode.AddProxyNode(node, sequenceNode, False)
            browserNode.SetAndObserveMasterSequenceNodeID(sequenceNode.GetID())

    def loadCustomLog(self, path: Path):
        """
        Load a custom log file and return a pandas table with the parsed content.

        Log format:
        - Each line is a record (e.g. "Radius: 0.1, Snw: 0.5")
        - Each column is separated by a comma
        - No header
        - Arbitrary number of columns
        """

        import re
        import pandas as pd

        pat = re.compile(r"(?P<name>\w+): (?P<value>\d+(\.\d+)?)")

        try:
            with open(path, "r") as f:
                lines = f.readlines()

            data = defaultdict(list)
            for line in lines:
                cols = line.strip().split(",")
                for c in cols:
                    m = pat.search(c.strip())
                    if m:
                        block = m.groupdict()
                        data[block["name"]].append(float(block["value"]))
            return pd.DataFrame(data)

        except Exception as e:
            import traceback

            traceback.print_exc()
            print(repr(e))
            return None

    def onPorosimetryCLIModified(self, sim_info, cliNode, event):
        sequenceIndex = -1

        if cliNode is None:
            self.cliNode = None
            return

        if cliNode.GetStatusString() == "Completed":
            """On CLI, results was write as Nodes and some arrays are passed by stream
            as a JSON payload. So, here we need to get this payload based on the same key
            used on CLI (for this example is 'porosimetry') and extract those arrays.
            """

            simulator = sim_info["simulator"].upper()

            referenceNodeID = sim_info["inputNodeID"]
            referenceNode = helpers.tryGetNode(referenceNodeID)

            results = sim_info["results"]
            prefix = sim_info["nodename"]
            sequenceIndex = sim_info["sequenceIndex"]

            nodes = []

            for name, dtype in results:
                node = helpers.tryGetNode(name)
                name_template = "_".join([v for v in (prefix, simulator, dtype) if v])
                nodeName = slicer.mrmlScene.GenerateUniqueName(name_template)
                node.SetName(nodeName)
                nodes.append(node)

            try:
                output_file_dir = Path(slicer.app.temporaryPath).absolute() / f"{sim_info['simulator']}.csv"
                df = self.loadCustomLog(Path(output_file_dir))
                output_file_dir.unlink()

                if df is not None:
                    tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
                    tableNode.SetName(f"{prefix}_{simulator}_Runtime_Log")
                    du.dataFrameToTableNode(df, tableNode)
                    nodes.append(tableNode)

            except Exception as e:
                logging.error(f"Failed to load runtime log. Path: {output_file_dir.as_posix()}. Cause: {repr(e)}.")

            if sequenceIndex < 1:
                self.addNodesToScene(nodes)
                self.setNodesHierarchy(nodes, referenceNode, projectDirName=f"{prefix}_{simulator}")

            if sequenceIndex > -1:
                self.findSequenceAndAddNode(prefix, nodes, sequenceIndex)

        if not cliNode.IsBusy():
            logging.info("ExecCmd CLI %s" % cliNode.GetStatusString())

            del self.cliNode
            self.cliNode = None
            self.processFinished.emit()

            if sequenceIndex < 1:
                try:
                    helpers.removeTemporaryNodes(environment=Tag(sim_info["workspace"]))
                except Exception as e:
                    pass

    def runLocal(
        self, simulator, inputNode, name=None, tag=None, output_path: str = None, params=None, sequenceIndex: int = None
    ):
        workspace_dir = tag.value or str(uuid.uuid4())

        if name is None:
            name = inputNode.GetName()

        if output_path is None:
            output_path = str(Path(slicer.app.temporaryPath).absolute() / workspace_dir)

        outputNodeName = "SIMULATOR_OUTPUT_TMP_NODE"
        outputNode = helpers.createTemporaryVolumeNode(
            slicer.vtkMRMLScalarVolumeNode, outputNodeName, environment=tag, hidden=True, uniqueName=False
        )

        outputTableName = "SIMULATOR_OUTPUT_TMP_TABLE"
        outputTable = helpers.createTemporaryNode(
            slicer.vtkMRMLTableNode, outputTableName, environment=tag, hidden=True, uniqueName=False
        )

        dirOutput = str(Path(slicer.app.temporaryPath).absolute() / rf"{simulator}.csv")
        params["output_file_path"] = dirOutput

        sim_info = {
            "simulator": simulator,
            "n_threads": 1,
            "workspace": workspace_dir,
            "nodename": name,
            "cli": None,
            "job_id": "Local",
            "inputNodeID": inputNode.GetID(),
            "results": [(outputNode.GetID(), ""), (outputTable.GetID(), "Data")],
            "sequenceIndex": sequenceIndex if sequenceIndex is not None else -1,
        }

        # Configure your CLI task
        cliParams = {
            "inputVolume": inputNode.GetID(),
            "outputVolume": outputNode.GetID(),
            "outputAxis": outputTable.GetID(),
            "nthreads": 1,
            "outputDir": output_path,
            "simulator": simulator,
            "workspace": workspace_dir,
            "params": json.dumps(params) if params is not None else None,
        }

        # Run CLI Asynchronous
        """
        Here we show how to run a CLI without blocking the UI, by passing wait_for_completion=False.
        You can catch the cliNode and handle events, like messages, progress, errors and flow controls
        like Cancel.
        """
        self.cliNode = slicer.cli.run(slicer.modules.porosimetrycli, None, cliParams, wait_for_completion=False)
        self.cliNode.AddObserver("ModifiedEvent", partial(self.onPorosimetryCLIModified, sim_info))
        # Setup progress bar
        self.progressBar.setCommandLineModuleNode(self.cliNode)

    def run(
        self,
        simulator,
        segmentationNode,
        referenceNode,
        labels,
        roiNode=None,
        output_path=None,
        mode="Local",
        outputPrefix="",
        params=None,
    ):
        tag = Tag(str(uuid.uuid4()))

        try:
            if segmentationNode is None:
                if roiNode:
                    inputNodeName = "TMP_REFNODE"
                    inputVolumeNode = helpers.createTemporaryVolumeNode(
                        referenceNode.__class__, inputNodeName, environment=tag, uniqueName=False, content=referenceNode
                    )
                    inputVolumeNode = helpers.maskInputWithROI(inputVolumeNode, roiNode, mask=False)
                else:
                    inputVolumeNode = referenceNode

                nodeName = referenceNode.GetName()

            else:
                if not labels:
                    slicer.util.errorDisplay(
                        "Please, select at least one segment by checking the segment box on the segment list. "
                        "The selected segment will be considered as the pore space."
                    )
                    return

                nodeName = segmentationNode.GetName()
                inputVolumeNode, _ = helpers.createLabelmapInput(
                    segmentationNode=segmentationNode,
                    name=nodeName,
                    segments=labels,
                    tag=tag,
                    referenceNode=referenceNode,
                    soiNode=roiNode,
                )

                helpers.mergeSegments(inputVolumeNode)

            if not outputPrefix:
                outputPrefix = nodeName

            if mode == "Remote":
                uid = self.dispatch(simulator, inputVolumeNode, outputPrefix, tag, referenceNode, params)
            else:
                browser_node = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(segmentationNode)
                if browser_node and simulator == "psd":
                    sequence_node = browser_node.GetSequenceNode(segmentationNode)
                    self.sequencePreRun(simulator, sequence_node, labels, outputPrefix, tag, output_path, params)
                else:
                    self.runLocal(simulator, inputVolumeNode, outputPrefix, tag, output_path, params)
                uid = simulator

            return uid
        except Exception as e:
            import traceback

            traceback.print_exc()
            helpers.removeTemporaryNodes(environment=tag)
            slicer.util.errorDisplay("Sorry, something went wrong...check out the logs")

    def sequencePreRun(self, simulator, sequenceNode, labels, outputPrefix, tag, output_path, params):
        sequenceName = slicer.mrmlScene.GenerateUniqueName(f"{outputPrefix}_{simulator.upper()}_Output_Proxy")

        for image in range(sequenceNode.GetNumberOfDataNodes() - 1, -1, -1):
            inputVolumeNode = helpers.createTemporaryVolumeNode(
                slicer.vtkMRMLLabelMapVolumeNode,
                f"{outputPrefix}_MOCK_INPUT_{image}",
                environment=tag,
                content=sequenceNode.GetNthDataNode(image),
            )

            helpers.mergeSegments(inputVolumeNode, labels)
            self.runLocal(simulator, inputVolumeNode, sequenceName, tag, output_path, params, sequenceIndex=image)

    def dispatch(self, simulator, labelmapVolumeNode, outputPrefix, tag: Tag = None, referenceNode=None, params=None):
        shared_path = Path(
            r"geoslicer/remote/jobs"
        )  # Note: do not put a slash at the start of the path, unless it is the absolute path

        direction = params.get("direction", "z").upper()
        # collector = SimpleCollector(simulator, outputPrefix, referenceNode.GetID(), direction, tag, params) # TODO mover para dentro do OneResultSlurmHandler

        opening_cmd = ""  #'bash -c "source /etc/bashrc" && source /nethome/drp/microtom/init.sh'

        if simulator == "krel":
            diameters = params.get("diameters", "")[1:-1].split(",")
            collector = KrelCompiler()

            managed_cmd = OneResultSlurmHandler(
                simulator,
                collector,
                labelmapVolumeNode,
                shared_path,
                opening_cmd,
                "cpu",
                params,
                outputPrefix,
                referenceNode.GetID(),
                tag,
                post_args=dict(diameters=diameters),
            )

        elif "kabs" in simulator:
            if_not_kabs_rev = not (simulator == "stokes_kabs_rev")
            collector = StokesKabsCompiler()

            managed_cmd = OneResultSlurmHandler(
                simulator,
                collector,
                labelmapVolumeNode,
                shared_path,
                opening_cmd,
                "cpu",
                params,
                outputPrefix,
                referenceNode.GetID(),
                tag,
                post_args=dict(load_volumes=if_not_kabs_rev),
            )

            managed_cmd.is_strict = if_not_kabs_rev

        else:
            vfrac = params.pop("vfrac", None)
            collector = PorosimetryCompiler()

            managed_cmd = OneResultSlurmHandler(
                simulator,
                collector,
                labelmapVolumeNode,
                shared_path,
                opening_cmd,
                "cpu",
                params,
                outputPrefix,
                referenceNode.GetID(),
                tag,
                post_args=dict(vfrac=vfrac),
            )

        job_name = f"{simulator}: {outputPrefix} ({direction})"

        return slicer.modules.RemoteServiceInstance.cli.run(managed_cmd, name=job_name, job_type="microtom")


from ltrace.remote.connections import JobExecutor
from ltrace.remote.jobs import JobManager


def microtom_job_compiler(job: JobExecutor):
    details = job.details
    simulator = details.get("simulator", "psd")
    outputPrefix = details.get("output_prefix", "output")
    direction = details.get("direction", "z")
    tag = details.get("geoslicer_tag", "")
    referenceNodeId = details.get("reference_volume_node_id", None)

    try:
        if referenceNodeId:
            node = slicer.util.getNode(referenceNodeId)
            if node is None:
                raise ValueError("Reference node not found")
    except Exception:
        referenceNodeId = None

    shared_path = Path(r"geoslicer/remote/jobs")

    # TODO make this conditions shared with dispatch code
    if simulator == "krel":
        collector = KrelCompiler()
        task_handler = OneResultSlurmHandler(
            simulator,
            collector,
            None,
            shared_path,
            "",
            "cpu",
            {"direction": direction},
            outputPrefix,
            referenceNodeId,
            tag,
            post_args=dict(diameters=details.get("diameters", None), direction=direction),
        )

    elif "kabs" in simulator:
        collector = StokesKabsCompiler()
        task_handler = OneResultSlurmHandler(
            simulator,
            collector,
            None,
            shared_path,
            "",
            "cpu",
            {"direction": direction},
            outputPrefix,
            referenceNodeId,
            tag,
            post_args=dict(load_volumes=details.get("load_volumes", None), direction=direction),
        )

    else:
        collector = PorosimetryCompiler()

        task_handler = OneResultSlurmHandler(
            simulator,
            collector,
            None,
            shared_path,
            "",
            "cpu",
            {"direction": direction},
            outputPrefix,
            referenceNodeId,
            tag,
            post_args=dict(vfrac=details.get("vfrac", None), direction=direction),
        )
    task_handler.jobid = str(job.details["job_id"][0])
    task_handler.jobs = [str(j) for j in job.details["job_id"]]
    job.task_handler = task_handler

    return job


JobManager.register("microtom", microtom_job_compiler)
