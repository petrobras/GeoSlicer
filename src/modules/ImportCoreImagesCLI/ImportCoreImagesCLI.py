#! /usr/bin/env python-real

import vtk

import logging
import numpy as np
import itertools
import pickle
import cv2
from pathlib import Path
from ltrace.units import global_unit_registry as ureg
from ltrace.image.segmentation import TF_RGBImageArrayBinarySegmenter
from ltrace.assets import get_asset
from ltrace.cli_progress import ProgressBarClient, StoppedError


def find_plug_holes(images_folder, progress_bar):
    results = []

    all_images = list(
        itertools.chain(
            images_folder.glob("*.jpg"),
            images_folder.glob("*.jpeg"),
            images_folder.glob("*.png"),
        )
    )
    all_images.sort(key=lambda x: x.stem)

    progress_bar.configure(1 + len(all_images), "Loading")

    if progress_bar.should_stop:
        raise StoppedError()

    model = TF_RGBImageArrayBinarySegmenter(get_asset("unet-binary-segop.h5"))
    for image in all_images:
        results.append([image, _find_plug_holes_in_file(image, model, progress_bar)])

    progress_bar.progress(progress_bar.steps, "Finished")

    return results


def _find_plug_holes_in_file(file, model, progress_bar):
    img = cv2.cvtColor(cv2.imread(str(file), 1), cv2.COLOR_BGR2RGB)
    template_start_y, cores = _split_cores(img)

    pixel_size = (10 * ureg.centimeter) / (280 * ureg.pixel)
    core_size = 90 * ureg.centimeter

    current_depth = 0 * ureg.centimeter

    core_results = []

    progress_value = progress_bar.next_progress_step()
    core_progress_step = 1 / len(cores)

    # save_folder = Path(r"C:\Users\Felipe Silveira\Desktop\Output")
    # rgb_2_bgr = lambda im: cv2.cvtColor(im, cv2.COLOR_RGB2BGR)

    for i, core in enumerate(cores):
        progress_bar.progress(progress_value + i * core_progress_step, "{} - Core {}".format(file.name, 1 + i))
        core_height = core.shape[0]

        if progress_bar.should_stop:
            raise StoppedError()

        # cv2.imwrite(str(save_folder / ("core_" + str(i) + ".png")), rgb_2_bgr(core))
        core_begin_y = _white_out_background(core, model)
        # cv2.imwrite(str(save_folder / ("core_whiteed_out" + str(i) + ".png")), rgb_2_bgr(core))
        top_offset = core_begin_y - template_start_y

        circles_centers = []
        for center_x, center_y, radius in _find_plug_holes(core, i):
            if center_y - radius <= core_begin_y or center_y + radius >= core_height:
                continue

            # cv2.circle(core, (center_x, int(center_y)), radius, (255, 0, 0), thickness=3)

            center_y = (center_y - core_begin_y) * ureg.pixel
            circles_centers.append(current_depth + center_y * pixel_size)

        # cv2.imwrite(str(save_folder / ("core_result_" + str(i) + ".png")), rgb_2_bgr(core))
        core_results.append(((current_depth, current_depth + core_size), circles_centers))
        current_depth += core_size

    return core_results


