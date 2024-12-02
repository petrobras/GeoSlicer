import ctk
import qt
import slicer

from ltrace.algorithms import stops
from ltrace.slicer.ui import hierarchyVolumeInput
from .model import ModelLogic, ModelWidget


class StopsWidget(ModelWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup()

    def setup(self):
        formLayout = qt.QFormLayout(self)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        # Input section
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Input")
        formLayout.addWidget(inputCollapsibleButton)

        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.ttStopsBox = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLScalarVolumeNode"], tooltip="Select the transit time image.", hasNone=True
        )
        inputFormLayout.addRow("Transit time image:", self.ttStopsBox)
        inputFormLayout.addRow(" ", None)

        paramsCollapsibleButton = ctk.ctkCollapsibleButton()
        paramsCollapsibleButton.setText("Parameters")
        formLayout.addWidget(paramsCollapsibleButton)

        paramsFormLayout = qt.QFormLayout(paramsCollapsibleButton)
        paramsFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.thresholdSlider = ctk.ctkSliderWidget()
        self.thresholdSlider.singleStep = 1
        self.thresholdSlider.minimum = 10
        self.thresholdSlider.maximum = 255
        self.thresholdSlider.value = 180
        self.thresholdSlider.decimals = 0
        self.thresholdSlider.setToolTip(
            "Detection threshold. A lower value will detect more instances, but also have more false positives."
        )

        self.blurSizeSlider = ctk.ctkSliderWidget()
        self.blurSizeSlider.singleStep = 2
        self.blurSizeSlider.minimum = 3
        self.blurSizeSlider.maximum = 51
        self.blurSizeSlider.value = 17
        self.blurSizeSlider.decimals = 0
        self.blurSizeSlider.setToolTip(
            "Size of the Gaussian blur filter to apply to the transit time image before detection. A higher value will blur more."
        )

        self.blurSigmaSlider = ctk.ctkSliderWidget()
        self.blurSigmaSlider.singleStep = 0.2
        self.blurSigmaSlider.minimum = 0
        self.blurSigmaSlider.maximum = 5
        self.blurSigmaSlider.value = 2.2
        self.blurSigmaSlider.decimals = 1
        self.blurSigmaSlider.setToolTip(
            "Sigma of the Gaussian blur filter to apply to the transit time image before detection. A higher value will blur more."
        )

        paramsFormLayout.addRow("Threshold:", self.thresholdSlider)
        paramsFormLayout.addRow(" ", None)

        blurGroupBox = qt.QGroupBox("Pre-detection blur")
        blurFormLayout = qt.QFormLayout(blurGroupBox)
        blurFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        blurFormLayout.addRow("Size:", self.blurSizeSlider)
        blurFormLayout.addRow("Sigma:", self.blurSigmaSlider)

        paramsFormLayout.addRow(blurGroupBox)
        paramsFormLayout.addRow(" ", None)

        applyButton = qt.QPushButton("Apply")
        applyButton.setFixedHeight(40)
        applyButton.clicked.connect(self.onApplyButtonClicked)

        self.stopsOutputPrefixLineEdit = qt.QLineEdit()

        def onInputChanged():
            node = self.ttStopsBox.currentNode()
            applyButton.enabled = type(node) == slicer.vtkMRMLScalarVolumeNode
            self.stopsOutputPrefixLineEdit.text = node.GetName() if node else ""

            if node:
                if any(s in node.GetName().lower() for s in ["amp", "amplitude"]):
                    slicer.util.warningDisplay(
                        "This input image appears to be an amplitude image. Please check if it is the correct input."
                    )

        onInputChanged()
        self.ttStopsBox.currentItemChanged.connect(onInputChanged)

        # Output section
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addWidget(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        outputFormLayout.addRow("Output prefix:", self.stopsOutputPrefixLineEdit)
        outputFormLayout.addRow(" ", None)

        self.stopsStatusLabel = qt.QLabel()
        self.stopsStatusLabel.setAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)
        self.stopsStatusLabel.setWordWrap(True)

        formLayout.addWidget(applyButton)
        formLayout.addWidget(self.stopsStatusLabel)

    def onApplyButtonClicked(self):
        try:
            self.stopsStatusLabel.setText("Segmenting...")
            slicer.app.processEvents()
            params = stops.SegmentStopsParams(
                canny_thresh=self.thresholdSlider.value,
                blur_size=self.blurSizeSlider.value,
                blur_sigma=self.blurSigmaSlider.value,
            )
            labelmap, table = stops.create_stops_nodes(
                self.ttStopsBox.currentNode(),
                params,
                self.stopsOutputPrefixLineEdit.text,
            )
        except Exception as exc:
            slicer.util.errorDisplay(f"Failed to segment stops.\n\n{exc}")
            self.stopsStatusLabel.setText("Failed to segment stops.")
            raise
        self.stopsStatusLabel.setText(f"Segmentation completed, found {table.GetNumberOfRows()} stops.")
