import SimpleITK as sitk
import dask
import dask.array as da
import numpy as np
from typing import Union


def _apply_filter(dataArray: "dask.array.core.Array", origin: tuple, spacing: tuple) -> np.ndarray:
    image = sitk.GetImageFromArray(dataArray)
    image.SetSpacing(spacing)
    image.SetOrigin(origin)

    filter = sitk.GradientMagnitudeImageFilter()
    filteredImage = filter.Execute(image)
    filteredArray = sitk.GetArrayFromImage(filteredImage)

    return filteredArray


def _apply_threshold(
    dataArray: "dask.array.core.Array",
    segmentsDataArray: "dask.array.core.Array",
    mask: "dask.array.core.Array",
    thresholds: tuple,
) -> "dask.array.core.Array":
    thresholdMin, thresholdMax = thresholds

    segmentedArray = np.where((dataArray >= thresholdMin) & (dataArray <= thresholdMax) & mask, 0, segmentsDataArray)
    return segmentedArray


def remove_boundaries(
    dataArrayBlock: "dask.array.core.Array",
    segmentationArrayBlock: "dask.array.core.Array",
    origin: tuple,
    spacing: tuple,
    thresholds: tuple,
    microporosityIndex: int = None,
) -> Union[None, "dask.array.core.Array"]:
    if dataArrayBlock is None or segmentationArrayBlock is None:
        return None

    filteredArray = _apply_filter(dataArray=dataArrayBlock, origin=origin, spacing=spacing)
    mask = (
        (segmentationArrayBlock == microporosityIndex)
        if microporosityIndex is not None
        else da.ones(filteredArray.shape, dtype=bool)
    )
    filteredSegmentedArray = _apply_threshold(
        dataArray=filteredArray, segmentsDataArray=segmentationArrayBlock, mask=mask, thresholds=thresholds
    )
    return filteredSegmentedArray
