#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

from __future__ import print_function

import vtk, slicer, slicer.util, mrml
import json
import numpy as np
import sys
import time

from pathlib import Path
from ltrace.assets_utils import get_metadata, get_pth
from ltrace.slicer.cli_utils import writeDataInto, readFrom, progressUpdate
from ltrace.slicer.volume_operator import VolumeOperator, SegmentOperator
from ltrace.algorithms.measurements import LabelStatistics2D, calculate_statistics_on_segments
from ltrace import transforms

import cv2
from mmdet.apis import init_detector, inference_detector
from mmdet.utils import register_all_modules
from mmengine import Config
import torch
import pandas as pd
import scipy
from skimage.transform import resize


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

        # reset the attribute dictionary, otherwise it will be transferred over
        attrs = vtk.vtkStringArray()
        nodeOut.GetAttributeNames(attrs)
        for i in range(0, attrs.GetNumberOfValues()):
            nodeOut.SetAttribute(attrs.GetValue(i), None)

    # reset the data array to force resizing, otherwise we will just keep the old data too
    nodeOut.SetAndObserveImageData(None)
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


def resize_mask(output_shape, data):
    output = resize(data, output_shape, preserve_range=True, order=0).astype(np.uint16)

    return output


np.set_printoptions(suppress=True)


