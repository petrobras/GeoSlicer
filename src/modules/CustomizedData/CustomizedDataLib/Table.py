import qt
import slicer
import os

RESOURCES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Resources", "Icons")
CHARTS_ICON_PATH = os.path.join(RESOURCES_PATH, "Charts.png")


class TableWidget(qt.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup()

    def setup(self):
        contentsFrameLayout = qt.QFormLayout(self)
        contentsFrameLayout.setLabelAlignment(qt.Qt.AlignRight)
        contentsFrameLayout.setContentsMargins(0, 0, 0, 0)

        self.toolBar = qt.QToolBar()

        # Charts action
        icon = qt.QIcon(str(CHARTS_ICON_PATH))
        self.chartsShortcutAction = qt.QAction(icon, "Charts")
        self.chartsShortcutAction.setToolTip("Open Charts module with current table selected.")
        self.chartsShortcutAction.triggered.connect(self.__onChartsButtonClicked)
        self.toolBar.addAction(self.chartsShortcutAction)

        contentsFrameLayout.addRow(self.toolBar)
        self.tableView = slicer.qMRMLTableView()
        self.tableView.setEditTriggers(slicer.qMRMLTableView.NoEditTriggers)
        contentsFrameLayout.addRow(self.tableView)

    def setNode(self, node):
        self.tableView.setMRMLTableNode(node)

    def __onChartsButtonClicked(self):
        # Find the node related to the current item ID
        node = self.tableView.mrmlTableNode()
        if node is None:
            return

        module = "Charts"

        # Get module's widget
        widget = slicer.util.getModuleWidget(module)

        # Apply node selection in the module's widget
        widget.setSelectedNode(node)

        # Change module
        slicer.util.selectModule(module)
