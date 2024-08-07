#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

from __future__ import print_function

import json
import os
import shutil
import sys
from dataclasses import dataclass

import vtk
import slicer
import slicer.util
import mrml

import numpy as np
from numpy.random import RandomState
import pickle
import cv2
from PIL import Image

from skimage.filters import gaussian
from scipy.ndimage import gaussian_filter, uniform_filter
from scipy import signal
from sklearn.ensemble import RandomForestClassifier

from ltrace import transforms
from Minkowsky.minkowsky import minkowsky_filter, minkowsky_filter_2d
from ltrace.algorithms.CorrelationDistance.CorrelationDistance import CorrelationDistance, interpolate_spline
from ltrace.algorithms.gabor import get_gabor_kernels

DEFAULT_SETTINGS = "settings.json"


def progressUpdate(value):
    """
    Progress Bar updates over stdout (Slicer handles the parsing)
    """
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


def gabor(img, sigma, lambd, n_rotations, size):
    ref_shape = np.array(img.shape)
    is_2d = len(ref_shape) == 2

    if is_2d:
        params = {
            "sigma": sigma,
            "lambd": lambd,
            "gamma": 1.0,
            "psi": 0.0,
            "ktype": cv2.CV_32F,
        }

        while size > 1:
            try:
                fimg = []
                for kern in get_gabor_kernels(sigma, lambd, n_rotations, size, is_2d):
                    convolution = cv2.filter2D(img.astype(np.float32), cv2.CV_32F, kern)
                    fimg.append(convolution)

                return fimg, size
            except MemoryError:
                size = size // 2
                print(
                    f"Reducing the size of gabor kernels to {size} px, since the RAM was not suficient to do 4*sigma."
                )

    else:
        while size > 1:
            try:
                kernels = get_gabor_kernels(sigma, lambd, n_rotations, size, is_2d)
                fimg = [signal.convolve(img.astype(np.float32), kern, mode="same") for kern in kernels]

                return fimg, size
            except MemoryError:
                size = size // 2
                print(
                    f"Reducing the size of gabor kernels to {size} px, since the RAM was not suficient to do 4*sigma."
                )


def minkowsky(img, kernel_size, threshold):
    ref_shape = np.array(img.shape)
    is_2d = len(ref_shape) == 2

    max_value = img.max()
    binary = (img > threshold * max_value).astype(np.uint16)
    # threshold_value, binary = cv2.threshold(img, threshold * max_value, max_value, cv2.THRESH_BINARY)
    # binary = (binary / binary.max()).astype(np.uint16)

    return minkowsky_filter_2d(binary, kernel_size) if is_2d else minkowsky_filter(binary, kernel_size)


def winVar(img, wlen):
    # Variance filter
    img = img.astype(np.float32)
    wlen = round(wlen)
    wmean, wsqrmean = (cv2.boxFilter(x, -1, (wlen, wlen), borderType=cv2.BORDER_REFLECT) for x in (img, img * img))
    return wsqrmean - wmean * wmean


def winVar3d(img, wlen):
    # Variance filter
    img = img.astype(np.float32)
    wlen = round(wlen)
    wmean, wsqrmean = (uniform_filter(x, size=wlen, mode="reflect") for x in (img, img * img))
    return wsqrmean - wmean * wmean


def adjustbounds(volume, bounds):
    new_bounds = np.zeros(6)
    volume.GetRASBounds(new_bounds)
    # intersect bounds by getting max of lower bounds and min of upper
    new_bounds[0::2] = np.maximum(new_bounds[0::2], bounds[0::2])  # max of lower bounds
    new_bounds[1::2] = np.minimum(new_bounds[1::2], bounds[1::2])  # min of upper bounds
    return new_bounds


