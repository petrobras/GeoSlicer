"""
Detect scale ruler and use its color to threshold the image.
https://docs.google.com/presentation/d/1zApaSeLxe_AoBkkb36CEyXir2tht2HFa1imIQaHMvvU/edit?usp=sharing
"""

import cv2
import numpy as np

from itertools import combinations


def image_corners(img):
    """Stitch together the four corners of the image."""
    sx, sy, _ = img.shape
    parts = 4
    sx //= parts
    sy //= parts

    corners = np.zeros((sx * 2, sy * 2, 3), dtype=np.uint8)

    corners[:sx, :sy] = img[:sx, :sy, :3]
    corners[-sx:, :sy] = img[-sx:, :sy, :3]
    corners[:sx, -sy:] = img[:sx, -sy:, :3]
    corners[-sx:, -sy:] = img[-sx:, -sy:, :3]

    return corners


def edge_detect(img):
    img = cv2.GaussianBlur(img, (3, 3), 5)
    img = cv2.Canny(img, 300, 400)

    return img


def line_detect(img):
    # Make horizontal lines less wobbly
    kernel1 = np.array([[-2, -2, 1, 1, -2, -2]]).T / 3
    kernel2 = np.ones((1, 10)) / 3

    img = cv2.filter2D(img, cv2.CV_16S, kernel1, borderType=cv2.BORDER_ISOLATED)
    img = cv2.filter2D(img, cv2.CV_16S, kernel2, borderType=cv2.BORDER_ISOLATED)
    img = (img > 250).astype(np.uint8) * 255

    return cv2.HoughLinesP(img, 1, np.pi / 180, 50, minLineLength=30, maxLineGap=20)


def center_of_rect(lines):
    """Given a list of lines, find a pair of horizontal lines
    that are most likely to be the long edges of the scale
    rectangle and return the center of the rectangle."""

    if lines is None or lines.shape[0] < 2 or lines.shape[0] > 100:
        return None

    lines = lines.squeeze()

    best_diff = 10000000
    best_lines = None

    line_pairs = combinations(lines, 2)
    for pair in line_pairs:
        line_a, line_b = pair

        ax1, ay1, ax2, ay2 = line_a
        bx1, by1, bx2, by2 = line_b

        vdiff = abs(ay1 - by1) + abs(ay2 - by2)
        if vdiff > 100 or vdiff < 4:
            continue

        hdiff = abs(ax1 - bx1) + abs(ax2 - bx2)

        if hdiff < best_diff * vdiff:
            best_diff = hdiff / vdiff
            best_lines = pair

    if best_lines is None:
        return None

    best_lines = np.array(best_lines)
    best_lines = np.concatenate(np.split(best_lines, 2, axis=1))
    center_point = best_lines.mean(axis=0).astype(int)
    return best_diff, center_point


def color_threshold(img, color):
    """Given an image and a color, return a binary image of only that color
    and crop the relevant area."""

    margin = 30
    low_color = np.clip(color.astype(np.int16) - margin, 0, 255).astype(np.uint8)
    high_color = np.clip(color.astype(np.int16) + margin, 0, 255).astype(np.uint8)
    segment = cv2.inRange(img, low_color, high_color) == 255

    coords = np.argwhere(segment)
    x_min, y_min = coords.min(axis=0)
    x_max, y_max = coords.max(axis=0)
    return (~segment[x_min : x_max + 1, y_min : y_max + 1]).astype(np.uint8) * 255


def detect_scale(img):
    img_h = edge_detect(img)
    img_v = np.transpose(img_h)

    candidates = []
    candidate_h = center_of_rect(line_detect(img_h))
    candidate_v = center_of_rect(line_detect(img_v))

    if candidate_h is not None:
        candidates.append(candidate_h)
    if candidate_v is not None:
        best_diff, center_point = candidate_v
        candidate_v = best_diff, np.flip(center_point)
        candidates.append(candidate_v)

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])

    for diff, point in candidates:
        color = img[point[1], point[0]]
        segment = color_threshold(img, color)
        segment_area = segment.shape[0] * segment.shape[1]
        img_area = img.shape[0] * img.shape[1]

        if segment_area / img_area > 0.2:
            continue
        else:
            return segment

    return None
