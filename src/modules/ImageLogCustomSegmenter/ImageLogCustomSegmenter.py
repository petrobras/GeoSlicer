import json
import time
import typing
import re
import os
import numpy as np

from pathlib import Path
from dataclasses import dataclass

import qt, slicer

from ltrace.slicer_utils import *

from ltrace.slicer.widget.msrfnet_frontend import ComboBox, FormSection
from ltrace.slicer import helpers
from ltrace.slicer.ui import hierarchyVolumeInput

from ltrace.remote.connections import JobExecutor
from ltrace.remote.jobs import JobManager


TARGETS = ("Breakouts", "Fraturas")
PATTERN = re.compile("({})".format("|".join(TARGETS)))


class ImageLogCustomSegmenter(LTracePlugin):
    SETTING_KEY = "ImageLogCustomSegmenter"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "PUC Image Log Segmenter"
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace GeoSlicer Team"]
        self.parent.helpText = ""
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = ""


class ImageLogCustomSegmenterWidget(LTracePluginWidget):
    def manageWidget(widgetAttrName: str):
        def disallowButtonImpl(func):
            def wrapper(self, *args, **kwargs):
                try:
                    widget = getattr(self, widgetAttrName)
                    widget.enabled = False
                    print(args)
                    func(self, *args, **kwargs)
                except:
                    raise
                finally:
                    widget.enabled = True

            return wrapper

        return disallowButtonImpl

    def __init__(self, parent=None):
        LTracePluginWidget.__init__(self, parent)

        self.alignment = qt.Qt.AlignLeft

        self.logic: ImageLogCustomSegmenterLogic = None

        self.progress = None

    def setup(self):
        LTracePluginWidget.setup(self)

        self.logic = ImageLogCustomSegmenterLogic()
        # self.logic.setProgressCallback(self.updateProgress)

        self.amplitudeImageInputWidget = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLScalarVolumeNode"],
            onChange=self.onAmplitudeImageNodeChanged,
            tooltip="Select the amplitude image.",
        )

        self.classOfInterestComboBox = ComboBox(
            "classOfInterestComboBox", items=TARGETS, tooltip="Select a class to be segmented."
        )

        self.classOfInterestComboBox.currentTextChanged.connect(self.updatePrefix)

        self.outputPrefixLineEdit = qt.QLineEdit()

        self.pythonInterpreterLineEdit = qt.QLineEdit()
        self.pythonInterpreterLineEdit.enabled = False
        self.scriptLineEdit = qt.QLineEdit()
        self.scriptLineEdit.enabled = False

        self.segmentButton = qt.QPushButton("Run")
        self.segmentButton.setFixedHeight(40)
        self.segmentButton.clicked.connect(self.onApply)
        self.segmentButton.enabled = False

        sections = [
            FormSection("Inputs", children=[("Image: ", self.amplitudeImageInputWidget)], align=self.alignment),
            FormSection(
                "Parameters",
                children=[
                    ("Class of Interest: ", self.classOfInterestComboBox),
                    # ("Depth range (m): ", self.buildDepthRange()),
                ],
                align=self.alignment,
            ),
            FormSection(
                "Output",
                children=[
                    ("Output prefix: ", self.outputPrefixLineEdit),
                    ("Python Interpreter: ", self.pythonInterpreterLineEdit),
                    ("Script: ", self.scriptLineEdit),
                ],
            ),
        ]

        for sec in sections:
            self.layout.addWidget(sec)

        self.layout.addWidget(self.segmentButton)
        self.layout.addStretch(1)

        config = self.logic.loadConfig()

        self.pythonInterpreterLineEdit.text = config.get("pythonInterpreter", "")
        self.scriptLineEdit.text = config.get("script", "")

    def updatePrefix(self, text: str):
        currentValue = self.outputPrefixLineEdit.text
        newValue = re.sub(PATTERN, text, currentValue) if currentValue else text
        self.outputPrefixLineEdit.text = newValue

    def segmentButtonClicked(self, callback):
        self.segmentButton.clicked.connect(callback)

    @manageWidget("segmentButton")
    def onAmplitudeImageNodeChanged(self, itemId):
        node = self.amplitudeImageInputWidget.currentNode()
        refName = node.GetName() + "_" if node else ""

        currentClass = self.classOfInterestComboBox.currentText
        currentValue = self.outputPrefixLineEdit.text
        newValue = re.sub(PATTERN, currentClass, currentValue) if currentValue else currentClass
        self.outputPrefixLineEdit.text = f"{refName}{newValue}"

    def buildDepthRange(self):
        self.initialDepthLineEdit = qt.QSpinBox()
        self.initialDepthLineEdit.setMinimum(0)
        self.initialDepthLineEdit.setMaximum(65535)
        self.initialDepthLineEdit.setSingleStep(1)
        self.initialDepthLineEdit.setValue(0)
        self.initialDepthLineEdit.setToolTip("Initial depth to start segmenting")

        self.finalDepthLineEdit = qt.QSpinBox()
        self.finalDepthLineEdit.setMinimum(0)
        self.finalDepthLineEdit.setMaximum(65535)
        self.finalDepthLineEdit.setSingleStep(1)
        self.finalDepthLineEdit.setValue(0)
        self.finalDepthLineEdit.setToolTip("Final depth")

        widget = qt.QFrame()
        depthRangeHBoxLayout = qt.QVBoxLayout(widget)
        depthRangeHBoxLayout.setMargin(0)
        depthRangeHBoxLayout.addWidget(self.initialDepthLineEdit)
        depthRangeHBoxLayout.addWidget(self.finalDepthLineEdit)

        return widget

    def updateProgress(self, value: int, message: str = None):
        if self.progress is None:
            return

        self.progress.show()
        self.progress.activateWindow()
        self.centerProgress()

        self.progress.setValue(value)

        if message:
            self.progress.setLabelText(message)

        if value == 100:
            time.sleep(1)
            self.progress.close()
            self.progress = None

            if slicer.util.selectedModule() != "ImageLogEnv":
                if slicer.util.confirmYesNoDisplay(
                    "Your data has already been fetched. Do you want to change to ImageLogs viewer?", "Job Completed"
                ):
                    slicer.util.selectModule("ImageLogEnv")
        elif value < 0:
            self.progress.close()
            self.progress = None

        slicer.app.processEvents()

    def centerProgress(self):
        mainWindow = slicer.util.mainWindow()
        screenMainPos = mainWindow.pos
        x = screenMainPos.x() + int((mainWindow.width - self.progress.width) / 2)
        y = screenMainPos.y() + int((mainWindow.height - self.progress.height) / 2)
        self.progress.move(x, y)

    @manageWidget("segmentButton")
    def onApply(self, clicked=False):
        try:
            self.logic.dispatch(
                self.amplitudeImageInputWidget.currentNode(),
                self.classOfInterestComboBox.currentText,
                (0, 0),
                self.outputPrefixLineEdit.text,
            )
        except Exception as e:
            slicer.util.errorDisplay(repr(e))


