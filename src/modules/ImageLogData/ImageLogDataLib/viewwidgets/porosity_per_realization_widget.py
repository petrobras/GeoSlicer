import numpy as np
import PySide2
import qt
import shiboken2
import slicer

from .base_view_widget import BaseViewWidget
from ImageLogDataLib.view.View import CurvePlot, SECONDARY_VIEW_BOX
from ltrace.slicer.graph_data import LINE_PLOT_TYPE, SCATTER_PLOT_TYPE
from ltrace.slicer_utils import tableNodeToDict


class PorosityPerRealizationViewWidget(BaseViewWidget):
    def __init__(self, parent, view_data, primary_node):
        super().__init__()
        self.view_data = view_data

        view_widget_layout = qt.QVBoxLayout(parent)
        view_widget_layout.setContentsMargins(0, 0, 0, 0)
        self.curve_plot = CurvePlot()
        self.curve_plot.set_background("#FFFFFF")
        self.curve_plot._plot_item.setContentsMargins(-7, -7, -6, -6)
        self.curve_plot._plot_item.hideButtons()
        self.curve_plot._plot_item.hideAxis("left")
        self.curve_plot._plot_item.hideAxis("bottom")
        self.curve_plot._plot_item.showAxis("top")
        self.curve_plot._plot_item.getAxis("top").setPen(color=(0, 0, 0))
        self.curve_plot._plot_item.getAxis("top").setTextPen(color=(0, 0, 0))
        self.curve_plot._plot_item.ctrlMenu.actions()[0].setVisible(False)
        self.__primary_table_dict = tableNodeToDict(primary_node)

        if view_data.primaryTableNodeColumn != "":
            if view_data.primaryTableNodePlotType == LINE_PLOT_TYPE:
                primary_plot_type = LINE_PLOT_TYPE
                primary_plot_symbol = None
            else:
                primary_plot_type = SCATTER_PLOT_TYPE
                primary_plot_symbol = view_data.primaryTableNodePlotType

            column_List = view_data.primaryTableNodeColumnList.copy()

            self.curve_plot.add_data(
                data_node=primary_node,
                x_parameter=view_data.primaryTableNodeColumn,
                y_parameter="DEPTH",
                plot_type=primary_plot_type,
                color=view_data.primaryTableNodePlotColor,
                symbol=primary_plot_symbol,
                size=10,
            )
            column_List.remove(view_data.primaryTableNodeColumn)

            if "TI" in column_List:
                self.curve_plot.add_data(
                    data_node=primary_node,
                    x_parameter="TI",
                    y_parameter="DEPTH",
                    plot_type=primary_plot_type,
                    color="#0000FF",
                    symbol=primary_plot_symbol,
                    size=10,
                )
                column_List.remove("TI")

            if column_List:
                self.curve_plot.add_data(
                    data_node=primary_node,
                    x_parameter=column_List,
                    y_parameter="DEPTH",
                    plot_type=primary_plot_type,
                    color="#000000",
                    symbol=primary_plot_symbol,
                )

        # Secondary table node
        secondary_table_node = self.__get_node_by_id(view_data.secondaryTableNodeId)
        if secondary_table_node is not None and view_data.secondaryTableNodeColumn != "":
            if view_data.secondaryTableNodePlotType == LINE_PLOT_TYPE:
                secondary_plot_type = LINE_PLOT_TYPE
                secondary_plot_symbol = None
            else:
                secondary_plot_type = SCATTER_PLOT_TYPE
                secondary_plot_symbol = view_data.secondaryTableNodePlotType

            self.curve_plot.add_data(
                data_node=secondary_table_node,
                x_parameter=view_data.secondaryTableNodeColumn,
                y_parameter="DEPTH",
                plot_type=secondary_plot_type,
                color=view_data.secondaryTableNodePlotColor,
                symbol=secondary_plot_symbol,
                view_box=SECONDARY_VIEW_BOX,
            )

        pyside_qvbox_layout = shiboken2.wrapInstance(hash(view_widget_layout), PySide2.QtWidgets.QVBoxLayout)
        graphics_layout_widget = self.curve_plot._graphics_layout_widget
        pyside_qvbox_layout.addWidget(graphics_layout_widget)

    def getPlot(self):
        return self.curve_plot

    def set_range(self, current_range):
        if self.curve_plot is not None:
            self.curve_plot.set_y_range(*current_range[::-1])

    def getGraphX(self, view_x, width):
        range = self.curve_plot._plot_item.viewRange()
        hDif = range[0][1] - range[0][0]
        if hDif == 0:
            xScale = 1
            xOffset = 0
        else:
            xScale = width / hDif
            xOffset = range[0][0] * xScale

        xDepth = (view_x + xOffset) / xScale

        return xDepth

    def getBounds(self):
        bounds = self.curve_plot.get_data_range()
        _, (y_min, y_max) = bounds
        y_min = y_min if y_min is not None else 0
        y_max = y_max if y_max is not None else 0
        bounds = (-1 * y_max, -1 * y_min)
        return bounds

    def getValue(self, x, y):
        primary_dict = self.__primary_table_dict
        depths = primary_dict["DEPTH"]
        index_pairs = self.__get_bounding_depth_indices(depths, y)
        values_column_name = self.view_data.primaryTableNodeColumn
        values = primary_dict[values_column_name]
        minimum_distance = (
            abs(np.nanmax(values) - np.nanmin(values)) / 4
        )  # Minimum detection distance by mouse is 25% of the data range
        value = self.__get_intermediary_value(values, depths, index_pairs, x, y, minimum_distance)

        return value

    def __get_node_by_id(self, nodeId):
        if nodeId is not None:
            return slicer.mrmlScene.GetNodeByID(nodeId)
        return None

    def __on_logmode_changed(self, activated):
        self.view_data.logMode = activated
        self.signalUpdated.emit()

    def __get_bounding_depth_indices(self, depths, y):
        index_pairs = []
        adjusted_y = y * 1000  # converted from m to mm
        for i in range(len(depths) - 1):
            if depths[i] < adjusted_y < depths[i + 1] or depths[i] > adjusted_y > depths[i + 1]:
                index_pairs.append((i, i + 1))
        return index_pairs

    def __get_intermediary_value(self, values, depths, index_pairs, x, y, maximum_distance=float("inf")):
        closest = None
        shortest_distance = float("inf")
        for pair in index_pairs:
            depth1 = depths[pair[0]] / 1000
            depth2 = depths[pair[1]] / 1000
            value1 = values[pair[0]]
            value2 = values[pair[1]]
            if value1 == value2:
                corresponding_value = value1
            else:
                a = (depth1 - depth2) / (value1 - value2)
                b = depth1 - a * value1
                corresponding_value = (y - b) / a
            diff = abs(corresponding_value - x)
            if diff < shortest_distance and diff < maximum_distance:
                closest = corresponding_value
                shortest_distance = diff
        return closest
