import ctk
import json
import os
import qt
import slicer
import logging
import sys
import vtk
import numpy as np
import ltrace.slicer.helpers as helpers
import traceback

from ltrace.slicer.app import getApplicationVersion
from ltrace.slicer.lazy import lazy
from ltrace.slicer import ui
from ltrace.slicer.ui import numberParamInt
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer.widget.custom_path_line_edit import CustomPathLineEdit
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from pathlib import Path
from pathvalidate import sanitize_filepath
from ltrace.slicer import netcdf

from PolynomialShadingCorrection import PolynomialShadingCorrection

try:
    from Test.PolynomialShadingCorrectionBigImageTest import PolynomialShadingCorrectionBigImageTest
except ImportError:
    PolynomialShadingCorrectionBigImageTest = None  # tests not deployed to final version or closed source


from dataclasses import dataclass

SLICE_GROUP_SIZE = "sliceGroupSize"
FITTING_POINTS_PERCENTAGE = "fittingPointsPercentage"
FUNCTION_TYPE = "functionType"
POLYNOMIAL_ORDER = "polynomialOrder"


@dataclass
class PolynomialShadingCorrectionParameters:
    inputNode: slicer.vtkMRMLNode = None
    inputShadingMaskNode: slicer.vtkMRMLNode = None
    sliceGroupSize: int = None
    fittingPointsPercentage: int = None
    exportPath: str = None
    functionType: str = None
    polynomialOrder: int = None
    useCustomCenter: bool = None
    centerX: int = None
    centerY: int = None


