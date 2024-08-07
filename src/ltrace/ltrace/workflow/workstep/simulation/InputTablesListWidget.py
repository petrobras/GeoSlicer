import qt
import slicer

from MercurySimulationLib.MercurySimulationLogic import (
    MercurySimulationLogic,
    FixedRadiusLogic,
    LeverettNewLogic,
    LeverettOldLogic,
    PressureCurveLogic,
)
from MercurySimulationLib.SubscaleModelWidget import (
    SubscaleModelWidget,
    FixedRadiusWidget,
    LeverettNewWidget,
    LeverettOldWidget,
    PressureCurveWidget,
    ThroatRadiusCurveWidget,
)
from ltrace.slicer_utils import dataFrameToTableNode, dataframeFromTable
from ltrace.pore_networks.functions import geo2spy

import numpy as np
import pandas as pd

logic_models = {
    FixedRadiusWidget.STR: FixedRadiusLogic(),
    LeverettNewWidget.STR: LeverettNewLogic(),
    LeverettOldWidget.STR: LeverettOldLogic(),
    PressureCurveWidget.STR: PressureCurveLogic(),
    ThroatRadiusCurveWidget.STR: PressureCurveLogic(),
}


def set_subres_model_and_params(table_node, idx, params, pressure_tables):
    pore_network = geo2spy(table_node)
    x_size = float(table_node.GetAttribute("x_size"))
    y_size = float(table_node.GetAttribute("y_size"))
    z_size = float(table_node.GetAttribute("z_size"))
    volume = x_size * y_size * z_size

    subres_model = params["subres_model_name"]
    subres_params = params["subres_params"]

    if subres_model == "Pressure Curve" or subres_model == "Throat Radius Curve":
        subres_params = set_pressure_table_model(pressure_tables, subres_model, subres_params, idx)

    subresolution_function = logic_models[subres_model].get_capillary_pressure_function(
        subres_params, pore_network, volume
    )

    return subresolution_function


def set_pressure_table_model(pressure_tables, subres_model, subres_params, idx):
    pressure_table_len = len(pressure_tables)
    if pressure_table_len != 0:
        pressure_table_idx = pressure_table_len - 1 - idx
        if pressure_table_len - 1 - idx < 0:
            pressure_table_idx = 0
            print(
                "Using the last curve from the list, as the number of pressure curves is less than number of selected pore nodes."
            )
        pressure_curve_name, fvol_column, curve_column = pressure_tables[pressure_table_idx]
        pressure_curve_node = slicer.util.getNode(pressure_curve_name)
        df = dataframeFromTable(pressure_curve_node)
        df = df.replace("", np.nan)
        df = df.astype("float32")
        Curve = df[curve_column].to_numpy()
        Fvol = df[fvol_column].to_numpy()

        if subres_model == "Pressure Curve":
            subres_params = {"throat radii": None, "capillary pressure": Curve, "dsn": Fvol}
        elif subres_model == "Throat Radius Curve":
            subres_params = {"throat radii": Curve, "capillary pressure": None, "dsn": Fvol}
    else:
        print("The table of pressures is empty. Executing the simulation with the currently selected options.")
        subres_params = {i: np.asarray(subres_params[i]) for i in subres_params.keys()}

    return subres_params


class InputTablesListWidget(qt.QWidget):
    def __init__(self, subscale_widget):
        super().__init__()
        layout = qt.QFormLayout(self)

        self.subscale_widget = subscale_widget

        self.queueLabel = qt.QLabel(
            "Each pressure table listed below will be combined with a selected pore table\non the left, if they don't match your results may not be the expected."
        )
        layout.addWidget(self.queueLabel)

        hboxLayout = qt.QHBoxLayout()
        self.addButton = qt.QPushButton("Add to queue")
        hboxLayout.addWidget(self.addButton)
        self.removeButton = qt.QPushButton("Remove from queue")
        hboxLayout.addWidget(self.removeButton)
        layout.addRow("", hboxLayout)
        self.addButton.connect("clicked(bool)", self.add)
        self.removeButton.connect("clicked(bool)", self.remove)

        self.queue = qt.QTableWidget()
        self.queue.horizontalHeader().setMinimumSectionSize(200)
        self.queue.horizontalHeader().setStretchLastSection(qt.QHeaderView.Stretch)
        self.queue.horizontalHeader().hide()
        self.queue.verticalHeader().hide()
        layout.addWidget(self.queue)

        subscale_widget.microscale_model_dropdown.currentTextChanged.connect(self.onChangeModel)
        self.onChangeModel(subscale_widget.microscale_model_dropdown.currentText)

    def onChangeModel(self, text):
        self.curve_widget = self.subscale_widget.parameter_widgets[text]

        state = text == "Pressure Curve" or text == "Throat Radius Curve"
        self.setVisible(state)
        self.queue.setRowCount(0)

    def setItem(self, row, col, string):
        item = qt.QTableWidgetItem(string)
        item.setTextAlignment(qt.Qt.AlignCenter)
        item.setFlags(qt.Qt.ItemIsEnabled)
        self.queue.setItem(row, col, item)

    def add(self):
        row = self.queue.rowCount
        self.queue.insertRow(row)
        self.queue.setColumnCount(3)

        text = self.subscale_widget.microscale_model_dropdown.currentText
        if text == "Pressure Curve":
            node = self.curve_widget.pressureCurveSelector.currentNode()
        elif text == "Throat Radius Curve":
            node = self.curve_widget.throatRadiusSelector.currentNode()

        if node:
            self.setItem(row, 0, node.GetName())
            self.setItem(row, 1, self.curve_widget.cboxes["Volume Fraction Column"].currentText)
            if text == "Pressure Curve":
                self.setItem(row, 2, self.curve_widget.cboxes["Throat Pressure Column"].currentText)
            elif text == "Throat Radius Curve":
                self.setItem(row, 2, self.curve_widget.cboxes["Throat Radius Column"].currentText)

    def remove(self):
        row = self.queue.currentRow()
        self.queue.removeRow(row)

    def write_qtable_to_list(self, table):
        col_count = table.columnCount
        row_count = table.rowCount

        list1 = []
        for row in range(row_count):
            list2 = []
            for col in range(col_count):
                table_item = table.item(row, col)
                list2.append("" if table_item is None else str(table_item.text()))
            list1.append(list2)

        return list1
