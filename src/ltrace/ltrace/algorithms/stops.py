from dataclasses import dataclass
from typing import Tuple

import cv2
import numpy as np
import pandas as pd
import slicer
from scipy.ndimage import gaussian_filter1d

from ltrace.slicer import helpers
from ltrace.slicer.node_attributes import ImageLogDataSelectable
from ltrace.slicer_utils import dataFrameToTableNode


def fit_line(contour):
    _, eigenvectors, eigenvalues = cv2.PCACompute2(contour.squeeze().astype(np.float32), mean=None)
    eigenvalues = eigenvalues.squeeze()

    linearity = eigenvalues[0] / eigenvalues[1]

    eigenvectors = eigenvectors.squeeze()

    angle = np.arctan2(eigenvectors[0, 1], eigenvectors[0, 0]) * 180 / np.pi
    return angle, linearity


@dataclass
class SegmentStopsParams:
    canny_thresh: float = 160
    blur_size: int = 11
    blur_sigma: float = 2.0


def segment_stops(
    tt: np.ndarray, params: SegmentStopsParams, y_spacing: float = 1.0, y_origin: float = 0.0
) -> Tuple[np.ndarray, dict]:
    original_shape = tt.shape
    tt = tt.squeeze()
    squeezed_shape = tt.shape

    tt = cv2.resize(tt, (0, 0), fx=0.5, fy=0.5)

    row_min = np.percentile(tt, 20, axis=1)
    row_max = np.percentile(tt, 80, axis=1)
    row_min = gaussian_filter1d(row_min, 10)
    row_max = gaussian_filter1d(row_max, 10)
    tt = (tt - row_min[:, None]) / (row_max[:, None] - row_min[:, None])
    tt = np.clip(tt * 255, 0, 255).astype(np.uint8)

    tt = np.concatenate([tt, tt], axis=1)

    blur_size = int(params.blur_size)
    tt = cv2.GaussianBlur(tt, (blur_size, blur_size), params.blur_sigma)

    canny = cv2.Canny(tt, params.canny_thresh, params.canny_thresh * 2)

    sobel_x = cv2.Sobel(canny, cv2.CV_64F, 1, 0, ksize=5)
    sobel_y = cv2.Sobel(canny, cv2.CV_64F, 0, 1, ksize=5)

    angles = np.arctan2(sobel_y, sobel_x) * 180 / np.pi
    gradient_mask = np.logical_and(angles < -25, angles > -95)

    # Offset vertically by 1 pixel
    tmp = np.zeros_like(gradient_mask)
    tmp[:-1, :] = gradient_mask[1:, :]
    gradient_mask = tmp

    gradient_mask = gradient_mask.astype(np.uint8) * 255

    kernel = np.ones((2, 6), np.uint8)
    gradient_mask = cv2.morphologyEx(gradient_mask, cv2.MORPH_CLOSE, kernel)

    angles = (angles + 180) / 2
    angles = np.clip(angles, 0, 179).astype(np.uint8)

    contours, _ = cv2.findContours(gradient_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    labels = np.zeros(gradient_mask.shape, dtype=np.uint16)
    label = 1

    report = []

    area = None
    for cnt in reversed(contours):
        new_area = cv2.contourArea(cnt)

        new_x, new_y, new_w, new_h = cv2.boundingRect(cnt)

        if area and (int(new_area), int(new_y)) == (int(area), int(y)):
            # Skip duplicates coming from well wrap-around
            continue

        if new_area < canny.shape[1] * 0.3:
            continue

        angle, linearity = fit_line(cnt)

        if linearity < 60 or angle < 4 or angle > 50:
            continue

        area = new_area
        x, y, w, h = new_x, new_y, new_w, new_h
        cv2.drawContours(labels, [cnt], 0, label, -1)

        cy = y + h / 2
        # Multiply by 2 because we resized the image
        depth = (2 * cy * y_spacing - y_origin) / 1000
        report.append([depth, round(angle, 1), round(area), round(linearity), label])
        label += 1
    left_half = labels[:, : labels.shape[1] // 2]
    right_half = labels[:, labels.shape[1] // 2 :]
    left_half[left_half == 0] = right_half[left_half == 0]
    labels = left_half
    labels = cv2.resize(labels, (squeezed_shape[1], squeezed_shape[0]), interpolation=cv2.INTER_NEAREST)

    labels = cv2.dilate(labels, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=1)
    labels = np.reshape(labels, original_shape)
    return labels, report


def create_stops_nodes(
    tt_node: slicer.vtkMRMLScalarVolumeNode,
    params: SegmentStopsParams,
    output_prefix: str,
):
    tt = slicer.util.arrayFromVolume(tt_node).astype(np.float32)

    # Image depth axis y is represented by z axis in slicer
    y_spacing = tt_node.GetSpacing()[2]
    y_origin = tt_node.GetOrigin()[2]

    labels, report = segment_stops(tt, params, y_spacing, y_origin)

    labelmap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
    labelmap.SetName(f"{output_prefix} - Stops instances")
    labelmap.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)
    slicer.util.updateVolumeFromArray(labelmap, labels.astype(np.int32))
    labelmap.CopyOrientation(tt_node)
    labelmap.CreateDefaultDisplayNodes()

    color_table = helpers.labelArrayToColorNode(labels, labelmap.GetName() + "_color_table")
    labelmap.GetDisplayNode().SetAndObserveColorNodeID(color_table.GetID())

    table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
    table.SetName(f"{output_prefix} - Stops report")

    df = pd.DataFrame(data=report, columns=["depth (m)", "steepness (°)", "area", "linearity", "label"])
    df = df.sort_values(by=["depth (m)"])
    dataFrameToTableNode(df, table)

    table.SetAttribute("InstanceSegmenter", "ImageLogStops")
    table.AddNodeReferenceID("InstanceSegmenterLabelMap", labelmap.GetID())

    sh_node = slicer.mrmlScene.GetSubjectHierarchyNode()

    parent = sh_node.GetItemParent(sh_node.GetItemByDataNode(tt_node))
    sh_node.SetItemParent(sh_node.GetItemByDataNode(table), parent)
    sh_node.SetItemParent(sh_node.GetItemByDataNode(labelmap), parent)

    return labelmap, table