class mmdetInference:
    def __init__(self, image, scale_percent, config, model_path, device):
        self.scale_percent = scale_percent
        self.config = config
        self.model = get_pth(model_path).as_posix()
        self.device = device

        self.classes = get_metadata(model_path)["outputs"]["y"]["class_names"]

        self.width = int(image.shape[1] * scale_percent)
        self.height = int(image.shape[0] * scale_percent)

        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        image = cv2.resize(image, dsize=(self.width, self.height), interpolation=cv2.INTER_AREA)
        self.image = np.squeeze(image[np.newaxis, ...])

        register_all_modules()

        self.detector = init_detector(config, self.model, device=self.device)
        progressUpdate(0.3)

    def run_inference(self, conf_thresh, nms_thresh):
        for i in range(2):
            try:
                result = inference_detector(self.detector, self.image)
                progressUpdate(0.6)
                break
            except Exception as e:
                if self.device != "cpu":
                    print(f"Error occured during inference while using device:{self.device}. Switching to 'cpu'.")
                    self.device = "cpu"
                    self.detector = init_detector(self.config, self.model, device=self.device)
                else:
                    raise e

        instances = result.pred_instances
        instances = instances.cpu()

        boxes, masks, confidences, class_ids = (
            instances.bboxes.numpy(),
            instances.masks.numpy(),
            instances.scores.numpy(),
            instances.labels.numpy(),
        )

        valid_confidence_indices = np.where(confidences >= conf_thresh)
        boxes = boxes[valid_confidence_indices]
        masks = masks[valid_confidence_indices]
        confidences = confidences[valid_confidence_indices]
        class_ids = class_ids[valid_confidence_indices]

        if boxes.size == 0 or masks.size == 0 or confidences.size == 0 or class_ids.size == 0:
            return None, None, None, None, None

        boxes[:, 2] -= boxes[:, 0]
        boxes[:, 3] -= boxes[:, 1]

        indices = cv2.dnn.NMSBoxes(boxes, confidences, conf_thresh, nms_thresh)
        indices_list = list(indices.flatten())

        removed_inds = []
        labels = []
        idx = np.zeros(len(self.classes), dtype=np.uint16)
        instances = np.zeros((len(self.classes), self.height, self.width), dtype=np.uint16)
        scale = 1.0 / self.scale_percent
        if len(indices_list) > 0:
            for num, i in enumerate(indices.flatten()):
                mask = masks[i]
                overlap = (mask > 0) * (instances[class_ids[i]] != 0)
                difference = (mask > 0) * (instances[class_ids[i]] == 0)

                if not np.any(overlap) or difference.sum() / (mask > 0).sum() > 0.5:
                    idx[class_ids[i]] += 1
                    instances[class_ids[i]] += idx[class_ids[i]] * (mask > 0) * (instances[class_ids[i]] == 0)
                    labels.append(idx[class_ids[i]])
                else:
                    removed_inds.append(i)

        progressUpdate(0.8)
        indices = np.array([i for i in indices if i not in removed_inds])
        boxes = boxes[indices]
        confidences = confidences[indices]
        class_ids = class_ids[indices]

        return labels, boxes, confidences, class_ids, instances

    def run_chunked_inference(self, conf_thresh, nms_thresh, chunk_size=3200, chunk_overlap=0.5, pad_size=0):
        chunk_size = int(self.scale_percent * chunk_size)

        for i in range(2):
            try:
                results = self.inference_detector_by_chunks(conf_thresh, chunk_size, chunk_overlap, pad_size)
                break
            except Exception as e:
                if self.device != "cpu":
                    print(f"Error occured during inference while using device:{self.device}. Switching to 'cpu'.")
                    self.device = "cpu"
                    self.detector = init_detector(self.config, self.model, device=self.device)
                else:
                    raise e

        if not results:
            return None, None, None, None, None

        #### Filter results
        origins_list = []
        boxes_list = []
        masks_list = []
        confidences_list = []
        class_ids_list = []

        origin_x = np.array([origin[0] for origin, _, _, _, _ in results])
        origin_y = np.array([origin[1] for origin, _, _, _, _ in results])

        for chunk_index, chunk in enumerate(results):
            boxes, masks, confidences, class_ids = chunk[1], chunk[2], chunk[3], chunk[4]
            boxes[:, 2] -= boxes[:, 0]
            boxes[:, 3] -= boxes[:, 1]
            boxes[:, 0] += origin_x[chunk_index]
            boxes[:, 1] += origin_y[chunk_index]

            origins_list_chunk = [[origin_x[chunk_index], origin_y[chunk_index]] for i in boxes]
            if origins_list_chunk:
                origins_list.append(origins_list_chunk)
            boxes_list.append(boxes)
            masks_list.append(masks)
            confidences_list.append(confidences)
            class_ids_list.append(class_ids)

        boxes = np.vstack(boxes_list)
        masks = np.vstack(masks_list)
        origins = np.vstack(origins_list)
        confidences = np.concatenate(confidences_list)
        class_ids = np.concatenate(class_ids_list)

        indices = cv2.dnn.NMSBoxes(boxes, confidences, conf_thresh, nms_thresh)
        indices = indices.flatten()

        #### Join masks
        removed_inds = []
        labels = []
        idx = np.zeros(len(self.classes), dtype=np.uint16)
        instances = np.zeros((len(self.classes), self.height, self.width), dtype=np.uint16)
        if len(indices) > 0:
            for num, i in enumerate(indices):
                chunk_instance = instances[
                    class_ids[i], origins[i, 1] : origins[i, 1] + chunk_size, origins[i, 0] : origins[i, 0] + chunk_size
                ]
                mask = masks[
                    i, pad_size : pad_size + chunk_instance.shape[0], pad_size : pad_size + chunk_instance.shape[1]
                ]
                overlap = (mask > 0) * (chunk_instance != 0)
                difference = (mask > 0) * (chunk_instance == 0)

                if not np.any(overlap) or difference.sum() / (mask > 0).sum() > 0.5:
                    idx[class_ids[i]] += 1
                    instances[
                        class_ids[i],
                        origins[i, 1] : origins[i, 1] + chunk_size,
                        origins[i, 0] : origins[i, 0] + chunk_size,
                    ] += (
                        idx[class_ids[i]] * (mask > 0) * (chunk_instance == 0)
                    )
                    labels.append(idx[class_ids[i]])
                else:
                    removed_inds.append(i)

        indices = np.array([i for i in indices if i not in removed_inds])
        boxes = boxes[indices]
        confidences = confidences[indices]
        class_ids = class_ids[indices]

        return labels, boxes, confidences, class_ids, instances

    def inference_detector_by_chunks(self, conf_thresh, chunk_size, chunk_overlap, pad_size):
        results = []
        stride = (1 - chunk_overlap) * chunk_size

        t = 0
        total = (self.width / stride) * (self.height / stride)
        progressUpdate(0.1)
        for i in np.arange(0, self.width, stride):
            for j in np.arange(0, self.height, stride):
                i, j = int(i), int(j)

                t += 1.0 / total
                t = min(t, 1.0)
                progressUpdate(0.1 + 0.7 * t)

                a = self.image[j : j + chunk_size, i : i + chunk_size]
                pad = np.array([chunk_size, chunk_size]) - a.shape[:2]
                img_crop = np.pad(
                    a, ((pad_size, pad[0] + pad_size), (pad_size, pad[1] + pad_size), (0, 0)), mode="reflect"
                )

                result = inference_detector(self.detector, img_crop)
                instances = result.pred_instances
                instances = instances.cpu()

                boxes, masks, confidences, class_ids = (
                    instances.bboxes.numpy(),
                    instances.masks.numpy(),
                    instances.scores.numpy(),
                    instances.labels.numpy(),
                )

                valid_confidence_indices = np.where(confidences >= conf_thresh)
                boxes = boxes[valid_confidence_indices]
                masks = masks[valid_confidence_indices]
                confidences = confidences[valid_confidence_indices]
                class_ids = class_ids[valid_confidence_indices]

                boxes = boxes.clip(pad_size, chunk_size + pad_size + -1)
                valid = np.where(
                    (boxes[:, 0] + i < self.width)
                    & (boxes[:, 1] + j < self.height)
                    & (boxes[:, 2] > boxes[:, 0])
                    & (boxes[:, 3] > boxes[:, 1])
                )

                boxes = boxes[valid]
                masks = masks[valid]
                confidences = confidences[valid]
                class_ids = class_ids[valid]

                if boxes.size > 0 and masks.size > 0 and confidences.size > 0 and class_ids.size > 0:
                    results.append(([i, j], boxes, masks, confidences, class_ids))

        return results