class PolynomialShadingCorrectionBigImage(LTracePlugin):
    SETTING_KEY = "PolynomialShadingCorrectionBigImage"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent: qt.QWidget) -> None:
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Polynomial Shading Correction for Big Images"
        self.parent.categories = ["Tools", "MicroCT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = PolynomialShadingCorrectionBigImage.help()
        self.setHelpUrl("Volumes/BigImage/BigImage.html#polynomial-shading-correction")

    @classmethod
    def readme_path(cls: LTracePlugin) -> None:
        return str(cls.MODULE_DIR / "README.md")


class PolynomialShadingCorrectionBigImageWidget(LTracePluginWidget):
    def __init__(self, parent: qt.QWidget) -> None:
        LTracePluginWidget.__init__(self, parent)
        self.logic = None
        self.title = "Polynomial Shading Correction Big Image"
        self.centerFiducialNode = None
        self.pointAddedObserverTag = None

    def getSliceGroupSize(self) -> int:
        return int(PolynomialShadingCorrection.get_setting(SLICE_GROUP_SIZE, default="1"))

    def getFittingPointsPercentage(self) -> int:
        return int(PolynomialShadingCorrection.get_setting(FITTING_POINTS_PERCENTAGE, default="60"))

    def setup(self) -> None:
        LTracePluginWidget.setup(self)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.collapsed = False
        inputSection.text = "Input"

        self.__inputSelector = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLScalarVolumeNode", "vtkMRMLTextNode"],
            tooltip="Select the image within the NetCDF dataset to filter.",
            onChange=self.onInputImageChanged,
        )
        self.__inputSelector.objectName = "Input Image Selector"

        self.__inputShadingMaskSelector = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLLabelMapVolumeNode", "vtkMRMLSegmentationNode", "vtkMRMLTextNode"],
            tooltip="Select the input mask.",
        )
        self.__inputShadingMaskSelector.objectName = "Input Shading Mask Selector"

        inputLayout = qt.QFormLayout(inputSection)
        inputLayout.addRow("Input image:", self.__inputSelector)
        inputLayout.addRow("Input shading mask:", self.__inputShadingMaskSelector)

        # Parameters section
        parametersSection = ctk.ctkCollapsibleButton()
        parametersSection.text = "Parameters"
        parametersSection.collapsed = False
        parametersSection.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        self.__functionTypeComboBox = qt.QComboBox()
        self.__functionTypeComboBox.addItems(["Polynomial", "Polynomial Radial", "Spline Radial"])
        self.__functionTypeComboBox.setCurrentText(
            PolynomialShadingCorrection.get_setting(FUNCTION_TYPE, default="Polynomial Radial")
        )
        self.__functionTypeComboBox.currentTextChanged.connect(self.onFunctionTypeChanged)

        self.__polynomialOrderComboBox = qt.QComboBox()
        self.__polynomialOrderComboBox.addItems(["2", "4", "6"])
        self.__polynomialOrderComboBox.setCurrentText(
            PolynomialShadingCorrection.get_setting(POLYNOMIAL_ORDER, default="6")
        )

        centerLayout = qt.QHBoxLayout()
        self.__useCustomCenterCheckBox = qt.QCheckBox("Set")
        self.__centerXSpinBox = qt.QSpinBox()
        self.__centerXSpinBox.setRange(0, 100000)
        self.__centerXSpinBox.setEnabled(False)
        self.__centerYSpinBox = qt.QSpinBox()
        self.__centerYSpinBox.setRange(0, 100000)
        self.__centerYSpinBox.setEnabled(False)

        self.__pickCenterButton = qt.QPushButton("Pick Red View")
        self.__pickCenterButton.setObjectName("pickCenterButton")
        self.__pickCenterButton.setEnabled(False)
        self.__pickCenterButton.clicked.connect(self.onPickCenterClicked)

        self.__useCustomCenterCheckBox.toggled.connect(self.__centerXSpinBox.setEnabled)
        self.__useCustomCenterCheckBox.toggled.connect(self.__centerYSpinBox.setEnabled)
        self.__useCustomCenterCheckBox.toggled.connect(self.__pickCenterButton.setEnabled)

        centerLayout.addWidget(self.__useCustomCenterCheckBox)
        centerLayout.addStretch(1)
        centerLayout.addWidget(qt.QLabel("X"))
        centerLayout.addWidget(self.__centerXSpinBox)
        centerLayout.addWidget(qt.QLabel("Y"))
        centerLayout.addWidget(self.__centerYSpinBox)
        centerLayout.addStretch(1)
        centerLayout.addWidget(self.__pickCenterButton)

        self.__sliceGroupSize = qt.QSpinBox()
        self.__sliceGroupSize.objectName = "Slice Group Size"
        self.__sliceGroupSize.setRange(1, 9)
        self.__sliceGroupSize.setSingleStep(2)
        self.__sliceGroupSize.setValue(self.getSliceGroupSize())
        self.__sliceGroupSize.setToolTip(
            "This parameter will cause the polynomial function to be fitted for the central slice in the group of slices. All the other "
            "slices of the group will use the same fitted function."
        )

        self.__fittingPointsPercentage = numberParamInt(vrange=(1, 100), value=int(self.getFittingPointsPercentage()))
        self.__fittingPointsPercentage.setObjectName("Fitting Points Percentage")
        self.__fittingPointsPercentage.setToolTip("Percentage of points used in the function fitting process.")

        self.parametersLayout = qt.QFormLayout(parametersSection)
        self.parametersLayout.addRow("Function:", self.__functionTypeComboBox)
        self.parametersLayout.addRow("Center:", centerLayout)
        self.parametersLayout.addRow("Order:", self.__polynomialOrderComboBox)
        self.parametersLayout.addRow("Group size:", self.__sliceGroupSize)
        self.parametersLayout.addRow("Fitting points (%):", self.__fittingPointsPercentage)

        # Output section
        outputSection = ctk.ctkCollapsibleButton()
        outputSection.text = "Output"
        outputSection.collapsed = False

        self.__exportPathEdit = CustomPathLineEdit()
        self.__exportPathEdit.filters = ctk.ctkPathLineEdit.Files | ctk.ctkPathLineEdit.Writable
        self.__exportPathEdit.nameFilters = ["*.nc"]
        self.__exportPathEdit.settingKey = "PolynomialShadingCorrectionBigImage/OutputPath"
        self.__exportPathEdit.setToolTip("Select the output path for the .nc image file output")
        self.__exportPathEdit.objectName = "Output Path Line Edit"

        outputFormLayout = qt.QFormLayout(outputSection)
        outputFormLayout.addRow("Output Path:", self.__exportPathEdit)

        # Apply button
        self.__applyButton = ui.ApplyButton(
            onClick=self.__onApplyButtonClicked, tooltip="Apply changes", enabled=True, object_name="Apply Button"
        )

        self.__cancelButton = qt.QPushButton("Cancel")
        self.__cancelButton.setEnabled(False)
        self.__cancelButton.clicked.connect(self.__onCancelButtonClicked)
        self.__cancelButton.objectName = "Cancel Button"

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.__applyButton)
        buttonsHBoxLayout.addWidget(self.__cancelButton)

        # CLI progress bar
        self.__cliProgressBar = LocalProgressBar()

        # Update layout
        self.layout.addWidget(inputSection)
        self.layout.addWidget(parametersSection)
        self.layout.addWidget(outputSection)
        self.layout.addLayout(buttonsHBoxLayout)
        self.layout.addWidget(self.__cliProgressBar)
        self.layout.addStretch(1)

        self.onFunctionTypeChanged(self.__functionTypeComboBox.currentText)

    def onInputImageChanged(self, itemId):
        inputImage = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(itemId)
        if inputImage and inputImage.IsA("vtkMRMLScalarVolumeNode"):
            imageData = inputImage.GetImageData()
            if imageData:
                dims = imageData.GetDimensions()
                self.__centerXSpinBox.setValue(dims[0] // 2)
                self.__centerYSpinBox.setValue(dims[1] // 2)

    def onFunctionTypeChanged(self, text):
        is_spline = text == "Spline Radial"
        self.__polynomialOrderComboBox.setVisible(not is_spline)
        if hasattr(self, "parametersLayout"):
            label = self.parametersLayout.labelForField(self.__polynomialOrderComboBox)
            if label:
                label.setVisible(not is_spline)

    def onPickCenterClicked(self):
        if not self.centerFiducialNode:
            self.centerFiducialNode = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLMarkupsFiducialNode", "ShadingCenterBigImage"
            )
            displayNode = self.centerFiducialNode.GetDisplayNode()
            displayNode.SetSelectedColor(1, 0, 0)
            displayNode.RemoveAllViewNodeIDs()
            displayNode.AddViewNodeID("vtkMRMLSliceNodeRed")
            self.centerFiducialNode.SetHideFromEditors(True)

        self.centerFiducialNode.RemoveAllControlPoints()

        interactionNode = slicer.mrmlScene.GetNodeByID("vtkMRMLInteractionNodeSingleton")
        selectionNode = slicer.mrmlScene.GetNodeByID("vtkMRMLSelectionNodeSingleton")

        selectionNode.SetReferenceActivePlaceNodeClassName("vtkMRMLMarkupsFiducialNode")
        selectionNode.SetActivePlaceNodeID(self.centerFiducialNode.GetID())
        interactionNode.SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.Place)

        if self.pointAddedObserverTag is None:
            self.pointAddedObserverTag = self.centerFiducialNode.AddObserver(
                slicer.vtkMRMLMarkupsNode.PointPositionDefinedEvent, self.onCenterPointAdded
            )

    def onCenterPointAdded(self, caller, event):
        interactionNode = slicer.mrmlScene.GetNodeByID("vtkMRMLInteractionNodeSingleton")
        interactionNode.SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.ViewTransform)

        pos = [0.0, 0.0, 0.0]
        self.centerFiducialNode.GetNthControlPointPositionWorld(0, pos)

        volumeNode = self.__inputSelector.currentNode()
        if not volumeNode or not volumeNode.IsA("vtkMRMLScalarVolumeNode"):
            self.centerFiducialNode.RemoveAllControlPoints()
            return

        transform = vtk.vtkGeneralTransform()
        slicer.vtkMRMLTransformNode.GetTransformBetweenNodes(None, volumeNode.GetParentTransformNode(), transform)
        pos_volume = transform.TransformPoint(pos)

        ijkMatrix = vtk.vtkMatrix4x4()
        volumeNode.GetRASToIJKMatrix(ijkMatrix)

        ijk = [0, 0, 0, 1]
        ijkMatrix.MultiplyPoint(np.append(pos_volume, 1.0), ijk)

        i, j = int(round(ijk[0])), int(round(ijk[1]))

        self.__centerXSpinBox.setValue(i)
        self.__centerYSpinBox.setValue(j)

        self.centerFiducialNode.RemoveAllControlPoints()

    def exit(self):
        if self.centerFiducialNode:
            slicer.mrmlScene.RemoveNode(self.centerFiducialNode)
            self.centerFiducialNode = None
            self.pointAddedObserverTag = None

    def setParameters(self, **kwargs) -> None:
        params = PolynomialShadingCorrectionParameters(**kwargs)

        if params.inputNode:
            self.__inputSelector.setCurrentNode(params.inputNode)

        if params.inputShadingMaskNode:
            self.__inputShadingMaskSelector.setCurrentNode(params.inputShadingMaskNode)

        if params.sliceGroupSize:
            self.__sliceGroupSize.setValue(params.sliceGroupSize)

        if params.fittingPointsPercentage:
            self.__fittingPointsPercentage.setValue(params.fittingPointsPercentage)

        if params.functionType:
            self.__functionTypeComboBox.setCurrentText(params.functionType)

        if params.polynomialOrder:
            self.__polynomialOrderComboBox.setCurrentText(str(params.polynomialOrder))

        if params.useCustomCenter is not None:
            self.__useCustomCenterCheckBox.setChecked(params.useCustomCenter)

        if params.centerX is not None:
            self.__centerXSpinBox.setValue(params.centerX)

        if params.centerY is not None:
            self.__centerYSpinBox.setValue(params.centerY)

        if params.exportPath:
            self.__exportPathEdit.setCurrentPath(params.exportPath)

    def __onApplyButtonClicked(self, state: bool) -> None:
        if self.__inputSelector.currentNode() is None:
            slicer.util.errorDisplay("Please select a volume node as the input.", self.title)
            return

        if self.__inputShadingMaskSelector.currentNode() is None:
            slicer.util.errorDisplay("Please select a node as the input shading mask.", self.title)
            return

        if not self.__exportPathEdit.currentPath:
            slicer.util.errorDisplay("Please select an output path.", self.title)
            return

        data = {
            "inputNodeId": self.__inputSelector.currentNode().GetID(),
            "inputShadingMaskNodeId": self.__inputShadingMaskSelector.currentNode().GetID(),
            "sliceGroupSize": self.__sliceGroupSize.value,
            "fittingPointsPercentage": self.__fittingPointsPercentage.value,
            "functionType": self.__functionTypeComboBox.currentText,
            "polynomialOrder": int(self.__polynomialOrderComboBox.currentText),
            "useCustomCenter": self.__useCustomCenterCheckBox.isChecked(),
            "centerX": self.__centerXSpinBox.value,
            "centerY": self.__centerYSpinBox.value,
            "exportPath": self.__exportPathEdit.currentPath,
            "geoslicerVersion": getApplicationVersion(),
            "nullValue": 0,
        }

        self.logic = PolynomialShadingCorrectionBigImageLogic(parent=self.parent)
        self.logic.signalProcessRuntimeError.connect(self.onProcessError)
        self.logic.signalProcessSucceed.connect(self.onProcessSucceed)
        self.logic.signalProcessCancelled.connect(self.onProcessCancelled)

        try:
            self.logic.apply(data=data, progressBar=self.__cliProgressBar)
        except Exception as error:
            self.onProcessError(error)

        self.__updateButtonsEnablement(running=True)

        helpers.save_path(self.__exportPathEdit)
        PolynomialShadingCorrection.set_setting(SLICE_GROUP_SIZE, self.__sliceGroupSize.value)
        PolynomialShadingCorrection.set_setting(FITTING_POINTS_PERCENTAGE, self.__fittingPointsPercentage.value)
        PolynomialShadingCorrection.set_setting(FUNCTION_TYPE, self.__functionTypeComboBox.currentText)
        PolynomialShadingCorrection.set_setting(POLYNOMIAL_ORDER, self.__polynomialOrderComboBox.currentText)

    def __updateButtonsEnablement(self, running: bool) -> None:
        self.__cancelButton.setEnabled(running)
        self.__applyButton.setEnabled(not running)

    def __onCancelButtonClicked(self) -> None:
        if not self.logic:
            return

        self.logic.cancel()

    def onProcessError(self, error: str) -> None:
        logging.error(f"{error}.\n{traceback.format_exc()}")
        slicer.util.errorDisplay(
            "An error was found during the process. Please, check the application logs for more details.", self.title
        )
        self.__updateButtonsEnablement(running=False)

    def onProcessSucceed(self, nodeName: str) -> None:
        slicer.util.infoDisplay(f"Process finished successfully.\nPlease check the node '{nodeName}'.", self.title)
        self.__updateButtonsEnablement(running=False)

    def onProcessCancelled(self) -> None:
        logging.debug(f"Process cancelled by the user.")
        self.__updateButtonsEnablement(running=False)


