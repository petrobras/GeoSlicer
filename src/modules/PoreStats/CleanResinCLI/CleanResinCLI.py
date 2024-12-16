#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

from __future__ import print_function
from pathlib import Path
import time

import cv2
import joblib

import slicer
import slicer.util
import mrml

from ltrace.slicer.cli_utils import progressUpdate, readFrom, writeDataInto

import numpy as np
from skimage.segmentation import watershed


def incrementalProgressUpdate(progress, addition):
    progress += addition
    progressUpdate(progress)
    return progress


def clean_resin(image, binary_seg, px_image, pp_rock_area, px_rock_area, decide_best_reg):
    def remove_artifacts(mask, open_kernel_size, close_kernel_size):
        if open_kernel_size is not None:
            open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_kernel_size, open_kernel_size))
            mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, open_kernel)
        if close_kernel_size is not None:
            close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_kernel_size, close_kernel_size))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel).astype(bool)

        return mask

    def get_roi_from_blue_channel(image):
        nonlocal progress

        blue_channel = image[:, :, 2]
        blue_channel = cv2.equalizeHist(blue_channel)

        # with open(Path(__file__).parent.parent / "PoreStatsCLI" / "Libs" / "pore_stats" / "models" / "pore_residues" / "blue_channel.pkl", 'rb') as pkl:
        #    kmeans = pickle.load(pkl)

        # Usando joblib em vez de pickle para aproveitar a compressão do modelo (K-Means pickle fica muito grande)
        # O modelo joblib foi salvo usando a mesma versão do Python usado para executar este script (PythonSlicer). Divergência de versão causa erro.
        kmeans = joblib.load(
            Path(__file__).parent.parent
            / "PoreStatsCLI"
            / "Libs"
            / "pore_stats"
            / "models"
            / "pore_residues"
            / "blue_channel.pkl"
        )

        clusters = kmeans.predict(blue_channel.flatten().reshape(-1, 1))
        progress = incrementalProgressUpdate(progress, 0.25)
        blue_mask = clusters.reshape(blue_channel.shape) == kmeans.cluster_centers_.argmax()
        return remove_artifacts(blue_mask, open_kernel_size=20, close_kernel_size=None)

    def get_roi_from_hue_channel(image):
        nonlocal progress

        progress = incrementalProgressUpdate(progress, 0.03)
        hue_channel = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)[:, :, 0]

        hue_mask = (hue_channel >= 75) & (
            hue_channel <= 135
        )  # blue hue, which catches both the resin and the dark bubbles/residues
        for open_kernel_size, close_kernel_size in [(5, None), (None, 13), (13, None)]:
            hue_mask = remove_artifacts(
                hue_mask, open_kernel_size=open_kernel_size, close_kernel_size=close_kernel_size
            )
            progress = incrementalProgressUpdate(progress, 0.01)

        return hue_mask

    def get_roi_from_px_hsv(pp, px, pores_mask, decide_best_reg):
        def crop_rock_area(image, rock_area):
            non_zero_coords = cv2.findNonZero(rock_area.astype(np.uint8))
            x, y, w, h = cv2.boundingRect(non_zero_coords)
            crop = image[y : y + h, x : x + w]
            return crop

        def register_px_to_pp(pp, px, pp_rock_area=None, px_rock_area=None):
            reg_px = np.zeros((max(pp.shape[0], px.shape[0]), max(pp.shape[1], px.shape[1]), 3)).astype(np.uint8)
            orig_pp_shape = pp.shape

            if pp_rock_area is not None:
                pp = crop_rock_area(pp, pp_rock_area)
            if px_rock_area is not None:
                px = crop_rock_area(px, px_rock_area)

            px_y0 = reg_px.shape[0] // 2 - px.shape[0] // 2
            px_y1 = reg_px.shape[0] // 2 + px.shape[0] // 2 + px.shape[0] % 2
            px_x0 = reg_px.shape[1] // 2 - px.shape[1] // 2
            px_x1 = reg_px.shape[1] // 2 + px.shape[1] // 2 + px.shape[1] % 2

            reg_px[px_y0:px_y1, px_x0:px_x1] = px.copy()

            pp_y0 = reg_px.shape[0] // 2 - orig_pp_shape[0] // 2
            pp_y1 = reg_px.shape[0] // 2 + orig_pp_shape[0] // 2 + orig_pp_shape[0] % 2
            pp_x0 = reg_px.shape[1] // 2 - orig_pp_shape[1] // 2
            pp_x1 = reg_px.shape[1] // 2 + orig_pp_shape[1] // 2 + orig_pp_shape[1] % 2

            return reg_px[pp_y0:pp_y1, pp_x0:pp_x1]

        nonlocal progress

        reg_px = {
            "Centralized": register_px_to_pp(pp, px),
        }
        progress = incrementalProgressUpdate(progress, 0.02)
        if decide_best_reg:
            reg_px.update(
                {
                    "Cropped and centralized": register_px_to_pp(
                        pp, px, pp_rock_area=pp_rock_area, px_rock_area=px_rock_area
                    )
                }
            )
            progress = incrementalProgressUpdate(progress, 0.07)
        px_pores_mask = None
        best_reg_quality = -1
        best_method = None
        for method, px in reg_px.items():
            px_hsv = cv2.cvtColor(cv2.GaussianBlur(px, (99, 99), 9), cv2.COLOR_RGB2HSV)

            kmeans = joblib.load(
                Path(__file__).parent.parent
                / "PoreStatsCLI"
                / "Libs"
                / "pore_stats"
                / "models"
                / "pore_residues"
                / "px_hsv.pkl"
            )
            clusters = kmeans.predict(px_hsv.flatten().reshape(-1, 3))
            test_px_pores_mask = clusters.reshape(px_hsv.shape[:2]) == 3
            test_px_pores_mask = remove_artifacts(test_px_pores_mask, open_kernel_size=13, close_kernel_size=13)

            reg_area = np.count_nonzero(test_px_pores_mask & pores_mask)
            pore_area = np.count_nonzero(pores_mask)
            test_reg_quality = reg_area / pore_area if pore_area > 0 else 0
            print(method, "registration quality:", "{:.2f} %".format(100 * test_reg_quality))
            if test_reg_quality > best_reg_quality:
                best_method = method
                best_reg_quality = test_reg_quality
                px_pores_mask = test_px_pores_mask
            progress = incrementalProgressUpdate(progress, 0.25)

        print(best_method, "registration method chosen.")
        return px_pores_mask

    def grow_pores_through_mask(mask, pores):
        markers = pores & mask
        return watershed(~mask, markers=markers, mask=mask)

    use_px = px_image is not None

    if pp_rock_area is not None:
        image *= pp_rock_area.astype(np.uint8)[..., np.newaxis]

    print("Detecting air bubbles and residues in pore resin... Using PX:", {False: "No", True: "Yes"}[use_px])
    start_time = time.time()
    progress = incrementalProgressUpdate(0, 0)

    # O canal azul da imagem funde as bolhas brancas à resina azul
    blue_mask = get_roi_from_blue_channel(image)
    # O canal Hue da imagem funde as bolhas negras e resíduos à resina azul
    hue_mask = get_roi_from_hue_channel(image)

    if use_px:
        # A região escura do PX funde as bolhas e resíduos à região porosa
        px_pores_mask = get_roi_from_px_hsv(image, px_image, binary_seg, decide_best_reg)

        # As regiões não-escuras do PX são descartadas das regiões úteis dos canais azul e Hue
        blue_mask &= px_pores_mask
        hue_mask &= px_pores_mask

    # Os poros detectados crescem sobre a região azul, cobrindo as bolhas brancas
    bubbled_blue_mask = grow_pores_through_mask(blue_mask, binary_seg)
    # Os poros detectados crescem sobre a região Hue, cobrindo as bolhas negras e resíduos
    bubbled_hue_mask = grow_pores_through_mask(hue_mask, binary_seg)

    print(f"Done ({time.time() - start_time}s).")
    progressUpdate(1)
    # As regiões crescidas são unidas. Os poros originais são reinclusos para o caso de terem sido
    # perdidos por um mal alinhamento entre PP e PX
    return bubbled_blue_mask | bubbled_hue_mask | binary_seg


