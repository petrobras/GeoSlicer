from multiprocessing import cpu_count, Pool
from multiprocessing.sharedctypes import RawArray
from scipy.linalg import null_space

import numba
import numpy as np


class ArrayProcessor:
    @staticmethod
    def initThreadContext(model, data_buf, roi_buf, out_buf, datashape, roishape, winshape):
        global _model_
        global _data_df_, _roi_df_, _out_df_
        global _winshape_, _volshape_

        _model_ = model
        _data_df_ = np.ctypeslib.as_array(data_buf).reshape(datashape)
        _roi_df_ = np.ctypeslib.as_array(roi_buf).reshape(roishape)
        _out_df_ = np.ctypeslib.as_array(out_buf).reshape(roishape)
        _winshape_ = winshape

    def process(self, model, inputVoxelArray, roiVoxelArray, windowShape, **kwargs):
        cores = min(cpu_count() - 1, 6)
        # ps = int(np.ceil(inputVoxelArray.shape[0] / cores))

        pad = int(np.floor(windowShape[0] / 2.0))
        padder = [(pad, pad) for s in windowShape]
        bbox = bbox_3D(roiVoxelArray)

        bboxROI = bbox_to_slices(bbox)
        roi_roi = roiVoxelArray[bboxROI]

        padded_bbox, pad_diffs = pad_bbox_3D(bbox, img_shape=roiVoxelArray.shape, pad=padder)
        bboxPaddedROI = bbox_to_slices(padded_bbox)
        roi_data = np.pad(inputVoxelArray[bboxPaddedROI], pad_diffs, mode="reflect")

        sorted_axis = list(reversed(np.argsort(roi_data.shape)))
        roi_data = np.swapaxes(roi_data, sorted_axis[0], sorted_axis[1])
        roi_roi = np.swapaxes(roi_roi, sorted_axis[0], sorted_axis[1])

        dtype = np.dtype(inputVoxelArray.dtype)
        cdtype = np.ctypeslib.as_ctypes_type(dtype)  # convert to raw typing naming

        memshared = RawArray(cdtype, roi_data.size)
        memsharedbuf = np.ctypeslib.as_array(memshared)  # np.frombuffer(memshared, dtype=dtype)
        np.copyto(memsharedbuf, roi_data.ravel())

        memsharedROI = RawArray("B", roi_roi.size)
        memsharedROIbuf = np.ctypeslib.as_array(memsharedROI)  # np.frombuffer(memsharedROI, dtype=np.uint8)
        np.copyto(memsharedROIbuf, roi_roi.ravel())

        memsharedOut = RawArray("B", roi_roi.size)  # H = uint16 (unsigned short) i = int16
        memsharedbufOut = np.ctypeslib.as_array(memsharedOut).reshape(
            roi_roi.shape
        )  # np.frombuffer(memsharedOut, dtype=np.uint8)
        memsharedbufOut.fill(0)

        if cores <= 1 or not kwargs.get("parallel", False):
            self.initThreadContext(
                model,
                memshared,
                memsharedROI,
                memsharedOut,
                roi_data.shape,
                roi_roi.shape,
                windowShape,
            )
            for i in range(roi_roi.shape[0]):
                applyModelToSlice(i)
        else:
            params = (
                model,
                memshared,
                memsharedROI,
                memsharedOut,
                roi_data.shape,
                roi_roi.shape,
                windowShape,
            )
            with Pool(
                processes=cores,
                initializer=ArrayProcessor.initThreadContext,
                initargs=params,
            ) as pool:
                pool.map(applyModelToSlice, range(roi_roi.shape[0]))

        out_roi = np.swapaxes(memsharedbufOut, sorted_axis[0], sorted_axis[1])
        ndout = np.zeros(roiVoxelArray.shape, dtype=np.uint8)
        ndout[bboxROI] = out_roi

        return ndout