def variogram(component_name, kernel_size, image, spacing, initial_progress_value, final_progress_value, report_file):
    unit_size = kernel_size // 2
    try:
        output_data, output_spacing = CorrelationDistance.calculate_correlation(
            image,
            spacing,
            [kernel_size] * len(image.shape),
            [unit_size] * len(image.shape),
            initial_progress_value,
            (final_progress_value + initial_progress_value) / 2,
        )
    except RuntimeError as e:
        with open(report_file, "w") as returnFile:
            returnFile.write("variogramerror={}".format(str(e)))
        return Component(component_name, image)

    output_data = np.nan_to_num(output_data)
    output_data, output_spacing = interpolate_spline(image.shape, spacing, output_data)
    progressUpdate(final_progress_value)
    padding = np.array(image.shape) - np.array(output_data.shape)
    pad_width = ()
    for axis, margin in enumerate(padding):
        if margin >= 0:
            pad_width += ((0, margin),)
        else:
            output_data = np.delete(output_data, slice(0, abs(margin)), axis)
            pad_width += ((0, 0),)
    output_padded_data = np.pad(output_data, pad_width, mode="edge")
    return Component(component_name, output_padded_data)


def rescale(filters, out_type=np.uint16):
    """
    Rescale filters by setting the quantile of 2% as
    minimum and quantile of 98% as maximum.
    """
    fmin = np.quantile(filters, 0.02)
    fmax = np.quantile(filters, 0.98)
    max_value = np.iinfo(out_type).max
    filters_quant = np.array((filters - fmin) * max_value / (fmax - fmin))
    filters_quant = np.clip(filters_quant, 0, max_value)
    return filters_quant.astype(out_type)


