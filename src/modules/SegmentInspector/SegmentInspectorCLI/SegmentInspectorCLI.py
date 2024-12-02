#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

from __future__ import print_function

import itertools
import json

from collections import defaultdict
from pathlib import Path
import time

import scipy.ndimage as spim

import numba
import numpy as np
import pandas as pd

import vtk
import slicer
import slicer.util
import mrml
import sys
import os
import gc

from ltrace import transforms
from ltrace.algorithms import partition
from ltrace.algorithms.measurements import (
    LabelStatistics2D,
    calculate_statistics_on_segments,
    LabelStatistics3D,
    PORE_SIZE_CATEGORIES,
)
from ltrace.pore_networks.generalized_network_extractor import generate_pore_network_label_map
from ltrace.slicer.cli_utils import progressUpdate, readFrom, writeDataInto
from ltrace.slicer.throat_analysis.throat_analysis import ThroatAnalysis
from ltrace.slicer.volume_operator import VolumeOperator, SegmentOperator

from DeepWatershedLib import deepwatershed

DEFAULT_SETTINGS = "settings.json"


def getIJKSpacing(node):
    return np.flip([i for i in node.GetSpacing()])


def get_ijk_from_ras_bounds(data, node, rasbounds, kij=False):
    volumeRASToIJKMatrix = vtk.vtkMatrix4x4()
    node.GetRASToIJKMatrix(volumeRASToIJKMatrix)
    # reshape bounds for a matrix of 3 collums and 2 rows
    rasbounds = np.array([[rasbounds[0], rasbounds[2], rasbounds[4]], [rasbounds[1], rasbounds[3], rasbounds[5]]])

    boundsijk = transforms.transformPoints(volumeRASToIJKMatrix, rasbounds, returnInt=True)

    return boundsijk


@numba.jit(nopython=True)
def mergebins(*bins):
    sz = max([len(b) for b in bins])
    arr = np.zeros(sz, dtype=np.uint32)

    for binarr in bins:
        for i in range(0, len(binarr)):
            arr[i] += binarr[i]
    return arr


