import datetime
import logging
import os
import random
from collections import namedtuple
from pathlib import Path

import ctk
import numpy as np
import qt
import slicer
from scipy.optimize import curve_fit

from ltrace.slicer.helpers import (
    triggerNodeModified,
    getSourceVolume,
    highlight_error,
    reset_style_on_valid_text,
    copy_display,
    getVolumeNullValue,
    setVolumeNullValue,
    extractSegmentInfo,
)
from ltrace.slicer.ui import hierarchyVolumeInput, numberParamInt
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.transforms import clip_to
from ltrace.slicer import helpers
from ltrace.slicer.lazy import lazy

try:
    from Test.PolynomialShadingCorrectionTest import PolynomialShadingCorrectionTest
except ImportError:
    PolynomialShadingCorrectionTest = None  # tests not deployed to final version or closed source


class PolynomialShadingCorrection(LTracePlugin):
    SETTING_KEY = "PolynomialShadingCorrection"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Shading correction - Polynomial"
        self.parent.categories = ["LTrace Tools"]
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
            "inputMask",
            "inputShadingMask",
            SLICE_GROUP_SIZE,
            NUMBER_FITTING_POINTS,
            "outputImageName",
        ],
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def getSliceGroupSize(self):
        return PolynomialShadingCorrection.get_setting(self.SLICE_GROUP_SIZE, default="7")

    def getNumberFittingPoints(self):
        return PolynomialShadingCorrection.get_setting(self.NUMBER_FITTING_POINTS, default="1000")

    def __updateApplyToAll(self):
        inputNode = self.inputImageComboBox.currentNode()
        inputMaskNode = self.inputMaskComboBox.currentNode()
        inputShadingMaskNode = self.inputShadingMaskComboBox.currentNode()

        virtualInputNode = lazy.getParentLazyNode(inputNode) if inputNode is not None else None
        virtualInputMaskNode = lazy.getParentLazyNode(inputMaskNode) if inputMaskNode is not None else None
        virtualInputShadingMaskNode = (
            lazy.getParentLazyNode(inputShadingMaskNode) if inputShadingMaskNode is not None else None
        )
        hasVirtualNode = (
            virtualInputNode is not None
            and virtualInputMaskNode is not None
            and virtualInputShadingMaskNode is not None
        )

        self.applyFullButton.visible = hasVirtualNode

    def __onInputMaskChanged(self, itemId):
        self.__updateApplyToAll()

    def __onInputShadingMaskChanged(self, itemId):
        self.__updateApplyToAll()

    def setup(self):
        LTracePluginWidget.setup(self)

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        formLayout = qt.QFormLayout(frame)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        # Input section
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Input")
        formLayout.addRow(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.inputImageComboBox = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLScalarVolumeNode"], onChange=self.onInputImageChanged
        )
        self.inputImageComboBox.setObjectName("inputImageComboBox")
        self.inputImageComboBox.setToolTip("Select the input image.")
        inputFormLayout.addRow("Input image:", self.inputImageComboBox)
        self.inputImageComboBox.resetStyleOnValidNode()

        self.inputMaskComboBox = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLLabelMapVolumeNode", "vtkMRMLSegmentationNode"], onChange=self.__onInputMaskChanged
        )
        self.inputMaskComboBox.setObjectName("inputMaskComboBox")
        self.inputMaskComboBox.setToolTip("Select the input mask.")
        inputFormLayout.addRow("Input mask:", self.inputMaskComboBox)
        self.inputMaskComboBox.resetStyleOnValidNode()

        self.inputShadingMaskComboBox = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLLabelMapVolumeNode", "vtkMRMLSegmentationNode"],
            onChange=self.__onInputShadingMaskChanged,
        )
        self.inputShadingMaskComboBox.setObjectName("inputShadingMaskComboBox")
        self.inputShadingMaskComboBox.setToolTip("Select the input shading mask.")
        inputFormLayout.addRow("Input shading mask:", self.inputShadingMaskComboBox)
        inputFormLayout.addRow(" ", None)
        self.inputShadingMaskComboBox.resetStyleOnValidNode()

        # Parameters section
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.setText("Parameters")
        formLayout.addRow(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)

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

        self.outputImageNameLineEdit = qt.QLineEdit()
        self.outputImageNameLineEdit.setObjectName("outputImageNameLineEdit")
        outputFormLayout.addRow("Output image name:", self.outputImageNameLineEdit)
        outputFormLayout.addRow(" ", None)
        reset_style_on_valid_text(self.outputImageNameLineEdit)

        self.apply = qt.QPushButton("Apply")
        self.apply.setObjectName("applyButton")
        self.apply.setFixedHeight(40)
        self.apply.clicked.connect(self.onRegisterButtonClicked)

        self.applyFullButton = qt.QPushButton("Apply to full volume")
        self.applyFullButton.setFixedHeight(40)
        self.applyFullButton.toolTip = "Run the algorithm on the full volume."
        self.applyFullButton.clicked.connect(self.onApplyFull)
        self.applyFullButton.visible = False
        self.applyFullButton.setObjectName("applyAllButton")

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.setFixedHeight(40)
        self.cancelButton.setEnabled(False)
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.apply)
        buttonsHBoxLayout.addWidget(self.applyFullButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        formLayout.addRow(buttonsHBoxLayout)

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

    def onInputImageChanged(self, itemId):
        self.unrequireField(self.inputMaskComboBox)
        self.unrequireField(self.inputShadingMaskComboBox)

        self.inputMaskComboBox.setCurrentNode(None)
        self.inputShadingMaskComboBox.setCurrentNode(None)
        inputImage = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(itemId)
        if inputImage:
            outputImageName = inputImage.GetName() + self.OUTPUT_SUFFIX

            segmentationNodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
            for segmentationNode in segmentationNodes:
                if getSourceVolume(segmentationNode) == inputImage:
                    self.inputMaskComboBox.setCurrentNode(segmentationNode)
                    self.inputShadingMaskComboBox.setCurrentNode(segmentationNode)
                    break

        else:
            outputImageName = ""
        self.outputImageNameLineEdit.setText(outputImageName)
        self.__updateApplyToAll()

    def requireField(self, widget):
        widget.setStyleSheet("QWidget {background-color: #600000}")

    def unrequireField(self, widget):
        widget.setStyleSheet("")

    def onApplyFull(self):
        slicer.util.selectModule("PolynomialShadingCorrectionBigImage")
        widget = slicer.modules.PolynomialShadingCorrectionBigImageWidget

        params = {
            "inputNode": self.inputImageComboBox.currentNode(),
            "inputMaskNode": self.inputMaskComboBox.currentNode(),
            "inputShadingMaskNode": self.inputShadingMaskComboBox.currentNode(),
            "sliceGroupSize": self.sliceGroupSize.value,
            "numberFittingPoints": self.numberFittingPoints.value,
        }

        widget.setParameters(**params)

    def onRegisterButtonClicked(self):
        self.unrequireField(self.sliceGroupSize)

        try:
            if self.inputImageComboBox.currentNode() is None:
                highlight_error(self.inputImageComboBox)
                return

            inputNode = self.inputImageComboBox.currentNode()

            try:
                inputMaskNode = extractSegmentInfo(self.inputMaskComboBox.currentItem(), refNode=inputNode)
            except Exception as e:
                import traceback

                traceback.print_exc()
                logging.warning("Invalid input mask. Cause:" + repr(e))
                highlight_error(self.inputMaskComboBox)
                return

            try:
                inputShadingMaskNode = extractSegmentInfo(
                    self.inputShadingMaskComboBox.currentItem(), refNode=inputNode
                )
            except Exception as e:
                import traceback

                traceback.print_exc()
                logging.warning("Invalid input shading mask. Cause:" + repr(e))
                highlight_error(self.inputShadingMaskComboBox)
                return

            if self.sliceGroupSize.value % 2 == 0:
                highlight_error(self.sliceGroupSize)
                return

            inputImageDimensions = self.inputImageComboBox.currentNode().GetImageData().GetDimensions()
            maximumNumberFittingPoints = inputImageDimensions[0] * inputImageDimensions[1]
            if self.numberFittingPoints.value > maximumNumberFittingPoints:
                highlight_error(self.numberFittingPoints)
                raise ProcessInfo(
                    "Number of fitting points must be at maximum " + str(maximumNumberFittingPoints) + "."
                )

            if self.outputImageNameLineEdit.text.strip() == "":
                highlight_error(self.outputImageNameLineEdit)
                return

            PolynomialShadingCorrection.set_setting(self.SLICE_GROUP_SIZE, self.sliceGroupSize.value)
            PolynomialShadingCorrection.set_setting(self.NUMBER_FITTING_POINTS, self.numberFittingPoints.value)

            self.apply.setEnabled(False)
            self.applyFullButton.setEnabled(False)
            self.cancelButton.setEnabled(True)
            self.statusLabel.setText("Status: Running")
            self.statusLabel.show()
            self.progressBar.setValue(0)
            self.progressBar.show()
            slicer.app.processEvents()

            processParameters = self.ProcessParameters(
                inputNode,
                inputMaskNode,
                inputShadingMaskNode,
                self.sliceGroupSize.value,
                self.numberFittingPoints.value,
                self.outputImageNameLineEdit.text,
            )
            if self.logic.process(processParameters):
                self.statusLabel.setText("Status: Completed")
                self.progressBar.setValue(100)

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

        self.apply.setEnabled(True)
        self.applyFullButton.setEnabled(True)
        self.cancelButton.setEnabled(False)


class PolynomialShadingCorrectionLogic(LTracePluginLogic):
    def __init__(self, statusLabel, progressBar):
        LTracePluginLogic.__init__(self)
        self.statusLabel = statusLabel
        self.progressBar = progressBar
        self.cancelProcess = False

    def cancel(self):
        self.cancelProcess = True

    def process(self, parameters):
        self.cancelProcess = False

        self.inputImage = parameters.inputImage
        inputImageArray = slicer.util.arrayFromVolume(self.inputImage)

        inputMask = parameters.inputMask
        inputMaskArray = slicer.util.arrayFromVolume(inputMask)

        inputShadingMask = parameters.inputShadingMask
        inputShadingMaskArray = slicer.util.arrayFromVolume(inputShadingMask)

        nullValue = getVolumeNullValue(self.inputImage)

        try:
            outputImageArray = self.polynomialShadingCorrection(
                inputImageArray=inputImageArray,
                inputMaskArray=inputMaskArray,
                inputShadingMaskArray=inputShadingMaskArray,
                sliceGroupSize=parameters.sliceGroupSize,
                numberOfFittingPoints=parameters.numberFittingPoints,
                input_null_value=nullValue,
            )

            if self.cancelProcess:
                return False

            outputImage = slicer.modules.volumes.logic().CloneVolume(self.inputImage, parameters.outputImageName)
            slicer.util.updateVolumeFromArray(outputImage, outputImageArray)
            setVolumeNullValue(outputImage, outputImageArray[inputMaskArray == 0][0])

            copy_display(self.inputImage, outputImage)

            subjectHierarchyNode = slicer.mrmlScene.GetSubjectHierarchyNode()
            itemParent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(self.inputImage))
            subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(outputImage), itemParent)

            slicer.util.setSliceViewerLayers(background=outputImage, foreground=None, label=None, fit=True)
        except Exception as e:
            import traceback

            traceback.print_exc()

            slicer.util.infoDisplay("An unexpected error has occurred during the shading correction process: " + str(e))
        finally:
            helpers.removeTemporaryNodes()

        return True

    def polynomialShadingCorrection(
        self,
        inputImageArray,
        inputMaskArray,
        inputShadingMaskArray,
        sliceGroupSize=1,
        numberOfFittingPoints=1000,
        input_null_value=None,
    ):
        start = datetime.datetime.now()

        outputImageArray = inputImageArray.copy()
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
                outputImageArray[j] = inputImageArray[j] / zz

            # In the last iteration, proceed to apply the function in all the remaining slices
            if i == iterationIndexes[-1]:
                end = len(inputImageArray)
            else:
                end = i + sliceGroupSize // 2 + 1

            for j in range(i + 1, end):
                outputImageArray[j] = inputImageArray[j] / zz

        end = datetime.datetime.now()
        elapsed = end - start
        logging.info("Polynomial shading correction elapsed time: " + str(elapsed.total_seconds()))

        output_null_value = input_null_value if input_null_value != None else 0
        outputImageArray[inputMaskArray == 0] = output_null_value

        # Converting to uint16
        outputImageArray = clip_to(outputImageArray, "uint16")

        return outputImageArray

    def polynomial(self, data, a, b, c, d, e, f, g, h):
        x, y = data
        return a * (x - b) ** 2 + c * (y - d) ** 2 + e * (x - b) + f * (y - d) + g * (x - b) * (y - d) + h

    def plane(self, data, a, b, c, d, e):
        x, y = data
        return a * (x - b) + c * (y - d) + e


class ProcessInfo(RuntimeError):
    pass
