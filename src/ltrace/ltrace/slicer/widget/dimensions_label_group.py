import slicer
import qt

from abc import abstractmethod
from ltrace.slicer import helpers

DEFAULT_DIMENSIONS_UNITS = {"px": True, "mm": False}


class DimensionsLabel(qt.QWidget):
    def __init__(self, unit: str, node: slicer.vtkMRMLNode = None, parent: qt.QWidget = None):
        super().__init__(parent)
        self.unit = unit
        self.nodeId = None
        self.dims = None
        self.__setupUi()

        if node:
            self.setNode(node)

        self.objectName = f"Dimensions Label ({unit})"

    def setNode(self, node: slicer.vtkMRMLNode) -> None:
        self.nodeId = node.GetID() if node is not None else None
        self._updateDimensions()
        self.__updateDimensionsLabel()

    def __setupUi(self):
        layout = qt.QFormLayout()
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(6)

        self.dimsLabel = qt.QLabel("")

        layout.addRow(f"Dimensions ({self.unit}):", self.dimsLabel)
        self.setLayout(layout)

    def __updateDimensionsLabel(self) -> None:
        dims = f"{self.dims[0]} x {self.dims[1]} x {self.dims[2]}" if self.dims is not None else ""
        self.dimsLabel.setText(dims)

    @abstractmethod
    def _updateDimensions(self) -> None:
        pass

    @property
    def text(self):
        return self.dimsLabel.text


class PixelDimensousLabel(DimensionsLabel):
    def __init__(self, node: slicer.vtkMRMLNode = None, parent: qt.QWidget = None):
        super().__init__(unit="px", node=node, parent=parent)

    def _updateDimensions(self) -> None:
        if self.nodeId is None:
            self.dims = None
            return

        node = helpers.tryGetNode(self.nodeId)
        if node is None or node.GetImageData() is None:
            self.dims = None
            return

        self.dims = node.GetImageData().GetDimensions()


class MillimeterDimensousLabel(DimensionsLabel):
    def __init__(self, node: slicer.vtkMRMLNode = None, parent: qt.QWidget = None, decimals=4):
        super().__init__(unit="mm", node=node, parent=parent)
        self._decimals = decimals

    def _updateDimensions(self) -> None:
        if self.nodeId is None:
            self.dims = None
            return

        node = helpers.tryGetNode(self.nodeId)
        if node is None or node.GetImageData() is None:
            self.dims = None
            return

        imageData = node.GetImageData()

        dims = imageData.GetDimensions()
        spacing = node.GetSpacing()

        dims = (dims[0] * spacing[0], dims[1] * spacing[1], dims[2] * spacing[2])
        self.dims = [round(dim, self._decimals) for dim in dims]


class DimensionsLabelGroup(qt.QWidget):
    def __init__(self, parent=None, units: dict = DEFAULT_DIMENSIONS_UNITS) -> None:
        super().__init__(parent)
        self.units = units
        self.labels = []
        self.__setupUi()

    @staticmethod
    def buildLabel(unit: str, node: slicer.vtkMRMLNode = None) -> DimensionsLabel:
        if unit == "px":
            return PixelDimensousLabel(node)
        elif unit == "mm":
            return MillimeterDimensousLabel(node)
        else:
            raise AttributeError("Invalid 'DimensionsLabel' unit.")

    def __setupUi(self):
        layout = qt.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(0)

        for unit, enable in self.units.items():
            if not enable:
                continue

            label = DimensionsLabelGroup.buildLabel(unit)
            layout.addWidget(label)
            self.labels.append(label)

        self.setLayout(layout)

    def setNode(self, node: slicer.vtkMRMLNode) -> None:
        [label.setNode(node) for label in self.labels]