@numba.jit(nopython=True)
def reverse_map(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """This functions return a reverse map to match the unique labels to a new sequece

    Args:
        x (np.ndarray): Unique labels. It is not required to be sorted or to be a sequence.
        y (np.ndarray): New labels.

    Returns:
        np.ndarray: Reverse label map
    """
    out = np.zeros(x.max() + 1)
    for i in range(len(y)):
        out[x[i]] = y[i]
    return out


# def indsort(im):
#     u, count = np.unique(im, return_counts=True)
#     ## Force label zero to always be the first (to be labelled as zero)
#     for i in range(len(u)):
#         if u[i] == 0:
#             count[i] = im.size + 1
#             break
#     return u, np.argsort(-count)


# @numba.jit(nopython=True)
# def invmap(labels, descend_sorted_ind):
#     Np = labels.max()
#     positions = np.zeros(Np + 1, dtype=np.uint32)
#     for i, label in enumerate(labels):
#         positions[label] = np.nonzero(descend_sorted_ind == i)[0][0]
#     return positions


# @numba.jit(nopython=True)
# def indreplace(im, sortmap):
#     for ind in np.ndindex(im.shape):
#         im[ind] = sortmap[im[ind]]
#     return im


def experiment1(regions, attributes: pd.DataFrame):
    rows, cols = regions.shape
    half = int(cols / 2)
    breakouts = set([])
    visited = set([])

    backtrack = defaultdict(list)

    for row in regions:
        spots = np.where(row)
        labels = {v for v in row[spots]}
        for pair in itertools.combinations(labels, 2):
            if pair in visited:
                continue

            visited.add(pair)
            label_a, label_b = pair

            anchor_label, small_label = (
                label_a,
                label_b if attributes.voxelCount[label_a - 1] > attributes.voxelCount[label_b - 1] else label_b,
            )

            try:
                centroid_a = np.argwhere(regions == label_a).mean(axis=0)
                centroid_b = np.argwhere(regions == label_b).mean(axis=0)

                distance = abs(centroid_a[1] - centroid_b[1])
                if not np.isclose(distance, half, rtol=0.1):
                    print("bad distance", distance, half, centroid_a, label_a, centroid_b, label_b)
                    continue
            except Exception as e:
                print("labels", label_a, label_a, spots, labels)
                raise

            # elong_a = attributes.aspect_ratio[label_a]
            # elong_b = attributes.aspect_ratio[label_b]
            #
            # if not np.isclose(elong_a, elong_b, atol=0.1):
            #     print('label_a', label_a, 'label_b', label_b, 'bad elong', elong_a, elong_b)
            #     backtrack[anchor_label].append(small_label)
            #     continue

            angle_a = attributes.angle[label_a - 1]
            angle_b = attributes.angle[label_b - 1]

            if 30 < angle_a < 330 and label_a == anchor_label:
                print("label_a", label_a, "bad angle a", angle_a)
                continue

            if 30 < angle_b < 330 and label_b == anchor_label:
                print("label_b", label_b, "bad angle b", angle_b)
                continue

            # if 30 < angle_a < 330:
            #     print('label_a', label_a, 'bad angle a', angle_a)
            #     if angle_a != anchor_label:
            #         backtrack[anchor_label].append(small_label)
            #     continue
            #
            # if 30 < angle_b < 330:
            #     print('label_b', label_b, 'bad angle b', angle_b)
            #     if angle_b != anchor_label:
            #         backtrack[anchor_label].append(small_label)
            #     continue

            # if angle_a <= 90 and angle_b > 90:
            #     angular_diff = (360 - angle_b) + angle_a
            # elif angle_a > 90 and angle_b <= 90:
            #     angular_diff = (360 - angle_a) + angle_b
            # else:
            #     angular_diff = abs(angle_a-angle_b)
            #
            # if angular_diff > 10:
            #     print('label_a', label_a, 'label_b', label_b, 'bad angle close', angle_a, angle_b, angular_diff)
            #     backtrack[anchor_label].append(small_label)
            #     continue

            print("added labels", label_a, label_b)
            breakouts.add(label_a)
            breakouts.add(label_b)

    for row in attributes.itertuples():
        if row.label not in breakouts:
            regions[regions == row.label] = 0

    regions[regions != 0] = 1

    return regions


def writeToTable(df, tableID):
    df.to_pickle(tableID)


def runPoreThroatAnalysis(params, outputVolumeID, partitionsVolumeID):
    partitionsOutputVolume = readFrom(partitionsVolumeID, mrml.vtkMRMLLabelMapVolumeNode)
    throat_analysis = ThroatAnalysis(
        labelVolume=partitionsOutputVolume, params=params, progress_update_callback=progressUpdate
    )

    return throat_analysis


def writePoreThroatBoundaries(throat_analysis, outputVolumeID, referenceVolume):
    writeDataInto(
        outputVolumeID,
        throat_analysis.boundary_labeled_array,
        mrml.vtkMRMLLabelMapVolumeNode,
        reference=referenceVolume,
    )


def writeThroatAnalysisReport(throat_analysis, throatOutputReportNodeID):
    writeToTable(throat_analysis.throat_report_df, throatOutputReportNodeID)


def fakeuntilitistrue():
    progressUpdate(0.3)
    time.sleep(1)
    progressUpdate(0.6)
    time.sleep(1)
    progressUpdate(0.9)
    time.sleep(0.5)
    progressUpdate(1.0)


def main(args):
    if args.labelVolume is None:
        fakeuntilitistrue()
        return

    products = set(args.products.split(","))

    params = json.loads(args.params)

    labelVolumeNode = readFrom(args.labelVolume, mrml.vtkMRMLLabelMapVolumeNode)

    # Convert parameters from mm to voxels
    size_min_threshold = params.get("size_min_threshold", 0)  # keep as mm

    volumeOperator = VolumeOperator(labelVolumeNode)

    im = volumeOperator._array

    result = None

    shape = np.array(im.shape)
    spacing = getIJKSpacing(labelVolumeNode)[np.where(shape != 1)]

    """This case does not handle non-orthogonal volumes.
    """

    if ("all" in products or "partitions" in products) and params.get("method") is not None:
        if np.any(shape == 1):
            im_mod = im.squeeze()
            if params.get("method") != "medial surface":
                mask = im_mod > 0
                spim.binary_closing(im_mod, output=im_mod)
                spim.binary_dilation(im_mod, output=im_mod, mask=mask)
                im_mod = np.pad(im_mod[1:-1, 1:-1], 1, mode="edge")
        else:
            if params.get("method") != "medial surface":
                im_mod = spim.binary_closing(im)
                spim.binary_dilation(im_mod, output=im_mod, mask=im > 0)
                im_mod = np.pad(im_mod[1:-1, 1:-1, 1:-1], 1, mode="edge")
            else:
                im_mod = im

        if params.get("method") == "snow":
            min_voxel_size = params.get("voxel_size") or min(spacing)
            sigma_vx = params["sigma"] / min_voxel_size
            r_max = int(params["d_min_filter"])
            if r_max < 2:
                r_max = 2
                print("d_min_filter must be at least 2, setting to 2")

            if np.any(min_voxel_size != spacing):
                print("Anisotropic watershed is not currently suported, running isotropic watershed")
            # TODO: implement anisotropy in PyEDT, but pass to snow_partitioning by precalculating dt

            result = partition.snow_partitioning(im_mod, r_max=r_max, sigma=sigma_vx)

        elif params.get("method") == "deep watershed":
            base_volume = int(params["base_volume"])
            intersection = int(params["intersection"])
            background_threshold = float(params["background_threshold"])
            split_threshold = float(params["split_threshold"])
            border = int(params["border"])
            result = deepwatershed.get_dwlabels(
                im_mod,
                base_volume=base_volume,
                intersection=intersection,
                border=border,
                split_threshold=split_threshold,
                background_threshold=background_threshold,
            )

        elif params.get("method") == "islands":
            result = partition.islands(im_mod)

        elif params.get("method") == "medial surface":
            smooth_filter_sigma = int(params["smooth_filter_sigma"])
            num_processes = int(params["num_processes"])
            result = generate_pore_network_label_map(im_mod, smooth_filter_sigma, num_processes)

    else:
        result = partition.Results()
        result.im = None
        result.dt = None
        result.peaks = None
        result.regions = slicer.util.arrayFromVolume(labelVolumeNode).astype(np.uint32).squeeze()

    if result is not None:
        number_of_partitions = result.regions.max()
        if "all" in products or "report" in products:
            if result.regions.ndim == 2:
                directionVector = params.get("direction", None)
                operator = LabelStatistics2D(result.regions, spacing, directionVector, size_min_threshold)
            else:
                operator = LabelStatistics3D(result.regions, spacing, size_min_threshold)

            df, nlabels = calculate_statistics_on_segments(
                result.regions,
                SegmentOperator(operator, volumeOperator.ijkToRasOperator),
                callback=lambda i, total: progressUpdate(i / total),
            )

            progressUpdate(0.3)

            if df.shape[1] > 1 and df.shape[0] > 0:
                df = df.set_axis(operator.ATTRIBUTES, axis=1)

                df = df.dropna(axis=1, how="all")  # Remove unused columns
                df = df.dropna(axis=0, how="any")  # Remove unused columns

                filtered_indices = df[df.max_feret < size_min_threshold].index
                # Remove filtered segments by user's diameter choice
                df = df.drop(filtered_indices, axis=0)

                # Round all float columns
                for col in df.select_dtypes(include=["float"]).columns:
                    df[col] = df[col].round(5)

                df = df.sort_values(by=["voxelCount", "max_feret", "label"], ascending=False)

                # After sorting, old labels serve as a reverse map
                # Added one more position because regions has the label '0'
                if df.shape[0] > 0:
                    new_labels = np.arange(1, len(df.index) + 1)
                    labelmap = reverse_map(df["label"].to_numpy(copy=False), new_labels)

                    # Remove all labels that are filtered out before (they are not present on labelmap)
                    result.regions[result.regions >= len(labelmap)] = 0

                    regions = labelmap[result.regions]  # remap volume
                    df["label"] = new_labels  # remap table
                else:
                    regions = np.zeros_like(result.regions)  # clear disposed labels from volume

                if args.outputReport:
                    df = addUnitsToDataFrameParameters(df)
                    categ = {i: v for i, v in enumerate(PORE_SIZE_CATEGORIES)}
                    df.pore_size_class = df.pore_size_class.replace(categ)
                    print(f"writing df to tableNode, {args.outputReport}")
                    writeToTable(df, args.outputReport)

                result.regions = regions
            else:
                print("Nothing to write")

            number_of_partitions = len(df)

    if "all" in products or "partitions" in products:
        reshaped_regions = result.regions.reshape(shape).astype(np.int32)

        if args.outputVolume:
            writeDataInto(
                args.outputVolume, reshaped_regions, mrml.vtkMRMLLabelMapVolumeNode, reference=labelVolumeNode
            )

        print(params.get("generate_throat_analysis"), args.throatOutputVolume)

    if (
        ("all" in products or ("partitions" in products and "report" in products))
        and params.get("generate_throat_analysis") == True
        and args.throatOutputVolume is not None
    ):
        # TODO isolate better pore throat analysis to separate in partitions and report
        params["spacing"] = spacing
        pore_throat_analysis = runPoreThroatAnalysis(params, args.throatOutputVolume, args.outputVolume)

        writePoreThroatBoundaries(pore_throat_analysis, args.throatOutputVolume, referenceVolume=labelVolumeNode)

        if params.get("throatOutputReport") is not None:
            writeThroatAnalysisReport(pore_throat_analysis, params.get("throatOutputReport"))

    progressUpdate(0.8)

    with open(args.returnparameterfile, "w") as returnFile:
        returnFile.write(f"number_of_partitions={number_of_partitions}\n")

    progressUpdate(1.0)


def addUnitsToDataFrameParameters(df):
    def appendUnit(data, parameter, unit_str):
        if parameter not in data.columns:
            return data

        data = data.rename(columns={parameter: f"{parameter} ({unit_str})"})
        return data

    df = appendUnit(df, "voxelCount ", "voxels")
    df = appendUnit(df, "area", "mm^2")
    df = appendUnit(df, "volume", "mm^3")
    df = appendUnit(df, "angle_ref_to_max_feret", "deg")
    df = appendUnit(df, "angle_ref_to_min_feret", "deg")
    df = appendUnit(df, "angle", "deg")
    df = appendUnit(df, "min_feret", "mm")
    df = appendUnit(df, "max_feret", "mm")
    df = appendUnit(df, "mean_feret", "mm")
    df = appendUnit(df, "ellipse_perimeter", "mm")
    df = appendUnit(df, "ellipse_area", "mm^2")
    df = appendUnit(df, "ellipse_perimeter_over_ellipse_area", "1/mm")
    df = appendUnit(df, "perimeter", "mm")
    df = appendUnit(df, "perimeter_over_area", "1/mm")
    df = appendUnit(df, "angle", "mm^2")
    df = appendUnit(df, "ellipsoid_area", "mm^2")
    df = appendUnit(df, "ellipsoid_volume", "mm^3")
    df = appendUnit(df, "ellipsoid_area_over_ellipsoid_volume", "1/mm")
    df = appendUnit(df, "sphere_diameter_from_volume", "mm")

    return df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--labels", type=str, dest="labelVolume", default=None)
    # parser.add_argument('--values', type=str, dest='valuesVolume', default=None)
    parser.add_argument("--output", type=str, dest="outputVolume", default=None)
    parser.add_argument("--report", type=str, dest="outputReport", default=None)
    parser.add_argument("--params", type=str)
    parser.add_argument("--products", type=str, default="all")
    parser.add_argument("--returnparameterfile", type=str, help="File destination to store an execution outputs")
    parser.add_argument("--throatOutput", type=str, dest="throatOutputVolume", default=None)
    try:
        main(parser.parse_args())
    except Exception as e:
        with open(parser.parse_args().returnparameterfile, "w") as returnFile:
            returnFile.write(f"errors={e}\n")

    # Make sure all prints are flushed
    sys.stdout.flush()
    sys.stderr.flush()

    # Avoid vtkDebugLeaks error boxes
    gc.collect()

    # Kill the process with no further cleanup,
    # otherwise it gets stuck in GeoSlicerRemote
    os._exit(0)
