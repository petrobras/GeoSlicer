import logging

import numpy as np
import numba as nb
from skimage.transform import rescale
from scipy import ndimage

import porespy

DEFAULT_NULL_VALUES = set((-999.25, -9999.00, -9999.25))
ANP_880_2022_DEFAULT_NULL_VALUE = -999.25


@nb.jit(nopython=True)
def trimPointSearch(data, nullvalue=DEFAULT_NULL_VALUES, reverse=False):
    end_ptr = len(data)
    indexing = range(end_ptr) if not reverse else range(end_ptr - 1, 0, -1)
    for i in indexing:
        if data[i] not in nullvalue:
            return i if not reverse else i + 1

    return end_ptr if not reverse else None


@nb.jit(nopython=True)
def trimPointSearch2d(data, nullvalue=DEFAULT_NULL_VALUES, reverse=False):
    end_ptr = len(data)
    rows = range(end_ptr) if not reverse else range(end_ptr - 1, 0, -1)
    for row in rows:
        for v in data[row]:
            if v in nullvalue:
                break
        else:
            return row if not reverse else row + 1
    return end_ptr if not reverse else None


def argTrimNullValues(arr, nullvalue):
    if arr.ndim == 1:
        start = trimPointSearch(arr, nullvalue=nullvalue)
        end = trimPointSearch(arr, reverse=True, nullvalue=nullvalue)
    else:
        start = trimPointSearch2d(arr, nullvalue=nullvalue)
        end = trimPointSearch2d(arr, reverse=True, nullvalue=nullvalue)

    return slice(start, end)


# deprecated
# def standardize_null_values(data, nullvalues):
#     data[~np.isfinite(data)] = DEFAULT_NULL_VALUE
#     for nv in nullvalues:
#         if nv != DEFAULT_NULL_VALUE:
#             data[data == nv] = DEFAULT_NULL_VALUE
#     return data

# deprecated
# def rescale_classes(data, scale):
#     mask = data == DEFAULT_NULL_VALUE
#     filtered = np.array(data, copy=True)
#     filtered[mask] = int(np.nanmedian(data) + np.nanstd(data)*0.5)
#     filtered = rescale(filtered, scale, anti_aliasing=False, preserve_range=True, clip=True).astype(int)
#     return filtered


def rescale_depth(data, scale):
    return rescale(data, scale, anti_aliasing=False, preserve_range=True, clip=True).astype(float)


def preprocess(data, depth, nullvalues: list = None, scale=None):
    if nullvalues:
        # standardize_null_values(data, nullvalues)
        # data[data <= nullvalues[0]] = DEFAULT_NULL_VALUE
        validSlice = argTrimNullValues(data, nullvalues)
        S_ = lambda X: X[validSlice]
    else:
        S_ = lambda X: X

    if scale:
        data_t = rescale(S_(data), scale, anti_aliasing=True, preserve_range=True)
        depth_t = rescale_depth(S_(depth), scale)
    else:
        data_t, depth_t = S_(data), S_(depth)

    # only_valid_values = data_t[data_t != DEFAULT_NULL_VALUE]
    return data_t, depth_t


def createProportionVolume(data: np.ndarray):
    props = np.zeros(data.shape)
    for row, rdata in enumerate(data):
        values, counts = np.unique(rdata, return_counts=True)
        ptr = 0
        for v, c in zip(values, counts):
            props[row, ptr : ptr + c] = v
            ptr += c

    return props


@nb.jit(nopython=True)
def calculateStats(data, nullvalue=np.nan):
    array = data.ravel()
    minimum = np.inf
    maximum = -np.inf
    n = len(array)
    mu = np.nanmean(data)
    si_acc = 0
    for value in array:
        if value not in nullvalue and not np.isnan(value):
            if value < minimum:
                minimum = value
            if value > maximum:  # TODO rever depth e mudar essa condição para elif
                maximum = value
            si_acc += (value - mu) ** 2
    stddev = np.sqrt(si_acc / (n - 1))
    return minimum, maximum, mu, stddev


