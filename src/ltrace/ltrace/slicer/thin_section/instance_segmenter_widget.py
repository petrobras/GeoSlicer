from ltrace.slicer.helpers import (
    arrayFromSegmentBinaryLabelmap,
    clearPattern,
    get_scripted_modules_path,
    validateSourceVolume,
)
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.slicer.widget.trained_model_selector import TrainedModelSelector
from ltrace.slicer import ui, widgets
import numpy as np

import qt
import ctk
import slicer

from .instance_segmenter_logic import ThinSectionInstanceSegmenterLogic
from ltrace.slicer.app import MANUAL_BASE_URL


class ThinSectionInstanceSegmenterWidget(qt.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.logic: ThinSectionInstanceSegmenterLogic = None
        self.refNode = None
        self.cliNode = None
        self.layoutWidgets = []

        # based on the original training
        self.default = {
            "chunk size label": "Chunk size (px):",
            "chunk size": 2048,
            "spacing": 0.00132,
            "chunk overlap": 50,
            "confidence threshold": 70,
            "NMS threshold": 10,
            "resize ratio": 0.5,
        }

    def setup(self):
        self.layoutWidgets.append(self._setupDetectorSection())
        self.layoutWidgets.append(self._setupInputsSection())
        self.layoutWidgets.append(self._setupSettingsSection())
        self.layoutWidgets.append(self._setupAdvancedSection())
        self.layoutWidgets.append(self._setupLocalRemoteSection())
        self.layoutWidgets.append(self._setupOutputSection())
        self.layoutWidgets.append(self._setupApplySection())

    def _setupLocalRemoteSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Resources"

        self.localRadioButton = qt.QRadioButton("Local")
        self.localRadioButton.setToolTip("Select to run inference with local resources")
        self.localRadioButton.objectName = "Local Resources RadioButton"
        self.remoteRadioButton = qt.QRadioButton("Remote")
        self.remoteRadioButton.setToolTip("Select to run inference with remote resources")
        self.remoteRadioButton.objectName = "Remote Resources RadioButton"

        hbox = qt.QHBoxLayout(widget)
        hbox.addWidget(self.localRadioButton)
        hbox.addWidget(self.remoteRadioButton)

        self.localRadioButton.setChecked(True)

        return widget

    def _setupDetectorSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Detector"
        layout = qt.QVBoxLayout(widget)

        scripted_modules_path = get_scripted_modules_path()

        self.classifierInput = TrainedModelSelector(["TexturalStructures"])
        self.classifierInput.objectName = "Thin Section Instance Segmenter Model ComboBox"

        classifierInputHelpButton = HelpButton(
            f"### Instance Segmentation Inference\n\n The frameworks provided here can support different types of models. Select one of then from the list.\n\n-----\n More information available at [Geoslicer Manual]({MANUAL_BASE_URL}ThinSection/Segmentation/ThinSectionSegmenter.html)"
        )

        hbox = qt.QHBoxLayout(widget)
        hbox.addWidget(self.classifierInput)
        hbox.addWidget(classifierInputHelpButton)
        layout.addLayout(hbox)

        self.classifierInfo = qt.QLabel()
        self.classifierInfo.setTextFormat(qt.Qt.RichText)
        self.classifierInfo.setOpenExternalLinks(True)
        self.classifierInfo.setTextInteractionFlags(qt.Qt.TextBrowserInteraction)
        self.classifierInfo.setWordWrap(True)
        self.classifierInfoGroupBox = ctk.ctkCollapsibleGroupBox()
        self.classifierInfoGroupBox.setLayout(qt.QVBoxLayout())
        self.classifierInfoGroupBox.layout().addWidget(self.classifierInfo)
        self.classifierInfoGroupBox.collapsed = True
        layout.addWidget(self.classifierInfoGroupBox)

        return widget

    def _setupInputsSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Inputs"
        layout = qt.QVBoxLayout(widget)

        self.inputsSelector = widgets.SingleShotInputWidget(
            rowTitles={"reference": "PX"},
            checkable=False,
            setDefaultMargins=False,
        )
        self.inputsSelector.setParent(widget)
        self.inputsSelector.onReferenceSelectedSignal.connect(self._onReferenceSelected)
        self.inputsSelector.onSoiSelectedSignal.connect(self._updateRecommendedSettingsButton)
        self.inputsSelector.segmentationLabel.visible = False
        self.inputsSelector.mainInput.visible = False
        self.inputsSelector.segmentsContainerWidget.visible = False
        self.inputsSelector.mainInput.setCurrentNode(None)
        self.inputsSelector.soiInput.enabled = True
        self.inputsSelector.soiInput.objectName = "Thin Section Instance Segmenter SOI ComboBox"
        self.inputsSelector.referenceInput.enabled = True
        self.inputsSelector.referenceInput.objectName = "Thin Section Instance Segmenter Input Volume ComboBox"
        self.inputsSelector.referenceInput.selectorWidget.setNodeTypes(["vtkMRMLVectorVolumeNode"])

        self.pxInputCombobox = self.inputsSelector.referenceInput

        layout.addWidget(self.inputsSelector)

        return widget

    def _setupSettingsSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Parameters"
        layout = qt.QFormLayout(widget)

        self.chunkedInferenceCheckbox = qt.QCheckBox("")
        self.chunkedInferenceCheckbox.objectName = "Chunked Inference CheckBox"
        self.chunkedInferenceCheckbox.setChecked(True)
        self.chunkedInferenceCheckbox.setToolTip(
            "If selected, the inference is performed on overlapping chunks of the input volume. It tends to be slower, but to provide more accurate results.\nIf not selected, the inference is performed on the entire image at once. It tends to be faster, but to struggle finding instances in high resolution images."
        )
        self.chunkedInferenceCheckbox.connect("toggled(bool)", self._onChunkedInferenceCheckboxClicked)

        self.chunkSizeSpinBox = qt.QSpinBox()
        self.chunkSizeSpinBox.setRange(1, 99999)
        self.chunkSizeSpinBox.setValue(self.default["chunk size"])
        self.chunkSizeSpinBox.setToolTip(
            "Size of the chunks on which inference is performed. Small values may take longer to process."
        )
        self.chunkSizeSpinBox.objectName = "Chunk Size SpinBox"
        self.chunkSizeSpinBox.valueChanged.connect(self._onChunkSizeChanged)

        self.chunkSizeLabel = qt.QLabel(self.default["chunk size label"])

        self.chunkSizeMmLabel = qt.QLabel("  0 mm")
        self.chunkSizeMmLabel.visible = False

        self.recommendedSettingsButton = qt.QPushButton("Set to recommended settings")
        self.recommendedSettingsButton.objectName = "Recommended Settings Button"
        self.recommendedSettingsButton.setToolTip(
            "Determine if chunking should be used and the recommended chunk size based on the size and scale of the region of interest."
        )
        self.recommendedSettingsButton.connect("clicked()", self._onRecommendedSettingsButtonClicked)
        self.recommendedSettingsButton.enabled = False

        hbox = qt.QHBoxLayout()
        hbox.setAlignment(qt.Qt.AlignLeft)
        hbox.addWidget(self.chunkedInferenceCheckbox)
        hbox.addWidget(self.chunkSizeLabel)
        hbox.addWidget(self.chunkSizeSpinBox)
        hbox.addWidget(self.chunkSizeMmLabel)

        layout.addRow(self.recommendedSettingsButton)
        layout.addRow(hbox)

        return widget

    def _setupAdvancedSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Advanced"
        widget.flat = True
        widget.collapsed = True

        layout = qt.QFormLayout(widget)

        self.overlapSpinbox = qt.QSpinBox()
        self.overlapSpinbox.objectName = "Chunk Overlap SpinBox"
        self.overlapSpinbox.setRange(0, 99)
        self.overlapSpinbox.setValue(self.default["chunk overlap"])
        self.overlapSpinbox.setToolTip(
            "Overlap between chunks. Larger values prevents cutting predicted instances, but take longer to process."
        )
        self.overlapSpinbox.valueChanged.connect(self._updateRecommendedSettingsButton)
        self.overlapLabel = qt.QLabel("Chunk overlap (%):")

        self.confSpinbox = qt.QSpinBox()
        self.confSpinbox.objectName = "Confidence Threshold SpinBox"
        self.confSpinbox.setRange(0, 100)
        self.confSpinbox.setValue(self.default["confidence threshold"])
        self.confSpinbox.setToolTip(
            "Confidence threshold used to filter results. Larger values ​​provide better quality results, small values ​​provide more predictions."
        )
        self.confSpinbox.valueChanged.connect(self._updateRecommendedSettingsButton)

        self.nmsSpinbox = qt.QSpinBox()
        self.nmsSpinbox.objectName = "NMS Threshold SpinBox"
        self.nmsSpinbox.setRange(0, 100)
        self.nmsSpinbox.setValue(self.default["NMS threshold"])
        self.nmsSpinbox.setToolTip(
            "Non-maximum suppression limit: remove boxes with intersection over union ratio greater than this value. Larger values ​​give closer results, small values ​​give sparser results."
        )
        self.nmsSpinbox.valueChanged.connect(self._updateRecommendedSettingsButton)

        self.resizeSpinbox = qt.QDoubleSpinBox()
        self.resizeSpinbox.objectName = "Resize SpinBox"
        self.resizeSpinbox.setRange(0, 1)
        self.resizeSpinbox.setValue(self.default["resize ratio"])
        self.resizeSpinbox.setSingleStep(0.05)
        self.resizeSpinbox.setToolTip(
            "Scale used to resize the image before inference. Larger values may take longer to process."
        )
        self.resizeSpinbox.valueChanged.connect(self._updateRecommendedSettingsButton)

        layout.addRow(self.overlapLabel, self.overlapSpinbox)
        layout.addRow("Confidence threshold (%):", self.confSpinbox)
        layout.addRow("NMS threshold (%):", self.nmsSpinbox)
        layout.addRow("Resize ratio:", self.resizeSpinbox)

        return widget

    def _setupOutputSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Output"

        self.calculateStatisticsCheckbox = qt.QCheckBox("Calculate statistics on segments")
        self.calculateStatisticsCheckbox.objectName = "Statistics CheckBox"
        self.calculateStatisticsCheckbox.setChecked(True)
        self.calculateStatisticsCheckbox.setToolTip(
            "Calculate geometric properties of each instance (Required for use in the instance editor)."
        )

        self.outputPrefix = qt.QLineEdit()
        self.outputPrefix.objectName = "Thin Section Instance Segmenter Output Prefix Line Edit"

        formLayout = qt.QFormLayout(widget)
        formLayout.addRow(self.calculateStatisticsCheckbox)
        formLayout.addRow("Output Prefix: ", self.outputPrefix)

        return widget

    def _setupApplySection(self):
        widget = qt.QWidget()
        vlayout = qt.QVBoxLayout(widget)

        self.applyCancelButtons = ui.ApplyCancelButtons(
            onApplyClick=self._onApplyClicked,
            onCancelClick=self._onCancel,
            applyTooltip="Run segmenter on input data limited by ROI",
            cancelTooltip="Cancel",
            applyText="Apply",
            cancelText="Cancel",
            enabled=False,
            applyObjectName="Thin Section Instance Segmenter Apply Button",
            cancelObjectName=None,
        )

        self.progressBar = LocalProgressBar()

        hlayout = qt.QHBoxLayout()
        hlayout.addWidget(self.applyCancelButtons)
        hlayout.setContentsMargins(0, 8, 0, 8)

        vlayout.addLayout(hlayout)
        vlayout.addWidget(self.progressBar)

        return widget

    def _updateChunkSizeMmLabelVisibility(self):
        self.chunkSizeMmLabel.visible = (self.refNode is not None) and self.chunkedInferenceCheckbox.checked

    def _updateRecommendedSettingsButton(self):
        self.recommendedSettingsButton.enabled = self.refNode is not None

    def _setRecommendedChunking(self):
        spacing = self.refNode.GetSpacing()[0]
        if spacing == 0:
            self.chunkSizeSpinBox.setValue(self.default["chunk size"])
            return

        soiNode = self.inputsSelector.soiInput.currentNode()

        refDims = self.refNode.GetImageData().GetDimensions()[:-1]
        refMinDim = min(refDims)
        refMaxDim = max(refDims)
        soiMinDim = refMinDim
        soiMaxDim = refMaxDim

        if soiNode:
            soiMask = arrayFromSegmentBinaryLabelmap(
                segmentationNode=soiNode,
                segmentId=soiNode.GetSegmentation().GetNthSegmentID(0),
                referenceVolumeNode=self.refNode,
            )
            maskDims = [coords.max() - coords.min() + 1 for coords in np.where(soiMask)[1:]]
            soiMinDim = min(maskDims)
            soiMaxDim = max(maskDims)

        recommendedChunkSize = round(self.default["chunk size"] * self.default["spacing"] / spacing)
        maxChunkSize = min(refMinDim, soiMinDim)
        roiMaxDim = min(refMaxDim, soiMaxDim)

        if recommendedChunkSize >= roiMaxDim:  # recommended chunk size > the whole ROI itself
            recommendedChunkSize = maxChunkSize
            self.chunkedInferenceCheckbox.checked = False
        else:
            if recommendedChunkSize > maxChunkSize:  # recommended chunk size > only one ROI's dimension
                recommendedChunkSize = maxChunkSize
            self.chunkedInferenceCheckbox.checked = True

        self.chunkSizeSpinBox.setValue(recommendedChunkSize)
        self.overlapSpinbox.setValue(self.default["chunk overlap"])

    def _onRecommendedSettingsButtonClicked(self):
        self._setRecommendedChunking()
        self.confSpinbox.setValue(self.default["confidence threshold"])
        self.nmsSpinbox.setValue(self.default["NMS threshold"])
        self.resizeSpinbox.setValue(self.default["resize ratio"])

        self.recommendedSettingsButton.enabled = False

    def _onChunkedInferenceCheckboxClicked(self):
        self._updateRecommendedSettingsButton()

        checked = self.chunkedInferenceCheckbox.isChecked()

        self.chunkSizeSpinBox.visible = checked
        self.chunkSizeLabel.enabled = checked
        self._updateChunkSizeMmLabelVisibility()
        self.overlapSpinbox.enabled = checked
        self.overlapLabel.enabled = checked

        self.chunkSizeLabel.text = self.default["chunk size label"]
        if not checked:
            self.chunkSizeLabel.text = self.chunkSizeLabel.text[:-1]

    def _onReferenceSelected(self, node):
        self.refNode = node
        self._updateChunkSizeMmLabelVisibility()

        self._onChunkSizeChanged(self.chunkSizeSpinBox.value)

        self._checkRequirementsForApply()

        if self.refNode:
            self.outputPrefix.setText(self.refNode.GetName())

    def _pxToMm(self, valuePx):
        if self.refNode is None:
            spacingMmPerPixel = 0
        else:
            spacingMmPerPixel = self.refNode.GetSpacing()[0]
        return round(valuePx * spacingMmPerPixel, 4)

    def _onChunkSizeChanged(self, valuePx):
        self._updateRecommendedSettingsButton()
        self.chunkSizeMmLabel.setText(f"  {self._pxToMm(valuePx)} mm")

    def _checkRequirementsForApply(self):
        if self.cliNode is None or not self.cliNode.IsBusy():
            self.applyCancelButtons.setEnabled(self.refNode is not None)

    def _onCancel(self):
        if self.cliNode is None:
            return
        self.cliNode.Cancel()
        self.resetUI()

    def _onApplyClicked(self):
        if self.outputPrefix.text.strip() == "":
            slicer.util.errorDisplay("Please type an output prefix.")
            return

        if self.inputsSelector.referenceInput.currentNode() is None:
            slicer.util.errorDisplay("Please select an input node.")
            return

        if not validateSourceVolume(
            None,
            self.inputsSelector.soiInput.currentNode(),
            self.inputsSelector.referenceInput.currentNode(),
        ):
            return

        self.applyCancelButtons.applyBtn.setEnabled(False)
        self.applyCancelButtons.cancelBtn.setEnabled(True)

        prefix = self.outputPrefix.text + "_{type}"

        try:
            model_dir = self.classifierInput.getSelectedModelPath()
            refNode = self.inputsSelector.referenceInput.currentNode()
            soiNode = self.inputsSelector.soiInput.currentNode()

            do_chunking = self.chunkedInferenceCheckbox.isChecked()

            params = dict(
                conf_thresh=self.confSpinbox.value,
                nms_thresh=self.nmsSpinbox.value,
                resize_ratio=self.resizeSpinbox.value,
                chunk_size=self.chunkSizeSpinBox.value if do_chunking else None,
                chunk_overlap=self.overlapSpinbox.value if do_chunking else None,
                calculate_statistics=self.calculateStatisticsCheckbox.checked,
            )

            logic = ThinSectionInstanceSegmenterLogic(onFinish=self.resetUI)
            classes = self.classifierInput.getSelectedModelMetadata()["outputs"]["y"]["class_names"]

            if self.remoteRadioButton.checked:
                self.cliNode = logic.dispatch(model_dir, refNode, soiNode, prefix, params, classes)
                self.applyCancelButtons.applyBtn.setEnabled(True)
                self.applyCancelButtons.cancelBtn.setEnabled(False)
            else:
                self.cliNode = logic.run(
                    model_dir,
                    refNode,
                    soiNode,
                    prefix,
                    params,
                    classes,
                    self.recommendedSettingsButton.text,
                    self.chunkSizeLabel.text,
                )
                if self.cliNode:
                    self.progressBar.setCommandLineModuleNode(self.cliNode)

            if self.cliNode is None:
                self.resetUI()

        except Exception as e:
            slicer.util.errorDisplay(f"Failed to complete execution. {e}")
            tmpPrefix = prefix.replace("{type}", "TMP_*")
            clearPattern(tmpPrefix)
            self.applyCancelButtons.applyBtn.setEnabled(True)
            self.applyCancelButtons.cancelBtn.setEnabled(False)
            raise

    def resetUI(self):
        self._checkRequirementsForApply()
        self.cliNode = None
