import importlib
import json
import logging
import os
import re
import uuid
from collections import defaultdict

import numpy as np

from pathlib import Path
from functools import partial

import qt
import slicer
import ctk
import vtk

from ltrace.constants import MAX_LOOP_ITERATIONS
from ltrace.slicer import ui, helpers, widgets, data_utils as du
from ltrace.slicer.node_attributes import Tag, NodeEnvironment
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer_utils import *

from RemoteTasks.OneResultSlurm import OneResultSlurmHandler
from ltrace.readers.microtom import KrelCompiler, PorosimetryCompiler, StokesKabsCompiler
from ltrace.slicer_utils import print_stack

try:
    from Test.MicrotomRemoteTest import MicrotomRemoteTest
except:
    pass


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
        return super().params() | {"verbose": True}


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

    def setup(self):
        LTracePluginWidget.setup(self)

        importlib.reload(widgets)

        self.MODES = [widgets.SingleShotInputWidget]

        self.loadedFiles = {}

        self.modeSelectors = {}
        self.modeWidgets = {}

        self.logic = MicrotomRemoteLogic(self)

        # Instantiate and connect widgets ...
        self.layout.addWidget(self._setupMethodsSection())
        self.layout.addWidget(self._setupInputsSection())
        self.layout.addWidget(self._setupConfigSection())
        self.layout.addWidget(self._setupOutput())

        def resetAll():
            for i in range(self.configWidget.count):
                self.configWidget.widget(i).reset()

        self.segmentInputWidget.segmentListUpdated.connect(resetAll)

        self.modeSelectors[widgets.SingleShotInputWidget.MODE_NAME].setChecked(True)

        self.simBtn.enabled = False

        # Add vertical spacer
        self.layout.addStretch(1)

    def _setupMethodsSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Methods"
        layout = qt.QVBoxLayout(widget)
        methodsLayout = qt.QFormLayout()

        self.simOptions = qt.QComboBox()
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

        self.simOptions.setToolTip("Select a simulation MicroTom method.")
        self.simOptions.currentIndexChanged.connect(self._onSimulSelected)
        methodsLayout.addRow("Select a Simulation: ", self.simOptions)
        layout.addLayout(methodsLayout)
        return widget

    def _setupInputsSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Inputs"
        layout = qt.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        optionsLayout = qt.QHBoxLayout()
        self.optionsStack = qt.QStackedWidget()

        btn1 = qt.QRadioButton(widgets.SingleShotInputWidget.MODE_NAME)
        self.modeSelectors[widgets.SingleShotInputWidget.MODE_NAME] = btn1
        optionsLayout.addWidget(btn1)
        btn1.toggled.connect(self._onModeClicked)
        panel1 = widgets.SingleShotInputWidget(dimensionsUnits={"px": True, "mm": True})

        panel1.onMainSelected = self._onInputSelected
        panel1.onReferenceSelected = self._onReferenceSelected
        self.modeWidgets[widgets.SingleShotInputWidget.MODE_NAME] = panel1
        self.optionsStack.addWidget(self.modeWidgets[widgets.SingleShotInputWidget.MODE_NAME])

        # This will be hidden when the method input is a scalar with a SOI
        # currently only for darcy
        self.hideWhenInputIsScalar = [
            panel1.segmentationLabel,
            panel1.mainInput,
            panel1.segmentsContainerWidget,
        ]

        btn1.hide()

        # btn2 = qt.QRadioButton(widgets.BatchInputWidget.MODE_NAME)
        # self.modeSelectors[widgets.BatchInputWidget.MODE_NAME] = btn2
        # optionsLayout.addWidget(btn2)
        # btn2.toggled.connect(self._onModeClicked)
        # panel2 = widgets.BatchInputWidget()
        # panel2.onDirSelected = self._onInputSelected
        # self.modeWidgets[widgets.BatchInputWidget.MODE_NAME] = panel2
        # self.optionsStack.addWidget(self.modeWidgets[widgets.BatchInputWidget.MODE_NAME])

        layout.addLayout(optionsLayout)
        layout.addWidget(self.optionsStack)
        self.segmentInputWidget = panel1

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

        self.simBtn = qt.QPushButton("Apply")
        self.simBtn.setStyleSheet("QPushButton {font-size: 11px; font-weight: bold; padding: 8px; margin: 4px}")
        self.simBtn.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Preferred)
        self.simBtn.objectName = "Apply PushButton"

        self.simBtn.clicked.connect(self.onExecuteClicked)

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
        ioPageLayout.addWidget(self.simBtn)

        ioPageLayout.addLayout(self.ioResultsComboBox)

        ioPageLayout.addWidget(self.progressBar)

        ioPageLayout.addStretch(1)

        return ioSection

    def showThreads(self):
        dialogWidget = qt.QDialog(slicer.util.mainWindow())
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
        modeWidget: widgets.SingleShotInputWidget = self.modeWidgets[self.currentMode]
        if "darcy_kabs_foam" in self.simOptions.currentData:
            for widget in self.hideWhenInputIsScalar:
                widget.visible = False
            modeWidget.mainInput.setCurrentNode(None)
            modeWidget.mainInput.visible = False
            modeWidget.soiInput.enabled = True
            modeWidget.referenceInput.enabled = True
        else:
            for widget in self.hideWhenInputIsScalar:
                widget.visible = True
            modeWidget.mainInput.visible = True
            if modeWidget.mainInput.currentNode() is None:
                modeWidget.referenceInput.setCurrentNode(None)

        if "krel" in self.simOptions.currentData:
            self.configWidget.setCurrentIndex(6)
            self._disableSwitchFor("Local", keep="Remote")
        elif "darcy" in self.simOptions.currentData:
            self.configWidget.setCurrentIndex(5)
            self._disableSwitchFor("Local", keep="Remote")
        elif "kabs_rev" in self.simOptions.currentData:
            self.configWidget.setCurrentIndex(4)
            self._disableSwitchFor("Local", keep="Remote")
        elif "kabs" in self.simOptions.currentData:
            self.configWidget.setCurrentIndex(3)
            self._disableSwitchFor("Local", keep="Remote")
        elif "hpsd" in self.simOptions.currentData:
            self.configWidget.setCurrentIndex(1)
            self._enableAllSwitches()
        elif "psd" in self.simOptions.currentData:
            self.configWidget.setCurrentIndex(0)
            self._enableAllSwitches()
        else:
            self.configWidget.setCurrentIndex(2)
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

        if node is None:
            return

        # Get name first to avoid using reference node name
        nodeName = node.GetName()

        if node.IsA("vtkMRMLSegmentationNode"):
            node = helpers.getSourceVolume(node)
            if node is None:
                return

        # tokens = nodeName.split("_")
        # if len(tokens) < 4:
        #     arr = slicer.util.arrayFromVolume(node).astype(np.uint8)
        #     image_type = "BIN"

        #     shape = ["{:04d}".format(int(d)) for d in arr.shape[::-1]]
        #     res = min([v for v in node.GetSpacing()])

        #     nodeName = "_".join([*tokens, image_type, *shape, "{:05d}".format(int(round(res * 1e6))) + "nm"])

        self.outputPrefix.setText(nodeName)

    def _onReferenceSelected(self, node):

        if "darcy_kabs_foam" in self.simOptions.currentData:
            self.simBtn.enabled = node is not None

            if node is None:
                return

            nodeName = node.GetName()
            tokens = nodeName.split("_")
            if len(tokens) < 4:
                arr = slicer.util.arrayFromVolume(node).astype(np.float64)
                image_type = "KABS"

                shape = ["{:04d}".format(int(d)) for d in arr.shape[::-1]]
                res = min([v for v in node.GetSpacing()])

                nodeName = "_".join([*tokens, image_type, *shape, "{:05d}".format(int(round(res * 1e6))) + "nm"])

            self.outputPrefix.setText(nodeName)

    def onSelectionChanged(self):
        items = self.ioFileVariablesList.selectedItems()
        self.ioFileLoadDataSetButton.enabled = len(items) > 0

    def onCLICancelCLicked(self):
        try:
            text = self.ioRunningComboBox.currentItem().text()
            amatch = re.search(r"\[(.*)\]", text)
            if amatch:
                workspace = amatch.group(1)
                print(f"Cancelling {workspace}")
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
            self.simBtn.enabled = False
            self.simBtn.blockSignals(True)
            slicer.app.processEvents()

            modeWidget: widgets.SingleShotInputWidget = self.modeWidgets[self.currentMode]

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
            print_debug(repr(e))
        finally:
            slicer.app.processEvents()
            self.simBtn.blockSignals(False)
            self.simBtn.enabled = True


