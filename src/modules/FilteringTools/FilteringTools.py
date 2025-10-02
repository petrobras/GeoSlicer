import os
from pathlib import Path

import qt
import slicer.util
from ltrace.slicer_utils import *
from ltrace.slicer import helpers
from ltrace.slicer.node_attributes import NodeEnvironment

from CustomizedCurvatureAnisotropicDiffusion import CustomizedCurvatureAnisotropicDiffusion
from CustomizedGaussianBlurImageFilter import CustomizedGaussianBlurImageFilter
from CustomizedGradientAnisotropicDiffusion import CustomizedGradientAnisotropicDiffusion
from CustomizedMedianImageFilter import CustomizedMedianImageFilter
from ShadingCorrection import ShadingCorrection


class FilteringTools(LTracePlugin):
    SETTING_KEY = "FilteringTools"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Filter"
        self.parent.categories = ["Tools", "MicroCT", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.setHelpUrl("Volumes/Filter/MicroCTFlowApplyFilters.html", NodeEnvironment.MICRO_CT)
        self.setHelpUrl("Multiscale/VolumesPreProcessing/Filter.html", NodeEnvironment.MULTISCALE)

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class FilteringToolsWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)
        self.currentWidget = None

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        self.formLayout = qt.QFormLayout(frame)
        self.formLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.filters = [
            ("Select a filtering tool", None),
            (
                "Gradient Anisotropic Diffusion",
                slicer.modules.customizedgradientanisotropicdiffusion.createNewWidgetRepresentation(),
            ),
            (
                "Curvature Anisotropic Diffusion",
                slicer.modules.customizedcurvatureanisotropicdiffusion.createNewWidgetRepresentation(),
            ),
            (
                "Gaussian Blur Image Filter",
                slicer.modules.customizedgaussianblurimagefilter.createNewWidgetRepresentation(),
            ),
            (
                "Median Image Filter",
                slicer.modules.customizedmedianimagefilter.createNewWidgetRepresentation(),
            ),
            (
                "Simple Filters",
                slicer.modules.simplefilters.createNewWidgetRepresentation(),
            ),
            (
                "Shading correction - Gaussian",
                slicer.modules.shadingcorrection.createNewWidgetRepresentation(),
            ),
            (
                "Shading correction - Polynomial",
                slicer.modules.polynomialshadingcorrection.createNewWidgetRepresentation(),
            ),
        ]

        self.toolComboBox = qt.QComboBox()
        self.toolComboBox.setCurrentIndex(0)
        self.toolComboBox.setToolTip("Select a filtering tool.")
        self.toolComboBox.currentIndexChanged.connect(self.onToolComboBoxCurrentIndexChanged)

        self.formLayout.addRow("Filtering tool:", self.toolComboBox)

        for i, (name, widget) in enumerate(self.filters):
            self.toolComboBox.addItem(name, i)
            self.formLayout.addRow(widget)
        self.hideFilteringToolsWidgets()

        self.layout.addStretch()

    def onToolComboBoxCurrentIndexChanged(self, index):
        self.hideFilteringToolsWidgets()
        self.currentWidget = self.filters[index][1]
        if self.currentWidget:
            self.currentWidget.visible = True
            self.currentWidget.enter()

    def hideFilteringToolsWidgets(self):
        for _, widget in self.filters[1:]:
            widget.visible = False
        if self.currentWidget:
            self.currentWidget.exit()
        self.currentWidget = None

    def exit(self):
        self.toolComboBox.setCurrentIndex(0)
