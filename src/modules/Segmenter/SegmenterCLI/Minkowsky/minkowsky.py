# -*- coding: utf-8 -*-
"""
Created on Sun Jul 12 14:48:23 2020
@author: Rafael Arenhart
"""

import os
import numpy as np
import sys
from numpy.lib.stride_tricks import sliding_window_view
from scipy.ndimage import zoom
from numba import njit


def interpolate_spline(output_shape, data):
    zoom_factor = np.array(output_shape) / np.delete(np.array(data.shape), -1)
    output = zoom(data, [*zoom_factor, 1], order=3, mode="nearest")

    return output


CURRENT_PATH = os.path.dirname(os.path.realpath(__file__))

isotropic_templates = np.zeros(256, dtype=np.uint8)
with open(os.path.join(CURRENT_PATH, "minkowsky_templates.csv"), mode="r") as file:
    for line in file:
        index, n, *templates = [int(i.strip()) for i in line.strip().split(",")]
        for template in templates:
            isotropic_templates[template] = index

indexing_template = np.zeros((2, 2, 2), dtype=np.uint8)
for i, j, k in [(a, b, c) for a in range(2) for b in range(2) for c in range(2)]:
    indexing_template[i, j, k] = 2 ** (i + 2 * j + 4 * k)

with open(os.path.join(CURRENT_PATH, "minkowsy_values.csv"), mode="r") as file:
    header = file.readline()
    if not header:
        raise ValueError("Missing header in minkowsy_values.csv")

    header = header.strip().split(",")
    minkowsky_names = [i.strip() for i in header[1:]]
    divisors = file.readline()
    if not divisors:
        raise ValueError("Missing divisors in minkowsy_values.csv")

    divisors = divisors.strip().split(",")
    minkowsky_divisors = np.array([int(i) for i in divisors[1:]], dtype=np.int8)
    minkowsky_values = np.zeros((22, 6), dtype=np.int64)
    for line in file:
        index, *vals = [int(i.strip()) for i in line.split(",")]
        minkowsky_values[index] = vals


@njit
def cube2index(img):
    return (img * indexing_template).sum()


def minkowsky_filter(img, kernel_size=3):
    padded_img = np.pad(img, kernel_size // 2, mode="reflect").astype(bool)
    x, y, z = padded_img.shape
    mink = np.zeros((*padded_img.shape, 6), dtype=np.float32)

    for i in range(x - 1):
        for j in range(y - 1):
            for k in range(z - 1):
                template_index = cube2index(padded_img[i : i + 2, j : j + 2, k : k + 2])
                minkowsky_template = isotropic_templates[template_index]
                mink[i, j, k, :] = minkowsky_values[minkowsky_template]

    if kernel_size == 1:
        return mink
    else:
        stride = np.ceil(kernel_size / 2).astype(int)
        output_shape = np.ceil(np.array(img.shape) / stride).astype(int)
        output = np.zeros((*output_shape, 6), dtype=np.float32)
        x, y, z = output_shape
        w = sliding_window_view(mink, [kernel_size, kernel_size, kernel_size, 1])
        w = np.squeeze(w)
        w = w[::stride, ::stride, ::stride, :]
        output = np.mean(w, axis=(4, 5, 6))

        return interpolate_spline(img.shape, output)


# Implementação 2d
isotropic_templates_2d = np.zeros(16, dtype=np.uint8)
with open(os.path.join(CURRENT_PATH, "minkowsky_templates_2d.csv"), mode="r") as file:
    for line in file:
        index, n, *templates = [int(i.strip()) for i in line.strip().split(",")]
        for template in templates:
            isotropic_templates_2d[template] = index

indexing_template_2d = np.zeros((2, 2), dtype=np.uint8)
for i, j in [(a, b) for a in range(2) for b in range(2)]:
    indexing_template_2d[i, j] = 2 ** (i + 2 * j)

with open(os.path.join(CURRENT_PATH, "minkowsy_values_2d.csv"), mode="r") as file:
    header = file.readline()
    if not header:
        raise ValueError("Missing header in minkowsy_values_2d.csv")

    header = header.strip().split(",")
    minkowsky_names = [i.strip() for i in header[1:]]
    divisors = file.readline()
    if not divisors:
        raise ValueError("Missing divisors in minkowsy_values_2d.csv")

    divisors = divisors.strip().split(",")
    minkowsky_divisors = np.array([int(i) for i in divisors[1:]], dtype=np.int8)
    minkowsky_values_2d = np.zeros((6, 4), dtype=np.int64)
    for line in file:
        index, *vals = [int(i.strip()) for i in line.split(",")]
        minkowsky_values_2d[index] = vals


@njit
def square2index(img):
    return (img * indexing_template_2d).sum()


def minkowsky_filter_2d(img, kernel_size=31):
    padded_img = np.pad(img, kernel_size // 2, mode="reflect").astype(bool)
    x, y = padded_img.shape
    mink = np.zeros((*padded_img.shape, 4), dtype=np.float32)

    for i in range(x - 1):
        for j in range(y - 1):
            template_index = square2index(padded_img[i : i + 2, j : j + 2])
            minkowsky_template = isotropic_templates_2d[template_index]
            mink[i, j, :] = minkowsky_values_2d[minkowsky_template]

    if kernel_size == 1:
        return mink
    else:
        stride = np.ceil(kernel_size / 2).astype(int)
        output_shape = np.ceil(np.array(img.shape) / stride).astype(int)
        output = np.zeros((*output_shape, 4), dtype=np.float32)
        x, y = output_shape
        w = sliding_window_view(mink, [kernel_size, kernel_size, 1])
        w = np.squeeze(w)
        output = np.mean(w[::stride, ::stride, :], axis=(3, 4))

        return interpolate_spline(img.shape, output)
