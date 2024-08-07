import cv2
import numpy as np
import slicer
import slicer.util
from ltrace.assets_utils import get_asset
from ltrace.lmath.filtering import DistributionFilter
from scipy.ndimage import zoom


class Model:
    def getModelPath(self, model):
        return get_asset("ImageLogEnv/" + model + ".h5")

    def segment(self, parameters):
        raise NotImplementedError


def updateLabelMapArray(labelMapArray, referenceImageNode):
    imageArray = slicer.util.arrayFromVolume(referenceImageNode)
    resizeFactors = np.array(imageArray.shape) / labelMapArray.shape
    labelMapArray = zoom(labelMapArray, resizeFactors, order=0)
    return labelMapArray


def processImageArray(imageNode, imageWidth, cloneColumns=None):
    imageArray = None
    if imageNode is not None:
        imageSpacing = imageNode.GetSpacing()
        imageArray = slicer.util.arrayFromVolume(imageNode)[:, 0, :]
        imageArray = equalize(imageArray)
        imageArray = normalize(imageArray)
        imageArray = resizeToWidth(imageArray, imageWidth, imageSpacing[0], imageSpacing[2])

    if cloneColumns:
        imageArray = np.concatenate(
            (imageArray[:, imageWidth - cloneColumns :], imageArray, imageArray[:, :cloneColumns]), axis=1
        )

    return imageArray


def normalize(image):
    normalizedImage = cv2.normalize(image, None, alpha=0, beta=2**16 - 1, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_16U)
    return normalizedImage.astype(np.uint16)


def equalize(imageArray):
    def windowScale(data, window, level):
        out_range = [np.min(data), np.max(data)]
        data_new = np.empty(data.shape, dtype=np.double)
        data_new.fill(out_range[1] - 1)
        data_new[data <= (level - window / 2)] = out_range[0]
        data_new[(data > (level - window / 2)) & (data <= (level + window / 2))] = (
            (data[(data > (level - window / 2)) & (data <= (level + window / 2))] - (level - 0.5)) / (window - 1) + 0.5
        ) * (out_range[1] - out_range[0]) + out_range[0]
        data_new[data > (level + window / 2)] = out_range[1] - 1
        return data_new

    clipSize = int(len(imageArray) / 10)
    clippedImageArray = imageArray[clipSize : len(imageArray) - clipSize]

    distributionFilter = DistributionFilter(clippedImageArray)
    default_num_of_stds = 2
    min, max = distributionFilter.get_filter_min_max(default_num_of_stds)

    window = max - min
    level = (min + max) / 2
    return windowScale(imageArray, window, level)


def resizeToWidth(image, imageWidth, intraSliceSpacing, interSliceSpacing):
    realWidth = image.shape[1] * intraSliceSpacing
    realHeight = image.shape[0] * interSliceSpacing

    newImageWidth = imageWidth
    newImageHeight = realHeight * imageWidth / realWidth

    heightZoomFactor = newImageHeight / image.shape[0]
    widthZoomFactor = newImageWidth / image.shape[1]

    return zoom(image, (heightZoomFactor, widthZoomFactor), order=1)


def combineImageArrays(redImageArray, greenImageArray, blueImageArray):
    imageArrays = [redImageArray, greenImageArray, blueImageArray]

    # We need at least one filled imageArray to form an image (and find its shape)
    shape = [np.inf, np.inf]
    for imageArray in imageArrays:
        if imageArray is not None:
            shape = np.minimum(shape, imageArray.shape)
    shape = shape.astype(int)

    # For the missing channels, we fill with zeros
    for i in range(len(imageArrays)):
        if imageArrays[i] is None:
            imageArrays[i] = np.full(shape, 0, dtype=np.uint16)
        else:
            imageArrays[i] = imageArrays[i][: shape[0], : shape[1]]

    # Then we can build the RGB image
    combinedImageArray = np.dstack([imageArrays[0], imageArrays[1], imageArrays[2]])

    # Convert to 24 bits
    combinedImageArray = cv2.normalize(
        combinedImageArray, None, alpha=0, beta=2**8 - 1, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_8U
    )

    return combinedImageArray, *imageArrays


def getRoundedInteger(value):
    return int(np.round(value))
