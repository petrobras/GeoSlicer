#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division

import numpy as np
from skimage.measure import label
import skimage.segmentation as seg
from recordtype import recordtype
from scipy import ndimage
from .inference import DWinference


def slice_division(shape, patch_dim):
    idx = []
    for i in shape:
        d = i // patch_dim
        r = i - (patch_dim * d)
        idx.append((d, r))
    return idx


def get_slices(shape, patch_dim, intersection):

    divisions = slice_division(shape, patch_dim)
    ix = []
    iy = []
    iz = []
    for i in range(divisions[0][0] + 1):
        ix.append(i * patch_dim)
    ix.append(shape[0])
    for j in range(divisions[1][0] + 1):
        iy.append(j * patch_dim)
    iy.append(shape[1])
    for k in range(divisions[2][0] + 1):
        iz.append(k * patch_dim)
    iz.append(shape[2])

    coords = []
    for i in range(len(ix[:-1])):
        for j in range(len(iy[:-1])):
            for k in range(len(iz[:-1])):
                ixi = max(ix[i] - intersection, 0)
                ixi1 = min(ix[i + 1] + intersection, shape[0])

                iyi = max(iy[j] - intersection, 0)
                iyi1 = min(iy[j + 1] + intersection, shape[1])

                izi = max(iz[k] - intersection, 0)
                izi1 = min(iz[k + 1] + intersection, shape[2])

                temp = np.s_[ixi:ixi1, iyi:iyi1, izi:izi1]
                coords.append(temp)
    return coords


def get_3ddepths(volume, base_volume, intersection, border):

    model = DWinference(mode="3D")
    results_patches = np.empty(volume.shape, dtype="float32")
    results_patches[:] = np.nan
    slices = get_slices(volume.shape, patch_dim=base_volume, intersection=intersection)
    total = len(slices)

    for i in range(total):

        img = volume[slices[i]]
        if len(img[img > 0]) / img.size < 0.05:
            depths = np.zeros(img.shape, dtype="float32")
        else:
            depths = model.run_model(img)
        depths = depths

        # removing border from the patch
        rm_border = border

        starts = [rm_border, rm_border, rm_border]
        stops = [-rm_border, -rm_border, -rm_border]

        for idx, j in enumerate(slices[i]):
            if j.start == 0:
                starts[idx] = 0

        for idx, j in enumerate(slices[i]):
            if j.stop == results_patches.shape[idx] or rm_border == 0:
                stops[idx] = depths.shape[idx]

        wout_border = np.s_[starts[0] : stops[0], starts[1] : stops[1], starts[2] : stops[2]]

        temp_depths_vsize = np.zeros(depths.shape, dtype="int8")
        temp_depths_vsize[wout_border] = 1
        depths[temp_depths_vsize == 0] = np.nan
        # end border removal

        # Adding new results, but averaging on intersections
        results_patches[slices[i]] = np.nanmean((results_patches[slices[i]], depths), axis=0)

        del (img, depths)

    return results_patches


def get_segmentation(image, threshold=0.05, label_background=0, label_pores=1):
    binary = np.where(image >= threshold, label_pores, label_background)
    binary = binary.astype("int8")
    return binary


def expand_depths(depths, background_threshold, split_threshold, volume=None):
    if volume is None:
        semantic = get_segmentation(depths, threshold=background_threshold)
    else:
        semantic = volume
    del volume
    segmented = label(get_segmentation(depths, threshold=split_threshold)).astype("int32")
    depths = (depths * 127).astype(np.int8)
    labeled_semantic = label(semantic).astype("int32")
    max_label = np.amax(segmented)
    objects = ndimage.find_objects(labeled_semantic)

    for i in range(len(objects)):
        slices = objects[i]
        roi_semantic = semantic[slices].copy()
        roi_segmented = segmented[slices].copy()
        if np.all(roi_segmented[labeled_semantic[slices] == i + 1] == 0):
            segmented[slices][labeled_semantic[slices] == i + 1] = max_label + 1
            max_label += 1
        else:
            wtd_mask = np.where(labeled_semantic[slices] == (i + 1), 1, 0)
            wtd_img = seg.watershed(
                -depths[slices] * wtd_mask.astype("int8"),
                roi_segmented * wtd_mask.astype("int8"),
                mask=roi_semantic * wtd_mask.astype(bool),
            )
            segmented[slices][labeled_semantic[slices] == i + 1] = wtd_img[labeled_semantic[slices] == i + 1]
            del wtd_mask, wtd_img

    return segmented


def get_2ddepths(volume):
    model = DWinference(mode="2D")
    log_depths = model.run_model(volume)
    return log_depths


def get_dwlabels(volume, base_volume=100, intersection=50, border=30, split_threshold=0.9, background_threshold=0.05):

    if volume.ndim == 3:
        depths_volume = get_3ddepths(volume * 1, base_volume, intersection, border)
        expanded_result = expand_depths(
            depths_volume, background_threshold=background_threshold, split_threshold=split_threshold, volume=volume * 1
        )
        del depths_volume, volume
        Results = recordtype("Results", [("im", None), ("dt", None), ("peaks", None), ("regions", None)])
        Results.regions = expanded_result
        return Results
    else:
        depths_volume = get_2ddepths(volume * 1)
        expanded_result = expand_depths(
            depths_volume, background_threshold=background_threshold, split_threshold=split_threshold, volume=volume * 1
        )
        expanded_result = expanded_result
        Results = recordtype("Results", [("im", None), ("dt", None), ("peaks", None), ("regions", None)])
        Results.regions = expanded_result
        return Results
