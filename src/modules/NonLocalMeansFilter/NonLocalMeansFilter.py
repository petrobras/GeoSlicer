import logging
import os
from pathlib import Path

import ctk
import qt
import slicer

from commons.algorithms.non_local_means import (
    DEFAULT_PATCH_DISTANCE,
    DEFAULT_PATCH_SIZE,
    DEFAULT_STRENGTH,
    MODE_2D,
    MODE_3D,
    rgb_to_greyscale,
)
from commons.slicer import ui
from commons.slicer.helpers import (
    copy_display,
    copy_subject_hierarchy_item_parent,
    createTemporaryVolumeNode,
    getVolumeNullValue,
    highlight_error,
    makeTemporaryNodePermanent,
    setVolumeNullValue,
    tryGetNode,
)
from commons.slicer.node_attributes import NodeEnvironment
from commons.slicer.widget.global_progress_bar import LocalProgressBar
from commons.slicer_utils import LTracePlugin, LTracePluginLogic, LTracePluginWidget, arrayFromVolumeWithChannels

try:
    from Test.NonLocalMeansFilterTest import NonLocalMeansFilterTest
except ImportError:
    NonLocalMeansFilterTest = None  # tests not deployed to final version or closed source

# Number of channels of RGB and RGBA images, which are converted to greyscale before filtering
RGB_CHANNELS = (3, 4)


def getNumberOfChannels(volumeNode):
    imageData = volumeNode.GetImageData() if volumeNode is not None else None
    return imageData.GetNumberOfScalarComponents() if imageData is not None else 0


