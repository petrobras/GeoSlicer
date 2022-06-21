import cv2
import numpy as np
import qt
import slicer


class HistogramEqualizationWidget(qt.QWidget):
    def __init__(self, imageToolsWidget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.imageToolsWidget = imageToolsWidget
        self.setup()

    def setup(self):
        self.logic = HistogramEqualizationLogic()

        formLayout = qt.QFormLayout(self)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        formLayout.addRow(" ", None)

        self.equalizeHistogramButton = qt.QPushButton("Equalize histogram")
        self.equalizeHistogramButton.clicked.connect(self.onEqualizeHistogramButtonClicked)
        formLayout.addRow(self.equalizeHistogramButton)

        formLayout.addRow(" ", None)

    def onEqualizeHistogramButtonClicked(self):
        self.logic.apply(self.imageToolsWidget.currentNode)
        self.equalizeHistogramButton.enabled = False
        self.imageToolsWidget.applyButton.enabled = True
        self.imageToolsWidget.cancelButton.enabled = True

    def reset(self):
        self.equalizeHistogramButton.enabled = True


class HistogramEqualizationLogic:
    def apply(self, node):
        array = slicer.util.arrayFromVolume(node)
        # reshaping to OpenCV's image array shape
        imageArray = array[0, :, :, :]
        # convert from RGB color-space to YCrCb
        imageArray = cv2.cvtColor(imageArray, cv2.COLOR_BGR2YCrCb)
        # equalize the histogram of the Y channel
        imageArray[:, :, 0] = cv2.equalizeHist(imageArray[:, :, 0])
        # convert back to RGB color-space from YCrCb
        imageArray = cv2.cvtColor(imageArray, cv2.COLOR_YCrCb2BGR)
        # reshaping back to Slicer's vector volume array shape
        array = np.reshape(imageArray, [1, *imageArray.shape])
        slicer.util.updateVolumeFromArray(node, array)
