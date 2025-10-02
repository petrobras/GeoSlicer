import datetime
import logging
import os
from collections import namedtuple
from pathlib import Path

import ctk
import qt
import slicer
from ltrace.slicer import helpers
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer_utils import *

from ltrace.slicer.node_attributes import NodeEnvironment


class CustomizedMedianImageFilter(LTracePlugin):
    SETTING_KEY = "CustomizedMedianImageFilter"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Median Image Filter"
        self.parent.categories = ["Tools", "MicroCT", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.setHelpUrl("Volumes/Filter/MicroCTFlowApplyFilters.html", NodeEnvironment.MICRO_CT)
        self.setHelpUrl("Multiscale/VolumesPreProcessing/Filter.html", NodeEnvironment.MULTISCALE)

        self.parent.helpText = CustomizedMedianImageFilter.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class CustomizedMedianImageFilterWidget(LTracePluginWidget):
    # Settings constants
    X_NEIGHBORHOOD = "xNeighborhood"
    Y_NEIGHBORHOOD = "yNeighborhood"
    Z_NEIGHBORHOOD = "zNeighborhood"
    OUTPUT_SUFFIX = "_Median"

    FilteringParameters = namedtuple(
        "FilteringParameters", ["inputVolume", X_NEIGHBORHOOD, Y_NEIGHBORHOOD, Z_NEIGHBORHOOD, "outputVolumeName"]
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def getXNeighborhood(self):
        return CustomizedMedianImageFilter.get_setting(self.X_NEIGHBORHOOD, default="1")

    def getYNeighborhood(self):
        return CustomizedMedianImageFilter.get_setting(self.Y_NEIGHBORHOOD, default="1")

    def getZNeighborhood(self):
        return CustomizedMedianImageFilter.get_setting(self.Z_NEIGHBORHOOD, default="1")

    def setup(self):
        LTracePluginWidget.setup(self)
        self.progressBar = LocalProgressBar()
        self.logic = CustomizedMedianImageFilterLogic(self.progressBar)

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        formLayout = qt.QFormLayout(frame)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        # Input section
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Input")
        self.inputCollapsibleButton = inputCollapsibleButton
        formLayout.addRow(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.inputVolumeComboBox = slicer.qMRMLNodeComboBox()
        self.inputVolumeComboBox.nodeTypes = ["vtkMRMLScalarVolumeNode"]
        self.inputVolumeComboBox.selectNodeUponCreation = True
        self.inputVolumeComboBox.addEnabled = False
        self.inputVolumeComboBox.removeEnabled = False
        self.inputVolumeComboBox.noneEnabled = True
        self.inputVolumeComboBox.showHidden = False
        self.inputVolumeComboBox.showChildNodeTypes = False
        self.inputVolumeComboBox.setMRMLScene(slicer.mrmlScene)
        self.inputVolumeComboBox.setToolTip("Select the input image.")
        self.inputVolumeComboBox.currentNodeChanged.connect(self.onInputChanged)
        inputFormLayout.addRow("Input image:", self.inputVolumeComboBox)
        inputFormLayout.addRow(" ", None)

        # Parameters section
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.setText("Parameters")
        formLayout.addRow(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.xNeighborhoodSpinBox = qt.QSpinBox()
        self.xNeighborhoodSpinBox.setValue(float(self.getXNeighborhood()))
        self.xNeighborhoodSpinBox.toolTip = "The size of the neighborhood in the X dimension."
        xBoxLayout = qt.QHBoxLayout()
        xBoxLayout.addWidget(self.xNeighborhoodSpinBox)
        parametersFormLayout.addRow("X Neighborhood:", xBoxLayout)

        self.yNeighborhoodSpinBox = qt.QSpinBox()
        self.yNeighborhoodSpinBox.setValue(float(self.getYNeighborhood()))
        self.yNeighborhoodSpinBox.toolTip = "The size of the neighborhood in the Y dimension."
        yBoxLayout = qt.QHBoxLayout()
        yBoxLayout.addWidget(self.yNeighborhoodSpinBox)
        parametersFormLayout.addRow("Y Neighborhood:", yBoxLayout)

        self.zNeighborhoodSpinBox = qt.QSpinBox()
        self.zNeighborhoodSpinBox.setValue(float(self.getZNeighborhood()))
        self.zNeighborhoodSpinBox.toolTip = "The size of the neighborhood in the Z dimension."
        zBoxLayout = qt.QHBoxLayout()
        zBoxLayout.addWidget(self.zNeighborhoodSpinBox)
        parametersFormLayout.addRow("Z Neighborhood:", zBoxLayout)

        parametersFormLayout.addRow(" ", None)

        # Output section
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        self.outputCollapsibleButton = outputCollapsibleButton
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.outputVolumeNameLineEdit = qt.QLineEdit()
        outputFormLayout.addRow("Output image name:", self.outputVolumeNameLineEdit)

        outputFormLayout.addRow(" ", None)

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setFixedHeight(40)
        self.applyButton.clicked.connect(self.onApplyButtonClicked)

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.setFixedHeight(40)
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.applyButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        formLayout.addRow(buttonsHBoxLayout)

        self.layout.addStretch()

        self.layout.addWidget(self.progressBar)

    def onApplyButtonClicked(self):
        try:
            if self.inputVolumeComboBox.currentNode() is None:
                raise FilteringInfo("Input image is required.")
            if not self.outputVolumeNameLineEdit.text:
                raise FilteringInfo("Output image name is required.")

            CustomizedMedianImageFilter.set_setting(self.X_NEIGHBORHOOD, self.xNeighborhoodSpinBox.value)
            CustomizedMedianImageFilter.set_setting(self.Y_NEIGHBORHOOD, self.yNeighborhoodSpinBox.value)
            CustomizedMedianImageFilter.set_setting(self.Z_NEIGHBORHOOD, self.zNeighborhoodSpinBox.value)
            filteringParameters = self.FilteringParameters(
                self.inputVolumeComboBox.currentNode(),
                self.xNeighborhoodSpinBox.value,
                self.yNeighborhoodSpinBox.value,
                self.zNeighborhoodSpinBox.value,
                self.outputVolumeNameLineEdit.text,
            )
            self.logic.apply(filteringParameters)
        except FilteringInfo as e:
            slicer.util.infoDisplay(str(e))
            return

    def onCancelButtonClicked(self):
        self.logic.cancel()

    def onInputChanged(self, inputNode):
        newOutputName = inputNode.GetName() + self.OUTPUT_SUFFIX if inputNode != None else ""
        self.outputVolumeNameLineEdit.setText(newOutputName)


class CustomizedMedianImageFilterLogic(LTracePluginLogic):
    def __init__(self, progressBar):
        LTracePluginLogic.__init__(self)
        self.cliNode = None
        self.progressBar = progressBar
        self.onComplete = lambda: None
        self.onFailed = lambda: None

    def apply(self, p):
        # Removing old cli node if it exists
        slicer.mrmlScene.RemoveNode(self.cliNode)
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        inputVolumeItemParent = subjectHierarchyNode.GetItemParent(
            subjectHierarchyNode.GetItemByDataNode(p.inputVolume)
        )

        # Output volume
        self.outputVolume = slicer.mrmlScene.AddNewNodeByClass(p.inputVolume.GetClassName())
        self.outputVolume.SetName(p.outputVolumeName)
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(self.outputVolume), inputVolumeItemParent
        )

        cliParams = {
            "inputVolume": p.inputVolume.GetID(),
            "outputVolume": self.outputVolume.GetID(),
            "neighborhood": str((p.xNeighborhood, p.yNeighborhood, p.zNeighborhood)),
        }

        self.inputVolume = p.inputVolume
        self.cliNode = slicer.cli.run(slicer.modules.medianimagefilter, None, cliParams)
        self.progressBar.setCommandLineModuleNode(self.cliNode)
        self.cliNode.AddObserver("ModifiedEvent", self.filteringCLICallback)

    def filteringCLICallback(self, caller, event):
        status = caller.GetStatusString()
        if "Completed" in status or status == "Cancelled":
            logging.info(status)
            self.cliNode.RemoveAllObservers()
            self.cliNode = None

            slicer.util.setSliceViewerLayers(background=self.outputVolume, fit=True)
            helpers.copy_display(self.inputVolume, self.outputVolume)

            if status == "Completed":
                self.onComplete()
            elif status == "Cancelled":
                slicer.mrmlScene.RemoveNode(self.outputVolume)
                self.onFailed()
            else:
                slicer.mrmlScene.RemoveNode(self.outputVolume)
                slicer.util.errorDisplay("Filtering failed.")
                self.onFailed

    def cancel(self):
        if self.cliNode is None:
            return  # nothing running, nothing to do
        self.cliNode.Cancel()


class FilteringInfo(RuntimeError):
    pass
