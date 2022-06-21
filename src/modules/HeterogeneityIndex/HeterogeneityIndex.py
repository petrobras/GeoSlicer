import ctk
import numpy as np
import os
import pandas as pd
import qt
import slicer
from ltrace.slicer.node_attributes import ImageLogDataSelectable
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from pathlib import Path
from scipy import ndimage
from vtk.util.numpy_support import numpy_to_vtk


class HeterogeneityIndex(LTracePlugin):
    SETTING_KEY = "HeterogeneityIndex"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Heterogeneity Index"
        self.parent.categories = ["LTrace Tools"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = HeterogeneityIndex.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class HeterogeneityIndexWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)

        formLayout = qt.QFormLayout()
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Input")
        formLayout.addRow(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        self.inputSelector = hierarchyVolumeInput(onChange=self.onInputChanged, nodeTypes=["vtkMRMLScalarVolumeNode"])
        self.inputSelector.setToolTip("Select the amplitude image.")
        inputFormLayout.addRow("Amplitude image:", self.inputSelector)

        paramsCollapsibleButton = ctk.ctkCollapsibleButton()
        paramsCollapsibleButton.setText("Parameters")
        formLayout.addRow(paramsCollapsibleButton)
        paramsFormLayout = qt.QFormLayout(paramsCollapsibleButton)
        self.windowSizeSpinBox = qt.QDoubleSpinBox()
        self.windowSizeSpinBox.setDecimals(2)
        self.windowSizeSpinBox.setValue(0.5)
        self.windowSizeSpinBox.setSingleStep(0.05)
        self.windowSizeSpinBox.setToolTip(
            "Size in meters of the largest depth window which will be analyzed. Increasing this will result in a smoother HI curve."
        )
        paramsFormLayout.addRow("Window size (m):", self.windowSizeSpinBox)

        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        self.outputPrefixLineEdit = qt.QLineEdit()
        self.outputPrefixLineEdit.setToolTip('Output curve will be named "<prefix>_HI".')
        outputFormLayout.addRow("Output prefix:", self.outputPrefixLineEdit)

        self.statusLabel = qt.QLabel()
        self.statusLabel.setAlignment(qt.Qt.AlignRight)

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setFixedHeight(30)
        self.applyButton.enabled = False
        self.applyButton.clicked.connect(self.onApplyButtonClicked)
        self.applyButton.setToolTip("Compute heterogeneity index.")
        formLayout.addRow(self.applyButton)
        formLayout.addRow(self.statusLabel)

        self.layout.addLayout(formLayout)
        self.layout.addStretch(1)

    def onInputChanged(self, _):
        inputNode = self.inputSelector.currentNode()
        if inputNode:
            self.outputPrefixLineEdit.setText(inputNode.GetName())
        self.applyButton.enabled = inputNode is not None

    def onApplyButtonClicked(self):
        self.statusLabel.setText("Computing heterogeneity index...")
        slicer.app.processEvents()
        try:
            output_table = create_hi_curve(
                self.inputSelector.currentNode(), self.outputPrefixLineEdit.text, float(self.windowSizeSpinBox.value)
            )
            output_table.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)
            self.statusLabel.setText("Heterogeneity index computed.")
        except Exception as e:
            msg = "Error: " + str(e)
            self.statusLabel.setText(msg)
            slicer.util.errorDisplay(msg)
        slicer.app.processEvents()


def create_hi_curve(inputVolume, outputPrefix, window_size_m):
    array = slicer.util.arrayFromVolume(inputVolume)
    array[np.isnan(array)] = 0
    array = array.astype(np.float32).squeeze()
    hi = compute_hi(array, -inputVolume.GetOrigin()[2], inputVolume.GetSpacing()[2], window_size_m)
    outputName = slicer.mrmlScene.GetUniqueNameByString(outputPrefix + "_HI")
    table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", outputName)

    table.AddColumn(numpy_to_vtk(hi["DEPTH"].values, deep=True))
    table.AddColumn(numpy_to_vtk(hi["HI"].values, deep=True))
    table.GetTable().GetColumn(0).SetName("DEPTH")
    table.GetTable().GetColumn(1).SetName("HI")

    return table


def compute_hi(amp, y_origin, y_spacing, window_size_m):
    """Calculates standard deviation of amplitude image at different scales.
    The heterogeneity index is calculated by fitting a linear regression where
    X = log scale; Y = std
    The slope of the regression is the heterogeneity index.
    """
    img = ndimage.zoom(amp, 0.5, order=1)  # Image will be filtered by at least 2, so downsample to save time
    width = img.shape[1]

    sizes = 1, 2, 3, 4, 6, 8, 10, 12, 16, 20, 24, 28, 32, 40, 48, 56, 64
    size_mul = width / 128
    sizes = [max(round(size * size_mul), 1) for size in sizes]

    y_spacing *= 2
    window_size = int(window_size_m * 1000 / y_spacing)
    filtered = []
    ratio = window_size / width
    window_filtered_img = ndimage.uniform_filter(img, size=(window_size, img.shape[1]), mode="wrap")

    for size in sizes:
        filtered_img = ndimage.uniform_filter(img, size=(size * ratio, size), mode="wrap")
        filtered.append(filtered_img)

    filtered = np.array(filtered)
    sqr_diff = np.square(filtered - window_filtered_img)
    mean_sqr_diff = ndimage.uniform_filter(sqr_diff, size=(1, window_size, filtered.shape[2]), mode="wrap")
    stds = np.sqrt(mean_sqr_diff)
    stds = stds[:, :, 0]

    x = np.array(sizes).reshape((-1, 1))
    x = np.log(x) * 2  # Same as log(x^2), since cylinder sector volume is proportional to size^2
    x_with_intercept = np.hstack((x, np.ones_like(x)))
    coefficients, residuals, _, _ = np.linalg.lstsq(x_with_intercept, stds, rcond=None)
    slopes, intercepts = coefficients[:-1, :], coefficients[-1, :]
    hi_values = -slopes.flatten()

    df = pd.DataFrame(
        {
            "DEPTH": np.linspace(
                y_origin, y_origin + y_spacing * hi_values.shape[0], hi_values.shape[0], endpoint=False
            ),
            "HI": hi_values,
        }
    )
    return df
