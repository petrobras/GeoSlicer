#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

from __future__ import print_function

import json
import math
import os
import sys
from pathlib import Path

import vtk
import vtk.util.numpy_support
import slicer
import slicer.util
import mrml

import monai
from monai.networks.nets import UNet
from monai.networks.layers import Norm
from monai.inferers import sliding_window_inference
from monai.utils import set_determinism
import numpy as np
from numpy.random import RandomState
import pickle
from PIL import Image
import torch
from monai.transforms import MapLabelValued

from ltrace import transforms

DEFAULT_SETTINGS = "settings.json"


from copy import deepcopy

from MonaiModelsLib.models.unet import UNetAct, UNetActWithBoundarySupervision

from MonaiModelsLib.transforms import (
    ComposedTransform,
    IdentityTransform,
    ReadNetCDFTransform,
    ReadFirstNetCDFVariableTransform,
    ToTensorTransform,
    QuantileTransform,
    QuantileDeformationTransform,
    ApplyPickledTransform,
    MultiChannelTransform,
    AddAxisTransform,
    SwapAxesTransform,
    PermuteTransform,
    ConcatenateTransform,
    RenameTransform,
    AddBinaryBoundaryMaskTransform,
    BinarizerTransform,
    ArgmaxTransform,
    MinMaxTransform,
    AddConstantTransform,
    get_torch_dtype,
    load_from_str,
    TakeChannelsTransform,
)


def make_get_object_by_name(*objects):
    def get_object_by_name(name):
        for obj in objects:
            if obj.__name__.lower() == name.lower():
                return obj
        raise Exception(f"{name} is not defined")

    return get_object_by_name


get_model = make_get_object_by_name(
    UNet,
    UNetAct,
    UNetActWithBoundarySupervision,
    # UNestPretrained,
)

get_transform = make_get_object_by_name(
    ComposedTransform,
    IdentityTransform,
    ReadNetCDFTransform,
    ReadFirstNetCDFVariableTransform,
    ToTensorTransform,
    QuantileTransform,
    QuantileDeformationTransform,
    ApplyPickledTransform,
    MultiChannelTransform,
    AddAxisTransform,
    SwapAxesTransform,
    PermuteTransform,
    ConcatenateTransform,
    RenameTransform,
    BinarizerTransform,
    ArgmaxTransform,
    MinMaxTransform,
    AddConstantTransform,
    AddBinaryBoundaryMaskTransform,
    TakeChannelsTransform,
    MapLabelValued,
)


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
    print(f"{dataVoxelArray.shape=}", 1)
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
            print(f"{dataVoxelArray.shape=}", 2)

        # reset the attribute dictionary, otherwise it will be transferred over
        attrs = vtk.vtkStringArray()
        nodeOut.GetAttributeNames(attrs)
        for i in range(0, attrs.GetNumberOfValues()):
            nodeOut.SetAttribute(attrs.GetValue(i), None)

    # reset the data array to force resizing, otherwise we will just keep the old data too
    nodeOut.SetAndObserveImageData(None)

    # print(nodeOut)

    # print(f"{dataVoxelArray.shape=}", 3)
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


