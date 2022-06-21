import numpy as np


def reflect_data(data, direction="z"):
    """
    Reflect the information in a 3D data, dupling its total size and making it periodic.

    Parameters
    ----------
    data : numpy.ndarray
        Any data which needs to be doubled.
    direction : str, optional
        Direction in which the medium is doubled, can be 'x', 'y' or 'z'.
        The default is 'z'.

    Returns
    -------
    result_data : numpy.ndarray
        New medium with the size doubled in the direction of the argument.

    """
    if direction == "x":
        result_data = np.concatenate((data, data[:, :, ::-1]), axis=2)
    if direction == "y":
        result_data = np.concatenate((data, data[:, ::-1, :]), axis=1)
    if direction == "z":
        result_data = np.concatenate((data, data[::-1, :, :]), axis=0)
    return result_data


def multiply_data(data, multiply_by=2):
    """
    Multiply the size of each voxel in a 3D data, multiplying its total size by multiply_by

    Parameters
    ----------
    data : numpy.ndarray
        Any data which needs to be multiplied.
    multiply_by : float, optional
        How many times the data should be multiplied.
        The default is 2.
    Returns
    -------
    result_data : numpy.ndarray
        New medium with the size multiplied in all the directions by multiply_by.

    """
    result_data = np.zeros(np.multiply(multiply_by, data.shape))
    for i in range(multiply_by):
        for j in range(multiply_by):
            for k in range(multiply_by):
                result_data[i::multiply_by, j::multiply_by, k::multiply_by] = data
    return result_data
