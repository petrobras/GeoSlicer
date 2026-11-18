import itertools
import os
import re
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import ctk
import numpy as np
import pyqtgraph as pg
import qt
import slicer
import vtk

from commons.slicer import ui
from commons.slicer.node_attributes import NodeEnvironment
from commons.slicer.helpers import arrayFromSegmentBinaryLabelmap, getPythonQtWidget
from commons.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic

try:
    from Test.SpectralProfileTest import SpectralProfileTest
except ImportError:
    SpectralProfileTest = None  # tests not deployed to final version or closed source

SERIES_COLORS = [
    (31, 119, 180),
    (214, 39, 40),
    (44, 160, 44),
    (255, 127, 14),
    (148, 103, 189),
    (140, 86, 75),
    (227, 119, 194),
    (23, 190, 207),
]

HEATMAP_COLORMAP = "viridis"

# Acquisition range of the multi-energy scans: 160 kV on the first slice down to 20 kV on the last. Attenuation grows
# towards low energies, and the data grows with the slice index, which fits this order (and not the reverse).
DEFAULT_AXIS_LABEL = "Tube voltage (kV)"
DEFAULT_AXIS_FIRST = 160.0
DEFAULT_AXIS_LAST = 20.0

# Energy used to normalize the axis in the power-law model, so that `a` is the photoelectric term at this energy
POWER_LAW_REFERENCE_ENERGY = 100.0
DEFAULT_EXPONENT = -3.5
MIN_EXPONENT, MAX_EXPONENT = -10.0, -0.1
SELECTION_DELAY_MS = 250  # wait for the slider to stop before refitting
# Estimating the exponent b on the standards: the grid it is searched on, how many pixels are used at most, and what
# counts as a well constrained result
ESTIMATE_EXPONENT_RANGE = (-6.0, -1.0)
ESTIMATE_EXPONENT_STEP = 0.05
ESTIMATE_MAX_PIXELS = 20_000
ESTIMATE_FLAT_RATIO = 1.05  # the residual must grow by this much at 0.5 from the best b, or b is not well defined
ESTIMATE_PASSES = 2  # the standards are found with b, so after estimating it they are found again
MIN_ENERGIES = 3  # the model has three degrees of freedom once the exponent is fixed plus the noise estimate

# Calibration with standards. Atomic number and standard atomic weight of the elements that appear in rocks and in
# the usual standards (a formula with any other element is rejected).
ATOMIC_DATA = {
    "H": (1, 1.008), "He": (2, 4.0026), "Li": (3, 6.94), "Be": (4, 9.0122), "B": (5, 10.81), "C": (6, 12.011),
    "N": (7, 14.007), "O": (8, 15.999), "F": (9, 18.998), "Ne": (10, 20.180), "Na": (11, 22.990),
    "Mg": (12, 24.305), "Al": (13, 26.982), "Si": (14, 28.085), "P": (15, 30.974), "S": (16, 32.06),
    "Cl": (17, 35.45), "Ar": (18, 39.948), "K": (19, 39.098), "Ca": (20, 40.078), "Ti": (22, 47.867),
    "V": (23, 50.942), "Cr": (24, 51.996), "Mn": (25, 54.938), "Fe": (26, 55.845), "Co": (27, 58.933),
    "Ni": (28, 58.693), "Cu": (29, 63.546), "Zn": (30, 65.38), "Br": (35, 79.904), "Sr": (38, 87.62),
    "Zr": (40, 91.224), "Mo": (42, 95.95), "Ag": (47, 107.87), "Sn": (50, 118.71), "Ba": (56, 137.33),
    "W": (74, 183.84), "Pb": (82, 207.2),
}  # fmt: skip
MINERAL_Z_OVER_A = 0.4995  # Z/A of the common rock-forming minerals, to turn the electron density into a density
DEFAULT_Z_EXPONENT = 2.94  # exponent n of  a / c = K * sum(f_i * Z_i ** n)  when it is not fitted (Mayneord's)
STANDARD_BORDER_PIXELS = 3  # pixels dropped around each standard, where the material mixes with its surroundings
MIN_STANDARD_PIXELS = 20
# The standards of the scans, always the same: (name, formula, density in g/cm3, rank of the attenuation at low
# energy). They are found by clustering the pixels outside the SOI, whatever their shape, and each one is told
# apart by its pattern: the electron density sets c and the Zeff sets a / c, both known up to a scale.
PRESET_STANDARDS = [
    ("Teflon", "C2F4", 2.2, 0),
    ("Aluminum", "Al", 2.70, 2),
    ("Fused quartz", "SiO2", 2.2, 1),  # silica glass, not the crystal (2.65 g/cm3)
]
MIN_STANDARD_AREA = 100  # pixels; smaller specks of a cluster outside the SOI are dropped
FIT_Z_EXPONENT_RANGE = (1.5, 6.0)  # range the exponent n of Zeff is fitted in; a fit at an end is not trusted
Z_EXPONENT_LIMIT_MARGIN = 0.02
POINT_OFF_LINE = 0.08  # relative distance of a standard to the calibration line above which it is marked
MERGE_DISTANCE = 2.0  # a leftover cluster this close (in standard deviations) to a standard is a piece of it
STANDARD_EXTRA_CLUSTERS = 2  # clusters outside the SOI beyond the standards: the holder, mixed pixels at borders...
RESULT_COLUMNS = [  # (title, tooltip) of the table of the minerals
    ("Class", "Cluster or segment (the color is the one of its segment)"),
    ("Pixels (%)", "Share of the classified pixels"),
    ("Electron density (mol/cm3)", "Moles of electrons per cm3 (c divided by the calibration constant beta)"),
    ("Zeff", "Effective atomic number, from the ratio a / c and the calibration"),
    ("Bulk density (g/cm3)", "Electron density divided by Z/A = 0.4995: an estimate, not a measurement"),
    (
        "Mineral",
        "Mineral of this class. It starts as the reference mineral with the closest Zeff and density (Pores when "
        "there is no attenuation); change it if you know better, then name the segments after the minerals",
    ),
]
MINERAL_COLUMN_MIN_WIDTH = 150  # pixels of the column with the choice of the mineral, which takes the free width
DEFAULT_MIN_CONFIDENCE = 90  # percent: pixels the clustering is less sure about are left out
CALIBRATION_BOOTSTRAP = 300
CALIBRATION_BOOTSTRAP_PIXELS = 20_000
# Reference minerals to name the classes (formula, density in g/cm3). The suggestion keeps the ones whose Zeff is
# close to the class and picks, among them, the one with the closest density (calcite, aragonite and anhydrite have
# nearly the same Zeff and differ in density).
REFERENCE_MINERALS = {
    "Quartz": ("SiO2", 2.65),
    "Calcite": ("CaCO3", 2.71),
    "Aragonite": ("CaCO3", 2.93),
    "Dolomite": ("CaMg(CO3)2", 2.85),
    "Ankerite": ("Ca(Mg0.5Fe0.5)(CO3)2", 3.05),
    "Siderite": ("FeCO3", 3.96),
    "Anhydrite": ("CaSO4", 2.97),
    "Gypsum": ("CaSO4(H2O)2", 2.31),
    "Pyrite": ("FeS2", 5.0),
}
GAUSSIANS_ATTRIBUTE = "SpectralProfile.Gaussians"  # Gaussians of a segmentation, kept on its node
PROPERTIES_REFERENCE = "SpectralProfile.Properties"  # the table of a segmentation, referenced from its node
PORES = "Pores"  # first choice of the mineral column: the class with no (or very little) attenuation
PORE_DENSITY_LIMIT = 0.8  # g/cm3: a class below this bulk density is suggested as pores
NO_MINERAL = "-"  # last choice: leaves the name of the segment as it is
MINERAL_CHOICES = [PORES] + list(REFERENCE_MINERALS) + [NO_MINERAL]
MINERAL_MATCH_TOLERANCE = 0.10  # relative difference of Zeff above which no mineral is suggested

HISTOGRAM_BINS = 256
PARAM_BINS = 200
CLUSTER_FIT_SAMPLES = 50_000
# (label, key) of the clustering methods. The hierarchical ones need the distances between all the pixels, so they
# are run on a smaller sample; every method ends as one Gaussian per cluster (its mean and covariance), which is what
# the plot shows, lets you edit and classifies the pixels.
CLUSTER_METHODS = [
    ("Gaussian mixture", "gmm"),
    ("K-means", "kmeans"),
    ("Hierarchical (Ward)", "ward"),
    ("Hierarchical (average)", "average"),
    ("Hierarchical (complete)", "complete"),
]
HIERARCHICAL_SAMPLES = 4000

# Stability check: how much each perturbation moves the inputs of the clustering
STABILITY_EXPONENT_STEP = 0.2
STABILITY_DROPPED_FRACTION = 0.1
STABILITY_SEEDS = (1, 2, 3)
STABILITY_DROP_RUNS = 3
STABILITY_TARGET_PIXELS = 150_000


# 3D multi-energy volumes (e.g. dual energy) are too big to be held as float: they are processed in blocks of voxels
# whose working arrays take about DUAL_BYTES_BASE + DUAL_BYTES_PER_CLUSTER * clusters bytes per voxel (the measured
# values, the fitted (c, a), the features, and the probabilities of each cluster with their temporaries)
DUAL_BYTES_BASE = 100
DUAL_BYTES_PER_CLUSTER = 40
# Memory of the working arrays of the 3D segmentation. The volume is read in slabs of slices (and each slab in blocks
# of voxels) that fit in it, so nothing the size of a volume is created besides the result (one byte per voxel): 2 GB
# are 130 slices of a 600 x 600 scan and 5 slices of a 3000 x 3000 one, and more only makes it a little faster.
DUAL_WORKING_MEMORY_GB = 2.0
AUTO_REFERENCE_SLICES = 21  # slices around the slice of the multi-energy scan that the automatic references cover
AUTO_REFERENCE_MIN_PIXELS = 100  # pixels a reference needs in the volumes to be taken
DUAL_COMPACT_SPREAD = 0.12  # relative spread of the gray of a region outside the SOI that can be a standard or the air
AUTO_REFERENCE_SPREAD = 3.0  # robust standard deviations from the median gray a pixel may be to stay in a reference
DUAL_REFERENCE_SAMPLES = 2_000_000  # voxels of a reference (standard or air) read to measure its gray value
DUAL_AIR_NAMES = ("air", "ar", "background")  # names of the segment of the reference with no attenuation
DUAL_RESIDUAL_LIMIT = 0.05  # relative distance of a reference to the scale calibration above which it is flagged
# Dual energy learned from the multi-energy slice: the cross section scanned with many energies is also a slice of
# the 3D volumes, so its classes are the training data of a classifier in the plane of the two gray values
SUPERVISED_BORDER = (
    3  # pixels of the multi-energy slice dropped around each class (where classes mix and slices differ)
)
SUPERVISED_MIN_SAMPLES = 200  # voxels a class needs to be learned
SUPERVISED_SLICES = 1  # slices on each side of the registered one that are also sampled
SUPERVISED_TRIM = (
    3.5  # standard deviations beyond which a voxel of a class is an outlier (a saturated grain, a mixed voxel)
)
SUPERVISED_TRIM_PASSES = 4
SUPERVISED_VARIANCE_FLOOR = 1e-3  # fraction of the variance added to the diagonal of each covariance
SUPERVISED_SMOOTHING = 1.0  # sigma (voxels) of the Gaussian filter of the volumes before classifying
SUPERVISED_BYTES_PER_VOXEL = 40  # of the float arrays of a slab of the volumes: inputs, filtered and their temporaries
REGISTRATION_STEP_MM = 0.4  # distance between the slices tried when looking for the slice of the reference
REGISTRATION_SEARCH_SHRINK = 0.5  # the search of the slice runs on images shrunk by this factor
REGISTRATION_REFINE_PIXELS = 6  # the position is refined this far (reference pixels) around the one of the search
REGISTRATION_SCORE_LIMIT = 0.4  # correlation below which the slices are probably not the same cross section
DUAL_HISTOGRAM_BINS = 256
DUAL_HISTOGRAM_SLICES = 60  # slices of the range that the histogram reads, evenly spaced
DUAL_REFERENCES_NAME = "dual_standards"  # the references that the Auto button makes
DUAL_SPECTRAL_NAME = "dual_multienergy_calib"  # the result of the classes of the multi-energy scan
DUAL_CLUSTER_NAME = "dual_cluster_classes"  # the result of the clusters, followed by their number
DUAL_METHODS = [("Classes of the multi-energy scan", "spectral"), ("Cluster the 3D volumes", "cluster")]
DUAL_DEFAULT_CLUSTERS = 4
DUAL_CLUSTER_SAMPLES = 200_000  # voxels the clusters are fitted on