def calculate_statistics(df, instances, class_ids, classes, scale, spacing):
    df_props = pd.DataFrame()
    spacing[:2] *= scale
    referenceSpacing = spacing
    voxel_area = np.product(referenceSpacing)
    tot_classes = np.unique(class_ids)
    for idx, class_id in enumerate(tot_classes):
        progressUpdate(0.9 + 0.05 * np.float64(idx) / len(tot_classes))
        if np.any(instances[class_id] != 0):
            print(f"------ {classes[class_id]} ------")
            node = mrml.vtkMRMLLabelMapVolumeNode()
            node.SetAndObserveImageData(None)
            slicer.util.updateVolumeFromArray(node, instances[class_id])
            node.SetSpacing(referenceSpacing)
            node.Modified()

            volumeOperator = VolumeOperator(node)
            operator = LabelStatistics2D(
                instances[class_id], referenceSpacing, direction=None, is_pore=False, size_filter=0
            )
            df_stats, nlabels = calculate_statistics_on_segments(
                instances[class_id],
                SegmentOperator(operator, volumeOperator.ijkToRasOperator),
                callback=lambda i, total: None,
            )
            if len(df_stats) > 0:
                df_stats = df_stats.set_axis(operator.ATTRIBUTES, axis=1)
                for col in df_stats.select_dtypes(include=["float"]).columns:
                    df_stats[col] = df_stats[col].round(5)

                df_stats["class_op"] = classes[class_id]
                df_props = pd.concat([df_props, df_stats], ignore_index=True)
            else:
                instances[class_id] = 0

    if not df_props.empty and not df.empty:
        df_props = df_props.rename(columns={"label": "label_op"})

        df = df.sort_values(["class", "label"], ignore_index=True)
        df_props = df_props.sort_values(["class_op", "label_op"], ignore_index=True)
        df_final = pd.merge(df, df_props, left_on=["class", "label"], right_on=["class_op", "label_op"])

        excluded_props = [
            "class_op",
            "label_op",
            "pore_size_class",
            "voxelCount",
            "angle_ref_to_max_feret",
            "angle_ref_to_min_feret",
            "ellipse_perimeter",
            "ellipse_area",
            "ellipse_perimeter_over_ellipse_area",
            "gamma",
            "angle",
            "perimeter_over_area",
        ]

        df_final = df_final.drop(excluded_props, axis=1)

        # normalize array and table to be sequential
        for class_id in np.unique(class_ids):
            class_report = df[df["class"] == classes[class_id]].copy()
            old_labels = np.array(class_report["label"])
            class_report.loc[:, "label"] = range(1, len(class_report) + 1)
            df[df["class"] == classes[class_id]] = class_report
            unique_instances = np.zeros(instances[class_id].shape, dtype=np.uint16)
            for i, lab in enumerate(old_labels):
                unique_instances += np.uint16(i + 1) * (instances[class_id] == lab) * (unique_instances == 0)
            instances[class_id] = unique_instances
    else:
        df_final = pd.DataFrame()

    return df_final, instances


