import slicer
import qt
import ctk
import datetime
import logging
import numpy as np
import os
import random
import traceback

from collections import namedtuple
from enum import Enum

from ltrace.flow.util import createSimplifiedSegmentEditor, onSegmentEditorEnter, onSegmentEditorExit

from ltrace.slicer.helpers import (
    highlight_error,
    reset_style_on_valid_text,
    copy_display,
    getVolumeNullValue,
    setVolumeNullValue,
    extractSegmentInfo,
    remove_highlight,
    safe_convert_array,
)

from ltrace.slicer.ui import hierarchyVolumeInput, numberParamInt
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer import helpers
from ltrace.slicer.lazy import lazy
from ltrace.slicer.widget.status_panel import StatusPanel
from pathlib import Path
from scipy.optimize import curve_fit
from scipy.ndimage import gaussian_filter1d
from scipy.interpolate import interp1d


try:
    from Test.PolynomialShadingCorrectionTest import PolynomialShadingCorrectionTest
except ImportError:
    PolynomialShadingCorrectionTest = None  # tests not deployed to final version or closed source


def normalize_z(data_3d, sigma=3.0, quantile_low=0.4, quantile_high=0.95, downsample=8):
    """
    Normalize a 3D volume along its Z-axis using quantile-based normalization.
    """

    orig_dtype = data_3d.dtype
    z_size = data_3d.shape[0]

    data_downsampled = data_3d[::downsample]

    low_q = np.quantile(data_downsampled, quantile_low, axis=(1, 2))
    high_q = np.quantile(data_downsampled, quantile_high, axis=(1, 2))

    global_low = low_q.mean()
    global_high = high_q.mean()

    low_q_smooth = gaussian_filter1d(low_q, sigma)
    high_q_smooth = gaussian_filter1d(high_q, sigma)

    z_down = np.arange(0, z_size, downsample)
    z_full = np.arange(z_size)
    interp_low = interp1d(z_down, low_q_smooth, kind="linear", bounds_error=False, fill_value="extrapolate")
    interp_high = interp1d(z_down, high_q_smooth, kind="linear", bounds_error=False, fill_value="extrapolate")

    low_q_interp = interp_low(z_full)[:, None, None]
    high_q_interp = interp_high(z_full)[:, None, None]

    range_q = np.clip(high_q_interp - low_q_interp, 1e-8, None)

    data_float = data_3d.astype(np.float32)
    mult = (global_high - global_low) / range_q
    normalized_float = (data_float - low_q_interp) * mult + global_low

    if np.issubdtype(orig_dtype, np.integer):
        normalized_float = np.clip(normalized_float, np.iinfo(orig_dtype).min, np.iinfo(orig_dtype).max)

    normalized_data = normalized_float.astype(orig_dtype)

    return normalized_data