def run_inference(saved_model: dict):
    """run inferece for a model"""

    title = saved_model["title"]
    config = saved_model["config"]
    meta = config["meta"]

    params = json.loads(args.xargs)
    if params["deterministic"]:
        set_determinism(seed=12345)
        np.random.seed(12345)

    model_name = config["model"]["name"]
    model_params = config["model"].get("params", {})
    model_state_dict = saved_model["model_state_dict"]
    model = get_model(model_name)(**model_params)
    model.load_state_dict(model_state_dict)

    transforms = config.get("transforms", {})
    pre_processing_transforms = transforms.get("pre_processing_transforms", [])
    post_processing_transforms = transforms.get("post_processing_transforms", [])

    pre_processing_transforms = ComposedTransform(
        [get_transform(t["name"])(**t["params"]) for t in pre_processing_transforms]
    )

    post_processing_transforms = ComposedTransform(
        [get_transform(t["name"])(**t["params"]) for t in post_processing_transforms]
    )

    is_segmentation_model = meta["is_segmentation_model"]
    model_spatial_dims = meta["spatial_dims"]
    input_roi_shape = meta["input_roi_shape"]

    inputs = meta["inputs"]
    pre_processed_inputs = meta.get("pre_processed_inputs", inputs)
    outputs = meta["outputs"]

    input_names = list(inputs.keys())
    pre_processed_input_names = list(pre_processed_inputs.keys())
    output_names = list(outputs.keys())

    # temporary limitation: only volume is fed to the model, only output is accepted
    pre_processed_input_name = pre_processed_input_names[0]
    output_name = output_names[0]

    # get volumes from arguments
    inputFiles = [file for file in (args.inputVolume, args.inputVolume1, args.inputVolume2) if file is not None]
    volumeNodes = [readFrom(file, mrml.vtkMRMLScalarVolumeNode) for file in inputFiles]

    sample = {}
    for v, volumeNode in enumerate(volumeNodes):
        input_name = input_names[v]
        description = inputs[input_name]
        spatial_dims = description.get("spatial_dims", 3)
        n_channels = description.get("n_channels", 1)

        vimage = volumeNode.GetImageData()
        nshape = tuple(reversed(volumeNode.GetImageData().GetDimensions()))
        narray = vtk.util.numpy_support.vtk_to_numpy(vimage.GetPointData().GetScalars())
        if narray.ndim == 1:
            shape = (*nshape, 1)
        else:
            shape = (*nshape, narray.shape[-1])

        narray = narray.reshape(shape)
        narray = np.moveaxis(narray, [0, 1, 2, 3], [1, 2, 3, 0])
        narray = narray[:n_channels]

        if spatial_dims == 2:
            dims = narray.shape[1:]
            depth_dim = np.argwhere(np.equal(dims, 1))[0].item()
            narray = np.squeeze(narray, axis=depth_dim + 1)

        sample[input_name] = torch.as_tensor(narray.astype(np.float32))

    is_segmentation_model = meta["is_segmentation_model"]
    model_spatial_dims = meta["spatial_dims"]
    input_roi_shape = meta["input_roi_shape"]

    inputs = meta["inputs"]
    pre_processed_inputs = meta.get("pre_processed_inputs", inputs)
    outputs = meta["outputs"]

    input_names = list(inputs.keys())
    pre_processed_input_names = list(pre_processed_inputs.keys())
    output_names = list(outputs.keys())

    # temporary limitation: only volume is fed to the model, only output is accepted
    pre_processed_input_name = pre_processed_input_names[0]
    output_name = output_names[0]

    # get volumes from arguments
    inputFiles = [file for file in (args.inputVolume, args.inputVolume1, args.inputVolume2) if file is not None]
    volumeNodes = [readFrom(file, mrml.vtkMRMLScalarVolumeNode) for file in inputFiles]

    sample = {}
    for v, volumeNode in enumerate(volumeNodes):
        input_name = input_names[v]
        description = inputs[input_name]
        spatial_dims = description.get("spatial_dims", 3)
        n_channels = description.get("n_channels", 1)

        vimage = volumeNode.GetImageData()
        nshape = tuple(reversed(volumeNode.GetImageData().GetDimensions()))
        narray = vtk.util.numpy_support.vtk_to_numpy(vimage.GetPointData().GetScalars())
        if narray.ndim == 1:
            shape = (*nshape, 1)
        else:
            shape = (*nshape, narray.shape[-1])

        narray = narray.reshape(shape)
        narray = np.moveaxis(narray, [0, 1, 2, 3], [1, 2, 3, 0])
        narray = narray[:n_channels]

        if spatial_dims == 2:
            dims = narray.shape[1:]
            depth_dim = np.argwhere(np.equal(dims, 1))[0].item()
            narray = np.squeeze(narray, axis=depth_dim + 1)

        sample[input_name] = torch.as_tensor(narray.astype(np.float32))

    sample = pre_processing_transforms(sample)
    # create batch dimension for prediction
    batch = {name: tensor[None, ...] for name, tensor in sample.items()}

    device = "cuda" if torch.cuda.is_available() else "cpu"
    for i in range(2):
        try:
            model.to(device)
            model.eval()
            with torch.no_grad():
                batched_output = {
                    output_name: sliding_window_inference(
                        inputs=batch[pre_processed_input_name],
                        roi_size=input_roi_shape,
                        predictor=model,
                        geoslicer_progress=True,
                        sw_batch_size=1,
                        sw_device=device,
                    ),
                }
                batched_output = post_processing_transforms(batched_output)
                batched_inference = batched_output[output_name]
            break
        except RuntimeError as e:
            print(e)
            print("PyTorch is not able to use GPU: falling back to CPU.")
            device = "cpu"

    # remove batch and channel dimensions
    output = batched_inference.detach().numpy()[0, 0]

    if model_spatial_dims == 2:
        output = np.expand_dims(output, depth_dim)

    return output, volumeNodes


def runcli(args):
    """Read input volumes"""
    saved_model = torch.load(args.inputmodel, map_location="cuda" if torch.cuda.is_available() else "cpu")

    # Composed model
    if "models_to_compose" in saved_model.keys():
        inferences = []
        models = saved_model["models_to_compose"]

        for model_key in models:
            infernece, volumeNodes = run_inference(models[model_key])
            inferences.append(infernece)

        output = np.zeros_like(inferences[0])

        for combination_rule in saved_model["config"]["inference_combination"]:
            model_index = combination_rule["model_index"]
            values_to_take = combination_rule["take"]

            for take_class_value in values_to_take:
                output[np.where(inferences[model_index] == take_class_value)] = take_class_value

    # Single model
    else:
        output, volumeNodes = run_inference(saved_model)

    writeDataInto(args.outputVolume, output, mrml.vtkMRMLLabelMapVolumeNode, reference=volumeNodes[0])


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
        type=str,
        help="Input model text file",
    )

    args = parser.parse_args()

    runcli(args)

    print("Done")
