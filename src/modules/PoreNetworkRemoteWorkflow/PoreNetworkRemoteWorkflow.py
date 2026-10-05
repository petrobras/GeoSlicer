import os
import platform
from pathlib import Path

import ctk
import pandas as pd
import qt
import slicer

from ltrace.pore_networks.simulation_parameters_node import (
    parameter_node_to_dict,
    save_dict_to_parameter_node,
    PNM_PARAMETER_TYPE_ATTR,
    EXTRACTOR_TYPE,
    ONE_PHASE_SIMULATION_TYPE,
    TWO_PHASE_SIMULATION_TYPE,
    REMOTE_WORKFLOW_TYPE,
)
from ltrace.pore_networks.simulation_parameters_widgets import LoadParamsLayout, SaveParamsLayout
from ltrace.remote.handlers.PoreNetworkRemoteWorkflowHandler import PoreNetworkRemoteWorkflowHandler
from ltrace.remote.slurm import MAX_WORKERS
from ltrace.slicer import ui
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer.widget.help_button import HelpButton
from ltrace.slicer_utils import LTracePlugin, LTracePluginLogic, LTracePluginWidget


class PoreNetworkRemoteWorkflow(LTracePlugin):
    SETTING_KEY = "PoreNetworkRemoteWorkflow"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Pore Network Remote Workflow"
        self.parent.categories = ["MicroCT", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.setHelpUrl("Volumes/PNM/PNM.html#pore-network-remote-workflow", NodeEnvironment.MICRO_CT)
        self.setHelpUrl("Multiscale/PNM/PNM.html#pore-network-remote-workflow", NodeEnvironment.MULTISCALE)

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PoreNetworkRemoteWorkflowWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.selected_csv_path = None

    def setup(self):
        LTracePluginWidget.setup(self)

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        mainLayout = qt.QVBoxLayout(frame)
        mainLayout.setContentsMargins(0, 0, 0, 0)

        # ========================
        # CSV selector (ComboBox) and Load button
        # ========================
        csvLayout = qt.QHBoxLayout()
        self.csvComboBox = qt.QComboBox()
        self.csvComboBox.addItem("")
        if platform.system() == "Windows":
            all_csv_path = r"\\dfs\cientifico\cenpes\res\drp\servicos\LTRACE\database\all_microtom_dados_brutos.csv"
        else:
            all_csv_path = "/nethome/drp/servicos/LTRACE/database/all_microtom_dados_brutos.csv"
        self.csvComboBox.addItem("All", all_csv_path)
        self.csvComboBox.currentIndexChanged.connect(self.onComboSelectionChanged)
        self.csvComboBox.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Fixed)
        csvLayout.addWidget(qt.QLabel("Select CSV File:"))
        csvLayout.addWidget(self.csvComboBox)

        self.loadButton = qt.QPushButton("Load")
        self.loadButton.setFixedWidth(100)
        self.loadButton.setFixedHeight(30)
        self.loadButton.clicked.connect(self.onLoadButtonClicked)
        csvLayout.addWidget(self.loadButton)

        csvHelp = HelpButton(
            "Select your index file data (e.g., 'All') and click **Load** to populate the sample list."
        )
        csvLayout.addWidget(csvHelp)

        mainLayout.addLayout(csvLayout)
        mainLayout.addSpacing(4)

        # ========================
        # Search bar with column selector
        # ========================
        searchLayout = qt.QHBoxLayout()
        searchLabel = qt.QLabel("Filter:")

        self.searchBox = qt.QLineEdit()
        self.searchBox.setPlaceholderText("Type to filter table...")
        self.searchBox.textChanged.connect(self.filterTable)

        self.columnCombo = qt.QComboBox()
        self.columnCombo.setFixedWidth(150)
        self.columnCombo.addItem("name")
        self.columnCombo.addItem("codigo_amostra")
        self.columnCombo.addItem("tipo_amostra")
        self.columnCombo.addItem("phi")
        self.columnCombo.currentIndexChanged.connect(lambda _: self.filterTable(self.searchBox.text))

        searchLayout.addWidget(searchLabel)
        searchLayout.addWidget(self.searchBox)
        searchLayout.addWidget(qt.QLabel(" in "))
        searchLayout.addWidget(self.columnCombo)

        mainLayout.addLayout(searchLayout)

        # ========================
        # Split View for Table and Selected Names
        # ========================
        self.tableTextSplitter = qt.QSplitter(qt.Qt.Vertical)
        mainLayout.addWidget(self.tableTextSplitter)

        self.dataTable = qt.QTableWidget()
        self.dataTable.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        self.dataTable.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        self.dataTable.doubleClicked.connect(self.onTableDoubleClick)
        self.dataTable.setSortingEnabled(True)
        self.dataTable.horizontalHeader().setStretchLastSection(True)
        self.dataTable.horizontalHeader().setSectionResizeMode(qt.QHeaderView.Stretch)
        self.tableTextSplitter.addWidget(self.dataTable)

        self.selectedNamesText = qt.QTextEdit()
        self.selectedNamesText.setPlaceholderText(
            "Selected names will appear here. You can also paste sample names directly, separated by spaces, commas, or semicolons."
        )
        self.selectedNamesText.setAcceptRichText(False)
        self.tableTextSplitter.addWidget(self.selectedNamesText)

        mainLayout.addSpacing(4)

        # ========================
        # Parameters
        # ========================

        # --- Workflow Settings ---
        self.workflowCollapsible = ctk.ctkCollapsibleButton()
        self.workflowCollapsible.text = "Workflow Settings"
        self.workflowCollapsible.collapsed = True
        mainLayout.addWidget(self.workflowCollapsible)

        workflowLayout = qt.QFormLayout(self.workflowCollapsible)
        workflowLayout.setLabelAlignment(qt.Qt.AlignRight)

        # Parameters Input/Output Sections
        self.loadParamsLayout = LoadParamsLayout(REMOTE_WORKFLOW_TYPE, self.onParameterInputLoad)
        self.parameterInputLoadCollapsible = self.loadParamsLayout.collapsible
        self.parameterInputWidget = self.loadParamsLayout.parameterInputWidget
        workflowLayout.addRow(self.loadParamsLayout)

        self.saveParamsLayout = SaveParamsLayout("remote_workflow_input_parameters", self.onParameterInputSave)
        self.parameterInputLineEdit = self.saveParamsLayout.lineEdit
        workflowLayout.addRow(self.saveParamsLayout)

        # Extractor Parameters
        self.extractor_params_combo = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLTextNode"],
            defaultText="Select the extractor parameters",
            hasNone=True,
        )
        self.extractor_params_combo.addNodeAttributeIncludeFilter(PNM_PARAMETER_TYPE_ATTR, EXTRACTOR_TYPE)
        self.extractor_params_combo.showEmptyHierarchyItems = False

        extractorHelp = HelpButton("Select the extraction parameters used to generate the pore network.")
        extractorHBox = qt.QHBoxLayout()
        extractorHBox.addWidget(self.extractor_params_combo)
        extractorHBox.addWidget(extractorHelp)
        workflowLayout.addRow("Extractor params:", extractorHBox)

        # One-Phase Parameters
        self.one_phase_simulation_params_combo = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLTextNode"],
            defaultText="Select the one-phase simulation parameters",
            hasNone=True,
        )
        self.one_phase_simulation_params_combo.addNodeAttributeIncludeFilter(
            PNM_PARAMETER_TYPE_ATTR, ONE_PHASE_SIMULATION_TYPE
        )
        self.one_phase_simulation_params_combo.showEmptyHierarchyItems = False

        onePhaseHelp = HelpButton("Select the parameters used for the one-phase simulation.")
        onePhaseHBox = qt.QHBoxLayout()
        onePhaseHBox.addWidget(self.one_phase_simulation_params_combo)
        onePhaseHBox.addWidget(onePhaseHelp)
        workflowLayout.addRow("One-phase params:", onePhaseHBox)

        # Two-Phase Parameters
        self.two_phase_simulation_params_combo = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLTextNode"],
            defaultText="Select the two-phase simulation parameters",
            hasNone=True,
        )
        self.two_phase_simulation_params_combo.addNodeAttributeIncludeFilter(
            PNM_PARAMETER_TYPE_ATTR, TWO_PHASE_SIMULATION_TYPE
        )
        self.two_phase_simulation_params_combo.showEmptyHierarchyItems = False

        twoPhaseHelp = HelpButton("Select the parameters used for the two-phase simulation.")
        twoPhaseHBox = qt.QHBoxLayout()
        twoPhaseHBox.addWidget(self.two_phase_simulation_params_combo)
        twoPhaseHBox.addWidget(twoPhaseHelp)
        workflowLayout.addRow("Two-phase params:", twoPhaseHBox)

        # Output Folder Prefix
        self.outputFolderPrefixLine = qt.QLineEdit()
        self.outputFolderPrefixLine.setText("Workflow")
        self.outputFolderPrefixLine.setPlaceholderText("Output folder prefix")

        prefixHelp = HelpButton("Appends a custom identifying string to the workflow output directory name.")
        prefixHBox = qt.QHBoxLayout()
        prefixHBox.addWidget(self.outputFolderPrefixLine)
        prefixHBox.addWidget(prefixHelp)
        workflowLayout.addRow("Output folder prefix:", prefixHBox)

        # Downsampling Factors
        self.downsamplingFactorLineEdit = qt.QLineEdit()
        self.downsamplingFactorLineEdit.setText("4")
        self.downsamplingFactorLineEdit.setPlaceholderText("e.g., 2, 4.5, 6")

        dsHelp = HelpButton(
            "Accepts a comma-separated list of values (e.g., 2, 4.5, 6). "
            "A separate workflow is generated for each specified factor."
        )
        dsHBox = qt.QHBoxLayout()
        dsHBox.addWidget(self.downsamplingFactorLineEdit)
        dsHBox.addWidget(dsHelp)
        workflowLayout.addRow("Downsampling factor(s):", dsHBox)

        # Workers
        self.workersSpinBox = qt.QSpinBox()
        self.workersSpinBox.setRange(1, MAX_WORKERS)
        self.workersSpinBox.setValue(9)

        self.suggestWorkersButton = qt.QPushButton("Suggest")
        self.suggestWorkersButton.clicked.connect(self.onSuggestWorkers)

        workersHelp = HelpButton(
            "Defines the maximum number of samples processed simultaneously on the cluster. "
            "The **Suggest** button automatically calculates the recommended number of workers "
            "based on the number of selected samples and downsampling factors."
        )
        workersHBox = qt.QHBoxLayout()
        workersHBox.addWidget(self.workersSpinBox)
        workersHBox.addWidget(self.suggestWorkersButton)
        workersHBox.addWidget(workersHelp)
        workflowLayout.addRow("Workers:", workersHBox)

        # Wall time
        self.walltimeLineEdit = qt.QLineEdit()
        self.walltimeLineEdit.setText("72:00:00")
        self.walltimeLineEdit.setPlaceholderText("e.g., 72:00:00 or 12-00:00:00")

        walltimeHelp = HelpButton(
            "Defines the maximum execution walltime for the master SLURM job and Dask workers "
            "(e.g., '72:00:00' or '12-00:00:00'). Maximum partition limit is 12 days."
        )
        walltimeHBox = qt.QHBoxLayout()
        walltimeHBox.addWidget(self.walltimeLineEdit)
        walltimeHBox.addWidget(walltimeHelp)
        workflowLayout.addRow("Wall time:", walltimeHBox)

        self.saveWorkstepImageDataCheckbox = qt.QCheckBox("Save workstep image")
        self.saveWorkstepImageDataCheckbox.setChecked(False)
        workflowLayout.addRow(self.saveWorkstepImageDataCheckbox)

        # --- Crop Sample Options ---
        self.cropSampleCollapsible = ctk.ctkCollapsibleButton()
        self.cropSampleCollapsible.text = "Crop Sample Options"
        self.cropSampleCollapsible.collapsed = True
        mainLayout.addWidget(self.cropSampleCollapsible)

        cropSampleLayout = qt.QFormLayout(self.cropSampleCollapsible)
        cropSampleLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.cropSampleCheckbox = qt.QCheckBox("Crop sample")
        self.cropSampleCheckbox.setChecked(True)
        cropSampleLayout.addRow(self.cropSampleCheckbox)

        self.cropMethodComboBox = qt.QComboBox()
        self.cropMethodComboBox.addItems(["Auto", "Sample segmentation", "Cylindrical crop"])
        self.cropMethodComboBox.setCurrentText("Auto")

        cropMethodHelp = HelpButton(
            "**Auto Mode:** The workflow analyzes the micro-CT volume boundaries to automatically choose the most appropriate cropping strategy:\n\n"
            "- **Cylindrical crop:** Selected if the sample fills the image but exhibits corner attenuation.\n"
            "- **Sample segmentation:** Selected if the sample terminates before the image boundaries.\n"
            "- **Skipped:** Cropping is skipped if neither condition matches.\n\n"
            "**Sample Segmentation:** Uses a 3-phase Multi-Otsu segmentation followed by morphological processing to separate the rock from the background and remove artifacts.\n\n"
            "**Cylindrical Crop:** Applies a cylindrical mask. Center coordinates default to the detected sample center. The radius may be automatically reduced using the **Reduction (%)** parameter."
        )
        cropMethodHBox = qt.QHBoxLayout()
        cropMethodHBox.addWidget(self.cropMethodComboBox)
        cropMethodHBox.addWidget(cropMethodHelp)
        cropSampleLayout.addRow("Method:", cropMethodHBox)

        self.cylinderCenterXSpinBox = qt.QSpinBox()
        self.cylinderCenterXSpinBox.setRange(-1, 99999)
        self.cylinderCenterXSpinBox.setSpecialValueText("Auto")
        self.cylinderCenterXSpinBox.setValue(-1)

        self.cylinderCenterYSpinBox = qt.QSpinBox()
        self.cylinderCenterYSpinBox.setRange(-1, 99999)
        self.cylinderCenterYSpinBox.setSpecialValueText("Auto")
        self.cylinderCenterYSpinBox.setValue(-1)

        self.cylinderRadiusSpinBox = qt.QSpinBox()
        self.cylinderRadiusSpinBox.setRange(-1, 99999)
        self.cylinderRadiusSpinBox.setSpecialValueText("Auto")
        self.cylinderRadiusSpinBox.setValue(-1)

        self.radiusReductionWidget = qt.QWidget()
        reductionLayout = qt.QHBoxLayout(self.radiusReductionWidget)
        reductionLayout.setContentsMargins(10, 0, 0, 0)

        reductionLabel = qt.QLabel("Reduction:")
        self.cylinderRadiusReductionSpinBox = qt.QSpinBox()
        self.cylinderRadiusReductionSpinBox.setMinimumWidth(80)
        self.cylinderRadiusReductionSpinBox.setRange(0, 75)
        self.cylinderRadiusReductionSpinBox.setValue(6)
        self.cylinderRadiusReductionSpinBox.setSuffix(" %")

        reductionLayout.addWidget(reductionLabel)
        reductionLayout.addWidget(self.cylinderRadiusReductionSpinBox)

        radiusCombinedWidget = qt.QWidget()
        radiusCombinedLayout = qt.QHBoxLayout(radiusCombinedWidget)
        radiusCombinedLayout.setContentsMargins(0, 0, 0, 0)

        radiusCombinedLayout.addWidget(self.cylinderRadiusSpinBox)
        radiusCombinedLayout.addWidget(self.radiusReductionWidget)

        self.cylinderParamsWidget = qt.QWidget()
        cylinderLayout = qt.QFormLayout(self.cylinderParamsWidget)
        cylinderLayout.setContentsMargins(0, 0, 0, 0)
        cylinderLayout.addRow("Center X (pixels):", self.cylinderCenterXSpinBox)
        cylinderLayout.addRow("Center Y (pixels):", self.cylinderCenterYSpinBox)
        cylinderLayout.addRow("Radius (pixels):", radiusCombinedWidget)

        cropSampleLayout.addRow(self.cylinderParamsWidget)

        self.cropMethodComboBox.currentIndexChanged.connect(self._onCropMethodChanged)
        self.cylinderRadiusSpinBox.valueChanged.connect(self._onRadiusValueChanged)

        self._onCropMethodChanged()
        self._onRadiusValueChanged(self.cylinderRadiusSpinBox.value)

        discardZLayout = qt.QHBoxLayout()
        self.zDiscardBottomSpinBox = qt.QSpinBox()
        self.zDiscardBottomSpinBox.setRange(0, 45)
        self.zDiscardBottomSpinBox.setValue(1)
        self.zDiscardBottomSpinBox.setSuffix(" %")
        self.zDiscardTopSpinBox = qt.QSpinBox()
        self.zDiscardTopSpinBox.setRange(0, 45)
        self.zDiscardTopSpinBox.setValue(1)
        self.zDiscardTopSpinBox.setSuffix(" %")

        discardZHelp = HelpButton(
            "Removes a configurable percentage (0–45%) from the lower and upper ends of the sample along the Z axis."
        )
        discardZLayout.addWidget(qt.QLabel("Discard bottom/top:"))
        discardZLayout.addWidget(self.zDiscardBottomSpinBox)
        discardZLayout.addWidget(self.zDiscardTopSpinBox)
        discardZLayout.addWidget(discardZHelp)
        cropSampleLayout.addRow(discardZLayout)

        # --- Shading Correction Options ---
        self.shadingCorrectionCollapsible = ctk.ctkCollapsibleButton()
        self.shadingCorrectionCollapsible.text = "Shading Correction Options"
        self.shadingCorrectionCollapsible.collapsed = True
        mainLayout.addWidget(self.shadingCorrectionCollapsible)

        shadingLayout = qt.QFormLayout(self.shadingCorrectionCollapsible)
        shadingLayout.setLabelAlignment(qt.Qt.AlignRight)

        shadingCheckboxLayout = qt.QHBoxLayout()
        self.shadingCorrectionCheckbox = qt.QCheckBox("Shading correction")
        self.shadingCorrectionCheckbox.setChecked(True)
        shadingHelp = HelpButton("Corrects illumination gradients and X-ray beam hardening artifacts.")
        shadingCheckboxLayout.addWidget(self.shadingCorrectionCheckbox)
        shadingCheckboxLayout.addWidget(shadingHelp)
        shadingCheckboxLayout.addStretch()
        shadingLayout.addRow(shadingCheckboxLayout)

        self.functionTypeComboBox = qt.QComboBox()
        self.functionTypeComboBox.addItems(["Auto", "Polynomial", "Polynomial Radial", "Spline Radial"])
        self.functionTypeComboBox.setCurrentText("Auto")

        functionHelp = HelpButton(
            "**Auto Mode:** Evaluates sample boundaries and cropping results to select the most appropriate correction model:\n\n"
            "- **Polynomial Radial:** Selected when cylindrical cropping or partial sample boundaries are detected.\n"
            "- **Spline Radial:** Selected when no sample cropping is required.\n\n"
            "**Polynomial:** Fits a conventional polynomial across the calculated slice mask.\n\n"
            "**Polynomial Radial:** Constraints the polynomial fitting to a radially symmetric model.\n\n"
            "**Spline Radial:** Applies a radially symmetric spline-based function."
        )
        functionHBox = qt.QHBoxLayout()
        functionHBox.addWidget(self.functionTypeComboBox)
        functionHBox.addWidget(functionHelp)
        shadingLayout.addRow("Function:", functionHBox)

        self.polynomialOrderComboBox = qt.QComboBox()
        self.polynomialOrderComboBox.addItems(["2", "4", "6"])
        self.polynomialOrderComboBox.setCurrentText("6")

        orderHelp = HelpButton(
            "Defines the degree of the polynomial function used to fit and estimate the background illumination intensity gradient."
        )
        orderHBox = qt.QHBoxLayout()
        orderHBox.addWidget(self.polynomialOrderComboBox)
        orderHBox.addWidget(orderHelp)
        shadingLayout.addRow("Order:", orderHBox)

        sliceGroupLayout = qt.QHBoxLayout()
        self.sliceGroupSizeSpinBox = qt.QSpinBox()
        self.sliceGroupSizeSpinBox.setRange(1, 10)
        self.sliceGroupSizeSpinBox.setValue(1)

        sliceGroupHelp = HelpButton("Number of consecutive slices sharing the same fitted correction model.")
        sliceGroupLayout.addWidget(self.sliceGroupSizeSpinBox)
        sliceGroupLayout.addWidget(sliceGroupHelp)
        shadingLayout.addRow("Slice group size:", sliceGroupLayout)

        fittingPointsLayout = qt.QHBoxLayout()
        self.fittingPointsPercentageSpinBox = qt.QSpinBox()
        self.fittingPointsPercentageSpinBox.setRange(1, 100)
        self.fittingPointsPercentageSpinBox.setValue(60)
        self.fittingPointsPercentageSpinBox.setSuffix(" %")

        fittingPointsHelp = HelpButton("Percentage of mask pixels used to estimate the correction surface.")
        fittingPointsLayout.addWidget(self.fittingPointsPercentageSpinBox)
        fittingPointsLayout.addWidget(fittingPointsHelp)
        shadingLayout.addRow("Fitting points (%):", fittingPointsLayout)

        self.shadingMaskPercentileMinSpinBox = qt.QSpinBox()
        self.shadingMaskPercentileMinSpinBox.setRange(0, 100)
        self.shadingMaskPercentileMinSpinBox.setValue(20)

        self.shadingMaskPercentileMaxSpinBox = qt.QSpinBox()
        self.shadingMaskPercentileMaxSpinBox.setRange(0, 100)
        self.shadingMaskPercentileMaxSpinBox.setValue(90)

        self.shadingMaskPercentileMinSpinBox.valueChanged.connect(
            lambda val: self.shadingMaskPercentileMaxSpinBox.setMinimum(val)
        )
        self.shadingMaskPercentileMaxSpinBox.valueChanged.connect(
            lambda val: self.shadingMaskPercentileMinSpinBox.setMaximum(val)
        )

        percentileLayout = qt.QHBoxLayout()
        percentileLayout.addWidget(self.shadingMaskPercentileMinSpinBox)
        percentileLayout.addWidget(self.shadingMaskPercentileMaxSpinBox)

        shadingMaskHelp = HelpButton("Defines the intensity percentile range used to estimate the correction mask.")
        percentileLayout.addWidget(shadingMaskHelp)
        shadingLayout.addRow("Mask percentile min/max:", percentileLayout)

        # --- Porosity Map Options ---
        self.porosityMapCollapsible = ctk.ctkCollapsibleButton()
        self.porosityMapCollapsible.text = "Porosity Map Options"
        self.porosityMapCollapsible.collapsed = True
        mainLayout.addWidget(self.porosityMapCollapsible)

        porosityLayout = qt.QFormLayout(self.porosityMapCollapsible)
        porosityLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.minSubresPorosityFractionSpinBox = qt.QDoubleSpinBox()
        self.minSubresPorosityFractionSpinBox.setRange(0.01, 1.00)
        self.minSubresPorosityFractionSpinBox.setSingleStep(0.01)
        self.minSubresPorosityFractionSpinBox.setValue(0.40)

        porosityHelp = HelpButton(
            "**Standard Method (experimental φ available):** Uses the experimental porosity loaded from the database to calibrate the porosity map.\n\n"
            "**Fallback Method (experimental φ unavailable):** Uses a three-class Multi-Otsu segmentation to estimate macro- and sub-resolution porosity."
        )
        porosityRowHBox = qt.QHBoxLayout()
        porosityRowHBox.addWidget(self.minSubresPorosityFractionSpinBox)
        porosityRowHBox.addWidget(porosityHelp)
        porosityLayout.addRow("Min subres porosity fraction:", porosityRowHBox)

        self.multiOtsuShift1Slider = ctk.ctkSliderWidget()
        self.multiOtsuShift1Slider.minimum = -15
        self.multiOtsuShift1Slider.maximum = 15
        self.multiOtsuShift1Slider.value = 0
        self.multiOtsuShift1Slider.decimals = 0
        self.multiOtsuShift1Slider.suffix = "%"
        self.multiOtsuShift1Slider.setToolTip(
            "Shift applied to Phase 1 Multi-Otsu threshold when Experimental Porosity is missing."
        )
        porosityLayout.addRow("Otsu Threshold 1 Shift:", self.multiOtsuShift1Slider)

        self.multiOtsuShift2Slider = ctk.ctkSliderWidget()
        self.multiOtsuShift2Slider.minimum = -15
        self.multiOtsuShift2Slider.maximum = 15
        self.multiOtsuShift2Slider.value = 0
        self.multiOtsuShift2Slider.decimals = 0
        self.multiOtsuShift2Slider.suffix = "%"
        self.multiOtsuShift2Slider.setToolTip(
            "Shift applied to Phase 2 Multi-Otsu threshold when Experimental Porosity is missing."
        )
        porosityLayout.addRow("Otsu Threshold 2 Shift:", self.multiOtsuShift2Slider)

        gadLayout = qt.QHBoxLayout()
        self.applyGradientCheckbox = qt.QCheckBox("Gradient anisotropic diffusion")
        self.applyGradientCheckbox.setChecked(True)
        gadHelp = HelpButton(
            "Optional edge-preserving smoothing filter that reduces noise while preserving pore boundaries."
        )
        gadLayout.addWidget(self.applyGradientCheckbox)
        gadLayout.addWidget(gadHelp)
        gadLayout.addStretch()
        porosityLayout.addRow(gadLayout)

        self.conductanceSpinBox = qt.QDoubleSpinBox()
        self.conductanceSpinBox.setRange(0.0, 10.0)
        self.conductanceSpinBox.setSingleStep(0.1)
        self.conductanceSpinBox.setValue(3.0)
        porosityLayout.addRow("Conductance:", self.conductanceSpinBox)

        self.iterationsSpinBox = qt.QSpinBox()
        self.iterationsSpinBox.setRange(1, 30)
        self.iterationsSpinBox.setSingleStep(1)
        self.iterationsSpinBox.setValue(10)
        porosityLayout.addRow("Iterations:", self.iterationsSpinBox)

        self.timeStepSpinBox = qt.QDoubleSpinBox()
        self.timeStepSpinBox.setDecimals(4)
        self.timeStepSpinBox.setRange(0.001, 0.0625)
        self.timeStepSpinBox.setSingleStep(0.001)
        self.timeStepSpinBox.setValue(0.0625)
        porosityLayout.addRow("Time step:", self.timeStepSpinBox)

        # ========================
        # Action Buttons (Visualize and Apply)
        # ========================
        actionsLayout = qt.QHBoxLayout()

        self.visualizeButton = qt.QPushButton("Visualize")
        self.visualizeButton.setFixedHeight(40)
        self.visualizeButton.setToolTip("Load to visually inspect the raw data.")
        self.visualizeButton.clicked.connect(self.onVisualize)

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setFixedHeight(40)
        self.applyButton.clicked.connect(self.onApply)

        actionsHelp = HelpButton(
            "**Visualize:** Perform a visualization-only execution.\n\n"
            "**Apply:** Submit the workflow to the cluster."
        )

        actionsLayout.addWidget(self.visualizeButton, 1)
        actionsLayout.addWidget(self.applyButton, 2)
        actionsLayout.addWidget(actionsHelp)

        mainLayout.addLayout(actionsLayout)
        mainLayout.addSpacing(10)

        self.logic = PoreNetworkRemoteWorkflowLogic()
        self.df = None

    def _onCropMethodChanged(self):
        if self.cropMethodComboBox.currentText == "Cylindrical crop":
            self.cylinderParamsWidget.setVisible(True)
        else:
            self.cylinderParamsWidget.setVisible(False)

    def _onRadiusValueChanged(self, value):
        if 0 <= value < 100:
            self.cylinderRadiusSpinBox.blockSignals(True)
            if value == 0:
                self.cylinderRadiusSpinBox.setValue(100)
                value = 100
            elif value == 99:
                self.cylinderRadiusSpinBox.setValue(-1)
                value = -1
            else:
                self.cylinderRadiusSpinBox.setValue(100)
                value = 100
            self.cylinderRadiusSpinBox.blockSignals(False)

        if value == -1:
            self.radiusReductionWidget.setEnabled(True)
        else:
            self.radiusReductionWidget.setEnabled(False)

    def onComboSelectionChanged(self, index):
        if index <= 0:
            self.selected_csv_path = None
            self.loadButton.setEnabled(False)
            return
        self.selected_csv_path = self.csvComboBox.itemData(index)
        self.loadButton.setEnabled(True)

    def onLoadButtonClicked(self):
        if not self.selected_csv_path:
            slicer.util.warningDisplay("Please select a CSV file first.")
            return
        try:
            self.loadCSV(self.selected_csv_path)
            self.searchBox.clear()
            self.columnCombo.setCurrentIndex(0)
        except Exception as e:
            slicer.util.errorDisplay(f"Failed to load CSV: {str(e)}")

    def loadCSV(self, csv_path):
        self.df = pd.read_csv(csv_path)

        base_dir = os.path.dirname(csv_path)
        summary_path = os.path.join(base_dir, "summary.csv")

        summary_df = pd.read_csv(summary_path)
        self.df = self.df.merge(summary_df, on="codigo_amostra", how="left", suffixes=("", "_summary"))

        required_columns = ["codigo_amostra", "tipo_amostra", "name", "phi"]
        available_columns = [col for col in required_columns if col in self.df.columns]
        self.df = self.df[available_columns]

        self.dataTable.setRowCount(len(self.df))
        self.dataTable.setColumnCount(len(self.df.columns))
        self.dataTable.setHorizontalHeaderLabels(self.df.columns.tolist())

        for i, row in self.df.iterrows():
            for j, col in enumerate(self.df.columns):
                val = row[col]
                item_text = "" if pd.isna(val) else str(val)
                item = qt.QTableWidgetItem(item_text)
                self.dataTable.setItem(i, j, item)

        header = self.dataTable.horizontalHeader()
        for i in range(len(self.df.columns)):
            header.setSectionResizeMode(i, qt.QHeaderView.Interactive)

    def filterTable(self, text):
        if self.df is None or self.df.empty:
            return

        text = text.strip().lower()
        selected_column = self.columnCombo.currentText

        if selected_column not in self.df.columns:
            return

        col_index = list(self.df.columns).index(selected_column)

        for row in range(len(self.df)):
            item = self.dataTable.item(row, col_index)
            visible = True if not text else (item is not None and text in item.text().lower())
            self.dataTable.setRowHidden(row, not visible)

    def onTableDoubleClick(self, index):
        if self.df is None:
            return
        row = index.row()
        try:
            name_col_idx = self.df.columns.get_loc("name")
            name_item = self.dataTable.item(row, name_col_idx)
            name = name_item.text().strip()
        except (KeyError, ValueError, TypeError, AttributeError):
            return

        current_text = self.selectedNamesText.toPlainText().strip()
        current_text = current_text.replace(",", " ").replace(";", " ")
        current_names = set(current_text.split()) if current_text else set()

        if name not in current_names:
            current_names.add(name)
            new_text = " ".join(current_names)
            self.selectedNamesText.setText(new_text)

    def onSuggestWorkers(self):
        raw_text = self.selectedNamesText.toPlainText()
        selected_names = raw_text.replace(",", " ").replace(";", " ").split()

        ds_text = self.downsamplingFactorLineEdit.text
        ds_factors = [x.strip() for x in ds_text.split(",") if x.strip()]

        if not selected_names or not ds_factors:
            return

        suggested_workers = min(len(selected_names) * len(ds_factors), MAX_WORKERS)
        self.workersSpinBox.setValue(suggested_workers)

    def onParameterInputSave(self):
        parameterValues = self.getParams(visualize=False, save_state=True)
        parameterNode = save_dict_to_parameter_node(
            parameterValues, self.parameterInputLineEdit.text, None, node_type=REMOTE_WORKFLOW_TYPE
        )
        slicer.app.applicationLogic().GetSelectionNode().SetActiveTableID(parameterNode.GetID())
        slicer.app.applicationLogic().PropagateTableSelection()

    def onParameterInputLoad(self):
        selectedNode = self.parameterInputWidget.currentNode()
        if selectedNode:
            parameters_dict = parameter_node_to_dict(selectedNode)
            self.setParams(parameters_dict)
            self.parameterInputLoadCollapsible.collapsed = True

    def getParams(self, visualize=False, save_state=False):
        extractor_params_node = self.extractor_params_combo.currentNode()
        one_phase_simulation_params_node = self.one_phase_simulation_params_combo.currentNode()
        two_phase_simulation_params_node = self.two_phase_simulation_params_combo.currentNode()

        try:
            ds_factors = [float(x.strip()) for x in self.downsamplingFactorLineEdit.text.split(",") if x.strip()]
        except ValueError:
            ds_factors = []

        crop_sample_active = (
            self.cropSampleCheckbox.isChecked()
            if save_state
            else (self.cropSampleCheckbox.isChecked() if not visualize else False)
        )
        shading_correction_active = (
            self.shadingCorrectionCheckbox.isChecked()
            if save_state
            else (self.shadingCorrectionCheckbox.isChecked() if not visualize else False)
        )
        save_workstep_active = (
            self.saveWorkstepImageDataCheckbox.isChecked()
            if save_state
            else (self.saveWorkstepImageDataCheckbox.isChecked() if not visualize else True)
        )

        use_gpu_active = False

        extractor_active = (True if extractor_params_node else False) if (save_state or not visualize) else False
        one_phase_active = (
            (True if one_phase_simulation_params_node else False) if (save_state or not visualize) else False
        )
        two_phase_active = (
            (True if two_phase_simulation_params_node else False) if (save_state or not visualize) else False
        )

        workflow_params = {
            "selected_names": self.selectedNamesText.toPlainText(),
            "output_folder_prefix": self.outputFolderPrefixLine.text.strip(),
            "downsampling_factors": ds_factors,
            "walltime": self.walltimeLineEdit.text.strip() or "72:00:00",
            "use_gpu": use_gpu_active,
            "crop_sample": crop_sample_active,
            "shading_correction": shading_correction_active,
            "save_workstep_image_data": save_workstep_active,
            "workers": self.workersSpinBox.value,
            "extractor": extractor_active,
            "one_phase_simulation": one_phase_active,
            "two_phase_simulation": two_phase_active,
            "visualize": visualize,
            "shading_correction_params": None,
            "extractor_params": None,
            "one_phase_simulation_params": None,
            "two_phase_simulation_params": None,
            "porosity_map_params": None,
            "extractor_node_id": extractor_params_node.GetID() if extractor_params_node else "",
            "one_phase_simulation_node_id": (
                one_phase_simulation_params_node.GetID() if one_phase_simulation_params_node else ""
            ),
            "two_phase_simulation_node_id": (
                two_phase_simulation_params_node.GetID() if two_phase_simulation_params_node else ""
            ),
        }

        if crop_sample_active or save_state:
            workflow_params["crop_sample_params"] = {
                "method": self.cropMethodComboBox.currentText,
                "z_discard_bottom": self.zDiscardBottomSpinBox.value,
                "z_discard_top": self.zDiscardTopSpinBox.value,
                "center_x": self.cylinderCenterXSpinBox.value,
                "center_y": self.cylinderCenterYSpinBox.value,
                "radius": self.cylinderRadiusSpinBox.value,
                "auto_radius_reduction": self.cylinderRadiusReductionSpinBox.value,
            }

        if shading_correction_active or save_state:
            workflow_params["shading_correction_params"] = {
                "slice_group_size": self.sliceGroupSizeSpinBox.value,
                "fitting_points_percentage": self.fittingPointsPercentageSpinBox.value,
                "shading_mask_percentile_min": self.shadingMaskPercentileMinSpinBox.value,
                "shading_mask_percentile_max": self.shadingMaskPercentileMaxSpinBox.value,
                "function_type": self.functionTypeComboBox.currentText,
                "polynomial_order": (
                    int(self.polynomialOrderComboBox.currentText) if self.polynomialOrderComboBox.currentText else 6
                ),
            }

        if extractor_active and extractor_params_node:
            workflow_params["extractor_params"] = parameter_node_to_dict(extractor_params_node)

        if one_phase_active and one_phase_simulation_params_node:
            workflow_params["one_phase_simulation_params"] = parameter_node_to_dict(one_phase_simulation_params_node)

        if two_phase_active and two_phase_simulation_params_node:
            workflow_params["two_phase_simulation_params"] = parameter_node_to_dict(two_phase_simulation_params_node)

        gad_active = (
            self.applyGradientCheckbox.isChecked()
            if save_state
            else (self.applyGradientCheckbox.isChecked() if not visualize else False)
        )

        workflow_params["porosity_map_params"] = {
            "min_subres_porosity_fraction": self.minSubresPorosityFractionSpinBox.value,
            "multi_otsu_shift1": self.multiOtsuShift1Slider.value,
            "multi_otsu_shift2": self.multiOtsuShift2Slider.value,
            "gradient_anisotropic_diffusion": gad_active,
            "gradient_anisotropic_diffusion_params": None,
        }

        if gad_active or save_state:
            workflow_params["porosity_map_params"]["gradient_anisotropic_diffusion_params"] = {
                "conductance": self.conductanceSpinBox.value,
                "number_of_iterations": self.iterationsSpinBox.value,
                "time_step": self.timeStepSpinBox.value,
            }

        return workflow_params

    def setParams(self, params):
        if not params:
            return

        if "selected_names" in params:
            self.selectedNamesText.setText(params["selected_names"])
        if "output_folder_prefix" in params:
            self.outputFolderPrefixLine.setText(params["output_folder_prefix"])

        if "downsampling_factors" in params:
            factors = params["downsampling_factors"]
            if isinstance(factors, list):
                self.downsamplingFactorLineEdit.setText(", ".join(map(str, factors)))
            else:
                self.downsamplingFactorLineEdit.setText(str(factors))

        if "workers" in params:
            self.workersSpinBox.setValue(int(params["workers"]))

        if "walltime" in params:
            self.walltimeLineEdit.setText(str(params["walltime"]))

        if "save_workstep_image_data" in params:
            self.saveWorkstepImageDataCheckbox.setChecked(
                str(params["save_workstep_image_data"]).lower() in ("true", "1", "t")
            )

        if "crop_sample" in params:
            self.cropSampleCheckbox.setChecked(str(params["crop_sample"]).lower() in ("true", "1", "t"))

        crop_params = params.get("crop_sample_params", {})
        if crop_params:
            if "method" in crop_params:
                self.cropMethodComboBox.setCurrentText(crop_params["method"])
            if "z_discard_bottom" in crop_params:
                self.zDiscardBottomSpinBox.setValue(int(crop_params["z_discard_bottom"]))
            if "z_discard_top" in crop_params:
                self.zDiscardTopSpinBox.setValue(int(crop_params["z_discard_top"]))
            if "center_x" in crop_params:
                self.cylinderCenterXSpinBox.setValue(int(crop_params["center_x"]))
            if "center_y" in crop_params:
                self.cylinderCenterYSpinBox.setValue(int(crop_params["center_y"]))
            if "radius" in crop_params:
                self.cylinderRadiusSpinBox.setValue(int(crop_params["radius"]))
            if "auto_radius_reduction" in crop_params:
                self.cylinderRadiusReductionSpinBox.setValue(int(crop_params["auto_radius_reduction"]))

        if "shading_correction" in params:
            self.shadingCorrectionCheckbox.setChecked(str(params["shading_correction"]).lower() in ("true", "1", "t"))

        shading_params = params.get("shading_correction_params", {})
        if shading_params:
            if "slice_group_size" in shading_params:
                self.sliceGroupSizeSpinBox.setValue(int(shading_params["slice_group_size"]))
            if "fitting_points_percentage" in shading_params:
                self.fittingPointsPercentageSpinBox.setValue(int(shading_params["fitting_points_percentage"]))
            if "shading_mask_percentile_min" in shading_params:
                self.shadingMaskPercentileMinSpinBox.setValue(int(shading_params["shading_mask_percentile_min"]))
            if "shading_mask_percentile_max" in shading_params:
                self.shadingMaskPercentileMaxSpinBox.setValue(int(shading_params["shading_mask_percentile_max"]))
            if "function_type" in shading_params:
                self.functionTypeComboBox.setCurrentText(shading_params["function_type"])
            if "polynomial_order" in shading_params:
                self.polynomialOrderComboBox.setCurrentText(str(shading_params["polynomial_order"]))

        porosity_params = params.get("porosity_map_params", {})
        if porosity_params:
            if "min_subres_porosity_fraction" in porosity_params:
                self.minSubresPorosityFractionSpinBox.setValue(float(porosity_params["min_subres_porosity_fraction"]))
            if "multi_otsu_shift1" in porosity_params:
                self.multiOtsuShift1Slider.value = float(porosity_params["multi_otsu_shift1"])
            if "multi_otsu_shift2" in porosity_params:
                self.multiOtsuShift2Slider.value = float(porosity_params["multi_otsu_shift2"])
            if "gradient_anisotropic_diffusion" in porosity_params:
                self.applyGradientCheckbox.setChecked(
                    str(porosity_params["gradient_anisotropic_diffusion"]).lower() in ("true", "1", "t")
                )

            gad_params = porosity_params.get("gradient_anisotropic_diffusion_params", {})
            if gad_params:
                if "conductance" in gad_params:
                    self.conductanceSpinBox.setValue(float(gad_params["conductance"]))
                if "number_of_iterations" in gad_params:
                    self.iterationsSpinBox.setValue(int(gad_params["number_of_iterations"]))
                if "time_step" in gad_params:
                    self.timeStepSpinBox.setValue(float(gad_params["time_step"]))

        for key, combo in [
            ("extractor_node_id", self.extractor_params_combo),
            ("one_phase_simulation_node_id", self.one_phase_simulation_params_combo),
            ("two_phase_simulation_node_id", self.two_phase_simulation_params_combo),
        ]:
            node_id = params.get(key, "")
            node = slicer.mrmlScene.GetNodeByID(node_id) if node_id else None
            if node:
                combo.setCurrentNode(node)
            else:
                combo.setCurrentNode(None)

    def onVisualize(self):
        self.runWorkflow(visualize=True)

    def onApply(self):
        self.runWorkflow(visualize=False)

    def showJobs(self):
        msg = qt.QMessageBox()
        msg.setIcon(qt.QMessageBox.Warning)
        msg.setText("Your job was successfully scheduled on cluster. Do you want to move to job monitor view?")
        msg.setWindowTitle("Show jobs")
        msg.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.No)
        msg.setDefaultButton(qt.QMessageBox.No)
        if msg.exec_() == qt.QMessageBox.Yes:
            slicer.modules.AppContextInstance.rightDrawer.show(1)

    def _confirmDiskSpaceUsage(self, selected_names, ds_factors):
        if len(selected_names) > 1 and 1 in ds_factors and self.saveWorkstepImageDataCheckbox.isChecked():
            msg = (
                "Saving workstep image data with a downsampling factor of 1 across multiple samples "
                "will consume a large amount of disk space.\n\nAre you sure you want to proceed?"
            )
            return slicer.util.confirmYesNoDisplay(msg, windowTitle="Disk Space Warning")
        return True

    def runWorkflow(self, visualize=False):
        if self.df is None:
            slicer.util.warningDisplay("Please load a CSV file first before proceeding.")
            return

        try:
            ds_factors = [float(x.strip()) for x in self.downsamplingFactorLineEdit.text.split(",") if x.strip()]
            if not ds_factors:
                raise ValueError
        except ValueError:
            slicer.util.warningDisplay("Please provide valid comma-separated numbers for downsampling factor(s).")
            return

        raw_text = self.selectedNamesText.toPlainText()
        selected_names = raw_text.replace(",", " ").replace(";", " ").split()

        if not selected_names:
            slicer.util.warningDisplay("Please select or paste at least one sample name.")
            return

        if not self._confirmDiskSpaceUsage(selected_names, ds_factors):
            return

        files_data = []
        for name in selected_names:
            phi_val = None
            resolved_name = name

            match = self.df[self.df["name"] == name]

            if match.empty and "name" in self.df.columns:
                mask = self.df["name"].apply(lambda x: os.path.splitext(str(x))[0] == name if pd.notna(x) else False)
                match_no_ext = self.df[mask]
                if not match_no_ext.empty:
                    match = match_no_ext
                    resolved_name = match.iloc[0]["name"]

            if not match.empty and "phi" in self.df.columns:
                val = match.iloc[0]["phi"]
                if not pd.isna(val) and val != "":
                    try:
                        phi_val = float(val)
                    except ValueError:
                        phi_val = None

            files_data.append({"name": resolved_name, "sample_phi": phi_val})

        prefix = self.outputFolderPrefixLine.text.strip()

        workflow_params = self.getParams(visualize=visualize, save_state=False)

        success = self.logic.process(self, files_data, prefix, workflow_params)

        if success:
            self.showJobs()

    def resetInputWidgetsStyle(self):
        pass

    def requireField(self, widget):
        widget.setStyleSheet("QWidget {background-color: #600000}")

    def unrequireField(self, widget):
        widget.setStyleSheet("")


class PoreNetworkRemoteWorkflowLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.handler = None

    def process(self, callback, files_data, prefix, workflow_params):
        self.handler = PoreNetworkRemoteWorkflowHandler(files_data, prefix, workflow_params)

        job_name = f"PNM Workflow: {prefix}"
        success = slicer.modules.RemoteServiceInstance.cli.run(
            self.handler, name=job_name, job_type="pnmworkflow", polling_enabled=True
        )
        return success