def runcli(args):
    progressUpdate(0.0)

    """Read input volumes"""
    inputFile = [file for file in (args.input_volume,) if file is not None]
    volumeNodes = [readFrom(inputFile[0], mrml.vtkMRMLScalarVolumeNode)]

    intersect_bounds = np.zeros(6)
    volumeNodes[0].GetRASBounds(intersect_bounds)
    """ Found commmon boundaries to align inputs """
    for ith in range(1, len(volumeNodes)):
        intersect_bounds = adjustbounds(volumeNodes[ith], intersect_bounds)

    channels = [slicer.util.arrayFromVolume(volume) for volume in volumeNodes]

    """Crop volumes using common boundaries"""
    for i in range(len(channels)):
        channels[i] = crop_to_rasbounds(channels[i], volumeNodes[i], intersect_bounds, rgb=True)

    progressUpdate(0.01)
    ref_shape = np.array([1, *channels[0].shape[:2]])
    valid_axis = np.squeeze(np.argwhere(ref_shape > 1))
    is_2d = np.any(ref_shape == 1)

    params = json.loads(args.xargs)
    conf_thresh = params["conf_thresh"] / 100
    nms_thresh = params["nms_thresh"] / 100

    # Inference parameters
    scale_percent = params["resize_ratio"]
    chunk_size = params.get("chunk_size")
    chunk_overlap = params.get("chunk_overlap")
    chunk_overlap = chunk_overlap / 100.0 if chunk_overlap is not None else 0
    image = channels[0]

    model_path = Path(args.input_model)
    metadata = get_metadata(model_path)
    classes = metadata["outputs"]["y"]["class_names"]

    config = Config.fromstring(metadata["cfg"], file_format=".py")

    device = "cuda:0" if torch.cuda.is_available() else "cpu"

    progressUpdate(0.05)

    # Inference
    start = time.time()
    model = mmdetInference(image, scale_percent, config, model_path, device)
    if chunk_size is None:
        labels, boxes, confidences, class_ids, instances = model.run_inference(conf_thresh, nms_thresh)
    else:
        labels, boxes, confidences, class_ids, instances = model.run_chunked_inference(
            conf_thresh, nms_thresh, chunk_size, chunk_overlap
        )
    end = time.time()
    print(f"Inference: {end - start}")

    del model

    if instances is None:
        progressUpdate(1.00)
        new_instances = np.zeros((len(classes),) + tuple(ref_shape[1:]), dtype=np.uint16)
        writeDataInto(args.output_volume, new_instances, mrml.vtkMRMLLabelMapVolumeNode)
        return

    # Pos-processing: filter broken instances into single ones
    for cls_ind, cls in enumerate(classes):
        unique_instances = np.zeros(tuple((scale_percent * ref_shape[1:]).astype(int)), dtype=np.uint16)
        for i, label_ind in enumerate(np.unique(instances[cls_ind])[1:]):
            mask = instances[cls_ind] == label_ind
            label, num_labels = scipy.ndimage.label(mask)
            if num_labels > 1:
                separadelabels = [(label == k).sum() for k in range(1, num_labels + 1)]
                index = np.argmax(separadelabels) + 1
                mask = label == index
            unique_instances += np.uint16(i + 1) * mask
        instances[cls_ind] = unique_instances

    progressUpdate(0.90)

    # Calculate statistics
    if params["calculate_statistics"]:
        spacing = np.array(volumeNodes[0].GetSpacing())
        scale = 1.0 / scale_percent
        class_names = [classes[idx] for idx in class_ids]
        df = pd.DataFrame(
            {
                "class": class_names,
                "label": labels,
                "width": spacing[0] * scale * boxes[:, 2],
                "height": spacing[1] * scale * boxes[:, 3],
                "confidence": 100 * confidences,
            }
        )
        df["label"] = df["label"].astype(np.int64)
        df, instances = calculate_statistics(df, instances, class_ids, classes, scale, spacing)

        if len(df) != 0 and args.output_table:
            df.to_pickle(args.output_table)

    # Resize output labelmap
    new_instances = np.zeros((len(classes),) + tuple(ref_shape[1:]), dtype=np.uint16)
    for cls_ind, cls in enumerate(classes):
        progressUpdate(0.95 + 0.05 * np.float64(cls_ind) / len(classes))
        new_instances[cls_ind] = resize_mask(ref_shape[1:], instances[cls_ind])

    progressUpdate(1.00)

    writeDataInto(args.output_volume, new_instances, mrml.vtkMRMLLabelMapVolumeNode)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument(
        "--input_model",
        type=str,
        dest="input_model",
        default=None,
        help="Input model file",
    )
    parser.add_argument(
        "-i", "--input_volume", type=str, dest="input_volume", default=None, help="Input LabelMap volume"
    )
    parser.add_argument(
        "-o", "--output_volume", type=str, dest="output_volume", default=None, help="Output LabelMap volume"
    )
    parser.add_argument("-t", "--output_table", type=str, dest="output_table", default=None, help="Output Table")
    parser.add_argument("--xargs", type=str, default="", help="Model configuration string")
    parser.add_argument("--ctypes", type=str, default="", help="Input Color Types")

    parser.add_argument(
        "--returnparameterfile", type=str, default=None, help="File destination to store an execution outputs"
    )

    args = parser.parse_args()

    runcli(args)
