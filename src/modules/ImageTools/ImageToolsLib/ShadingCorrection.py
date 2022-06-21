import random

import cv2
import numpy as np
import qt
import slicer
from scipy.optimize import curve_fit


class ShadingCorrectionWidget(qt.QWidget):
    def __init__(self, imageToolsWidget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.imageToolsWidget = imageToolsWidget
        self.setup()

    def setup(self):
        self.logic = ShadingCorrectionLogic()

        formLayout = qt.QFormLayout(self)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

    def reset(self):
        pass

    def select(self):
        self.logic.apply(self.imageToolsWidget.currentNode)
        self.imageToolsWidget.applyButton.enabled = True
        self.imageToolsWidget.cancelButton.enabled = True


class ShadingCorrectionLogic:
    def apply(self, node):
        array = slicer.util.arrayFromVolume(node)
        # reshaping to OpenCV's image array shape
        imageArray = array[0, :, :, :]

        imageArray = self.shadeCorrection(imageArray)

        # reshaping back to Slicer's vector volume array shape
        array = np.reshape(imageArray, [1, *imageArray.shape])
        slicer.util.updateVolumeFromArray(node, array)

    def shadeCorrection(self, image):
        image = cv2.cvtColor(image, cv2.COLOR_RGB2HSV).astype(np.uint16)
        h, s, v = cv2.split(image)
        image = np.array([h, s, v])
        shape = np.shape(image)

        def polynomial(data, a, b, c, d, e, f, g, h):
            x, y = data
            return a * (x - b) ** 2 + c * (y - d) ** 2 + e * (x - b) + f * (y - d) + g * (x - b) * (y - d) + h

        def plane(data, a, b, c, d, e):
            x, y = data
            return a * (x - b) + c * (y - d) + e

        x, y = np.meshgrid([i for i in range(shape[1])], [j for j in range(shape[2])])

        polynomialInitialParameters = [1, shape[1] / 2, 1, shape[2] / 2, 1, 1, 1, 255]
        planeInitialParameters = [1, shape[1] / 2, 1, shape[2] / 2, 255]

        shadingMask = np.zeros_like(s)
        indexes = np.where((h >= 90) & (h <= 110) & (v >= 110))
        shadingMask[indexes] = 255

        # Selecting random points
        xData, yData = np.where(shadingMask == 255)
        data = [(x, y) for x, y in zip(xData, yData)]
        data = random.sample(data, min(len(data), 50000))
        xData, yData = list(zip(*data))

        correctedImage = []
        for channel, clipValue in zip([h, s, v], [179, 255, 255]):
            zData = channel[(xData, yData)]

            # Fitting
            function = polynomial
            try:
                fittedParameters, pcov = curve_fit(function, [xData, yData], zData, p0=polynomialInitialParameters)
            except:
                function = plane
                try:
                    fittedParameters, pcov = curve_fit(function, [xData, yData], zData, p0=planeInitialParameters)
                except:
                    pass

            # Applying function
            z = function((x, y), *fittedParameters)
            z = np.swapaxes(z, 0, 1)

            channelShadingMaskMean = np.mean(channel[shadingMask == 255])
            zz = z / channelShadingMaskMean

            zz = np.clip(zz, 0.8, 1.2)  # maximum ranges of correction, to avoid blow ups from the fitted function

            channel = channel / zz
            channel = channel.astype(np.uint16)
            channel = np.clip(channel, 0, clipValue)
            correctedImage.append(channel)

        correctedImage = cv2.merge(correctedImage).astype(np.uint8)
        correctedImage = cv2.cvtColor(correctedImage, cv2.COLOR_HSV2RGB)
        return correctedImage