def applyModelToSlice(slice_i, batch_size=64):
    global _model_, _roi_df_, _out_df_, _data_df_, _winshape_
    wi, wj, wk = _winshape_
    nr_features = int(wi * wj * wk)
    valid_positions = np.argwhere(_roi_df_[slice_i, ...] == 1).astype(np.int32)

    samples = len(valid_positions)
    if samples == 0:
        return

    left_samples, consumed = samples, 0
    buffer = np.empty((batch_size, nr_features), dtype=_data_df_.dtype)
    while left_samples > 0:
        if left_samples < batch_size:
            buffer = np.empty((left_samples, nr_features), dtype=_data_df_.dtype)

        batch_positions = valid_positions[consumed : consumed + buffer.shape[0], ...]

        procSliceFlat(slice_i, batch_positions, buffer, _data_df_, wi, wj, wk)
        writeSliceFlat(slice_i, _out_df_, batch_positions, _model_.predict(buffer))

        left_samples -= buffer.shape[0]
        consumed += buffer.shape[0]


# @numba.jit(['void(int32, int32[:,:], uint16[:,:], uint16[:,:,:], int32, int32, int32)'], nopython=True)
@numba.jit(nopython=True)
def procSliceFlat(i, valid_positions, buffer, roi_data, wi, wj, wk):
    for f, pos in enumerate(valid_positions):
        j, k = pos
        buffer[f, :] = roi_data[i : i + wi, j : j + wj, k : k + wk].ravel()


# @numba.jit(['void(int32, uint8[:,:,:], int32[:,:], uint8[:])',
#             'void(int32, uint8[:,:,:], int32[:,:], int16[:])'], nopython=True)
@numba.jit(nopython=True)
def writeSliceFlat(i, roi_out, positions, result):
    for f, pos in enumerate(positions):
        j, k = pos
        roi_out[i, j, k] = result[f]


def bbox_to_slices(bbox):
    r"""
    # Extracted from https://github.com/PMEAL/porespy/blob/master/porespy/tools/__funcs__.py
    # Changelog:
    # - changed bbox order to a more natural one (grouped minmax)

    Given a tuple containing bounding box coordinates, return a tuple of slice
    objects.
    A bounding box in the form of a straight list is returned by several
    functions in skimage, but these cannot be used to direct index into an
    image.  This function returns a tuples of slices can be, such as:
    ``im[bbox_to_slices([xmin, ymin, xmax, ymax])]``.
    Parameters
    ----------
    bbox : tuple of ints
        The bounding box indices in the form (``xmin``, ``xmax``, ``ymin``,
        ``ymax``, ``zmin``, ``zmax``).  For a 2D image, simply omit the
        ``zmin`` and ``zmax`` entries.
    Returns
    -------
    slices : tuple
        A tuple of slice objects that can be used to directly index into a
        larger image.
    """
    if len(bbox) == 4:
        ret = (slice(bbox[0], bbox[1] + 1), slice(bbox[2], bbox[3] + 1))
    else:
        ret = (
            slice(bbox[0], bbox[1] + 1),
            slice(bbox[2], bbox[3] + 1),
            slice(bbox[4], bbox[5] + 1),
        )
    return ret


def points_are_below_line(line_points, points):
    # expand matrices to include the intercept/independent term
    line_points = np.c_[line_points, np.ones(len(line_points))]
    points = np.c_[points, np.ones(len(points))]

    # line equation := line_points @ coeficients = 0, therefore:
    coefficients = null_space(line_points)

    # evaluate the linear equation for each point to determine its position relative to the line
    position_relative_to_line = points @ coefficients

    # check if each point is below the line (true if below, false otherwise)
    is_below_line = np.ravel(position_relative_to_line < 0)

    return is_below_line


def points_are_below_plane(points, plane_point, plane_vector):
    """
    Check if a set of points are below a plane defined by a point and a vector.

    Args:
    - points: a Nx3 numpy array representing the N points to be checked
    - plane_point: a numpy array representing a point on the plane
    - plane_vector: a numpy array representing the normal vector of the plane

    Returns:
    - Bool array, True if the point is below the plane, False otherwise
    """
    product = plane_vector * (points - plane_point)
    dot_product = product.sum(axis=1)

    return dot_product < 0


