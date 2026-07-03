import PySide2 as pyside
import ctk
import numpy as np
import pyqtgraph as pg
import qt
import shiboken2
import slicer
from pyqtgraph.Qt import QtCore
from vtk.util.numpy_support import vtk_to_numpy

from .SubscaleModelWidget import SubscaleModelWidget
from ltrace.pore_networks.subres_models import (
    get_pore_network_volume_data,
    estimate_pressure,
    rebin_psd_log_uniform,
    make_log_uniform_bins,
)
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer.widget.customized_pyqtgraph.GraphicsLayoutWidget import GraphicsLayoutWidget
from PoreNetworkSimulationLib.constants import MICP

PA_TO_PSI = 0.000145038  # 1 Pa = 0.000145038 psi
MM_TO_UM = 1000  # 1 mm = 1000 µm


class MercurySimulationWidget(qt.QFrame):
    DEFAULT_VALUES = {
        "simulation type": MICP,
        "keep_temporary": False,
        "subres_model_name": "Fixed Radius",
        "subres_params": {"radius": 0.001},
        "subres_shape_factor": 0.04,
        "subres_porositymodifier": 1.0,
        "pressures": 100,
        "save_radii_distrib_plots": True,
        "experimental_radius": None,
    }

    def __init__(self):
        super().__init__()
        layout = qt.QFormLayout(self)

        self.subscaleModelWidget = SubscaleModelWidget()
        layout.addWidget(self.subscaleModelWidget)

        #
        # MICP Graph visualization
        #
        self.micpCollapsibleButton = ctk.ctkCollapsibleButton()
        self.micpCollapsibleButton.text = "MICP Visualization"
        self.micpCollapsibleButton.setChecked(False)
        layout.addRow(self.micpCollapsibleButton)
        micpFormLayout = qt.QFormLayout(self.micpCollapsibleButton)

        # input volume selector
        self.micpSelector = hierarchyVolumeInput(nodeTypes=["vtkMRMLTableNode"])
        self.micpSelector.showEmptyHierarchyItems = False
        self.micpSelector.addNodeAttributeIncludeFilter("table_type", "micp")
        self.micpSelector.currentItemChanged.connect(self.onChangeMicp)
        labelWidget = qt.QLabel("Simulation Results Node: ")

        micpSelectorLayout = qt.QHBoxLayout()
        micpSelectorLayout.addWidget(self.micpSelector)
        self.toggleMicpButton = qt.QPushButton("Hide")
        self.toggleMicpButton.setCheckable(True)
        self.toggleMicpButton.setChecked(True)
        self.toggleMicpButton.setToolTip("Toggle simulation plots visibility")
        self.toggleMicpButton.toggled.connect(self.onToggleMicpPlots)
        self.toggleMicpButton.setFixedWidth(50)
        micpSelectorLayout.addWidget(self.toggleMicpButton)
        micpFormLayout.addRow(labelWidget, micpSelectorLayout)

        self.sirrSelector = hierarchyVolumeInput(nodeTypes=["vtkMRMLTableNode"])
        self.sirrSelector.showEmptyHierarchyItems = False
        self.sirrSelector.addNodeAttributeIncludeFilter("table_type", "micp")
        self.sirrSelector.setToolTip("Select a SIRR imported MICP table node.")
        self.sirrSelector.objectName = "SIRR Input Selector"
        self.sirrSelector.currentItemChanged.connect(self.onChangeSirrMicp)
        sirrLabelWidget = qt.QLabel("Reference Table Node: ")

        sirrSelectorLayout = qt.QHBoxLayout()
        sirrSelectorLayout.addWidget(self.sirrSelector)
        self.toggleSirrButton = qt.QPushButton("Hide")
        self.toggleSirrButton.setCheckable(True)
        self.toggleSirrButton.setChecked(True)
        self.toggleSirrButton.setToolTip("Toggle SIRR plots visibility")
        self.toggleSirrButton.toggled.connect(self.onToggleSirrPlots)
        self.toggleSirrButton.setFixedWidth(50)
        sirrSelectorLayout.addWidget(self.toggleSirrButton)
        micpFormLayout.addRow(sirrLabelWidget, sirrSelectorLayout)

        # plots
        pysideReportForm = shiboken2.wrapInstance(hash(micpFormLayout), pyside.QtWidgets.QFormLayout)
        self.subvolumeGraphicsLayout = GraphicsLayoutWidget()
        self.subvolumeGraphicsLayout.setMinimumHeight(600)
        self.subvolumeGraphicsLayout.setMinimumWidth(100)

        # SIRR Plots (Background)
        self.micpPlotItem = self.subvolumeGraphicsLayout.addPlot(
            row=1, col=1, rowspan=1, colspan=1, left="Pressure (Pa)", bottom="Mercury saturation"
        )
        self.micpLegend = self.micpPlotItem.addLegend(offset=(-10, 10))
        self.micpSirrSeries = self.micpPlotItem.plot(
            name="Reference",
            pen=pg.mkPen((255, 100, 100), width=2, style=QtCore.Qt.DotLine),
            symbol="t",
            symbolPen=(255, 100, 100),
            symbolSize=8,
            symbolBrush=(255, 100, 100),
        )
        self.micpSirrSeries.getViewBox().invertX(True)
        self.resolutionLine = pg.InfiniteLine(
            angle=0,
            movable=False,
            pen=pg.mkPen((200, 200, 200), width=2, style=QtCore.Qt.DashLine),
            label="Resolution limit",
            labelOpts={
                "position": 0.1,
                "color": (200, 200, 200),
                "movable": True,
                "fill": (0, 0, 0, 150),
            },
        )
        self.micpPlotItem.addItem(self.resolutionLine)
        self.resolutionLine.hide()

        self.pcPlotItem = self.subvolumeGraphicsLayout.addPlot(
            row=2, col=1, rowspan=1, colspan=1, left="Pore volume fraction (%)", bottom="Pressure (Pa)"
        )
        self.pcLegend = self.pcPlotItem.addLegend(offset=(-10, 10))
        self.pcResolutionLine = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen((200, 200, 200), width=2, style=QtCore.Qt.DashLine),
            label="Resolution limit",
            labelOpts={
                "position": 0.9,
                "color": (200, 200, 200),
                "movable": True,
                "fill": (0, 0, 0, 150),
            },
        )
        self.pcPlotItem.addItem(self.pcResolutionLine)
        self.pcResolutionLine.hide()
        self.pcSirrSeries = self.pcPlotItem.plot(
            name="Reference",
            pen=pg.mkPen((100, 200, 100), width=2, style=QtCore.Qt.DotLine),
            symbol="t",
            symbolPen=(100, 200, 100),
            symbolSize=8,
            symbolBrush=(100, 200, 100),
        )

        self.radiiPlotItem = self.subvolumeGraphicsLayout.addPlot(
            row=3, col=1, rowspan=1, colspan=1, left="Pore volume fraction (%)", bottom="Radius (µm)"
        )
        self.radiiLegend = self.radiiPlotItem.addLegend(offset=(10, 10))
        self.radiiResolutionLine = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen((200, 200, 200), width=2, style=QtCore.Qt.DashLine),
            label="Resolution limit",
            labelOpts={
                "position": 0.9,
                "color": (200, 200, 200),
                "movable": True,
                "fill": (0, 0, 0, 150),
            },
        )
        self.radiiPlotItem.addItem(self.radiiResolutionLine)
        self.radiiResolutionLine.hide()
        self.radiiSirrSeries = self.radiiPlotItem.plot(
            name="Reference",
            pen=pg.mkPen((150, 150, 255), width=2, style=QtCore.Qt.DotLine),
            symbol="t",
            symbolPen=(150, 150, 255),
            symbolSize=8,
            symbolBrush=(150, 150, 255),
        )

        # Simulation Plots (Foreground)
        self.micpSeries = self.micpPlotItem.plot(
            name="Simulation",
            pen=pg.mkPen("r", width=2, style=QtCore.Qt.DashLine),
            symbol="o",
            symbolPen="r",
            symbolSize=8,
            symbolBrush="r",
        )
        self.pcSeries = self.pcPlotItem.plot(
            name="Simulation",
            pen=pg.mkPen("g", width=2, style=QtCore.Qt.DashLine),
            symbol="o",
            symbolPen="g",
            symbolSize=8,
            symbolBrush="g",
        )
        self.radiiSeries = self.radiiPlotItem.plot(
            name="Simulation",
            pen=pg.mkPen((50, 50, 255), width=2, style=QtCore.Qt.DashLine),
            symbol="o",
            symbolPen=(50, 50, 255),
            symbolSize=8,
            symbolBrush=(50, 50, 255),
        )

        pysideReportForm.addRow(self.subvolumeGraphicsLayout)

        # Plot options collapsible
        self.plotOptionsCollapsible = ctk.ctkCollapsibleButton()
        self.plotOptionsCollapsible.text = "Plot options"
        self.plotOptionsCollapsible.collapsed = True
        self.plotOptionsCollapsible.flat = True
        micpFormLayout.addRow(self.plotOptionsCollapsible)
        plotOptionsLayout = qt.QFormLayout(self.plotOptionsCollapsible)

        self.show_resolution_lines_checkbox = qt.QCheckBox()
        self.show_resolution_lines_checkbox.checked = True
        self.show_resolution_lines_checkbox.toggled.connect(self.onShowResolutionLinesToggled)
        plotOptionsLayout.addRow("Show resolution limit:", self.show_resolution_lines_checkbox)

        self.show_legend_checkbox = qt.QCheckBox()
        self.show_legend_checkbox.checked = True
        self.show_legend_checkbox.toggled.connect(self.onToggleLegend)
        plotOptionsLayout.addRow("Show legend:", self.show_legend_checkbox)

        # Unit selector
        self.pressureUnitGroup = qt.QButtonGroup(self)
        self.paRadioButton = qt.QRadioButton("Pa")
        self.paRadioButton.setChecked(True)
        self.psiRadioButton = qt.QRadioButton("psi")
        self.pressureUnitGroup.addButton(self.paRadioButton)
        self.pressureUnitGroup.addButton(self.psiRadioButton)
        pressureUnitLayout = qt.QHBoxLayout()
        pressureUnitLayout.addWidget(self.paRadioButton)
        pressureUnitLayout.addWidget(self.psiRadioButton)
        pressureUnitLayout.addStretch()
        self.paRadioButton.toggled.connect(self.onUnitChanged)
        plotOptionsLayout.addRow("Pressure unit:", pressureUnitLayout)

        self.radiusUnitGroup = qt.QButtonGroup(self)
        self.mmRadioButton = qt.QRadioButton("mm")
        self.umRadioButton = qt.QRadioButton("µm")
        self.umRadioButton.setChecked(True)
        self.radiusUnitGroup.addButton(self.mmRadioButton)
        self.radiusUnitGroup.addButton(self.umRadioButton)
        radiusUnitLayout = qt.QHBoxLayout()
        radiusUnitLayout.addWidget(self.mmRadioButton)
        radiusUnitLayout.addWidget(self.umRadioButton)
        radiusUnitLayout.addStretch()
        self.mmRadioButton.toggled.connect(self.onUnitChanged)
        plotOptionsLayout.addRow("Radius unit:", radiusUnitLayout)

        self.logUniformRebinCheckBox = qt.QCheckBox()
        self.logUniformRebinCheckBox.checked = False
        self.logUniformRebinCheckBox.setToolTip("Rebin both distributions to log-uniform bins for direct comparison")
        self.logUniformRebinCheckBox.toggled.connect(self.onLogUniformRebinToggled)
        plotOptionsLayout.addRow("Log-uniform rebinning:", self.logUniformRebinCheckBox)

        self.densityNormCheckBox = qt.QCheckBox()
        self.densityNormCheckBox.checked = False
        self.densityNormCheckBox.enabled = False
        self.densityNormCheckBox.setToolTip(
            "Normalize rebinned histogram to probability density (divide by bin width). "
            "When off, bars show probability mass per bin."
        )
        self.densityNormCheckBox.toggled.connect(self.onLogUniformRebinToggled)
        self.logUniformRebinCheckBox.toggled.connect(self.onLogUniformRebinCheckBoxToggled)
        plotOptionsLayout.addRow("Probability density:", self.densityNormCheckBox)

        # Log scale checkboxes
        self.logPcCheckBox = qt.QCheckBox("Pressure")
        self.logRadiiCheckBox = qt.QCheckBox("Radius")
        self.logPcCheckBox.toggled.connect(self.onLogScaleToggled)
        self.logRadiiCheckBox.toggled.connect(self.onLogScaleToggled)
        self.logPcCheckBox.setChecked(True)
        self.logRadiiCheckBox.setChecked(True)
        logLayout = qt.QHBoxLayout()
        logLayout.addWidget(self.logPcCheckBox)
        logLayout.addWidget(self.logRadiiCheckBox)
        logLayout.addStretch()
        plotOptionsLayout.addRow("Log scale:", logLayout)

        self.onLogScaleToggled()

    def setVolumeNode(self, node):
        self.current_node = node
        self.subscaleModelWidget.setVolumeNode(node)
        self.updateResolutionLines(node)

    def onUnitChanged(self):
        pressure_unit = "Pa" if self.paRadioButton.isChecked() else "psi"
        self.micpPlotItem.setLabel("left", f"Pressure ({pressure_unit})")
        self.pcPlotItem.setLabel("bottom", f"Pressure ({pressure_unit})")

        radius_unit = "mm" if self.mmRadioButton.isChecked() else "µm"
        self.radiiPlotItem.setLabel("bottom", f"Radius ({radius_unit})")

        self.onChangeSirrMicp()
        self.onChangeMicp()
        self.updateResolutionLines(getattr(self, "current_node", None))

    def onLogUniformRebinCheckBoxToggled(self, checked):
        self.densityNormCheckBox.enabled = checked
        if not checked:
            self.densityNormCheckBox.checked = False

    def onLogUniformRebinToggled(self):
        self.onChangeSirrMicp()
        self.onChangeMicp()

    def onLogScaleToggled(self):
        logPc = self.logPcCheckBox.checked
        logRadii = self.logRadiiCheckBox.checked

        self.micpPlotItem.setLogMode(y=logPc)
        self.pcPlotItem.setLogMode(x=logPc)
        self.radiiPlotItem.setLogMode(x=logRadii)

        self.updateResolutionLines(getattr(self, "current_node", None))

    def updateResolutionLines(self, node):
        if node is not None and self.show_resolution_lines_checkbox.checked:
            volume_data = get_pore_network_volume_data(node)
            spacing = volume_data.get("spacing", {})
            min_spacing = min(spacing.values()) if spacing else 1.0
            pressure = estimate_pressure(min_spacing)
            if self.psiRadioButton.isChecked():
                pressure *= PA_TO_PSI

            radius = min_spacing
            if self.umRadioButton.isChecked():
                radius *= MM_TO_UM

            logPc = self.logPcCheckBox.checked
            logRadii = self.logRadiiCheckBox.checked

            pressure_val = np.log10(pressure) if logPc else pressure
            radius_val = np.log10(radius) if logRadii else radius

            self.resolutionLine.setValue(pressure_val)
            self.resolutionLine.show()
            self.pcResolutionLine.setValue(pressure_val)
            self.pcResolutionLine.show()
            self.radiiResolutionLine.setValue(radius_val)
            self.radiiResolutionLine.show()
        else:
            self.resolutionLine.hide()
            self.pcResolutionLine.hide()
            self.radiiResolutionLine.hide()

    def onShowResolutionLinesToggled(self, checked):
        self.updateResolutionLines(getattr(self, "current_node", None))

    def onToggleLegend(self, checked):
        if checked:
            self.micpLegend.show()
            self.pcLegend.show()
            self.radiiLegend.show()
        else:
            self.micpLegend.hide()
            self.pcLegend.hide()
            self.radiiLegend.hide()

    def getSirrSelector(self):
        return self.sirrSelector

    def onToggleMicpPlots(self, visible):
        self.toggleMicpButton.setText("Hide" if visible else "Show")
        if visible:
            self.micpSeries.show()
            self.pcSeries.show()
            self.radiiSeries.show()
            self.onChangeMicp()
        else:
            self.micpSeries.hide()
            self.pcSeries.hide()
            self.radiiSeries.hide()

    def onToggleSirrPlots(self, visible):
        self.toggleSirrButton.setText("Hide" if visible else "Show")
        if visible:
            self.micpSirrSeries.show()
            self.pcSirrSeries.show()
            self.radiiSirrSeries.show()
            self.onChangeSirrMicp()
        else:
            self.micpSirrSeries.hide()
            self.pcSirrSeries.hide()
            self.radiiSirrSeries.hide()

    def _rebin(self, x, y, bins_source=None):
        """Rebin (x, y) to log-uniform bins.

        y is expected in % and will be converted to fraction internally.
        bins_source defines the bin range and count; defaults to x itself.

        When the "Probability density" checkbox is checked, the returned
        heights are divided by the linear width of each bin and re-normalized
        to sum to 100, converting probability mass into probability density.
        """
        src = bins_source if bins_source is not None else x
        src_pos = src[src > 0]
        if src_pos.size == 0:
            return np.array([]), np.array([])

        bins = make_log_uniform_bins(src_pos.min(), src_pos.max(), n_bins=len(src))
        hist, centers = rebin_psd_log_uniform(x, y / 100, bins)
        if self.densityNormCheckBox.checked:
            bin_widths = np.diff(bins)
            if hist.size and bin_widths.size == hist.size:
                hist = hist / bin_widths
                hist_sum = hist.sum()
                if hist_sum > 0:
                    hist = (hist / hist_sum) * 100
        return hist, centers

    def _clearRefData(self):
        """Clear the Sirr/reference series and drop any cached reference arrays."""
        self.micpSirrSeries.clear()
        self.pcSirrSeries.clear()
        self.radiiSirrSeries.clear()
        for attr in (
            "ref_pc_values",
            "ref_snwp_values",
            "ref_pc_x_values",
            "ref_pc_y_values",
            "ref_radius_x_values",
            "ref_radius_y_values",
        ):
            if hasattr(self, attr):
                delattr(self, attr)

    def onChangeSirrMicp(self):
        sirr_table_node = self.sirrSelector.currentNode()
        if not sirr_table_node:
            self._clearRefData()
            return
        pc_table_id = sirr_table_node.GetAttribute("pc_table_id")
        radius_table_id = sirr_table_node.GetAttribute("radius_table_id")

        if not isinstance(pc_table_id, str) or not isinstance(radius_table_id, str):
            self._clearRefData()
            return

        pc_table = slicer.mrmlScene.GetNodeByID(pc_table_id)
        radius_table = slicer.mrmlScene.GetNodeByID(radius_table_id)

        if not pc_table or not radius_table:
            self._clearRefData()
            return

        # Load reference data in base units (Pa, mm)
        self.ref_pc_values = vtk_to_numpy(sirr_table_node.GetTable().GetColumnByName("pc")).copy()
        self.ref_snwp_values = vtk_to_numpy(sirr_table_node.GetTable().GetColumnByName("snwp")).copy()
        self.ref_pc_x_values = vtk_to_numpy(pc_table.GetTable().GetColumnByName("pc")).copy()
        self.ref_pc_y_values = vtk_to_numpy(pc_table.GetTable().GetColumnByName("dsn")).copy()
        self.ref_radius_x_values = vtk_to_numpy(radius_table.GetTable().GetColumnByName("radius")).copy()
        self.ref_radius_y_values = vtk_to_numpy(radius_table.GetTable().GetColumnByName("dsn")).copy()

        pc_values = self.ref_pc_values.copy()
        pc_x = self.ref_pc_x_values.copy()
        pc_y = self.ref_pc_y_values.copy()
        radius_x = self.ref_radius_x_values.copy()
        radius_y = self.ref_radius_y_values.copy()

        if self.logUniformRebinCheckBox.checked:
            pc_y, pc_x = self._rebin(pc_x, pc_y)
            radius_y, radius_x = self._rebin(radius_x, radius_y)
        else:
            pc_x, pc_y = pc_x[:-1], pc_y[:-1]
            radius_x, radius_y = radius_x[:-1], radius_y[:-1]

        # Apply unit conversion
        if self.psiRadioButton.isChecked():
            pc_values *= PA_TO_PSI
            pc_x *= PA_TO_PSI
        if self.umRadioButton.isChecked():
            radius_x *= MM_TO_UM

        self.micpSirrSeries.setData(self.ref_snwp_values, pc_values)
        self.pcSirrSeries.setData(pc_x, pc_y)
        self.radiiSirrSeries.setData(radius_x, radius_y)

    def onChangeMicp(self):
        micp_table_node = self.micpSelector.currentNode()
        if not micp_table_node:
            self.micpSeries.clear()
            self.pcSeries.clear()
            self.radiiSeries.clear()
            return
        pc_table_id = micp_table_node.GetAttribute("pc_table_id")
        radius_table_id = micp_table_node.GetAttribute("radius_table_id")

        if not isinstance(pc_table_id, str) or not isinstance(radius_table_id, str):
            self.micpSeries.clear()
            self.pcSeries.clear()
            self.radiiSeries.clear()
            return

        pc_table = slicer.mrmlScene.GetNodeByID(pc_table_id)
        radius_table = slicer.mrmlScene.GetNodeByID(radius_table_id)

        if not pc_table or not radius_table:
            return

        # Load simulation data
        pc_values = vtk_to_numpy(micp_table_node.GetTable().GetColumnByName("pc")).copy()
        snwp_values = vtk_to_numpy(micp_table_node.GetTable().GetColumnByName("snwp")).copy()
        pc_x = vtk_to_numpy(pc_table.GetTable().GetColumnByName("pc")).copy()
        pc_y = vtk_to_numpy(pc_table.GetTable().GetColumnByName("dsn")).copy()
        radius_x = vtk_to_numpy(radius_table.GetTable().GetColumnByName("radius")).copy()
        radius_y = vtk_to_numpy(radius_table.GetTable().GetColumnByName("dsn")).copy()

        # Load reference data in base units (Pa, mm) if available.
        has_ref = hasattr(self, "ref_pc_x_values")
        ref_pc_x = self.ref_pc_x_values.copy() if has_ref else None
        ref_pc_y = self.ref_pc_y_values.copy() if has_ref else None
        ref_radius_x = self.ref_radius_x_values.copy() if has_ref else None
        ref_radius_y = self.ref_radius_y_values.copy() if has_ref else None

        if self.logUniformRebinCheckBox.checked:
            bins_source_pc = ref_pc_x
            bins_source_radius = ref_radius_x
            if ref_pc_x is not None:
                ref_pc_y, ref_pc_x = self._rebin(ref_pc_x, ref_pc_y)
                ref_radius_y, ref_radius_x = self._rebin(ref_radius_x, ref_radius_y)
            pc_y, pc_x = self._rebin(pc_x, pc_y, bins_source=bins_source_pc)
            radius_y, radius_x = self._rebin(radius_x, radius_y, bins_source=bins_source_radius)
        else:
            pc_x, pc_y = pc_x[:-1], pc_y[:-1]
            radius_x, radius_y = radius_x[:-1], radius_y[:-1]
            if ref_pc_x is not None:
                ref_pc_x, ref_pc_y = ref_pc_x[:-1], ref_pc_y[:-1]
                ref_radius_x, ref_radius_y = ref_radius_x[:-1], ref_radius_y[:-1]

        # Apply unit conversion
        if self.psiRadioButton.isChecked():
            pc_values *= PA_TO_PSI
            pc_x *= PA_TO_PSI
            if ref_pc_x is not None:
                ref_pc_x *= PA_TO_PSI
        if self.umRadioButton.isChecked():
            radius_x *= MM_TO_UM
            if ref_radius_x is not None:
                ref_radius_x *= MM_TO_UM

        self.micpSeries.setData(snwp_values, pc_values)
        self.pcSeries.setData(pc_x, pc_y)
        self.radiiSeries.setData(radius_x, radius_y)
        if ref_pc_x is not None:
            self.pcSirrSeries.setData(ref_pc_x, ref_pc_y)
            self.radiiSirrSeries.setData(ref_radius_x, ref_radius_y)

    def getParams(self, node):
        subscale_model_params = self.subscaleModelWidget.getParams()
        subres_model_name = self.subscaleModelWidget.microscale_model_dropdown.currentText
        widget = self.subscaleModelWidget.parameter_widgets[subres_model_name]
        if (subres_model_name == "Throat Radius Curve" or subres_model_name == "Pressure Curve") and hasattr(
            widget, "_get_params_with_data"
        ):
            subres_params = widget._get_params_with_data()
        else:
            subres_params = widget.get_params()
        subres_shape_factor = subscale_model_params["subres_shape_factor"]
        subres_porositymodifier = subscale_model_params["subres_porositymodifier"]

        subres_params_copy = {}
        if (subres_model_name == "Throat Radius Curve" or subres_model_name == "Pressure Curve") and subres_params:
            for i in subres_params.keys():
                if isinstance(subres_params[i], (list, np.ndarray)):
                    subres_params_copy[i] = np.asarray(subres_params[i]).tolist()
                else:
                    subres_params_copy[i] = subres_params[i]
        else:
            subres_params_copy = subres_params

        params = {
            "simulation type": MICP,
            "keep_temporary": False,
            "subres_model_name": subres_model_name,
            "subres_shape_factor": subres_shape_factor,
            "subres_porositymodifier": subres_porositymodifier,
            "subres_params": subres_params_copy,
            "pressures": 100,
            "save_radii_distrib_plots": True,
            "experimental_radius": subres_params_copy.get("pore radii") if subres_params_copy else None,
        }

        if type(node) is slicer.vtkMRMLTableNode:
            params.update(get_pore_network_volume_data(node))
        return params

    def setParams(self, params):
        self.subscaleModelWidget.microscale_model_dropdown.setCurrentText(params["subres_model_name"])
        self.subscaleModelWidget.setParams(params)
