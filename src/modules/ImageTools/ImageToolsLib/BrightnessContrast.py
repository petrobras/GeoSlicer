import cv2
import numpy as np
import qt
import slicer
from PIL import Image, ImageEnhance


class BrightnessContrastWidget(qt.QWidget):
    def __init__(self, imageToolsWidget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.imageToolsWidget = imageToolsWidget
        self.setup()

    def setup(self):
        self.logic = BrightnessContrastLogic()

        formLayout = qt.QFormLayout(self)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        formLayout.addRow(" ", None)

        self.brightnessSliderWidget = slicer.qMRMLSliderWidget()
        self.brightnessSliderWidget.minimum = -100
        self.brightnessSliderWidget.maximum = 100
        self.brightnessSliderWidget.tracking = False
        self.brightnessSliderWidget.valueChanged.connect(self.onBrightnessContrastSliderValueChanged)
        formLayout.addRow("Brightness:", self.brightnessSliderWidget)

        self.contrastSliderWidget = slicer.qMRMLSliderWidget()
        self.contrastSliderWidget.minimum = -100
        self.contrastSliderWidget.maximum = 100
        self.contrastSliderWidget.tracking = False
        self.contrastSliderWidget.valueChanged.connect(self.onBrightnessContrastSliderValueChanged)
        formLayout.addRow("Contrast:", self.contrastSliderWidget)

        formLayout.addRow(" ", None)

    def reset(self):
        self.brightnessSliderWidget.blockSignals(True)
        self.brightnessSliderWidget.value = 0
        self.brightnessSliderWidget.blockSignals(False)
        self.contrastSliderWidget.blockSignals(True)
        self.contrastSliderWidget.value = 0
        self.contrastSliderWidget.blockSignals(False)

    def select(self):
        pass

    def onBrightnessContrastSliderValueChanged(self):
        node = self.imageToolsWidget.currentNode
        # Change to its start state back before applying brightness again
        slicer.util.updateVolumeFromArray(node, self.imageToolsWidget.imageArray)
        self.logic.brightnessContrast(node, self.brightnessSliderWidget.value, self.contrastSliderWidget.value)
        self.imageToolsWidget.applyButton.enabled = True
        self.imageToolsWidget.cancelButton.enabled = True


class BrightnessContrastLogic:
    def brightnessContrast(self, node, brightnessValue, contrastValue):
        array = slicer.util.arrayFromVolume(node)
        # reshaping to OpenCV's image array shape
        imageArray = array[0, :, :, :]

        pilImageArray = Image.fromarray(imageArray)
        enhancer = ImageEnhance.Brightness(pilImageArray)
        pilImageArray = enhancer.enhance(brightnessValue / 100 + 1)
        enhancer = ImageEnhance.Contrast(pilImageArray)
        pilImageArray = enhancer.enhance(contrastValue / 100 + 1)
        imageArray = np.array(pilImageArray)

        # reshaping back to Slicer's vector volume array shape
        array = np.reshape(imageArray, [1, *imageArray.shape])
        slicer.util.updateVolumeFromArray(node, array)
