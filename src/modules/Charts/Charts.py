import os
import traceback
import vtk, qt, ctk, slicer
import logging
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer_utils import *
from pathlib import Path

from Plots.Crossplot.CrossplotWidget import CrossplotWidget
from Plots.BarPlot.BarPlotBuilder import BarPlotBuilder
from Plots.Windrose.WindrosePlotBuilder import WindrosePlotBuilder
from Plots.Crossplot.CrossplotPlotBuilder import CrossplotBuilder
from Plots.HistogramInDepthPlot.HistogramInDepthPlotBuilder import HistogramInDepthPlotBuilder
from Plots.HistogramPlot.HistogramPlotBuilder import HistogramPlotBuilder
from ltrace.constants import DLISImportConst
import numpy as np
from ltrace.slicer.helpers import createTemporaryNode, removeTemporaryNodes
from ltrace.slicer_utils import dataframeFromTable, dataFrameToTableNode

try:
    from Test.CrossplotWidgetTest import CrossplotWidgetTest
except ImportError:
    CrossplotWidgetTest = None


INCOMPATIBLE_MESSAGE = (
    "The input table cannot be plotted because its format is not compatible with the chosen chart type."
)


def isVarDescriptor(node):
    return (
        node is not None
        and node.GetAttribute(NodeEnvironment.name())
        and node.GetColumnName(0) == "Properties"
        and node.GetColumnName(1) == "Values"
        and node.GetNumberOfColumns() == 2
    )