class PolynomialShadingCorrectionBigImageLogic(LTracePluginLogic):

    signalProcessRuntimeError = qt.Signal(str)
    signalProcessSucceed = qt.Signal(str)
    signalProcessCancelled = qt.Signal()

    def __init__(self, parent) -> None:
        LTracePluginLogic.__init__(self, parent)
        self._cliNode = None
        self.__cliNodeModifiedObserver = None

    def _getLazyData(self, node: slicer.vtkMRMLNode) -> None:
        if lazy.is_lazy_node(node):
            return lazy.data(node)

        path = Path(slicer.app.temporaryPath).absolute() / f"{node.GetName().lower()}.nc"
        path = sanitize_filepath(file_path=path, platform="auto")
        netcdf.exportNetcdf(path, [node])

        assert path.exists(), f"Failed to export node {node.GetName()} as NetCDF"

        return lazy.LazyNodeData(url=f"file://{path.as_posix()}", var=f"{node.GetName()}")

    def _removeProxyNodeFile(self, node: slicer.vtkMRMLNode, url: str) -> None:
        if lazy.is_lazy_node(node):
            return

        proxyFilePath = Path(url)
        if not proxyFilePath.exists():
            return

        logging.debug(f"Deleting file: {proxyFilePath.as_posix()}")
        proxyFilePath.unlink()

    def apply(self, data: dict, progressBar: LocalProgressBar = None) -> None:
        inputNode = helpers.tryGetNode(data["inputNodeId"])
        inputShadingMaskNode = helpers.tryGetNode(data["inputShadingMaskNodeId"])

        if not inputNode:
            raise ValueError("The node selected as input is invalid.")

        if not inputShadingMaskNode:
            raise ValueError("The node selected as input shading mask is invalid.")

        inputLazyData = self._getLazyData(inputNode)
        inputShadingMaskLazyData = self._getLazyData(inputShadingMaskNode)

        inputLazyNodeProtocol = inputLazyData.get_protocol()
        inputLazyNodeHost = inputLazyNodeProtocol.host()
        inputShadingMaskLazyNodeProtocol = inputShadingMaskLazyData.get_protocol()
        inputShadingMaskLazyNodeHost = inputShadingMaskLazyNodeProtocol.host()

        data = {
            **data,
            "inputLazyNodeUrl": inputLazyData.url,
            "inputLazyNodeVar": inputLazyData.var,
            "inputShadingMaskLazyNodeUrl": inputShadingMaskLazyData.url,
            "inputShadingMaskLazyNodeVar": inputShadingMaskLazyData.var,
            "inputLazyNodeHost": inputLazyNodeHost.to_dict(),
            "inputShadingMaskLazyNodeHost": inputShadingMaskLazyNodeHost.to_dict(),
        }

        cliConfig = {
            "params": json.dumps(data),
        }

        if progressBar is not None:
            progressBar.visible = True

        self._cliNode = slicer.cli.run(
            slicer.modules.polynomialshadingcorrectionbigimagecli,
            None,
            cliConfig,
            wait_for_completion=False,
        )
        self.__cliNodeModifiedObserver = self._cliNode.AddObserver(
            "ModifiedEvent", lambda c, ev, info=cliConfig: self.__onCliModifiedEvent(c, ev, info)
        )

        if progressBar is not None:
            progressBar.setCommandLineModuleNode(self._cliNode)

    def __onCliModifiedEvent(self, caller, event, info) -> None:
        if self._cliNode is None:
            return

        if caller is None:
            del self._cliNode
            self._cliNode = None
            return

        if caller.IsBusy():
            return

        params = json.loads(info["params"])
        if caller.GetStatusString() == "Completed":
            lazyNodeData = lazy.LazyNodeData(
                url="file://" + params["exportPath"], var=params["inputLazyNodeVar"] + "_filtered"
            )
            lazyNodeData.to_node()
            self.signalProcessSucceed.emit(lazyNodeData.var)
        elif caller.GetStatusString() != "Cancelled":
            self.signalProcessRuntimeError.emit(caller.GetErrorText())
        else:  # Cancelled
            self.signalProcessCancelled.emit()

        inputNode = helpers.tryGetNode(params["inputNodeId"])
        inputShadingMaskNode = helpers.tryGetNode(params["inputShadingMaskNodeId"])
        self._removeProxyNodeFile(inputNode, params["inputLazyNodeUrl"])
        self._removeProxyNodeFile(inputShadingMaskNode, params["inputShadingMaskLazyNodeUrl"])

        if self.__cliNodeModifiedObserver is not None:
            self._cliNode.RemoveObserver(self.__cliNodeModifiedObserver)
            self.__cliNodeModifiedObserver = None

        del self._cliNode
        self._cliNode = None

    def cancel(self) -> None:
        if not self._cliNode:
            return

        self._cliNode.Cancel()
