import numpy as np
import slicer
import vtk

from ltrace.transforms import transformPoints


def inscribedCuboidArray(volumeNode, radiusCutoffFactor=0.98, heightCutoffFactor=0.98):
    iLimits, jLimits, kLimits = getInscribedCuboidLimits(volumeNode, radiusCutoffFactor, heightCutoffFactor)

    array = slicer.util.arrayFromVolume(volumeNode)
    clippedArray = array[kLimits[0] : kLimits[1], jLimits[0] : jLimits[1], iLimits[0] : iLimits[1]]
    return clippedArray


def getInscribedCuboidLimits(volumeNode, radiusCutoffFactor=0.98, heightCutoffFactor=0.98):
    segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
    segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
    segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
    segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)

    # Segmenting
    segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
    segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(volumeNode)
    addedSegmentID = segmentationNode.GetSegmentation().AddEmptySegment("")
    segmentEditorWidget.setSegmentationNode(segmentationNode)
    segmentEditorWidget.setSourceVolumeNode(volumeNode)
    segmentEditorWidget.setCurrentSegmentID(addedSegmentID)
    segmentEditorWidget.setActiveEffectByName("Threshold")
    effect = segmentEditorWidget.activeEffect()
    effect.setParameter("AutoThresholdMethod", "OTSU")
    effect.setParameter("AutoThresholdMode", "SET_LOWER_MAX")
    effect.self().onAutoThreshold()
    effect.self().onApply()

    bounds = np.zeros(6)
    segmentationNode.GetBounds(bounds)
    slicer.mrmlScene.RemoveNode(segmentationNode)

    axisCenter = [(bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2]

    radius = np.mean([(bounds[1] - bounds[0]) / 2, (bounds[3] - bounds[2]) / 2]) * radiusCutoffFactor
    cubeHalfLength = radius * np.sqrt(2) / 2

    cylinderHeightCutoff = (bounds[5] - bounds[4]) * (1 - heightCutoffFactor)

    inscribedCuboidBounds = [
        axisCenter[0] - cubeHalfLength,
        axisCenter[0] + cubeHalfLength,
        axisCenter[1] - cubeHalfLength,
        axisCenter[1] + cubeHalfLength,
        bounds[4] + cylinderHeightCutoff,
        bounds[5] - cylinderHeightCutoff,
    ]

    volumeRAStoIJKMatrix = vtk.vtkMatrix4x4()
    volumeNode.GetRASToIJKMatrix(volumeRAStoIJKMatrix)

    iLimits = transformPoints(
        volumeRAStoIJKMatrix, [[inscribedCuboidBounds[0], 0, 0], [inscribedCuboidBounds[1], 0, 0]], returnInt=True
    )[:, 0]
    jLimits = transformPoints(
        volumeRAStoIJKMatrix, [[0, inscribedCuboidBounds[2], 0], [0, inscribedCuboidBounds[3], 0]], returnInt=True
    )[:, 1]
    kLimits = transformPoints(
        volumeRAStoIJKMatrix, [[0, 0, inscribedCuboidBounds[4]], [0, 0, inscribedCuboidBounds[5]]], returnInt=True
    )[:, 2]

    # According to the values in RASToIJKMatrix lower RAS values may mean higher IJK values
    # The following sorts are required in order to guarantee that the arrays are in the [lower, higher] form
    kLimits.sort()
    jLimits.sort()
    iLimits.sort()

    if iLimits[1] == 0:
        iLimits[1] = 1
    if jLimits[1] == 0:
        jLimits[1] = 1
    if kLimits[1] == 0:
        kLimits[1] = 1

    return iLimits, jLimits, kLimits
