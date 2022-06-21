import math

from numba import njit, prange
import numpy as np
import itertools


def get_subvolumes_dimensions(data, unit, divisor):
    """Try to divide the data volume into "divisor" parts that fit round numbers of "unit"

    Args:
        data (np.array): data to be divided
        unit (np.array): dimensions of the unit that must fit in the parts
        divisor (int): number of times that data will be divided in each dimension

    Returns:
        list of tuple of slices: slices that delimit a subvolume of "data"
    """
    data_shape = np.array(data.shape)

    shape_in_units = data_shape // unit
    divisor = np.minimum(shape_in_units, divisor)
    subvolume_size = (shape_in_units // divisor) * unit
    dim_it_counters = [0] * len(data_shape)
    base = [0] * len(data_shape)
    return get_subvolumes_dimensions_recursively(0, dim_it_counters, divisor, data_shape, base, subvolume_size)


def get_subvolumes_dimensions_recursively(dim_index, dim_it_counters, divisor, data_shape, base, subvolume_size):
    ranges = []
    for i in range(divisor[dim_index]):
        dim_it_counters[dim_index] = i
        base[dim_index] = dim_it_counters[dim_index] * subvolume_size[dim_index]
        if dim_index < len(data_shape) - 1:
            ranges.extend(
                get_subvolumes_dimensions_recursively(
                    dim_index + 1,
                    dim_it_counters,
                    divisor,
                    data_shape,
                    base,
                    subvolume_size,
                )
            )
        else:
            ranges.append(get_subvolume_slices(data_shape, base, subvolume_size, dim_it_counters, divisor))
    return ranges


def get_subvolume_slices(data_shape, base, subvolume_size, dim_it_counters, divisor):
    """Get slices that delimit a subvolume that must be extracted from the original data

    Args:
        data_shape (tuple): shape of the original data
        base (tuple): initial position of the slices
        subvolume_size (tuple): size of the subvolume
        dim_it_counters (tuple): "identifier of" the current subvolume
        divisor (int): number of times that the original volume is being divided

    Returns:
        tuple of slices: slices that delimit a subvolume
    """
    new_range = ()
    for dim_index in range(len(data_shape)):
        new_range += (
            slice(
                base[dim_index],
                base[dim_index] + subvolume_size[dim_index]
                if dim_it_counters[dim_index] < divisor[dim_index] - 1
                else data_shape[dim_index],
            ),
        )
    return new_range


def add_padding_to_slices(slices, padding_list):
    padded_slices = ()
    for i, single_slice in enumerate(slices):
        padded_slices += (slice(single_slice.start, single_slice.stop + 2 * padding_list[i]),)
    return padded_slices


@njit
def calculate_process_indexes(padding, kernel_dimensions, unit_dimensions, output_shape):
    """Calculate the indexes of subvolumes for the volume iterator

    Args:
        padding (np.array): padding of the data being iterated
        kernel_dimensions (tuple): dimensions of the kernel that will walk thought the data during the iteration
        unit_dimensions (np.array): dimensions of the unit
        output_shape (tuple): desired shape of the current subvolume
    """
    half_kernel_dimensions = kernel_dimensions // 2
    half_unit_dimensions = unit_dimensions // 2

    iteration_count = np.prod(np.array(output_shape))
    progress = 0
    progress_step = 100 / iteration_count

    for output_coordinate in coordinate_iterator(np.array(output_shape)):
        base_coordinates = padding + output_coordinate * unit_dimensions
        kernel_start_position = get_kernel_start_from_unit_start(
            base_coordinates,
            half_kernel_dimensions,
            half_unit_dimensions,
        )
        input_slice = []
        for i, dimension in enumerate(kernel_dimensions):
            input_slice.append((kernel_start_position[i], kernel_start_position[i] + dimension))
        progress += progress_step
        yield input_slice, output_coordinate, progress


@njit
def coordinate_iterator(shape_array):
    """Similar to the itertools.product but numba compatible
    Create every coordination of a volume with shape "shape_array"

    Args:
        shape_array (np.array): shape of the volume

    Returns:
        tuple: coordinate to be used in an iteration
    """
    # coordinate_iterator = ()
    # for size in shape_array:
    #     coordinate_iterator += (range(size),)
    # return itertools.product(*coordinate_iterator)
    number_of_dimensions = len(shape_array)
    for i in range(np.prod(shape_array)):
        coordinate = np.zeros(number_of_dimensions, dtype=np.int32)
        quotient = i
        for dimension in range(number_of_dimensions):
            index = number_of_dimensions - 1 - dimension
            quotient, remainder = divmod(quotient, shape_array[index])
            coordinate[index] = remainder
        yield coordinate


@njit
def get_kernel_start_from_unit_start(unit_start_position, half_kernel_dimensions, half_unit_dimensions):
    """Given the initial coordinate of a unit, get the initial coordinator for the kernel.

    Args:
        unit_start_position (np.array): initial coordinate of a unit (top, left)
        half_kernel_dimensions (np.array): dimension of the kernel divided by two
        half_unit_dimensions (np.array): dimension of the unit divided by two

    Returns:
        np.array: initial coordinate of the kernel
    """
    kernel_start_position = unit_start_position + half_unit_dimensions - half_kernel_dimensions
    return kernel_start_position


def divide_slices_according_to_unit(slices, unit):
    result = ()
    for i in range(len(slices)):
        result += (slice(slices[i].start // unit[i], slices[i].stop // unit[i]),)
    return result
