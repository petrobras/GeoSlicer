import ctk
import qt
from ltrace.slicer import ui
from ltrace.slicer_utils import getResourcePath
from ltrace.pore_networks.simulation_parameters_node import PNM_PARAMETER_TYPE_ATTR


class LoadParamsLayout(qt.QHBoxLayout):
    def __init__(self, parameter_type, on_load_callback, parent=None):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(4)

        self.collapsible = ctk.ctkCollapsibleButton()
        self.collapsible.text = "Load parameters"
        self.collapsible.collapsed = True
        self.collapsible.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Preferred)

        self.parameterInputWidget = ui.hierarchyVolumeInput(
            nodeTypes=["vtkMRMLTextNode"],
            defaultText="Select node to load parameters from",
        )
        self.parameterInputWidget.objectName = "Parameter input"
        self.parameterInputWidget.addNodeAttributeIncludeFilter(PNM_PARAMETER_TYPE_ATTR, parameter_type)
        self.parameterInputWidget.showEmptyHierarchyItems = False

        loadButton = qt.QPushButton("Load parameters")
        loadButton.objectName = "Parameter input load button"
        loadButton.clicked.connect(on_load_callback)

        layout = qt.QFormLayout(self.collapsible)
        layout.addRow("Input parameter node:", self.parameterInputWidget)
        layout.addRow(loadButton)

        icon = qt.QLabel()
        try:
            icon.setPixmap(qt.QIcon(getResourcePath("Icons") / "png" / "Load.png").pixmap(qt.QSize(20, 20)))
        except Exception:
            pass
        icon.setContentsMargins(0, 4, 0, 0)

        self.addWidget(icon, 0, qt.Qt.AlignTop)
        self.addWidget(self.collapsible)


class SaveParamsLayout(qt.QHBoxLayout):
    def __init__(self, default_name, on_save_callback, parent=None):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(4)

        self.collapsible = ctk.ctkCollapsibleButton()
        self.collapsible.text = "Save parameters"
        self.collapsible.collapsed = True
        self.collapsible.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Preferred)

        self.lineEdit = qt.QLineEdit(default_name)
        saveButton = qt.QPushButton("Save parameters")
        saveButton.clicked.connect(on_save_callback)

        layout = qt.QFormLayout(self.collapsible)
        layout.addRow("Output parameter node name:", self.lineEdit)
        layout.addRow(saveButton)

        icon = qt.QLabel()
        try:
            icon.setPixmap(qt.QIcon(getResourcePath("Icons") / "png" / "Save.png").pixmap(qt.QSize(20, 20)))
        except Exception:
            pass
        icon.setContentsMargins(0, 4, 0, 0)

        self.addWidget(icon, 0, qt.Qt.AlignTop)
        self.addWidget(self.collapsible)
