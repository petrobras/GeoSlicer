"""Image quality metrics on Slicer nodes: converts a volume and a segmentation to arrays and keeps the results table."""

import numpy as np
import pandas as pd
import slicer

from commons.lmath.image_quality_api import QualityError, QualityOptions, QualityResult, measure_quality
from commons.slicer.data_utils import dataFrameToTableNode, tableNodeToDataFrame
from commons.slicer.helpers import arrayFromSegmentBinaryLabelmap

TABLE_NODE_NAME = "Image Quality Metrics"


def measureNodes(volumeNode, segmentationNode, options: QualityOptions, metadata=None) -> QualityResult:
    """Run `measure_quality` with the segments of `segmentationNode` as regions (segment ids in `options`).

    `metadata` maps column names to values and is copied into the row of the result.
    """
    segmentation = segmentationNode.GetSegmentation()
    return measure_quality(
        slicer.util.arrayFromVolume(volumeNode),
        # Slicer arrays are (z, y, x) while GetSpacing() is (x, y, z)
        tuple(reversed(volumeNode.GetSpacing())),
        mask_provider=lambda segmentId: _segmentMask(segmentationNode, segmentId, volumeNode),
        name_provider=lambda segmentId: segmentation.GetSegment(segmentId).GetName(),
        options=options,
        label=volumeNode.GetName(),
        metadata=metadata,
    )


# Exporting a segment to the geometry of the volume takes, at its peak, about this many bytes per voxel (measured: 11.6
# on a 1000^3 volume)
EXPORT_BYTES_PER_VOXEL = 12


def _availableMemory():
    """Free memory in bytes, or None if it cannot be told."""
    try:
        import psutil

        return int(psutil.virtual_memory().available)
    except Exception:
        pass
    try:
        with open("/proc/meminfo") as meminfo:
            for line in meminfo:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def _segmentMask(segmentationNode, segmentId, volumeNode):
    """Mask of a segment in the geometry of the volume."""
    voxels = int(np.prod(slicer.util.arrayFromVolume(volumeNode).shape))
    available = _availableMemory()
    if available is not None and available < EXPORT_BYTES_PER_VOXEL * voxels:
        raise QualityError(
            f"Not enough free memory to export a segment of this volume: about "
            f"{EXPORT_BYTES_PER_VOXEL * voxels / 1024**3:.0f} GB are needed and {available / 1024**3:.0f} GB are free. "
            "Close other applications and try again."
        )
    mask = arrayFromSegmentBinaryLabelmap(segmentationNode, segmentId, volumeNode)
    # The exported labelmap holds 0 and 1 only. Viewing it as bool avoids a copy of the whole volume.
    return mask.view(bool) if mask is not None and mask.dtype == np.uint8 else mask


def resultsTableNode():
    node = slicer.mrmlScene.GetFirstNodeByName(TABLE_NODE_NAME)
    return node if node is not None and node.IsA("vtkMRMLTableNode") else None


def appendResultRow(row: dict):
    """Add a row to the persistent results table, creating it on first use. Returns the table node."""
    tableNode = resultsTableNode()
    if tableNode is None:
        tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", TABLE_NODE_NAME)
    frame = pd.concat([tableNodeToDataFrame(tableNode), pd.DataFrame([row])], ignore_index=True)
    textColumns = {column: "" for column in frame.columns if frame[column].dtype == object}
    dataFrameToTableNode(frame.fillna(textColumns), tableNode, replace=True)
    return tableNode


def clearResultsTable():
    tableNode = resultsTableNode()
    if tableNode is not None:
        tableNode.RemoveAllColumns()
