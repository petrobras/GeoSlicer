#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

from __future__ import print_function

import json
import math
import os
import sys
from pathlib import Path

import vtk
import slicer
import slicer.util
import mrml

import itertools
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy.ndimage import zoom
from scipy.signal import fftconvolve
from sklearn.preprocessing import QuantileTransformer

from ltrace import transforms

from torch import load as torch_load
from PIL import Image


def progressUpdate(value):
    print(f"<filter-progress>{value}</filter-progress>")
    sys.stdout.flush()


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


def get_ijk_from_ras_bounds(node, rasbounds):
    volumeRASToIJKMatrix = vtk.vtkMatrix4x4()
    node.GetRASToIJKMatrix(volumeRASToIJKMatrix)
    # reshape bounds for a matrix of 3 collums and 2 rows
    rasbounds = np.array([[rasbounds[0], rasbounds[2], rasbounds[4]], [rasbounds[1], rasbounds[3], rasbounds[5]]])
    boundsijk = np.ceil(transforms.transformPoints(volumeRASToIJKMatrix, rasbounds, returnInt=False)).astype(int)
    return boundsijk


def crop_to_rasbounds(data, node, rasbounds, rgb=False):
    boundsijk = get_ijk_from_ras_bounds(node, rasbounds)
    if rgb:
        boundsijk[:, 0] = [0, 3]
    arr, _ = transforms.crop_to_selection(data, np.fliplr(boundsijk))  # crop without copying
    return arr


def get_origin(data, node, rasbounds, kij=False):
    boundsijk = get_ijk_from_ras_bounds(data, node, rasbounds, kij)
    min_ijk = np.min(boundsijk, axis=0)
    origin_ijk = np.repeat(min_ijk[np.newaxis, :], 2, axis=0)
    volumeIJKToRASMatrix = vtk.vtkMatrix4x4()
    node.GetIJKToRASMatrix(volumeIJKToRASMatrix)
    origin_ras = transforms.transformPoints(volumeIJKToRASMatrix, origin_ijk)
    return origin_ras[0, :]


def adjustbounds(volume, bounds):
    new_bounds = np.zeros(6)
    volume.GetRASBounds(new_bounds)
    # intersect bounds by getting max of lower bounds and min of upper
    new_bounds[0::2] = np.maximum(new_bounds[0::2], bounds[0::2])  # max of lower bounds
    new_bounds[1::2] = np.minimum(new_bounds[1::2], bounds[1::2])  # min of upper bounds
    return new_bounds