class NonLocalMeansFilter(LTracePlugin):
    SETTING_KEY = "NonLocalMeansFilter"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Non-Local Means Filter"
        self.parent.categories = ["Tools", "MicroCT", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = "Denoises a volume with the non-local means filter, in full 3D or slice by slice."
        self.setHelpUrl("Volumes/Filter/Filter.html#non-local-means-filter", NodeEnvironment.MICRO_CT)
        self.setHelpUrl(
            "Multiscale/VolumesPreProcessing/VolumesPreProcessing.html#filtering-tools", NodeEnvironment.MULTISCALE
        )

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class NonLocalMeansFilterWidget(LTracePluginWidget):
    OUTPUT_SUFFIX = "_NLM"

    def setup(self):
        LTracePluginWidget.setup(self)

        self.progressBar = LocalProgressBar()
        self.logic = NonLocalMeansFilterLogic(self, self.progressBar)

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

        self.inputImageComboBox = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLScalarVolumeNode"], onChange=self.onInputNodeChanged
        )
        self.inputImageComboBox.setToolTip("Select the image to be filtered.")
        self.inputImageComboBox.objectName = "Input Image ComboBox"
        inputFormLayout.addRow("Input image:", self.inputImageComboBox)
        inputFormLayout.addRow(" ", None)

        # Parameters section
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.setText("Parameters")
        formLayout.addRow(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.modeComboBox = qt.QComboBox()
        self.modeComboBox.addItem("3D", MODE_3D)
        self.modeComboBox.addItem("2D (slice by slice)", MODE_2D)
        self.modeComboBox.setToolTip(
            "3D compares patches across the whole volume. 2D filters each axial slice independently, which is "
            "faster but does not use the information of neighboring slices."
        )
        self.modeComboBox.objectName = "Mode ComboBox"
        self.modeComboBox.currentIndexChanged.connect(self.onModeChanged)
        parametersFormLayout.addRow("Mode:", self.modeComboBox)

        self.strengthSpinBox = ui.numberParam(vrange=(0.01, 5), value=DEFAULT_STRENGTH[MODE_3D], step=0.05, decimals=2)
        self.strengthSpinBox.setToolTip(
            "Filter strength h as a multiple of the noise standard deviation. Higher values smooth more, at the cost "
            "of fine details. Recommended values are about 0.45-0.6 for 3D and 0.6-0.8 for 2D."
        )
        self.strengthSpinBox.objectName = "Strength SpinBox"
        parametersFormLayout.addRow("Strength (× noise std):", self.strengthSpinBox)

        self.estimateSigmaCheckBox = qt.QCheckBox("Estimate")
        self.estimateSigmaCheckBox.setChecked(True)
        self.estimateSigmaCheckBox.setToolTip("Estimate the noise standard deviation from the image.")
        self.estimateSigmaCheckBox.objectName = "Estimate Sigma CheckBox"
        self.estimateSigmaCheckBox.toggled.connect(self.onEstimateSigmaToggled)
        self.sigmaSpinBox = ui.numberParam(vrange=(0, 1e9), value=0, step=1, decimals=3)
        self.sigmaSpinBox.setToolTip("Standard deviation of the image noise, in intensity units.")
        self.sigmaSpinBox.objectName = "Sigma SpinBox"
        self.sigmaSpinBox.setEnabled(False)
        sigmaLayout = qt.QHBoxLayout()
        sigmaLayout.addWidget(self.sigmaSpinBox)
        sigmaLayout.addWidget(self.estimateSigmaCheckBox)
        parametersFormLayout.addRow("Noise std:", sigmaLayout)

        self.patchSizeSpinBox = ui.numberParamInt(vrange=(1, 21), value=DEFAULT_PATCH_SIZE)
        self.patchSizeSpinBox.setToolTip(
            "Side, in voxels, of the patches compared to find similar regions. Larger patches are more robust to "
            "noise but slower and may blur small features."
        )
        self.patchSizeSpinBox.objectName = "Patch Size SpinBox"
        parametersFormLayout.addRow("Patch size (voxels):", self.patchSizeSpinBox)

        self.patchDistanceSpinBox = ui.numberParamInt(vrange=(1, 30), value=DEFAULT_PATCH_DISTANCE)
        self.patchDistanceSpinBox.setToolTip(
            "Maximal distance, in voxels, to search for similar patches. Processing time grows quickly with this "
            "value, especially in 3D."
        )
        self.patchDistanceSpinBox.objectName = "Patch Distance SpinBox"
        parametersFormLayout.addRow("Search distance (voxels):", self.patchDistanceSpinBox)

        self.fastModeCheckBox = qt.QCheckBox()
        self.fastModeCheckBox.setChecked(True)
        self.fastModeCheckBox.objectName = "Fast Mode CheckBox"
        parametersFormLayout.addRow("Fast mode:", self.fastModeCheckBox)
        parametersFormLayout.addRow(" ", None)
        self.updateFastModeCheckBox()

        # Output section
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.outputVolumeNameLineEdit = qt.QLineEdit()
        self.outputVolumeNameLineEdit.objectName = "Output Volume Name LineEdit"
        outputFormLayout.addRow("Output image name:", self.outputVolumeNameLineEdit)
        outputFormLayout.addRow(" ", None)

        self.rgbWarningLabel = qt.QLabel(
            "The input image has color channels. It will be converted to single-channel greyscale before "
            "filtering, so the output will be a greyscale image."
        )
        self.rgbWarningLabel.setStyleSheet("QLabel { color : yellow; }")
        self.rgbWarningLabel.setWordWrap(True)
        self.rgbWarningLabel.objectName = "RGB Warning Label"
        self.rgbWarningLabel.hide()
        formLayout.addRow(self.rgbWarningLabel)

        self.buttons = ui.ApplyCancelButtons(
            onApplyClick=self.onApplyButtonClicked,
            onCancelClick=self.onCancelButtonClicked,
            applyTooltip="Apply the filter",
            cancelTooltip="Cancel the filtering",
        )
        formLayout.addRow(self.buttons)

        self.usedParametersLabel = qt.QLabel()
        self.usedParametersLabel.objectName = "Used Parameters Label"
        self.usedParametersLabel.setVisible(False)
        formLayout.addRow(self.usedParametersLabel)

        self.layout.addStretch()
        self.layout.addWidget(self.progressBar)

    def onModeChanged(self, index):
        mode = self.modeComboBox.itemData(index)
        previousMode = MODE_3D if mode == MODE_2D else MODE_2D
        # Only replace the strength if the user did not customize it
        if abs(self.strengthSpinBox.value - DEFAULT_STRENGTH[previousMode]) < 1e-6:
            self.strengthSpinBox.value = DEFAULT_STRENGTH[mode]
        self.updateFastModeCheckBox()

    def updateFastModeCheckBox(self):
        # 3D always uses the fast patch distance, as the Gaussian-weighted one is too slow for volumes
        is3d = self.modeComboBox.itemData(self.modeComboBox.currentIndex) == MODE_3D
        self.fastModeCheckBox.setEnabled(not is3d)
        if is3d:
            self.fastModeCheckBox.setToolTip("3D mode always uses the fast patch distance.")
        else:
            self.fastModeCheckBox.setToolTip(
                "Use a faster patch distance with uniform weights. When unchecked, patch distances are weighted by a "
                "Gaussian, which is slightly more accurate but much slower."
            )

    def onEstimateSigmaToggled(self, checked):
        self.sigmaSpinBox.setEnabled(not checked)

    def onInputNodeChanged(self, itemId):
        inputNode = self.inputImageComboBox.currentNode()
        self.outputVolumeNameLineEdit.setText(inputNode.GetName() + self.OUTPUT_SUFFIX if inputNode else "")
        self.rgbWarningLabel.setVisible(getNumberOfChannels(inputNode) in RGB_CHANNELS)

    def getFilterParameters(self):
        return dict(
            mode=self.modeComboBox.itemData(self.modeComboBox.currentIndex),
            strength=self.strengthSpinBox.value,
            sigma=0 if self.estimateSigmaCheckBox.isChecked() else self.sigmaSpinBox.value,
            patchSize=self.patchSizeSpinBox.value,
            patchDistance=self.patchDistanceSpinBox.value,
            fastMode=self.fastModeCheckBox.isChecked(),
        )

    def onApplyButtonClicked(self):
        inputNode = self.inputImageComboBox.currentNode()
        if inputNode is None:
            highlight_error(self.inputImageComboBox)
            slicer.util.errorDisplay("Please select an input image.")
            return

        channels = getNumberOfChannels(inputNode)
        if channels != 1 and channels not in RGB_CHANNELS:
            highlight_error(self.inputImageComboBox)
            slicer.util.errorDisplay(
                f"The input image has {channels} channels. Only greyscale and RGB images are supported."
            )
            return

        outputName = self.outputVolumeNameLineEdit.text.strip()
        if not outputName:
            highlight_error(self.outputVolumeNameLineEdit)
            slicer.util.errorDisplay("Please type an output image name.")
            return

        parameters = self.getFilterParameters()
        if not self.estimateSigmaCheckBox.isChecked() and parameters["sigma"] <= 0:
            highlight_error(self.sigmaSpinBox)
            slicer.util.errorDisplay("Noise standard deviation must be greater than zero.")
            return

        self.usedParametersLabel.setVisible(False)
        self.buttons.applyBtn.setEnabled(False)
        try:
            self.logic.apply(inputNode=inputNode, outputName=outputName, **parameters)
        except Exception:
            self.onFilteringFinished()
            raise

    def onCancelButtonClicked(self):
        self.logic.cancel()

    def onFilteringFinished(self, usedSigma=None, usedH=None):
        self.buttons.applyBtn.setEnabled(True)
        if usedSigma is not None:
            self.usedParametersLabel.setText(f"Last run: noise std = {usedSigma:.4g}, h = {usedH:.4g}")
            self.usedParametersLabel.setVisible(True)


class NonLocalMeansFilterLogic(LTracePluginLogic):
    def __init__(self, widget, progressBar):
        LTracePluginLogic.__init__(self)
        self.widget = widget
        self.progressBar = progressBar
        self.cliNode = None
        self.inputNodeId = None
        self.outputNodeId = None
        self.greyscaleNodeId = None

    def apply(self, inputNode, outputName, mode, strength, sigma, patchSize, patchDistance, fastMode):
        if self.cliNode is not None:
            slicer.mrmlScene.RemoveNode(self.cliNode)

        cliInputNode = inputNode
        if getNumberOfChannels(inputNode) in RGB_CHANNELS:
            cliInputNode = self.createGreyscaleNode(inputNode)
            self.greyscaleNodeId = cliInputNode.GetID()

        outputNode = createTemporaryVolumeNode(slicer.vtkMRMLScalarVolumeNode, name=outputName)
        copy_subject_hierarchy_item_parent(inputNode, outputNode)
        self.inputNodeId = inputNode.GetID()
        self.outputNodeId = outputNode.GetID()

        nullValue = getVolumeNullValue(inputNode)
        cliParams = {
            "inputVolume": cliInputNode.GetID(),
            "outputVolume": outputNode.GetID(),
            "mode": mode,
            "strength": strength,
            "sigma": sigma,
            "patchSize": patchSize,
            "patchDistance": patchDistance,
            "fastMode": fastMode,
            "nullValue": "" if nullValue is None else str(nullValue),
        }

        try:
            self.cliNode = slicer.cli.run(
                slicer.modules.nonlocalmeansfiltercli, None, cliParams, wait_for_completion=False
            )
        except Exception:
            slicer.mrmlScene.RemoveNode(outputNode)
            self.removeGreyscaleNode()
            raise
        self.progressBar.setCommandLineModuleNode(self.cliNode)
        self.cliNode.AddObserver("ModifiedEvent", self.onCliModified)

    @staticmethod
    def createGreyscaleNode(inputNode):
        """Creates a hidden single-channel copy of an RGB(A) volume, with the same data type and geometry."""
        slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            rgb = arrayFromVolumeWithChannels(inputNode)
            greyscaleNode = createTemporaryVolumeNode(
                slicer.vtkMRMLScalarVolumeNode, name=f"{inputNode.GetName()}_greyscale"
            )
            slicer.util.updateVolumeFromArray(greyscaleNode, rgb_to_greyscale(rgb, dtype=rgb.dtype))
            greyscaleNode.CopyOrientation(inputNode)
            return greyscaleNode
        finally:
            slicer.app.restoreOverrideCursor()

    def removeGreyscaleNode(self):
        greyscaleNode = tryGetNode(self.greyscaleNodeId)
        if greyscaleNode is not None:
            slicer.mrmlScene.RemoveNode(greyscaleNode)
        self.greyscaleNodeId = None

    def onCliModified(self, caller, event):
        if caller.IsBusy():
            return

        status = caller.GetStatusString()
        caller.RemoveAllObservers()
        self.cliNode = None
        self.removeGreyscaleNode()

        inputNode = tryGetNode(self.inputNodeId)
        outputNode = tryGetNode(self.outputNodeId)

        if status != "Completed":
            slicer.mrmlScene.RemoveNode(outputNode)
            if status != "Cancelled":
                logging.error(caller.GetErrorText())
                slicer.util.errorDisplay("Non-local means filtering failed.")
            self.widget.onFilteringFinished()
            return

        # The display of a color image does not apply to the greyscale output
        if getNumberOfChannels(inputNode) == 1:
            copy_display(inputNode, outputNode)
        nullValue = getVolumeNullValue(inputNode)
        if nullValue is not None:
            setVolumeNullValue(outputNode, nullValue)
        makeTemporaryNodePermanent(outputNode, show=True)
        slicer.util.setSliceViewerLayers(background=outputNode, fit=True)

        usedSigma = float(caller.GetParameterAsString("usedSigma"))
        usedH = float(caller.GetParameterAsString("usedH"))
        logging.info(f"Non-local means filter applied with noise std = {usedSigma}, h = {usedH}.")
        self.widget.onFilteringFinished(usedSigma, usedH)

    def cancel(self):
        if self.cliNode is not None:
            self.cliNode.Cancel()