class Charts(LTracePlugin):
    """Charts Plugin. The name has 'ZZZ' prefix to avoid problem with the Slicer's plugins order initialization.
    The problem consists in the incompatibility between matplotlib and pyqtgraph python backend.
    """

    SETTING_KEY = "Charts"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Charts"
        self.parent.categories = ["Tools", "Charts", "MicroCT"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]  # replace with "Firstname Lastname (Organization)"
        self.parent.helpText = Charts.help()
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = ""

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ChartsWidget(LTracePluginWidget):
    CREATE_NEW_PLOT_LABEL = "Create new plot"
    RESOURCES_PATH = Path(__file__).absolute().with_name("Resources")
    WINDOWN_ICON = RESOURCES_PATH / "Icons" / "Charts.png"

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.__plotWidgetBuilders = [
            CrossplotBuilder(),
            WindrosePlotBuilder(),
            BarPlotBuilder(),
            HistogramInDepthPlotBuilder(),
            HistogramPlotBuilder(),
        ]
        self.__plotWidgets = dict()

    def setup(self):
        LTracePluginWidget.setup(self)
        collapsibleButton = ctk.ctkCollapsibleButton()
        collapsibleButton.text = "Charts"
        self.layout.addWidget(collapsibleButton)
        parametersFormLayout = qt.QFormLayout(collapsibleButton)

        # Table node list widget (Subject Hierarchy Tree View)
        self.nodeSelector = self._create_node_selector()
        parametersFormLayout.addRow(self.nodeSelector)
        self.current_items_ids = vtk.vtkIdList()

        # Plot type combo box
        self.plotTypeComboBox = qt.QComboBox()

        plot_type_labels = [plotWidgetBuilder.TYPE for plotWidgetBuilder in self.__plotWidgetBuilders]
        self.plotTypeComboBox.addItems(plot_type_labels)
        parametersFormLayout.addRow("Plot type: ", self.plotTypeComboBox)

        defaultPlotType = CrossplotWidget.TYPE
        self.plotTypeComboBox.setCurrentText(defaultPlotType)

        # Plot widgets combo box
        self.plotWidgetsComboBox = qt.QComboBox()
        self.__populatePlotWidgetsComboBox()
        parametersFormLayout.addRow("Plot to: ", self.plotWidgetsComboBox)

        # Add Stacked widget to add the selected plot configuration widgets
        self.plotConfigurationWidget = qt.QStackedWidget()
        for plotWidgetBuilder in self.__plotWidgetBuilders:
            widget = plotWidgetBuilder.configurationWidget()
            self.plotConfigurationWidget.addWidget(widget)

        self.__updateConfigurationWidget(defaultPlotType)
        parametersFormLayout.addRow(self.plotConfigurationWidget)

        # Plot Button
        self.plotButton = qt.QPushButton("Plot")
        self.plotButton.toolTip = "Plot selected data"
        self.plotButton.enabled = True
        parametersFormLayout.addRow(self.plotButton)

        # connections
        self.plotButton.clicked.connect(self.onPlotButtonClicked)
        self.plotTypeComboBox.currentTextChanged.connect(self.__onPlotTypeComboBoxChanged)

        # Add vertical spacer
        self.layout.addStretch(1)

    def enter(self) -> None:
        super().enter()

    def exit(self):
        removeTemporaryNodes()

    def _create_node_selector(self):
        """Handles node selector widget creation.

        Returns:
            qMRMLSubjectHierarchyTreeView: the node selector widget object.
        """
        subjectHierarchyTreeView = slicer.qMRMLSubjectHierarchyTreeView()
        subjectHierarchyTreeView.setMRMLScene(slicer.app.mrmlScene())
        subjectHierarchyTreeView.hideColumn(2)
        subjectHierarchyTreeView.hideColumn(3)
        subjectHierarchyTreeView.hideColumn(4)
        subjectHierarchyTreeView.hideColumn(5)
        subjectHierarchyTreeView.setEditMenuActionVisible(False)
        subjectHierarchyTreeView.setMultiSelection(True)
        subjectHierarchyTreeView.setContextMenuEnabled(False)
        subjectHierarchyTreeView.nodeTypes = [slicer.vtkMRMLTableNode.__name__]
        subjectHierarchyTreeView.setToolTip("Pick the table to be used at the desired plot")
        subjectHierarchyTreeView.connect("currentItemChanged(vtkIdType)", self._on_node_selector_item_changed)

        return subjectHierarchyTreeView

    def __showNewPlotWidgetDialog(self):
        """Show dialog to define new plot name

        Returns:
            bool: True if the input name was correctly inserted. Otherwise, returns False.
            str: The plot label.
        """
        dialog = qt.QDialog(self.parent)
        dialog.setWindowFlags(dialog.windowFlags() & ~qt.Qt.WindowContextHelpButtonHint)
        dialog.setWindowTitle("New plot")
        dialog.setWindowIcon(qt.QIcon(str(self.WINDOWN_ICON)))

        # Question Layout
        formLayout = qt.QFormLayout()
        newPlotWidgetLineEdit = qt.QLineEdit()
        formLayout.addRow("Plot name", newPlotWidgetLineEdit)

        okButton = qt.QPushButton("OK")
        cancelButton = qt.QPushButton("Cancel")

        # Connections
        def showPopup(message):
            qt.QMessageBox.warning(dialog, "Error", message)

        def okButtonClicked():
            newPlotLabel = newPlotWidgetLineEdit.text
            if newPlotLabel == "":
                showPopup("Plot name cannot be empty")
                return

            if self.__plotWidgets.get(newPlotLabel) is not None:
                showPopup("Plot name {} already exists".format(newPlotLabel))
                return

            dialog.accept()

        okButton.clicked.connect(lambda checked: okButtonClicked())
        cancelButton.clicked.connect(lambda checked: dialog.reject())

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.addWidget(okButton)
        buttonsLayout.addSpacing(10)
        buttonsLayout.addWidget(cancelButton)
        formLayout.addRow(buttonsLayout)
        formLayout.setVerticalSpacing(10)

        dialog.setLayout(formLayout)

        status = dialog.exec()

        # Check result
        newPlotLabel = newPlotWidgetLineEdit.text
        if bool(status) is True and newPlotLabel != "":
            return True, newPlotLabel

        return False, ""

    def __populatePlotWidgetsComboBox(self):
        """Handles plot widgets combo box population"""
        self.plotWidgetsComboBox.clear()
        self.plotWidgetsComboBox.addItem(self.CREATE_NEW_PLOT_LABEL)

        for plotLabel, plotWidget in self.__plotWidgets.items():
            if plotWidget is None or plotWidget.TYPE != self.plotTypeComboBox.currentText:
                continue

            self.plotWidgetsComboBox.addItem(plotLabel)

    def __handle_plot_type_creation(self, plotType, plotLabel):
        """Handle plot widget creation

        Args:
            plotType (str): the plot type string
            plotLabel (str): the plot label
        """
        for plotWidgetBuilder in self.__plotWidgetBuilders:
            if plotType == plotWidgetBuilder.TYPE:
                plotWidget = plotWidgetBuilder.build(plotLabel=plotLabel, parent=None)

                try:
                    plotWidget.show()
                except (RuntimeError, Exception) as error:
                    logging.warning(error)
                    slicer.util.errorDisplay(
                        text=INCOMPATIBLE_MESSAGE, parent=slicer.modules.AppContextInstance.mainWindow
                    )
                    plotWidget.deleteLater()
                    plotWidget = None
                else:
                    plotWidget.finished.connect(lambda: self.__handle_plot_widget_closed(plotLabel))

                return plotWidget

    def __handle_plot_widget_closed(self, plotLabel):
        """Handles a Plot Widget closed event

        Args:
            plotLabel (str): the plot label
        """
        if plotLabel not in self.__plotWidgets:
            return

        del self.__plotWidgets[plotLabel]
        self.__populatePlotWidgetsComboBox()

    def _get_selected_nodes(self):
        """Wrapper to get the vtkMRMLNode object from the item selected on node selector widget.

        Returns:
            List[vtkMRMLNode]: the node's object.
        """
        current_items_ids = vtk.vtkIdList()
        self.nodeSelector.currentItems(current_items_ids)
        subject_hierarchy = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        nodes = []
        for i in range(current_items_ids.GetNumberOfIds()):
            node = subject_hierarchy.GetItemDataNode(current_items_ids.GetId(i))
            if node is None:
                continue

            browser_node = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(node)
            if browser_node:
                sequence_node = browser_node.GetSequenceNode(node)
                for item in range(sequence_node.GetNumberOfDataNodes()):
                    nodes.append(sequence_node.GetNthDataNode(item))
            else:
                nodes.append(node)

        return nodes

    def onPlotButtonClicked(self):
        """Handle the click event at the plot button."""
        currentNodes = self._get_selected_nodes()

        nodes = ChartsWidget.getNodesMergedByWell(currentNodes)

        self.plot(nodes)

    def plot(self, nodes):
        failures = [node.GetName() for node in nodes if isVarDescriptor(node)]

        if failures:
            message = (
                "The nodes below cannot be plotted because its format is not compatible with the chosen chart type.\n"
            )
            message += "\n".join([f" - {name}" for name in failures])
            slicer.util.errorDisplay(text=message, parent=slicer.modules.AppContextInstance.mainWindow)
            return

        selectedPlotWidgetLabel = self.plotWidgetsComboBox.currentText

        if selectedPlotWidgetLabel == self.CREATE_NEW_PLOT_LABEL:
            status, selectedPlotWidgetLabel = self.__showNewPlotWidgetDialog()
            if status is False:
                return

            self.__plotWidgets[selectedPlotWidgetLabel] = None

        selectedPlotType = self.plotTypeComboBox.currentText

        selectPlotWidget = self.__plotWidgets.get(selectedPlotWidgetLabel)
        if selectPlotWidget is None:
            selectPlotWidget = self.__handle_plot_type_creation(selectedPlotType, selectedPlotWidgetLabel)
            if selectPlotWidget is None:
                return

        for currentNode in nodes:
            try:
                selectPlotWidget.appendData(currentNode)
            except (ValueError, RuntimeError) as error:
                if self.__plotWidgets.get(selectedPlotWidgetLabel) is None and selectPlotWidget is not None:
                    selectPlotWidget.deleteLater()
                logging.warning(error)
                slicer.util.errorDisplay(text=error, parent=slicer.modules.AppContextInstance.mainWindow)
            except Exception as error:
                if self.__plotWidgets.get(selectedPlotWidgetLabel) is None and selectPlotWidget is not None:
                    selectPlotWidget.deleteLater()
                logging.warning(error)
                slicer.util.errorDisplay(text=INCOMPATIBLE_MESSAGE, parent=slicer.modules.AppContextInstance.mainWindow)
            else:
                self.__plotWidgets[selectedPlotWidgetLabel] = selectPlotWidget
                self.__populatePlotWidgetsComboBox()
                self.plotWidgetsComboBox.setCurrentText(selectedPlotWidgetLabel)

    def __onPlotTypeComboBoxChanged(self, text):
        self.__populatePlotWidgetsComboBox()
        self.__updateConfigurationWidget(text)

    def __updateConfigurationWidget(self, plotTypeLabel):
        for plotWidgetBuilder in self.__plotWidgetBuilders:
            if plotWidgetBuilder.TYPE != plotTypeLabel:
                continue

            widget = plotWidgetBuilder.configurationWidget()
            self.plotConfigurationWidget.setCurrentWidget(widget)
            break

    def wrapWidget(self):
        from PySide2.QtWidgets import QWidget
        import PythonQt
        import shiboken2

        self.pyqtwidget = PythonQt.Qt.QWidget(slicer.modules.AppContextInstance.mainWindow)
        self.pysidewidget = shiboken2.wrapInstance(hash(self.pyqtwidget), QWidget)
        return self.pysidewidget

    def setSelectedNode(self, node):
        if node is None:
            return False

        subject_hierarchy = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        item_id = subject_hierarchy.GetItemByDataNode(node)
        self.nodeSelector.setCurrentItem(item_id)

        return True

    def _on_node_selector_item_changed(self, item_id):
        pass

    def getNodesMergedByWell(nodes):
        outNodes = []
        wellsIndexesNodes = []  # tables from wells need to be merged into a multi-colun table per well
        wells = []
        for node in nodes:
            wellName = node.GetAttribute(DLISImportConst.WELL_NAME_TAG)
            wellsIndexesNodes.append(
                {
                    "WellName": wellName,
                    "node": node,
                }
            )
            if wellName is None or wellName == "":
                outNodes.append(node)
            elif wellName not in wells:
                wells.append(wellName)

        #
        #  If there are tables originated from wells, we merge them into a multi-column table per well

        nodesToMerge = []
        for w in wells:
            if w is not None:
                nodesToMerge.append([d["node"] for d in wellsIndexesNodes if d["WellName"] == w])

        mergedTableNode = None
        if len(nodesToMerge) > 0:
            for w in range(len(nodesToMerge)):
                df = dataframeFromTable(
                    nodesToMerge[w][0]
                )  # table node to which the other ones of the same well will be appended
                for i, node in enumerate(nodesToMerge[w][1:], start=1):
                    dfToAdd = dataframeFromTable(node)
                    columnToAdd = dfToAdd.values[0:, 1]
                    df.insert(df.values.shape[1], dfToAdd.columns[1], columnToAdd)

                mergedTableNode = createTemporaryNode(slicer.vtkMRMLTableNode, wells[w])
                dataFrameToTableNode(df, mergedTableNode)
                outNodes.append(mergedTableNode)

        return outNodes


class ChartsLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