##
def calculate_cov_matrices(img, annotations, kernel_size=9):
    considered_segments = np.unique(annotations[1])
    padded_img = np.pad(img, pad_width=(kernel_size - 1) // 2, mode="reflect")

    mean = np.empty(len(considered_segments))
    cov = np.empty((len(considered_segments), kernel_size**img.ndim, kernel_size**img.ndim), np.float64)
    w = np.lib.stride_tricks.sliding_window_view(padded_img, [kernel_size] * padded_img.ndim)
    for idx, seg in enumerate(considered_segments):
        segment = tuple(annotations[0][annotations[1] == seg].T)
        mu = np.mean(img[segment])
        n_pixels = np.product(img[segment].shape)

        D = w[segment].reshape(n_pixels, -1) - mu
        cov[idx, ...] = np.cov(D.T)
        mean[idx] = mu
        del D

    return cov, mean


# stencil mask operations
def create_stencil_mask(dim, stencil, kernel_size):
    if dim == 2:
        if stencil == "planes" or stencil == "cubes":
            A = np.ones([kernel_size] * dim, dtype=bool)
        elif stencil == "axes":
            A = np.zeros([kernel_size] * dim, dtype=bool)
            A[kernel_size // 2, :] = 1
            A[:, kernel_size // 2] = 1
    elif dim == 3:
        if stencil == "cubes":
            A = np.ones([kernel_size] * dim, dtype=bool)
        elif stencil == "planes":
            A = np.zeros([kernel_size] * dim, dtype=bool)
            A[kernel_size // 2, :, :] = 1
            A[:, kernel_size // 2, :] = 1
            A[:, :, kernel_size // 2] = 1
        elif stencil == "axes":
            A = np.zeros([kernel_size] * dim, dtype=bool)
            A[kernel_size // 2, kernel_size // 2, :] = 1
            A[:, kernel_size // 2, kernel_size // 2] = 1
            A[kernel_size // 2, :, kernel_size // 2] = 1
    A = A.ravel()

    return A


def bayesian_inference(img, considered_segments, mean, cov, stride, stencil="axes", unsafe_memory_opt=False):
    kernel_size = np.ceil(np.power(cov[0].shape[0], 1.0 / img.ndim)).astype(int)
    kernel_radius = (int(kernel_size - 1) // 2,) * img.ndim

    # use fftconvolve
    if img.ndim == 2 and stride == 1 and kernel_size > 50 and stencil == "cubes":
        logdet = []
        Sigma_inv = []
        for m in range(len(considered_segments)):
            logdet.append(np.linalg.slogdet(cov[m])[1])
            Sigma_inv.append(np.linalg.inv(cov[m]).reshape((kernel_size**2, kernel_size, kernel_size)))

        P = []
        for m in range(len(considered_segments)):
            segment = tuple(annotations[0][annotations[1] == considered_segments[m]].T)
            mu = float(img[segment].mean())

            Pm = np.zeros_like(img)
            for i in range(Sigma_inv[m].shape[0]):
                conv = fftconvolve(img - mu, Sigma_inv[m][i], mode="same")

                img_shift = np.roll(
                    img, (i // kernel_size - kernel_size // 2, i % kernel_size - kernel_size // 2), (0, 1)
                )
                Pm[...] = Pm + (img_shift - mu) * conv

            Pm = -Pm / 2.0 - logdet[m] / 2.0
            P.append(Pm)

        P = np.array(P)
    else:
        A = create_stencil_mask(img.ndim, stencil, kernel_size)

        cov = cov[:, A == True, :][:, :, A == True] + 0.001 * np.eye(sum(A))
        cov_inv = np.array([np.linalg.inv(cov[m]) for m in range(len(considered_segments))])

        logdet = np.array([np.linalg.slogdet(cov[m])[1] for m in range(len(considered_segments))])

        padded_img = np.pad(img, pad_width=(kernel_size - 1) // 2, mode="reflect")

        if unsafe_memory_opt:
            P = np.zeros((len(considered_segments),) + tuple(np.ceil(np.array(img.shape) / stride).astype(int)))
            for m in range(len(considered_segments)):
                w = sliding_window_view(padded_img - mean[m], [kernel_size] * padded_img.ndim)
                if img.ndim == 2:
                    w = w[::stride, ::stride]
                else:
                    w = w[::stride, ::stride, ::stride]

                w = w.reshape(np.prod(w.shape[: img.ndim]), np.prod(w.shape[img.ndim :])).T
                w = w[A == True]

                P[m, ...] = ((-np.sum(w * (cov_inv[m] @ w), axis=0) - logdet[m]) / 2.0).reshape(
                    np.ceil(np.array(img.shape) / stride).astype(int)
                )
        else:
            grid = np.mgrid[[slice(0, img.shape[dim], stride) for dim in range(img.ndim)]]
            points_inf = grid.reshape(grid.shape[0], -1).T
            points_inf_stride = points_inf // stride

            P = np.zeros((len(considered_segments),) + tuple(np.ceil(np.array(img.shape) / stride).astype(int)))
            for m in range(len(considered_segments)):
                w = sliding_window_view(padded_img - mean[m], [kernel_size] * padded_img.ndim)
                for i in range(len(points_inf)):
                    x = w[tuple(points_inf[i])].ravel()
                    x = x[A == True]

                    P[m][tuple(points_inf_stride[i])] = (-np.sum(x * (cov_inv[m] @ x), axis=0) - logdet[m]) / 2.0

    return P


def interpolate_spline(output_shape, data):
    zoom_factor = np.array(output_shape) / np.array(data.shape)
    output = zoom(data, zoom_factor, order=3, mode="nearest")

    return output


def gaussian_taper(is_2d, cov, kernel_size, desv_pad=10):
    ndim = 2 if is_2d else 3

    w = np.zeros(cov[0].shape)
    for i, j in itertools.product(range(w.shape[0]), range(w.shape[1])):
        indexes = np.unravel_index([i, j], [kernel_size] * ndim)
        distance = np.sqrt(np.sum([np.subtract(*axis) ** 2 for axis in indexes]))
        w[i, j] = np.exp(-np.power(distance, 2.0) / (2 * np.power(desv_pad, 2.0)))

    for m in range(cov.shape[0]):
        cov[m, ...] = w * cov[m]


def runcli(args):
    """Read input volumes"""
    inputFiles = [file for file in (args.inputVolume, args.inputVolume1, args.inputVolume2) if file is not None]
    volumeNodes = [readFrom(file, mrml.vtkMRMLScalarVolumeNode) for file in inputFiles]

    intersect_bounds = np.zeros(6)
    volumeNodes[0].GetRASBounds(intersect_bounds)
    """ Found commmon boundaries to align inputs """
    for ith in range(1, len(volumeNodes)):
        intersect_bounds = adjustbounds(volumeNodes[ith], intersect_bounds)

    channels = [slicer.util.arrayFromVolume(volume) for volume in volumeNodes]
    ctypes = args.ctypes.split(",")

    if len(channels) > 1:
        """Crop volumes using common boundaries"""
        for i in range(len(channels)):
            channels[i] = crop_to_rasbounds(channels[i], volumeNodes[i], intersect_bounds, rgb=ctypes[i] == "rgb")

    for i in range(len(channels)):
        if ctypes[i] == "rgb":
            image_hsv = Image.fromarray(channels[i]).convert("HSV")
            channels[i] = np.array(image_hsv)

    ref_shape = np.array([1, *channels[0].shape[:2]]) if ctypes[0] == "rgb" else np.array(channels[0].shape)
    valid_axis = np.squeeze(np.argwhere(ref_shape > 1))
    is_2d = np.any(ref_shape == 1)
    ndim = len(valid_axis)

    progressUpdate(0.00001)
    for i in range(len(channels)):
        channels[i] = np.squeeze(channels[i])

        if ctypes[i] != "rgb":
            channels[i] = (
                QuantileTransformer(n_quantiles=1000, output_distribution="normal")
                .fit_transform(channels[i].ravel().reshape(-1, 1))
                .reshape(channels[i].shape)
            )

        progressUpdate(i / len(channels) / 3.0)

    if args.inputModel:
        model = torch_load(args.inputModel)

        params = model["config"]["model"]["params"]
        kernel_size = params["kernel_size"]
        stride = np.ceil(kernel_size / 2).astype(int)
        stencil = params["kernel_type"]

        model_outputs = model["config"]["meta"]["outputs"]
        model_output_names = list(model_outputs.keys())
        model_output = model_outputs[model_output_names[0]]
        unsafe_memory_opt = True

        mean = params["mean"]
        cov = params["cov"]

        considered_segments = range(len(mean))

        if not kernel_size % 2:
            kernel_size += 1

        P_shape = np.ceil(np.array(ref_shape[valid_axis]) / stride).astype(int)
        P = np.zeros((len(considered_segments),) + tuple(P_shape))
        for i, feature in enumerate(channels):
            if ctypes[i] == "rgb":
                for j in range(feature.shape[-1]):
                    P[...] = P + bayesian_inference(
                        feature[..., j],
                        considered_segments,
                        mean[:, j, ...],
                        cov[:, j, ...],
                        stride,
                        stencil,
                        unsafe_memory_opt,
                    )
                    progressUpdate(
                        1.0 / 3.0 + float(i * feature.shape[-1] + j) / (len(channels) * feature.shape[-1]) / 3.0
                    )
            else:
                P[...] = P + bayesian_inference(
                    feature, considered_segments, mean, cov, stride, stencil, unsafe_memory_opt
                )
                progressUpdate(1.0 / 3.0 + float(i) / len(channels) / 3.0)
    else:
        labelsNode = readFrom(args.labelVolume, mrml.vtkMRMLLabelMapVolumeNode)
        labelsArray = np.squeeze(slicer.util.arrayFromVolume(labelsNode)).astype(np.int32)
        locations = labelsArray[:, valid_axis]
        labels = labelsArray[:, -1]
        annotations = locations, labels

        params = json.loads(args.xargs)
        kernel_size = params["kernel"]
        stride = params["stride"]
        stencil = params["kernel_type"]

        if not kernel_size % 2:
            kernel_size += 1

        considered_segments = np.unique(annotations[1])

        P_shape = np.ceil(np.array(ref_shape[valid_axis]) / stride).astype(int)
        P = np.zeros((len(considered_segments),) + tuple(P_shape))
        for i, feature in enumerate(channels):
            if ctypes[i] == "rgb":
                for j in range(feature.shape[-1]):
                    covariance, mean = calculate_cov_matrices(feature[..., j], annotations, kernel_size)
                    progressUpdate(
                        1.0 / 3.0 + 0.5 * float(i * feature.shape[-1] + j) / (len(channels) * feature.shape[-1]) / 3.0
                    )

                    # Pos-processamento da matrix covariancia
                    gaussian_taper(is_2d, covariance, kernel_size, desv_pad=kernel_size / 5)

                    unsafe_memory_opt = params["unsafe_memory_opt"]
                    P[...] = P + bayesian_inference(
                        feature[..., j], considered_segments, mean, covariance, stride, stencil, unsafe_memory_opt
                    )
                    progressUpdate(
                        1.0 / 3.0 + float(i * feature.shape[-1] + j) / (len(channels) * feature.shape[-1]) / 3.0
                    )
            else:
                covariance, mean = calculate_cov_matrices(feature, annotations, kernel_size)
                progressUpdate(1.0 / 3.0 + 0.5 * float(i) / len(channels) / 3.0)

                # Pos-processamento da matrix covariancia
                if kernel_size > 10:
                    gaussian_taper(is_2d, covariance, kernel_size, desv_pad=kernel_size / 5)

                unsafe_memory_opt = params["unsafe_memory_opt"]
                P[...] = P + bayesian_inference(
                    feature, considered_segments, mean, covariance, stride, stencil, unsafe_memory_opt
                )
                progressUpdate(1.0 / 3.0 + float(i) / len(channels) / 3.0)

    progressUpdate(2.0 / 3.0)

    # Interpolação das probabilidades
    if ctypes[i] == "rgb":
        Pint = np.zeros(
            (len(considered_segments),) + tuple(np.array(np.delete(channels[0].shape, -1))[:ndim].astype(int))
        )
        for m, seg in enumerate(considered_segments):
            Pint[m] = interpolate_spline(np.delete(channels[0].shape, -1), P[m])
    else:
        Pint = np.zeros((len(considered_segments),) + tuple(np.array(channels[0].shape)[:ndim].astype(int)))
        for m, seg in enumerate(considered_segments):
            Pint[m] = interpolate_spline(channels[0].shape, P[m])

    # Configura o output 2d
    if is_2d:
        axis = np.delete(np.arange(3), valid_axis)[0] + 1
        Pint = np.expand_dims(Pint, axis=axis)

    progressUpdate(3.0 / 3.0)

    seg_inf = np.argmax(Pint, axis=0).astype(float) + 1

    if args.inputModel:
        considered_segments = model_output["class_indices"]

        seg_mapped = np.zeros_like(seg_inf)
        for m, seg in enumerate(considered_segments):
            seg_mapped[seg_inf == seg] = seg
        seg_inf = seg_mapped

    writeDataInto(args.outputVolume, seg_inf, mrml.vtkMRMLLabelMapVolumeNode, reference=volumeNodes[0])


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--master", type=str, dest="inputVolume", default=None, help="Intensity Input Values")
    parser.add_argument("--extra1", type=str, dest="inputVolume1", default=None, help="Intensity Input Values")
    parser.add_argument("--extra2", type=str, dest="inputVolume2", default=None, help="Intensity Input Values")
    parser.add_argument("--labels", type=str, dest="labelVolume", default=None, help="Labels Input (3d) Values")
    parser.add_argument(
        "--outputvolume", type=str, dest="outputVolume", default=None, help="Output labelmap (3d) Values"
    )
    parser.add_argument("--xargs", type=str, default="", help="Model configuration string")
    parser.add_argument("--ctypes", type=str, default="", help="Input Color Types")
    parser.add_argument("--returnparameterfile", type=str, help="File destination to store an execution outputs")
    parser.add_argument(
        "--inputmodel",
        type=argparse.FileType("rb"),
        dest="inputModel",
        default=None,
        help="Input model file",
    )

    args = parser.parse_args()
    runcli(args)

    print("Done")
