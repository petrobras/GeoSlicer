import cv2
import numpy as np
import qt
import slicer


class NewHistogramEqualizationWidget(qt.QWidget):
    def __init__(self, imageToolsWidget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.imageToolsWidget = imageToolsWidget
        self.setup()

    def setup(self):
        self.logic = NewHistogramEqualizationLogic()

        formLayout = qt.QFormLayout(self)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

    def reset(self):
        pass

    def select(self):
        self.logic.apply(self.imageToolsWidget.currentNode)
        self.imageToolsWidget.applyButton.enabled = True
        self.imageToolsWidget.cancelButton.enabled = True


class NewHistogramEqualizationLogic:
    def apply(self, node):
        array = slicer.util.arrayFromVolume(node)
        # reshaping to OpenCV's image array shape
        imageArray = array[0, :, :, :]

        # https://medium.com/analytics-vidhya/image-equalization-contrast-enhancing-in-python-82600d3b371c
        imageArray = self.equalize_this(imageArray)

        # reshaping back to Slicer's vector volume array shape
        array = np.reshape(imageArray, [1, *imageArray.shape]).astype(array.dtype)
        slicer.util.updateVolumeFromArray(node, array)

    def equalize_this(self, imageArray, bins=256):
        r_image_eq = self.enhance_contrast(image_matrix=imageArray[:, :, 0], bins=bins)
        g_image_eq = self.enhance_contrast(image_matrix=imageArray[:, :, 1], bins=bins)
        b_image_eq = self.enhance_contrast(image_matrix=imageArray[:, :, 2], bins=bins)
        image_eq = np.dstack(tup=(r_image_eq, g_image_eq, b_image_eq))
        return image_eq

    def enhance_contrast(self, image_matrix, bins=256):
        image_flattened = image_matrix.flatten()
        image_hist = np.zeros(bins)

        # frequency count of each pixel
        for pix in image_matrix:
            image_hist[pix] += 1

        # cummulative sum
        cum_sum = np.cumsum(image_hist)
        norm = (cum_sum - cum_sum.min()) * 255
        # normalization of the pixel values
        n_ = cum_sum.max() - cum_sum.min()
        uniform_norm = norm / n_
        uniform_norm = uniform_norm.astype("int")

        # flat histogram
        image_eq = uniform_norm[image_flattened]
        # reshaping the flattened matrix to its original shape
        image_eq = np.reshape(a=image_eq, newshape=image_matrix.shape)

        return image_eq
