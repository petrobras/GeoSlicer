import numpy as np
import qt
import slicer


class LabelsTableWidget(qt.QTableWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup()

    def setup(self):
        self.setColumnCount(2)
        self.setHorizontalHeaderLabels(["Color", "Name"])
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(qt.QHeaderView.Fixed)
        self.horizontalHeader().setFixedHeight(20)
        self.setAlternatingRowColors(True)
        self.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        self.setSelectionMode(qt.QAbstractItemView.SingleSelection)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(19)
        self.setColumnWidth(0, 30)

    def set_labelmap_node(self, labelmap_node):
        self.clearContents()
        if labelmap_node is None:
            return

        colors = self.get_label_colors(labelmap_node)
        self.set_colors(colors)

    def set_color_node(self, color_node):
        self.clearContents()
        colors = self.get_colors_from_color_node(color_node)
        self.set_colors(colors)

    def set_colors(self, colors):
        self.setRowCount(len(colors))
        for i, (color_name, color_value) in enumerate(colors):
            colorWidget = qt.QLabel()
            colorWidget.setFixedSize(16, 16)
            colorWidget.setStyleSheet("QLabel{background-color: rgb(%s, %s, %s)}" % color_value)
            self.setCellWidget(i, 0, colorWidget)
            self.setItem(i, 1, qt.QTableWidgetItem(color_name))

    @staticmethod
    def get_colors_from_color_node(color_node, index_range=None):
        start = 1
        end = color_node.GetNumberOfColors()
        if index_range is not None:
            range_start, range_end = index_range
            start = max(start, range_start)
            end = min(end, range_end)

        colors = []
        for i in range(int(start), int(end)):
            colorName = color_node.GetColorName(i)
            color = [0] * 4
            color_node.GetColor(i, color)
            color_value = tuple(int(ch * 255) for ch in color[:3])
            colors.append((colorName, color_value))

        return colors

    @staticmethod
    def get_label_colors(labelmapNode):
        displayNode = labelmapNode.GetDisplayNode()
        if displayNode is None:
            return []
        colorNode = displayNode.GetColorNode()
        if colorNode is None:
            return []
        imageData = labelmapNode.GetImageData()
        if imageData is None:
            return []

        scalarRange = imageData.GetScalarRange()
        colors = LabelsTableWidget.get_colors_from_color_node(
            colorNode, index_range=(scalarRange[0], scalarRange[1] + 1)
        )
        return colors
