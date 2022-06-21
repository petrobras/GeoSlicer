#! /usr/bin/env python-real

import vtk

import pickle
from multiprocessing import Manager, Pool, cpu_count
from pathlib import Path

import cv2
import mrml
import numpy as np
import slicer
import slicer.util
from ltrace.wrappers import sanitize_file_path
from ltrace.transforms import transformPoints, getRoundedInteger
from ltrace.units import global_unit_registry as ureg, SLICER_LENGTH_UNIT
from pathvalidate.argparse import sanitize_filepath_arg
from skimage.feature import canny
from skimage.transform import hough_circle, hough_circle_peaks


def calculateCoreGeometry(volume, coreRadius):
    normalizedVolumeArray = normalize(slicer.util.arrayFromVolume(volume))

    # Avoiding destroyed core ends
    numDiscardedEndSlices = 20

    # Search radius margin in SLICER_LENGTH_UNIT
    searchRadiusMargin = 3 * SLICER_LENGTH_UNIT
    searchRadiusMarginInPixels = getRoundedInteger(
        physicalToImageCoordinates(searchRadiusMargin, getIntraSliceSpacing(volume))
    ).m

    startSlice = numDiscardedEndSlices
    endSlice = len(normalizedVolumeArray) - numDiscardedEndSlices
    numSliceSamples = int((endSlice - startSlice) / 5)
    coreRadiusInPixels = physicalToImageCoordinates(coreRadius, getIntraSliceSpacing(volume)).m
    minSearchRadius = coreRadiusInPixels - searchRadiusMarginInPixels
    maxSearchRadius = coreRadiusInPixels + searchRadiusMarginInPixels
    searchRadius = [minSearchRadius, maxSearchRadius]

    manager = Manager()
    slicesCoreGeometryInIJKCoordinates = manager.list()
    pool = Pool(max(cpu_count() - 2, 1))
    parameters = []
    for i in np.linspace(startSlice, endSlice, num=numSliceSamples, dtype=int):
        parameters.append((i, normalizedVolumeArray[i], searchRadius, slicesCoreGeometryInIJKCoordinates))
    pool.map(calculateSliceCoreGeometry, parameters)

    slicesCoreGeometryInIJKCoordinates = np.array(slicesCoreGeometryInIJKCoordinates)
    sliceCoreCentersInIJKCoordinates = slicesCoreGeometryInIJKCoordinates[:, :-1]
    foundRadii = slicesCoreGeometryInIJKCoordinates[:, -1]

    # Calculating the core center for each slice in RAS coordinates
    volumeIJKToRASMatrix = vtk.vtkMatrix4x4()
    volume.GetIJKToRASMatrix(volumeIJKToRASMatrix)
    sliceCoreCentersInRASCoordinates = transformPoints(volumeIJKToRASMatrix, sliceCoreCentersInIJKCoordinates)

    # Removing 1 SLICER_LENGTH_UNIT of material to obtain a cleaner result
    meanFoundRadiiInPhysical = np.around(
        imageToPhysicalCoordinates(np.mean(foundRadii) * ureg.pixel, getIntraSliceSpacing(volume))
        - 1 * SLICER_LENGTH_UNIT,
        1,
    )
    return [sliceCoreCentersInRASCoordinates, meanFoundRadiiInPhysical]


def calculateSliceCoreGeometry(parameters):
    sliceIndex, sliceImage, searchRadius, slicesCoreGeometryInIJKCoordinates = parameters
    sliceImageShape = sliceImage.shape
    # Search at max for 3 circles (core, internal and external wrapper wall) and return the smallest
    circle = findSmallestCircle(canny(sliceImage), searchRadius[0], searchRadius[1], 3)
    if (circle[0] - (sliceImageShape[1] - 1) / 2) ** 2 + (circle[1] - (sliceImageShape[0] - 1) / 2) ** 2 < (
        np.min(sliceImageShape) / 10
    ) ** 2:
        slicesCoreGeometryInIJKCoordinates.append([circle[0], circle[1], sliceIndex, circle[2]])


def findSmallestCircle(edges, startRadius, endRadius, totalNumPeaks):
    houghRadii = np.arange(startRadius, endRadius, 1)
    houghRes = hough_circle(edges, houghRadii)
    # Select the most prominent circles
    _, cx, cy, radii = hough_circle_peaks(houghRes, houghRadii, num_peaks=1, total_num_peaks=totalNumPeaks)
    # Get the smallest circle
    circle = sorted(np.array([cx, cy, radii]).T, key=lambda x: x[2])[0]
    return circle


def normalize(image):
    normalizedImage = cv2.normalize(image, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_16S)
    return normalizedImage.astype(np.uint8)


def physicalToImageCoordinates(value, spacing):
    return value / spacing


def imageToPhysicalCoordinates(value, spacing):
    return value * spacing


def getIntraSliceSpacing(volumeOrSpacing):
    if type(volumeOrSpacing) is tuple:
        return volumeOrSpacing[0]
    return getSpacing(volumeOrSpacing)[0]


def getSpacing(node):
    return tuple(i * SLICER_LENGTH_UNIT / ureg.pixel for i in node.GetSpacing())


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("volume", type=str)
    parser.add_argument("coreRadius", type=float)
    parser.add_argument("coreGeometryDataFile", type=str, type=sanitize_filepath_arg)
    args = parser.parse_args()

    # Loading the volume nrrd file from disk
    storageNode = slicer.vtkMRMLNRRDStorageNode()
    storageNode.SetFileName(args.volume)
    volume = mrml.vtkMRMLScalarVolumeNode()
    storageNode.ReadData(volume)

    # Calculating the core geometry (core centers and radii)
    coreGeometryData = calculateCoreGeometry(volume, args.coreRadius)
    coreGeometryDataFile = sanitize_file_path(args.coreGeometryDataFile)

    # Saving result on disk
    with open(coreGeometryDataFile.as_posix(), "wb") as f:
        f.write(pickle.dumps(coreGeometryData))
