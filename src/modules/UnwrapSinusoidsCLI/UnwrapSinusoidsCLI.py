#! /usr/bin/env python-real

import vtk

import pickle
from multiprocessing import Manager, Pool, cpu_count
from pathlib import Path

import cv2
import mrml
import numpy as np
import slicer.util
import re

from ltrace.constants import MAX_LOOP_ITERATIONS
from ltrace.transforms import getRoundedInteger
from ltrace.wrappers import sanitize_file_path
from pathvalidate.argparse import sanitize_filepath_arg
from scipy import optimize
from scipy.optimize import OptimizeWarning
from scipy.signal import correlate


def findUnwrapSinusoids(unwrapArray, sinusoidsStartingPositions):
    treatedUnwrapImage = getTreatedUnwrapImageForSinusoidFinding(unwrapArray)
    height, width = np.shape(treatedUnwrapImage)
    treatedUnwrapImage = treatedUnwrapImage - np.mean(treatedUnwrapImage)
    manager = Manager()
    sinusoids = manager.list()
    phases = manager.list()
    pool = Pool(max(cpu_count() - 2, 1))
    parameters = []
    iterations = min(len(sinusoidsStartingPositions), MAX_LOOP_ITERATIONS)
    for i in range(0, iterations):
        parameters.append((treatedUnwrapImage, sinusoidsStartingPositions[i], width, height, sinusoids, phases))
    pool.map(findUnwrapSinusoid, parameters)
    sinusoids = list(sinusoids)
    phases = list(phases)
    return [sinusoids, phases]


def findUnwrapSinusoid(parameters):
    image, startingPosition, width, height, sinusoids, phases = parameters
    gaussianWindowStd = height / 3
    shiftSize = getRoundedInteger(width / 5)
    sinusoidsPerPosition = np.zeros((width, len(np.arange(0, width, shiftSize))))
    gaussianWindow = np.exp(-(((np.arange(height) - startingPosition) / gaussianWindowStd) ** 2))
    windowedUnwrap = image * np.array([gaussianWindow]).T
    for j in np.arange(np.shape(sinusoidsPerPosition)[1]):
        shiftedUnwrap = np.roll(windowedUnwrap, j * shiftSize, axis=1)
        signalReference = np.array([shiftedUnwrap[:, 0]]).T
        correlation = np.flip(
            correlate(signalReference, shiftedUnwrap),
            (0, 1),
        )
        sinusoidsPerPosition[:, j] = np.roll(np.argmax(correlation, axis=0), -j * shiftSize)
    sinusoidsPerPosition = sinusoidsPerPosition - np.mean(sinusoidsPerPosition, axis=0)
    xData = np.arange(width)
    yData = np.median(sinusoidsPerPosition, axis=1)
    try:
        curveParameters, curveParametersCovariance = optimize.curve_fit(
            lambda x, a, b: sine(x, width, a, b),
            xData,
            yData,
            bounds=[[0, 0], [np.inf, 3 * np.pi]],
        )
        errors = np.sqrt(np.diag(curveParametersCovariance))
        # If the parameters all have errors less this standard deviation fraction, include fit
        if np.max(errors) < 0.5:
            sinusoids.append(sine(xData, width, *curveParameters) + startingPosition - curveParameters[0] / 2)
            phases.append(curveParameters[1])
    except (RuntimeError, OptimizeWarning):
        # When a curve could not be fit (not a problem)
        pass

    # If no sinusoid is found, return a sine with an insignificant amplitude and phase zero
    # (it is still necessary to be a sine, for later processes)
    if len(sinusoids) == 0:
        sinusoids.append(sine(np.arange(width), width, 1, 0))
        phases.append(0)


def sine(x, width, a, b):
    return a * np.sin(b + x * (2 * np.pi / width))


def getTreatedUnwrapImageForSinusoidFinding(unwrapArray):
    unwrapImage = unwrapArrayToImage(unwrapArray)
    # We skip too low and too high intensity values, for better sinusoid finding
    unwrapImage[unwrapImage < 1800] = 1800
    unwrapImage[unwrapImage > 3000] = 3000
    unwrapImageTemp = normalize(unwrapImage)
    minValue = np.min(unwrapImage)
    unwrapImageUnsigned = (unwrapImage - minValue).astype(np.uint16)
    _, mask = cv2.threshold(
        unwrapImageTemp,
        np.min(unwrapImageTemp),
        np.max(unwrapImageTemp),
        cv2.THRESH_BINARY_INV,
    )
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=4)
    unwrapImageUnsigned = cv2.inpaint(unwrapImageUnsigned, mask, 10, cv2.INPAINT_TELEA)
    unwrapImage = unwrapImageUnsigned + minValue
    return unwrapImage


def unwrapArrayToImage(unwrapArray):
    return unwrapArray[::-1, 0, ::-1]


def normalize(image):
    normalizedImage = cv2.normalize(image, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_16S)
    return normalizedImage.astype(np.uint8)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("volume", type=sanitize_filepath_arg)
    parser.add_argument("sinusoidsStartingPositions", type=str)
    parser.add_argument("unwrapSinusoidsDataFile", type=sanitize_filepath_arg)
    args = parser.parse_args()

    volumePath = sanitize_file_path(args.volume)
    # Loading the volume nrrd file from disk
    storageNode = slicer.vtkMRMLNRRDStorageNode()
    storageNode.SetFileName(volumePath.as_posix())
    volume = mrml.vtkMRMLScalarVolumeNode()
    storageNode.ReadData(volume)

    # Retrieving the sinusoids suggested starting points
    sinusoidsStartingPositions = args.sinusoidsStartingPositions or ""
    sinusoidsStartingPositions = re.sub("[^0-9,.]", "", sinusoidsStartingPositions)
    sinusoidsStartingPositions = list(map(int, args.sinusoidsStartingPositions.split(",")))

    # Calculating the core geometry (core centers and radii)
    unwrapSinusoidsData = findUnwrapSinusoids(slicer.util.arrayFromVolume(volume), sinusoidsStartingPositions)

    # Saving result on disk
    unwrapSinusoidsDataFilePath = sanitize_file_path(args.unwrapSinusoidsDataFile)
    with open(unwrapSinusoidsDataFilePath.as_posix(), "wb") as f:
        f.write(pickle.dumps(unwrapSinusoidsData))