def generate_equidistant_points_on_sphere(N, r=1):
    """
    Creates a set of points, equidistant in the surface of a sphere of radius 1 and
    center at origin. The actual number of points may be close but unnequal to N.

    Args:
    N - approximate number of points generated

    Returns:
    - An float array, Mx3, where M is aproximatelly N
    """
    x = []
    y = []
    z = []

    a = 4 * np.pi / N
    d = np.sqrt(a)
    Mt = np.around(np.pi / d).astype(int)
    dt = np.pi / Mt
    dp = a / dt

    for m in range(Mt):
        theta = np.pi * (m + 0.5) / Mt
        Mp = np.around(2 * np.pi * np.sin(theta) / dp).astype(int)
        for n in range(Mp):
            phi = 2 * np.pi * n / Mp
            x.append(np.sin(theta) * np.cos(phi) * r)
            y.append(np.sin(theta) * np.sin(phi) * r)
            z.append(np.cos(theta) * r)

    return np.column_stack((x, y, z))


def get_two_highest_peaks(array):
    first_index = np.argmax(array)
    first_index = np.unravel_index(first_index, array.shape)

    tmp = array[first_index]
    array[first_index] = 0

    second_index = np.argmax(array)
    second_index = np.unravel_index(second_index, array.shape)

    array[first_index] = tmp

    return (array[first_index], *first_index), (array[second_index], *second_index)


def bbox_3D(img, padding=0):
    r"""
    Extracted from https://stackoverflow.com/questions/31400769/bounding-box-of-numpy-array
    """
    r = np.any(img, axis=(1, 2))
    c = np.any(img, axis=(0, 2))
    z = np.any(img, axis=(0, 1))

    def pad(a, b, axis=0):
        return max(0, a - padding), min(img.shape[axis], b - padding)

    rmin, rmax = pad(*np.where(r)[0][[0, -1]], axis=0)
    cmin, cmax = pad(*np.where(c)[0][[0, -1]], axis=1)
    zmin, zmax = pad(*np.where(z)[0][[0, -1]], axis=2)

    return rmin, rmax, cmin, cmax, zmin, zmax


def pad_bbox_3D(bbox, img_shape, pad=None):
    rmin, rmax, cmin, cmax, zmin, zmax = bbox

    r_diff = np.zeros(2, dtype=np.int32)
    c_diff = np.zeros(2, dtype=np.int32)
    z_diff = np.zeros(2, dtype=np.int32)

    if pad is not None:
        rmin = rmin - pad[0][0]
        if rmin < 0:
            r_diff[0] = abs(rmin)
            rmin = 0

        rmax = rmax + pad[0][1] + 1
        if rmax > img_shape[0]:
            r_diff[1] = int(rmax - img_shape[0])
            rmax = img_shape[0]

        cmin = cmin - pad[1][0]
        if cmin < 0:
            c_diff[0] = abs(cmin)
            cmin = 0

        cmax = cmax + pad[1][1] + 1
        if cmax > img_shape[1]:
            c_diff[1] = int(cmax - img_shape[1])
            cmax = img_shape[1]

        zmin = zmin - pad[2][0]
        if zmin < 0:
            z_diff[0] = abs(zmin)
            zmin = 0

        zmax = zmax + pad[2][1] + 1
        if zmax > img_shape[2]:
            z_diff[1] = int(zmax - img_shape[2])
            zmax = img_shape[2]

    return (rmin, rmax, cmin, cmax, zmin, zmax), (r_diff, c_diff, z_diff)


@numba.jit(nopython=True)
def cSegmentIndexingArray(data: np.ndarray, n_segments, void_value=0):
    roi_indexes = np.argwhere(data != void_value)
    map_ = np.empty((len(roi_indexes), 4))
    count_ = np.zeros(n_segments)
    for i in range(len(roi_indexes)):
        index = roi_indexes[i, :]
        value = data[index[0], index[1], index[2]]
        map_[i, 0:3] = index[:]
        map_[i, 4] = value
        count_[value] += 1

    return map_, count_


def parseWindowFormat(fmt):
    shapestr, step, wintype = fmt.split(":")
    shape = tuple([int(d) for d in shapestr.split(",")])
    return shape, int(step), wintype


