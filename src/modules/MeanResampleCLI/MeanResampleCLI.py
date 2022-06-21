#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
import vtk, slicer, slicer.util, mrml
from ltrace.slicer.cli_utils import readFrom, writeDataInto
import numpy as np
from math import ceil
from itertools import product
from skimage.transform import resize


def single_channel_mean_resampling(source_array, scale):
    target_shape = []
    stride = []
    source_resamp_points = []
    target_points = []

    for i in range(len(source_array.shape)):
        target_shape.append(max(1, round(source_array.shape[i] * scale[i])))
        stride.append(int(source_array.shape[i] / target_shape[i]))

        crop_size = stride[i] * target_shape[i]
        init_point = (source_array.shape[i] - crop_size) // 2

        source_resamp_points.append(
            np.linspace(init_point, source_array.shape[i], target_shape[i] + 1)[:-1].astype(int)
        )
        target_points.append(np.arange(target_shape[i]))

    target_array = np.zeros(tuple(target_shape)).astype(source_array.dtype)
    source_resamp_coords = list(product(*source_resamp_points))
    target_coords = list(product(*target_points))

    for src_coord, tgt_coord in zip(source_resamp_coords, target_coords):
        window = tuple([slice(src_coord[i], src_coord[i] + stride[i]) for i in range(len(src_coord))])
        target_array[tgt_coord] = source_array[window].mean()

    return target_array


def mean_resampling(source_array, scale):
    if source_array.ndim == 3:
        return single_channel_mean_resampling(source_array, scale)

    n_channels = source_array.shape[-1]

    target_array = None
    for channel in range(n_channels):
        source_channel = single_channel_mean_resampling(source_array[:, :, :, channel], scale)
        source_channel = source_channel.reshape(*source_channel.shape, 1)
        if target_array is None:
            target_array = source_channel.copy()
        else:
            target_array = np.concatenate((target_array, source_channel), axis=-1)

    return target_array


def will_expand(scale):
    return any([dim_scale > 1.0 for dim_scale in scale])


def runcli(args):
    volume_type = mrml.vtkMRMLScalarVolumeNode if args.volume_type == "scalar" else mrml.vtkMRMLVectorVolumeNode
    input_volume = readFrom(args.input_volume, volume_type)

    input_spacing_xyz = input_volume.GetSpacing()
    output_spacing_xyz = list(map(float, args.output_spacing.split(",")))

    if not any(output_spacing_xyz):
        output_spacing_xyz = input_spacing_xyz
    else:
        assert all(
            output_spacing_xyz
        ), "0 spacing is only accepted if applied for all dimensions (input spacing is used in this case)"

    output_scale_zyx = [input_spacing_xyz[i] / output_spacing_xyz[i] for i in reversed(range(len(input_spacing_xyz)))]

    input_array = slicer.util.arrayFromVolume(input_volume)

    if will_expand(output_scale_zyx):
        # if any dimension will be upsampled, use linear interpolation instead
        output_shape = [max(1, round(input_array.shape[i] * output_scale_zyx[i])) for i in range(len(output_scale_zyx))]
        resampled_array = resize(input_array, output_shape, order=1, preserve_range=True).astype(input_array.dtype)
    else:
        resampled_array = mean_resampling(input_array, output_scale_zyx)

    writeDataInto(args.output_volume, resampled_array, volume_type, reference=input_volume, spacing=output_spacing_xyz)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--input_volume", type=str)
    parser.add_argument("--output_volume", type=str)
    parser.add_argument("--output_spacing", type=str)
    parser.add_argument("--volume_type", type=str, choices=["scalar", "vector"], default="scalar")
    parser.add_argument(
        "--returnparameterfile", type=str, default=None, help="File destination to store an execution outputs"
    )
    args = parser.parse_args()

    runcli(args)