class ResultHandler:
    def __call__(self, results: typing.Dict[str, typing.Any]) -> None:
        ref_node_id = results.get("reference_volume_node_id", None)
        ouputs = results.get("results", [])

        try:
            slicer.util.getNode(ref_node_id)
        except slicer.util.MRMLNodeNotFoundException:
            ref_node_id = None

        for local_file in ouputs:
            name = local_file.stem

            node = slicer.util.loadVolume(
                rf"{local_file}", properties={"singleFile": True, "labelmap": True, "name": name}
            )
            helpers.makeNodeTemporary(node, hide=True)

            folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

            itemTreeId = folderTree.GetItemByDataNode(node)
            parentItemId = folderTree.GetItemParent(itemTreeId)

            outputDir = folderTree.CreateFolderItem(
                parentItemId, helpers.generateName(folderTree, f"Segmentation Result")
            )

            helpers.makeTemporaryNodePermanent(node, show=True)

            helpers.moveNodeTo(outputDir, node, dirTree=folderTree)
            if ref_node_id is not None:
                node.SetAttribute("ReferenceVolumeNode", ref_node_id)


@dataclass
class ImageLogCustomSegmenterEventHandler:
    referenceNodeID: str
    outputNodeID: str

    def __call__(self, caller, *args) -> typing.Any:
        if caller is None:
            return

        status = caller.GetStatusString()

        if status == "Completed":
            outputLabelMapVolumeNode = slicer.util.getNode(self.outputNodeID)

            folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

            itemTreeId = folderTree.GetItemByDataNode(outputLabelMapVolumeNode)
            parentItemId = folderTree.GetItemParent(itemTreeId)

            outputDir = folderTree.CreateFolderItem(
                parentItemId, helpers.generateName(folderTree, f"Segmentation Result")
            )

            helpers.makeTemporaryNodePermanent(outputLabelMapVolumeNode, show=True)

            helpers.moveNodeTo(outputDir, outputLabelMapVolumeNode, dirTree=folderTree)
            if self.referenceNodeID is not None:
                outputLabelMapVolumeNode.SetAttribute("ReferenceVolumeNode", self.referenceNodeID)