#
# MicrotomRemoteLogic
#
class MicrotomRemoteLogic(LTracePluginLogic):
    def __init__(self, widget):
        self.widget = widget

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

                # name_template = "_".join([v for v in (prefix, simulator, dtype) if v])
                # nodeName = slicer.mrmlScene.GenerateUniqueName(name_template)
                # node.SetName(nodeName)

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

        # if simulator == "krel":
        #     workspaceDir = None
        #     for vtkVolumePath, volumeName in zip(
        #         jsonDict.get("output_vtk_volumes", ""), jsonDict.get("output_volumes_titles", "")
        #     ):
        #         try:
        #             properties = {"name": volumeName}
        #             vtkVolumePath = str(Path(vtkVolumePath))
        #             workspaceDir = Path(vtkVolumePath).parents[2]
        #             volume = slicer.util.loadVolume(vtkVolumePath, properties=properties)
        #             folderTree.CreateItem(foundResultDir, volume)
        #         except Exception as e:
        #             slicer.util.errorDisplay(f"Failed to load vtk simulation output volume {volumeName}:\n {repr(e)}")

        #     for tablePath, tableName in zip(
        #         jsonDict.get("output_tables", ""), jsonDict.get("output_tables_titles", "")
        #     ):
        #         try:
        #             tablePath = str(Path(tablePath))
        #             table = slicer.util.loadTable(tablePath)
        #             table.SetName(tableName)
        #             folderTree.CreateItem(foundResultDir, table)
        #         except Exception as e:
        #             slicer.util.errorDisplay(f"Failed to load permeability table {tableName}:\n {repr(e)}")
        #     if workspaceDir is not None:
        #         shutil.rmtree(workspaceDir)

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
            for line in lines[:MAX_LOOP_ITERATIONS]:
                cols = line.strip().split(",")
                for c in cols:
                    m = pat.search(c.strip())
                    if m:
                        block = m.groupdict()
                        data[block["name"]].append(float(block["value"]))
            return pd.DataFrame(data)

        except Exception as e:
            print_stack()
            print_debug(f"Failed to load custom log file. Cause: {repr(e)}", channel=logging.warning)
            return None

    def onPorosimetryCLIModified(self, sim_info, cliNode, event):
        sequenceIndex = -1

        if cliNode is None:
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
                output_file_dir = Path(slicer.app.temporaryPath).absolute() / rf"{simulator}.csv"
                df = self.loadCustomLog(Path(output_file_dir))
                output_file_dir.unlink()

                if df is not None:
                    tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
                    tableNode.SetName(f"{prefix}_{simulator}_Runtime_Log")
                    du.dataFrameToTableNode(df, tableNode)
                    nodes.append(tableNode)

            except Exception as e:
                logging.error(f"Failed to load runtime log. Cause: {repr(e)}")

            if sequenceIndex < 1:
                self.addNodesToScene(nodes)
                self.setNodesHierarchy(nodes, referenceNode, projectDirName=f"{prefix}_{simulator}")

            if sequenceIndex > -1:
                self.findSequenceAndAddNode(prefix, nodes, sequenceIndex)

        if not cliNode.IsBusy():
            print("ExecCmd CLI %s" % cliNode.GetStatusString())

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
        cliNode = slicer.cli.run(slicer.modules.porosimetrycli, None, cliParams, wait_for_completion=False)
        cliNode.AddObserver("ModifiedEvent", partial(self.onPorosimetryCLIModified, sim_info))
        # Setup progress bar
        self.widget.progressBar.setCommandLineModuleNode(cliNode)

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
            print_stack()
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

        print("CLI Run")

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
