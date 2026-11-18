import dask
import SimpleITK as sitk
import numpy as np


def expand_segments(
    segmentationArrayBlock: "dask.array.core.Array",
    origin: tuple,
    spacing: tuple,
    microporosityIndex: int = None,
) -> "np.ndarray":
    filter = sitk.MorphologicalWatershedFromMarkersImageFilter()
    filter.FullyConnectedOff()
    filter.MarkWatershedLineOff()

    if microporosityIndex is not None:
        microporosity = segmentationArrayBlock == microporosityIndex
        segmentationArrayBlock[microporosity] = 0

    segmentation = sitk.GetImageFromArray(segmentationArrayBlock.astype(np.uint8))
    segmentation.SetSpacing(spacing)
    segmentation.SetOrigin(origin)

    image = sitk.Image(*segmentation.GetSize(), sitk.sitkUInt8)
    image.SetSpacing(spacing)
    image.SetOrigin(origin)

    result = filter.Execute(image, segmentation)
    result = sitk.GetArrayFromImage(result)

    if microporosityIndex is not None:
        result[microporosity] = microporosityIndex

    return result