class ImageLogCustomSegmenterLogic(LTracePluginLogic):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.cliNode = None
        self.config = None

    def loadConfig(self):
        moduleDir = Path(os.path.dirname(os.path.realpath(__file__)))
        sampleFilePath = moduleDir / "Resources" / "ImageLogCustomSegmenterConfig.json"

        with open(sampleFilePath, "r") as f:
            config = json.load(f)
            # TODO move this to a global config and make it flexible
            self.config = config["atena02"]
            return self.config

    def setProgressCallback(self, func: callable):
        self.progressCb = func

    def run(self, image, coi: str, depthInterval: typing.Iterable[np.uint32], outputPrefix: str):
        # TODO do all the checks

        if depthInterval[1] >= depthInterval[0]:
            if depthInterval[1] > 0:
                raise ValueError("Wrong depth interval.")
            else:
                depthInterval = (0, max(image.GetImageData().GetDimensions()))

        imResult = helpers.createTemporaryVolumeNode(
            slicer.vtkMRMLLabelMapVolumeNode, name=f"{outputPrefix}_LabelMap", content=image
        )

        params = dict(inputImage=image, outputLabel=imResult, segmentClass=coi, depthInterval=depthInterval)

        observer = ImageLogCustomSegmenterEventHandler(image.GetID(), outputNodeID=imResult.GetID())

        self.cliNode = slicer.cli.run(
            slicer.modules.petropucimagelogsegmentercli, None, params, wait_for_completion=True
        )
        self.cliNode.AddObserver("ModifiedEvent", observer)

    def dispatch(self, image, coi: str, depthInterval: typing.Iterable[np.uint32], outputPrefix: str):
        from ImageLogCustomSegmenterRemoteTask.PUCModelExecutionHandler import PUCModelExecutionHandler

        handler = ResultHandler()

        cmd_handler = PUCModelExecutionHandler(
            handler,
            f"{outputPrefix}_LabelMap.nrrd",
            bin_path=self.config["pythonInterpreter"],
            script_path=self.config["script"],
            image_log_node_id=image.GetID(),
            class_of_interest=coi,
            depth_interval=depthInterval,
            opening_cmd='bash -c "source /etc/bashrc" && source /nethome/drp/microtom/init.sh',
        )

        job_name = f"segmentation: {outputPrefix} ({coi}, {depthInterval})"

        slicer.modules.RemoteServiceInstance.cli.run(cmd_handler, name=job_name, job_type="pucnet")


def pucnet_loader(job: JobExecutor):
    from ImageLogCustomSegmenterRemoteTask.PUCModelExecutionHandler import PUCModelExecutionHandler

    details = job.details
    output_name = details.get("output_name", "output")
    class_of_interest = details.get("class_of_interest", 0)
    depth_interval = details.get("depth_interval", (0, 0))
    inputNodeId = details.get("input_volume_node_id", None)
    script_path = details.get("script_path", "")
    bin_path = details.get("bin_path", "")

    handler = ResultHandler()

    task_handler = PUCModelExecutionHandler(
        handler,
        output_name,
        bin_path=bin_path,
        script_path=script_path,
        image_log_node_id=inputNodeId,
        class_of_interest=class_of_interest,
        depth_interval=depth_interval,
        opening_cmd="",
    )

    task_handler.jobid = str(job.details["job_id"][0])
    job.task_handler = task_handler
    print("JOB ok:", job)
    return job


JobManager.register("pucnet", pucnet_loader)
