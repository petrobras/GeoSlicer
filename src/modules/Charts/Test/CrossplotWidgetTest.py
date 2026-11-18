from Charts import CrossplotWidget
import Charts
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import wait, process_events, load_project
from commons.slicer.helpers import tryGetNode
from slicer.util import arrayFromTableColumn
from pathlib import Path
from typing import Tuple
import numpy as np
import cv2
import logging
import tempfile
import shutil
import pyqtgraph as pg
import pyqtgraph.exporters as pg_exporters

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
CROSSPLOT_RAW_PROJECT_FILE = TEST_RESOURCES_DIR / "CROSSPLOT_RAW" / "CROSSPLOT_RAW.mrml"
CROSSPLOT_TABLES_AND_WELLS_PROJECT_FILE = TEST_RESOURCES_DIR / "TABLES_AND_WELLS" / "TABLES_AND_WELLS.mrml"


def exportPlot(widget: CrossplotWidget, path: Path) -> None:
    try:
        plotItem = widget.dataPlotWidget._DataPlotWidget__plotItem
    except Exception as error:
        logging.info(f"PlotItem not found.\n{error}\n{dir(widget.dataPlotWidget)}")

        raise error

    exporter = pg_exporters.ImageExporter(plotItem)
    exporter.parameters()["width"] = 720
    exporter.export(path.as_posix())


def resetGraphData(widget: CrossplotWidget) -> None:
    for graphData in widget.graphDataList[:]:
        graphData.signalRemoved.emit()

    process_events()


