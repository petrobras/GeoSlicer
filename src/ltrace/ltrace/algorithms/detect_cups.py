import numpy as np
import cv2
import logging
from scipy import signal

EROSION_AMOUNT = 10
COMPENSATION = 14


def otsu_threshold(img):
    normalized = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    normalized = cv2.GaussianBlur(normalized, (5, 5), 0)
    threshold_image = cv2.threshold(normalized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    kernel = np.ones((3, 3), np.uint8)
    threshold_image = cv2.erode(threshold_image, kernel, iterations=EROSION_AMOUNT)
    contours = cv2.findContours(threshold_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    contour = max(contours, key=cv2.contourArea)
    mask = np.zeros_like(threshold_image)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    mask &= threshold_image
    return mask


def z_range(std_signal):
    std_signal = np.convolve(std_signal, np.ones(11) / 11, mode="same")
    sigma = 0.2
    peaks = np.argmax(std_signal > sigma), std_signal.shape[0] - np.argmax(std_signal[::-1] > sigma)
    return peaks


def normalize(array):
    return (array - array.min()) / (array.max() - array.min())


def detect_rock_circle(array):
    """
    WHAT:
        detect a rock circle in the array

    HOW:
        Over the Z axis, divide the middle portion into 8 blocks
        Calculate the standard deviation and median of each block
        Combine them all and take the geometric mean
        Otsu threshold, erode, largest island, Hough circle

    WHY:
        std: rock is usually more heterogeneous than the background
        median: rock usually has higher attenuation
        geometric mean: we eliminate features that only show up in a few blocks,
            such as smaller teflon pieces supporting the rock
    """

    N_BLOCKS = 8
    START = 0.3
    LENGTH = 0.4

    block_size_fraction = LENGTH / N_BLOCKS
    z_size = array.shape[0]
    block_size_z = round(array.shape[0] * block_size_fraction)

    acc = np.ones((array.shape[1], array.shape[2]))
    for i in range(N_BLOCKS):
        start = round((START + i * block_size_fraction) * z_size)
        block = array[start : start + block_size_z]
        std_z = normalize(block.std(axis=0))
        median_z = np.median(block, axis=0)
        median_z /= median_z.max()
        combined = np.sqrt(std_z * median_z)
        acc *= combined
    geometric_mean = np.power(acc, 1 / 8)

    mask = otsu_threshold(geometric_mean)
    min_radius = round(array.shape[1] * 0.15)
    max_radius = round(array.shape[1] * 0.5)
    circles = cv2.HoughCircles(
        mask, cv2.HOUGH_GRADIENT, 1, 20, param1=200, param2=10, minRadius=min_radius, maxRadius=max_radius
    )

    if circles is None:
        return None

    # Find the circle with best accuracy (within the top 5 detected)
    best_circle = None
    best_loss = 999999
    for circle in circles[0][:5]:
        x, y, r = circle
        x = round(x)
        y = round(y)
        r = round(r + COMPENSATION)
        circle_mask = np.zeros_like(mask)
        cv2.circle(circle_mask, (x, y), r, 255, -1)
        xor = circle_mask ^ mask
        loss = np.count_nonzero(xor == 255)
        if loss < best_loss:
            best_loss = loss
            best_circle = circle

    x, y, r = best_circle
    r += COMPENSATION
    return x, y, r


def detect_rock_height(array, circle_center_x, circle_radius):
    """
    WHAT:
        detect the height extent of the rock cylinder

    HOW:
        Take a thin block in the middle of the cylinder
        Std over Y axis, median over Y axis
        Difference of gaussians of std, combined with median
        Turn into smoothed 1D signal, find first and last points above a threshold

    WHY:
        std: rock is usually more heterogeneous than the background
        median: rock usually has higher attenuation
        diff of gaussians: highlight variation in other axes
        geometric mean: highlight regions that are both heterogeneous and high attenuation
    """
    x = circle_center_x
    r = circle_radius

    y_size = array.shape[1]
    block = array[:, round(y_size * 0.48) : round(y_size * 0.52), round(x - r * 0.8) : round(x + r * 0.8)]
    std_y = block.std(axis=1)
    median_y = np.median(block, axis=1)

    std_y = normalize(std_y)
    median_y = median_y / median_y.max()

    gauss1 = cv2.GaussianBlur(std_y, (11, 11), 0)
    gauss2 = cv2.GaussianBlur(std_y, (51, 51), 0)
    diff1 = np.abs(std_y - gauss1)
    diff2 = np.abs(gauss1 - gauss2)
    combined = np.sqrt((diff1 + diff2) * median_y)
    min_ = np.percentile(combined, 1)
    max_ = np.percentile(combined, 99)
    combined = normalize(np.clip(combined, min_, max_))
    std_xy = combined.mean(axis=1)
    z_min, z_max = z_range(std_xy)

    return z_min, z_max


def detect_rock_cylinder(array):
    should_downscale = min(array.shape) > 500

    if should_downscale:
        array = array[::2, ::2, ::2]

    circle = detect_rock_circle(array)
    if circle is None:
        return None
    x, y, r = circle
    z_min, z_max = detect_rock_height(array, x, r)
    cylinder = [x, y, r, z_min, z_max]

    if should_downscale:
        cylinder = [v * 2 for v in cylinder]
    return cylinder


PADDING = 15


def crop_cylinder(array, cylinder):
    x, y, r, z_min, z_max = cylinder
    min_ = array.min()
    x_min, x_max = round(x - r), round(x + r)
    y_min, y_max = round(y - r), round(y + r)
    z_min, z_max = round(z_min), round(z_max)
    x_min = max(x_min, 0)
    y_min = max(y_min, 0)
    z_min = max(z_min, 0)
    array = array[z_min:z_max, y_min:y_max, x_min:x_max]

    xx, yy = np.meshgrid(np.arange(array.shape[2]), np.arange(array.shape[1]))
    dist = np.sqrt((xx - r) ** 2 + (yy - r) ** 2)
    mask = dist <= r
    mask = mask[np.newaxis, ...]
    array = (array * mask) + (~mask * min_)

    array = np.pad(array, ((0, 0), (PADDING, PADDING), (PADDING, PADDING)), mode="constant", constant_values=min_)
    return array


def get_origin_offset(cylinder):
    x, y, r, z_min, z_max = cylinder
    r += PADDING
    return -round(x - r), -round(y - r), round(z_min)


def isolated_cups_slice(array, cylinder):
    x, y, r, z_min, z_max = cylinder
    cup_slice = array[z_min:z_max, array.shape[1] // 2, :].squeeze()
    cup_left = cup_slice[:, : round(x - r)]
    cup_right = cup_slice[:, round(x + r) :]
    cup_right = np.flip(cup_right, axis=1)
    return cup_left, cup_right


def detect_bars(cup):
    img = cv2.GaussianBlur(cup, (3, 31), 0)
    min_ = np.percentile(img, 5)
    max_ = np.percentile(img, 95)
    norm = img - min_
    norm = norm * 255 / (max_ - min_)
    norm = np.clip(norm, 0, 255).astype(np.uint8)
    img = cv2.Canny(norm, 50, 100)

    lines_p = cv2.HoughLinesP(img, 1, np.pi / 180, 100, maxLineGap=10)
    if lines_p is None:
        return None

    acc = np.zeros(img.shape[1])
    for line in lines_p:
        x1, y1, x2, y2 = line[0]
        if abs((x2 - x1) / (y2 - y1)) < 0.05:
            x = round((x1 + x2) / 2)
            acc[x] += abs(y2 - y1)

    acc /= img.shape[0]
    acc = np.convolve(acc, np.ones(3) / 3, mode="same")
    boundaries = signal.find_peaks(acc, prominence=0.05, distance=8)[0]

    boundaries = [0] + list(boundaries) + [img.shape[1]]
    values = []
    for a, b in zip(boundaries, boundaries[1:]):
        a = max(a, 0)
        b = min(b, cup.shape[1])
        if b - a < 8:
            continue
        a += 3
        b -= 3
        part = cup[:, a:b]

        # Bars bleed into each other, so we use median to get a representative value
        values.append(np.median(part))

    return values


def greatest_decreasing_subtriplet(sequence):
    branches = [tuple()]
    for value in sequence:
        new = []
        for branch in branches:
            if not branch or (value < branch[-1] and len(branch) < 3):
                new.append(branch + (value,))
        branches.extend(new)
    branches = [branch for branch in branches if len(branch) == 3]
    if not branches:
        logging.error("No decreasing subtriplet found")
        return None
    best = max(branches)
    if len(best) == 3:
        return best
    return None


def reference_values(bars):
    if not bars:
        return None
    if len(bars) > 20:
        return None
    return greatest_decreasing_subtriplet(bars)


def quartz_ratio(refs):
    return (refs[1] - refs[2]) / (refs[0] - refs[2])


def detect_cups_from_sides(cup_left, cup_right):
    left_bars = detect_bars(cup_left)
    left_values = reference_values(left_bars)
    right_bars = detect_bars(cup_right)
    right_values = reference_values(right_bars)

    logging.debug(f"left_bars: {left_bars}")
    logging.debug(f"left_values: {left_values}")
    logging.debug(f"right_values: {right_values}")
    logging.debug(f"right_bars: {right_bars}")

    if left_values:
        left_quartz = quartz_ratio(left_values)
        if left_quartz < 0.27 or left_quartz > 0.42:
            left_values = None

    if right_values:
        right_quartz = quartz_ratio(right_values)
        if right_quartz < 0.27 or right_quartz > 0.42:
            right_values = None

    if left_values is None and right_values is None:
        return None

    if left_values is not None and right_values is not None:
        return [(l + r) / 2 for l, r in zip(left_values, right_values)]

    return left_values or right_values


def detect_cups(array, cylinder):
    cup_left, cup_right = isolated_cups_slice(array, cylinder)
    return detect_cups_from_sides(cup_left, cup_right)


def full_detect(array, callback=lambda *args: None):
    """Detects cups and isolates rock cylinder"""
    callback(0, "Detecting cylinder")
    cylinder = detect_rock_cylinder(array)
    if cylinder is None:
        return None, None, None
    logging.debug(f"x, y, r, z0, z1 = {cylinder}")

    callback(50, "Cropping cylinder")
    rock = crop_cylinder(array, cylinder)
    callback(70, "Detecting cups")
    cup_left, cup_right = isolated_cups_slice(array, cylinder)
    refs = detect_cups_from_sides(cup_left, cup_right)
    if refs:
        logging.debug(f"(Q - T) / (A - T) = {quartz_ratio(refs)}")
    return rock, refs, cylinder
