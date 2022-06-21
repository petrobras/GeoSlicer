from typing import List
from collections import namedtuple, Counter
import multiprocessing
import json
from pathlib import Path
import dask.array as da
from loguru import logger
from ltrace.slicer import helpers
import scipy.ndimage as spim
import scipy.spatial as sptl
from skimage.feature import peak_local_max
from skimage.segmentation import watershed
from skimage.morphology import square, cube
from recordtype import recordtype

import pandas as pd
import numpy as np
from scipy import ndimage
from numba import njit, prange
from porespy.filters import snow_partitioning

import slicer

from porespy.tools import extend_slice
from ltrace.slicer.helpers import (
    createOutput,
    createTemporaryNode,
    createTemporaryVolumeNode,
    extractLabels,
    getIJKVector,
    mergeSegments,
)


class InvalidSegmentError(Exception):
    def __init__(self, segments: List[str] = None, threshold=0.5):
        super().__init__(
            f"You have selected these segments: {segments}. This selection represents less than {threshold}% of the image, "
            "which is not enough to apply the partitioning method. Please select another segment or choose a different dataset."
        )

        self.selection = segments
        self.threshold = threshold


Results = recordtype("Results", [("im", None), ("dt", None), ("peaks", None), ("regions", None)])


ResultInfo = namedtuple(
    "ResultInfo",
    [
        "sourceLabelMapNode",
        "outputVolume",
        "outputReport",
        "reportNode",
        "outputPrefix",
        "allLabels",
        "targetLabels",
        "saveOutput",
        "referenceNode",
        "params",
        "currentDir",
        "inputNode",
        "roiNode",
    ],
)


def runPartitioning(
    labelMapNode,
    labels,
    outputPrefix,
    params,
    currentDir,
    create_output=True,
    tag=None,
    inputNode=None,
    wait=False,
    **kwargs,
):
    reportNode = createOutput(
        prefix=outputPrefix,
        where=currentDir,
        ntype="Report",
        builder=lambda n, hidden=True: createTemporaryNode(slicer.vtkMRMLTableNode, n, environment=tag, hidden=hidden),
    )

    if create_output:
        outNode = createOutput(
            prefix=outputPrefix,
            where=currentDir,
            ntype="LabelMap",
            builder=lambda n, hidden=True: createTemporaryVolumeNode(
                slicer.vtkMRMLLabelMapVolumeNode, n, environment=tag, hidden=hidden
            ),
        )
        outNodeID = outNode.GetID()
    else:
        outNodeID = None

    helpers.castVolumeNode(labelMapNode, dtype=np.uint32)

    sourceLabelMapNode = createTemporaryVolumeNode(
        slicer.vtkMRMLLabelMapVolumeNode, name="Source Inspector LabelMap", environment=tag, content=labelMapNode
    )

    if params["method"] is not None:
        labelsValues = list(labels.keys())
        mergeSegments(labelMapNode, labelsValues)

    segment_count_array = np.bincount(slicer.util.arrayFromVolume(labelMapNode).ravel(), minlength=2)

    segment_percent = (segment_count_array[1] / sum(segment_count_array)) * 100

    threshold = 0.08  # arbitrarily chosen
    if segment_percent < threshold:
        result = slicer.util.confirmOkCancelDisplay(
            f"The selected segments represents less than {threshold}% of the image. Are you sure you want to continue?\n"
        )
        if result == False:
            raise RuntimeError("Canceled")

    directionVector = params.get("direction", None)
    if directionVector:
        direction = getIJKVector(directionVector, labelMapNode).tolist()
        params["direction"] = sorted(direction, key=lambda p: p[0], reverse=True)
    else:
        params["direction"] = []

    outputPath = str(Path(slicer.app.temporaryPath).absolute() / "temp_data.pkl")

    throatOutputVolume = params.get("throatOutputLabelVolume")

    products = kwargs.get("products", None) or ["all"]

    cliConf = dict(
        params=json.dumps(params),
        products=",".join(products),
        labelVolume=labelMapNode.GetID(),
        outputVolume=outNodeID,
        outputReport=outputPath,
        throatOutputVolume=throatOutputVolume,
    )

    cliNode = slicer.cli.run(slicer.modules.segmentinspectorcli, None, cliConf, wait_for_completion=wait)

    allLabels = labels if inputNode is None else extractLabels(inputNode)
    resultInfo = ResultInfo(
        sourceLabelMapNode=sourceLabelMapNode,
        outputVolume=cliConf["outputVolume"],
        outputReport=cliConf["outputReport"],
        reportNode=reportNode,
        outputPrefix=outputPrefix,
        allLabels=allLabels,
        targetLabels=labels,
        saveOutput=kwargs.get("saveTo", None),
        referenceNode=kwargs.get("referenceNode", None),
        params=params,
        currentDir=currentDir,
        inputNode=labelMapNode,
        roiNode=kwargs.get("roiNode"),
    )

    return cliNode, resultInfo


def islands(im):
    labels_im, _ = ndimage.label(im.astype(np.uint8))
    tup = Results()
    tup.im = im
    tup.dt = None
    tup.peaks = None
    tup.regions = labels_im

    return tup