def get_array_if_exists(input_path, is_segmentation):
    if input_path:
        builder = mrml.vtkMRMLLabelMapVolumeNode if is_segmentation else mrml.vtkMRMLVectorVolumeNode
        node = readFrom(input_path, builder)
        return slicer.util.arrayFromVolume(node)[0]
    return None


def runcli(args):
    sourceVolumeNode = readFrom(args.ppImage, mrml.vtkMRMLVectorVolumeNode)
    pp_image = slicer.util.arrayFromVolume(sourceVolumeNode)[0]

    poreSegmentationNode = readFrom(args.poreSegmentation, mrml.vtkMRMLLabelMapVolumeNode)
    pore_seg = slicer.util.arrayFromVolume(poreSegmentationNode)[0].astype(bool)

    px_image = get_array_if_exists(args.pxImage, is_segmentation=False)
    pp_rock_area = get_array_if_exists(args.ppRockArea, is_segmentation=True)
    px_rock_area = get_array_if_exists(args.pxRockArea, is_segmentation=True)

    pore_seg = clean_resin(pp_image, pore_seg, px_image, pp_rock_area, px_rock_area, args.smartReg)

    writeDataInto(args.output, pore_seg, mrml.vtkMRMLLabelMapVolumeNode, reference=sourceVolumeNode)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Clean Resin Wrapper for Slicer.")
    parser.add_argument("--ppimage", type=str, dest="ppImage", default=None, help="Input PP Image")
    parser.add_argument(
        "--poreseg",
        type=str,
        dest="poreSegmentation",
        default=None,
        help="Prior Pore Segmentation For Resin Cleaning",
    )
    parser.add_argument("--output", type=str, dest="output", default=None, help="Output Segmentation")
    parser.add_argument("--pximage", type=str, dest="pxImage", default=None, help="Input PX Image")
    parser.add_argument("--pprockarea", type=str, dest="ppRockArea", default=None, help="PP Rock Area Segmentation")
    parser.add_argument("--pxrockarea", type=str, dest="pxRockArea", default=None, help="PX Rock Area Segmentation")
    parser.add_argument(
        "--smartreg",
        action="store_true",
        dest="smartReg",
        help="Decide Best Auto-Registration Heuristic",
    )

    args = parser.parse_args()
    runcli(args)