def binset(values):
    d = np.diff(np.unique(values)).min()
    left_of_first_bin = values.min() - float(d) / 2
    right_of_last_bin = values.max() + float(d) / 2
    return np.arange(left_of_first_bin, right_of_last_bin + d, d)


def substitute(x, y, area, pair_swap, target):
    xpoints = x
    ypoints = y

    xmin, ymin, xmax, ymax = area

    bound_cols = np.nonzero(np.logical_and(xpoints >= xmin, xpoints <= xmax))
    bound_rows = np.nonzero(np.logical_and(ypoints >= ymin, ypoints <= ymax))

    i_coords, j_coords = np.meshgrid(bound_rows, bound_cols, indexing="ij")
    coordinate_grid = np.array([i_coords.ravel(), j_coords.ravel()]).T

    for coord in coordinate_grid:
        value = target[coord[0], coord[1]]
        if value == pair_swap[0]:
            target[coord[0], coord[1]] = pair_swap[1]

    return target


# TODO move to a better place
@nb.jit(nopython=True)
def min_max(arr):
    n = len(arr)
    local_min = arr[0]
    local_max = arr[1]

    for i in range(n):
        el = arr[i]
        if el < local_min:
            local_min = el
        if el > local_max:
            local_max = el

    return local_min, local_max


def handle_null_values(image, nullValues: set):
    offset = 0.000001

    # for each null value in null value set, replace it with nan
    working_image = image.astype(np.float32)

    for v in nullValues:
        working_image[working_image == v] = np.nan
    # if no values were replaced, return our standard invalid value
    if not np.isnan(np.min(working_image)):
        return ANP_880_2022_DEFAULT_NULL_VALUE

    tempArrayMaxValue = np.nan
    tempArrayMinValue = np.nan
    newNullValue = ANP_880_2022_DEFAULT_NULL_VALUE
    try:
        tempArrayMaxValue = np.nanmax(working_image)
        tempArrayMinValue = np.nanmin(working_image)
    except RuntimeWarning:
        logging.warning(f"Failed to handle null values. Using {newNullValue} as default.")
    else:
        if not np.isnan(tempArrayMaxValue) and not np.isnan(tempArrayMinValue):
            # TODO(PL-1429b) does not work if min == max
            newNullValue = int(np.floor(tempArrayMinValue - ((tempArrayMaxValue - tempArrayMinValue) * offset)))
        np.nan_to_num(working_image, copy=False, nan=newNullValue, posinf=newNullValue, neginf=newNullValue)

    working_image = working_image.astype(image.dtype)
    image[...] = working_image

    return newNullValue