class RGBImageTargets:
    def __init__(self, image, spacing, palette=None, use_hsv=False):
        if image.ndim == 4:
            image = np.squeeze(image)
        self.pil_quantized = Image.fromarray(image, "RGB").quantize(colors=256, method=2, dither=0, palette=palette)
        self.quantized = np.array(self.pil_quantized, dtype=np.uint8)
        self.grayscale = image.mean(axis=-1)
        self.image = image if use_hsv is False else cv2.cvtColor(image.astype(np.float32), cv2.COLOR_RGB2HSV)
        self.spacing = spacing
        self.use_hsv = use_hsv
        self.filters = (2, 4, 8, 16, 32)
        self.rng = RandomState(5431)

    def reduced(self):
        return Component("reduced", self.quantized)

    def channels(self):
        yield Component("channels_0", self.image[:, :, 0])
        yield Component("channels_1", self.image[:, :, 1])
        yield Component("channels_2", self.image[:, :, 2])

    def gaussians(self, radius=1):
        for i, sigma in enumerate([1, *self.filters]):
            if sigma * 4 <= radius:
                yield Component(f"gaussian_{i}", gaussian(self.quantized, sigma, preserve_range=True))
            else:
                print("Missed filter...you have some room for improvement, increase the radius parameter")
                break

    def customized(self, **kwargs):
        print("Using filters: ")

        custom_filters = kwargs.get("filters", {"petrobras": True})
        report_file = kwargs.get("report")

        total_filters = 0
        total_filters += 1  # Temporary fix to avoid getting to 100% before predict
        for filter_func in custom_filters.keys():
            if filter_func in ("raw", "quantized", "petrobras"):
                total_filters += 1
            elif filter_func == "variogram":
                total_filters += 3
            else:
                multiplicity = 1
                for param in custom_filters[filter_func].keys():
                    multiplicity *= len(custom_filters[filter_func][param])
                total_filters += multiplicity

        filter_index = 0

        if "raw" in custom_filters:
            if custom_filters["raw"] == True:
                yield from self.channels()
                filter_index += 1
                progressUpdate(filter_index / (total_filters + 1))

        if "quantized" in custom_filters:
            if custom_filters["quantized"] == True:
                yield self.reduced()
                filter_index += 1
                progressUpdate(filter_index / (total_filters + 1))

        if "petrobras" in custom_filters:
            if custom_filters["petrobras"] == True:
                yield from self.channels()

                yield self.reduced()

                yield from self.gaussians(radius=30)

                filter_index += 1
                progressUpdate(filter_index / (total_filters + 1))

        if "gaussian" in custom_filters:
            for i, sigma in enumerate(custom_filters["gaussian"]["sigma"]):
                print(f"gaussian with sigma={sigma} px")
                for ch in range(3):
                    filters = gaussian(self.image[..., ch], sigma, preserve_range=True)
                    yield Component(f"gaussian{i}_{ch}", rescale(filters))
                filter_index += 1
                progressUpdate(filter_index / (total_filters + 1))

        if "winvar" in custom_filters:
            for i, sigma in enumerate(custom_filters["winvar"]["sigma"]):
                print(f"winvar with sigma={sigma} px")
                filters = winVar(self.grayscale, sigma)
                yield Component(f"winvar{i}", rescale(filters))
            filter_index += 1
            progressUpdate(filter_index / (total_filters + 1))

        if "gabor" in custom_filters:
            component_index = 0
            for lambd in custom_filters["gabor"]["lambda"]:
                for sigma in custom_filters["gabor"]["sigma"]:
                    print(f"gabor with sigma={sigma} px and lambda={lambd} px")
                    size = int(4 * sigma)
                    n_rotations = custom_filters["gabor"]["rotations"][0]
                    fimgs, final_size = gabor(self.image.mean(axis=2), sigma, lambd, n_rotations, size)
                    for fimg in fimgs:
                        yield Component(f"gabor{component_index}", rescale(fimg))
                        component_index += 1
                    filter_index += 1
                    progressUpdate(filter_index / (total_filters + 1))

                    if size != final_size:
                        with open(report_file, "w") as returnFile:
                            returnFile.write(
                                f"report=The available physical memory in your computer was not suficient to run a gabor kernel with the default size=4*sigma={size} px, so {final_size} px was used. You may be seeing a result that is not changing because of this scale. Consider decrease the size of sigma for obtain a different result."
                            )

        if "minkowsky" in custom_filters:
            component_index = 0
            progressUpdate(0)
            for kernel_size in custom_filters["minkowsky"]["kernel_size"]:
                if not kernel_size % 2:
                    kernel_size += 1
                for threshold in custom_filters["minkowsky"]["threshold"]:
                    print(f"minkowsky with kernel={kernel_size} and threshold={threshold}")
                    fimg = minkowsky(rescale(self.grayscale), kernel_size, threshold)

                    for i in range(fimg.shape[-1]):
                        yield Component(f"minkowsky{component_index}", fimg[:, :, i])
                        component_index += 1
                    filter_index += 1
                    progressUpdate(filter_index / (total_filters + 1))

        if "variogram" in custom_filters:
            kernel_size = custom_filters["variogram"]["kernel_size"][0]
            initial_progress_value = filter_index / float(total_filters)
            final_progress_value = (filter_index + 1) / float(total_filters)
            yield variogram(
                f"variogram",
                kernel_size,
                self.grayscale,
                self.spacing,
                initial_progress_value,
                final_progress_value,
                report_file,
            )
            filter_index += 1


