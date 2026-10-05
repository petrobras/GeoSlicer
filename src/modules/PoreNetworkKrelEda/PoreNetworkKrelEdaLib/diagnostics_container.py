import qt
import shiboken2
import slicer

from ltrace.slicer import ui
from ltrace.slicer.nodes.directory_node import DirectoryNode
from ltrace.slicer.widget.layout import SlicerLayoutWindow
from ltrace.slicer.app.onboard_view import _svgIcon


class DiagnosticsContainerWidget(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        attribute_type, attribute_value = DirectoryNode.getNodeAttribute()
        self.diagnosticsSelector = ui.hierarchyVolumeInput(
            hasNone=True, nodeTypes=[DirectoryNode.getNodeType().__name__]
        )
        self.diagnosticsSelector.addNodeAttributeIncludeFilter(attribute_type, attribute_value)
        self.diagnosticsSelector.setToolTip("Select diagnostics node")
        self.diagnosticsSelector.clearSelection()
        self.diagnosticsSelector.objectName = "Diagnostics Selector"
        self.diagnosticsSelector.showEmptyHierarchyItems = False
        self.diagnosticsSelector.currentItemChanged.connect(self._onDiagnosticsSelectorChanged)

        self.closeButton = qt.QPushButton("Close")
        self.closeButton.setEnabled(False)
        self.closeButton.clicked.connect(lambda: self.diagnosticsSelector.setCurrentNode(None))

        self.mainLayout = qt.QFormLayout()
        self.mainLayout.addRow("Diagnostics:", self.diagnosticsSelector)
        self.mainLayout.addRow(self.closeButton)
        self.setLayout(self.mainLayout)

        self.slicerLayout = None
        slicer.app.layoutManager().layoutChanged.connect(self._onSlicerLayoutChanged)

    def _onDiagnosticsSelectorChanged(self):
        diagnosticsNode = self.diagnosticsSelector.currentNode()
        if diagnosticsNode is not None:
            dirNode = DirectoryNode(diagnosticsNode)
            self._setDiagnostics(str(dirNode.getDirPath()))
            self.closeButton.setEnabled(True)
        else:
            self._setDiagnostics(None)
            self.closeButton.setEnabled(False)

    def _onSlicerLayoutChanged(self, layout_id):
        if (
            self.slicerLayout is not None
            and self.slicerLayout.isEnabled()
            and layout_id != DiagnosticsSlicerLayout.LAYOUT_ID
        ):
            self.diagnosticsSelector.setCurrentNode(None)

    def _setDiagnostics(self, diagnostics_path: str):
        if diagnostics_path:
            if self.slicerLayout is None:
                self.slicerLayout = DiagnosticsSlicerLayout()
                self.slicerLayout.closeButtonClicked.connect(lambda: self.diagnosticsSelector.setCurrentNode(None))
            self.slicerLayout.enable(diagnostics_path)
        elif self.slicerLayout is not None:
            # the layout is only built on the first selection, so clearing the selector
            # before anything was selected must not fail
            self.slicerLayout.disable()


class DiagnosticsSlicerLayout(SlicerLayoutWindow):
    LAYOUT_ID = 16001

    closeButtonClicked = qt.Signal()

    def __init__(self):
        currentLayoutId = slicer.app.layoutManager().layout
        self.previousLayout = currentLayoutId if currentLayoutId != self.LAYOUT_ID else 0
        super().__init__(self.LAYOUT_ID)

        closeBtn = qt.QPushButton()
        closeBtn.objectName = "Diagnostics close Button"
        closeBtn.setIcon(_svgIcon("Close.svg"))
        closeBtn.setIconSize(qt.QSize(18, 18))
        closeBtn.setToolTip("Close diagnostics")
        closeBtnStyleSheet = """
            QPushButton {
                background: transparent;
            }
            """
        closeBtn.setStyleSheet(closeBtnStyleSheet)
        closeBtn.clicked.connect(self.__onCloseButtonClicked)

        self.slicerLayoutLayout = qt.QGridLayout()
        self.slicerLayoutLayout.setColumnStretch(0, 1)
        self.slicerLayoutLayout.setColumnStretch(1, 0)
        self.slicerLayoutLayout.setRowStretch(0, 0)
        self.slicerLayoutLayout.setRowStretch(1, 1)
        self.slicerLayoutLayout.addWidget(closeBtn, 0, 1, 1, 1)
        self.centralWidget.setLayout(self.slicerLayoutLayout)
        self.diagnosticsWidget = None

    def enable(self, diagnostics_path):
        self.__destroyDiagnosticsWidget()
        self.diagnosticsWidget = DiagnosticsView(diagnostics_path)
        self.slicerLayoutLayout.addWidget(self.diagnosticsWidget, 1, 0, 1, 2)

        currentLayoutId = slicer.app.layoutManager().layout
        if currentLayoutId != self.LAYOUT_ID:
            self.previousLayout = currentLayoutId

        slicer.app.layoutManager().setLayout(self.layoutId)

    def disable(self):
        self.__destroyDiagnosticsWidget()
        if slicer.app.layoutManager().layout == self.LAYOUT_ID:
            slicer.app.layoutManager().setLayout(self.previousLayout)

    def isEnabled(self):
        return self.diagnosticsWidget is not None

    def __destroyDiagnosticsWidget(self):
        if self.diagnosticsWidget is not None:
            self.diagnosticsWidget.deleteLater()
            self.diagnosticsWidget = None

    def __onCloseButtonClicked(self):
        self.closeButtonClicked.emit()
        self.disable()


class DiagnosticsView(qt.QWidget):
    def __init__(self, diagnostics_path):
        super().__init__()

        import py_pore_flow as ppf
        import PySide2

        frameLayout = qt.QVBoxLayout()
        frameLayout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(frameLayout)
        pysideFrame = shiboken2.wrapInstance(hash(self), PySide2.QtWidgets.QWidget)
        pysideFrameLayout = shiboken2.wrapInstance(hash(frameLayout), PySide2.QtWidgets.QVBoxLayout)

        self.diagnosticsWidget = ppf.DiagnosticsWidget(pysideFrame)
        self.diagnosticsWidget.set_diagnostics(diagnostics_path)
        pysideFrameLayout.addWidget(self.diagnosticsWidget)

    def deleteLater(self):
        self.diagnosticsWidget.setParent(None)
        self.diagnosticsWidget.deleteLater()
        self.diagnosticsWidget = None
        qt.QObject.deleteLater(self)