def _split_cores(img):
    height, width, _ = img.shape

    image_containing_scale = cv2.cvtColor(img[:, width - 100 :], cv2.COLOR_RGB2GRAY)
    _, image_containing_scale = cv2.threshold(image_containing_scale, 245, 255, cv2.THRESH_BINARY)

    scale_template = np.zeros((280 * 10, 27), dtype=image_containing_scale.dtype)
    for i in range(0, 10, 2):
        scale_template[280 * i : 280 * (i + 1), :] = 255

    result = cv2.matchTemplate(image_containing_scale, scale_template, cv2.TM_SQDIFF)

    # (x,y) coordinates instead of opencv's (y,x)
    _, _, template_top_left, _ = cv2.minMaxLoc(result)
    # convert to (y,x)
    template_top_left = tuple(reversed(template_top_left))
    template_bottom_right = (
        template_top_left[0] + scale_template.shape[0],
        template_top_left[1] + scale_template.shape[1],
    )

    scale_y_top = template_top_left[0]

    cut_top_left = (0, 42)
    cut_bottom_right = (
        template_bottom_right[0],
        width - image_containing_scale.shape[1] + template_top_left[1],
    )

    img = img[cut_top_left[0] : cut_bottom_right[0], cut_top_left[1] : cut_bottom_right[1]]
    height, width, _ = img.shape

    number_of_cores = width // 450
    spacing_pixels = 100 * (number_of_cores - 1)
    core_pixels = width - spacing_pixels

    single_core_pixels = core_pixels // number_of_cores
    single_spacing_pixels = spacing_pixels // (number_of_cores - 1)
    current_x = 0

    cores = []
    for _ in range(number_of_cores):
        cut_core = img[0:height, current_x : current_x + single_core_pixels]
        cores.append(cut_core)
        current_x += single_core_pixels + single_spacing_pixels

    return scale_y_top, cores


def _white_out_background(core, model):
    mask = model.predict(core)
    mask = mask.reshape(np.shape(core)[:2])

    kernel = np.ones((15, 15), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    mask_top = 0
    height, width = np.shape(mask)
    for i in range(height):
        if np.sum(mask[i]) > 0:
            mask_top = i
            break

    white = [255, 255, 255]
    core[mask == 0] = white
    core[0 : mask_top + 1, :] = white

    return mask_top


def _find_plug_holes(core, i):
    # save_folder = Path(r"C:\Users\Felipe Silveira\Desktop\Output")
    # gray_2_bgr = lambda im: cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)

    core_height, core_width, _ = core.shape
    core = cv2.GaussianBlur(core, (9, 9), 2, 2)
    core_gray = cv2.cvtColor(core, cv2.COLOR_RGB2GRAY)
    # cv2.imwrite(str(save_folder / ("core_blur" + str(i) + ".png")), gray_2_bgr(core_gray))

    _, binary_mask = cv2.threshold(core_gray, 45, 255, cv2.THRESH_BINARY_INV)
    # cv2.imwrite(str(save_folder / ("core_masked" + str(i) + ".png")), gray_2_bgr(binary_mask))

    kernel = np.ones((15, 15), np.uint8)
    binary_mask = cv2.morphologyEx(binary_mask, cv2.MORPH_OPEN, kernel)

    binary_mask[:, : core_width // 2 - 100] = [0]
    binary_mask[:, core_width // 2 + 100 :] = [0]
    binary_mask[: int(0.01 * core_height), :] = [0]
    binary_mask[int(0.93 * core_height) :, :] = [0]
    binary_mask = cv2.morphologyEx(binary_mask, cv2.MORPH_OPEN, kernel)
    # cv2.imwrite(str(save_folder / ("core_cleaned_" + str(i) + ".png")), gray_2_bgr(binary_mask))

    circles = cv2.HoughCircles(
        binary_mask,
        cv2.HOUGH_GRADIENT,
        dp=1,
        minDist=core_height // 4.5,
        param1=150,
        param2=10,
        minRadius=20,
        maxRadius=80,
    )

    if circles is None:
        return []

    circles = circles[0, :]

    # core_color = gray_2_bgr(binary_mask)
    # for center_x, center_y, radius in circles:
    #    cv2.circle(core_color, (center_x, int(center_y)), radius, (0, 0, 255), thickness=3)
    # cv2.imwrite(str(save_folder / ("core_found" + str(i) + ".png")), core_color)

    return circles


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 4:
        logging.error(
            "Wrong number of parameters. Expected call: ImportCoreImagesCLI <folder with images> <output file> <progress_file>"
        )
        sys.exit(1)

    images_folder = Path(sys.argv[1]).absolute()
    output_file = Path(sys.argv[2]).absolute()
    zmq_port = int(sys.argv[3])

    with ProgressBarClient(zmq_port) as progress_bar:
        if not images_folder.is_dir():
            raise RuntimeError("Images folder isn't valid")

        result = find_plug_holes(images_folder, progress_bar)

        with open(output_file, "wb") as f:
            f.write(pickle.dumps(result))