class ScalarImageTargets:
    def __init__(self, image, spacing):
        if image.ndim == 4:
            image = np.squeeze(image)
        self.image = image
        self.spacing = spacing
        self.filters = (2, 4, 8, 16, 32)

    def reduced(self):
        return Component("reduced", gaussian_filter(self.image, 1))

    def channels(self):
        return [Component("channel", np.array(self.image, copy=True))]

    def gaussians(self, radius=1):
        for i, sigma in enumerate([1, *self.filters]):
            if sigma * 4 <= radius:
                yield Component(f"gaussian{i}", gaussian_filter(self.image, sigma))
            else:
                print("Missed filter...you have some room for improvement, increase the radius parameter")
                break

    def customized(self, **kwargs):
        print("Using filters: ")

        custom_filters = kwargs.get("filters", {"petrobras": True})
        report_file = kwargs.get("report")

        total_filters = 0
        total_filters += 1  # Temporary fix to avoid getting to 100% before predict
        for filter_func in custom_filters.keys():
            if filter_func in ("raw", "petrobras", "quantized"):
                total_filters += 1
            else:
                multiplicity = 1
                for param in custom_filters[filter_func].keys():
                    multiplicity *= len(custom_filters[filter_func][param])
                total_filters += multiplicity

        filter_index = 0

        has_raw = custom_filters.get("raw", False)
        has_quantized = custom_filters.get("quantized", False)

        if has_raw or has_quantized:
            yield Component("raw", rescale(np.array(self.image, copy=True)))
            filter_index += 1
            progressUpdate(filter_index / (total_filters + 1))

        if "petrobras" in custom_filters:
            if custom_filters["petrobras"] == True:
                yield from self.channels()

                yield self.reduced()

                yield from self.gaussians(radius=30)

                filter_index += 1
                progressUpdate(filter_index / (total_filters + 1))

        if "gaussian" in custom_filters:
            for i, sigma in enumerate(custom_filters["gaussian"]["sigma"]):
                print(f"gaussian with sigma={sigma} px")
                filters = gaussian_filter(self.image, sigma)
                yield Component(f"gaussian{i}", rescale(filters))
                filter_index += 1
                progressUpdate(filter_index / (total_filters + 1))

        if "winvar" in custom_filters:
            for i, sigma in enumerate(custom_filters["winvar"]["sigma"]):
                print(f"winvar with sigma={sigma} px")
                filters = winVar3d(self.image, sigma)
                yield Component(f"winvar{i}", rescale(filters))
                filter_index += 1
                progressUpdate(filter_index / (total_filters + 1))

        if "gabor" in custom_filters:
            component_index = 0
            for lambd in custom_filters["gabor"]["lambda"]:
                for sigma in custom_filters["gabor"]["sigma"]:
                    print(f"gabor with sigma={sigma} px and lambda={lambd} px")
                    size = int(4 * sigma)
                    n_rotations = custom_filters["gabor"]["rotations"][0]
                    fimgs, final_size = gabor(self.image, sigma, lambd, n_rotations, size)
                    for fimg in fimgs:
                        yield Component(f"gabor{component_index}", rescale(fimg))
                        component_index += 1
                    filter_index += 1
                    progressUpdate(filter_index / (total_filters + 1))

                    if size != final_size:
                        with open(report_file, "w") as returnFile:
                            returnFile.write(
                                f"report=The available physical memory in your computer was not suficient to run a gabor kernel with the default size=4*sigma={size} px, so {final_size} px was used. You may be seeing a result that is not changing because of this scale. Consider decrease the size of sigma for obtain a different result.\n"
                            )

        if "minkowsky" in custom_filters:
            component_index = 0
            progressUpdate(0)
            for kernel_size in custom_filters["minkowsky"]["kernel_size"]:
                if not kernel_size % 2:
                    kernel_size += 1
                for threshold in custom_filters["minkowsky"]["threshold"]:
                    print(f"minkowsky with kernel_size={kernel_size} and threshold={threshold}")
                    fimg = minkowsky(rescale(self.image), kernel_size, threshold)

                    if fimg.ndim == 4:
                        for i in range(fimg.shape[-1]):
                            yield Component(f"minkowsky{component_index}", fimg[:, :, :, i])
                            component_index += 1
                    elif fimg.ndim == 3:
                        for i in range(fimg.shape[-1]):
                            yield Component(f"minkowsky{component_index}", fimg[:, :, i])
                            component_index += 1

                    filter_index += 1
                    progressUpdate(filter_index / (total_filters + 1))

        if "variogram" in custom_filters:
            kernel_size = custom_filters["variogram"]["kernel_size"][0]
            initial_progress_value = filter_index / float(total_filters)
            final_progress_value = (filter_index + 1) / float(total_filters)
            yield variogram(
                "variogram",
                kernel_size,
                self.image,
                self.spacing,
                initial_progress_value,
                final_progress_value,
                report_file,
            )
            filter_index += 1