def connected_image(array, connectivity=1, direction="all_combinations", make_contiguous=True):
    """
    Takes a 3D array and returns an image with same shape with only connected elements


    Parameters
    ----------
    array : ndarray
        A 3D ndarray, values different from 0 are considered active elements and axis [z, y, x]

    connectivity : int
        The manhattam distance to consider two elements in contact, default is one (face connectivity)

    direction : string
        String defining what faces are considered when checking connectivity
        Single faces: 'z+', 'y+', 'x+', 'z-', 'y-' or 'x-' --> clusters touching the specified face
        Double faces: 'x', 'y', or 'z' --> clusters touching both oppoisite faces in the specified axis
        Multiple faces: 'all', 'all_combinations' or 'any' -->
            'all' -> clusters that touch any two opposite faces
            'all_combinations' -> clusters that touch any two faces
            'any' -> any cluster touching any face

    make_contiguous : bool
        If true, the label values of the returned array are made contiguous

    Returns
    -------
    labeled : ndarray
        Numpy array with same shape as 'array'

    """

    dimensions = np.count_nonzero([s > 1 for s in array.shape])

    if dimensions != 3 and dimensions != 2:
        raise ValueError(
            f"connected_image is only valid for 3D or 2D images," f" given image has {dimensions} dimensions"
        )

    if connectivity == 1:
        labeled = ndimage.label(array)[0]
    elif connectivity in [2, 3]:
        structure = ndimage.generate_binary_structure(rank=3, connectivity=connectivity)
        labeled = ndimage.label(array, structure=structure)[0]
    else:
        raise ValueError(f"Connectivity must be in (1, 2, 3), was {connectivity}")
    # fmt: off
    set_generators = {
        'z-' : lambda: set(np.unique(labeled[1:-1, 1:-1,  0])),
        'z+' : lambda: set(np.unique(labeled[1:-1, 1:-1, -1])),
        'y-' : lambda: set(np.unique(labeled[1:-1,  0, 1:-1])),
        'y+' : lambda: set(np.unique(labeled[1:-1, -1, 1:-1])),
        'x-' : lambda: set(np.unique(labeled[ 0, 1:-1, 1:-1])),
        'x+' : lambda: set(np.unique(labeled[-1, 1:-1, 1:-1])),
    } if dimensions == 3 else {
        'y-' : lambda: set(np.unique(labeled[1:-1,  0])),
        'y+' : lambda: set(np.unique(labeled[1:-1, -1])),
        'x-' : lambda: set(np.unique(labeled[ 0, 1:-1])),
        'x+' : lambda: set(np.unique(labeled[-1, 1:-1])),
    }
    # fmt: on

    ruleset = (
        {  # test faces and minimum number of touching faces
            "z+": (("z+",), 1),
            "y+": (("y+",), 1),
            "x+": (("x+",), 1),
            "z-": (("z-",), 1),
            "y-": (("y-",), 1),
            "x-": (("x-",), 1),
            "z": (("z+", "z-"), 2),
            "y": (("y+", "y-"), 2),
            "x": (("x+", "x-"), 2),
            "any": (("z+", "y+", "x+", "z-", "y-", "x-"), 1),
            "all_combinations": (("z+", "y+", "x+", "z-", "y-", "x-"), 2),
        }
        if dimensions == 3
        else {
            "y+": (("y+",), 1),
            "x+": (("x+",), 1),
            "y-": (("y-",), 1),
            "x-": (("x-",), 1),
            "y": (("y+", "y-"), 2),
            "x": (("x+", "x-"), 2),
            "any": (("y+", "x+", "y-", "x-"), 1),
            "all_combinations": (("y+", "x+", "y-", "x-"), 2),
        }
    )

    if direction == "all":
        connected_labels = set()
        for faces_list, _ in [ruleset[rule] for rule in ("z", "y", "x")]:
            sets = [set_generators[face]() for face in faces_list]
            all_labels = set().union(*sets)
            all_labels.discard(0)
            for i in all_labels:
                faces_count = sum([(i in current_set) for current_set in sets])
                if faces_count == 2:
                    connected_labels.add(i)
        connected_labels = list(connected_labels)

    else:
        try:
            faces_list, required_connections = ruleset[direction]
        except KeyError as e:
            raise ValueError(f"Direction {direction} cannot be selected for array of {dimensions} dimensions!")
        sets = [set_generators[face]() for face in faces_list]
        all_labels = set().union(*sets)
        all_labels.discard(0)
        connected_labels = []
        for i in all_labels:
            faces_count = sum([(i in current_set) for current_set in sets])
            if faces_count >= required_connections:
                connected_labels.append(i)

    labeled = np.where(np.isin(labeled, connected_labels), array, 0)

    if labeled.max() > 1 and make_contiguous:
        labeled = porespy.tools.make_contiguous(labeled)

    return labeled


def create_manhattan_structure(distance: int):
    """
    Returns the 3D ndarray representing the manhattan geometry structuring element with 'distance' distance
    with shape (2*distance + 1, 2*distance + 1, 2*distance + 1)
    """
    diameter = 2 * distance + 1
    structure = abs(np.mgrid[0:diameter, 0:diameter, 0:diameter] - distance).sum(axis=0)
    structure = (structure <= distance).astype(np.uint8)
    return structure
