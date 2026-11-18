import numpy as np
import dask


def apply_multiple_threshold(array: dask.array, threshs):
    segmentation = np.zeros(array.shape, dtype=np.uint8)
    index = 1
    for lower, upper in zip(threshs[:-1], threshs[1:]):
        segmentation = np.where((array >= lower) & (array < upper), index, segmentation)
        index += 1

    return segmentation