@dataclass
class Component:
    filter_type: str
    image: np.ndarray
    image_index: int = -1


def prepare(channels, spacing, **kwargs):
    components = []
    for i, chan in enumerate(channels):
        if chan.shape[-1] == 3:
            palette = kwargs.get("palette")
            target = RGBImageTargets(chan, spacing, palette, use_hsv=True)
        else:
            target = ScalarImageTargets(chan, spacing)

        for comp in target.customized(**kwargs):
            comp.image_index = i
            components.append(comp)

    return target, components


# @numba.njit
def select_first_guess_2d(components, locations):
    seeds = np.zeros((len(locations), len(components)), dtype=np.float64)
    for i, row in enumerate(locations):
        for j, comp in enumerate(components):
            try:
                seeds[i, j] = comp[int(row[0]), int(row[1])]
            except:
                pass
    return seeds


# @numba.njit
def select_first_guess_3d(components, locations):
    seeds = np.zeros((len(locations), len(components)))
    for i, row in enumerate(locations):
        for j, comp in enumerate(components):
            seeds[i, j] = comp[int(row[0]), int(row[1]), int(row[2])]
    return seeds


def select_first_guess(is_2d, *args):
    return select_first_guess_2d(*args) if is_2d else select_first_guess_3d(*args)


def rf_fit(components, annotations, is_2d, **kwargs):
    locations, labels = annotations
    first_guess = select_first_guess(is_2d, [c.image for c in components], locations)
    random_seed = kwargs.get("random_seed")

    model = RandomForestClassifier(
        n_estimators=64,
        n_jobs=4,
        warm_start=False,
        random_state=(RandomState(5423) if random_seed == None else random_seed),
        bootstrap=True,
        oob_score=True,
        min_impurity_decrease=0.001,
        class_weight="balanced",
    )

    model.fit(first_guess, labels)
    return model


def rf_predict(components, model):
    data = np.hstack([np.reshape(c.image, (c.image.size, 1)) for c in components]).astype(float)

    result = model.predict(data)
    res_shape = components[0].image.shape
    return result.reshape(res_shape)


def check_disk_usage(components, path):
    """Checks if disk free space is enough to store components

    Args:
        components (list of Component): List of components that may be in disk.
        path (str): Path inside the disk that will be checked.

    Returns:
        bool: True if there's enough space. False otherwise.
    """
    total_components_memory = 0
    for comp in components:
        total_components_memory += comp.image.size * comp.image.itemsize
    return total_components_memory < shutil.disk_usage(path).free