class PolynomialShadingCorrection(LTracePlugin):
    SETTING_KEY = "PolynomialShadingCorrection"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Shading correction - Polynomial"
        self.parent.categories = ["Tools", "MicroCT", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = PolynomialShadingCorrection.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PolynomialShadingCorrectionWidget(LTracePluginWidget):
    # Settings constants
    SLICE_GROUP_SIZE = "sliceGroupSize"
    NUMBER_FITTING_POINTS = "numberFittingPoints"
    OUTPUT_SUFFIX = "_ShadingCorrection"

    ProcessParameters = namedtuple(
        "ProcessParameters",
        [
            "inputImage",
            "shadingMask",
            SLICE_GROUP_SIZE,
            NUMBER_FITTING_POINTS,
            "outputImageName",
        ],
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.normalizedVolume = None
        self.samplingMaskSegmentation = None

    def getSliceGroupSize(self):
        return PolynomialShadingCorrection.get_setting(self.SLICE_GROUP_SIZE, default="7")

    def getNumberFittingPoints(self):
        return PolynomialShadingCorrection.get_setting(self.NUMBER_FITTING_POINTS, default="1000")

    def __updateApplyToAll(self):
        inputNode = self.inputImageComboBox.currentNode()
        virtualInputNode = lazy.getParentLazyNode(inputNode) if inputNode is not None else None
        hasVirtualNode = virtualInputNode is not None
        self.applyFullButton.visible = hasVirtualNode

    class WidgetState(Enum):
        INITIAL = "initial"
        THRESHOLD = "threshold"
        PROCESS = "process"

    def updateWidgetsVisibility(self, state):
        if state == self.WidgetState.INITIAL:
            self.inputCollapsibleButton.collapsed = False
            self.parametersCollapsibleButton.visible = False
            self.outputCollapsibleButton.visible = False
            self.thresholdCollapsibleButton.visible = False
            self.statusPanel.set_instruction("Choose the input image to correct.")
        elif state == self.WidgetState.THRESHOLD:
            self.inputCollapsibleButton.collapsed = True
            self.parametersCollapsibleButton.visible = False
            self.outputCollapsibleButton.visible = False
            self.thresholdCollapsibleButton.visible = True
            self.samplingMaskSegmentation.GetDisplayNode().SetVisibility(True)
            slicer.util.setSliceViewerLayers(background=self.normalizedVolume, fit=True)
            self.statusPanel.set_instruction("Adjust the threshold to create a sampling mask.")
        elif state == self.WidgetState.PROCESS:
            self.inputCollapsibleButton.collapsed = True
            self.parametersCollapsibleButton.visible = True
            self.outputCollapsibleButton.visible = True
            self.thresholdCollapsibleButton.visible = False
            self.samplingMaskSegmentation.GetDisplayNode().SetVisibility(False)
            self.apply.setEnabled(True)
            self.statusPanel.set_instruction("Choose the parameters and run the shading correction.")

    def setup(self):
        LTracePluginWidget.setup(self)

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        formLayout = qt.QFormLayout(frame)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        self.statusPanel = StatusPanel("")
        self.statusPanel.statusLabel.setWordWrap(True)
        formLayout.addRow(self.statusPanel)

        # Input section
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Input")
        formLayout.addRow(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.inputCollapsibleButton = inputCollapsibleButton

        self.inputImageComboBox = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLScalarVolumeNode"], onChange=self.onInputImageChanged
        )
        self.inputImageComboBox.setObjectName("inputImageComboBox")
        self.inputImageComboBox.setToolTip("Select the input image.")
        inputFormLayout.addRow("Input image:", self.inputImageComboBox)
        self.inputImageComboBox.resetStyleOnValidNode()

        self.keepNormalizedBox = qt.QCheckBox("Keep intermediate image")
        self.keepNormalizedBox.setToolTip(
            "The image slices are pre-normalized to make the thresholding step easier. "
            "If this option is checked, the normalized image will be kept in the project."
        )
        inputFormLayout.addRow(self.keepNormalizedBox)

        # Initialize button
        self.initializeButton = qt.QPushButton("Initialize")
        self.initializeButton.setObjectName("initializeButton")
        self.initializeButton.setToolTip("Normalize the input volume and prepare for thresholding.")
        self.initializeButton.clicked.connect(self.onInitializeButtonClicked)
        inputFormLayout.addRow("", self.initializeButton)

        # Segment Editor
        widget, _, self.sourceVolumeBox, self.segmentationBox = createSimplifiedSegmentEditor()
        widget.setObjectName("thresholdEditor")
        effects = ["Threshold"]
        widget.setEffectNameOrder(effects)
        widget.unorderedEffectsVisible = False
        tableView = widget.findChild(qt.QTableView, "SegmentsTable")
        tableView.setFixedHeight(100)

        self.thresholdCollapsibleButton = ctk.ctkCollapsibleButton()
        self.thresholdCollapsibleButton.setText("Threshold")
        formLayout.addRow(self.thresholdCollapsibleButton)
        thresholdLayout = qt.QVBoxLayout(self.thresholdCollapsibleButton)

        thresholdLayout.addWidget(widget)
        self.segmentEditorWidget = widget

        # Parameters section
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.setText("Parameters")
        formLayout.addRow(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.parametersCollapsibleButton = parametersCollapsibleButton

        self.sliceGroupSize = qt.QSpinBox()
        self.sliceGroupSize.setObjectName("sliceGroupSize")
        self.sliceGroupSize.setRange(1, 9)
        self.sliceGroupSize.setSingleStep(2)
        self.sliceGroupSize.setValue(int(self.getSliceGroupSize()))
        self.sliceGroupSize.setToolTip(
            "This parameter will cause the polynomial function to be fitted for the central slice in the group of slices. All the other "
            "slices of the group will use the same fitted function."
        )
        parametersFormLayout.addRow("Slice group size:", self.sliceGroupSize)
        self.sliceGroupSize.valueChanged.connect(lambda: self.sliceGroupSize.setStyleSheet(""))

        self.numberFittingPoints = numberParamInt(vrange=(100, 999999), value=int(self.getNumberFittingPoints()))
        self.numberFittingPoints.setObjectName("numberFittingPoints")
        self.numberFittingPoints.setToolTip("Number of points used in the function fitting process.")
        parametersFormLayout.addRow("Number of fitting points:", self.numberFittingPoints)
        parametersFormLayout.addRow(" ", None)

        # Output section
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.outputCollapsibleButton = outputCollapsibleButton

        self.outputImageNameLineEdit = qt.QLineEdit()
        self.outputImageNameLineEdit.setObjectName("outputImageNameLineEdit")
        outputFormLayout.addRow("Output image name:", self.outputImageNameLineEdit)
        outputFormLayout.addRow(" ", None)
        reset_style_on_valid_text(self.outputImageNameLineEdit)

        self.apply = qt.QPushButton("Apply")
        self.apply.setObjectName("applyButton")
        self.apply.setFixedHeight(40)
        self.apply.clicked.connect(self.onRegisterButtonClicked)
        self.apply.setEnabled(False)  # Disabled until initialization and thresholding

        self.applyFullButton = qt.QPushButton("Apply to full volume")
        self.applyFullButton.setFixedHeight(40)
        self.applyFullButton.toolTip = "Run the algorithm on the full volume."
        self.applyFullButton.clicked.connect(self.onApplyFull)
        self.applyFullButton.visible = False
        self.applyFullButton.setObjectName("applyAllButton")

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.setObjectName("cancelButton")
        self.cancelButton.setFixedHeight(40)
        self.cancelButton.setEnabled(False)
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.apply)
        buttonsHBoxLayout.addWidget(self.applyFullButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        outputFormLayout.addRow(buttonsHBoxLayout)

        self.statusLabel = qt.QLabel()
        self.statusLabel.setAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)
        self.statusLabel.hide()
        formLayout.addRow(self.statusLabel)

        self.progressBar = qt.QProgressBar()
        self.progressBar.setValue(0)
        self.progressBar.hide()
        formLayout.addRow(self.progressBar)

        self.logic = PolynomialShadingCorrectionLogic(self.statusLabel, self.progressBar)

        self.layout.addStretch(1)

        self.reset()

    def onInputImageChanged(self, itemId):
        self.reset()

        inputImage = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(itemId)
        if inputImage:
            outputImageName = inputImage.GetName() + self.OUTPUT_SUFFIX
        else:
            outputImageName = ""

        self.outputImageNameLineEdit.setText(outputImageName)
        self.__updateApplyToAll()

    def reset(self):
        if self.samplingMaskSegmentation:
            slicer.mrmlScene.RemoveNode(self.samplingMaskSegmentation)
            self.samplingMaskSegmentation = None
        if self.normalizedVolume and not self.keepNormalized:
            slicer.mrmlScene.RemoveNode(self.normalizedVolume)
            self.normalizedVolume = None
        self.inputNode = None

        onSegmentEditorExit(self.segmentEditorWidget)
        self.updateWidgetsVisibility(self.WidgetState.INITIAL)

    def exit(self):
        self.reset()

    def onInitializeButtonClicked(self):
        inputNode = self.inputImageComboBox.currentNode()
        if not inputNode:
            highlight_error(self.inputImageComboBox)
            return

        onSegmentEditorEnter(self.segmentEditorWidget, "ShadingMask")

        # Show status
        self.statusLabel.setText("Status: Normalizing volume...")
        self.statusLabel.show()
        self.progressBar.setValue(0)
        self.progressBar.show()
        slicer.app.processEvents()

        try:
            inputArray = slicer.util.arrayFromVolume(inputNode)

            self.progressBar.setValue(30)
            slicer.app.processEvents()

            normalizedArray = normalize_z(inputArray)

            self.progressBar.setValue(60)
            slicer.app.processEvents()

            self.reset()

            self.inputNode = inputNode

            self.keepNormalized = self.keepNormalizedBox.isChecked()

            volumeName = inputNode.GetName() + "_PreNormalized"
            self.normalizedVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", volumeName)
            self.normalizedVolume.CopyOrientation(inputNode)
            copy_display(inputNode, self.normalizedVolume)
            slicer.util.updateVolumeFromArray(self.normalizedVolume, normalizedArray)
            if not self.keepNormalizedBox.isChecked():
                self.normalizedVolume.SetHideFromEditors(True)
                self.normalizedVolume.SaveWithSceneOff()

            self.progressBar.setValue(80)
            slicer.app.processEvents()

            self.samplingMaskSegmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
            self.samplingMaskSegmentation.SetName(inputNode.GetName() + "_sampling_mask")
            self.samplingMaskSegmentation.CreateDefaultDisplayNodes()
            self.samplingMaskSegmentation.SetReferenceImageGeometryParameterFromVolumeNode(self.normalizedVolume)
            self.samplingMaskSegmentation.GetSegmentation().AddEmptySegment("Sampling Mask", "Sampling Mask")
            self.samplingMaskSegmentation.SetHideFromEditors(True)
            self.samplingMaskSegmentation.SaveWithSceneOff()

            self.segmentationBox.setCurrentNode(self.samplingMaskSegmentation)
            self.sourceVolumeBox.setCurrentNode(self.normalizedVolume)
            self.segmentEditorWidget.setActiveEffectByName("Threshold")

            maskingWidget = self.segmentEditorWidget.findChild(qt.QGroupBox, "MaskingGroupBox")
            maskingWidget.visible = False
            maskingWidget.setFixedHeight(0)

            self.updateWidgetsVisibility(self.WidgetState.THRESHOLD)

            effect = self.segmentEditorWidget.effectByName("Threshold")
            applyThresholdButton = effect.self().applyButton
            applyThresholdButton.clicked.connect(lambda: self.updateWidgetsVisibility(self.WidgetState.PROCESS))

            pulseBox = effect.self().enablePulsingCheckbox
            pulseBox.setChecked(False)
            pulseBox.hide()

            frame = effect.optionsFrame()
            for groupBox in frame.findChildren(ctk.ctkCollapsibleGroupBox):
                groupBox.hide()

            self.statusLabel.setText("Status: Ready")
            self.progressBar.setValue(0)

        except Exception as e:
            import traceback

            traceback.print_exc()
            self.statusLabel.setText("Status: Error during initialization")
            slicer.util.errorDisplay(f"Failed to initialize: {str(e)}")
        finally:
            slicer.app.processEvents()

    def onApplyFull(self):
        slicer.util.selectModule("PolynomialShadingCorrectionBigImage")
        widget = slicer.modules.PolynomialShadingCorrectionBigImageWidget

        # Get the segmentation as a labelmap
        if not self.samplingMaskSegmentation:
            slicer.util.errorDisplay("Please initialize and create a threshold segment first.")
            return

        # Create parameters for the full volume processing
        params = {
            "inputNode": self.inputNode,
            "inputMaskNode": None,
            "inputShadingMaskNode": self.samplingMaskSegmentation,
            "sliceGroupSize": self.sliceGroupSize.value,
            "numberFittingPoints": self.numberFittingPoints.value,
        }

        widget.setParameters(**params)

    def resetInputWidgetsStyle(self):
        remove_highlight(self.inputImageComboBox)
        remove_highlight(self.sliceGroupSize)
        remove_highlight(self.numberFittingPoints)
        remove_highlight(self.outputImageNameLineEdit)

    def onRegisterButtonClicked(self):
        self.unrequireField(self.sliceGroupSize)

        try:
            if self.inputImageComboBox.currentNode() is None:
                highlight_error(self.inputImageComboBox)
                return

            inputNode = self.inputNode

            if not self.samplingMaskSegmentation:
                slicer.util.errorDisplay("Please initialize and create a threshold segment first.")
                return

            if self.sliceGroupSize.value % 2 == 0:
                highlight_error(self.sliceGroupSize)
                return

            if self.outputImageNameLineEdit.text.strip() == "":
                highlight_error(self.outputImageNameLineEdit)
                return

            inputImageDimensions = self.inputImageComboBox.currentNode().GetImageData().GetDimensions()
            maximumNumberFittingPoints = inputImageDimensions[0] * inputImageDimensions[1]
            if self.numberFittingPoints.value > maximumNumberFittingPoints:
                highlight_error(self.numberFittingPoints)
                raise ProcessInfo(
                    "Number of fitting points must be at maximum " + str(maximumNumberFittingPoints) + "."
                )

            inputNode = self.inputImageComboBox.currentNode()

            PolynomialShadingCorrection.set_setting(self.SLICE_GROUP_SIZE, self.sliceGroupSize.value)
            PolynomialShadingCorrection.set_setting(self.NUMBER_FITTING_POINTS, self.numberFittingPoints.value)

            self.resetInputWidgetsStyle()
            self.apply.setEnabled(False)
            self.applyFullButton.setEnabled(False)
            self.cancelButton.setEnabled(True)
            self.statusLabel.setText("Status: Running")
            self.statusLabel.show()
            self.progressBar.setValue(0)
            self.progressBar.show()
            slicer.app.processEvents()

            # Convert the segmentation to labelmap for processing
            labelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
            slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(
                self.samplingMaskSegmentation, labelMapNode, inputNode
            )

            processParameters = self.ProcessParameters(
                inputNode,
                labelMapNode,
                self.sliceGroupSize.value,
                self.numberFittingPoints.value,
                self.outputImageNameLineEdit.text,
            )

            if self.logic.process(processParameters):
                self.statusLabel.setText("Status: Completed")
                self.progressBar.setValue(100)

            # Clean up temporary labelmap
            slicer.mrmlScene.RemoveNode(labelMapNode)

            # Clean up other intermediate nodes
            self.reset()

        except ProcessInfo as e:
            self.statusLabel.setText("Status: Not completed")
            slicer.util.infoDisplay(str(e))
        except RuntimeError as e:
            self.statusLabel.setText("Status: Not completed")
            slicer.util.infoDisplay("An unexpected error has occurred: " + str(e))
        finally:
            self.apply.setEnabled(True)
            self.applyFullButton.setEnabled(True)
            self.cancelButton.setEnabled(False)

    def onCancelButtonClicked(self):
        self.statusLabel.setText("Status: Canceled")
        self.progressBar.hide()
        self.logic.cancel()
        helpers.removeTemporaryNodes()
        self.apply.setEnabled(True)
        self.applyFullButton.setEnabled(True)
        self.cancelButton.setEnabled(False)

    def requireField(self, widget):
        widget.setStyleSheet("QWidget {background-color: #600000}")

    def unrequireField(self, widget):
        widget.setStyleSheet("")


class PolynomialShadingCorrectionLogic(LTracePluginLogic):
    def __init__(self, statusLabel, progressBar):
        LTracePluginLogic.__init__(self)
        self.statusLabel = statusLabel
        self.progressBar = progressBar
        self.cancelProcess = False

    def cancel(self):
        self.cancelProcess = True

    def process(self, parameters: PolynomialShadingCorrectionWidget.ProcessParameters) -> bool:
        self.cancelProcess = False

        self.inputImage = parameters.inputImage
        inputImageArray = slicer.util.arrayFromVolume(self.inputImage)

        shadingMask = parameters.shadingMask
        shadingMaskArray = slicer.util.arrayFromVolume(shadingMask)

        nullValue = getVolumeNullValue(self.inputImage)

        try:
            outputImageArray = self.polynomialShadingCorrection(
                inputImageArray=inputImageArray,
                inputShadingMaskArray=shadingMaskArray,
                sliceGroupSize=parameters.sliceGroupSize,
                numberOfFittingPoints=parameters.numberFittingPoints,
                input_null_value=nullValue,
            )

            if self.cancelProcess:
                return False

            outputImage = slicer.modules.volumes.logic().CloneVolume(self.inputImage, parameters.outputImageName)
            slicer.util.updateVolumeFromArray(outputImage, outputImageArray)
            setVolumeNullValue(outputImage, nullValue)

            copy_display(self.inputImage, outputImage)

            subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
            itemParent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(self.inputImage))
            subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(outputImage), itemParent)

            slicer.util.setSliceViewerLayers(background=outputImage, foreground=None, label=None, fit=True)
        except Exception as e:
            traceback.print_exc()
            slicer.util.infoDisplay("An unexpected error has occurred during the shading correction process: " + str(e))
        finally:
            helpers.removeTemporaryNodes()

        return True

    def polynomialShadingCorrection(
        self,
        inputImageArray,
        inputShadingMaskArray,
        sliceGroupSize=1,
        numberOfFittingPoints=1000,
        input_null_value=None,
    ):
        start = datetime.datetime.now()

        outputImageArray = np.zeros_like(inputImageArray, dtype=np.float32)
        array = inputImageArray[inputShadingMaskArray != 0]
        inputArrayShadingMaskMax = np.max(array)
        inputArrayShadingMaskMean = np.mean(array)
        initialParameters = [
            1,
            inputImageArray.shape[1] / 2,
            1,
            inputImageArray.shape[2] / 2,
            1,
            1,
            1,
            inputArrayShadingMaskMax,
        ]

        x, y = np.meshgrid([i for i in range(inputImageArray.shape[1])], [j for j in range(inputImageArray.shape[2])])

        iterationIndexes = np.arange(sliceGroupSize // 2, len(inputImageArray), sliceGroupSize)
        for i in iterationIndexes:
            if self.cancelProcess:
                break

            end = datetime.datetime.now()
            elapsed = end - start

            self.statusLabel.setText("Status: Running (" + str(np.round(elapsed.total_seconds(), 1)) + ")")

            self.progressBar.setValue(round(100 * (i / len(inputImageArray))))
            slicer.app.processEvents()

            # Selecting random points
            xData, yData = np.where(inputShadingMaskArray[i] != 0)
            if len(xData) == 0:  # if no indexes where found
                continue
            data = [(x, y) for x, y in zip(xData, yData)]
            data = random.sample(data, min(len(data), numberOfFittingPoints))
            xData, yData = list(zip(*data))
            zData = inputImageArray[i][(xData, yData)]

            # Fitting
            function = self.polynomial
            try:
                fittedParameters, pcov = curve_fit(function, [xData, yData], zData, p0=initialParameters)
                initialParameters = fittedParameters
            except:
                # If the polynomial fitting fails, try to fit a simple plane
                function = self.plane
                try:
                    fittedParameters, pcov = curve_fit(
                        function,
                        [xData, yData],
                        zData,
                        p0=[1, inputImageArray.shape[1] / 2, 1, inputImageArray.shape[2] / 2, inputArrayShadingMaskMax],
                    )
                except:
                    # If nothing can be fitted, skip
                    continue

            # Applying function
            z = function((x, y), *fittedParameters)
            z = np.swapaxes(z, 0, 1)
            zz = z / inputArrayShadingMaskMean

            # Adjusting slice data
            for j in range(i - sliceGroupSize // 2, i + 1):
                outputImageArray[j] = zz

            # In the last iteration, proceed to apply the function in all the remaining slices
            if i == iterationIndexes[-1]:
                end = len(inputImageArray)
            else:
                end = i + sliceGroupSize // 2 + 1

            for j in range(i + 1, end):
                outputImageArray[j] = zz

        # Apply 1D gaussian filter to smooth the shading correction
        outputImageArray = gaussian_filter1d(outputImageArray, sigma=3, axis=0)
        outputImageArray = inputImageArray / outputImageArray

        if input_null_value is not None:
            outputImageArray[inputImageArray == input_null_value] = input_null_value

        outputImageArray = safe_convert_array(outputImageArray, inputImageArray.dtype.name)
        end = datetime.datetime.now()
        elapsed = end - start
        logging.info("Polynomial shading correction elapsed time: " + str(elapsed.total_seconds()))

        return outputImageArray

    def polynomial(self, data, a, b, c, d, e, f, g, h):
        x, y = data
        return a * (x - b) ** 2 + c * (y - d) ** 2 + e * (x - b) + f * (y - d) + g * (x - b) * (y - d) + h

    def plane(self, data, a, b, c, d, e):
        x, y = data
        return a * (x - b) + c * (y - d) + e


class ProcessInfo(RuntimeError):
    pass
