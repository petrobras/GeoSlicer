#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
import vtk, slicer, slicer.util, mrml

import ctypes
import json
import math
import multiprocessing
import time

import numpy as np
import scipy

from ltrace.algorithms.Variogram_FFT.variogram import VariogramFFT
from ltrace.slicer.cli_utils import writeDataInto, readFrom, progressUpdate
from ltrace.algorithms.CorrelationDistance import common


class CorrelationDistance:
    @staticmethod
    def calculate_correlation(data, spacing, kernel_input, unit_input, initial_progress=0, final_progress=1):
        """Calculate correlation distance of a data

        Args:
            data (np.array): input data
            spacing (tuple): data's pixel spacing
            kernel_input (tuple): shape of the kernel that will go through the data
            unit_input (tuple): shape of the output granularity. It determines the output resolution
            initial_progress (float): cli progress will be set to this value in the beggining
            final_progress (float): cli progess wil be at this value at the end

        Returns:
            np.array: volume with correlation distance result
            tuple: spacing of the resulting volume
        """
        start = time.time()

        kernel_input = np.round(kernel_input)
        unit_input = np.round(unit_input)
        if not (unit_input < data.shape).all():
            raise RuntimeError("feature_cli: error: unit must be smaller than data shape")
        if not (kernel_input > unit_input).all():
            raise RuntimeError("feature_cli: error: kernel must be bigger than unit")

        maximum_number_of_processes = multiprocessing.cpu_count() - 1
        padding_size = math.ceil(np.max(kernel_input) / 2) - math.floor(np.min(unit_input) / 2)
        padded_data = np.pad(data, padding_size, mode="reflect")
        divisor = math.ceil((maximum_number_of_processes) ** (1 / 3))

        progress_value_list = []
        multi_proc_manager = multiprocessing.Manager()
        arguments = []
        subvolumes_dimensions = common.get_subvolumes_dimensions(data, unit_input, divisor)
        print("feature_cli: volume divided into {} parts".format(len(subvolumes_dimensions)))
        output_subvolumes_slices = []
        for slices in subvolumes_dimensions:
            padded_slices = common.add_padding_to_slices(slices, [padding_size] * len(slices))
            subvolume = padded_data[padded_slices]
            progress_value = multi_proc_manager.Value(ctypes.c_int, 0)
            progress_value_list.append(progress_value)
            unpadded_shape = np.array(subvolume.shape) - 2 * padding_size
            output_subvolume_shape = tuple(unpadded_shape // np.array(unit_input))
            arguments.append(
                (
                    subvolume,
                    padding_size,
                    spacing,
                    kernel_input,
                    unit_input,
                    output_subvolume_shape,
                    progress_value,
                )
            )
            output_subvolumes_slices.append(common.divide_slices_according_to_unit(slices, unit_input))

        progress_interval = final_progress - initial_progress
        progress_multiplier = progress_interval / (len(progress_value_list) * 100.0)
        number_of_processes = min(maximum_number_of_processes, len(subvolumes_dimensions))
        print("feature_cli: using {} processes".format(number_of_processes))
        with multiprocessing.Pool(number_of_processes) as pool:
            pool_result = pool.starmap_async(CorrelationDistance.internal_calculate_correlation, arguments)
            while not pool_result.ready():
                progress_to_display = 0
                for progress_value in progress_value_list:
                    progress_to_display += progress_value.value
                progressUpdate(value=initial_progress + (progress_to_display * progress_multiplier))
                pool_result.wait(2)
            subvolumes_correlations = pool_result.get()

        output_shape = np.array(data.shape) // np.array(unit_input)
        output_correlation = np.empty(output_shape)
        subvolume_index = 0
        for slices in output_subvolumes_slices:
            output_correlation[slices] = subvolumes_correlations[subvolume_index]
            subvolume_index += 1

        end = time.time()
        print("feature_cli: elapsed time: ", end - start)

        input_spacing = spacing
        spacing = ()
        for i in range(len(input_spacing)):
            spacing += (input_spacing[i] * unit_input[i],)

        return output_correlation, spacing

    @staticmethod
    def internal_calculate_correlation(
        clipped_data,
        padding_size,
        spacing,
        kernel_input,
        unit_input,
        output_shape,
        progress_value,
    ):
        data_shape = clipped_data.shape

        feature_CorrLenght = np.empty(output_shape)
        progress_to_display = 0

        for (
            input_indexes,
            output_position,
            progress,
        ) in common.calculate_process_indexes(padding_size, kernel_input, unit_input, output_shape):
            input_slice = CorrelationDistance.__create_array_slice(input_indexes)
            feature_CorrLenght[tuple(output_position)] = VariogramFFT._calculate_feature(
                clipped_data[input_slice], spacing
            )
            if progress > progress_to_display:
                progress_to_display = math.ceil(progress)
                progress_value.value = progress_to_display

        return feature_CorrLenght

    @staticmethod
    def __create_array_slice(indexes):
        slices = ()
        for index in indexes:
            slices += (slice(*index),)
        return slices


def interpolate_linear(output_shape, output_spacing, data):
    z = np.linspace(0, output_shape[0] - 1, data.shape[0])
    y = np.linspace(0, output_shape[1] - 1, data.shape[1])
    x = np.linspace(0, output_shape[2] - 1, data.shape[2])
    interpolating_function = scipy.interpolate.RegularGridInterpolator((z, y, x), data)

    z = np.linspace(0, output_shape[0] - 1, output_shape[0])
    y = np.linspace(0, output_shape[1] - 1, output_shape[1])
    x = np.linspace(0, output_shape[2] - 1, output_shape[2])
    k, j, i = np.meshgrid(z, y, x)

    points = np.column_stack((k.ravel(), j.ravel(), i.ravel()))
    pressure = interpolating_function(points)
    del points

    output = np.empty(output_shape)
    output[k.ravel().astype(int), j.ravel().astype(int), i.ravel().astype(int)] = pressure
    return output, output_spacing


def interpolate_spline(output_shape, output_spacing, data):
    zoom_factor = (np.array(output_shape) / np.array(data.shape)).min()
    output = scipy.ndimage.zoom(data, zoom_factor, order=3, mode="nearest")

    return output, output_spacing


def interpolate_slinear(output_shape, output_spacing, data):
    z = np.linspace(0, output_shape[0] - 1, data.shape[0])
    y = np.linspace(0, output_shape[1] - 1, data.shape[1])
    x = np.linspace(0, output_shape[2] - 1, data.shape[2])
    interpolating_function = scipy.interpolate.RegularGridInterpolator((z, y, x), data, method="slinear")

    z = np.linspace(0, output_shape[0] - 1, output_shape[0])
    y = np.linspace(0, output_shape[1] - 1, output_shape[1])
    x = np.linspace(0, output_shape[2] - 1, output_shape[2])
    k, j, i = np.meshgrid(z, y, x)

    points = np.column_stack((k.ravel(), j.ravel(), i.ravel()))
    k_coords = k.ravel().astype(int)
    j_coords = j.ravel().astype(int)
    i_coords = i.ravel().astype(int)
    output = np.empty(output_shape)

    for index in range(0, len(points), 50):
        interp_slice = slice(index, index + 50)
        pressure = interpolating_function(points[interp_slice])
        output[k_coords[interp_slice], j_coords[interp_slice], i_coords[interp_slice]] = pressure

    del points
    return output, output_spacing