def runcli(args):
    """Read input volumes"""
    inputFiles = [file for file in (args.inputVolume, args.inputVolume1, args.inputVolume2) if file is not None]
    volumeNodes = [readFrom(file, mrml.vtkMRMLScalarVolumeNode) for file in inputFiles]

    intersect_bounds = np.zeros(6)
    volumeNodes[0].GetRASBounds(intersect_bounds)
    """ Found commmon boundaries to align inputs """
    for ith in range(1, len(volumeNodes)):
        intersect_bounds = adjustbounds(volumeNodes[ith], intersect_bounds)

    channels = [slicer.util.arrayFromVolume(volume) for volume in volumeNodes]
    ctypes = args.ctypes.split(",")

    if len(channels) > 1:
        """Crop volumes using common boundaries"""
        for i in range(len(channels)):
            channels[i] = crop_to_rasbounds(channels[i], volumeNodes[i], intersect_bounds, rgb=ctypes[i] == "rgb")

    ref_shape = np.array([1, *channels[0].shape[:2]]) if ctypes[0] == "rgb" else np.array(channels[0].shape)
    valid_axis = np.squeeze(np.argwhere(ref_shape > 1))
    is_2d = np.any(ref_shape == 1)

    """ Setup same dimensions for all data types """
    for i in range(len(channels)):
        if ctypes[i] == "rgb":
            channels[i] = channels[i][np.newaxis, ...]
        else:
            channels[i] = channels[i][..., np.newaxis]

    params = json.loads(args.xargs)
    params["report"] = args.returnparameterfile

    spacing = ()
    for axis in valid_axis:
        spacing += (volumeNodes[0].GetSpacing()[axis],)

    cli_data = pickle.load(args.inputClassifier) if args.inputClassifier else {}
    params["palette"] = cli_data.get("quantized_palette")

    target, components = prepare(channels, spacing, **params)

    output_temp_dir = f"{args.tempDir}/segmenter_cli"
    shutil.rmtree(output_temp_dir, ignore_errors=True)
    if args.outputFeaturesResults:
        if not os.path.exists(output_temp_dir):
            os.makedirs(output_temp_dir)

        if check_disk_usage(components, output_temp_dir):
            for comp in components:
                filtered_output = comp.image
                if is_2d:
                    filtered_output = filtered_output.reshape(ref_shape)
                np.save(f"{output_temp_dir}/img{comp.image_index}_{comp.filter_type}", filtered_output)
        else:
            with open(args.returnparameterfile, "w") as returnFile:
                returnFile.write(
                    "intermediateoutputerror=The available physical memory in your computer was not suficient to export outputs\n"
                )

    # Try to get the model from the input classifier
    model = cli_data.get("model")

    # If there is no model, train a new one
    if not model:
        """Read annotation labels"""
        labelsNode = readFrom(args.labelVolume, mrml.vtkMRMLLabelMapVolumeNode)
        labelsArray = np.squeeze(slicer.util.arrayFromVolume(labelsNode)).astype(np.int32)

        locations = labelsArray[:, valid_axis]
        labels = labelsArray[:, -1]
        annotations = locations, labels

        model = rf_fit(components, annotations, is_2d, **params)

    img = rf_predict(components, model)
    if is_2d:
        img = img.reshape(ref_shape)

    writeDataInto(args.outputVolume, img, mrml.vtkMRMLLabelMapVolumeNode, reference=volumeNodes[0])

    if args.outputClassifier:
        palette = None
        if isinstance(target, RGBImageTargets):
            palette = target.pil_quantized

            # We only need to store the palette, not the whole image
            palette = palette.crop((0, 0, 1, 1))
        cli_data = {"model": model, "quantized_palette": palette}
        pickle.dump(cli_data, args.outputClassifier)

    progressUpdate(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--master", type=str, dest="inputVolume", default=None, help="Intensity Input Values")
    parser.add_argument("--extra1", type=str, dest="inputVolume1", default=None, help="Intensity Input Values")
    parser.add_argument("--extra2", type=str, dest="inputVolume2", default=None, help="Intensity Input Values")
    parser.add_argument("--labels", type=str, dest="labelVolume", default=None, help="Labels Input (3d) Values")
    parser.add_argument(
        "--outputvolume", type=str, dest="outputVolume", default=None, help="Output labelmap (3d) Values"
    )
    parser.add_argument(
        "--output_features_results",
        action="store_true",
        dest="outputFeaturesResults",
        help="Output filtered volume nodes",
    )
    parser.add_argument("--xargs", type=str, default="", help="Model configuration string")
    parser.add_argument("--ctypes", type=str, default="", help="Input Color Types")
    parser.add_argument(
        "--returnparameterfile", type=str, default=None, help="File destination to store an execution outputs"
    )
    parser.add_argument(
        "--inputclassifier",
        type=argparse.FileType("rb"),
        dest="inputClassifier",
        default=None,
        help="Input classifier text file",
    )
    parser.add_argument(
        "--outputclassifier",
        type=argparse.FileType("wb"),
        dest="outputClassifier",
        default=None,
        help="Output classifier text file",
    )
    parser.add_argument("--tempDir", type=str, help="Temporary directory")

    args = parser.parse_args()

    runcli(args)

    print("Done")
