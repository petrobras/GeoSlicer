#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

import vtk
import mrml

import slicer
import slicer.util
import numpy as np
from ltrace import transforms
import SimpleITK as sitk

from ltrace.transforms import clip_to
from ltrace.slicer.helpers import getVolumeNullValue, setVolumeNullValue


def get_origin(data, node, rasbounds, kij=False):
    boundsijk = get_ijk_from_ras_bounds(data, node, rasbounds, kij)
    min_ijk = np.min(boundsijk, axis=0)
    origin_ijk = np.repeat(min_ijk[np.newaxis, :], 2, axis=0)
    volumeIJKToRASMatrix = vtk.vtkMatrix4x4()
    node.GetIJKToRASMatrix(volumeIJKToRASMatrix)
    origin_ras = transforms.transformPoints(volumeIJKToRASMatrix, origin_ijk)
    return origin_ras[0, :]


def get_ijk_from_ras_bounds(node, rasbounds):
    volumeRASToIJKMatrix = vtk.vtkMatrix4x4()
    node.GetRASToIJKMatrix(volumeRASToIJKMatrix)
    # reshape bounds for a matrix of 3 collums and 2 rows
    rasbounds = np.array([[rasbounds[0], rasbounds[2], rasbounds[4]], [rasbounds[1], rasbounds[3], rasbounds[5]]])
    boundsijk = np.ceil(transforms.transformPoints(volumeRASToIJKMatrix, rasbounds, returnInt=False)).astype(np.float32)
    return boundsijk


def readFrom(volumeFile, builder):
    sn = slicer.vtkMRMLNRRDStorageNode()
    sn.SetFileName(volumeFile)
    nodeIn = builder()
    sn.ReadData(nodeIn)  # read data from volumeFile into nodeIn
    return nodeIn


def writeDataInto(volumeFile, dataVoxelArray, builder, reference=None, cropping_ras_bounds=None, kij=False):
    sn_out = slicer.vtkMRMLNRRDStorageNode()
    sn_out.SetFileName(volumeFile)
    nodeOut = builder()

    if reference:
        # copy image information
        nodeOut.Copy(reference)
        if cropping_ras_bounds is not None:
            # volume is cropped, move the origin to the min of the bounds
            crop_origin = get_origin(dataVoxelArray, reference, cropping_ras_bounds, kij)
            nodeOut.SetOrigin(crop_origin)

        # reset the attribute dictionary, otherwise it will be transferred over
        attrs = vtk.vtkStringArray()
        nodeOut.GetAttributeNames(attrs)
        for i in range(0, attrs.GetNumberOfValues()):
            nodeOut.SetAttribute(attrs.GetValue(i), None)

    # reset the data array to force resizing, otherwise we will just keep the old data too
    nodeOut.SetAndObserveImageData(None)
    slicer.util.updateVolumeFromArray(nodeOut, dataVoxelArray)
    nodeOut.Modified()

    sn_out.WriteData(nodeOut)


def runcli(args):
    # Read input volumes
    inputVolumeFile = args.inputVolume
    inputMaskFile = args.inputMask
    inputShadingMaskFile = args.inputShadingMask
    ballRadius = args.ballRadius

    inputVolumeNode = readFrom(inputVolumeFile, mrml.vtkMRMLScalarVolumeNode)
    inputMaskNode = readFrom(inputMaskFile, mrml.vtkMRMLLabelMapVolumeNode)
    inputShadingMaskNode = readFrom(inputShadingMaskFile, mrml.vtkMRMLLabelMapVolumeNode)

    volumeArray = slicer.util.arrayFromVolume(inputVolumeNode)
    maskArray = slicer.util.arrayFromVolume(inputMaskNode)
    shadingMaskArray = slicer.util.arrayFromVolume(inputShadingMaskNode)

    ### OPTION 1 ###
    ## Compute background image by trundating the thresholds with the mean value of the shading area
    mean_shading_area = np.mean(volumeArray[shadingMaskArray == 1])
    background = np.ones_like(volumeArray)
    background[shadingMaskArray == 0] = mean_shading_area
    background[maskArray == 0] = mean_shading_area
    background[shadingMaskArray == 1] = volumeArray[shadingMaskArray == 1]
    img = sitk.GetImageFromArray(background)
    gaussian = sitk.SmoothingRecursiveGaussianImageFilter()
    gaussian.SetSigma(float(ballRadius))
    img = gaussian.Execute(img)
    background = sitk.GetArrayFromImage(img)
    # background = scipy.ndimage.gaussian_filter(background, ballRadius, order=0, output=None, mode='reflect', cval=0.0, truncate=4.0)

    ### OPTION 2 ###
    ## Compute background image by trundating the thresholds with the threshold values
    # limit_min = volumeArray[shadingMaskArray==1].min()
    # limit_max = volumeArray[shadingMaskArray==1].max()
    # background = np.ones_like(volumeArray)
    # background[volumeArray<=limit_min] = limit_min
    # background[volumeArray>=limit_max] = limit_max
    # background[shadingMaskArray==1] = volumeArray[shadingMaskArray==1]
    # background = scipy.ndimage.gaussian_filter(background, ballRadius, order=0, output=None, mode='reflect', cval=0.0, truncate=4.0)

    # Apply
    corrected_data = volumeArray.astype(float) - background
    corrected_data = corrected_data - np.mean(corrected_data[maskArray == 1]) + np.mean(volumeArray[maskArray == 1])

    input_null_value = getVolumeNullValue(inputVolumeNode)
    output_null_value = input_null_value if input_null_value != None else 0
    corrected_data[maskArray == 0] = output_null_value

    writeDataInto(
        args.outputVolume,
        corrected_data,
        mrml.vtkMRMLScalarVolumeNode,
        reference=inputVolumeNode,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--master", type=str, dest="inputVolume", default=None, help="Intensity Input Values")
    parser.add_argument("--mask", type=str, dest="inputMask", default=None, help="Intensity Input Values")
    parser.add_argument("--smask", type=str, dest="inputShadingMask", default=None, help="Intensity Input Values")
    parser.add_argument("--radius", type=int, dest="ballRadius", default=None, help="Labels Input (3d) Values")
    parser.add_argument(
        "--outputvolume", type=str, dest="outputVolume", default=None, help="Output labelmap (3d) Values"
    )

    args = parser.parse_args()

    runcli(args)

    print("Done")