def random_alphaNumeric_string(lettersCount, digitsCount):
    import random
    import string

    sampleStr = "".join((random.choice(string.ascii_letters) for i in range(lettersCount)))
    sampleStr += "".join((random.choice(string.digits) for i in range(digitsCount)))

    # Convert string to list and shuffle it to mix letters and digits
    sampleList = list(sampleStr)
    random.shuffle(sampleList)
    finalString = "".join(sampleList)
    return finalString


def randomChoice(nparray, max_samples, value_to_exclude=None, seed=42):
    r"""
    Sample randomly without replacement up to max_samples from an array
    with a fixed seed for reproducibility.

    Parameters
    ----------
    nparray : nparray
        with values to be sampled from
    max_samples : int
        max number of samples to extract from it.
    value_to_exclude (optional) : scalar
        value to exclude from sampling, typically the null value.
    seed (optional) : int
        seed for the random number generator, the default is fixed to always
        sample a specific array the same way. Pass ``None`` for a random seed.
    Returns
    -------
    output : nparray
        A new array with the sampled values.
    """
    import random

    random.seed(seed)
    indexes = random.sample(range(0, np.size(nparray)), min(np.size(nparray), max_samples * 2))
    firstSizeGuess = min(max_samples, np.size(nparray))
    output = nparray[indexes[0:firstSizeGuess]]
    del indexes[0:firstSizeGuess]
    if value_to_exclude is not None:
        output = list(output[output != value_to_exclude])
        while len(output) < max_samples and len(output) < np.size(nparray) and len(indexes) > 0:
            index = indexes.pop(0)
            if nparray[index] != value_to_exclude:
                output.append(nparray[index])
    return np.array(output)


from numpy.lib.stride_tricks import as_strided


def sliding_window_view(x, window_shape, axis=None, *, subok=False, writeable=False):
    """Taken from numpy v1.20,
    See: https://numpy.org/devdocs/reference/generated/numpy.lib.stride_tricks.sliding_window_view.html
    """
    window_shape = tuple(window_shape) if np.iterable(window_shape) else (window_shape,)
    # first convert input to array, possibly keeping subclass
    x = np.array(x, copy=False, subok=subok)

    window_shape_array = np.array(window_shape)
    if np.any(window_shape_array < 0):
        raise ValueError("`window_shape` cannot contain negative values")

    if axis is None:
        axis = tuple(range(x.ndim))
        if len(window_shape) != len(axis):
            raise ValueError(
                f"Since axis is `None`, must provide "
                f"window_shape for all dimensions of `x`; "
                f"got {len(window_shape)} window_shape elements "
                f"and `x.ndim` is {x.ndim}."
            )
    else:
        axis = np.core.numeric.normalize_axis_tuple(axis, x.ndim, allow_duplicate=True)
        if len(window_shape) != len(axis):
            raise ValueError(
                f"Must provide matching length window_shape and "
                f"axis; got {len(window_shape)} window_shape "
                f"elements and {len(axis)} axes elements."
            )

    out_strides = x.strides + tuple(x.strides[ax] for ax in axis)

    # note: same axis can be windowed repeatedly
    x_shape_trimmed = list(x.shape)
    for ax, dim in zip(axis, window_shape):
        if x_shape_trimmed[ax] < dim:
            raise ValueError("window shape cannot be larger than input array shape")
        x_shape_trimmed[ax] -= dim - 1
    out_shape = tuple(x_shape_trimmed) + window_shape
    return as_strided(x, strides=out_strides, shape=out_shape, subok=subok, writeable=writeable)


class FlowSetter:
    def __init__(self, direction=None) -> None:
        self.direction = direction if direction in ("x", "y", "z") else "z"

    def apply(self, volumeArray):
        if self.direction == "y":
            volumeArray = volumeArray.transpose((1, 2, 0))
        elif self.direction == "x":
            volumeArray = volumeArray.transpose((2, 1, 0))

        return volumeArray

    def revert(self, volumeArray):
        if self.direction == "y":
            volumeArray = volumeArray.transpose((2, 0, 1))
        elif self.direction == "x":
            volumeArray = volumeArray.transpose((2, 1, 0))

        return volumeArray
