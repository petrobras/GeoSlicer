import logging
import os
from collections import namedtuple
from pathlib import Path
import csv

import numpy as np
import qt
import slicer
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer_utils import *
from ltrace.slicer import helpers as lsh
from functools import partial

try:
    from Test.ResampleVectorVolumeTest import ResampleVectorVolumeTest
except ImportError:
    ResampleVectorVolumeTest = None  # tests not deployed to final version or closed source


class ResampleVectorVolume(LTracePlugin):
    SETTING_KEY = "ResampleVectorVolume"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Resample Vector Volume"
        self.parent.categories = ["Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ResampleVectorVolume.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ResampleVectorVolumeWidget(LTracePluginWidget):
    # Settings constants
    SPACING = "spacing"
    INTERPOLATION = "interpolation"
    INTERPOLATIONS = {
        "Linear": "linear",
        "Nearest Neighbor": "nn",
        "B-spline": "bs",
        "Windowed Sinc": {function: "ws" for function in ["Cosine", "Lanczos"]},
        "Mean": "mean",
    }

    ResampleParameters = namedtuple(
        "ResampleParameters",
        [
            "inputVolume",
            SPACING,
            INTERPOLATION,
        ],
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def getSpacing(self):
        return ResampleVectorVolume.get_setting(self.SPACING, default="1,1,1")

    def getInterpolation(self):
        return ResampleVectorVolume.get_setting(self.INTERPOLATION, default=self.INTERPOLATIONS["Linear"])

    def setup(self):
        LTracePluginWidget.setup(self)
        self.progressBar = LocalProgressBar()
        self.logic = ResampleVectorVolumeLogic(self.progressBar)

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        formLayout = qt.QFormLayout(frame)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        self.inputVolume = slicer.qMRMLNodeComboBox()
        self.inputVolume.objectName = "inputVolume"
        self.inputVolume.nodeTypes = ["vtkMRMLVectorVolumeNode"]
        self.inputVolume.selectNodeUponCreation = True
        self.inputVolume.addEnabled = False
        self.inputVolume.removeEnabled = False
        self.inputVolume.noneEnabled = True
        self.inputVolume.showHidden = False
        self.inputVolume.showChildNodeTypes = False
        self.inputVolume.setMRMLScene(slicer.mrmlScene)
        self.inputVolume.setToolTip("Select the input volume.")
        formLayout.addRow("Input volume:", self.inputVolume)

        self.spacingLineEdit = qt.QLineEdit(self.getSpacing())
        self.spacingLineEdit.setObjectName("spacingLineEdit")
        self.spacingLineEdit.setToolTip("The new spacing.")
        formLayout.addRow("Spacing:", self.spacingLineEdit)

        self.interpolationComboBox = qt.QComboBox()
        self.interpolationComboBox.setObjectName("interpolationComboBox")
        for method in self.INTERPOLATIONS:
            if isinstance(self.INTERPOLATIONS[method], dict):
                for function in self.INTERPOLATIONS[method]:
                    self.interpolationComboBox.addItem(function, self.INTERPOLATIONS[method][function])
            else:
                self.interpolationComboBox.addItem(method, self.INTERPOLATIONS[method])
        self.interpolationComboBox.setCurrentIndex(self.interpolationComboBox.findData(self.getInterpolation()))
        formLayout.addRow("Interpolation:", self.interpolationComboBox)
        formLayout.addRow(" ", None)

        self.resampleButton = qt.QPushButton("Resample")
        self.resampleButton.setObjectName("resampleButton")
        self.resampleButton.setFixedHeight(40)
        self.resampleButton.clicked.connect(self.onResampleButtonClicked)

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.setFixedHeight(40)
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.resampleButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        formLayout.addRow(None, buttonsHBoxLayout)

        self.layout.addStretch()

        self.layout.addWidget(self.progressBar)

    def onResampleButtonClicked(self):
        try:
            if self.inputVolume.currentNode() is None:
                raise ResampleInfo("Input volume is required.")
            if not (self.spacingLineEdit.text):
                raise ResampleInfo("Spacing is required.")
            ResampleVectorVolume.set_setting(self.SPACING, self.spacingLineEdit.text)
            ResampleVectorVolume.set_setting(self.INTERPOLATION, self.interpolationComboBox.currentData)
            resampleParameters = self.ResampleParameters(
                self.inputVolume.currentNode(),
                self.spacingLineEdit.text,
                {"name": self.interpolationComboBox.currentText, "alias": self.interpolationComboBox.currentData},
            )
            self.logic.resample(resampleParameters)
        except ResampleInfo as e:
            slicer.util.infoDisplay(str(e))
            return

    def onCancelButtonClicked(self):
        self.logic.cancel()


class ResampleVectorVolumeLogic(LTracePluginLogic):
    def __init__(self, progressBar):
        LTracePluginLogic.__init__(self)
        self.cliNode = None
        self.progressBar = progressBar

    def resample(self, p):
        def makeColorsSlices(volumeNode, outputPrefix):
            # the strategy of making color channels slices is hacky,
            # works only for 2D data and thus should be avoided
            from ltrace.slicer.helpers import rgb2label

            originalNode = volumeNode
            volumeNode = rgb2label(originalNode, outputPrefix.replace("{type}", "TMP_REFNODECM"))
            return volumeNode

        try:
            outputVolume = lsh.createTemporaryVolumeNode(
                slicer.vtkMRMLVectorVolumeNode, name=f"{p.inputVolume.GetName()}_Resampled"
            )

            subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            itemParent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(p.inputVolume))
            subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(outputVolume), itemParent)

            realDimensions = self.getVolumeRealDimensions(p.inputVolume)
            newSpacing = np.array(list(map(float, list(csv.reader([p.spacing]))[0])))
            dimensions = (
                np.floor(realDimensions / newSpacing).astype(int) if newSpacing.any() else np.array(realDimensions)
            )
            dimensions[dimensions == 0] = 1  # The minimum dimension is 1

            cliParams = {
                "inputVolume": p.inputVolume.GetID(),
                "referenceVolume": p.inputVolume.GetID(),
                "outputImageSpacing": p.spacing,
                "outputImageSize": ",".join(map(str, dimensions)),
                "interpolationType": p.interpolation["alias"],
                "outputVolume": outputVolume.GetID(),
            }

            if p.interpolation["alias"] != "mean":
                if p.interpolation["alias"] == "ws":
                    cliParams["windowFunction"] = p.interpolation["name"][0].lower()
                resampleModule = slicer.modules.resamplescalarvectordwivolume
            else:
                cliParams["volumeType"] = "vector"
                resampleModule = slicer.modules.meanresamplecli

            self.cliNode = slicer.cli.run(resampleModule, None, cliParams)
            self.progressBar.setCommandLineModuleNode(self.cliNode)
            self.cli_observer_tag = self.cliNode.AddObserver(
                "ModifiedEvent", partial(self.eventHandler, outputVolumeID=outputVolume.GetID())
            )
        except Exception as e:
            print(f"Exception on Resample: {repr(e)}")
            lsh.removeTemporaryNodes(nodes=[outputVolume])

    def getVolumeRealDimensions(self, volume):
        bounds = np.zeros(6)
        volume.GetBounds(bounds)
        realDimensions = [bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]]
        return realDimensions

    def eventHandler(self, caller, event, outputVolumeID=None):
        if self.cliNode is None:
            return
        try:
            outputNode = lsh.tryGetNode(outputVolumeID)

            status = caller.GetStatusString()
            if status == "Completed":
                logging.info(status)
                lsh.makeTemporaryNodePermanent(outputNode, show=True)
            elif status == "Cancelled":
                logging.info(status)
                lsh.removeTemporaryNodes(nodes=[outputNode])

        except Exception as e:
            print(f'Exception on Event Handler: {repr(e)} with status "{status}"')
            lsh.removeTemporaryNodes(nodes=[outputNode])

    def cancel(self):
        if self.cliNode is None:
            return  # nothing running, nothing to do
        self.cliNode.Cancel()


class ResampleInfo(RuntimeError):
    pass
