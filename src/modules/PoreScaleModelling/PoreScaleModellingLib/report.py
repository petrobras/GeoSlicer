"""Report view for a simulation case: headline numbers, curves, and the tables behind them."""

import logging

import qt
import slicer

from ltrace.lbpm.results import LBPMResults
from ltrace.slicer.helpers import getPythonQtWidget

SUMMARY_LABELS = (
    ("frames", "Frames written"),
    ("steady_points", "Steady points"),
    ("last_timestep", "Last timestep"),
    ("sw_initial", "Initial saturation"),
    ("sw_final", "Final saturation"),
    ("krw_final", "Final krw"),
    ("krn_final", "Final krn"),
    ("porosity", "Porosity"),
)

CURVE_COLORS = ("#4fb8a3", "#e1a13a", "#8f7fe8", "#e16a6a", "#6aa9e1")


class ReportWidget(qt.QWidget):
    """Shows what a case produced. Works on a running case too: it reads whatever is on disk."""

    def __init__(self, parent=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.results = None
        self._plotWidget = None
        self.setup()

    def setup(self):
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.statusLabel = qt.QLabel("No results yet.")
        self.statusLabel.setWordWrap(True)
        layout.addWidget(self.statusLabel)

        self.summaryBox = qt.QGroupBox("Summary")
        self.summaryLayout = qt.QFormLayout(self.summaryBox)
        self.summaryValues = {}
        for key, label in SUMMARY_LABELS:
            value = qt.QLabel("—")
            value.objectName = f"Report {key}"
            self.summaryValues[key] = value
            self.summaryLayout.addRow(f"{label}:", value)
        self.summaryBox.visible = False
        layout.addWidget(self.summaryBox)

        self.plotContainer = qt.QWidget()
        self.plotContainerLayout = qt.QVBoxLayout(self.plotContainer)
        self.plotContainerLayout.setContentsMargins(0, 0, 0, 0)
        self.plotContainer.setMinimumHeight(420)
        layout.addWidget(self.plotContainer)

        self.tablesButton = qt.QPushButton("Create table nodes")
        self.tablesButton.objectName = "Report Tables Button"
        self.tablesButton.setToolTip(
            "Add the simulation logs to the scene as tables, so they can be plotted in Charts or exported."
        )
        self.tablesButton.enabled = False
        layout.addWidget(self.tablesButton)

    # -- population -----------------------------------------------------------------------------------
    def setResults(self, results: LBPMResults):
        self.results = results

        if results is None or not results.has_data:
            self.statusLabel.setText(
                "No simulation logs found in this folder yet. They appear as soon as the run writes its "
                "first analysis interval."
            )
            self.summaryBox.visible = False
            self.tablesButton.enabled = False
            self._clearPlots()
            return

        summary = results.summary()
        self.statusLabel.setText(f"Read from {results.case_dir.as_posix()}")
        self.summaryBox.visible = True
        self.tablesButton.enabled = True

        for key, label in self.summaryValues.items():
            value = summary.get(key)
            if value is None:
                label.setText("—")
            elif isinstance(value, float):
                label.setText(f"{value:.4g}")
            else:
                label.setText(str(value))

        self._drawPlots(results.curves())

    # -- plots ----------------------------------------------------------------------------------------
    def _clearPlots(self):
        if self._plotWidget is not None:
            self._plotWidget.setParent(None)
            self._plotWidget = None

    def _drawPlots(self, curves):
        self._clearPlots()
        if not curves:
            return

        try:
            import pyqtgraph as pg

            layoutWidget = pg.GraphicsLayoutWidget()
            layoutWidget.setBackground(None)

            for index, curve in enumerate(curves):
                plot = layoutWidget.addPlot(row=index // 2, col=index % 2, title=curve.title)
                plot.setLabel("bottom", curve.x_label)
                plot.setLabel("left", curve.y_label)
                plot.addLegend(offset=(-10, 10))
                plot.showGrid(x=True, y=True, alpha=0.2)

                for seriesIndex, (name, values) in enumerate(curve.series.items()):
                    pen = pg.mkPen(color=CURVE_COLORS[seriesIndex % len(CURVE_COLORS)], width=2)
                    plot.plot(list(curve.x), list(values), pen=pen, name=name)

            self._plotWidget = getPythonQtWidget(layoutWidget)
            if self._plotWidget is not None:
                self.plotContainerLayout.addWidget(self._plotWidget)
        except Exception as error:
            logging.warning(f"Unable to draw the LBPM report plots: {error}")
            fallback = qt.QLabel(f"Curves could not be drawn ({error}). The tables below hold the same data.")
            fallback.setWordWrap(True)
            self.plotContainerLayout.addWidget(fallback)
            self._plotWidget = fallback