def computeHistogram(image: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute the normalized histogram for an image.


    Args:
        image (_type_): The input image.

    Returns:
        np.ndarray: The normalized histogram.
    """
    # Convert the image to the HSV color space
    hsvImage = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # Calculate the histogram for each channel
    histH = cv2.calcHist([hsvImage], [0], None, [256], [0, 256])
    histS = cv2.calcHist([hsvImage], [1], None, [256], [0, 256])
    histV = cv2.calcHist([hsvImage], [2], None, [256], [0, 256])

    # Normalize the histograms
    histH = cv2.normalize(histH, histH).flatten()
    histS = cv2.normalize(histS, histS).flatten()
    histV = cv2.normalize(histV, histV).flatten()

    return histH, histS, histV


def compareHistograms(hist1: np.ndarray, hist2: np.ndarray) -> float:
    """Compare two histograms using the correlation method.


    Args:
        hist1 (np.ndarray): The first histogram.
        hist2 (np.ndarray): The second histogram.

    Returns:
        float: The comparison score.
    """
    scoreH = cv2.compareHist(hist1[0], hist2[0], cv2.HISTCMP_CORREL)
    scoreS = cv2.compareHist(hist1[1], hist2[1], cv2.HISTCMP_CORREL)
    scoreV = cv2.compareHist(hist1[2], hist2[2], cv2.HISTCMP_CORREL)

    return (scoreH + scoreS + scoreV) / 3.0


def compareImages(image1: Path, image2: Path) -> float:
    """Compare two images using the correlation method and return a comparison' score.

    Args:
        image1 (Path): The first image path object.
        image2 (Path): The second image path object.

    Returns:
        float: The comparison score.
    """
    img1 = cv2.imread(image1.as_posix())
    img2 = cv2.imread(image2.as_posix())

    hist1 = computeHistogram(img1)
    hist2 = computeHistogram(img2)
    score = compareHistograms(hist1, hist2)

    return score


class CrossplotWidgetTest(LTracePluginTest):
    def __init__(self, *args, **kwargs):
        kwargs["module_name"] = "Charts"
        super().__init__(*args, **kwargs)

    def post_setup(self) -> None:
        self.crossplotWidget = CrossplotWidget(plotLabel="Test")
        self.crossplotWidget.show()
        # Create the temporary directory used to store the test files
        self.__tempProjectDirPath = Path(tempfile.mkdtemp()).resolve()

        self.__widgets = {
            "xAxisComboBox": self.find_widget(
                name="X Axis Combo Box", obj=self.crossplotWidget, _type=pg.QtWidgets.QComboBox
            ),
            "yAxisComboBox": self.find_widget(
                name="Y Axis Combo Box", obj=self.crossplotWidget, _type=pg.QtWidgets.QComboBox
            ),
        }

        for key, widget in self.__widgets.items():
            assert widget is not None, f"Unable to found the widget related to the identifier '{key}'."

    def tear_down(self) -> None:
        # Remove the temporary directory used to store the test files
        if self.__tempProjectDirPath.exists():
            shutil.rmtree(self.__tempProjectDirPath)

        self.crossplotWidget.close()
        del self.crossplotWidget

    def generate_template_plots(self) -> None:
        load_project(CROSSPLOT_RAW_PROJECT_FILE)

        self.test_export_2D_plot(generateData=True)

    def test_export_2D_plot(self, generateData: bool = False) -> None:
        if not generateData:
            load_project(CROSSPLOT_RAW_PROJECT_FILE)

        # Reset graph data
        resetGraphData(self.crossplotWidget)

        # Get Nodes
        reportNode1 = tryGetNode("REPORT_1")
        reportNode2 = tryGetNode("REPORT_2")
        curveNode2 = tryGetNode("CURVE")

        assert reportNode1 is not None, "Node 'REPORT_1' not found."
        assert reportNode2 is not None, "Node 'REPORT_2' not found."
        assert curveNode2 is not None, "Node 'CURVE' not found."

        self.crossplotWidget.appendData(reportNode1)
        self.crossplotWidget.appendData(reportNode2)
        self.crossplotWidget.appendData(curveNode2)

        # Update colors from graphData
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
        for graphData in self.crossplotWidget.graphDataList:
            graphData.style.color = colors.pop()

        # Select X and Y parameters
        self.__widgets["xAxisComboBox"].setCurrentText("angle (deg)")
        self.__widgets["yAxisComboBox"].setCurrentText("label")

        wait(1)

        CROSSPLOT_OUTPUT_PLOT_2D_FILE = self.__tempProjectDirPath / "CROSSPLOT_OUTPUT_PLOT_2D.png"
        CROSSPLOT_TEMPLATE_PLOT_2D_FILE = TEST_RESOURCES_DIR / "CROSSPLOT_TEMPLATE_PLOT_2D.png"

        if generateData:
            exportPlot(self.crossplotWidget, CROSSPLOT_TEMPLATE_PLOT_2D_FILE)
        else:
            exportPlot(self.crossplotWidget, CROSSPLOT_OUTPUT_PLOT_2D_FILE)
        if generateData:
            return

        assert CROSSPLOT_TEMPLATE_PLOT_2D_FILE.exists(), (
            f"Plot template file not found: {CROSSPLOT_TEMPLATE_PLOT_2D_FILE}"
        )
        assert CROSSPLOT_OUTPUT_PLOT_2D_FILE.exists(), f"Plot output file not found: {CROSSPLOT_OUTPUT_PLOT_2D_FILE}"

        score = compareImages(CROSSPLOT_TEMPLATE_PLOT_2D_FILE, CROSSPLOT_OUTPUT_PLOT_2D_FILE)
        scoreThreshold = 0.998
        assert score > scoreThreshold, f"Expected score at least {scoreThreshold}, got {score}."

    def test_crossplot_merge_tables_by_wells(self):
        """Tests if tables were merged into a single table per well if tables without a WellName
        attribute were left unchanged
        """
        load_project(CROSSPLOT_TABLES_AND_WELLS_PROJECT_FILE)

        # Get Nodes
        nodes_names = [
            "vars1",
            "vars2",
            "c1 [ms]",
            "c3 [cal]",
            "c4 [cal]",
            "c5 [cal]",
            "c6 [s]",
            "ca [s]",
            "cb [A]",
            "cc [A]",
            "cd [A]",
        ]
        nodes = []
        for name in nodes_names:
            node = tryGetNode(name)
            assert node is not None, f"{name} node not found."
            nodes.append(node)

        # chartsWidget = getModuleWidget("Charts")

        mergedNodes = Charts.ChartsWidget.getNodesMergedByWell(nodes)

        wellA = ([node for node in mergedNodes if node.GetName() == "WellA"])[0]
        wellB = ([node for node in mergedNodes if node.GetName() == "WellB"])[0]
        vars1 = ([node for node in mergedNodes if node.GetName() == "vars1"])[0]
        vars2 = ([node for node in mergedNodes if node.GetName() == "vars2"])[0]

        # vars1 = input_data_widget.input_data_item.findItems("vars1", QtCore.Qt.MatchRecursive)
        assert vars1 is not None, "'vars1' not found in Crossplot Input data list."
        # vars2 = input_data_widget.findItems("vars2", QtCore.Qt.MatchRecursive)
        assert vars2 is not None, "'vars2' not found in Crossplot Input data list."
        # wellA = input_data_widget.findItems("WellA", QtCore.Qt.MatchRecursive)
        assert wellA is not None, "'wellA' not found in Crossplot Input data list."
        # wellB = input_data_widget.findItems("WellB", QtCore.Qt.MatchRecursive)
        assert wellB is not None, "'wellB' not found in Crossplot Input data list."

        # (The first 2 mergedNodes are the ones which didn't need merging (vars1 and vars2))

        wB1 = arrayFromTableColumn(wellB, mergedNodes[2].GetColumnName(1))
        wB2 = arrayFromTableColumn(wellB, mergedNodes[2].GetColumnName(2))
        wB3 = arrayFromTableColumn(wellB, mergedNodes[2].GetColumnName(3))
        wB4 = arrayFromTableColumn(wellB, mergedNodes[2].GetColumnName(4))
        wB5 = arrayFromTableColumn(wellB, mergedNodes[2].GetColumnName(5))
        np.testing.assert_array_equal(wB1, arrayFromTableColumn(nodes[2], nodes[2].GetColumnName(1)))
        np.testing.assert_array_equal(wB2, arrayFromTableColumn(nodes[3], nodes[3].GetColumnName(1)))
        np.testing.assert_array_equal(wB3, arrayFromTableColumn(nodes[4], nodes[4].GetColumnName(1)))
        np.testing.assert_array_equal(wB4, arrayFromTableColumn(nodes[5], nodes[5].GetColumnName(1)))
        np.testing.assert_array_equal(wB5, arrayFromTableColumn(nodes[6], nodes[6].GetColumnName(1)))

        wA1 = arrayFromTableColumn(wellA, mergedNodes[3].GetColumnName(1))
        wA2 = arrayFromTableColumn(wellA, mergedNodes[3].GetColumnName(2))
        wA3 = arrayFromTableColumn(wellA, mergedNodes[3].GetColumnName(3))
        wA4 = arrayFromTableColumn(wellA, mergedNodes[3].GetColumnName(4))
        np.testing.assert_array_equal(wA1, arrayFromTableColumn(nodes[7], nodes[7].GetColumnName(1)))
        np.testing.assert_array_equal(wA2, arrayFromTableColumn(nodes[8], nodes[8].GetColumnName(1)))
        np.testing.assert_array_equal(wA3, arrayFromTableColumn(nodes[9], nodes[9].GetColumnName(1)))
        np.testing.assert_array_equal(wA4, arrayFromTableColumn(nodes[10], nodes[10].GetColumnName(1)))