class SpectralProfile(LTracePlugin):
    SETTING_KEY = "SpectralProfile"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Spectral Profile"
        self.parent.categories = ["Segmentation", "MicroCT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.setHelpUrl("Volumes/Segmentation/Segmentation.html#spectral-profile", NodeEnvironment.MICRO_CT)

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class SpectralProfileWidget(LTracePluginWidget):
    """Segments a multi-energy volume by clustering how the attenuation of each pixel varies with the energy.

    The z axis is treated as a spectral axis (energy / tube voltage), not as depth. Every pixel is described by two
    numbers, the coefficients of  attenuation = a * E ** b + c  (E in units of 100 kV) with the exponent b fixed, and the pixels are
    grouped with a Gaussian mixture in the (c, a) plane.
    """

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = SpectralProfileLogic()
        self._axis = None  # axis values of the current volume
        self._selection = None  # indices of the energies used by the fit, None when the selection is invalid
        self._axisKey = None
        self._shadeItems = []  # grey bands over the energies left out
        self._heatmap = None  # (counts [slices, bins], low, high) of the current volume
        self._heatmapKey = None
        self._background = None  # air value of each slice of the current volume
        self._soiMask = None  # 2D bool mask [j, i] of the SOI, None when no SOI is used
        self._params = None  # (a [j, i], c [j, i], valid [j, i]) of the current volume
        self._paramsKey = None
        self._clusters = None  # Gaussians of the last clustering
        self._clusterLabels = None  # [j, i] labels (1-based) of the last clustering
        self._properties = None  # properties of each class (clusterProperties), for the table node
        self._clusterNode = None  # segmentation of the last clustering, refreshed when the Gaussians are edited
        self._calibration = None  # result of Logic.calibrate for the current volume, fit settings and energies
        self._standardsNode = None  # segmentation of the standards found by the last calibration
        self._clusterExponent = DEFAULT_EXPONENT
        self._dualCalibration = None  # calibration of the 3D volumes with the standards (see _dualDensityCalibration)
        self._sliceRegistration = None  # where the multi-energy slice is in the 3D volumes (see _registerDualSlice)

    def setup(self):
        LTracePluginWidget.setup(self)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.collapsed = False
        inputSection.text = "Input"

        self.inputSelector = ui.hierarchyVolumeInput(
            onChange=self._onVolumeChanged,
            hasNone=True,
            nodeTypes=["vtkMRMLScalarVolumeNode"],
        )
        self.inputSelector.setMRMLScene(slicer.mrmlScene)
        self.inputSelector.setToolTip("Volume whose z axis holds the different energies")
        self.inputSelector.objectName = "Input Selector"

        self.soiSelector = ui.hierarchyVolumeInput(
            onChange=self._onSoiChanged,
            hasNone=True,
            nodeTypes=["vtkMRMLSegmentationNode"],
        )
        self.soiSelector.setMRMLScene(slicer.mrmlScene)
        self.soiSelector.setToolTip(
            "Region of interest (optional): all the segments of the segmentation. Only the pixels inside it are "
            "analyzed, so calibration cylinders, the holder and the air can be left out."
        )
        self.soiSelector.objectName = "SOI Selector"

        self.soiStatusLabel = qt.QLabel("")
        self.soiStatusLabel.setWordWrap(True)

        inputLayout = qt.QFormLayout(inputSection)
        inputLayout.addRow("Volume:", self.inputSelector)
        inputLayout.addRow("SOI:", self.soiSelector)
        inputLayout.addRow(self.soiStatusLabel)

        # Axis section
        axisSection = ctk.ctkCollapsibleButton()
        axisSection.text = "Spectral axis"
        axisSection.collapsed = False

        self.axisLabelLineEdit = qt.QLineEdit(DEFAULT_AXIS_LABEL)
        self.axisLabelLineEdit.objectName = "Axis Label Line Edit"
        self.axisLabelLineEdit.editingFinished.connect(self._onAxisChanged)

        self.axisFirstSpinBox = self._makeAxisSpinBox("Axis First Spin Box", DEFAULT_AXIS_FIRST)
        self.axisFirstSpinBox.setToolTip("Axis value of the first z slice")
        self.axisLastSpinBox = self._makeAxisSpinBox("Axis Last Spin Box", DEFAULT_AXIS_LAST)
        self.axisLastSpinBox.setToolTip("Axis value of the last z slice. Intermediate slices are evenly spaced.")

        self.energiesRange = ctk.ctkRangeWidget()
        self.energiesRange.objectName = "Energies Range Widget"
        self.energiesRange.setDecimals(1)
        self.energiesRange.setToolTip(
            "Energies used by the fit: everything between the two handles. Leave out the noisy or saturated ends."
        )
        self.energiesRange.connect("valuesChanged(double,double)", self._onSelectionChanged)
        self._selectionTimer = qt.QTimer()
        self._selectionTimer.setSingleShot(True)
        self._selectionTimer.setInterval(SELECTION_DELAY_MS)
        self._selectionTimer.connect("timeout()", self._onSelectionSettled)

        self.energiesStatusLabel = qt.QLabel("")
        self.energiesStatusLabel.setWordWrap(True)

        axisLayout = qt.QFormLayout(axisSection)
        axisLayout.addRow("Axis label:", self.axisLabelLineEdit)
        axisLayout.addRow("First slice:", self.axisFirstSpinBox)
        axisLayout.addRow("Last slice:", self.axisLastSpinBox)
        self.energiesLabel = qt.QLabel("Energies used:")
        axisLayout.addRow(self.energiesLabel, self.energiesRange)
        axisLayout.addRow(self.energiesStatusLabel)

        # Attenuation of the pixels at each energy, with the fitted curve of each cluster on top. It sits in the
        # spectral axis section, next to the energies it shows and lets you choose.
        self._heatmapWidget = pg.PlotWidget()
        self._heatmapWidget.setBackground("w")
        self._heatmapWidget.setMinimumHeight(340)
        self._heatmapImage = pg.ImageItem()
        self._heatmapWidget.addItem(self._heatmapImage)
        self._legend = self._heatmapWidget.addLegend(
            offset=(-10, 10), labelTextColor="w", brush=pg.mkBrush(0, 0, 0, 120)
        )
        self._colorBar = pg.ColorBarItem(
            values=(0, 1), colorMap=pg.colormap.get(HEATMAP_COLORMAP), interactive=False, label="log pixels"
        )
        self._colorBar.setImageItem(self._heatmapImage, insert_in=self._heatmapWidget.getPlotItem())
        self._heatmapWidget.getAxis("left").setLabel("Attenuation above air (gray value - air)")
        self.heatmapView = getPythonQtWidget(self._heatmapWidget)
        self.heatmapView.objectName = "Spectral Heatmap View"

        axisLayout.addRow(self.heatmapView)

        # Clustering section
        clusterSection = ctk.ctkCollapsibleButton()
        clusterSection.text = "Clustering"
        clusterSection.collapsed = True

        self.exponentSpinBox = qt.QDoubleSpinBox()
        self.exponentSpinBox.objectName = "Exponent Spin Box"
        self.exponentSpinBox.setRange(MIN_EXPONENT, MAX_EXPONENT)
        self.exponentSpinBox.setDecimals(2)
        self.exponentSpinBox.setSingleStep(0.1)
        self.exponentSpinBox.setValue(DEFAULT_EXPONENT)
        self.exponentSpinBox.setToolTip(
            "<b>Energy exponent b</b> of the model fitted to every pixel:<br>"
            "attenuation = a &middot; E<sup>b</sup> + c<br>"
            "(E in units of 100 kV, so that a and c have similar sizes)<br><br>"
            "<b>a</b>: photoelectric term. It falls fast with the energy and is larger for denser materials and "
            "for heavier elements.<br>"
            "<b>c</b>: energy independent term, mostly Compton scattering. It follows the density.<br><br>"
            "Photoelectric absorption goes with E<sup>-3</sup> to E<sup>-3.5</sup>, so b is usually between -3 and "
            "-3.5. The axis may be tube voltage instead of photon energy, which can move the best value: check that "
            "the cluster curves follow the histogram.<br>"
            "Changing b rescales a and c and reshapes the clouds of the (c, a) plot."
        )
        self.exponentSpinBox.editingFinished.connect(self._onFitParametersChanged)
        self.exponentSpinBox.editingFinished.connect(self._updateDefaultName)
        axisLayout.addRow(
            "Exponent b:", self.exponentSpinBox
        )  # the energy dependence of the model, for all that follows

        self.clustersSpinBox = qt.QSpinBox()
        self.clustersSpinBox.objectName = "Clusters Spin Box"
        self.clustersSpinBox.setRange(2, 16)
        self.clustersSpinBox.setValue(4)
        self.clustersSpinBox.setToolTip("Number of Gaussians of the mixture fitted to the (c, a) cloud")
        self.clustersSpinBox.valueChanged.connect(self._updateDefaultName)
        self.methodSelector = qt.QComboBox()
        self.methodSelector.objectName = "Cluster Method Combo Box"
        for label, key in CLUSTER_METHODS:
            self.methodSelector.addItem(label, key)
        self.methodSelector.setToolTip(
            "How the (c, a) cloud is split. Each cluster ends as a Gaussian that you can edit on the plot. "
            "Hierarchical methods use a sample of the pixels."
        )

        self.confidenceSpinBox = qt.QSpinBox()
        self.confidenceSpinBox.objectName = "Confidence Spin Box"
        self.confidenceSpinBox.setRange(0, 99)
        self.confidenceSpinBox.setSuffix(" %")
        self.confidenceSpinBox.setValue(DEFAULT_MIN_CONFIDENCE)
        self.confidenceSpinBox.setToolTip(
            "Pixels whose most probable cluster has a probability below this are the undecided ones (between two "
            "clusters, or far from all) and are left out, both in the clustering of the sample and in the one that "
            "finds the standards. It removes mixed borders and most of the ring artifacts. 0 keeps every pixel."
        )

        self.adjustSelector = ui.hierarchyVolumeInput(
            onChange=self._onAdjustSegmentationChanged,
            hasNone=True,
            nodeTypes=["vtkMRMLSegmentationNode"],
        )
        self.adjustSelector.setMRMLScene(slicer.mrmlScene)
        self.adjustSelector.setToolTip(
            "The segmentation you are working on. Empty: the result of the next clustering. Choose a previous result "
            "of this module (or any segmentation of this volume) and each of its segments becomes a Gaussian on the "
            "plot, which you edit, and the segmentation is updated when you release a handle. The same classes are "
            "the ones the mineral table below (section Minerals) works on."
        )
        self.adjustSelector.objectName = "Adjust Segmentation Selector"

        self.outputNameLineEdit = qt.QLineEdit()
        self.outputNameLineEdit.objectName = "Output Name Line Edit"
        self.outputNameLineEdit.setPlaceholderText("")

        self._paramWidget = pg.PlotWidget()
        self._paramWidget.setBackground("w")
        self._paramWidget.setMinimumHeight(320)
        self._paramWidget.getAxis("bottom").setLabel("c  (energy independent term)")
        self._paramWidget.getAxis("left").setLabel("a  (photoelectric term)")
        self._paramImage = pg.ImageItem()
        self._paramWidget.addItem(self._paramImage)
        self._paramBar = pg.ColorBarItem(
            values=(0, 1), colorMap=pg.colormap.get(HEATMAP_COLORMAP), interactive=False, label="log pixels"
        )
        self._paramBar.setImageItem(self._paramImage, insert_in=self._paramWidget.getPlotItem())
        self.paramView = getPythonQtWidget(self._paramWidget)
        self.paramView.objectName = "Power Law Parameters View"

        self.clusterButton = qt.QPushButton("Cluster and segment")
        self.clusterButton.objectName = "Cluster Button"
        self.clusterButton.setToolTip("Fit a Gaussian mixture to the (c, a) cloud and create one segment per cluster")
        self.clusterButton.clicked.connect(self._onClusterClicked)

        self.stabilityButton = qt.QPushButton("Check stability")
        self.stabilityButton.objectName = "Stability Button"
        self.stabilityButton.setToolTip(
            "Repeat the clustering with small changes (another random start, exponent +-0.2, 10% of the energies "
            "left out) and measure how many pixels keep their cluster. Also creates a map of that agreement."
        )
        self.stabilityButton.clicked.connect(self._onStabilityClicked)

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.addWidget(self.clusterButton)
        buttonsLayout.addWidget(self.stabilityButton)

        self.clusterStatusLabel = qt.QLabel("")
        self.clusterStatusLabel.setWordWrap(True)
        self.clusterStatusLabel.setTextFormat(qt.Qt.RichText)

        clusterLayout = qt.QFormLayout(clusterSection)
        self.methodSelector.currentIndexChanged.connect(self._updateDefaultName)
        clusterLayout.addRow("Method:", self.methodSelector)
        clusterLayout.addRow("Clusters:", self.clustersSpinBox)
        clusterLayout.addRow("Minimum confidence:", self.confidenceSpinBox)
        clusterLayout.addRow("Work on segmentation:", self.adjustSelector)
        clusterLayout.addRow("Output name:", self.outputNameLineEdit)
        clusterLayout.addRow(self.paramView)
        clusterLayout.addRow(buttonsLayout)
        clusterLayout.addRow(self.clusterStatusLabel)

        self._updateDefaultName()
        # Calibration section: turn the (c, a) of the clusters into electron density, Zeff and density
        calibrationSection = ctk.ctkCollapsibleButton()
        calibrationSection.text = "Calibration with standards (optional)"
        calibrationSection.collapsed = True

        self.standardsSelector = ui.hierarchyVolumeInput(
            onChange=self._onStandardsChanged,
            hasNone=True,
            nodeTypes=["vtkMRMLSegmentationNode"],
        )
        self.standardsSelector.setMRMLScene(slicer.mrmlScene)
        self.standardsSelector.setToolTip(
            "Optional. By default the standards are found automatically: the pixels outside the SOI (and not air) are "
            "clustered by how their attenuation varies with the energy, and the clusters that fit the standards of the "
            "table are taken. To use your own, choose a segmentation with one segment per standard."
        )
        self.standardsSelector.objectName = "Standards Selector"

        self.standardsTable = qt.QTableWidget()
        self.standardsTable.objectName = "Standards Table"
        self.standardsTable.setColumnCount(3)
        self.standardsTable.setHorizontalHeaderLabels(["Standard", "Formula", "Density (g/cm3)"])
        self.standardsTable.verticalHeader().setVisible(False)
        self.standardsTable.setRowCount(len(PRESET_STANDARDS))
        for row, (name, formula, density, _) in enumerate(PRESET_STANDARDS):
            nameItem = qt.QTableWidgetItem(name)
            nameItem.setFlags(nameItem.flags() & ~qt.Qt.ItemIsEditable)
            self.standardsTable.setItem(row, 0, nameItem)
            self.standardsTable.setItem(row, 1, qt.QTableWidgetItem(formula))
            self.standardsTable.setItem(row, 2, qt.QTableWidgetItem(f"{density:g}"))
        self.standardsTable.resizeColumnsToContents()
        self.standardsTable.verticalHeader().setDefaultSectionSize(22)
        self.standardsTable.setFixedHeight(22 * (len(PRESET_STANDARDS) + 1) + 6)
        self.standardsTable.setVerticalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        self.standardsTable.horizontalHeaderItem(2).setToolTip("Density measured on the cylinder (porosity changes it)")
        self.standardsTable.setToolTip(
            "Formula and measured density of each standard. Clear a row to leave that standard out. The formula "
            "gives the composition the calibration needs (electron density and Zeff)."
        )

        self.calibrateButton = qt.QPushButton("Calibrate")
        self.calibrateButton.objectName = "Calibrate Button"
        self.calibrateButton.setToolTip(
            "Finds the standards outside the SOI, optionally estimates b, and fits the two constants that turn c into "
            "electron density and a / c into Zeff. The plots show how the standards fall on the calibration."
        )
        self.calibrateButton.clicked.connect(self._onCalibrateClicked)

        self.estimateExponentCheckBox = qt.QCheckBox("Estimate b")
        self.estimateExponentCheckBox.objectName = "Estimate Exponent Check Box"
        self.estimateExponentCheckBox.setChecked(True)
        self.estimateExponentCheckBox.setToolTip(
            "Also look for the exponent b that makes the power law fit the spectra of the standards best, and set it "
            "in Exponent b. Uncheck it to calibrate with the b you typed."
        )

        self._calibrationPlotC = self._makeCalibrationPlot("Electron density (known)", "c (measured)")
        self._calibrationPlotZ = self._makeCalibrationPlot("Zeff (known)", "a / c (measured)")
        self.calibrationPlotsView = [
            getPythonQtWidget(self._calibrationPlotC),
            getPythonQtWidget(self._calibrationPlotZ),
        ]
        for view, name in zip(self.calibrationPlotsView, ("Electron density", "Zeff")):
            view.objectName = f"Calibration Plot {name}"

        self.calibrationStatusLabel = qt.QLabel("")
        self.calibrationStatusLabel.setWordWrap(True)
        self.calibrationStatusLabel.setTextFormat(qt.Qt.RichText)

        # Minerals section: tells what each class is and names the segments after it
        # a plain "Advanced" part of the clustering (an arrow and the text, no frame): what each class is
        self.mineralsToggle = qt.QToolButton()
        self.mineralsToggle.objectName = "Minerals Toggle"
        self.mineralsToggle.setText("Advanced: minerals of the classes")
        self.mineralsToggle.setCheckable(True)
        self.mineralsToggle.setAutoRaise(True)
        self.mineralsToggle.setStyleSheet("QToolButton { border: none; }")  # no box, even when it is open
        self.mineralsToggle.setToolButtonStyle(qt.Qt.ToolButtonTextBesideIcon)
        self.mineralsToggle.setArrowType(qt.Qt.RightArrow)
        mineralSection = qt.QWidget()
        mineralSection.setVisible(False)

        def toggleMinerals(checked: bool) -> None:
            mineralSection.setVisible(checked)
            self.mineralsToggle.setArrowType(qt.Qt.DownArrow if checked else qt.Qt.RightArrow)

        self.mineralsToggle.toggled.connect(toggleMinerals)

        self.resultsTable = qt.QTableWidget()
        self.resultsTable.objectName = "Cluster Properties Table"
        self.resultsTable.setColumnCount(len(RESULT_COLUMNS))
        self.resultsTable.setHorizontalHeaderLabels([title for title, _ in RESULT_COLUMNS])
        for column, (_, tip) in enumerate(RESULT_COLUMNS):
            self.resultsTable.horizontalHeaderItem(column).setToolTip(tip)
        self.resultsTable.verticalHeader().setVisible(False)
        self.resultsTable.horizontalHeader().setStretchLastSection(False)
        self.resultsTable.horizontalHeader().setSectionResizeMode(len(RESULT_COLUMNS) - 1, qt.QHeaderView.Stretch)
        self.resultsTable.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        self.resultsTable.setMinimumHeight(170)
        self._mineralCombos = []

        self.applyMineralsButton = qt.QPushButton("Name the segments after the minerals")
        self.applyMineralsButton.objectName = "Apply Minerals Button"
        self.applyMineralsButton.setToolTip(
            "Renames each segment of the segmentation you work on with the mineral chosen for its class. Repeated "
            "minerals are numbered. Classes left at - keep their name."
        )
        self.applyMineralsButton.clicked.connect(self._onApplyMineralsClicked)

        mineralLayout = qt.QVBoxLayout(mineralSection)
        mineralLayout.setContentsMargins(0, 0, 0, 0)
        mineralLayout.addWidget(self.resultsTable)
        mineralLayout.addWidget(self.applyMineralsButton)
        clusterLayout.addRow(self.mineralsToggle)
        clusterLayout.addRow(mineralSection)

        calibrationLayout = qt.QFormLayout(calibrationSection)
        calibrationLayout.addRow("Standards segmentation (optional):", self.standardsSelector)
        calibrationLayout.addRow(self.standardsTable)
        buttonsRow = qt.QHBoxLayout()
        buttonsRow.addWidget(self.calibrateButton, 1)
        buttonsRow.addWidget(self.estimateExponentCheckBox)
        calibrationLayout.addRow(buttonsRow)
        plotsRow = qt.QHBoxLayout()
        for view in self.calibrationPlotsView:
            plotsRow.addWidget(view)
        calibrationLayout.addRow(plotsRow)
        calibrationLayout.addRow(self.calibrationStatusLabel)

        # Dual energy section: classify 3D volumes (one per energy) with the Gaussians of the clustering above
        dualSection = ctk.ctkCollapsibleButton()
        dualSection.text = "Dual energy 3D"
        dualSection.collapsed = True

        def volumeSelector(name: str, tip: str):
            selector = ui.hierarchyVolumeInput(
                onChange=self._onDualInputsChanged, hasNone=True, nodeTypes=["vtkMRMLScalarVolumeNode"]
            )
            selector.setMRMLScene(slicer.mrmlScene)
            selector.setToolTip(tip)
            selector.objectName = name
            return selector

        self.dualGaussiansSelector = ui.hierarchyVolumeInput(
            onChange=self._onDualInputsChanged, hasNone=True, nodeTypes=["vtkMRMLSegmentationNode"]
        )
        self.dualGaussiansSelector.setMRMLScene(slicer.mrmlScene)
        self.dualGaussiansSelector.setToolTip(
            "Segmentation made by the clustering of this module (or adjusted by it) on the multi-energy scan. Its "
            "Gaussians in the (c, a) plane, its exponent b and its segment names and colors are used for the 3D "
            "volumes, so they must come from the same scanner, energies, filtration and gray value scale."
        )
        self.dualGaussiansSelector.objectName = "Dual Gaussians Selector"
        self.dualMethodSelector = qt.QComboBox()
        self.dualMethodSelector.objectName = "Dual Method Combo Box"
        for label, key in DUAL_METHODS:
            self.dualMethodSelector.addItem(label, key)
        self.dualMethodSelector.setToolTip(
            "<b>Classes of the multi-energy scan</b>: the classes of the segmentation chosen below are found in the "
            "volumes (through the slice of that scan) and measured there; every voxel goes to the nearest.<br><br>"
            "<b>Cluster the 3D volumes</b>: no multi-energy scan: the voxels of the volumes (inside the SOI) are grouped "
            "by their two gray values into as many clusters as you choose. With the References (standards) each "
            "cluster is named after the mineral that its density and Zeff suggest."
        )
        self.dualMethodSelector.currentIndexChanged.connect(self._onDualMethodChanged)
        self.dualClustersSpinBox = qt.QSpinBox()
        self.dualClustersSpinBox.objectName = "Dual Clusters Spin Box"
        self.dualClustersSpinBox.setRange(2, 12)
        self.dualClustersSpinBox.setValue(DUAL_DEFAULT_CLUSTERS)
        self.dualClustersSpinBox.setToolTip(
            "Number of groups of voxels. Include the pores, and the mixed voxels of the borders usually take a group "
            "of their own: one more than the minerals you expect is a good start."
        )
        self.dualClustersSpinBox.valueChanged.connect(self._onDualInputsChanged)
        self.dualSoiSelector = ui.hierarchyVolumeInput(
            onChange=self._onDualInputsChanged, hasNone=True, nodeTypes=["vtkMRMLSegmentationNode"]
        )
        self.dualSoiSelector.setMRMLScene(slicer.mrmlScene)
        self.dualSoiSelector.setToolTip(
            "Region of the 3D volumes that is segmented (and shown in the histogram): the segments of this "
            "segmentation, together, wherever they are in the volumes (any slice, any shape). Without one, it is the "
            "SOI of the Input section, which is of the multi-energy slice and is repeated in every slice, or the whole "
            "volume when there is none."
        )
        self.dualSoiSelector.objectName = "Dual SOI Selector"
        self.dualLowSelector = volumeSelector("Dual Low Energy Selector", "3D volume of the first energy")
        self.dualHighSelector = volumeSelector("Dual High Energy Selector", "3D volume of the second energy")

        self.dualConfidenceSpinBox = qt.QSpinBox()
        self.dualConfidenceSpinBox.objectName = "Dual Confidence Spin Box"
        self.dualConfidenceSpinBox.setRange(0, 99)
        self.dualConfidenceSpinBox.setSuffix(" %")
        self.dualConfidenceSpinBox.setValue(0)  # every voxel gets the nearest class; raise it to leave the doubtful out
        self.dualConfidenceSpinBox.setToolTip(
            "Voxels whose most probable class has a probability below this are left out (label 0)"
        )

        self.dualReferenceSelector = ui.hierarchyVolumeInput(
            onChange=self._onDualInputsChanged, hasNone=True, nodeTypes=["vtkMRMLSegmentationNode"]
        )
        self.dualReferenceSelector.setMRMLScene(slicer.mrmlScene)
        self.dualReferenceSelector.setToolTip(
            "Only for the histogram, which shows c and a: the references that put the gray values of the volumes on "
            "the scale of the multi-energy scan. One segment, on the grid of the 3D volumes, for each standard of the "
            "calibration, named as in the table of the Calibration section (Teflon, Aluminum, Fused quartz), "
            "optionally one named Air. The energies above are those of the volumes; the effective ones are found from "
            "the references. The segmentation does not use any of this."
        )
        self.dualReferenceSelector.objectName = "Dual Reference Selector"
        self.dualAutoReferencesButton = qt.QPushButton("Auto")
        self.dualAutoReferencesButton.objectName = "Dual Auto References Button"
        self.dualAutoReferencesButton.setToolTip(
            "Finds the standards and the air in the volumes, outside the Region (SOI), and creates the references "
            "segmentation. It looks for uniform regions of the gray of the two volumes: the air is the darkest, and the "
            "standards are the ones, in order of attenuation, that make the volumes fit the density and Zeff of the "
            "standards (table of the Calibration section). Check them on the image: it is a guess."
        )
        self.dualAutoReferencesButton.clicked.connect(self._onDualAutoReferencesClicked)
        self.dualWorkingMemoryGB = DUAL_WORKING_MEMORY_GB  # an attribute so that a test can make the slabs small
        self.dualOutputNameLineEdit = qt.QLineEdit()
        self.dualOutputNameLineEdit.objectName = "Dual Output Name Line Edit"
        self.dualProgressLabel = qt.QLabel("")
        self.dualProgressBar = qt.QProgressBar()
        self.dualProgressBar.objectName = "Dual Progress Bar"
        self.dualProgressBar.setRange(0, 100)
        self.dualCancelButton = qt.QPushButton("Cancel")
        self.dualCancelButton.objectName = "Dual Cancel Button"
        self.dualCancelButton.clicked.connect(self._onDualCancelClicked)
        self.dualProgressWidget = qt.QWidget()
        progressLayout = qt.QHBoxLayout(self.dualProgressWidget)
        progressLayout.setContentsMargins(0, 0, 0, 0)
        progressLayout.addWidget(self.dualProgressLabel)
        progressLayout.addWidget(self.dualProgressBar, 1)
        progressLayout.addWidget(self.dualCancelButton)
        self.dualProgressWidget.setVisible(False)
        self._dualCancelled = False

        self._dualHistogramPlot = pg.PlotWidget()
        self._dualHistogramPlot.setBackground("w")
        self._dualHistogramPlot.setMinimumHeight(320)
        self._dualHistogramImage = pg.ImageItem()
        self._dualHistogramPlot.addItem(self._dualHistogramImage)
        self._dualHistogramLegend = self._dualHistogramPlot.addLegend(
            offset=(-10, 10), labelTextColor="w", brush=pg.mkBrush(0, 0, 0, 120)
        )
        self.dualHistogramView = getPythonQtWidget(self._dualHistogramPlot)
        self.dualHistogramView.objectName = "Dual Histogram View"
        self.dualHistogramView.setVisible(False)
        self.dualHistogramButton = qt.QPushButton("Show the histogram")
        self.dualHistogramButton.objectName = "Dual Histogram Button"
        self.dualHistogramButton.setToolTip(
            "Histogram of c (energy independent term) and a (photoelectric term) of the voxels of the volumes inside the "
            "SOI and the slices chosen, smoothed as they are segmented, converted with the calibration of the volumes "
            "(the standards). Each class is an ellipse around the voxels the multi-energy slice says are of it. Choose "
            "a SOI or a range of slices to see only a part of the volumes."
        )
        self.dualHistogramButton.clicked.connect(self._onDualHistogramClicked)

        self.dualButton = qt.QPushButton("Segment the 3D volumes")
        self.dualButton.objectName = "Dual Segment Button"
        self.dualButton.setToolTip(
            "Classify every voxel of the volumes and create a segmentation with one segment per class"
        )
        self.dualButton.clicked.connect(self._onDualClicked)
        self.dualStatusLabel = qt.QLabel("")
        self.dualStatusLabel.setWordWrap(True)
        self.dualStatusLabel.setTextFormat(qt.Qt.RichText)

        dualLayout = qt.QFormLayout(dualSection)
        dualLayout.addRow("Method:", self.dualMethodSelector)
        dualLayout.addRow("Classes from segmentation:", self.dualGaussiansSelector)
        dualLayout.addRow("Clusters:", self.dualClustersSpinBox)
        dualLayout.addRow("First energy volume:", self.dualLowSelector)
        dualLayout.addRow("Second energy volume:", self.dualHighSelector)
        dualLayout.addRow("Region (SOI):", self.dualSoiSelector)
        referencesRow = qt.QHBoxLayout()
        referencesRow.addWidget(self.dualReferenceSelector, 1)
        referencesRow.addWidget(self.dualAutoReferencesButton)
        dualLayout.addRow("References (standards, air):", referencesRow)
        dualLayout.addRow("Minimum confidence:", self.dualConfidenceSpinBox)
        dualLayout.addRow(self.dualHistogramButton)
        dualLayout.addRow(self.dualHistogramView)
        dualLayout.addRow("Output name:", self.dualOutputNameLineEdit)
        dualLayout.addRow(self.dualButton)
        dualLayout.addRow(self.dualProgressWidget)
        dualLayout.addRow(self.dualStatusLabel)
        # the classes of the spectral scan, or the number of clusters, according to the method
        self._dualMethodRows = {
            "spectral": [dualLayout.labelForField(self.dualGaussiansSelector), self.dualGaussiansSelector],
            "cluster": [dualLayout.labelForField(self.dualClustersSpinBox), self.dualClustersSpinBox],
        }
        self._onDualMethodChanged()

        self.layout.addWidget(inputSection)
        self.layout.addWidget(axisSection)
        self.layout.addWidget(calibrationSection)  # before the clustering: it can estimate the exponent b
        self.layout.addWidget(clusterSection)
        self.layout.addWidget(dualSection)
        self.layout.addStretch(1)

        self._refresh()

    @staticmethod
    def _makeCalibrationPlot(xLabel: str, yLabel: str) -> pg.PlotWidget:
        plot = pg.PlotWidget()
        plot.setBackground("w")
        plot.setMinimumHeight(260)
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.getAxis("bottom").setLabel(xLabel)
        plot.getAxis("left").setLabel(yLabel)
        return plot

    def _makeAxisSpinBox(self, name: str, value: float) -> qt.QDoubleSpinBox:
        spinBox = qt.QDoubleSpinBox()
        spinBox.objectName = name
        spinBox.setRange(-1e9, 1e9)
        spinBox.setDecimals(4)
        spinBox.setValue(value)
        spinBox.valueChanged.connect(self._onAxisSpinBoxChanged)
        return spinBox

    # ----- axis and energy selection -----
    def _onAxisSpinBoxChanged(self, *args):
        self._onAxisChanged()

    def _axisValues(self, size: int) -> np.ndarray:
        """Axis value of each slice: evenly spaced from the first to the last."""
        return np.linspace(self.axisFirstSpinBox.value, self.axisLastSpinBox.value, size)

    def _onAxisChanged(self, *args):
        self._invalidateFit()
        self._refresh()

    def _onSelectionChanged(self, *args):
        """The slider moved: only the label and the grey bands follow it; the fit is redone once it is released."""
        self._updateSelection()
        self._updateShading()
        self._selectionTimer.start()

    def _onSelectionSettled(self):
        if qt.QApplication.mouseButtons() & qt.Qt.LeftButton:  # still dragging
            self._selectionTimer.start()
            return
        self._invalidateFit()
        self._updateParams()
        self._adoptSegmentation()
        self._updateParamPlot()
        self._updateHeatmapPlot()

    def _syncEnergiesRange(self):
        """Keep the slider on the axis; it goes back to the whole axis when the axis changes."""
        if self._axis is None:
            return
        low, high = float(self._axis.min()), float(self._axis.max())
        key = (float(self._axis[0]), float(self._axis[-1]), len(self._axis))
        self.energiesRange.blockSignals(True)
        self.energiesRange.setRange(low, high)
        step = abs(high - low) / max(len(self._axis) - 1, 1)
        self.energiesRange.singleStep = step
        if key != self._axisKey:
            self._axisKey = key
            self.energiesRange.setValues(low, high)
        self.energiesRange.blockSignals(False)
        self.energiesLabel.setText(f"Energies used ({self.axisLabelLineEdit.text or 'z'}):")

    def _updateSelection(self):
        """Select the energies between the two handles and report how many there are."""
        self._selection = None
        if self._axis is None:
            self.energiesStatusLabel.setText("")
            return
        selection = self.logic.selectEnergyRange(
            self._axis, self.energiesRange.minimumValue, self.energiesRange.maximumValue
        )
        if len(selection) < MIN_ENERGIES:
            self.energiesStatusLabel.setText(
                f"<span style='color:#c0392b'>Select at least {MIN_ENERGIES} energies (got {len(selection)}).</span>"
            )
            return
        self._selection = selection
        self.energiesStatusLabel.setText(f"{len(selection)} of {len(self._axis)} energies used.")

    # ----- volume and SOI -----
    def _onVolumeChanged(self, *args):
        self._updateDefaultName()
        self._heatmap = None
        self._invalidateFit()
        self._refresh()

    def _onSoiChanged(self, *args):
        self._heatmap = None
        self._invalidateFit()
        self._refresh()

    def _currentSoiMask(self, volumeNode) -> Optional[np.ndarray]:
        """2D mask of the SOI (all the segments of the selected segmentation), or None without a usable SOI."""
        node = self.soiSelector.currentNode()
        if node is None or volumeNode is None:
            self.soiStatusLabel.setText("")
            return None
        segmentation = node.GetSegmentation()
        segmentIds = [segmentation.GetNthSegmentID(n) for n in range(segmentation.GetNumberOfSegments())]
        mask = self.logic.soiMask(node, segmentIds, volumeNode)
        if mask is None or not mask.any():
            self.soiStatusLabel.setText("The selected SOI is empty (or could not be read), so it is being ignored.")
            return None
        self.soiStatusLabel.setText("")
        return mask

    def _defaultName(self) -> str:
        """<volume>_spectral_b<|exponent|>_classes<clusters>_<method>, e.g. microtom_spectral_b3_classes4_gmm."""
        volumeNode = self.inputSelector.currentNode()
        return self.logic.defaultOutputName(
            volumeNode.GetName() if volumeNode is not None else "",
            self.exponentSpinBox.value,
            self.clustersSpinBox.value,
            self.methodSelector.currentData,
        )

    def _updateDefaultName(self, *args):
        self.outputNameLineEdit.setPlaceholderText(self._defaultName())

    def _outputName(self) -> str:
        return self.outputNameLineEdit.text.strip() or self._defaultName()

    # ----- refresh -----
    def _invalidateFit(self):
        self._params = None
        self._clusters = None
        self._clusterLabels = None
        self._clusterNode = None
        if self._calibration is not None:
            self.calibrationStatusLabel.setText("The calibration no longer matches the fit. Calibrate again.")
        self._calibration = None
        self._updateCalibrationPlots()
        self._updateClusterTable()

    def _refresh(self):
        volumeNode = self.inputSelector.currentNode()
        self._axis = self._axisValues(self.logic.sliceCount(volumeNode)) if volumeNode is not None else None
        self._syncEnergiesRange()
        self._updateSelection()
        self._updateHeatmap()
        self._updateParams()

    # ----- histogram -----
    def _updateHeatmap(self):
        """Recompute the (energy x attenuation) histogram if the volume or the SOI changed."""
        volumeNode = self.inputSelector.currentNode()
        if volumeNode is None:
            self._heatmap, self._heatmapKey, self._background = None, None, None
            self._updateHeatmapPlot()
            return
        soiNode = self.soiSelector.currentNode()
        key = (
            soiNode.GetID() if soiNode else None,
            soiNode.GetMTime() if soiNode else None,
            volumeNode.GetID(),
            volumeNode.GetMTime(),
        )
        if self._heatmap is None or key != self._heatmapKey:
            slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
            try:
                array = slicer.util.arrayFromVolume(volumeNode)
                self._soiMask = self._currentSoiMask(volumeNode)
                self._background = self.logic.backgroundValues(array)
                self._heatmap = self.logic.computeHeatmap(array, HISTOGRAM_BINS, self._background, self._soiMask)
                self._heatmapKey = key
            finally:
                slicer.app.restoreOverrideCursor()
        self._updateHeatmapPlot()

    def _updateHeatmapPlot(self, *args):
        plot = self._heatmapWidget
        for item in list(plot.getPlotItem().items):
            if item is not self._heatmapImage:
                plot.removeItem(item)
        self._shadeItems = []
        self._legend.clear()
        if self._heatmap is None or self._axis is None:
            self._heatmapImage.clear()
            return
        counts, low, high = self._heatmap
        data = np.log1p(counts.astype(float))
        axis = self._axis
        if len(axis) > 1 and axis[-1] < axis[0]:
            data = data[::-1]  # the image grid must follow an ascending x axis
        x0, x1 = SpectralProfileLogic.axisExtent(axis, counts.shape[0])
        self._heatmapImage.setImage(data, autoLevels=False)
        self._heatmapImage.setRect(pg.QtCore.QRectF(x0, low, x1 - x0, high - low))
        top = float(data.max()) or 1.0
        self._heatmapImage.setLevels((0, top))
        self._colorBar.setLevels((0, top))
        plot.getAxis("bottom").setLabel(self.axisLabelLineEdit.text or "z")
        plot.getPlotItem().getViewBox().setRange(xRange=(x0, x1), yRange=(low, high), padding=0)

        self._updateShading()

        for n, cluster in enumerate(self._clusters or []):
            curve = (
                cluster["mean"][1] * (axis / POWER_LAW_REFERENCE_ENERGY) ** self._clusterExponent + cluster["mean"][0]
            )
            plot.plot(
                axis,
                curve,
                pen=pg.mkPen(cluster.get("color", SERIES_COLORS[n % len(SERIES_COLORS)]), width=3),
                name=cluster.get("name", f"Cluster {n + 1}"),
            )

    def _updateShading(self):
        """Grey out the energies that the fit does not use (cheap, so it can follow the slider while dragging)."""
        plot = self._heatmapWidget
        for item in self._shadeItems:
            plot.removeItem(item)
        self._shadeItems = []
        if self._selection is None or self._axis is None or self._heatmap is None:
            return
        edges = SpectralProfileLogic.energyEdges(self._axis)
        for first, last in SpectralProfileLogic.unusedRuns(self._selection, len(self._axis)):
            left, right = sorted((edges[first], edges[last + 1]))
            region = pg.LinearRegionItem(
                values=(left, right), movable=False, brush=pg.mkBrush(90, 90, 90, 150), pen=pg.mkPen(None)
            )
            region.setZValue(5)
            plot.addItem(region, ignoreBounds=True)
            self._shadeItems.append(region)

    # ----- power-law fit and clustering -----
    def _onFitParametersChanged(self, *args):
        self._invalidateFit()
        self._updateParams()
        self._adoptSegmentation()
        self._updateHeatmapPlot()

    def _updateParams(self):
        """Fit attenuation = a * (E/100)**b + c to every pixel when the volume, SOI, energies or exponent changed."""
        volumeNode = self.inputSelector.currentNode()
        if volumeNode is None or self._selection is None:
            self._params, self._paramsKey = None, None
            self._updateParamPlot()
            return
        soiNode = self.soiSelector.currentNode()
        key = (
            soiNode.GetID() if soiNode else None,
            soiNode.GetMTime() if soiNode else None,
            volumeNode.GetID(),
            volumeNode.GetMTime(),
            self.exponentSpinBox.value,
            tuple(self._selection),
            tuple(self._axis[[0, -1]]),
        )
        if self._params is None or key != self._paramsKey:
            slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
            try:
                array = slicer.util.arrayFromVolume(volumeNode)
                mask = self._currentSoiMask(volumeNode)
                background = self._background if self._background is not None else self.logic.backgroundValues(array)
                self._params = self.logic.powerLawFit(
                    array, self._axis, self.exponentSpinBox.value, self._selection, background, mask
                )
                self._paramsKey = key
                self._clusters = None
            finally:
                slicer.app.restoreOverrideCursor()
        self._updateParamPlot()

    def _updateParamPlot(self, *args):
        plot = self._paramWidget
        for item in list(plot.getPlotItem().items):
            if item is not self._paramImage:
                plot.removeItem(item)
        if self._params is None:
            self._paramImage.clear()
            return
        a, c, valid = self._params
        if not valid.any():
            self._paramImage.clear()
            return
        cLow, cHigh = np.percentile(c[valid], [0.1, 99.9])
        aLow, aHigh = np.percentile(a[valid], [0.1, 99.9])
        counts, _, _ = np.histogram2d(c[valid], a[valid], bins=PARAM_BINS, range=[[cLow, cHigh], [aLow, aHigh]])
        data = np.log1p(counts)
        self._paramImage.setImage(data, autoLevels=False)
        self._paramImage.setRect(pg.QtCore.QRectF(cLow, aLow, cHigh - cLow, aHigh - aLow))
        top = float(data.max()) or 1.0
        self._paramImage.setLevels((0, top))
        self._paramBar.setLevels((0, top))
        plot.getPlotItem().getViewBox().setRange(xRange=(cLow, cHigh), yRange=(aLow, aHigh), padding=0)
        for n, cluster in enumerate(self._clusters or []):
            self._addClusterItems(n, cluster)

    # ----- editing the Gaussians on the plot -----
    def _addClusterItems(self, n: int, cluster: dict):
        """Draw a Gaussian as its 2-sigma ellipse with three handles to edit it: the center moves the mean, the one
        at the end of the major axis rotates and stretches that axis, the one at the end of the minor axis stretches
        it. The segmentation is redone when a handle is released."""
        plot = self._paramWidget
        color = cluster.get("color", SERIES_COLORS[n % len(SERIES_COLORS)])
        curve = pg.PlotCurveItem(pen=pg.mkPen(color, width=2.5))
        plot.addItem(curve)

        def handle(symbol, size):
            item = pg.TargetItem(
                pos=(0, 0),
                size=size,
                symbol=symbol,
                movable=True,
                pen=pg.mkPen("w", width=1.5),
                brush=pg.mkBrush(*color),
            )
            item.setZValue(20)
            plot.addItem(item)
            return item

        center, major, minor = handle("o", 13), handle("s", 9), handle("s", 9)

        def place(item, point):
            item.blockSignals(True)  # moving the handles from here must not count as the user dragging them
            item.setPos(float(point[0]), float(point[1]))
            item.blockSignals(False)

        def redraw():
            mean = np.asarray(cluster["mean"], dtype=float)
            angle, sigmaMajor, sigmaMinor = cluster["shape"]
            u1 = np.array([np.cos(angle), np.sin(angle)])
            u2 = np.array([-np.sin(angle), np.cos(angle)])
            outline = SpectralProfileLogic.ellipsePoints(
                mean, SpectralProfileLogic.gaussianCov(*cluster["shape"]), sigmas=2.0
            )
            curve.setData(outline[:, 0], outline[:, 1])
            place(center, mean)
            place(major, mean + 2 * sigmaMajor * u1)
            place(minor, mean + 2 * sigmaMinor * u2)

        def onCenterMoved(*_):
            cluster["mean"] = np.array([center.pos().x(), center.pos().y()])
            redraw()

        def onMajorMoved(*_):
            delta = np.array([major.pos().x(), major.pos().y()]) - np.asarray(cluster["mean"], dtype=float)
            length = float(np.linalg.norm(delta))
            if length > 1e-9:
                angle = float(np.arctan2(delta[1], delta[0]))
                cluster["shape"] = (angle, length / 2, min(cluster["shape"][2], length / 2))
            redraw()

        def onMinorMoved(*_):
            angle, sigmaMajor, _ = cluster["shape"]
            delta = np.array([minor.pos().x(), minor.pos().y()]) - np.asarray(cluster["mean"], dtype=float)
            perpendicular = abs(float(delta @ np.array([-np.sin(angle), np.cos(angle)])))
            cluster["shape"] = (angle, sigmaMajor, min(max(perpendicular / 2, 1e-6), sigmaMajor))
            redraw()

        cluster["shape"] = SpectralProfileLogic.gaussianShape(cluster["cov"])
        for item, handler in ((center, onCenterMoved), (major, onMajorMoved), (minor, onMinorMoved)):
            item.sigPositionChanged.connect(handler)
            item.sigPositionChangeFinished.connect(self._onGaussiansEdited)
        redraw()

    def _fitKey(self) -> dict:
        """What the (c, a) values depend on besides the volume: the Gaussians only fit a segmentation made with it."""
        return {
            "exponent": float(self.exponentSpinBox.value),
            "selection": [int(v) for v in self._selection],
            "axis": [float(self._axis[0]), float(self._axis[-1])],
        }

    def _saveGaussians(self):
        """Keep the Gaussians on the working segmentation, so that choosing it again gives back these ellipses
        instead of ones estimated again from its pixels."""
        if not self._clusters or self._clusterNode is None or self._selection is None or self._axis is None:
            return
        for n, cluster in enumerate(self._clusters):
            cluster.setdefault("segmentId", f"class{n + 1}")
        self._clusterNode.SetAttribute(GAUSSIANS_ATTRIBUTE, self.logic.encodeGaussians(self._clusters, self._fitKey()))

    def _onGaussiansEdited(self, *args):
        """Redo the segmentation (the same node) and the tables with the Gaussians as they are on the plot."""
        volumeNode = self.inputSelector.currentNode()
        if not self._clusters or self._params is None or volumeNode is None:
            return
        for cluster in self._clusters:
            cluster["cov"] = SpectralProfileLogic.gaussianCov(*cluster["shape"])
        a, c, valid = self._params
        slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            labels, counts = self.logic.classifyByGaussians(
                c, a, valid, self._clusters, self.confidenceSpinBox.value / 100.0
            )
            for cluster, count in zip(self._clusters, counts):
                cluster["count"] = count
            self._clusterLabels = labels
            self._clusterNode = self.logic.createSegmentation(
                volumeNode,
                labels,
                [cluster["name"] for cluster in self._clusters],
                [cluster["color"] for cluster in self._clusters],
                self._outputName(),
                node=self._clusterNode,
                segmentIds=[cluster.get("segmentId") for cluster in self._clusters]
                if all(cluster.get("segmentId") for cluster in self._clusters)
                else None,
            )
            self._saveGaussians()
        finally:
            slicer.app.restoreOverrideCursor()
        self._updateHeatmapPlot()
        self._showClusterSummary(valid)
        self._updateClusterTable()

    def _onAdjustSegmentationChanged(self, *args):
        self._clusters, self._clusterLabels, self._clusterNode = None, None, None
        if self.adjustSelector.currentNode() is not None:
            self._updateParams()
            self._adoptSegmentation()
        self._updateParamPlot()
        self._updateHeatmapPlot()
        self._updateClusterTable()

    def _adoptSegmentation(self):
        """Take the segments of the chosen segmentation as the Gaussians to adjust, so that editing them on the plot
        updates that segmentation. Does nothing without a segmentation or a fit."""
        node = self.adjustSelector.currentNode()
        volumeNode = self.inputSelector.currentNode()
        if node is None or volumeNode is None or self._params is None:
            return
        a, c, valid = self._params
        segmentation = node.GetSegmentation()
        masks = []
        for n in range(segmentation.GetNumberOfSegments()):
            mask = self.logic.soiMask(node, [segmentation.GetNthSegmentID(n)], volumeNode)
            masks.append(mask if mask is not None else np.zeros(valid.shape, dtype=bool))
        segmentIds = [segmentation.GetNthSegmentID(n) for n in range(segmentation.GetNumberOfSegments())]
        clusters = None
        if self._selection is not None and self._axis is not None:
            clusters = self.logic.decodeGaussians(
                node.GetAttribute(GAUSSIANS_ATTRIBUTE) or "", self._fitKey(), segmentIds
            )
        if clusters is not None:  # made here with this same fit: the Gaussians as they were, not re-estimated
            labels, counts = self.logic.classifyByGaussians(c, a, valid, clusters, self.confidenceSpinBox.value / 100.0)
            for n, (cluster, count) in enumerate(zip(clusters, counts)):
                cluster["count"], cluster["index"] = count, n
        else:
            clusters, labels = self.logic.segmentGaussians(c, a, valid, masks)
        if not clusters:
            slicer.util.warningDisplay(
                "No segment of this segmentation has enough pixels inside the SOI to be adjusted."
            )
            return
        for cluster in clusters:
            segment = segmentation.GetNthSegment(cluster["index"])
            cluster["name"] = segment.GetName()
            cluster["segmentId"] = segmentation.GetNthSegmentID(cluster["index"])
            cluster["color"] = tuple(int(round(255 * v)) for v in segment.GetColor())
        self._clusters, self._clusterLabels, self._clusterNode = clusters, labels, node
        self._clusterExponent = self.exponentSpinBox.value
        self._showClusterSummary(valid)

    def _showClusterSummary(self, valid: np.ndarray):
        leftOut = 100.0 * (1.0 - np.count_nonzero(self._clusterLabels) / max(int(valid.sum()), 1))
        self.clusterStatusLabel.setText(
            self.logic.describeClusters(self._clusters, self.confidenceSpinBox.value, leftOut)
        )

    # ----- calibration with standards -----
    def _onStandardsChanged(self, *args):
        self._calibration = None
        self.calibrationStatusLabel.setText("")
        self._updateClusterTable()

    def _standardInputs(self) -> List[Tuple[str, dict, int]]:
        """(name, composition, attenuation rank) of the rows with a formula and a density, in the table order.

        Raises ValueError, naming the row, for a formula or density that cannot be read."""
        inputs = []
        for row, (name, _, _, rank) in enumerate(PRESET_STANDARDS):
            formula = self.standardsTable.item(row, 1).text().strip()
            densityText = self.standardsTable.item(row, 2).text().strip().replace(",", ".")
            if not formula and not densityText:
                continue
            try:
                composition = self.logic.composition(self.logic.parseFormula(formula), float(densityText))
            except ValueError as e:
                raise ValueError(f"Standard '{name}': {e}")
            inputs.append((name, composition, rank))
        return inputs

    def _standardMasks(
        self, volumeNode, array, background, inputs: List[Tuple[str, dict, int]]
    ) -> Tuple[List[np.ndarray], str, Optional[dict]]:
        """2D masks of the standards in the order of `inputs`, a sentence about how they were found and, when they were
        found by clustering, that clustering (see `findStandards`).

        By default they are found by clustering the pixels outside the SOI. With a standards segmentation chosen,
        its segments are used and matched to the standards by increasing attenuation at the lowest energy."""
        standardsNode = self.standardsSelector.currentNode()
        if standardsNode is None:
            soi = self._currentSoiMask(volumeNode)
            if soi is None:
                raise ValueError(
                    "Select the SOI: the standards are searched outside it. Or choose a standards segmentation."
                )
            found = self.logic.findStandards(
                array,
                self._axis,
                self._selection,
                background,
                soi,
                self.exponentSpinBox.value,
                [composition for _, composition, _ in inputs],
                minProbability=self.confidenceSpinBox.value / 100.0,
            )
            return found["masks"], "", found
        segmentation = standardsNode.GetSegmentation()
        masks = []
        for n in range(segmentation.GetNumberOfSegments()):
            mask = self.logic.soiMask(standardsNode, [segmentation.GetNthSegmentID(n)], volumeNode)
            if mask is not None and mask.any():
                masks.append(mask)
        if len(masks) != len(inputs):
            raise ValueError(
                f"The standards segmentation has {len(masks)} segment(s) but {len(inputs)} standard(s) are set."
            )
        ordered = [
            masks[k] for k in self.logic.orderByAttenuation(array, self._axis, self._selection, background, masks)
        ]
        byRank = sorted(range(len(inputs)), key=lambda k: inputs[k][2])  # inputs from least to most attenuating
        aligned = [None] * len(inputs)
        for position, k in enumerate(byRank):
            aligned[k] = ordered[position]
        return aligned, "", None

    def _showFoundStandards(self, volumeNode, found: dict, names: List[str]):
        """Segmentation with the standards found outside the SOI, to be checked on the image. The other clusters of
        the fit (holder, mixed pixels at the borders) only served to isolate the standards and are not shown."""
        if self._standardsNode is not None and slicer.mrmlScene.IsNodePresent(self._standardsNode):
            slicer.mrmlScene.RemoveNode(self._standardsNode)
        labels = np.zeros_like(found["labels"])
        for index, mask in enumerate(found["masks"], start=1):  # standards without the specks the cleaning dropped
            labels[mask & (found["labels"] == index)] = index
        self._standardsNode = self.logic.createSegmentation(
            volumeNode,
            labels,
            list(names),
            [SERIES_COLORS[k % len(SERIES_COLORS)] for k in range(len(names))],
            f"{self.inputSelector.currentNode().GetName()}_standards",
            exclusive=False,
        )

    def _onCalibrateClicked(self, *args):
        self._calibrate()

    def _calibrate(self):
        """Find the standards, estimate b if asked to, and fit the constants of the calibration."""
        volumeNode = self.inputSelector.currentNode()
        if volumeNode is None:
            slicer.util.errorDisplay("Please select an input volume.")
            return
        if self._selection is None:
            slicer.util.errorDisplay("The energies used are not valid. See the Spectral axis section.")
            return
        try:
            inputs = self._standardInputs()
            if len(inputs) < 2:
                raise ValueError("Fill in the formula and density of at least two standards.")
        except ValueError as e:
            slicer.util.errorDisplay(str(e))
            return
        warning = note = ""
        slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            array = slicer.util.arrayFromVolume(volumeNode)
            background = self._background if self._background is not None else self.logic.backgroundValues(array)
            if self.estimateExponentCheckBox.checked:
                start = self.exponentSpinBox.value
                for _ in range(ESTIMATE_PASSES):  # the standards are found with b, so after a new b look again
                    masks, _, _ = self._standardMasks(volumeNode, array, background, inputs)
                    inner = [self.logic.standardPixels(mask, STANDARD_BORDER_PIXELS) for mask in masks]
                    result = self.logic.estimateExponent(array, self._axis, self._selection, background, inner)
                    best = round(result["best"], 2)
                    done = abs(best - self.exponentSpinBox.value) < 0.025
                    self.exponentSpinBox.setValue(best)
                    if done:
                        break
                if self.exponentSpinBox.value != start:
                    self._onFitParametersChanged()
                    self._updateDefaultName()
                note = self.logic.exponentWarning(result)
            masks, _, found = self._standardMasks(volumeNode, array, background, inputs)
            meanA, meanC = [], []
            for (name, _, _), mask in zip(inputs, masks):
                inner = self.logic.standardPixels(mask, STANDARD_BORDER_PIXELS)
                a, c, valid = self.logic.powerLawFit(
                    array, self._axis, self.exponentSpinBox.value, self._selection, background, inner
                )
                pixels = inner & valid
                if pixels.sum() < MIN_STANDARD_PIXELS:
                    raise ValueError(f"Standard '{name}' has fewer than {MIN_STANDARD_PIXELS} usable pixels.")
                meanA.append(float(np.median(a[pixels])))  # the median resists ring artifacts and leftover borders
                meanC.append(float(np.median(c[pixels])))
            self._calibration = self.logic.calibrate(meanA, meanC, [composition for _, composition, _ in inputs])
            self._calibration["names"] = [name for name, _, _ in inputs]
            self._calibration["exponent"] = float(self.exponentSpinBox.value)
            self._dualCalibration = None  # it depends on the standards of this calibration
            distance, worst = self.logic.calibrationResidual(self._calibration)
            if distance > POINT_OFF_LINE:
                warning = (
                    f"{self._calibration['names'][worst]} is {100 * distance:.0f} % off the calibration. "
                    f"Check {volumeNode.GetName()}_standards and its density."
                )
            if found is not None:
                self._showFoundStandards(volumeNode, found, self._calibration["names"])
        except ValueError as e:
            self._calibration = None
            slicer.util.errorDisplay(str(e))
            return
        finally:
            slicer.app.restoreOverrideCursor()
        self.calibrationStatusLabel.setText(self.logic.describeCalibration(self._calibration, warning, note))
        self._updateCalibrationPlots()
        self._updateParamPlot()
        self._updateClusterTable()

    def _updateCalibrationPlots(self):
        """Where each standard falls on the calibration: its measured value against the known one, with the line
        (or curve) the calibration draws. A standard far from it is marked in red."""
        if not hasattr(self, "_calibrationPlotZ"):  # the panel is still being built
            return
        for plot in (self._calibrationPlotC, self._calibrationPlotZ):
            plot.clear()
        calibration = self._calibration
        if calibration is None:
            return
        points, names = calibration["points"], calibration.get("names", [])
        knownE = np.array([p["electronDensity"] for p in points])
        knownZ = np.array([p["zeff"] for p in points])
        electrons = np.linspace(0.0, 1.15 * knownE.max(), 30)
        zeffs = np.linspace(0.85 * knownZ.min(), 1.15 * knownZ.max(), 60)
        self._calibrationPlotC.plot(electrons, calibration["beta"] * electrons, pen=pg.mkPen((120, 120, 120), width=2))
        self._calibrationPlotZ.plot(
            zeffs, calibration["K"] * zeffs ** calibration["n"], pen=pg.mkPen((120, 120, 120), width=2)
        )
        for index, point in enumerate(points):
            color = SERIES_COLORS[index % len(SERIES_COLORS)]
            for plot, x, y, expected in (
                (
                    self._calibrationPlotC,
                    point["electronDensity"],
                    point["c"],
                    calibration["beta"] * point["electronDensity"],
                ),
                (
                    self._calibrationPlotZ,
                    point["zeff"],
                    point["ratio"],
                    calibration["K"] * point["zeff"] ** calibration["n"],
                ),
            ):
                off = abs(y / expected - 1.0) > POINT_OFF_LINE
                plot.plot(
                    [x],
                    [y],
                    pen=None,
                    symbol="o",
                    symbolSize=12,
                    symbolBrush=pg.mkBrush(*color),
                    symbolPen=pg.mkPen((214, 39, 40) if off else "w", width=3),
                )
                label = pg.TextItem(names[index] if index < len(names) else "", color=color, anchor=(0, 1.3))
                label.setPos(float(x), float(y))
                plot.addItem(label)

    def _updateClusterTable(self):
        """Electron density, Zeff and bulk density of each class with the calibration, and the choice of its mineral, which
        starts as the suggested one. The classes are the clusters of the segmentation worked on."""
        table = self.resultsTable
        self._mineralCombos = []
        if self._calibration is None or not self._clusters or self._params is None or self._clusterLabels is None:
            table.setRowCount(0)
            return
        a, c, _ = self._params
        properties = self.logic.clusterProperties(a, c, self._clusterLabels, len(self._clusters), self._calibration)
        total = max(sum(item["pixels"] for item in properties), 1)
        table.setRowCount(len(properties))
        for row, (cluster, item) in enumerate(zip(self._clusters, properties)):
            electron, zeff, density = item["values"]
            sdElectron, sdZeff, sdDensity = item["sd"]
            suggested = self.logic.suggestMineral(zeff, density, self._calibration["n"])[0]
            cells = [
                cluster.get("name", f"Cluster {row + 1}"),
                f"{100 * item['pixels'] / total:.1f}",
                f"{electron:.3f} \u00b1 {sdElectron:.3f}",
                f"{zeff:.2f} \u00b1 {sdZeff:.2f}",
                f"{density:.2f} \u00b1 {sdDensity:.2f}",
            ]
            for column, text in enumerate(cells):
                cell = qt.QTableWidgetItem(text)
                if column == 0 and cluster.get("color") is not None:
                    cell.setForeground(qt.QBrush(qt.QColor(*cluster["color"])))
                table.setItem(row, column, cell)
            combo = qt.QComboBox()
            combo.addItems(MINERAL_CHOICES)
            combo.setMinimumWidth(MINERAL_COLUMN_MIN_WIDTH)
            combo.setCurrentText(cluster.get("mineral") or suggested or NO_MINERAL)
            combo.connect("currentIndexChanged(int)", lambda *_, index=row: self._onMineralChosen(index))
            table.setCellWidget(row, len(RESULT_COLUMNS) - 1, combo)
            self._mineralCombos.append(combo)
        for column in range(len(RESULT_COLUMNS) - 1):
            table.resizeColumnToContents(column)
        self._properties = properties
        self._updatePropertiesNode()

    def _updatePropertiesNode(self):
        """Table node next to the working segmentation with the estimated electrons, Zeff and bulk density of each
        segment (and the mineral chosen), refreshed whenever the classes, the calibration or the minerals change."""
        node = self._clusterNode
        if (
            node is None
            or not slicer.mrmlScene.IsNodePresent(node)
            or not self._clusters
            or self._calibration is None
            or self._properties is None
            or len(self._properties) != len(self._clusters)
        ):
            return
        minerals = [combo.currentText for combo in self._mineralCombos] or [""] * len(self._clusters)
        header, rows = self.logic.propertiesTable(
            [cluster.get("name", f"Cluster {n + 1}") for n, cluster in enumerate(self._clusters)],
            [m if m != NO_MINERAL else "" for m in minerals],
            self._properties,
        )
        tableNode = slicer.mrmlScene.GetNodeByID(node.GetNodeReferenceID(PROPERTIES_REFERENCE) or "")
        if tableNode is None:
            tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", f"{node.GetName()}_properties")
            node.SetNodeReferenceID(PROPERTIES_REFERENCE, tableNode.GetID())
            self.logic._placeNextTo(node, tableNode)
        self._writePropertiesTable(tableNode, header, rows)

    @staticmethod
    def _writePropertiesTable(tableNode, header: List[str], rows: List[list]) -> None:
        """Fill `tableNode` with the rows of `Logic.propertiesTable` (text in the first and last columns)."""
        tableNode.RemoveAllColumns()
        for column, name in enumerate(header):
            if column in (0, len(header) - 1):
                values = vtk.vtkStringArray()
            else:
                values = vtk.vtkDoubleArray()
            values.SetName(name)
            for row in rows:
                if column in (0, len(header) - 1):
                    values.InsertNextValue(str(row[column]))
                else:
                    values.InsertNextValue(float(row[column]))
            tableNode.AddColumn(values)

    def _onMineralChosen(self, index: int):
        if self._clusters and index < len(self._mineralCombos):
            self._clusters[index]["mineral"] = self._mineralCombos[index].currentText
            self._updatePropertiesNode()

    def _onApplyMineralsClicked(self):
        """Rename the segments of the working segmentation after the minerals chosen for their classes."""
        if not self._clusters or self._clusterNode is None or not slicer.mrmlScene.IsNodePresent(self._clusterNode):
            slicer.util.errorDisplay("There is no segmentation to name. Cluster, or choose a segmentation to work on.")
            return
        chosen = [combo.currentText for combo in self._mineralCombos]
        if not chosen or all(name == NO_MINERAL for name in chosen):
            slicer.util.errorDisplay("Choose the mineral of at least one class.")
            return
        # repeated minerals are numbered; the classes left at - keep the name they have
        named = [name if name != NO_MINERAL else None for name in chosen]
        numbered = iter(self.logic.uniqueSegmentNames([name for name in named if name]))
        segmentation = self._clusterNode.GetSegmentation()
        for index, (cluster, name) in enumerate(zip(self._clusters, named)):
            if name is None:
                continue
            newName = next(numbered)
            segment = segmentation.GetSegment(cluster.get("segmentId") or f"class{index + 1}")
            if segment is not None:
                segment.SetName(newName)
            cluster["name"] = newName
        self._updateHeatmapPlot()
        self._updateClusterTable()
        if self._params is not None:
            self._showClusterSummary(self._params[2])

    def _prepareAnalysis(self) -> Optional[tuple]:
        """Validate the inputs and return (volumeNode, array, mask, background), or None after showing why not."""
        volumeNode = self.inputSelector.currentNode()
        if volumeNode is None:
            slicer.util.errorDisplay("Please select an input volume.")
            return None
        if self._selection is None:
            slicer.util.errorDisplay("The energies used are not valid. See the Spectral axis section.")
            return None
        self._updateParams()
        if self._params is None or not self._params[2].any():
            slicer.util.errorDisplay("There are no pixels to cluster (check the SOI).")
            return None
        array = slicer.util.arrayFromVolume(volumeNode)
        return volumeNode, array, self._currentSoiMask(volumeNode), self._background

    def _onClusterClicked(self):
        prepared = self._prepareAnalysis()
        if prepared is None:
            return
        volumeNode = prepared[0]
        slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            a, c, valid = self._params
            labels, clusters = self.logic.clusterParameters(
                c,
                a,
                valid,
                self.clustersSpinBox.value,
                minProbability=self.confidenceSpinBox.value / 100.0,
                method=self.methodSelector.currentData,
            )
            for n, cluster in enumerate(clusters):
                cluster["name"], cluster["color"] = f"Cluster {n + 1}", SERIES_COLORS[n % len(SERIES_COLORS)]
            self._clusters = clusters
            self._clusterLabels = labels
            self._clusterExponent = self.exponentSpinBox.value
            self._clusterNode = self.logic.createSegmentation(
                volumeNode,
                labels,
                [cluster["name"] for cluster in clusters],
                [cluster["color"] for cluster in clusters],
                self._outputName(),
            )
            self._saveGaussians()
            self.adjustSelector.blockSignals(True)  # the new result is the one to adjust now
            self.adjustSelector.setCurrentNode(None)
            self.adjustSelector.blockSignals(False)
        finally:
            slicer.app.restoreOverrideCursor()
        self._updateParamPlot()
        self._updateHeatmapPlot()
        self._showClusterSummary(valid)
        self._updateClusterTable()

    def _onStabilityClicked(self):
        prepared = self._prepareAnalysis()
        if prepared is None:
            return
        volumeNode, array, mask, background = prepared
        slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            result = self.logic.clusterStability(
                array,
                self._axis,
                background,
                mask,
                self.exponentSpinBox.value,
                self._selection,
                self.clustersSpinBox.value,
                method=self.methodSelector.currentData,
            )
            self.logic.createStabilityMap(volumeNode, result["map"], f"{self._outputName()}_stability")
        finally:
            slicer.app.restoreOverrideCursor()
        self.clusterStatusLabel.setText(self.logic.describeStability(result))

    # ----- dual energy 3D -----
    def _dualClasses(self) -> Optional[Tuple[dict, List[dict]]]:
        """(fit, classes) of the chosen segmentation, each class with its Gaussian, name and color, or None when it
        has no Gaussians of this module."""
        node = self.dualGaussiansSelector.currentNode()
        parsed = self.logic.parseGaussians(node.GetAttribute(GAUSSIANS_ATTRIBUTE) or "") if node else None
        if parsed is None:
            return None
        fit, classes = parsed
        segmentation = node.GetSegmentation()
        for n, cluster in enumerate(classes):
            segment = segmentation.GetSegment(cluster["segmentId"])
            cluster["name"] = segment.GetName() if segment else f"Cluster {n + 1}"
            cluster["color"] = (
                tuple(int(round(255 * v)) for v in segment.GetColor())
                if segment
                else SERIES_COLORS[n % len(SERIES_COLORS)]
            )
        return fit, classes

    def _dualVolumes(self) -> Optional[list]:
        """The two volumes (as a list), or None when one is missing."""
        nodes = [self.dualLowSelector.currentNode(), self.dualHighSelector.currentNode()]
        return None if any(node is None for node in nodes) else nodes

    def _dualMethod(self) -> str:
        return self.dualMethodSelector.currentData

    def _dualDefaultName(self) -> str:
        """Name of the result when none is typed: it says which method made it."""
        if self._dualMethod() == "cluster":
            return f"{DUAL_CLUSTER_NAME}{self.dualClustersSpinBox.value}"
        return DUAL_SPECTRAL_NAME

    def _onDualMethodChanged(self, *args):
        """Show what the method needs: the classes of the spectral scan, or the number of clusters."""
        for method, widgets in self._dualMethodRows.items():
            for widget in widgets:
                widget.setVisible(method == self._dualMethod())
        self._onDualInputsChanged()

    def _dualClassCount(self) -> int:
        """Classes of the result: the segments of the chosen segmentation, or the clusters asked for."""
        if self._dualMethod() == "cluster":
            return self.dualClustersSpinBox.value
        node = self.dualGaussiansSelector.currentNode()
        return node.GetSegmentation().GetNumberOfSegments() if node else 0

    def _dualMemoryNeeded(self, shape: Tuple[int, int, int], count: int) -> int:
        """Bytes the segmentation adds: the labels and the working arrays, besides a slab of the filtered volumes (one
        working memory) that is read at a time."""
        memory = self.dualWorkingMemoryGB * 2**30
        mask = int(np.prod(shape)) if self.dualSoiSelector.currentNode() is not None else 0  # one byte per voxel
        return int(self.logic.estimateDualMemory(shape, count, memory) + memory + mask)

    def _dualProblem(self, needClasses: bool = True) -> str:
        """Why the 3D segmentation cannot run (empty when it can); the histogram needs the classes in another way."""
        if needClasses and self._dualMethod() == "spectral" and self._dualClassCount() < 2:
            return "Choose the segmentation of the multi-energy scan with its classes (at least two segments)."
        volumes = self._dualVolumes()
        if volumes is None:
            return "Choose the volume of each energy."
        nodes = volumes
        if nodes[0] is nodes[1]:
            return "The two energies need two different volumes."
        dimensions = [tuple(node.GetImageData().GetDimensions()) for node in nodes]
        if dimensions[0] != dimensions[1]:
            return f"The volumes have different sizes ({dimensions[0]} and {dimensions[1]})."
        return ""

    def _onDualInputsChanged(self, *args):
        self._dualCalibration = None
        self.dualStatusLabel.setText("")
        self.dualOutputNameLineEdit.setPlaceholderText(self._dualDefaultName())
        count = self._dualClassCount()
        volumes = self._dualVolumes()
        if count == 0 or volumes is None:
            return
        problem = self._dualProblem()
        if problem:
            self.dualStatusLabel.setText(self.logic.colored(problem, "bad"))
            return
        nodes = volumes
        shape = tuple(reversed(nodes[0].GetImageData().GetDimensions()))
        needed = self._dualMemoryNeeded(shape, count)
        text = (
            f"<p>{np.prod(shape) / 1e6:,.1f} Mvoxels. The segmentation adds about <b>{needed / 2**30:.2f} GB</b>.</p>"
        )
        available = self.logic.availableMemory()
        if available is not None and needed > 0.9 * available:
            text += self.logic.colored(f"Only {available / 2**30:.1f} GB of RAM are free.", "bad")
        geometry = [tuple(np.round(node.GetSpacing(), 6)) + tuple(np.round(node.GetOrigin(), 3)) for node in nodes]
        if geometry[0] != geometry[1]:
            text += self.logic.colored("The volumes have different spacing or origin: are they registered?", "warn")
        self.dualStatusLabel.setText(text)

    def _onDualCancelClicked(self, *args):
        self._dualCancelled = True

    def _histogramClasses(self, volumes: List[np.ndarray], convert) -> List[dict]:
        """The classes of the multi-energy slice as Gaussians in the plane of the histogram (their voxels in the
        volumes put through `convert`): dicts with name, color, mean and cov. Empty when the slice cannot be found."""
        try:
            found = self._registerDualSlice()
            names, colors, image, _ = self._dualClassImages()
            samples = self.logic.sampleClassVoxels(
                volumes, found["z"], image, found["scale"], found["offset"], len(names), 0.0
            )
        except ValueError:
            return []
        converted = [
            np.column_stack(convert([values[:, 0], values[:, 1]])) if len(values) else values for values in samples
        ]
        clusters, kept = self.logic.fitGrayGaussians(converted)
        return [dict(item, name=names[k], color=colors[k]) for item, k in zip(clusters, kept)]

    def _onDualHistogramClicked(self, *args):
        problem = self._dualProblem(needClasses=False)
        if problem:
            slicer.util.errorDisplay(problem)
            return
        lowNode, highNode = self._dualVolumes()
        shape = tuple(reversed(lowNode.GetImageData().GetDimensions()))
        slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            volumes = [slicer.util.arrayFromVolume(node) for node in (lowNode, highNode)]
            calibration = self._dualDensityCalibration()

            def convert(values):
                return self.logic.densityPlane(values, calibration["volumes"])

            region = self._dualRegion(shape)
            histogram = self.logic.dualHistogram(volumes, region, None, 0.0, convert=convert)
            classes = self._histogramClasses(volumes, convert)
        except ValueError as error:
            slicer.util.errorDisplay(str(error))
            return
        finally:
            slicer.app.restoreOverrideCursor()
        plot = self._dualHistogramPlot
        for item in list(plot.getPlotItem().items):
            if item is not self._dualHistogramImage:
                plot.removeItem(item)
        self._dualHistogramLegend.clear()
        data = np.log1p(histogram["counts"])
        (x0, x1), (y0, y1) = histogram["x"], histogram["y"]
        self._dualHistogramImage.setImage(data, autoLevels=False)
        self._dualHistogramImage.setRect(pg.QtCore.QRectF(x0, y0, x1 - x0, y1 - y0))
        self._dualHistogramImage.setLevels((0, float(data.max()) or 1.0))
        self._dualHistogramImage.setColorMap(pg.colormap.get(HEATMAP_COLORMAP))
        plot.getAxis("bottom").setLabel("Electron density (mol/cm3)")
        plot.getAxis("left").setLabel(f"Photoelectric term: electron density x Zeff^{calibration['exponent']:g}")
        plot.getPlotItem().getViewBox().setRange(xRange=(x0, x1), yRange=(y0, y1), padding=0)
        angles = np.linspace(0, 2 * np.pi, 80)
        for item in classes:
            values, vectors = np.linalg.eigh(item["cov"])
            outline = np.asarray(item["mean"])[:, None] + vectors @ (
                2 * np.sqrt(values)[:, None] * [np.cos(angles), np.sin(angles)]
            )
            plot.plot(outline[0], outline[1], pen=pg.mkPen(tuple(item["color"]), width=2), name=item["name"])
        self.dualHistogramView.setVisible(True)
        text = (
            (self._describeRegistration(self._sliceRegistration) if self._sliceRegistration else "")
            + f"<p>Histogram of {histogram['voxels'] / 1e6:,.1f} Mvoxels of {histogram['slices']} slices"
            + (" inside the SOI" if region is not None else " (no SOI: the holder and the air are in it)")
            + ".</p>"
        )
        self.dualStatusLabel.setText(text + self._dualCalibrationNote(calibration))

    def _dualRegion(self, shape: Tuple[int, int, int], fromInput: bool = True) -> Optional[np.ndarray]:
        """Where the volumes are segmented: the segments of the SOI chosen in the section, as a [z, y, x] mask of
        the voxels of the volumes; else, with `fromInput`, the SOI of the Input section, a [y, x] mask of the voxels
        (through the slice of the multi-energy scan, see `_registerDualSlice`), repeated in every slice; None
        without either."""
        node = self.dualSoiSelector.currentNode()
        if node is not None:
            segmentation = node.GetSegmentation()
            referenceNode = self.dualLowSelector.currentNode()
            region = np.zeros(shape, dtype=bool)
            for n in range(segmentation.GetNumberOfSegments()):
                mask = slicer.util.arrayFromSegmentBinaryLabelmap(node, segmentation.GetNthSegmentID(n), referenceNode)
                region |= mask > 0
            if not region.any():
                raise ValueError("The SOI chosen has no voxels in the volumes.")
            return region
        inputNode = self.inputSelector.currentNode()
        soi = self._currentSoiMask(inputNode) if inputNode is not None and fromInput else None
        if soi is None:
            return None
        found = self._registerDualSlice()
        return self.logic.mapToVolume(soi.astype(np.uint8), shape[1:], found["scale"], found["offset"]).astype(bool)

    def _dualSegmentation(self, labelNode):
        """The labelmap of a result as a segmentation (which replaces it in the scene)."""
        slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            return self.logic.labelVolumeToSegmentation(labelNode)
        finally:
            slicer.app.restoreOverrideCursor()

    # ----- dual energy: the classes of the multi-energy slice, found in the volumes -----
    def _progressDialog(self, text: str):
        """(handle, update) of the progress bar of the section, with its Cancel button: `update(fraction)` returns
        False once it was pressed, and `handle.close()` hides the bar. The buttons that start something are off
        meanwhile, because the application keeps answering to the user while it works."""
        self._dualCancelled = False
        self.dualProgressLabel.setText(text)
        self.dualProgressBar.setValue(0)
        self.dualProgressWidget.setVisible(True)
        buttons = [self.dualButton, self.dualHistogramButton, self.dualAutoReferencesButton]
        for button in buttons:
            button.setEnabled(False)

        def update(fraction: float) -> bool:
            self.dualProgressBar.setValue(int(100 * fraction))
            slicer.app.processEvents()
            return not self._dualCancelled

        def close() -> None:
            self.dualProgressWidget.setVisible(False)
            for button in buttons:
                button.setEnabled(True)

        return ProgressHandle(close), update

    def _registrationReference(self) -> np.ndarray:
        """Image of the multi-energy scan that the slice is looked for with: the mean of its highest energies, where
        the contrast is the one of a 3D volume scanned at a high voltage."""
        if self.inputSelector.currentNode() is None or self._axis is None:
            raise ValueError("Choose the multi-energy volume in the Input section: its slice is what is learned from.")
        array = slicer.util.arrayFromVolume(self.inputSelector.currentNode())
        highest = np.sort(np.argsort(self._axis)[::-1][: max(len(self._axis) // 14, 3)])
        return array[highest].astype(np.float32).mean(axis=0)

    def _registerDualSlice(self) -> dict:
        """Where the multi-energy slice is in the first 3D volume (see `Logic.registerSlice`), kept while the volumes
        do not change. Raises ValueError when it was stopped."""
        inputNode = self.inputSelector.currentNode()
        lowNode = self._dualVolumes()[0]
        if inputNode is None:
            raise ValueError("Choose the multi-energy volume in the Input section: its slice is what is learned from.")
        key = (inputNode.GetID(), lowNode.GetID())
        if self._sliceRegistration is not None and self._sliceRegistration["key"] == key:
            return self._sliceRegistration
        reference = self._registrationReference()
        dialog, update = self._progressDialog("Looking for the slice of the multi-energy scan...")
        try:
            found = self.logic.registerSlice(
                reference,
                inputNode.GetSpacing()[0],
                slicer.util.arrayFromVolume(lowNode),
                lowNode.GetSpacing()[0],
                None,
                update,
            )
        finally:
            dialog.close()
        if found is None:
            raise ValueError("Stopped.")
        found["key"] = key
        self._sliceRegistration = found
        return found

    def _describeRegistration(self, found: dict) -> str:
        level = "good" if found["score"] >= 0.5 else ("warn" if found["score"] >= REGISTRATION_SCORE_LIMIT else "bad")
        score = self.logic.colored(f"{found['score']:.2f}", level)
        text = (
            f"<p>The multi-energy slice is the slice <b>{found['z']}</b> of the first volume (position "
            f"({found['offset'][0]:.0f}, {found['offset'][1]:.0f}) pixels), correlation {score}.</p>"
        )
        if found["score"] < REGISTRATION_SCORE_LIMIT:
            text += self.logic.colored(
                "The correlation is low: it may not be the same cross section, or the scans are rotated or mirrored.",
                "bad",
            )
        return text

    def _dualClassImages(self) -> Tuple[List[str], list, np.ndarray, Optional[np.ndarray]]:
        """(names, colors, classes, region) of the multi-energy slice: the classes (the segments of the chosen
        segmentation, on the grid of the Input volume) as an image with the label of each, 1 to n, after dropping
        SUPERVISED_BORDER pixels around each so that the classes that mix at their borders do not teach anything,
        and the SOI (2D) when there is one, which the classes and the volumes are limited to."""
        from scipy.ndimage import binary_erosion

        node, volumeNode = self.dualGaussiansSelector.currentNode(), self.inputSelector.currentNode()
        if volumeNode is None:
            raise ValueError("Choose the multi-energy volume in the Input section: its slice is what is learned from.")
        segmentation = node.GetSegmentation()
        region = self._currentSoiMask(volumeNode)
        names, colors, classes = [], [], None
        for n in range(segmentation.GetNumberOfSegments()):
            segment = segmentation.GetNthSegment(n)
            mask = self.logic.soiMask(node, [segmentation.GetNthSegmentID(n)], volumeNode)
            if mask is None or not mask.any():
                continue
            if classes is None:
                classes = np.zeros(mask.shape, dtype=np.uint8)
            core = binary_erosion(mask, iterations=SUPERVISED_BORDER)
            if region is not None:
                core &= region
            classes[core & (classes == 0)] = len(names) + 1
            names.append(segment.GetName())
            colors.append(tuple(int(round(255 * v)) for v in segment.GetColor()))
        if len(names) < 2:
            raise ValueError("At least two segments of the classes segmentation must have pixels.")
        return names, colors, classes, region

    def _onDualAutoReferencesClicked(self, *args):
        """Create the references segmentation (the standards and the air, outside the SOI) and choose it."""
        problem = self._dualProblem(needClasses=False)
        if problem:
            slicer.util.errorDisplay(problem)
            return
        try:
            node, text = self._autoReferences()
        except ValueError as error:
            slicer.util.errorDisplay(str(error))
            return
        self.dualReferenceSelector.setCurrentNode(node)
        self.dualStatusLabel.setText(text)

    def _autoReferences(self):
        """(segmentation, status text) with the standards and the air found in the volumes, outside the Region (SOI).

        They are looked for on the middle slices of the SOI (a few averaged: the standards are prisms and the noise is
        less), among the uniform regions of the gray of the two volumes (see `Logic.findDualReferences`), and the
        segmentation covers AUTO_REFERENCE_SLICES slices there, as a slab, so that nothing the size of a volume is
        made. Raises ValueError, saying why."""
        lowNode, highNode = self._dualVolumes()
        if self.dualSoiSelector.currentNode() is None:
            raise ValueError("Choose the Region (SOI): the standards are searched outside it.")
        nz, ny, nx = (int(v) for v in reversed(lowNode.GetImageData().GetDimensions()))
        slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            inputs = sorted(self._standardInputs(), key=lambda item: item[2])  # least to most attenuating
            region = self._dualRegion((nz, ny, nx))
            slices = np.flatnonzero(region.any(axis=(1, 2)))
            first = int(min(max(np.median(slices) - AUTO_REFERENCE_SLICES // 2, 0), max(nz - AUTO_REFERENCE_SLICES, 0)))
            last = min(first + AUTO_REFERENCE_SLICES, nz)
            gray = np.stack(
                [
                    slicer.util.arrayFromVolume(node)[first:last].astype(np.float32).mean(axis=0)
                    for node in (lowNode, highNode)
                ]
            )
            from scipy.ndimage import binary_dilation

            near = binary_dilation(region[first:last].any(axis=0), iterations=3)
            found = self.logic.findDualReferences(
                gray,
                ~near,
                [(comp["electronDensity"], self.logic.effectiveZ(comp, DEFAULT_Z_EXPONENT)) for _, comp, _ in inputs],
                DEFAULT_Z_EXPONENT,
            )
        finally:
            slicer.app.restoreOverrideCursor()
        names = [name for name, _, _ in inputs] + ["Air"]
        labels = np.zeros((ny, nx), dtype=np.uint8)
        for index, mask in enumerate([*found["masks"], found["air"]], start=1):
            if mask.sum() < AUTO_REFERENCE_MIN_PIXELS:
                raise ValueError(f"The region found for {names[index - 1]} is too small. Draw the references by hand.")
            labels[mask & (labels == 0)] = index
        # the segmentation lives on a slab of the grid of the volumes: a scratch volume with that geometry
        slab = slicer.util.addVolumeFromArray(
            np.zeros((last - first, ny, nx), dtype=np.uint8), name="SpectralProfileSlab"
        )
        try:
            matrix = vtk.vtkMatrix4x4()
            lowNode.GetIJKToRASMatrix(matrix)
            for row in range(3):  # the slab starts `first` slices in
                matrix.SetElement(row, 3, matrix.GetElement(row, 3) + first * matrix.GetElement(row, 2))
            slab.SetIJKToRASMatrix(matrix)
            node = self.logic.createSegmentation(
                slab,
                labels,
                names,
                [SERIES_COLORS[k % len(SERIES_COLORS)] for k in range(len(names))],
                DUAL_REFERENCES_NAME,
                exclusive=False,
            )
        finally:
            slicer.mrmlScene.RemoveNode(slab)
        self.logic._placeNextTo(lowNode, node)
        grays = {name: float(np.median(gray[0][labels == k])) for k, name in enumerate(names, start=1)}
        text = (
            f"<p>References found outside the SOI: {', '.join(names)}, over slices {first} to {last - 1} of the volumes. "
            "Check them on the image (the median gray of the first volume: "
            + ", ".join(f"{name} {value:.0f}" for name, value in grays.items())
            + f"). They fit the model of the volumes within {100 * found['cost']:.1f} %.</p>"
        )
        return node, text

    def _dualStandardGrays(self) -> Tuple[List[List[float]], List[Optional[float]], list]:
        """Gray of each standard (and of the air) in each 3D volume, from the segments of the References selector:
        ([gray of the standards in the volume] for each volume, air gray of each volume, the known compositions of
        those standards). The standards are the ones of the table of the Calibration section, found by name or, as
        the segments are, by attenuation. Raises ValueError, saying why, when it cannot."""
        referenceNode = self.dualReferenceSelector.currentNode()
        if referenceNode is None:
            raise ValueError("Choose the segmentation with the standards and the air (References).")
        nodes = self._dualVolumes()
        inputs = self._standardInputs()
        segmentation = referenceNode.GetSegmentation()
        segmentNames = {
            segmentation.GetNthSegmentID(n): segmentation.GetNthSegment(n).GetName()
            for n in range(segmentation.GetNumberOfSegments())
        }
        byName = {name.strip().lower(): segmentId for segmentId, name in segmentNames.items()}
        chosen = {n: byName[name.lower()] for n, (name, _, _) in enumerate(inputs) if name.lower() in byName}
        airId = next((byName[name] for name in DUAL_AIR_NAMES if name in byName), None)
        pending = [n for n in range(len(inputs)) if n not in chosen]
        unnamed = [segmentId for segmentId in segmentNames if segmentId not in {*chosen.values(), airId}]
        if pending:
            if len(unnamed) != len(pending):
                raise ValueError(
                    f"The references segmentation needs the segments {', '.join(name for name, _, _ in inputs)} "
                    "(or as many segments as standards) and Air."
                )
            lowest = 0  # the attenuation orders the standards the same way in either volume
            median = {
                segmentId: float(np.median(self.logic.referenceGrayValues(referenceNode, segmentId, nodes)[lowest]))
                for segmentId in unnamed
            }
            for n, segmentId in zip(sorted(pending, key=lambda n: inputs[n][2]), sorted(unnamed, key=median.get)):
                chosen[n] = segmentId
        order = sorted(chosen)
        grays = [[] for _ in nodes]
        for n in order:
            for k, voxels in enumerate(self.logic.referenceGrayValues(referenceNode, chosen[n], nodes)):
                grays[k].append(float(np.median(voxels)))
        air = [None] * len(nodes)
        if airId is not None:
            air = [float(np.median(v)) for v in self.logic.referenceGrayValues(referenceNode, airId, nodes)]
        return grays, air, [inputs[n][1] for n in order]

    def _dualDensityCalibration(self) -> dict:
        """Calibration of each 3D volume with the standards (see `Logic.fitDensityCalibration`), with the exponent
        DEFAULT_Z_EXPONENT of Zeff; kept until the inputs change. Raises ValueError when it cannot be made."""
        if self._dualCalibration is None:
            grays, air, compositions = self._dualStandardGrays()
            exponent = DEFAULT_Z_EXPONENT
            self._dualCalibration = {
                "volumes": [
                    self.logic.fitDensityCalibration(
                        grays[k],
                        air[k],
                        [comp["electronDensity"] for comp in compositions],
                        [self.logic.effectiveZ(comp, exponent) for comp in compositions],
                        exponent,
                    )
                    for k in range(len(grays))
                ],
                "exponent": exponent,
            }
        return self._dualCalibration

    def _dualCalibrationNote(self, calibration: dict) -> str:
        """Warning when the standards are far from the model of a volume (empty when they are not)."""
        worst = max(fit["relative"] for fit in calibration["volumes"])
        if worst <= DUAL_RESIDUAL_LIMIT:
            return ""
        return self.logic.colored(
            f"The standards are {100 * worst:.0f} % off the model of the volumes: the values are not reliable. "
            "Check the segments of the standards.",
            "warn",
        )

    def _dualVolumeProperties(self, samples: List[np.ndarray]) -> Tuple[List[dict], dict]:
        """Electron density, Zeff and bulk density of each class from the gray values of the volumes, measured on
        the standards: the values of the median voxel of the class, and the spread (standard deviation) of its
        voxels. Returns (properties as `Logic.clusterProperties` does, the calibration of the volumes)."""
        calibration = self._dualDensityCalibration()
        rng = np.random.default_rng(0)
        properties = []
        for values in samples:
            median = self.logic.densityAndZeff(
                np.median(values, axis=0), calibration["volumes"], calibration["exponent"]
            )[0]
            some = values[rng.choice(len(values), min(len(values), 20_000), replace=False)]
            spread = self.logic.densityAndZeff(some, calibration["volumes"], calibration["exponent"])
            with np.errstate(all="ignore"):
                deviation = np.nanstd(spread, axis=0) if np.isfinite(spread).any() else np.full(3, np.nan)
            values_, sd_ = list(median), list(deviation)
            if np.isfinite(values_[2]) and values_[2] < PORE_DENSITY_LIMIT:  # almost nothing: Zeff is a ratio of noise
                values_[1], sd_[1] = float("nan"), float("nan")
            properties.append({"pixels": len(values), "values": tuple(values_), "sd": tuple(sd_)})
        return properties, calibration

    def _dualClassProperties(self, samples: List[np.ndarray]) -> Tuple[Optional[List[dict]], str]:
        """(properties, note) of the classes whose voxels in the slice are `samples`: electron density, Zeff and bulk
        density measured in the volumes with the standards. Properties is None, and the note says why, when the
        References do not allow it."""
        try:
            properties, calibration = self._dualVolumeProperties(samples)
        except ValueError as error:
            return None, f"{error} The electron density, Zeff and bulk density of the classes need them."
        return properties, self._dualCalibrationNote(calibration)

    def _spectralAgreement(self, predicted: np.ndarray, names: List[str], found: dict, region) -> Optional[tuple]:
        """(share of the pixels, share of those 2 pixels away from the borders of the classes) of the slice of the
        multi-energy scan where the 3D result, `predicted` in that slice of the volumes, gives the class that the
        multi-energy segmentation gives, or None when there is nothing to compare. `names` are the classes of the
        result in order; `region` the SOI of the Input section on its grid, or None."""
        from scipy.ndimage import binary_erosion

        node, volumeNode = self.dualGaussiansSelector.currentNode(), self.inputSelector.currentNode()
        segmentation = node.GetSegmentation()
        full = np.zeros(tuple(reversed(volumeNode.GetImageData().GetDimensions()))[1:], dtype=np.uint8)  # [y, x]
        for n in range(segmentation.GetNumberOfSegments()):
            name = segmentation.GetNthSegment(n).GetName()
            mask = self.logic.soiMask(node, [segmentation.GetNthSegmentID(n)], volumeNode)
            if mask is not None and name in names:
                full[mask & (full == 0)] = names.index(name) + 1
        truth = self.logic.mapToVolume(full, predicted.shape, found["scale"], found["offset"])
        inside = (
            np.ones(predicted.shape, dtype=bool)
            if region is None
            else self.logic.mapToVolume(
                region.astype(np.uint8), predicted.shape, found["scale"], found["offset"]
            ).astype(bool)
        )
        compared = inside & (truth > 0)
        if not compared.any():
            return None
        interior = np.zeros_like(compared)
        for k in range(1, len(names) + 1):
            interior |= binary_erosion(truth == k, iterations=2)
        interior &= compared
        agree = predicted == truth
        return float(agree[compared].mean()), float(agree[interior].mean()) if interior.any() else float("nan")

    def _onDualClicked(self, *args):
        problem = self._dualProblem()
        if problem:
            slicer.util.errorDisplay(problem)
            return
        lowNode, highNode = self._dualVolumes()
        shape = tuple(reversed(lowNode.GetImageData().GetDimensions()))
        memory = self.dualWorkingMemoryGB * 2**30
        clustering = self._dualMethod() == "cluster"
        needed = self._dualMemoryNeeded(shape, self._dualClassCount())
        available = self.logic.availableMemory()
        if available is not None and needed > 0.9 * available:
            slicer.util.errorDisplay(
                f"The segmentation needs about {needed / 2**30:.1f} GB and only {available / 2**30:.1f} GB of RAM are "
                "free. Crop the volumes or lower the working memory."
            )
            return
        found = region = names = colors = None
        try:
            if not clustering:
                found = self._registerDualSlice()
                if found["score"] < REGISTRATION_SCORE_LIMIT and not slicer.util.confirmYesNoDisplay(
                    f"The correlation of the slice is only {found['score']:.2f}: it may not be the same cross "
                    "section. Segment anyway?"
                ):
                    return
                names, colors, classes, region = self._dualClassImages()
            regionVolume = self._dualRegion(shape, fromInput=not clustering)
            slicer.app.setOverrideCursor(qt.Qt.WaitCursor)
            try:
                volumes = [slicer.util.arrayFromVolume(node) for node in (lowNode, highNode)]
                if clustering:
                    clusters, clusterSamples = self.logic.clusterGrayVolumes(
                        volumes, regionVolume, self.dualClustersSpinBox.value
                    )
                    kept = list(range(len(clusters)))
                else:
                    samples = self.logic.sampleClassVoxels(
                        volumes, found["z"], classes, found["scale"], found["offset"], len(names), 0.0
                    )
                    clusters, kept = self.logic.fitGrayGaussians(samples)
                    clusterSamples = [samples[k] for k in kept]
            finally:
                slicer.app.restoreOverrideCursor()
        except ValueError as error:
            slicer.util.errorDisplay(str(error))
            return
        if len(clusters) < 2:
            slicer.util.errorDisplay(
                f"Fewer than two classes have {SUPERVISED_MIN_SAMPLES} voxels in the slice of the volumes: "
                "check the registration and the classes."
            )
            return
        properties, note = self._dualClassProperties(clusterSamples)
        minerals = None
        if properties is not None:
            minerals = [
                self.logic.suggestMineral(item["values"][1], item["values"][2], DEFAULT_Z_EXPONENT)[0]
                for item in properties
            ]
        if clustering:  # the clusters are named after the mineral they suggest, and numbered when they repeat
            base = [(minerals[k] if minerals and minerals[k] else f"Cluster {k + 1}") for k in range(len(clusters))]
            clusterNames = self.logic.uniqueSegmentNames(base)
            clusterColors = [SERIES_COLORS[k % len(SERIES_COLORS)] for k in range(len(clusters))]
            for item, name_, color, voxels in zip(clusters, clusterNames, clusterColors, clusterSamples):
                item["name"], item["color"], item["samples"] = name_, color, len(voxels)
            skipped = []
        else:
            for item, k in zip(clusters, kept):
                item["name"], item["color"], item["samples"] = names[k], colors[k], len(samples[k])
            skipped = [names[k] for k in range(len(names)) if k not in kept]
        outputName = self.dualOutputNameLineEdit.text or self.dualOutputNameLineEdit.placeholderText
        labelNode = self.logic.createLabelVolume(
            lowNode, [item["name"] for item in clusters], [item["color"] for item in clusters], outputName
        )
        labels = slicer.util.arrayFromVolume(labelNode)
        dialog, update = self._progressDialog("Segmenting the 3D volumes...")
        try:
            result = self.logic.classifyGrayVolumes(
                volumes,
                clusters,
                labels,
                self.dualConfidenceSpinBox.value / 100.0,
                0.0,  # the volumes are used as they are: a filter, if wanted, is applied to them first
                memory,
                update,
                regionVolume,
                None,
            )
        finally:
            dialog.close()
        if result is None:
            colorNode = labelNode.GetDisplayNode().GetColorNode()
            slicer.mrmlScene.RemoveNode(labelNode)
            slicer.mrmlScene.RemoveNode(colorNode)
            self.dualStatusLabel.setText(self.logic.colored("Stopped.", "warn"))
            return
        labelNode.Modified()
        agreement = (
            self._spectralAgreement(labels[found["z"]], [item["name"] for item in clusters], found, region)
            if found is not None
            else None
        )
        segmentationNode = self._dualSegmentation(labelNode)
        for item, counted in zip(clusters, result["counts"]):
            item["count"] = counted
        leftOut = 100.0 * (1.0 - sum(result["counts"]) / max(result["valid"], 1))
        if properties is not None:
            for item, counted in zip(properties, result["counts"]):
                item["pixels"] = counted  # the share is of the voxels of the 3D result
            header, rows = self.logic.propertiesTable(
                [item["name"] for item in clusters], minerals, properties, unit="Voxels"
            )
            tableNode = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLTableNode", f"{segmentationNode.GetName()}_properties"
            )
            self._writePropertiesTable(tableNode, header, rows)
            self.logic._placeNextTo(segmentationNode, tableNode)
        text = self._describeRegistration(found) if found is not None else ""
        text += self.logic.describeDualClasses(
            clusters,
            self.dualConfidenceSpinBox.value,
            leftOut,
            properties,
            minerals,
            [] if clustering else [(names[k], colors[k]) for k in range(len(names)) if k not in kept],
        )
        if agreement is not None:
            text += (
                f"<p>Agreement with the classes of the multi-energy scan in its slice: <b>{100 * agreement[0]:.0f} %</b> "
                f"of its pixels ({100 * agreement[1]:.0f} % away from the borders of the classes).</p>"
            )
        if properties is not None:
            text += (
                "<p>Electron density, Zeff and bulk density measured in the volumes with the standards "
                "(\u00b1 is the spread of the voxels).</p>"
            )
        if note:
            text += self.logic.colored(note, "warn")
        if skipped:
            text += self.logic.colored(
                f"Not learned (fewer than {SUPERVISED_MIN_SAMPLES} voxels in the slice): {', '.join(skipped)}.", "warn"
            )
        if regionVolume is None:
            text += self.logic.colored("No SOI: the whole volume was classified, including holder and air.", "warn")
        self.dualStatusLabel.setText(text)
        slicer.util.setSliceViewerLayers(background=lowNode)


class ProgressHandle:
    """What `SpectralProfileWidget._progressDialog` gives back, to hide the progress bar of the section."""

    def __init__(self, close: Callable[[], None]):
        self.close = close


class SpectralProfileLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    # ----- naming -----
    @staticmethod
    def defaultOutputName(volumeName: str, exponent: float, clusters: int, method: str = "gmm") -> str:
        """Name of the outputs, which records the settings: <volume>_spectral_b<|exponent|>_classes<clusters>_<method>
        (the method as in CLUSTER_METHODS: gmm, kmeans, ward...)."""
        return f"{volumeName}_spectral_b{abs(exponent):g}_classes{clusters}_{method}" if volumeName else ""

    # ----- axis -----
    @staticmethod
    def sliceCount(volumeNode) -> int:
        return volumeNode.GetImageData().GetDimensions()[2]

    @staticmethod
    def axisExtent(axis: np.ndarray, size: int) -> Tuple[float, float]:
        """x range covered by `size` image columns centered on the axis values (half a step of padding)."""
        axis = np.asarray(axis, dtype=float)
        if axis.size < 2:
            return -0.5, size - 0.5
        step = abs(axis[-1] - axis[0]) / (axis.size - 1) or 1.0
        return min(axis[0], axis[-1]) - step / 2, max(axis[0], axis[-1]) + step / 2

    @staticmethod
    def energyEdges(axis: np.ndarray) -> np.ndarray:
        """Boundaries between the energies: size + 1 values, halfway between neighbours, extended at both ends."""
        axis = np.asarray(axis, dtype=float)
        if axis.size < 2:
            return np.array([axis[0] - 0.5, axis[0] + 0.5])
        middle = 0.5 * (axis[1:] + axis[:-1])
        return np.concatenate([[axis[0] - (middle[0] - axis[0])], middle, [axis[-1] + (axis[-1] - middle[-1])]])

    @staticmethod
    def selectEnergyRange(axis: np.ndarray, low: float, high: float) -> np.ndarray:
        """Indices of the energies whose axis value is between `low` and `high` (inclusive, in any order)."""
        axis = np.asarray(axis, dtype=float)
        low, high = sorted((low, high))
        tolerance = 1e-6 * max(abs(high - low), 1.0)
        return np.flatnonzero((axis >= low - tolerance) & (axis <= high + tolerance))

    @staticmethod
    def unusedRuns(selection: np.ndarray, size: int) -> List[Tuple[int, int]]:
        """Contiguous (first, last) index runs of the energies that are not in `selection`."""
        used = np.zeros(size, dtype=bool)
        used[np.asarray(selection, dtype=int)] = True
        runs, start = [], None
        for k in range(size):
            if not used[k] and start is None:
                start = k
            if used[k] and start is not None:
                runs.append((start, k - 1))
                start = None
        if start is not None:
            runs.append((start, size - 1))
        return runs

    # ----- SOI and histogram -----
    @staticmethod
    def soiMask(segmentationNode, segmentIds: List[str], volumeNode) -> Optional[np.ndarray]:
        """Union of the given segments as a 2D [j, i] mask in the volume's grid.

        The z axis of these volumes is spectral, so a segment drawn on a single slice is taken to cover that
        (j, i) region in every energy: the mask is collapsed (any) along z.
        """
        mask = None
        for segmentId in segmentIds:
            try:
                array = np.asarray(arrayFromSegmentBinaryLabelmap(segmentationNode, segmentId, volumeNode), dtype=bool)
            except RuntimeError:
                continue
            plane = array.any(axis=0) if array.ndim == 3 else array
            mask = plane if mask is None else (mask | plane)
        return mask

    @staticmethod
    def backgroundValues(array: np.ndarray) -> np.ndarray:
        """Most frequent intensity of each z slice. For samples surrounded by air this is the air value, which the
        reconstruction usually pins to a constant (it does not change with energy)."""
        background = np.empty(array.shape[0], dtype=float)
        for k in range(array.shape[0]):
            slice_ = array[k]
            if slice_.dtype.kind == "u":
                background[k] = np.bincount(slice_.ravel()).argmax()
            else:
                counts, edges = np.histogram(slice_, bins=4096)
                background[k] = 0.5 * (edges[counts.argmax()] + edges[counts.argmax() + 1])
        return background

    @staticmethod
    def _attenuation(slice_: np.ndarray, k: int, background: np.ndarray, mask=None) -> np.ndarray:
        """Attenuation above air of the pixels of one slice (inside the 2D `mask` if given)."""
        values = slice_[mask] if mask is not None else slice_.ravel()
        return values.astype(float) - background[k]

    @classmethod
    def robustRange(
        cls,
        array: np.ndarray,
        background: np.ndarray,
        mask=None,
        lowPercentile: float = 0.01,
        highPercentile: float = 99.99,
    ) -> Tuple[float, float]:
        """Range of the attenuation ignoring a few extreme voxels (e.g. saturated pixels), estimated on a subsample."""
        nz = array.shape[0]
        step = max(nz // 16, 1)
        sy, sx = max(array.shape[1] // 128, 1), max(array.shape[2] // 128, 1)
        slices = sorted(set(range(0, nz, step)) | {nz - 1})
        sub = array[:, ::sy, ::sx]
        sampleMask = mask[::sy, ::sx] if mask is not None else None
        sample = np.concatenate([cls._attenuation(sub[k], k, background, sampleMask) for k in slices])
        if sample.size == 0:
            return 0.0, 1.0
        low, high = np.percentile(sample, [lowPercentile, highPercentile])
        if high <= low:
            high = low + 1.0
        return float(low), float(high)

    @classmethod
    def histogramPerSlice(
        cls, array: np.ndarray, bins: int, low: float, high: float, background: np.ndarray, mask=None
    ) -> np.ndarray:
        """Number of pixels per attenuation bin for each z slice -> [slices, bins]. Out-of-range pixels are clipped
        into the first/last bin."""
        factor = bins / (high - low)
        counts = np.zeros((array.shape[0], bins), dtype=np.int64)
        for k in range(array.shape[0]):
            values = cls._attenuation(array[k], k, background, mask)
            index = np.clip(((values - low) * factor).astype(np.int64), 0, bins - 1)
            counts[k] = np.bincount(index, minlength=bins)
        return counts

    def computeHeatmap(
        self, array: np.ndarray, bins: int, background: np.ndarray, mask=None
    ) -> Tuple[np.ndarray, float, float]:
        low, high = self.robustRange(array, background, mask)
        return self.histogramPerSlice(array, bins, low, high, background, mask), low, high

    # ----- power-law fit and clustering -----
    @staticmethod
    def powerLawFit(
        array: np.ndarray,
        axis: np.ndarray,
        exponent: float,
        selection: np.ndarray,
        background: np.ndarray,
        mask: Optional[np.ndarray] = None,
        chunk: int = 65536,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Least-squares fit of  attenuation = a * (E / E0) ** exponent + c  to every pixel -> (a, c, valid), each
        [j, i]. The attenuation is the gray value minus the air value of each slice and only the energies in
        `selection` (slice indices) are used. With the exponent fixed the model is linear in (a, c), so the fit has
        a closed form. `valid` is the pixels inside `mask` that are not pure air."""
        nz, ny, nx = array.shape
        selection = np.asarray(selection, dtype=int)
        x = (np.asarray(axis, dtype=np.float64)[selection] / POWER_LAW_REFERENCE_ENERGY) ** exponent
        xc = x - x.mean()
        denominator = float(xc @ xc)
        offset = np.asarray(background, dtype=np.float64)[selection]
        pixels = array.reshape(nz, -1)
        indices = np.arange(ny * nx) if mask is None else np.flatnonzero(mask.ravel())
        a = np.zeros(ny * nx, dtype=np.float32)
        c = np.zeros(ny * nx, dtype=np.float32)
        valid = np.zeros(ny * nx, dtype=bool)
        for start in range(0, len(indices), chunk):
            block = indices[start : start + chunk]
            y = pixels[np.ix_(selection, block)].T.astype(np.float64) - offset  # [pixels, energies]
            slope = (y @ xc) / denominator if denominator > 0 else np.zeros(len(block))
            a[block] = slope
            c[block] = y.mean(axis=1) - slope * x.mean()
            valid[block] = np.any(y != 0, axis=1)
        return a.reshape(ny, nx), c.reshape(ny, nx), valid.reshape(ny, nx)

    @staticmethod
    def _logJoint(points, centers, weights, covariances) -> np.ndarray:
        """log(weight * Gaussian density) of every point for every component -> [points, k]."""
        dim = points.shape[1]
        out = np.empty((len(points), len(centers)))
        for n, (center, covariance) in enumerate(zip(centers, covariances)):
            delta = points - center
            inverse = np.linalg.inv(covariance)
            mahalanobis = np.einsum("ij,jk,ik->i", delta, inverse, delta)
            logDet = np.linalg.slogdet(covariance)[1]
            out[:, n] = np.log(max(weights[n], 1e-12)) - 0.5 * (mahalanobis + logDet + dim * np.log(2 * np.pi))
        return out

    @staticmethod
    def _mixtureInputs(c: np.ndarray, a: np.ndarray, valid: np.ndarray, seed: int):
        """Features of the valid pixels, standardized, and the random subsample of inliers the mixture is fitted on
        -> (features, scale, shift, normalized, sample).

        The mixture is fitted without the extreme pixels (noise, saturation), or a component would be wasted on
        them."""
        features = np.column_stack([c[valid], a[valid]]).astype(np.float64)
        scale = features.std(axis=0)
        scale[scale == 0] = 1.0
        shift = features.mean(axis=0)
        normalized = (features - shift) / scale
        low, high = np.percentile(normalized, [0.5, 99.5], axis=0)
        inliers = np.flatnonzero(np.all((normalized >= low) & (normalized <= high), axis=1))
        rng = np.random.default_rng(seed)
        sample = rng.choice(inliers, size=min(len(inliers), CLUSTER_FIT_SAMPLES), replace=False)
        return features, scale, shift, normalized, sample

    @staticmethod
    def fitClusters(
        c: np.ndarray, a: np.ndarray, valid: np.ndarray, clusters: int, seed: int = 0, method: str = "gmm"
    ) -> dict:
        """Cluster the (c, a) cloud of the valid pixels, before deciding who belongs where, with a Gaussian mixture
        or, with another `method` (see CLUSTER_METHODS), a clustering of a sample of the pixels whose clusters are
        described by their mean and covariance and the pixels get the probability of those Gaussians.

        Returns `posterior` (probability of each valid pixel for each cluster, [pixels, clusters]), `clusters` (mean
        as (c, a), covariance and weight of each) and `valid`. Clusters are numbered by increasing c (density)."""
        from sklearn.mixture import GaussianMixture

        features, scale, shift, normalized, sample = SpectralProfileLogic._mixtureInputs(c, a, valid, seed)
        clusters = min(clusters, len(sample))
        if method != "gmm":
            return SpectralProfileLogic._fitByMoments(
                features, scale, shift, normalized, sample, clusters, seed, method, valid
            )
        mixture = GaussianMixture(clusters, covariance_type="full", random_state=seed, n_init=2)
        mixture.fit(normalized[sample])
        fittedMeans = mixture.means_ * scale + shift
        order = np.argsort(fittedMeans[:, 0])
        described = [
            {
                "mean": fittedMeans[k],
                "cov": scale[:, None] * mixture.covariances_[k] * scale[None, :],
                "weight": float(mixture.weights_[k]),
            }
            for k in order
        ]
        return {"posterior": mixture.predict_proba(normalized)[:, order], "clusters": described, "valid": valid}

    @staticmethod
    def _fitByMoments(features, scale, shift, normalized, sample, clusters, seed, method, valid) -> dict:
        """`fitClusters` for the methods that do not give Gaussians: cluster the sample, take the mean, covariance
        and share of each cluster and let the pixels have the posterior of those Gaussians."""
        if method == "kmeans":
            from sklearn.cluster import KMeans

            labels = KMeans(clusters, random_state=seed, n_init=4).fit_predict(normalized[sample])
        else:
            from sklearn.cluster import AgglomerativeClustering

            rng = np.random.default_rng(seed)
            few = rng.choice(sample, size=min(len(sample), HIERARCHICAL_SAMPLES), replace=False)
            sample = few
            labels = AgglomerativeClustering(clusters, linkage=method).fit_predict(normalized[few])
        centers, covariances, weights = [], [], []
        for k in range(clusters):
            points = normalized[sample][labels == k]
            if len(points) == 0:
                continue
            centers.append(points.mean(axis=0))
            covariance = np.cov(points.T) if len(points) > 2 else np.zeros((2, 2))
            covariances.append(np.atleast_2d(covariance) + 1e-4 * np.eye(2))  # a single point has no spread
            weights.append(len(points) / len(sample))
        logProb = SpectralProfileLogic._logJoint(normalized, centers, weights, covariances)
        logProb -= logProb.max(axis=1, keepdims=True)
        posterior = np.exp(logProb)
        posterior /= posterior.sum(axis=1, keepdims=True)
        means = np.array(centers) * scale + shift
        order = np.argsort(means[:, 0])
        described = [
            {
                "mean": means[k],
                "cov": scale[:, None] * covariances[k] * scale[None, :],
                "weight": float(weights[k]),
            }
            for k in order
        ]
        return {"posterior": posterior[:, order], "clusters": described, "valid": valid}

    @staticmethod
    def assignClusters(
        model: dict, groups: Optional[List[List[int]]] = None, minProbability: float = 0.0
    ) -> Tuple[np.ndarray, List[int]]:
        """Label the pixels of a `fitClusters` model -> ([j, i] labels (1-based, 0 = left out), pixels of each group).

        Each group is one or more clusters taken together (by default every cluster is a group). A pixel goes to the
        group with the highest probability, the sum over its clusters, which is why the pieces of one material that
        the mixture split in two still count as decided. Pixels whose best probability is below `minProbability`
        (0 to 1) are the undecided ones, between groups or far from all, and are left out."""
        posterior = model["posterior"]
        groups = groups if groups is not None else [[k] for k in range(posterior.shape[1])]
        grouped = np.stack([posterior[:, group].sum(axis=1) for group in groups], axis=1)
        best = grouped.argmax(axis=1)
        sure = grouped.max(axis=1) >= minProbability
        labels = np.zeros(model["valid"].shape, dtype=np.uint8)
        labels[model["valid"]] = np.where(sure, best + 1, 0)
        return labels, [int(np.sum((best == k) & sure)) for k in range(len(groups))]

    @classmethod
    def clusterParameters(
        cls,
        c: np.ndarray,
        a: np.ndarray,
        valid: np.ndarray,
        clusters: int,
        seed: int = 0,
        minProbability: float = 0.0,
        method: str = "gmm",
    ) -> Tuple[np.ndarray, List[dict]]:
        """Cluster the (c, a) cloud of the valid pixels -> ([j, i] labels (1-based, 0 = not clustered), description
        of each cluster with its mean as (c, a) and its pixel `count`). Clusters are numbered by increasing c.

        Pixels whose most probable cluster has a probability below `minProbability` (0 to 1) are the undecided ones
        and are left out: they get label 0 and are not counted."""
        model = cls.fitClusters(c, a, valid, clusters, seed, method)
        labels, counts = cls.assignClusters(model, None, minProbability)
        return labels, [dict(cluster, count=count) for cluster, count in zip(model["clusters"], counts)]

    @staticmethod
    def gaussianShape(cov: np.ndarray) -> Tuple[float, float, float]:
        """(angle of the major axis, sigma along it, sigma along the minor axis) of a 2D covariance."""
        values, vectors = np.linalg.eigh(np.asarray(cov, dtype=float))
        sigmas = np.sqrt(np.maximum(values, 1e-12))
        major = vectors[:, 1]
        return float(np.arctan2(major[1], major[0])), float(sigmas[1]), float(sigmas[0])

    @staticmethod
    def gaussianCov(angle: float, sigmaMajor: float, sigmaMinor: float) -> np.ndarray:
        rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        return rotation @ np.diag([sigmaMajor**2, sigmaMinor**2]) @ rotation.T

    @staticmethod
    def encodeGaussians(clusters: List[dict], fit: dict) -> str:
        """JSON with the Gaussians of `clusters` (each with its `segmentId`) and the `fit` they belong to (exponent,
        energies and axis ends), to be kept on the segmentation so that it can be adjusted later as it was made."""
        import json

        return json.dumps(
            {
                "fit": fit,
                "clusters": [
                    {
                        "segmentId": cluster["segmentId"],
                        "mean": [float(v) for v in cluster["mean"]],
                        "cov": [[float(v) for v in row] for row in cluster["cov"]],
                        "weight": float(cluster["weight"]),
                    }
                    for cluster in clusters
                ],
            }
        )

    @staticmethod
    def decodeGaussians(text: str, fit: dict, segmentIds: List[str]) -> Optional[List[dict]]:
        """The Gaussians kept by `encodeGaussians`, in the order of `segmentIds`, or None when there are none, they
        were made with another fit (exponent, energies, axis) or the segments are not the same."""
        import json

        try:
            stored = json.loads(text)
            if stored["fit"] != fit or sorted(item["segmentId"] for item in stored["clusters"]) != sorted(segmentIds):
                return None
            byId = {item["segmentId"]: item for item in stored["clusters"]}
            return [
                {
                    "segmentId": segmentId,
                    "mean": np.array(byId[segmentId]["mean"], dtype=float),
                    "cov": np.array(byId[segmentId]["cov"], dtype=float),
                    "weight": float(byId[segmentId]["weight"]),
                }
                for segmentId in segmentIds
            ]
        except (TypeError, ValueError, KeyError):
            return None

    @staticmethod
    def propertiesTable(
        names: List[str], minerals: List[str], properties: List[dict], unit: str = "Pixels"
    ) -> Tuple[List[str], List[list]]:
        """(column names, rows) of the table with the estimated properties of each segment; `unit` is what its
        `pixels` count (pixels of an image, voxels of a volume)."""
        total = max(sum(item["pixels"] for item in properties), 1)
        header = [
            "Segment",
            f"{unit} (%)",
            "Electron density (mol/cm3)",
            "Electron density err",
            "Zeff",
            "Zeff err",
            "Bulk density (g/cm3)",
            "Bulk density err",
            "Mineral",
        ]
        rows = []
        for name, mineral, item in zip(names, minerals, properties):
            (electron, zeff, density), (sdElectron, sdZeff, sdDensity) = item["values"], item["sd"]
            rows.append(
                [name, 100.0 * item["pixels"] / total, electron, sdElectron, zeff, sdZeff, density, sdDensity, mineral]
            )
        return header, rows

    @staticmethod
    def segmentGaussians(
        c: np.ndarray, a: np.ndarray, valid: np.ndarray, masks: List[np.ndarray], minPixels: int = MIN_STANDARD_PIXELS
    ) -> Tuple[List[dict], np.ndarray]:
        """Gaussian of each segment in the (c, a) plane, to adjust a segmentation made by something else.

        `masks` are the 2D masks of the segments. For each one with at least `minPixels` valid pixels, the mean and
        covariance of their (c, a) and their share of the pixels are taken. Returns those clusters (each with the
        `index` of its mask) and their labels [j, i] (1-based, in that order, 0 elsewhere)."""
        labels = np.zeros(valid.shape, dtype=np.uint8)
        clusters = []
        for index, mask in enumerate(masks):
            pixels = mask & valid
            count = int(pixels.sum())
            if count < minPixels:
                continue
            features = np.column_stack([c[pixels], a[pixels]]).astype(np.float64)
            clusters.append(
                {
                    "mean": features.mean(axis=0),
                    "cov": np.cov(features.T) + 1e-9 * np.eye(2),
                    "weight": float(count),
                    "count": count,
                    "index": index,
                }
            )
            labels[pixels] = len(clusters)
        total = max(sum(cluster["weight"] for cluster in clusters), 1.0)
        for cluster in clusters:
            cluster["weight"] /= total
        return clusters, labels

    @classmethod
    def classifyByGaussians(
        cls, c: np.ndarray, a: np.ndarray, valid: np.ndarray, clusters: List[dict], minProbability: float = 0.0
    ) -> Tuple[np.ndarray, List[int]]:
        """Label the valid pixels with the Gaussians of `clusters` as they are (after being edited) -> ([j, i] labels
        (1-based, in the order of `clusters`, 0 = left out), pixels of each cluster).

        A pixel goes to the Gaussian with the highest weight times density at its (c, a); if that Gaussian's share of
        the total is below `minProbability` the pixel is undecided and left out."""
        features = np.column_stack([c[valid], a[valid]]).astype(np.float64)
        logProb = cls._logJoint(
            features,
            np.array([k["mean"] for k in clusters]),
            np.array([k["weight"] for k in clusters]),
            np.array([k["cov"] for k in clusters]),
        )
        top = logProb.max(axis=1, keepdims=True)
        posterior = np.exp(logProb - top) / np.exp(logProb - top).sum(axis=1, keepdims=True)
        best = posterior.argmax(axis=1)
        sure = posterior.max(axis=1) >= minProbability
        labels = np.zeros(valid.shape, dtype=np.uint8)
        labels[valid] = np.where(sure, best + 1, 0)
        return labels, [int(np.sum((best == k) & sure)) for k in range(len(clusters))]

    # ----- fewer energies (e.g. dual energy) with the Gaussians of the full fit -----
    @staticmethod
    def parseGaussians(text: str) -> Optional[Tuple[dict, List[dict]]]:
        """(fit, clusters) kept on a segmentation by `encodeGaussians`, whatever fit they belong to, or None when the
        text is empty or not what `encodeGaussians` writes. Each cluster has its `segmentId`, mean, cov and weight."""
        import json

        try:
            stored = json.loads(text)
            clusters = [
                {
                    "segmentId": item["segmentId"],
                    "mean": np.array(item["mean"], dtype=float),
                    "cov": np.array(item["cov"], dtype=float),
                    "weight": float(item["weight"]),
                }
                for item in stored["clusters"]
            ]
            return stored["fit"], clusters
        except (TypeError, ValueError, KeyError):
            return None

    @staticmethod
    def blockVoxels(clusterCount: int, memoryBytes: float) -> int:
        """Voxels per block that keep the working arrays of the classification within `memoryBytes`."""
        return max(int(memoryBytes // (DUAL_BYTES_BASE + DUAL_BYTES_PER_CLUSTER * clusterCount)), 1024)

    @staticmethod
    def estimateDualMemory(shape: Tuple[int, int, int], clusterCount: int, memoryBytes: float) -> int:
        """Bytes the segmentation of a volume adds: the labels (one byte per voxel) and the working arrays of a block
        (never more than the volume itself needs)."""
        voxels = int(np.prod(shape))
        block = min(voxels, SpectralProfileLogic.blockVoxels(clusterCount, memoryBytes))
        return voxels + block * (DUAL_BYTES_BASE + DUAL_BYTES_PER_CLUSTER * clusterCount)

    @staticmethod
    def normalizedCrossCorrelation(image: np.ndarray, template: np.ndarray) -> np.ndarray:
        """Correlation coefficient of `template` with every window of `image` of its size -> [positions]
        (the template at the position (i, j) covers image[i : i + h, j : j + w]). It does not change with the gain
        and offset of either image, which is what lets two scans with their own gray scale be compared."""
        from scipy.signal import fftconvolve

        image, template = np.asarray(image, dtype=np.float64), np.asarray(template, dtype=np.float64)
        count = template.size
        centered = template - template.mean()
        window = np.ones_like(template)
        total = fftconvolve(image, window, mode="valid")
        squares = fftconvolve(image**2, window, mode="valid")
        cross = fftconvolve(image, centered[::-1, ::-1], mode="valid")
        spread = np.sqrt(np.maximum(squares - total**2 / count, 1e-12)) * np.sqrt((centered**2).sum())
        return cross / spread

    @staticmethod
    def _shrink(image: np.ndarray, factor: float) -> np.ndarray:
        """`image` resampled by `factor` (smoothed first when it gets smaller, so that it does not alias)."""
        from scipy.ndimage import gaussian_filter, zoom

        image = np.asarray(image, dtype=np.float32)
        if factor < 1.0:
            image = gaussian_filter(image, 0.5 / factor)
        return zoom(image, factor, order=1, mode="nearest")  # not zeros beyond the edge, which are no data

    @classmethod
    def _bestPosition(cls, reference: np.ndarray, moving: np.ndarray) -> Tuple[float, Tuple[int, int]]:
        """(correlation, position of `moving` over `reference`) at the best translation. The position is the one
        of the origin of `moving` in the pixels of `reference` (negative when it starts before it). The smaller
        image is slid over the larger one."""
        if moving.shape[0] <= reference.shape[0] and moving.shape[1] <= reference.shape[1]:
            score = cls.normalizedCrossCorrelation(reference, moving)
            index = np.unravel_index(int(np.argmax(score)), score.shape)
            return float(score[index]), (int(index[0]), int(index[1]))
        score = cls.normalizedCrossCorrelation(moving, reference)
        index = np.unravel_index(int(np.argmax(score)), score.shape)
        return float(score[index]), (-int(index[0]), -int(index[1]))

    @classmethod
    def registerSlice(
        cls,
        reference: np.ndarray,
        referenceSpacing: float,
        volume: np.ndarray,
        volumeSpacing: float,
        zRange: Optional[Tuple[int, int]] = None,
        progress: Optional[Callable[[float], bool]] = None,
    ) -> Optional[dict]:
        """Where a 2D `reference` image (a slice of another scan of the same sample, with its own pixel size) is in a
        3D `volume` [z, y, x] -> `z` (the slice of the volume), `offset` (position of the origin of that slice in the
        pixels of the reference, as (y, x), so that a voxel (y, x) is at the reference pixel
        (y, x) / `scale` + `offset`), `scale` (voxels of the volume per pixel of the reference) and `score` (the
        correlation, 1 is identical; below REGISTRATION_SCORE_LIMIT it is probably not the same cross section).

        Only translation is searched, which is what two scans of a sample in the same holder need. The slices of the
        volume are tried every REGISTRATION_STEP_MM on shrunk images, and the best one is refined slice by slice, on
        the full images, around its position. `progress(fraction)` returns False to stop (the result is then None)."""
        from scipy.ndimage import gaussian_filter

        scale = referenceSpacing / volumeSpacing
        nz = volume.shape[0]
        low, high = zRange if zRange is not None else (0, nz)
        low, high = max(int(low), 0), min(int(high), nz)
        if high <= low:
            raise ValueError("There are no slices to look in.")
        shrink = REGISTRATION_SEARCH_SHRINK
        coarse = cls._shrink(gaussian_filter(np.asarray(reference, dtype=np.float32), 1.5), shrink)
        step = max(int(round(REGISTRATION_STEP_MM / volumeSpacing)), 1)
        candidates = list(range(low, high, step)) or [low]
        scores = {}
        for number, z in enumerate(candidates):
            moving = cls._shrink(volume[z], shrink / scale)
            scores[z] = cls._bestPosition(coarse, moving)
            if progress is not None and not progress(0.6 * (number + 1) / len(candidates)):
                return None
        first = max(candidates, key=lambda z: scores[z][0])
        smooth = gaussian_filter(np.asarray(reference, dtype=np.float32), 1.5)
        refined = {}
        around = list(range(max(first - step, low), min(first + step, high - 1) + 1))
        for number, z in enumerate(around):
            moving = cls._shrink(volume[z], 1.0 / scale)
            y0, x0 = (int(round(v / shrink)) for v in scores[first][1])
            pad = REGISTRATION_REFINE_PIXELS
            height, width = moving.shape
            top, left = max(y0 - pad, 0), max(x0 - pad, 0)
            window = smooth[top : max(y0 + height + pad, 0), left : max(x0 + width + pad, 0)]
            if y0 >= 0 and x0 >= 0 and window.shape[0] >= height and window.shape[1] >= width:
                score, (iy, ix) = cls._bestPosition(window, moving)
                refined[z] = (score, (iy + top, ix + left))
            else:  # the volume reaches outside the reference: look on the whole of it
                refined[z] = cls._bestPosition(smooth, moving)
            if progress is not None and not progress(0.6 + 0.4 * (number + 1) / len(around)):
                return None
        z = max(refined, key=lambda key: refined[key][0])
        score, offset = refined[z]
        return {
            "z": int(z),
            "offset": (float(offset[0]), float(offset[1])),
            "scale": float(scale),
            "score": float(score),
            "scores": {int(k): float(v[0]) for k, v in scores.items()},
        }

    @staticmethod
    def referenceGrid(shape: Tuple[int, int], scale: float, offset: Tuple[float, float], size: Tuple[int, int]):
        """Where each voxel (y, x) of a slice of `shape` falls in a reference image of `size`: ([ny] rows, [nx] columns,
        [ny] inside, [nx] inside) as the nearest pixel (clipped) and whether it is in the image."""
        rows = np.rint(np.arange(shape[0]) / scale + offset[0]).astype(int)
        columns = np.rint(np.arange(shape[1]) / scale + offset[1]).astype(int)
        insideRows = (rows >= 0) & (rows < size[0])
        insideColumns = (columns >= 0) & (columns < size[1])
        return np.clip(rows, 0, size[0] - 1), np.clip(columns, 0, size[1] - 1), insideRows, insideColumns

    @classmethod
    def mapToVolume(
        cls, image: np.ndarray, shape: Tuple[int, int], scale: float, offset: Tuple[float, float]
    ) -> np.ndarray:
        """`image` (a 2D array on the grid of the reference: classes, a mask) seen from the voxels of a slice of
        `shape` -> [ny, nx], 0 (False) where the slice is outside the reference."""
        rows, columns, insideRows, insideColumns = cls.referenceGrid(shape, scale, offset, image.shape)
        mapped = np.asarray(image)[rows[:, None], columns[None, :]]
        return np.where(insideRows[:, None] & insideColumns[None, :], mapped, np.zeros((), dtype=mapped.dtype))

    @staticmethod
    def _smoothSlab(volume: np.ndarray, first: int, last: int, halo: int, sigma: float) -> np.ndarray:
        """Slices [first, last) of `volume` as float32, filtered in 3D with a Gaussian of `sigma` voxels. The slab
        is read with `halo` slices more on each side (where they exist), so that its slices are the same as if
        the whole volume had been filtered, and only those of [first, last) are returned."""
        from scipy.ndimage import gaussian_filter

        low, high = max(first - halo, 0), min(last + halo, volume.shape[0])
        slab = np.asarray(volume[low:high], dtype=np.float32)
        if sigma > 0:
            slab = gaussian_filter(slab, sigma, mode="nearest")
        return slab[first - low : last - low]

    @classmethod
    def sampleClassVoxels(
        cls,
        volumes: List[np.ndarray],
        z: int,
        classes: np.ndarray,
        scale: float,
        offset: Tuple[float, float],
        count: int,
        smoothing: float = SUPERVISED_SMOOTHING,
        slices: int = SUPERVISED_SLICES,
    ) -> List[np.ndarray]:
        """Gray values, in every volume, of the voxels of each class of a reference slice -> `count` arrays
        [voxels, volumes]. `classes` is the 2D image of the reference (1..count, 0 = not used) and the voxels of the
        slices z - `slices` to z + `slices` of the volumes are looked up in it (see `registerSlice` for scale and
        offset). The volumes are filtered as `classifyGrayVolumes` will filter them."""
        nz, ny, nx = volumes[0].shape
        labels = cls.mapToVolume(classes, (ny, nx), scale, offset)
        first, last = max(z - slices, 0), min(z + slices + 1, nz)
        halo = int(np.ceil(3 * smoothing)) if smoothing > 0 else 0
        slabs = [cls._smoothSlab(volume, first, last, halo, smoothing) for volume in volumes]
        features = [[] for _ in range(count)]
        for k in range(count):
            inside = labels == k + 1
            for n in range(last - first):
                features[k].append(np.column_stack([slab[n][inside] for slab in slabs]))
        return [np.concatenate(items).astype(np.float64) for items in features]

    @staticmethod
    def fitGrayGaussians(
        samples: List[np.ndarray], minSamples: int = SUPERVISED_MIN_SAMPLES
    ) -> Tuple[List[dict], List[int]]:
        """One Gaussian in the plane of the gray values for each class that has at least `minSamples` voxels
        -> (clusters with mean, cov and weight (the share of the voxels), indices of the classes kept).

        A class is learned from the pixels of a segmentation, which hold some that are not of its material: a saturated
        grain, a voxel mixed with its neighbour. The voxels farther than SUPERVISED_TRIM standard deviations are
        dropped and the Gaussian is fitted again, up to SUPERVISED_TRIM_PASSES times, so that a few of them do not
        decide the covariance. The covariance gets SUPERVISED_VARIANCE_FLOOR of its variance added to the diagonal, to
        stay invertible."""
        kept = [k for k, values in enumerate(samples) if len(values) >= minSamples]
        total = max(sum(len(samples[k]) for k in kept), 1)
        clusters = []
        for k in kept:
            values = np.asarray(samples[k], dtype=np.float64)
            for _ in range(SUPERVISED_TRIM_PASSES):
                mean, covariance = values.mean(axis=0), np.cov(values.T)
                delta = values - mean
                distance = np.einsum("ij,jk,ik->i", delta, np.linalg.pinv(covariance), delta)
                inside = distance <= SUPERVISED_TRIM**2
                if inside.all() or inside.sum() < minSamples:
                    break
                values = values[inside]
            mean, covariance = values.mean(axis=0), np.cov(values.T)
            covariance = covariance + SUPERVISED_VARIANCE_FLOOR * np.diag(np.diag(covariance))
            clusters.append({"mean": mean, "cov": covariance, "weight": len(samples[k]) / total})
        return clusters, kept

    @staticmethod
    def fitDensityCalibration(
        standardGray: List[float],
        airGray: Optional[float],
        electronDensity: List[float],
        zeff: List[float],
        exponent: float,
    ) -> dict:
        """Calibration of one volume against references of known electron density and Zeff.

        The volume holds  gray = air + S * rho * (1 + R * Z ** n)  : the attenuation of a material is its electron
        density rho times (1 + R * Z ** n), where R depends on the energy the volume behaves as, and S is its gray
        scale. It is linear in (air, S, S * R), so the grays of the standards (and the air, with rho = 0) give them
        by least squares. Returns `air`, `scale`, `ratio` (R), `residuals` (gray minus the model), `relative` (the
        worst one over the range of the grays) and `freedom` (references minus the 3 unknowns). Raises ValueError
        with fewer than 3 references or a scale that is not positive."""
        rho = np.asarray(electronDensity, dtype=float)
        q = np.asarray(zeff, dtype=float) ** exponent
        rows, values = [[1.0, r, r * z] for r, z in zip(rho, q)], list(map(float, standardGray))
        if airGray is not None:
            rows.append([1.0, 0.0, 0.0])
            values.append(float(airGray))
        if len(values) < 3:
            raise ValueError("At least three references (standards, and the air) are needed.")
        design, values = np.array(rows), np.array(values)
        solution = np.linalg.lstsq(design, values, rcond=None)[0]
        air, scale, product = (float(v) for v in solution)
        if scale <= 0:
            raise ValueError(
                "The gray values do not grow with the electron density of the standards: check the segments."
            )
        residuals = values - design @ solution
        return {
            "air": air,
            "scale": scale,
            "ratio": product / scale,
            "residuals": [float(v) for v in residuals],
            "relative": float(np.max(np.abs(residuals)) / max(np.ptp(values), 1e-12)),
            "freedom": len(values) - 3,
        }

    @staticmethod
    def densityPlane(values: List[np.ndarray], calibrations: List[dict]) -> List[np.ndarray]:
        """The gray values of the two volumes (`values`, one array each) as (electron density, rho * Zeff ** n), the two
        terms of the model of `fitDensityCalibration` that a voxel is made of, and that follow from its two grays
        linearly: with u = (gray - air) / S  and  u_k = rho + R_k * p  for the two volumes, p = (u_0 - u_1) / (R_0 - R_1)
        and rho = u_0 - R_0 * p. The equivalent of c and a, without the energies."""
        u = [(np.asarray(values[k], dtype=float) - calibrations[k]["air"]) / calibrations[k]["scale"] for k in range(2)]
        difference = calibrations[0]["ratio"] - calibrations[1]["ratio"]
        if abs(difference) < 1e-12:
            raise ValueError("The two volumes behave as the same energy, so they cannot tell the Zeff.")
        p = (u[0] - u[1]) / difference
        return [u[0] - calibrations[0]["ratio"] * p, p]

    @classmethod
    def densityAndZeff(
        cls, gray: np.ndarray, calibrations: List[dict], exponent: float, zOverA: float = MINERAL_Z_OVER_A
    ) -> np.ndarray:
        """(electron density, Zeff, bulk density) of each row of `gray` [N, 2] (the gray of the two volumes), with the
        two calibrations of `fitDensityCalibration`. With u = (gray - air) / S  and  u_k = rho * (1 + R_k * Z ** n)
        for the two volumes, p = rho * Z ** n = (u_0 - u_1) / (R_0 - R_1) and rho = u_0 - R_0 * p: two equations for
        two unknowns. NaN where rho or p is not positive (no attenuation above air, or noise)."""
        gray = np.atleast_2d(np.asarray(gray, dtype=float))
        rho, p = cls.densityPlane([gray[:, 0], gray[:, 1]], calibrations)
        good = (rho > 0) & (p > 0)
        with np.errstate(invalid="ignore", divide="ignore"):
            z = np.where(good, (p / np.where(good, rho, 1.0)) ** (1.0 / exponent), np.nan)
        return np.column_stack([np.where(good, rho, np.nan), z, np.where(good, rho / zOverA, np.nan)])

    @staticmethod
    def refineReferenceMask(
        gray: np.ndarray, mask: np.ndarray, spread: float = AUTO_REFERENCE_SPREAD, floor: float = 0.01
    ) -> np.ndarray:
        """Pixels of `mask` that really are of one material: those whose gray value, in every channel of `gray`
        [channels, y, x], is within `spread` robust standard deviations (1.4826 MAD, at least `floor` of the median)
        of the median of the mask. A mask carried from another scan has specks of the neighbours and mixed borders,
        which this drops; then the isolated pixels are opened away and only the pieces at least a tenth of the
        largest are kept."""
        from scipy.ndimage import binary_opening, label

        mask = np.asarray(mask, dtype=bool)
        if not mask.any():
            return mask
        values = gray[:, mask]
        median = np.median(values, axis=1)
        deviation = np.maximum(1.4826 * np.median(np.abs(values - median[:, None]), axis=1), floor * np.abs(median))
        close = mask & np.all(np.abs(gray - median[:, None, None]) <= spread * deviation[:, None, None], axis=0)
        close = binary_opening(close, iterations=1)
        labels, count = label(close)
        if count == 0:
            return close
        sizes = np.bincount(labels.ravel())[1:]
        return np.isin(labels, 1 + np.flatnonzero(sizes >= 0.1 * sizes.max()))

    @classmethod
    def findDualReferences(
        cls,
        gray: np.ndarray,
        outside: np.ndarray,
        standards: List[Tuple[float, float]],
        exponent: float,
        seed: int = 0,
    ) -> dict:
        """The standards and the air among the pixels `outside` (a 2D mask) of the two volumes `gray` [2, y, x].

        The pixels are clustered in the plane of the two gray values (as many Gaussians as standards plus the air
        plus STANDARD_EXTRA_CLUSTERS for the holder and the mixed borders). The air and the standards are the regions
        that are compact, that is, whose gray varies less than DUAL_COMPACT_SPREAD around its mean: the air is the
        darkest and the standards are the `len(standards)` of the others, in order of attenuation, that make the
        calibration of both volumes fit best (see `fitDensityCalibration`). `standards` are the (electron density,
        Zeff) of the standards from the least to the most attenuating. Returns `masks` (one for each standard, cleaned
        with `refineReferenceMask`), `air` and `cost` (the worst relative residual of the calibration). Raises
        ValueError, saying why, when they cannot be found."""
        from sklearn.mixture import GaussianMixture

        count = len(standards)
        candidates = np.asarray(outside, dtype=bool).copy()
        lowest = gray[0].min()
        if (gray[0] == lowest).mean() > 0.01:  # what a scan leaves beyond its field of view is not a reference
            candidates &= gray[0] > lowest
        if candidates.sum() < MIN_STANDARD_AREA * (count + 1):
            raise ValueError(
                "There are too few pixels outside the SOI to hold the standards. Check that the SOI leaves them out."
            )
        values = gray[:, candidates].T.astype(np.float64)
        rng = np.random.default_rng(seed)
        sample = values if len(values) <= 60_000 else values[rng.choice(len(values), 60_000, replace=False)]
        regions = count + 1 + STANDARD_EXTRA_CLUSTERS
        mixture = GaussianMixture(regions, covariance_type="full", random_state=seed, n_init=2).fit(sample)
        labels = np.full(candidates.shape, -1, dtype=int)
        labels[candidates] = mixture.predict(values)
        sizes = np.bincount(labels[candidates], minlength=regions)
        spread = np.max(np.sqrt(np.stack([np.diag(c) for c in mixture.covariances_])) / np.abs(mixture.means_), axis=1)
        compact = [
            int(k)
            for k in np.argsort(mixture.means_[:, 0])
            if sizes[k] >= MIN_STANDARD_AREA and spread[k] <= DUAL_COMPACT_SPREAD
        ]
        if len(compact) < count + 1:
            raise ValueError(
                f"Only {len(compact)} uniform regions were found outside the SOI, and the {count} standards and the "
                "air are needed. Draw the references by hand."
            )
        air, rest = compact[0], compact[1:]
        density, zeff = [item[0] for item in standards], [item[1] for item in standards]
        best = None
        for chosen in itertools.combinations(rest, count):  # in order of gray: the order of attenuation
            grays = mixture.means_[list(chosen)]
            try:
                fits = [
                    cls.fitDensityCalibration(grays[:, k], mixture.means_[air][k], density, zeff, exponent)
                    for k in range(2)
                ]
            except ValueError:
                continue
            cost = max(fit["relative"] for fit in fits)
            if best is None or cost < best[0]:
                best = (cost, chosen)
        if best is None or best[0] > DUAL_RESIDUAL_LIMIT:
            raise ValueError(
                "The uniform regions outside the SOI do not fit the standards (their gray values do not follow their "
                "density and Zeff). Draw the references by hand."
            )

        def region(k: int) -> np.ndarray:
            """Pixels within 3 standard deviations of the Gaussian of region k: the mixture may have split a uniform
            region in two, and the pixels of the other half are as much of the reference as the ones it kept."""
            delta = gray.astype(np.float64) - mixture.means_[k][:, None, None]
            distance = np.einsum("iyx,ij,jyx->yx", delta, np.linalg.inv(mixture.covariances_[k]), delta)
            return cls.refineReferenceMask(gray, candidates & (distance <= 9.0))

        return {"masks": [region(k) for k in best[1]], "air": region(air), "cost": float(best[0])}

    @classmethod
    def dualHistogram(
        cls,
        volumes: List[np.ndarray],
        region: Optional[np.ndarray] = None,
        zRange: Optional[Tuple[int, int]] = None,
        smoothing: float = SUPERVISED_SMOOTHING,
        bins: int = DUAL_HISTOGRAM_BINS,
        maxSlices: int = DUAL_HISTOGRAM_SLICES,
        convert: Optional[Callable[[List[np.ndarray]], List[np.ndarray]]] = None,
    ) -> dict:
        """2D histogram of the gray values of two volumes (the same [z, y, x] shape), one axis for each, of the voxels
        inside `region` (a 2D [y, x] mask for every slice, or a 3D one) in `maxSlices` slices evenly spaced in `zRange` (first, last + 1),
        filtered with `smoothing` (as `classifyGrayVolumes` does) -> `counts` [bins, bins] (first volume, second
        volume), `x` and `y` (the gray range of each axis, from the 0.5 and 99.5 percentiles of the middle slice,
        widened by 5%), `slices` and `voxels` (counted). With `convert` (it takes the two arrays of the gray values
        of the voxels and gives two) the axes are what it gives. Raises ValueError when there is nothing to count."""
        if len(volumes) != 2 or volumes[0].shape != volumes[1].shape:
            raise ValueError("Two volumes of the same shape are needed.")
        nz, ny, nx = volumes[0].shape
        low, high = zRange if zRange is not None else (0, nz)
        low, high = max(int(low), 0), min(int(high), nz)
        if high <= low:
            raise ValueError("There are no slices in the range.")
        inside = np.ones((ny, nx), dtype=bool) if region is None else np.asarray(region, dtype=bool)
        if not inside.any():
            raise ValueError("The region has no voxels in the volumes.")
        halo = int(np.ceil(3 * smoothing)) if smoothing > 0 else 0
        slices = np.unique(np.round(np.linspace(low, high - 1, min(maxSlices, high - low))).astype(int))
        if inside.ndim == 3:  # a region in 3D: only the slices that have some of it
            slices = slices[[inside[z].any() for z in slices]]
            if len(slices) == 0:
                raise ValueError("The region has no voxels in these slices.")

        def plane(z: int) -> List[np.ndarray]:
            mask = inside[z] if inside.ndim == 3 else inside
            values = [cls._smoothSlab(volume, z, z + 1, halo, smoothing)[0][mask] for volume in volumes]
            return values if convert is None else convert(values)

        middle = plane(int(slices[len(slices) // 2]))
        edges = []
        for values in middle:
            first, last = np.percentile(values, [0.5, 99.5])
            margin = 0.05 * max(last - first, 1e-9)
            edges.append(np.linspace(first - margin, last + margin, bins + 1))
        counts = np.zeros((bins, bins))
        for z in slices:
            first, second = plane(int(z))
            counts += np.histogram2d(first, second, [edges[0], edges[1]])[0]
        return {
            "counts": counts,
            "x": (float(edges[0][0]), float(edges[0][-1])),
            "y": (float(edges[1][0]), float(edges[1][-1])),
            "slices": len(slices),
            "voxels": int(counts.sum()),
        }

    @classmethod
    def clusterGrayVolumes(
        cls,
        volumes: List[np.ndarray],
        region: Optional[np.ndarray],
        count: int,
        maxSamples: int = DUAL_CLUSTER_SAMPLES,
        seed: int = 0,
    ) -> Tuple[List[dict], List[np.ndarray]]:
        """Group the voxels of two volumes (the same [z, y, x] shape) inside `region` (a 2D [y, x] mask for every
        slice, or a 3D one; None = all) by their two gray values, with a mixture of `count` Gaussians fitted on at
        most `maxSamples` voxels drawn at random from slices evenly spaced along z (so that the volume is never read
        as a whole). Returns the clusters (mean, cov and weight of each, from the darkest to the brightest) and the
        voxels (gray of both volumes) drawn for each, to measure the clusters on. Raises ValueError when there are
        fewer voxels than clusters needing SUPERVISED_MIN_SAMPLES each."""
        from sklearn.mixture import GaussianMixture

        if len(volumes) != 2 or volumes[0].shape != volumes[1].shape:
            raise ValueError("Two volumes of the same shape are needed.")
        nz, ny, nx = volumes[0].shape
        inside = np.ones((ny, nx), dtype=bool) if region is None else np.asarray(region, dtype=bool)
        slices = np.arange(nz) if inside.ndim == 2 else np.flatnonzero(inside.any(axis=(1, 2)))
        if len(slices) == 0 or not inside.any():
            raise ValueError("The region has no voxels in the volumes.")
        slices = slices[np.unique(np.round(np.linspace(0, len(slices) - 1, min(len(slices), 200))).astype(int))]
        rng = np.random.default_rng(seed)
        per = max(maxSamples // len(slices), 1)
        drawn = []
        for z in slices:
            mask = inside[z] if inside.ndim == 3 else inside
            rows, columns = np.nonzero(mask)
            if len(rows) == 0:
                continue
            pick = rng.choice(len(rows), min(per, len(rows)), replace=False)
            drawn.append(np.column_stack([volume[z][rows[pick], columns[pick]] for volume in volumes]))
        values = np.concatenate(drawn).astype(np.float64)
        if len(values) < count * SUPERVISED_MIN_SAMPLES:
            raise ValueError("There are too few voxels in the region for that many clusters.")
        mixture = GaussianMixture(count, covariance_type="full", random_state=seed, n_init=3).fit(values)
        order = np.argsort(mixture.means_[:, 0])
        labels = mixture.predict(values)
        clusters = [
            {"mean": mixture.means_[k], "cov": mixture.covariances_[k], "weight": float(mixture.weights_[k])}
            for k in order
        ]
        return clusters, [values[labels == k] for k in order]

    @classmethod
    def classifyGrayVolumes(
        cls,
        volumes: List[np.ndarray],
        clusters: List[dict],
        labels: np.ndarray,
        minProbability: float = 0.0,
        smoothing: float = SUPERVISED_SMOOTHING,
        memoryBytes: float = 2**30,
        progress: Optional[Callable[[float], bool]] = None,
        region: Optional[np.ndarray] = None,
        zRange: Optional[Tuple[int, int]] = None,
    ) -> Optional[dict]:
        """Classify 3D volumes (one per energy, the same [z, y, x] shape) by the Gaussians of `clusters` in the space
        of their gray values, writing the label of every voxel (1-based in the order of `clusters`, 0 = outside
        `region` (a 2D [y, x] mask repeated in every slice, or a 3D one), outside `zRange` (first, last + 1) or
        undecided) into `labels`, an integer array of that shape that can be a view of the output volume.

        The volumes are filtered with a Gaussian of `smoothing` voxels and classified in slabs of slices that fit in
        `memoryBytes` (read with the halo that the filter needs), and each slab in pieces, so that nothing the size
        of a volume is created. Returns `counts` of each cluster, `valid` (voxels inside the region and range) and
        `voxels`, or None when `progress(fraction)` returned False."""
        if len(volumes) != 2 or any(volume.shape != labels.shape for volume in volumes):
            raise ValueError("Two volumes with the shape of the output are needed.")
        nz, ny, nx = labels.shape
        low, high = zRange if zRange is not None else (0, nz)
        low, high = max(int(low), 0), min(int(high), nz)
        halo = int(np.ceil(3 * smoothing)) if smoothing > 0 else 0
        depth = max(int(memoryBytes // (ny * nx * SUPERVISED_BYTES_PER_VOXEL)), 1)
        piece = cls.blockVoxels(len(clusters), memoryBytes)
        inside = np.ones((ny, nx), dtype=bool) if region is None else np.asarray(region, dtype=bool)
        counts, valid = np.zeros(len(clusters), dtype=np.int64), 0
        for start in range(0, nz, depth):
            stop = min(start + depth, nz)
            out = np.zeros((stop - start, ny, nx), dtype=np.uint8)
            first, last = max(start, low), min(stop, high)
            if last > first:
                slabs = [cls._smoothSlab(volume, first, last, halo, smoothing) for volume in volumes]
                flat = [slab.reshape(-1) for slab in slabs]
                usable = (
                    inside[first:last] if inside.ndim == 3 else np.broadcast_to(inside, (last - first, ny, nx))
                ).reshape(-1)
                result = np.zeros(flat[0].shape, dtype=np.uint8)
                for begin in range(0, len(result), piece):
                    part = slice(begin, begin + piece)
                    if not usable[part].any():
                        continue
                    result[part], found = cls.classifyByGaussians(
                        flat[0][part], flat[1][part], usable[part], clusters, minProbability
                    )
                    counts += found
                valid += int(usable.sum())
                out[first - start : last - start] = result.reshape(last - first, ny, nx)
            labels[start:stop] = out
            if progress is not None and not progress(stop / nz):
                return None
        return {"counts": [int(v) for v in counts], "valid": valid, "voxels": int(labels.size)}

    @staticmethod
    def availableMemory() -> Optional[int]:
        """Bytes of free RAM, or None when it cannot be known."""
        try:
            import psutil

            return int(psutil.virtual_memory().available)
        except Exception:
            return None

    @staticmethod
    def ellipsePoints(mean, cov, sigmas: float = 2.0, points: int = 60) -> np.ndarray:
        """Outline of the `sigmas` ellipse of a 2D Gaussian -> [points, 2]."""
        values, vectors = np.linalg.eigh(np.asarray(cov, dtype=float))
        angles = np.linspace(0, 2 * np.pi, points)
        circle = np.stack([np.cos(angles), np.sin(angles)])
        return (vectors @ (sigmas * np.sqrt(np.maximum(values, 0))[:, None] * circle)).T + np.asarray(mean)

    # ----- stability -----
    @staticmethod
    def matchClusters(base: np.ndarray, other: np.ndarray, count: int) -> np.ndarray:
        """Relabel `other` so that its clusters line up with those of `base` (both 1-based, 0 = not clustered).

        The pairing maximizes the number of pixels that share a label (Hungarian algorithm on the contingency
        table), since a clustering does not number its clusters in any meaningful order."""
        from scipy.optimize import linear_sum_assignment

        both = (base > 0) & (other > 0)
        table = np.zeros((count, count), dtype=np.int64)
        np.add.at(table, (base[both] - 1, other[both] - 1), 1)
        rows, columns = linear_sum_assignment(-table)
        mapping = np.zeros(count + 1, dtype=other.dtype)
        mapping[columns + 1] = rows + 1
        return mapping[other]

    @classmethod
    def clusterStability(
        cls,
        array: np.ndarray,
        axis: np.ndarray,
        background: np.ndarray,
        mask: Optional[np.ndarray],
        exponent: float,
        selection: np.ndarray,
        clusters: int,
        seed: int = 0,
        method: str = "gmm",
    ) -> dict:
        """Repeat the clustering with small perturbations and compare each result with the unperturbed one.

        The runs change only one thing at a time: the random start of the mixture (and its pixel sample), the exponent
        by +-STABILITY_EXPONENT_STEP, or a random STABILITY_DROPPED_FRACTION of the energies left out. The image is
        reduced to about STABILITY_TARGET_PIXELS pixels to keep it fast.

        Returns a dict with `overall` (fraction of pixels that keep their cluster, averaged over the runs),
        `categories` (the same per kind of perturbation), `perCluster` (per cluster of the unperturbed result) and
        `map` (uint8 [j, i], percent of the runs in which each pixel keeps its cluster, 0 outside the analysis)."""
        ny, nx = array.shape[1:]
        pixels = int(mask.sum()) if mask is not None else ny * nx
        stride = max(1, int(np.ceil(np.sqrt(pixels / STABILITY_TARGET_PIXELS))))
        small = array[:, ::stride, ::stride]
        smallMask = mask[::stride, ::stride] if mask is not None else None

        def run(exponentValue, energies, runSeed):
            a, c, valid = cls.powerLawFit(small, axis, exponentValue, energies, background, smallMask)
            return cls.clusterParameters(c, a, valid, clusters, runSeed, method=method)[0]

        base = run(exponent, selection, seed)
        count = int(base.max())
        rng = np.random.default_rng(seed + 1000)
        keep = max(MIN_ENERGIES, int(round(len(selection) * (1 - STABILITY_DROPPED_FRACTION))))
        runs = {"Another random start": [], f"Exponent b +-{STABILITY_EXPONENT_STEP:g}": []}
        runs[f"{int(STABILITY_DROPPED_FRACTION * 100)}% of the energies left out"] = []
        labelsOf = {name: [] for name in runs}
        names = list(runs)
        for runSeed in STABILITY_SEEDS:
            labelsOf[names[0]].append(run(exponent, selection, runSeed))
        for delta in (-STABILITY_EXPONENT_STEP, STABILITY_EXPONENT_STEP):
            shifted = min(max(exponent + delta, MIN_EXPONENT), MAX_EXPONENT)
            labelsOf[names[1]].append(run(shifted, selection, seed))
        for _ in range(STABILITY_DROP_RUNS):
            kept = np.sort(rng.choice(selection, size=min(keep, len(selection)), replace=False))
            labelsOf[names[2]].append(run(exponent, kept, seed))

        inside = base > 0
        agreement = np.zeros(base.shape, dtype=np.float64)
        categories, total = {}, 0
        for name, results in labelsOf.items():
            fractions = []
            for labels in results:
                matched = cls.matchClusters(base, labels, count)
                same = (matched == base) & inside
                agreement += same
                fractions.append(float(same.sum() / max(inside.sum(), 1)))
            categories[name] = float(np.mean(fractions))
            total += len(results)
        agreement /= max(total, 1)
        perCluster = [float(agreement[base == k + 1].mean()) if np.any(base == k + 1) else 0.0 for k in range(count)]
        percent = np.where(inside, np.round(agreement * 100), 0).astype(np.uint8)
        fullMap = np.repeat(np.repeat(percent, stride, axis=0), stride, axis=1)[:ny, :nx]
        return {
            "overall": float(np.mean(list(categories.values()))),
            "categories": categories,
            "perCluster": perCluster,
            "map": fullMap,
        }

    # ----- estimating the exponent on the standards -----
    @staticmethod
    def estimateExponent(
        array: np.ndarray,
        axis: np.ndarray,
        selection: np.ndarray,
        background: np.ndarray,
        masks: List[np.ndarray],
        exponents: Optional[np.ndarray] = None,
        seed: int = 0,
    ) -> dict:
        """Exponent b that fits the spectra of the standards best.

        For each b of the grid, attenuation = a * (E / E0) ** b + c is fitted to every pixel of the standards (the
        2D `masks`) and the squared residuals are added up; the b with the lowest sum wins, refined with a parabola
        through its neighbours. Unlike the Zeff calibration this needs no composition: it only asks which energy
        dependence the scan really has.

        Returns `best`, the `exponents` and `residual` of the grid, `atEdge` (the best b is an end of the grid, so the
        true one may be outside), `ratio` (how much the residual grows 0.5 away from the best b; close to 1 means b
        is not well defined by these standards) and `interval` (b values within 1% of the lowest residual)."""
        if exponents is None:
            exponents = np.arange(
                ESTIMATE_EXPONENT_RANGE[0],
                ESTIMATE_EXPONENT_RANGE[1] + ESTIMATE_EXPONENT_STEP / 2,
                ESTIMATE_EXPONENT_STEP,
            )
        selection = np.asarray(selection, dtype=int)
        energies = np.asarray(axis, dtype=np.float64)[selection] / POWER_LAW_REFERENCE_ENERGY
        flat = array.reshape(array.shape[0], -1)
        pixels = np.concatenate([np.flatnonzero(mask.ravel()) for mask in masks])
        if len(pixels) > ESTIMATE_MAX_PIXELS:
            pixels = np.random.default_rng(seed).choice(pixels, ESTIMATE_MAX_PIXELS, replace=False)
        y = flat[np.ix_(selection, pixels)].T.astype(np.float64) - np.asarray(background, dtype=np.float64)[selection]
        residual = np.empty(len(exponents))
        for index, exponent in enumerate(exponents):
            x = energies**exponent
            xc = x - x.mean()
            slope = (y @ xc) / float(xc @ xc)
            fitted = slope[:, None] * x[None, :] + (y.mean(axis=1) - slope * x.mean())[:, None]
            residual[index] = float(np.sum((y - fitted) ** 2))
        lowest = int(np.argmin(residual))
        best = float(exponents[lowest])
        atEdge = lowest in (0, len(exponents) - 1)
        if not atEdge:  # parabola through the best point and its neighbours
            left, middle, right = residual[lowest - 1], residual[lowest], residual[lowest + 1]
            curvature = left - 2 * middle + right
            if curvature > 0:
                best += float(ESTIMATE_EXPONENT_STEP * 0.5 * (left - right) / curvature)
        step = ESTIMATE_EXPONENT_STEP
        around = [residual[int(np.clip(lowest + sign * round(0.5 / step), 0, len(exponents) - 1))] for sign in (-1, 1)]
        within = exponents[residual <= residual[lowest] * 1.01]
        return {
            "best": best,
            "exponents": exponents,
            "residual": residual,
            "atEdge": atEdge,
            "ratio": float(min(around) / residual[lowest]) if residual[lowest] > 0 else float("inf"),
            "interval": (float(within.min()), float(within.max())),
        }

    @classmethod
    def describeExponentEstimate(cls, start: float, best: float, result: dict) -> str:
        """Sentence about an exponent estimate, with the warning that applies to it."""
        return f"b estimated from the standards: {best:.2f} (was {start:.2f}). {cls.exponentWarning(result)}".strip()

    # ----- calibration with standards -----
    @staticmethod
    def parseFormula(text: str) -> dict:
        """Element counts of a chemical formula such as 'SiO2', 'CaMg(CO3)2' or 'Ca(OH)2' -> {symbol: count}.

        Raises ValueError for an unknown element, unbalanced parentheses or any character that is not part of a
        formula."""
        text = text.replace(" ", "")
        if not text:
            raise ValueError("The formula is empty.")
        tokens = re.findall(r"[A-Z][a-z]?|\d+(?:\.\d+)?|[()]|.", text)
        groups = [{}]
        position = 0

        def multiplier():
            nonlocal position
            if position < len(tokens) and re.fullmatch(r"\d+(?:\.\d+)?", tokens[position]):
                position += 1
                return float(tokens[position - 1])
            return 1.0

        while position < len(tokens):
            token = tokens[position]
            position += 1
            if token == "(":
                groups.append({})
            elif token == ")":
                if len(groups) == 1:
                    raise ValueError(f"Unbalanced parentheses in '{text}'.")
                inner = groups.pop()
                factor = multiplier()
                for element, count in inner.items():
                    groups[-1][element] = groups[-1].get(element, 0.0) + factor * count
            elif re.fullmatch(r"[A-Z][a-z]?", token):
                if token not in ATOMIC_DATA:
                    raise ValueError(f"Unknown element '{token}' in '{text}'.")
                groups[-1][token] = groups[-1].get(token, 0.0) + multiplier()
            else:
                raise ValueError(f"Cannot read '{token}' in the formula '{text}'.")
        if len(groups) != 1:
            raise ValueError(f"Unbalanced parentheses in '{text}'.")
        return groups[0]

    @classmethod
    def composition(cls, formula: dict, density: float) -> dict:
        """Electron density and electron fractions of a compound.

        Returns `electronDensity` (mol of electrons per cm3 = density * sum(w_i Z_i / A_i), with w_i the mass
        fractions), `Z` and `fractions` (electron fraction f_i = n_i Z_i / sum(n_j Z_j) of each element)."""
        elements = list(formula)
        counts = np.array([formula[e] for e in elements], dtype=float)
        Z = np.array([ATOMIC_DATA[e][0] for e in elements], dtype=float)
        A = np.array([ATOMIC_DATA[e][1] for e in elements], dtype=float)
        massFractions = counts * A / np.sum(counts * A)
        return {
            "electronDensity": float(density * np.sum(massFractions * Z / A)),
            "Z": Z,
            "fractions": counts * Z / np.sum(counts * Z),
        }

    @staticmethod
    def effectiveZ(composition: dict, exponent: float) -> float:
        """Zeff = (sum f_i Z_i ** n) ** (1 / n) of a compound from its `composition`."""
        return float(np.sum(composition["fractions"] * composition["Z"] ** exponent) ** (1.0 / exponent))

    @classmethod
    def calibrate(
        cls,
        meanA: np.ndarray,
        meanC: np.ndarray,
        compositions: List[dict],
        fitExponent: bool = True,
        exponent: float = DEFAULT_Z_EXPONENT,
    ) -> dict:
        """Calibrate the fitted terms of the standards against their known composition.

        meanA, meanC: a and c of each standard. `compositions` come from `composition`. Two relations are fitted:
        beta in  c = beta * electron density  (through the origin) and  a / c = K * sum(f_i * Z_i ** n)  for K and,
        when `fitExponent` and there are at least 3 standards, for the exponent n too. How steeply a / c grows with
        the atomic number depends on the scan (its energies and filtration), so n is measured on the standards
        instead of assumed. If n cannot be fitted (fewer than 3 standards, or a result at an end of
        FIT_Z_EXPONENT_RANGE) it is fixed at `exponent` and `exponentNote` says so.

        Returns beta, K, n, `fittedExponent`, `exponentNote`, `standards` (the electron density and Zeff that the
        calibration gives back for each standard, against the known ones) and `points` (measured c and a / c
        against the known electron density and Zeff of each standard, to plot)."""
        from scipy.optimize import least_squares

        meanA, meanC = np.asarray(meanA, dtype=float), np.asarray(meanC, dtype=float)
        if len(compositions) < 2:
            raise ValueError("At least two standards are needed to calibrate.")
        if np.any(meanC <= 0) or np.any(meanA <= 0):
            raise ValueError("A standard has a <= 0 or c <= 0, so its a / c cannot be used (check the energies).")
        electronDensity = np.array([comp["electronDensity"] for comp in compositions])
        beta = float(np.sum(meanC * electronDensity) / np.sum(electronDensity**2))
        logRatio = np.log(meanA / meanC)

        def model(n):
            return np.log([np.sum(comp["fractions"] * comp["Z"] ** n) for comp in compositions])

        n, fitted, note = float(exponent), False, ""
        if fitExponent and len(compositions) < 3:
            note = f"n fixed at {exponent:g}: fitting it needs 3 standards."
        elif fitExponent:
            start = [float(np.mean(logRatio - model(exponent))), float(exponent)]
            lower, upper = [-np.inf, FIT_Z_EXPONENT_RANGE[0]], [np.inf, FIT_Z_EXPONENT_RANGE[1]]
            solution = least_squares(lambda p: logRatio - (p[0] + model(p[1])), start, bounds=(lower, upper))
            low, high = FIT_Z_EXPONENT_RANGE
            if min(solution.x[1] - low, high - solution.x[1]) <= Z_EXPONENT_LIMIT_MARGIN:
                note = f"n fixed at {exponent:g}: the fit ran to its limit ({solution.x[1]:.2f})."
            else:
                n, fitted = float(solution.x[1]), True
        logK = float(solution.x[0]) if fitted else float(np.mean(logRatio - model(n)))
        calibration = {
            "beta": beta,
            "K": float(np.exp(logK)),
            "n": n,
            "fittedExponent": fitted,
            "exponentNote": note,
        }
        predicted = [cls.convert(a, c, calibration) for a, c in zip(meanA, meanC)]
        knownZeff = [cls.effectiveZ(comp, n) for comp in compositions]
        calibration["standards"] = [
            {
                "electronDensity": (predicted[k][0], electronDensity[k]),
                "Zeff": (predicted[k][1], knownZeff[k]),
            }
            for k in range(len(compositions))
        ]
        calibration["points"] = [
            {
                "c": float(meanC[k]),
                "ratio": float(meanA[k] / meanC[k]),
                "electronDensity": float(electronDensity[k]),
                "zeff": float(knownZeff[k]),
            }
            for k in range(len(compositions))
        ]
        return calibration

    @staticmethod
    def convert(a: float, c: float, calibration: dict, zOverA: float = MINERAL_Z_OVER_A) -> Tuple[float, float, float]:
        """(electron density, Zeff, density) from the mean a and c of a material; NaN when a or c is not positive.

        electron density = c / beta,  Zeff = (a / (K * c)) ** (1 / n),  density = electron density / (Z/A)."""
        if not (a > 0 and c > 0):
            return float("nan"), float("nan"), float("nan")
        electronDensity = c / calibration["beta"]
        zeff = (a / (calibration["K"] * c)) ** (1.0 / calibration["n"])
        return float(electronDensity), float(zeff), float(electronDensity / zOverA)

    @classmethod
    def clusterProperties(
        cls, a: np.ndarray, c: np.ndarray, labels: np.ndarray, count: int, calibration: dict, seed: int = 0
    ) -> List[dict]:
        """Electron density, Zeff and density of each cluster 1..count, with a bootstrap standard deviation.

        The conversion uses the ratio of the means (mean a over mean c), not the mean of the ratios, which is
        unstable where c is small. The bootstrap resamples the pixels of the cluster; it does not include the
        uncertainty of the calibration itself."""
        rng = np.random.default_rng(seed)
        results = []
        for k in range(1, count + 1):
            inside = labels == k
            clusterA, clusterC = a[inside].astype(float), c[inside].astype(float)
            if clusterA.size == 0:
                results.append({"pixels": 0, "values": (np.nan,) * 3, "sd": (np.nan,) * 3})
                continue
            values = cls.convert(clusterA.mean(), clusterC.mean(), calibration)
            sample = min(clusterA.size, CALIBRATION_BOOTSTRAP_PIXELS)
            draws = []
            for _ in range(CALIBRATION_BOOTSTRAP):
                pick = rng.integers(0, clusterA.size, sample)
                draws.append(cls.convert(clusterA[pick].mean(), clusterC[pick].mean(), calibration))
            draws = np.array(draws, dtype=float)
            results.append(
                {"pixels": int(clusterA.size), "values": values, "sd": tuple(np.nanstd(draws, axis=0).tolist())}
            )
        return results

    @classmethod
    def suggestMineral(cls, zeff: float, density: float, exponent: float) -> Tuple[str, float, float]:
        """Reference mineral that best explains a class -> (name, Zeff difference, density difference), the
        differences relative to the mineral. Only minerals within MINERAL_MATCH_TOLERANCE of the Zeff are
        considered, and among them the one with the closest density wins (the Zeff alone cannot tell calcite from
        aragonite or anhydrite); without a usable density the closest Zeff wins. The name is empty when no mineral
        is close enough. A class with no attenuation above air (no valid Zeff) or with a bulk density below
        PORE_DENSITY_LIMIT is suggested as PORES."""
        if not np.isfinite(zeff) or (np.isfinite(density) and density < PORE_DENSITY_LIMIT):
            return PORES, float("nan"), float("nan")
        candidates = []
        for name, (formula, referenceDensity) in REFERENCE_MINERALS.items():
            reference = cls.effectiveZ(cls.composition(cls.parseFormula(formula), referenceDensity), exponent)
            zDifference = (zeff - reference) / reference
            if abs(zDifference) <= MINERAL_MATCH_TOLERANCE:
                densityDifference = (density - referenceDensity) / referenceDensity if np.isfinite(density) else np.nan
                candidates.append((name, zDifference, densityDifference))
        if not candidates:
            return "", float("nan"), float("nan")
        usable = [item for item in candidates if np.isfinite(item[2])]
        best = min(usable, key=lambda item: abs(item[2])) if usable else min(candidates, key=lambda item: abs(item[1]))
        return best[0], float(best[1]), float(best[2])

    @staticmethod
    def uniqueSegmentNames(names: List[str]) -> List[str]:
        """`names` with the repeated ones numbered: ['Calcite', 'Quartz', 'Calcite'] gives ['Calcite (1)', 'Quartz',
        'Calcite (2)']."""
        totals = {name: names.count(name) for name in names}
        seen = {}
        unique = []
        for name in names:
            if totals[name] > 1:
                seen[name] = seen.get(name, 0) + 1
                unique.append(f"{name} ({seen[name]})")
            else:
                unique.append(name)
        return unique

    @staticmethod
    def orderByAttenuation(
        array: np.ndarray, axis: np.ndarray, selection: np.ndarray, background: np.ndarray, masks: List[np.ndarray]
    ) -> List[int]:
        """Indices of `masks` from the least to the most attenuating, at the lowest energy used (where the materials
        differ the most)."""
        selection = np.asarray(selection, dtype=int)
        lowest = int(selection[np.argmin(np.asarray(axis, dtype=float)[selection])])
        attenuation = [float(array[lowest][mask].mean() - background[lowest]) for mask in masks]
        return [int(k) for k in np.argsort(attenuation)]

    @staticmethod
    def matchStandardClusters(
        clusters: List[dict], compositions: List[dict], minPixels: int
    ) -> Tuple[List[int], float]:
        """Which cluster is each standard -> (cluster index of each standard, mismatch).

        A standard of known composition has c = beta * electron density and a / c = K * sum(f_i Z_i ** n), with beta
        and K unknown but the same for all of them. So the right clusters make log c - log(electron density) and
        log(a / c) - log(sum f Z ** n) constant across the standards. Every ordered choice of clusters is tried and
        the one where those two differences vary the least (sum of the variances) wins. Clusters with a or c not
        positive, or with fewer than `minPixels`, cannot be a standard. Raises ValueError if too few remain."""
        from itertools import permutations

        logDensity = np.log([comp["electronDensity"] for comp in compositions])
        logZ = np.log([np.sum(comp["fractions"] * comp["Z"] ** DEFAULT_Z_EXPONENT) for comp in compositions])
        usable = [
            k
            for k, cluster in enumerate(clusters)
            if cluster["mean"][0] > 0 and cluster["mean"][1] > 0 and cluster["count"] >= minPixels
        ]
        if len(usable) < len(compositions):
            raise ValueError(
                f"Only {len(usable)} cluster(s) outside the SOI can be a standard, but {len(compositions)} are "
                "needed. Check that the SOI leaves the standards out."
            )
        logC = {k: np.log(clusters[k]["mean"][0]) for k in usable}
        logRatio = {k: np.log(clusters[k]["mean"][1] / clusters[k]["mean"][0]) for k in usable}
        best, bestScore = None, np.inf
        for choice in permutations(usable, len(compositions)):
            score = float(np.var([logC[k] for k in choice] - logDensity) + np.var([logRatio[k] for k in choice] - logZ))
            if score < bestScore:
                best, bestScore = list(choice), score
        return best, bestScore

    @staticmethod
    def cleanRegion(mask: np.ndarray) -> np.ndarray:
        """`mask` without the connected pieces smaller than MIN_STANDARD_AREA (scattered pixels of a cluster)."""
        from scipy.ndimage import label

        pieces, total = label(mask)
        if total == 0:
            return mask
        sizes = np.bincount(pieces.ravel())
        keep = sizes >= MIN_STANDARD_AREA
        keep[0] = False
        return keep[pieces]

    @classmethod
    def findStandards(
        cls,
        array: np.ndarray,
        axis: np.ndarray,
        selection: np.ndarray,
        background: np.ndarray,
        soiMask: np.ndarray,
        exponent: float,
        compositions: List[dict],
        seed: int = 0,
        minProbability: float = 0.0,
    ) -> dict:
        """Find the standards among the pixels outside the SOI by clustering them.

        Returns `masks` (2D mask of each standard in the order of `compositions`), `mismatch` of the match, and the
        whole clustering outside the SOI: `labels` (1 to the number of standards for them, in that order, then one
        value per other cluster; 0 = left out), `standards` and `others` (the clusters of each kind). Pixels that the clustering is not sure about (below `minProbability`) are left out, which
        also drops most of what a ring artifact or a mixed border leaves in a standard.

        The pixels that are not air and not in the SOI are fitted with the power law like the rest, clustered in the
        (c, a) plane in as many Gaussians as there are standards plus STANDARD_EXTRA_CLUSTERS (the holder, mixed
        pixels at the borders...), and `matchStandardClusters` tells which cluster is which standard. Nothing is
        assumed about their shape. Raises ValueError when they cannot be found."""
        count = len(compositions)
        outside = np.any(array != np.asarray(background)[:, None, None], axis=0) & ~soiMask
        if outside.sum() < MIN_STANDARD_AREA * count:
            raise ValueError(
                "There are too few pixels outside the SOI (and not air) to hold the standards. "
                "Check that the SOI leaves them out."
            )
        a, c, valid = cls.powerLawFit(array, axis, exponent, selection, background, outside)
        model = cls.fitClusters(c, a, valid, count + STANDARD_EXTRA_CLUSTERS, seed)
        _, counts = cls.assignClusters(model)
        clusters = [dict(cluster, count=n) for cluster, n in zip(model["clusters"], counts)]
        chosen, mismatch = cls.matchStandardClusters(clusters, compositions, MIN_STANDARD_AREA)
        # The mixture may split a standard in two (noise, ring artifacts): leftover clusters whose mean lies within
        # MERGE_DISTANCE standard deviations of a standard's Gaussian are pieces of it.
        groups = [[k] for k in chosen]
        for other in range(len(clusters)):
            if other in chosen:
                continue
            closest, closestDistance = None, MERGE_DISTANCE
            for index, k in enumerate(chosen):
                delta = np.asarray(clusters[other]["mean"]) - np.asarray(clusters[k]["mean"])
                distance = float(np.sqrt(delta @ np.linalg.inv(clusters[k]["cov"]) @ delta))
                if distance < closestDistance:
                    closest, closestDistance = index, distance
            if closest is not None:
                groups[closest].append(other)
        leftover = [k for k in range(len(clusters)) if not any(k in group for group in groups)]
        # Labels 1..count are the standards (in the order of `compositions`), the next ones the leftover clusters
        labels, _ = cls.assignClusters(model, groups + [[k] for k in leftover], minProbability)
        masks = [cls.cleanRegion(labels == index + 1) for index in range(count)]
        if any(not mask.any() for mask in masks):
            raise ValueError("A standard found outside the SOI has no solid region. Check the SOI.")
        return {
            "masks": masks,
            "mismatch": mismatch,
            "labels": labels,
            "standards": [clusters[k] for k in chosen],
            "others": [clusters[k] for k in leftover],
        }

    @staticmethod
    def standardPixels(mask: np.ndarray, border: int) -> np.ndarray:
        """Mask of a standard without its border (the pixels near the edge mix with the surroundings). The original
        mask is returned if removing the border leaves too few pixels."""
        from scipy.ndimage import binary_erosion

        if border <= 0:
            return mask
        inner = binary_erosion(mask, iterations=border)
        return inner if inner.sum() >= MIN_STANDARD_PIXELS else mask

    # ----- texts shown in the panel (rich text, so they can be laid out as tables) -----
    @staticmethod
    def swatch(color) -> str:
        """Colored square for a series index or an (r, g, b) color."""
        red, green, blue = SERIES_COLORS[color % len(SERIES_COLORS)] if isinstance(color, int) else color
        return f'<span style="color:rgb({red},{green},{blue})">&#9632;</span>'

    @staticmethod
    def table(headers: List[str], rows: List[List[str]]) -> str:
        """HTML table: the first column on the left, the others on the right."""
        cell = 'style="padding:1px 8px 1px 0; white-space:nowrap"'
        head = "".join(
            f'<th align="{"left" if n == 0 else "right"}" {cell}>{header}</th>' for n, header in enumerate(headers)
        )
        body = "".join(
            "<tr>"
            + "".join(f'<td align="{"left" if n == 0 else "right"}" {cell}>{text}</td>' for n, text in enumerate(row))
            + "</tr>"
            for row in rows
        )
        return f'<table cellspacing="0" cellpadding="0"><tr>{head}</tr>{body}</table>'

    @staticmethod
    def colored(text: str, level: str) -> str:
        """Text in green, orange or red (`level` is "good", "warn" or "bad")."""
        red, green, blue = {"good": (46, 160, 67), "warn": (230, 140, 30), "bad": (214, 39, 40)}[level]
        return f'<b><span style="color:rgb({red},{green},{blue})">{text}</span></b>'

    @classmethod
    def describeClusters(cls, clusters: List[dict], confidence: int, leftOut: float) -> str:
        total = max(sum(cluster["count"] for cluster in clusters), 1)
        rows = [
            [
                f"{cls.swatch(cluster.get('color', n))} {cluster.get('name', f'Cluster {n + 1}')}",
                f"{100 * cluster['count'] / total:.1f} %",
                f"{cluster['mean'][0]:.1f}",
                f"{cluster['mean'][1]:.1f}",
            ]
            for n, cluster in enumerate(clusters)
        ]
        text = cls.table(["Cluster", "Pixels", "c", "a"], rows)
        if confidence > 0:
            text += f"<p>Left out as undecided: <b>{leftOut:.1f} %</b></p>"
        return text

    @classmethod
    def describeGrayClasses(cls, clusters: List[dict], confidence: int, leftOut: float) -> str:
        """Table of the classes learned in the plane of the gray values: share of the classified voxels, the voxels
        they were learned from and the mean gray value in each volume."""
        total = max(sum(cluster["count"] for cluster in clusters), 1)
        rows = [
            [
                f"{cls.swatch(cluster['color'])} {cluster['name']}",
                f"{100 * cluster['count'] / total:.1f} %",
                f"{cluster['samples']:,}",
                f"{cluster['mean'][0]:.0f}",
                f"{cluster['mean'][1]:.0f}",
            ]
            for cluster in clusters
        ]
        text = cls.table(["Class", "Voxels", "Learned from", "Mean gray (1st)", "Mean gray (2nd)"], rows)
        if confidence > 0:
            text += f"<p>Left out as undecided: <b>{leftOut:.1f} %</b></p>"
        return text

    @classmethod
    def describeDualClasses(
        cls,
        clusters: List[dict],
        confidence: int,
        leftOut: float,
        properties: Optional[List[dict]] = None,
        minerals: Optional[List[str]] = None,
        skipped: Optional[List[Tuple[str, tuple]]] = None,
    ) -> str:
        """Table of the classes of the 3D result: the share of the classified voxels and, with `properties` (see
        `clusterProperties`, one per cluster) and the `minerals` suggested for them, the electron density, Zeff and
        bulk density of each, as in the table of the spectral segmentation; without them the voxels it was learned
        from and its mean gray values. `skipped` are the (name, color) of the classes that have no row because they
        could not be learned."""
        if properties is None:
            return cls.describeGrayClasses(clusters, confidence, leftOut)
        total = max(sum(cluster["count"] for cluster in clusters), 1)
        rows = []
        for cluster, item, mineral in zip(clusters, properties, minerals or [""] * len(clusters)):
            (electron, zeff, density), (sdElectron, sdZeff, sdDensity) = item["values"], item["sd"]

            def value(mean: float, sd: float, decimals: int) -> str:  # no attenuation above air: nothing to show
                return f"{mean:.{decimals}f} \u00b1 {sd:.{decimals}f}" if np.isfinite(mean) else "-"

            rows.append(
                [
                    f"{cls.swatch(cluster['color'])} {cluster['name']}",
                    f"{100 * cluster['count'] / total:.1f} %",
                    value(electron, sdElectron, 3),
                    value(zeff, sdZeff, 2),
                    value(density, sdDensity, 2),
                    mineral or "-",
                ]
            )
        for name, color in skipped or []:
            rows.append([f"{cls.swatch(color)} {name}", "0.0 %", "-", "-", "-", "not learned"])
        text = cls.table(
            ["Class", "Voxels", "Electron density (mol/cm3)", "Zeff", "Bulk density (g/cm3)", "Mineral"], rows
        )
        if confidence > 0:
            text += f"<p>Left out as undecided: <b>{leftOut:.1f} %</b></p>"
        return text

    @classmethod
    def describeStability(cls, result: dict) -> str:
        def level(value: float) -> str:
            return "good" if value >= 0.95 else ("warn" if value >= 0.85 else "bad")

        def percent(value: float) -> str:
            return cls.colored(f"{100 * value:.1f} %", level(value))

        text = f"<p><b>Stability</b>: {percent(result['overall'])} of the pixels keep their cluster.</p>"
        text += cls.table(["Change", "Agreement"], [[name, percent(v)] for name, v in result["categories"].items()])
        text += cls.table(
            ["Cluster", "Agreement"],
            [[f"{cls.swatch(n)} Cluster {n + 1}", percent(v)] for n, v in enumerate(result["perCluster"])],
        )
        return text

    @classmethod
    def describeCalibration(cls, calibration: dict, warning: str = "", note: str = "") -> str:
        text = f"<p><i>{note}</i></p>" if note else ""
        if warning:
            text += f"<p>{cls.colored(warning, 'bad')}</p>"
        how = "" if calibration["fittedExponent"] else " (fixed)"
        text += (
            f"<p>beta = <b>{calibration['beta']:.4g}</b>, K = <b>{calibration['K']:.4g}</b>, "
            f"n = <b>{calibration['n']:.2f}</b>{how}</p>"
        )
        if calibration["exponentNote"]:
            text += f"<p>{cls.colored(calibration['exponentNote'], 'warn')}</p>"
        return text

    @staticmethod
    def calibrationResidual(calibration: dict) -> Tuple[float, int]:
        """How far the worst standard is from the calibration -> (relative distance, index of that standard).

        Each standard has two distances: its measured c from beta * known electron density, and its measured a / c
        from K * known Zeff ** n (the same lines the plots draw), both relative to the line."""
        worst, index = 0.0, 0
        for k, point in enumerate(calibration["points"]):
            expectedC = calibration["beta"] * point["electronDensity"]
            expectedRatio = calibration["K"] * point["zeff"] ** calibration["n"]
            distance = max(abs(point["c"] / expectedC - 1.0), abs(point["ratio"] / expectedRatio - 1.0))
            if distance > worst:
                worst, index = distance, k
        return float(worst), index

    @staticmethod
    def exponentWarning(result: dict) -> str:
        """The warning that applies to an exponent estimate (see `estimateExponent`), or an empty text."""
        if result["atEdge"]:
            return "b is at an end of the range searched, so the true one may be outside."
        if result["ratio"] < ESTIMATE_FLAT_RATIO:
            low, high = result["interval"]
            return f"b is poorly defined by the standards ({low:.2f} to {high:.2f} fit within 1 %)."
        return ""

    # ----- outputs -----
    def createSegmentation(
        self,
        volumeNode,
        labels: np.ndarray,
        names: List[str],
        colors,
        outputName: str,
        exclusive: bool = True,
        node=None,
        segmentIds: Optional[List[str]] = None,
    ):
        """Segmentation node with one segment per class. The 2D classes are repeated along z (spectral axis), so they
        show up in every slice. With `exclusive` the other segmentations of the scene are hidden. When `node` is a
        segmentation made by this method, its segments are refreshed instead of creating another node; `segmentIds`
        (one per class) says which existing segments to refresh when the node was made by something else."""
        created = node is None or not slicer.mrmlScene.IsNodePresent(node)
        segmentationNode = node
        if created:
            segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", outputName)
            segmentationNode.CreateDefaultDisplayNodes()
            segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(volumeNode)
        segmentation = segmentationNode.GetSegmentation()
        shape = slicer.util.arrayFromVolume(volumeNode).shape
        for value, (name, color) in enumerate(zip(names, colors), start=1):
            segmentId = segmentIds[value - 1] if segmentIds else f"class{value}"
            if segmentation.GetSegment(segmentId) is None:
                segmentation.AddEmptySegment(segmentId, name, [c / 255.0 for c in color])
            plane = (labels == value).astype(np.uint8)
            volumeArray = np.broadcast_to(plane, shape).copy()
            slicer.util.updateSegmentBinaryLabelmapFromArray(volumeArray, segmentationNode, segmentId, volumeNode)
        if created:
            self._placeNextTo(volumeNode, segmentationNode)
            if exclusive:
                self.showOnly(segmentationNode)
        return segmentationNode

    @staticmethod
    def showOnly(segmentationNode) -> None:
        """Show `segmentationNode` and hide every other segmentation of the scene (the eye icon of the data tree).

        Changing the display of a segmentation makes the data tree rebuild its items and open them, so the expanded
        state of every item is saved first and restored afterwards, and nodes that are already right are left alone."""
        subjectHierarchy = slicer.mrmlScene.GetSubjectHierarchyNode()
        nodes = list(slicer.util.getNodesByClass("vtkMRMLSegmentationNode"))
        expanded = {}
        for node in nodes:
            item = subjectHierarchy.GetItemByDataNode(node)
            if item:
                expanded[item] = subjectHierarchy.GetItemExpanded(item)
        for node in nodes:
            display = node.GetDisplayNode()
            wanted = node.GetID() == segmentationNode.GetID()
            if display is not None and bool(display.GetVisibility()) != wanted:
                display.SetVisibility(wanted)
        for item, state in expanded.items():
            subjectHierarchy.SetItemExpanded(item, state)

    def createStabilityMap(self, volumeNode, percent: np.ndarray, name: str):
        """Scalar volume with the stability (0-100) of each pixel, repeated along z like the segmentation."""
        mapNode = slicer.modules.volumes.logic().CloneVolume(slicer.mrmlScene, volumeNode, name)
        shape = slicer.util.arrayFromVolume(volumeNode).shape
        slicer.util.updateVolumeFromArray(mapNode, np.broadcast_to(percent, shape).astype(np.uint8).copy())
        mapNode.CreateDefaultDisplayNodes()
        self._placeNextTo(volumeNode, mapNode)
        return mapNode

    @staticmethod
    def referenceGrayValues(
        segmentationNode,
        segmentId: str,
        volumeNodes: list,
        border: int = STANDARD_BORDER_PIXELS,
        maxSamples: int = DUAL_REFERENCE_SAMPLES,
    ) -> List[np.ndarray]:
        """Gray values of the voxels of a segment in each of `volumeNodes` (the same voxels in all), without reading
        the volumes or the segment as a whole: the segment is looked for on a coarse grid, then sampled on a regular
        grid of at most about `maxSamples` voxels, and the border (`border` voxels, within each slice) is dropped. The segmentation
        must have the spacing and orientation of the volumes, and may be up to half a voxel off in position (it is
        rounded to the nearest voxel). Raises ValueError when it is not, or the segment is too small."""
        from scipy.ndimage import binary_erosion, generate_binary_structure

        plane = generate_binary_structure(2, 1)[
            None
        ]  # the border is dropped within each slice: a segment may be one slice thick
        segment = segmentationNode.GetSegmentation().GetSegment(segmentId)
        image = segmentationNode.GetBinaryLabelmapInternalRepresentation(segmentId)
        array = slicer.util.arrayFromSegmentInternalBinaryLabelmap(segmentationNode, segmentId)
        value = segment.GetLabelValue()
        # where the segment's array starts in the volumes' voxels, and whether it is on their grid
        imageToWorld, worldToVolume = vtk.vtkMatrix4x4(), vtk.vtkMatrix4x4()
        image.GetImageToWorldMatrix(imageToWorld)
        volumeNodes[0].GetRASToIJKMatrix(worldToVolume)
        transform = np.array([[worldToVolume.GetElement(i, j) for j in range(4)] for i in range(4)]) @ np.array(
            [[imageToWorld.GetElement(i, j) for j in range(4)] for i in range(4)]
        )
        first = np.array(image.GetExtent()[::2] + (1,), dtype=float)
        start = transform @ first
        if not np.allclose(transform[:3, :3], np.eye(3), atol=1e-3):
            raise ValueError("The reference segmentation does not have the spacing and orientation of the volumes.")
        # a segment drawn on a grid a fraction of a voxel off (volumes with another origin) is put on the nearest voxel:
        # the half voxel at most is far less than the border that is dropped around each reference
        offset = np.round(start[:3]).astype(int)[::-1]  # [z, y, x]
        shapes = {tuple(slicer.util.arrayFromVolume(node).shape) for node in volumeNodes}
        if len(shapes) != 1:
            raise ValueError("The volumes have different sizes.")
        full = shapes.pop()

        # bounding box on a coarse grid
        coarse = max(int(np.ceil((array.size / 4_000_000) ** (1.0 / 3.0))), 1)
        found = np.argwhere(array[::coarse, ::coarse, ::coarse] == value)
        if len(found) == 0:
            raise ValueError("A reference segment is empty.")
        low = np.maximum(found.min(axis=0) * coarse - coarse, 0)
        high = np.minimum((found.max(axis=0) + 1) * coarse + coarse, array.shape)
        box = array[low[0] : high[0], low[1] : high[1], low[2] : high[2]]
        boxOffset = offset + low
        if np.any(boxOffset < 0) or np.any(boxOffset + box.shape > full):
            raise ValueError("The reference segmentation reaches outside the volumes.")

        stride = max(int(np.ceil((box.size / maxSamples) ** (1.0 / 3.0))), 1)
        while True:
            mask = box[::stride, ::stride, ::stride] == value
            inner = binary_erosion(mask, structure=plane, iterations=max(int(np.ceil(border / stride)), 1))
            if int(inner.sum()) >= MIN_STANDARD_PIXELS or stride <= max(stride // 2, 1):
                break
            stride = max(stride // 2, 1)
        if int(inner.sum()) < MIN_STANDARD_PIXELS:
            raise ValueError("A reference segment is too small (fewer than 20 voxels away from its border).")
        values = []
        for node in volumeNodes:
            volume = slicer.util.arrayFromVolume(node)
            view = volume[
                tuple(
                    slice(int(boxOffset[d]), int(boxOffset[d]) + stride * (inner.shape[d] - 1) + 1, stride)
                    for d in range(3)
                )
            ]
            values.append(view[inner].astype(np.float64))
        return values

    def createLabelVolume(self, referenceNode, names: List[str], colors, outputName: str):
        """Labelmap volume of one byte per voxel with the geometry of `referenceNode` and the classes as its color
        table (label n is `names[n - 1]`), without copying the reference. Its voxels are not initialized: the caller
        fills all of them."""
        labelNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", outputName)
        labelNode.CopyOrientation(referenceNode)
        image = vtk.vtkImageData()
        image.SetDimensions(referenceNode.GetImageData().GetDimensions())
        image.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
        labelNode.SetAndObserveImageData(image)
        labelNode.CreateDefaultDisplayNodes()
        colorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLColorTableNode", f"{outputName}_colors")
        colorNode.SetTypeToUser()
        colorNode.SetNumberOfColors(len(names) + 1)
        colorNode.SetColor(0, "Background", 0.0, 0.0, 0.0, 0.0)
        for value, (name, color) in enumerate(zip(names, colors), start=1):
            colorNode.SetColor(value, name, color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, 1.0)
        colorNode.SetNamesInitialised(True)
        labelNode.GetDisplayNode().SetAndObserveColorNodeID(colorNode.GetID())
        self._placeNextTo(referenceNode, labelNode)
        return labelNode

    def labelVolumeToSegmentation(self, labelNode):
        """Segmentation with one segment per class of `labelNode` (named and colored as its color table), which
        replaces the labelmap in the scene to free its memory."""
        name = labelNode.GetName()
        colorNode = labelNode.GetDisplayNode().GetColorNode()
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", name)
        segmentationNode.CreateDefaultDisplayNodes()
        segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(labelNode)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelNode, segmentationNode)
        self._placeNextTo(labelNode, segmentationNode)
        slicer.mrmlScene.RemoveNode(labelNode)
        slicer.mrmlScene.RemoveNode(colorNode)
        return segmentationNode

    @staticmethod
    def _placeNextTo(referenceNode, node):
        subjectHierarchy = slicer.mrmlScene.GetSubjectHierarchyNode()
        referenceItem = subjectHierarchy.GetItemByDataNode(referenceNode)
        subjectHierarchy.SetItemParent(
            subjectHierarchy.GetItemByDataNode(node), subjectHierarchy.GetItemParent(referenceItem)
        )
