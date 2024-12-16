#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

from __future__ import print_function
import os
from pathlib import Path
import pickle
import time
import warnings

import slicer
import slicer.util
import mrml

from ltrace.slicer.cli_utils import progressUpdate, readFrom, writeDataInto

import numpy as np
import scipy.ndimage as ndi
from skimage import measure


def remove_spurious(image, binary_seg, pore_model):
    def get_roi_from_centroid(cy, cx, image, seg, i_seg, roi_size):
        def get_ref_point(cy, cx, seg, i_seg):
            def try_getting_ref_point(y, x, seg):
                if any(np.isnan(coord) for coord in [y, x]):
                    return False, y, x
                y, x = int(y), int(x)
                return seg[y, x], y, x

            cy, cx = np.clip(int(cy), 0, seg.shape[0] - 1), np.clip(int(cx), 0, seg.shape[1] - 1)

            if not seg[cy, cx]:
                seg_y, seg_x = np.where(seg == i_seg)

                y, x = cy, cx
                success, y, x = try_getting_ref_point(cy, np.median(seg_x[(seg_x < cx) & (seg_y == cy)]), seg)
                if not success:
                    success, y, x = try_getting_ref_point(cy, np.median(seg_x[(seg_x > cx) & (seg_y == cy)]), seg)
                if not success:
                    success, y, x = try_getting_ref_point(np.median(seg_y[(seg_y < cy) & (seg_x == cx)]), cx, seg)
                if not success:
                    success, y, x = try_getting_ref_point(np.median(seg_y[(seg_y > cy) & (seg_x == cx)]), cx, seg)

                cy = y
                cx = x

            return cy, cx

        offset = roi_size // 2

        # Em alguns casos, o centróide do segmento reside fora dele. Então, tenta-se obter o pixel mediano do segmento à esquerda
        # do centróide. Se não houver, tenta-se à direita. Então, acima. Em último caso, abaixo.
        cy, cx = get_ref_point(cy, cx, seg, i_seg)
        y0, x0 = max(0, cy - offset), max(0, cx - offset)
        y1, x1 = y0 + roi_size, x0 + roi_size
        if y1 > image.shape[0]:
            d = y1 - image.shape[0]
            y0, y1 = y0 - d, y1 - d
        if x1 > image.shape[1]:
            d = x1 - image.shape[1]
            x0, x1 = x0 - d, x1 - d
        assert y1 - y0 == roi_size
        assert x1 - x0 == roi_size

        return image[y0:y1, x0:x1].flatten()

    split_pores = ndi.label(binary_seg)[0]

    if split_pores.max() > 0:
        # Há um modelo RandomForest de remoção de poros espúrios para cada modelo de segmentação de poros
        with open(
            Path(__file__).parent.parent
            / "PoreStatsCLI"
            / "Libs"
            / "pore_stats"
            / "models"
            / "spurious_removal"
            / f"spurious_{pore_model}.pkl",
            "rb",
        ) as pkl:
            scaler_and_model = pickle.load(pkl)
            scaler = scaler_and_model["scaler"]
            model = scaler_and_model["model"]

        # Para cada segmento de poro, é obtida uma pequena região de interesse (ROI) em volta do centróide
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore")

            print("Removing spurious pore detections...")
            start_time = time.time()
            regions_props = measure.regionprops(split_pores, intensity_image=image)

            rois = []
            candidate_pred_indexes = []
            pred_indexes = range(1, split_pores.max() + 1)
            for i in pred_indexes:
                progressUpdate(i / len(pred_indexes))
                region_props = regions_props[i - 1]
                if (
                    region_props.area < 3
                ):  # porque o Segment Inspector não inclui segmentos com menos de 3 pixeis no relatório
                    split_pores[split_pores == i] = 0
                else:
                    cy, cx = region_props.centroid
                    roi = get_roi_from_centroid(cy, cx, image, split_pores, i, roi_size=10)
                    rois.append(roi)
                    candidate_pred_indexes.append(i)

            if len(rois) > 0:
                # O modelo detecta os ROIs espúrios e os descarta
                predictions = model.predict(scaler.transform(np.array(rois)))
                valid_pred_indexes = np.array(candidate_pred_indexes)[np.nonzero(predictions)[0]]

                split_pores = np.where(np.isin(split_pores, valid_pred_indexes), split_pores, 0)
                n_valid = len(valid_pred_indexes)
            else:
                n_valid = 0

            n_discarded = i - n_valid

        print(f"Done: {n_valid} detections kept, {n_discarded} discarded ({time.time() - start_time}s).")
    else:
        print("No pores found.")

    return split_pores.astype(bool)


def runcli(args):
    sourceVolumeNode = readFrom(args.input, mrml.vtkMRMLVectorVolumeNode)
    image = slicer.util.arrayFromVolume(sourceVolumeNode)[0]

    poreSegmentationNode = readFrom(args.poreSegmentation, mrml.vtkMRMLLabelMapVolumeNode)
    pore_seg = slicer.util.arrayFromVolume(poreSegmentationNode)[0].astype(bool)

    pore_seg = remove_spurious(image, pore_seg, args.poreSegModel)

    progressUpdate(1)
    writeDataInto(args.output, pore_seg, mrml.vtkMRMLLabelMapVolumeNode, reference=sourceVolumeNode)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Remove Spurious Wrapper for Slicer.")
    parser.add_argument("--input", type=str, dest="input", default=None, help="Intensity Input Values")
    parser.add_argument("--output", type=str, dest="output", default=None, help="Output Segmentation")
    parser.add_argument(
        "--poreseg",
        type=str,
        dest="poreSegmentation",
        default=None,
        help="Prior Pore Segmentation For Spurious Removal",
    )
    parser.add_argument(
        "--poresegmodel",
        type=str,
        dest="poreSegModel",
        default=None,
        help="Pore Segmentation Model File",
    )

    args = parser.parse_args()
    runcli(args)
