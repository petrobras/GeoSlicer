import cv2
import numpy as np
import qt
import slicer
from PIL import Image, ImageEnhance


class SaturationWidget(qt.QWidget):
    def __init__(self, imageToolsWidget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.imageToolsWidget = imageToolsWidget
        self.setup()

    def setup(self):
        self.logic = SaturationLogic()

        formLayout = qt.QFormLayout(self)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        formLayout.addRow(" ", None)

        self.saturationSliderWidget = slicer.qMRMLSliderWidget()
        self.saturationSliderWidget.minimum = -100
        self.saturationSliderWidget.maximum = 100
        self.saturationSliderWidget.tracking = False
        self.saturationSliderWidget.valueChanged.connect(self.onSaturationSliderValueChanged)
        formLayout.addRow("Saturation:", self.saturationSliderWidget)

        formLayout.addRow(" ", None)

    def reset(self):
        self.saturationSliderWidget.blockSignals(True)
        self.saturationSliderWidget.value = 0
        self.saturationSliderWidget.blockSignals(False)

    def select(self):
        pass

    def onSaturationSliderValueChanged(self, value):
        node = self.imageToolsWidget.currentNode
        # Change to its start state back before applying brightness again
        slicer.util.updateVolumeFromArray(node, self.imageToolsWidget.imageArray)
        self.logic.saturation(node, value)
        self.imageToolsWidget.applyButton.enabled = True
        self.imageToolsWidget.cancelButton.enabled = True


class SaturationLogic:
    def saturation(self, node, value):
        array = slicer.util.arrayFromVolume(node)
        # reshaping to OpenCV's image array shape
        imageArray = array[0, :, :, :]

        pilImageArray = Image.fromarray(imageArray)
        enhancer = ImageEnhance.Color(pilImageArray)
        pilImageArray = enhancer.enhance(value / 100 + 1)
        imageArray = np.array(pilImageArray)

        # reshaping back to Slicer's vector volume array shape
        array = np.reshape(imageArray, [1, *imageArray.shape])
        slicer.util.updateVolumeFromArray(node, array)
