#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

from __future__ import print_function

import slicer
import slicer.util
import mrml

from ltrace.slicer.cli_utils import progressUpdate, readFrom, writeDataInto

import numpy as np
import cv2
from skimage import morphology, color
import scipy.ndimage as ndi


def filter_largest_islands(seg, n_largest_islands):

    # Filtra os N maiores fragmentos.

    seg = cv2.erode(seg.astype(np.uint8), np.ones((23, 23), np.uint8))  # para limpar pequenos artefatos
    islands = ndi.label(seg)[0]
    islands_sizes = np.bincount(islands.ravel())
    sorted_labels = np.argsort(islands_sizes)[::-1]
    sorted_labels = sorted_labels[sorted_labels != 0]
    seg[~np.isin(islands, sorted_labels[:n_largest_islands])] = 0

    return seg.astype(bool)


def get_rock_area(image):

    # Isola a área da rocha da borda da imagem
    def equalize_each_channel(image):
        return np.stack([cv2.equalizeHist(image[:, :, i]) for i in range(3)], axis=2)

    eq = equalize_each_channel(image)
    blur = cv2.GaussianBlur(eq, (199, 199), 255)
    progressUpdate(0.2)

    lum = color.rgb2gray(blur)
    mask = morphology.remove_small_holes(morphology.remove_small_objects((lum > 0.3) & (lum < 0.7), 500), 500)
    progressUpdate(0.4)

    mask = morphology.opening(mask, morphology.disk(3))
    progressUpdate(0.7)

    mask = filter_largest_islands(
        mask, 1
    )  # para pegar a área central da rocha e eliminar artefatos deixados nas bordas
    progressUpdate(0.75)

    return ndi.binary_fill_holes(mask)


def runcli(args):
    sourceVolumeNode = readFrom(args.input, mrml.vtkMRMLVectorVolumeNode)
    image = slicer.util.arrayFromVolume(sourceVolumeNode)[0]

    rock_area = get_rock_area(image)
    progressUpdate(0.85)

    writeDataInto(args.outputRock, rock_area, mrml.vtkMRMLLabelMapVolumeNode, reference=sourceVolumeNode)

    if args.poreSegmentation is not None:
        poreSegmentationNode = readFrom(args.poreSegmentation, mrml.vtkMRMLLabelMapVolumeNode)
        pore_seg = slicer.util.arrayFromVolume(poreSegmentationNode)[0].astype(bool)

        frags_mask = (~pore_seg) & rock_area
        progressUpdate(0.9)

        frags_mask = ndi.binary_fill_holes(frags_mask)
        progressUpdate(0.95)

        if args.nLargestFrags >= 0:
            frags_mask = filter_largest_islands(frags_mask, args.nLargestFrags)

        writeDataInto(args.outputFrags, frags_mask, mrml.vtkMRMLLabelMapVolumeNode, reference=sourceVolumeNode)

    progressUpdate(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Smart Foreground Wrapper for Slicer.")
    parser.add_argument("--input", type=str, dest="input", default=None, help="Intensity Input Values")
    parser.add_argument("--outputrock", type=str, dest="outputRock", default=None, help="Output Rock Area Segmentation")
    parser.add_argument(
        "--outputfrags", type=str, dest="outputFrags", default=None, help="Output Fragments Segmentation"
    )
    parser.add_argument(
        "--poreseg",
        type=str,
        dest="poreSegmentation",
        default=None,
        help="Prior Pore Segmentation For Fragment Splitting",
    )
    parser.add_argument(
        "--max_frags",
        type=int,
        dest="nLargestFrags",
        default=-1,
        help="Number of Fragments to Filter (From Largest to Smallest)",
    )

    args = parser.parse_args()
    runcli(args)
