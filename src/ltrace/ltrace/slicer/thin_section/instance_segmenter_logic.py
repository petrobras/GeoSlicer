import json
import os
from pathlib import Path

from ltrace.slicer.helpers import (
    clearPattern,
    createNode,
    generateName,
    moveNodeTo,
    separateLabelmapVolumeIntoSlices,
    updateSegmentationFromLabelMap,
)
from ltrace.slicer_utils import dataFrameToTableNode
import numpy as np

import pandas as pd
import vtk
import slicer

from .utils import *
from .cli_event_handler import CLIEventHandler


class ThinSectionInstanceSegmenterLogic:
    def __init__(self, onFinish=None):
        self.onFinish = onFinish or (lambda: None)
        self.progressUpdate = lambda value: print(value * 100, "%")

        self.config = None
        self.warningMessage = None

    def loadConfig(self):
        moduleDir = Path(os.path.dirname(os.path.realpath(__file__)))
        sampleFilePath = moduleDir / "Resources" / "ThinSectionInstanceSegmenterConfig.json"

        with open(sampleFilePath, "r") as f:
            config = json.load(f)
            self.config = config["atena02"]
            return self.config

    def run(
        self,
        model,
        referenceNode,
        soiNode,
        outputPrefix,
        params,
        classes,
        recommendedSettingsButtonText,
        chunkSizeCheckboxText,
        segmentation=False,
    ):
        tmpOutNode = createNode(slicer.vtkMRMLLabelMapVolumeNode, outputPrefix.replace("{type}", "TMP_OUTNODE"))
        slicer.mrmlScene.AddNode(tmpOutNode)

        inputNodes = [referenceNode]

        tmpInputNodes, ctypes = prepareTemporaryInputs(
            inputNodes,
            outputPrefix=outputPrefix,
            soiNode=soiNode,
            referenceNode=referenceNode,
            colorsToSlices=True,
        )

        tmpReferenceNode, *tmpExtraNodes = tmpInputNodes

        if params["chunk_size"] is not None:
            refDims = np.array(tmpReferenceNode.GetImageData().GetDimensions())
            refMinSize = min(refDims[1:])
            if params["chunk_size"] > refMinSize:
                slicer.util.warningDisplay(
                    f'The chosen chunk size is larger than the selected region of interest. Consider one of the following options:\n\n- Use the recommended configuration (by hitting "{recommendedSettingsButtonText}");\n\n- Run inference on the whole image (by unchecking "{chunkSizeCheckboxText}");\n\n- Reduce the chunk size manually.'
                )
                return

        cliConf = dict(
            input_model=model,
            input_volume=tmpReferenceNode.GetID(),
            output_volume=tmpOutNode.GetID(),
            output_table=str(Path(slicer.app.temporaryPath) / "instances_report"),
            ctypes=",".join(ctypes),
        )

        cliConf["xargs"] = json.dumps(params)

        if ctypes[0] == "rgb":
            cliNode = slicer.cli.run(
                slicer.modules.thinsectioninstancesegmentercli,
                None,
                cliConf,
                wait_for_completion=False,
            )
        else:
            slicer.util.warningDisplay(
                "You need to pass a rgb image.\nGo to Thin Section environment for more details."
            )
            return

        def onSuccess(caller):
            try:
                volumeIJKToRASMatrix = vtk.vtkMatrix4x4()
                tmpReferenceNode.GetIJKToRASMatrix(volumeIJKToRASMatrix)
                tmpOutNode.SetIJKToRASMatrix(volumeIJKToRASMatrix)
                referenceSpacing = tmpReferenceNode.GetSpacing()
                tmpOutNode.SetSpacing(referenceSpacing)
                volumeOrigin = tmpReferenceNode.GetOrigin()
                tmpOutNode.SetOrigin(volumeOrigin)

                folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
                itemTreeId = folderTree.GetItemByDataNode(referenceNode)
                parentItemId = folderTree.GetItemParent(itemTreeId)
                outputDir = folderTree.CreateFolderItem(
                    parentItemId, generateName(folderTree, f"{outputPrefix.replace('_{type}', '')} Results")
                )

                tableNodes = []
                sliceNodes = separateLabelmapVolumeIntoSlices(tmpOutNode, axis=0, verifyContent=True, dtype=np.int32)

                if len(sliceNodes) == 0:
                    self.warningMessage = "The model didn't find any instance.\n"
                    folderTree.RemoveItem(outputDir, True, True)

                    slicer.util.setSliceViewerLayers(
                        background=referenceNode,
                        fit=True,
                    )
                else:
                    if params["calculate_statistics"] and cliConf["output_table"]:
                        try:
                            output_report = pd.read_pickle(cliConf["output_table"])
                            os.remove(cliConf["output_table"])
                        except OSError as e:
                            self.warningMessage = (
                                "Without data on table.\nCan't calculate statistics on predicted labels.\n"
                            )

                    for i, node in sliceNodes:
                        node.SetIJKToRASMatrix(volumeIJKToRASMatrix)
                        node.SetSpacing(referenceSpacing)
                        node.SetOrigin(volumeOrigin)
                        if soiNode:
                            node = maskInputWithROI(node, soiNode, mask=True)

                        paddingImageUntilReference(node, referenceNode)

                        if segmentation:
                            array = slicer.util.arrayFromVolume(node)
                            instances = np.unique(array)

                            outNode = createNode(slicer.vtkMRMLSegmentationNode, f"{classes[i]}")
                            outNode.SetHideFromEditors(False)
                            slicer.mrmlScene.AddNode(outNode)
                            outNode.SetReferenceImageGeometryParameterFromVolumeNode(
                                referenceNode
                            )  # use orignal volume

                            invmap = [
                                [j, f"Segment_{j}", self.color_dict[classes[i]]] for j in range(len(instances[1:]))
                            ]

                            updateSegmentationFromLabelMap(outNode, labelmapVolumeNode=node)
                            revertColorTable(invmap, outNode)

                            setupResultInScene(outNode, referenceNode, None, croppedReferenceNode=tmpReferenceNode)
                            outNode.GetDisplayNode().SetVisibility(True)

                            slicer.mrmlScene.RemoveNode(node)
                        else:
                            nodeTreeId = folderTree.CreateItem(parentItemId, node)
                            moveNodeTo(outputDir, node, dirTree=folderTree)
                            folderTree.SetItemDisplayVisibility(nodeTreeId, True)
                            node.SetName(classes[i])

                            if params["calculate_statistics"]:
                                tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
                                nodeTreeId = folderTree.CreateItem(parentItemId, tableNode)

                                tableNode.SetName(classes[i] + "_Report")
                                class_report = output_report.loc[output_report["class"] == classes[i]]
                                class_report = class_report.drop("class", axis=1)
                                dataFrameToTableNode(class_report, tableNode=tableNode)
                                setTableUnits(tableNode)

                                del class_report

                                tableNode.SetAttribute("InstanceEditor", classes[i])
                                tableNode.SetAttribute("ReferenceVolumeNode", node.GetID())
                                tableNode.AddNodeReferenceID("InstanceEditorLabelMap", node.GetID())
                                tableNode.AddNodeReferenceID("referenceNode", referenceNode.GetID())
                                tableNodes.append(tableNode)
                                node.SetAttribute("ThinSectionInstanceTableNode", tableNode.GetID())

                            colorNode = slicer.util.loadColorTable(
                                str(
                                    Path(os.path.dirname(os.path.realpath(__file__)))
                                    / "Resources"
                                    / f"{classes[i]}.ctbl"
                                )
                            )
                            node.GetDisplayNode().SetAndObserveColorNodeID(colorNode.GetID())

                    if node:
                        slicer.util.setSliceViewerLayers(
                            background=referenceNode,
                            label=node,
                            fit=True,
                        )
                    else:
                        slicer.util.setSliceViewerLayers(
                            background=referenceNode,
                            fit=True,
                        )

                    if len(tableNodes) != 0:
                        for tableNode in tableNodes:
                            moveNodeTo(outputDir, tableNode, dirTree=folderTree)

            except Exception as e:
                print("Handle errors on state: %s" % caller.GetStatusString())
                tmpPrefix = outputPrefix.replace("{type}", "TMP_*")
                clearPattern(tmpPrefix)
                self.progressUpdate(0)
                raise

        def onFinish(caller):
            print("ExecCmd CLI %s" % caller.GetStatusString())
            tmpPrefix = outputPrefix.replace("{type}", "TMP_*")
            clearPattern(tmpPrefix)
            self.progressUpdate(1.0)
            self.onFinish()
            cliNode.RemoveObserver(self.observerTag)
            if self.warningMessage is not None:
                slicer.util.warningDisplay(self.warningMessage)
                self.warningMessage = None

        ehandler = CLIEventHandler()
        ehandler.onSuccessEvent = onSuccess
        ehandler.onFinish = onFinish

        self.observerTag = cliNode.AddObserver("ModifiedEvent", ehandler)

        return cliNode

    def dispatch(
        self,
        model,
        referenceNode,
        soiNode,
        outputPrefix,
        params,
        classes,
        segmentation=False,
    ):
        from Segmenter.ThinSectionInstanceSegmenterRemoteTask.ThinSectionInstanceSegmenterExecutionHandler import (
            ThinSectionInstanceSegmenterExecutionHandler,
        )
        from ltrace.remote.handlers.InstanceSegmenterHandler import ResultHandler

        handler = ResultHandler()

        tmpOutNode = createNode(slicer.vtkMRMLLabelMapVolumeNode, outputPrefix.replace("{type}", "TMP_OUTNODE"))
        slicer.mrmlScene.AddNode(tmpOutNode)

        inputNodes = [referenceNode]

        tmpInputNodes, ctypes = prepareTemporaryInputs(
            inputNodes,
            outputPrefix=outputPrefix,
            soiNode=soiNode,
            referenceNode=referenceNode,
            colorsToSlices=True,
        )

        tmpReferenceNode, *tmpExtraNodes = tmpInputNodes

        cmd_handler = ThinSectionInstanceSegmenterExecutionHandler(
            handler,
            outputPrefix.replace("{type}", "LabelMap.nrrd"),
            bin_path=self.config["pythonInterpreter"],
            script_path=self.config["script"],
            model_path=model,
            reference_node_id=referenceNode.GetID(),
            tmp_reference_node_id=tmpReferenceNode.GetID(),
            soi_node_id=soiNode.GetID() if soiNode else None,
            ctypes=ctypes,
            params=params,
            classes=classes,
            segmentation=False,
            opening_cmd='bash -c "source /etc/bashrc" && source /nethome/drp/microtom/init.sh',
        )

        job_name = f"Inst. Seg.: {outputPrefix.replace('_{type}', '')} ({os.path.basename(model)})"

        slicer.modules.RemoteServiceInstance.cli.run(cmd_handler, name=job_name, job_type="instseg")
