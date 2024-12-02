import csv
import numpy as np
import slicer

from pathlib import Path
from typing import Iterator, Union
from ltrace.slicer import export


def _units(node: slicer.vtkMRMLNode) -> str:
    if isinstance(node, slicer.vtkMRMLSegmentationNode):
        return "label"
    elif isinstance(node, slicer.vtkMRMLScalarVolumeNode):
        if node.GetVoxelValueUnits():
            return node.GetVoxelValueUnits().GetCodeValue()
    elif isinstance(node, slicer.vtkMRMLTableNode):
        units = node.GetColumnUnitLabel(node.GetColumnName(1))
        if units:
            return units

    return "no unit"


def _arrayPartsFromNode(node: slicer.vtkMRMLNode) -> tuple[np.ndarray, np.ndarray]:
    mmToM = 0.001
    if isinstance(node, slicer.vtkMRMLScalarVolumeNode):
        values = slicer.util.arrayFromVolume(node).copy().squeeze()
        if values.ndim != 2:
            raise ValueError(f"Node has dimension {values.ndim}, expected 2.")

        bounds = [0] * 6
        node.GetBounds(bounds)
        ymax = -bounds[4] * mmToM
        ymin = -bounds[5] * mmToM
        spacing = node.GetSpacing()[2] * mmToM
        depthColumn = np.arange(ymin, ymax - spacing / 2, spacing)

        ijkToRas = np.zeros([3, 3])
        node.GetIJKToRASDirections(ijkToRas)
        # if ijkToRas[0][0] > 0:
        #     values = np.flip(values, axis=0)
        # if ijkToRas[1][1] > 0:
        #     values = np.flip(values, axis=1)
        # if ijkToRas[2][2] > 0:
        #     values = np.flip(values, axis=2)
    elif isinstance(node, slicer.vtkMRMLTableNode):
        values = slicer.util.arrayFromTableColumn(node, node.GetColumnName(1))
        depthColumn = slicer.util.arrayFromTableColumn(node, node.GetColumnName(0)) * mmToM
        if depthColumn[0] > depthColumn[-1]:
            depthColumn = np.flipud(depthColumn)
            values = np.flipud(values)

    return depthColumn, values


def exportCSV(node: slicer.vtkMRMLNode, directory: Path, isTechlog: bool = False) -> Iterator[float]:
    directory.mkdir(parents=True, exist_ok=True)

    labelMap = None
    units = _units(node)
    if isinstance(node, slicer.vtkMRMLSegmentationNode):
        # Generate label map from segmentation
        labelMap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        labelMap.HideFromEditorsOn()
        labelMap.SetName(node.GetName())
        slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(
            node, labelMap, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY
        )

        # Write color table
        colorTable = export.getLabelMapLabelsCSV(labelMap)
        colorFilename = directory / f"{node.GetName()} Colors.csv"
        with open(colorFilename, mode="w", newline="") as csvFile:
            writer = csv.writer(csvFile, delimiter="\n")
            writer.writerow(colorTable)

        node = labelMap

    # Extract values and generate depth column from volume
    depthColumn, values = _arrayPartsFromNode(node)
    if labelMap:
        slicer.mrmlScene.RemoveNode(labelMap)

    # Add a dimension for tables
    if values.ndim == 1:
        values = values[:, np.newaxis]

    filename = directory / f"{node.GetName()}.csv"

    with open(filename, mode="w", newline="") as csvFile:
        writer = csv.writer(csvFile)
        if isTechlog:
            writer.writerows([["depth", "intensity"], ["m", units]])
        else:
            row = ["MD"] + [f"{node.GetName()}[{i}]" for i in range(values.shape[1])]
            writer.writerow(row)

        for i in range(values.shape[0]):
            depth = "%.6f" % depthColumn[i]
            row = values[i]
            if not labelMap:
                row = ["%.4f" % value for value in row]

            if isTechlog:
                # Techlog flattened format
                for value in row:
                    writer.writerow([depth, value])
            else:
                # Matrix format
                writer.writerow([depth] + list(row))

            if i % 100 == 0:
                # Progress
                yield i / values.shape[0]

                # Keep UI responsive
                slicer.app.processEvents()
