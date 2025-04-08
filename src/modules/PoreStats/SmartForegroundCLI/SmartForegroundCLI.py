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


def get_thin_section_rock_area(image):

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


def get_microct_rock_area(volume):
    def gradient(image):
        grad_x = cv2.Sobel(image, cv2.CV_64F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(image, cv2.CV_64F, 0, 1, ksize=3)

        gradient_magnitude = np.sqrt(grad_x**2 + grad_y**2)
        gradient_magnitude = cv2.normalize(gradient_magnitude, None, 0, 1, cv2.NORM_MINMAX)

        return gradient_magnitude

    mask = np.zeros_like(volume).astype(bool)

    if volume[0, 0, 0] == 0:
        for i, slice in enumerate(volume):
            mask[i] = ndi.binary_fill_holes(slice)
            progressUpdate(0.99 * (i + 1) / len(volume))
    else:
        sigma = tuple(sh / 360 for sh in volume.shape[1:])
        kernel_size = tuple(int(2 * (4 * round(sg) + 0.5)) for sg in sigma)

        for i, slice in enumerate(volume):
            slice = (255 * slice.astype(float) / slice.max()).astype(np.uint8)  # uint16 -> uint8
            slice = cv2.equalizeHist(slice)  # reforça contraste para as bordas ficarem mais escuras
            eq_slice = slice.copy()
            slice = (255 * gradient(slice)).astype(
                np.uint8
            )  # gradiente da imagem tende a ser baixo nas bordas e mais alto na área útil
            slice = cv2.equalizeHist(slice)  # reforça contraste do gradiente
            slice = (255 * (slice / 255.0 * eq_slice / 255.0)).astype(
                np.uint8
            )  # contribuição residual da própria imagem sobre o gradiente (bordas são escuras nos dois, então tendem a ficar ainda mais escuras)
            slice = cv2.GaussianBlur(
                slice, kernel_size, sigmaX=sigma[0], sigmaY=sigma[1]
            )  # borramento para amenizar os "buracos" mais centrais e desconectá-los das bordas
            slice = cv2.threshold(slice, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[
                1
            ]  # binarização do resultado: bordas tendem a zerar, e a área útil tende a ter valor verdadeiro
            slice = ndi.binary_fill_holes(slice)  # fecha buracos internos
            slice_islands = ndi.label(slice)[0]
            slice = (
                slice_islands == slice_islands[slice.shape[0] // 2, slice.shape[1] // 2]
            )  # mantém apenas a ilha central, excluindo pequenos ruídos nas bordas
            mask[i] = slice
            progressUpdate(0.99 * (i + 1) / len(volume))

    return mask.astype(np.uint8)


def runcli(args):
    if not args.is3d:
        sourceVolumeNode = readFrom(args.input, mrml.vtkMRMLVectorVolumeNode)
        image = slicer.util.arrayFromVolume(sourceVolumeNode)[0]

        rock_area = get_thin_section_rock_area(image)
        progressUpdate(0.85)

        if args.poreSegmentation is not None:
            poreSegmentationNode = readFrom(args.poreSegmentation, mrml.vtkMRMLLabelMapVolumeNode)
            pore_seg = slicer.util.arrayFromVolume(poreSegmentationNode)[0].astype(bool)

            frags_mask = (~pore_seg) & rock_area
            progressUpdate(0.9)

            frags_mask = ndi.binary_fill_holes(frags_mask)
            progressUpdate(0.95)

            if args.nLargestFrags >= 0:
                frags_mask = filter_largest_islands(frags_mask, args.nLargestFrags)

            rock_area = frags_mask
    else:
        sourceVolumeNode = readFrom(args.input, mrml.vtkMRMLScalarVolumeNode)
        volume = slicer.util.arrayFromVolume(sourceVolumeNode)

        rock_area = get_microct_rock_area(volume)

    writeDataInto(args.outputRock, rock_area, mrml.vtkMRMLLabelMapVolumeNode, reference=sourceVolumeNode)
    progressUpdate(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Smart Foreground Wrapper for Slicer.")
    parser.add_argument("--input", type=str, dest="input", default=None, help="Intensity Input Values")
    parser.add_argument("--outputrock", type=str, dest="outputRock", default=None, help="Output Rock Area Segmentation")
    parser.add_argument("--is3d", action="store_true", dest="is3d", help="Output Rock Area Segmentation")
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
