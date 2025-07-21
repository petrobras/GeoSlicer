import colorsys
import datetime
import os
import random
from pathlib import Path

import PySide2 as pyside
import ctk
import numpy as np
import pandas as pd
import qt
import shiboken2
import slicer
import vtk
from scipy.ndimage import zoom
from scipy.spatial import distance

from ltrace.pore_networks.visualization_model import PORE_TYPE, TUBE_TYPE
from ltrace.slicer.graph_data import DataFrameGraphData
from ltrace.slicer.helpers import highlight_error, reset_style_on_valid_text
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer.widget.data_plot_widget import DataPlotWidget
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.transforms import transformPoints

NUMBER_OF_VIEWS = 2


# Checks if closed source code is available
try:
    from Test.PoreNetworkCompareTest import PoreNetworkCompareTest
except ImportError:
    PoreNetworkCompareTest = None  # tests not deployed to final version or closed source


class PoreNetworkCompare(LTracePlugin):
    SETTING_KEY = "PoreNetworkCompare"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "PNM Compare Models"
        self.parent.categories = ["MicroCT"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = PoreNetworkCompare.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PoreNetworkCompareWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        slicer.app.layoutManager().layoutChanged.connect(self.onLayoutChange)

    def cleanup(self):
        super().cleanup()
        slicer.app.layoutManager().layoutChanged.disconnect(self.onLayoutChange)

    def onLayoutChange(self, layout):
        if self.visualizationWidget:
            self.visualizationWidget.setVisible(False)

    def setup(self):
        LTracePluginWidget.setup(self)

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        formLayout = qt.QFormLayout(frame)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        # Input section
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Input")
        formLayout.addRow(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.inputPoreLabelMap = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLLabelMapVolumeNode"], onChange=self.onInputPoreLabelMapChanged
        )
        self.inputPoreLabelMap.setObjectName("inputPoreLabelMap")
        self.inputPoreLabelMap.setToolTip("Select the input pore segmentation labelmap.")
        inputFormLayout.addRow("Pore labelmap:", self.inputPoreLabelMap)
        self.inputPoreLabelMap.resetStyleOnValidNode()

        self.inputWatershedPoreLabelMap = hierarchyVolumeInput(nodeTypes=["vtkMRMLLabelMapVolumeNode"])
        self.inputWatershedPoreLabelMap.setObjectName("inputWatershedPoreLabelMap")
        self.inputWatershedPoreLabelMap.setToolTip("Select the input watershed pore segmentation labelmap.")
        inputFormLayout.addRow("Watershed pore labelmap:", self.inputWatershedPoreLabelMap)
        self.inputWatershedPoreLabelMap.resetStyleOnValidNode()

        self.inputPoreTable = hierarchyVolumeInput(nodeTypes=["vtkMRMLTableNode"])
        self.inputPoreTable.setObjectName("inputPoreTable")
        self.inputPoreTable.setToolTip("Select the input pore table.")
        inputFormLayout.addRow("Pore table:", self.inputPoreTable)
        self.inputPoreTable.resetStyleOnValidNode()

        self.inputCycleNodeModel = hierarchyVolumeInput(nodeTypes=["vtkMRMLModelNode"])
        self.inputCycleNodeModel.setObjectName("inputCycleNodeModel")
        self.inputCycleNodeModel.setToolTip("Select the input cycle model.")
        inputFormLayout.addRow("Cycle model:", self.inputCycleNodeModel)
        self.inputCycleNodeModel.resetStyleOnValidNode()

        self.inputDrainageOilLabelmapsFolder = hierarchyVolumeInput(nodeTypes=["Directories"], allowFolders=True)
        self.inputDrainageOilLabelmapsFolder.setObjectName("inputDrainageOilLabelmapsFolder")
        self.inputDrainageOilLabelmapsFolder.setToolTip(
            "Select the input drainage oil labelmaps folder. This folder should contain a time series of labelmaps."
        )
        inputFormLayout.addRow("Drainage oil labelmaps folder:", self.inputDrainageOilLabelmapsFolder)
        self.inputDrainageOilLabelmapsFolder.resetStyleOnValidNode()

        self.inputImbibitionOilLabelmapsFolder = hierarchyVolumeInput(nodeTypes=["Directories"], allowFolders=True)
        self.inputImbibitionOilLabelmapsFolder.setObjectName("inputImbibitionOilLabelmapsFolder")
        self.inputImbibitionOilLabelmapsFolder.setToolTip(
            "Select the input imbibition oil labelmaps folder. This folder should contain a time series of labelmaps."
        )
        inputFormLayout.addRow("Imbibition oil labelmaps folder:", self.inputImbibitionOilLabelmapsFolder)
        self.inputImbibitionOilLabelmapsFolder.resetStyleOnValidNode()
        inputFormLayout.addRow(" ", None)

        # Parameters section
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.setText("Parameters")
        formLayout.addRow(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.downsamplingFactorSpinBox = qt.QDoubleSpinBox()
        self.downsamplingFactorSpinBox.setObjectName("downsamplingFactorSpinBox")
        self.downsamplingFactorSpinBox.setRange(0.01, 1)
        self.downsamplingFactorSpinBox.setDecimals(2)
        self.downsamplingFactorSpinBox.setSingleStep(0.1)
        self.downsamplingFactorSpinBox.setValue(0.3)
        self.downsamplingFactorSpinBox.setToolTip(
            "The downsampling factor used to generate the vector volumes containing the saturation data. "
            "Decrease this value if you are running out of RAM memory during the process."
        )
        parametersFormLayout.addRow("Downsampling factor:", self.downsamplingFactorSpinBox)

        self.numNearestNeighborsSpinBox = qt.QSpinBox()
        self.numNearestNeighborsSpinBox.setObjectName("numNearestNeighborsSpinBox")
        self.numNearestNeighborsSpinBox.setRange(0, 10)
        self.numNearestNeighborsSpinBox.setValue(0)
        self.numNearestNeighborsSpinBox.setToolTip(
            "The number of nearest neighbors used to smooth the simulation model saturations."
        )
        parametersFormLayout.addRow("Nearest neighbors smoothing:", self.numNearestNeighborsSpinBox)

        parametersFormLayout.addRow(" ", None)

        # Output section
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.outputFolderNameLineEdit = qt.QLineEdit()
        self.outputFolderNameLineEdit.setObjectName("outputFolderNameLineEdit")
        outputFormLayout.addRow("Output folder name:", self.outputFolderNameLineEdit)
        reset_style_on_valid_text(self.outputFolderNameLineEdit)
        outputFormLayout.addRow(" ", None)

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setObjectName("applyButton")
        self.applyButton.setFixedHeight(40)
        self.applyButton.clicked.connect(self.onApplyButtonClicked)

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.setObjectName("cancelButton")
        self.cancelButton.setFixedHeight(40)
        self.cancelButton.setEnabled(False)
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)

        buttonsHBoxLayout = qt.QHBoxLayout()
        buttonsHBoxLayout.addWidget(self.applyButton)
        buttonsHBoxLayout.addWidget(self.cancelButton)
        formLayout.addRow(buttonsHBoxLayout)
        formLayout.addRow(" ", None)

        # Visualization section
        visualizationCollapsibleButton = ctk.ctkCollapsibleButton()
        visualizationCollapsibleButton.setText("Visualization")
        formLayout.addRow(visualizationCollapsibleButton)
        visualizationFormLayout = qt.QFormLayout(visualizationCollapsibleButton)
        visualizationFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.resultsFolder = hierarchyVolumeInput(nodeTypes=["Directories"], allowFolders=True)
        self.resultsFolder.setObjectName("resultsFolder")
        self.resultsFolder.setToolTip("Select the Pore Network Compare results folder.")
        visualizationFormLayout.addRow("Results folder:", self.resultsFolder)
        self.resultsFolder.resetStyleOnValidNode()

        self.compareButton = qt.QPushButton("Compare")
        self.compareButton.setObjectName("compareButton")
        self.compareButton.setFixedHeight(40)
        self.compareButton.clicked.connect(self.onCompareButtonClicked)
        visualizationFormLayout.addRow(None, self.compareButton)
        visualizationFormLayout.addRow(" ", None)

        self.visualizationWidget = self.createVisualizationWidget()
        visualizationFormLayout.addRow(self.visualizationWidget)
        self.visualizationWidget.setVisible(False)

        self.statusLabel = qt.QLabel()
        self.statusLabel.setAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)
        self.statusLabel.hide()
        formLayout.addRow(self.statusLabel)

        self.progressBar = qt.QProgressBar()
        self.progressBar.setValue(0)
        self.progressBar.hide()
        formLayout.addRow(self.progressBar)

        self.logic = PoreNetworkCompareLogic(self.statusLabel, self.progressBar)

        self.layout.addStretch(1)

    def createVisualizationWidget(self):
        frame = qt.QFrame()
        formLayout = qt.QFormLayout(frame)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        self.stepSlider = slicer.qMRMLSliderWidget()
        self.stepSlider.setObjectName("stepSlider")
        self.stepSlider.setDecimals(0)
        self.stepSlider.valueChanged.connect(self.onStepSliderValueChanged)
        formLayout.addRow("Step:", self.stepSlider)

        dataLayout = qt.QHBoxLayout()
        dataLayout.setContentsMargins(0, 0, 0, 0)
        self.saturationDataPlotWidget = DataPlotWidget()
        self.saturationDataPlotWidget.widget.setFixedHeight(300)
        self.saturationDataPlotWidget.set_theme("Light")
        self.meanSaturationDataPlotWidget = DataPlotWidget()
        self.meanSaturationDataPlotWidget.widget.setFixedHeight(300)
        self.meanSaturationDataPlotWidget.set_theme("Light")
        pySideMainLayout = shiboken2.wrapInstance(hash(dataLayout), pyside.QtWidgets.QHBoxLayout)
        pySideMainLayout.addWidget(self.saturationDataPlotWidget.widget)
        pySideMainLayout.addWidget(self.meanSaturationDataPlotWidget.widget)
        formLayout.addRow(dataLayout)

        return frame

    def onInputPoreLabelMapChanged(self, itemId):
        inputPoreLabelMap = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(itemId)
        if inputPoreLabelMap:
            outputFolderName = inputPoreLabelMap.GetName() + "_Pore_Network_Compare"
        else:
            outputFolderName = ""
        self.outputFolderNameLineEdit.setText(outputFolderName)

    def onStepSliderValueChanged(self, step):
        step = int(step)
        self.logic.changeStep(int(step))

        dataItems = self.saturationDataPlotWidget.plotItem.listDataItems()
        for dataItem in dataItems:
            dataItem.setVisible(False)
        dataItems[step].setVisible(True)

        dataItems = self.meanSaturationDataPlotWidget.plotItem.listDataItems()
        for dataItem in dataItems:
            dataItem.setVisible(False)
        dataItems[step].setVisible(True)

    def onCompareButtonClicked(self):
        try:
            error = False

            results_folder = self.resultsFolder.currentItem()

            models = get_sorted_nodes_from_folder(results_folder, node_type=slicer.vtkMRMLModelNode)
            if len(models) == 0:
                highlight_error(self.resultsFolder)
                error = True

            nodes = get_sorted_nodes_from_folder(results_folder, node_type=slicer.vtkMRMLVectorVolumeNode)
            if len(nodes) == 0:
                highlight_error(self.resultsFolder)
                error = True

            if error:
                return

            self.logic.compare(models, nodes)
            self.populateGraphicsWidget()
            self.stepSlider.maximum = len(self.logic.saturationScalarNames) - 1
            slicer.app.processEvents()
            self.stepSlider.value = 0
            self.onStepSliderValueChanged(0)
            slicer.util.resetSliceViews()
            self.visualizationWidget.setVisible(True)
        except CompareInfo as e:
            slicer.util.infoDisplay(str(e))

    def populateGraphicsWidget(self):
        self.saturationDataPlotWidget.clear_plot()
        saturationDataFrames = self.logic.saturationDataFrames
        columnNames = ["sw (Model 1)", "sw (Model 2)", "zPosition"]
        for df in saturationDataFrames:
            self.saturationDataPlotWidget.add3dPlot(
                DataFrameGraphData(None, df),
                df[columnNames[0]],
                df[columnNames[1]],
                df[columnNames[2]],
                columnNames[0],
                columnNames[1],
                columnNames[2],
                np.min(df[columnNames[2]]),
                np.max(df[columnNames[2]]),
            )
        self.saturationDataPlotWidget.update_legend_item(columnNames[2])
        self.saturationDataPlotWidget._updatePlotsLayout(True, True, columnNames[2])
        self.saturationDataPlotWidget.plotItem.setXRange(0, 1)
        dataItems = self.saturationDataPlotWidget.plotItem.listDataItems()
        for dataItem in dataItems:
            dataItem.setVisible(False)

        self.meanSaturationDataPlotWidget.clear_plot()
        meanSaturationDataFrames = self.logic.meanSaturationDataFrames
        columnNames = ["mean swi", "zPosition", "model"]
        for df in meanSaturationDataFrames:
            self.meanSaturationDataPlotWidget.add3dPlot(
                DataFrameGraphData(None, df),
                df[columnNames[0]],
                df[columnNames[1]],
                df[columnNames[2]],
                columnNames[0],
                columnNames[1],
                columnNames[2],
                np.min(df[columnNames[2]]),
                np.max(df[columnNames[2]]),
            )
        self.meanSaturationDataPlotWidget.update_legend_item(columnNames[2])
        self.meanSaturationDataPlotWidget._updatePlotsLayout(True, True, columnNames[2])
        self.meanSaturationDataPlotWidget.plotItem.setXRange(0, 1)
        dataItems = self.meanSaturationDataPlotWidget.plotItem.listDataItems()
        for dataItem in dataItems:
            dataItem.setVisible(False)

    def onApplyButtonClicked(self):
        try:
            error = False

            if self.inputPoreTable.currentNode() is None:
                highlight_error(self.inputPoreTable)
                error = True

            if self.inputPoreLabelMap.currentNode() is None:
                highlight_error(self.inputPoreLabelMap)
                error = True

            if self.inputWatershedPoreLabelMap.currentNode() is None:
                highlight_error(self.inputWatershedPoreLabelMap)
                error = True

            if self.inputCycleNodeModel.currentNode() is None:
                highlight_error(self.inputCycleNodeModel)
                error = True

            drainageOilLabelMaps = get_sorted_nodes_from_folder(
                self.inputDrainageOilLabelmapsFolder.currentItem(), node_type=slicer.vtkMRMLLabelMapVolumeNode
            )
            if len(drainageOilLabelMaps) == 0:
                highlight_error(self.inputDrainageOilLabelmapsFolder)
                error = True

            imbibitionOilLabelMaps = get_sorted_nodes_from_folder(
                self.inputImbibitionOilLabelmapsFolder.currentItem(), node_type=slicer.vtkMRMLLabelMapVolumeNode
            )
            if len(imbibitionOilLabelMaps) == 0:
                highlight_error(self.inputImbibitionOilLabelmapsFolder)
                error = True

            if self.outputFolderNameLineEdit.text.strip() == "":
                highlight_error(self.outputFolderNameLineEdit)
                error = True

            if error:
                return

            self.applyButton.setEnabled(False)
            self.cancelButton.setEnabled(True)
            self.statusLabel.setText("Status: Running")
            self.statusLabel.show()
            self.progressBar.setValue(0)
            self.progressBar.show()
            slicer.app.processEvents()

            if self.logic.apply(
                poreTable=self.inputPoreTable.currentNode(),
                poreLabelMap=self.inputPoreLabelMap.currentNode(),
                watershedPoreLabelMap=self.inputWatershedPoreLabelMap.currentNode(),
                cycleNodeModel=self.inputCycleNodeModel.currentNode(),
                drainageOilLabelmaps=drainageOilLabelMaps,
                imbibitionOilLabelmaps=imbibitionOilLabelMaps,
                downsamplingFactor=self.downsamplingFactorSpinBox.value,
                outputFolderName=self.outputFolderNameLineEdit.text,
                numNearestNeighbors=self.numNearestNeighborsSpinBox.value,
            ):
                self.statusLabel.setText("Status: Completed")
        except ApplyInfo as e:
            self.statusLabel.setText("Status: Not completed")
            slicer.util.infoDisplay(str(e))
        except RuntimeError as e:
            self.statusLabel.setText("Status: Not completed")
            slicer.util.infoDisplay("An unexpected error has occurred: " + str(e))
        finally:
            self.applyButton.setEnabled(True)
            self.cancelButton.setEnabled(False)
            self.progressBar.setValue(100)

    def onCancelButtonClicked(self):
        self.statusLabel.setText("Status: Canceled")
        self.progressBar.hide()
        self.logic.cancel()

        self.applyButton.setEnabled(True)
        self.cancelButton.setEnabled(False)


class PoreNetworkCompareLogic(LTracePluginLogic):
    REFRESH_DELAY = 50  # ms

    def __init__(self, statusLabel, progressBar):
        LTracePluginLogic.__init__(self)
        self.statusLabel = statusLabel
        self.progressBar = progressBar
        self.processStartTime = None
        self.cancelProcess = False
        self.models = []
        self.threeDWidgets = []
        self.sliceWidgets = []
        self.saturationScalarNames = []
        self.saturationDataFrames = []
        self.meanSaturationDataFrames = []
        self.previousLayout = None
        self.poreSaturations = {}
        self.modelPositionToPointIJK = {}
        self.newSaturationIndex = None

    def compare(self, models, nodes):
        self.comparing = True
        self.models = models
        self.nodes = nodes

        self.saturationScalarNames = get_scalar_names_from_model_node(self.models[0], "saturation")
        for model in self.models[1:]:
            saturationScalarNames = get_scalar_names_from_model_node(model, "saturation")
            if saturationScalarNames != self.saturationScalarNames:
                raise CompareInfo("All models must have the same saturation steps.")

        if len(self.nodes) != len(self.saturationScalarNames):
            raise CompareInfo("The number of nodes must be equal to the number of saturation steps from the models.")

        self.viewsCompare()
        self.saturationDataFrames, self.meanSaturationDataFrames = self.getGraphicsDataFrames()

    def changeStep(self, step):
        for model in self.models:
            model.GetDisplayNode().SetActiveScalarName(self.saturationScalarNames[step])

        node = self.nodes[step]
        for slicerWidget in self.sliceWidgets:
            sliceCompositeNode = slicerWidget.sliceLogic().GetSliceCompositeNode()
            sliceCompositeNode.SetBackgroundVolumeID(node.GetID())

    ###########################################################################
    # Graphics compare
    ###########################################################################

    def getGraphicsDataFrames(self):
        saturationDataFrames = []
        meanSaturationDataFrames = []
        for saturationScalarName in self.saturationScalarNames:
            saturationDataFrame = pd.DataFrame()
            for i, model in enumerate(self.models):
                modelIds = slicer.util.arrayFromModelPointData(model, "id")
                modelTypes = slicer.util.arrayFromModelPointData(model, "type")
                uniquePoreModelIds = np.unique(modelIds[modelTypes == PORE_TYPE])
                modelSaturation = slicer.util.arrayFromModelPointData(model, saturationScalarName)
                modelPosition = slicer.util.arrayFromModelPointData(model, "position")
                poresSaturations = []
                poreZPositions = []
                for modelId in uniquePoreModelIds:
                    poresSaturations.append(modelSaturation[modelIds == modelId][0])
                    poreZPositions.append(modelPosition[modelIds == modelId][0, 2])
                saturationDataFrame[f"sw (Model {i + 1})"] = poresSaturations
            saturationDataFrame["zPosition"] = poreZPositions
            saturationDataFrames.append(saturationDataFrame)
            meanSaturationDataFrames.append(self.getMeanSaturationDataFrame(saturationDataFrame))
        return saturationDataFrames, meanSaturationDataFrames

    def getMeanSaturationDataFrame(self, saturationDataFrame):
        df = saturationDataFrame
        num_segments = 10

        # Calculate the range of column3 values
        column3_min = df["zPosition"].min()
        column3_max = df["zPosition"].max()

        # Calculate the segment size
        segment_size = (column3_max - column3_min) / num_segments

        # Calculate mid value for each segment
        mid_values = [column3_min + (i + 0.5) * segment_size for i in range(num_segments)]

        # Create a DataFrame from the mid-values
        segment_df = pd.DataFrame({"Segment Mid Value": mid_values})

        # Calculate mean column1 and column2 values for each segment
        mean_column1_values = []
        mean_column2_values = []

        for mid_value in mid_values:
            segment_start = mid_value - 0.5 * segment_size
            segment_end = mid_value + 0.5 * segment_size

            column1_values_in_segment = df[(df["zPosition"] >= segment_start) & (df["zPosition"] <= segment_end)][
                "sw (Model 1)"
            ]
            mean_column1_values.append(column1_values_in_segment.mean())

            column2_values_in_segment = df[(df["zPosition"] >= segment_start) & (df["zPosition"] <= segment_end)][
                "sw (Model 2)"
            ]
            mean_column2_values.append(column2_values_in_segment.mean())

        # Add the calculated mean column1 and column2 values as new columns
        segment_df["mean sw (Model 1)"] = mean_column1_values
        segment_df["mean sw (Model 2)"] = mean_column2_values

        # Removing the first and last points, since they are not representative
        segment_df = segment_df.iloc[1:-1]

        # Print the new DataFrame
        source = [1] * len(segment_df) + [2] * len(segment_df)

        # Combine 'Mean Column1' and 'Mean Column2' values into a single column
        merged_values = segment_df["mean sw (Model 1)"].tolist() + segment_df["mean sw (Model 2)"].tolist()

        # Combine 'Segment Mid Value' values into a single list
        segment_mid_values = segment_df["Segment Mid Value"].tolist() * 2

        # Create a new DataFrame with the merged values, 'Segment Mid-Value', and source column
        merged_df = pd.DataFrame({"zPosition": segment_mid_values, "mean swi": merged_values, "model": source})

        return merged_df

    ###########################################################################
    # Views compare
    ###########################################################################

    def viewsCompare(self):
        slicer.app.setRenderPaused(True)
        self.buildLayout(self.models)
        qt.QTimer.singleShot(2 * self.REFRESH_DELAY, self.finishViewsCompare)

    def finishViewsCompare(self):
        allModels = slicer.util.getNodesByClass("vtkMRMLModelNode")
        for model in allModels:
            model.GetDisplayNode().GetDisplayableNode().SetDisplayVisibility(False)

        for i, (model, threeDWidget) in enumerate(zip(self.models, self.threeDWidgets)):
            viewNode = threeDWidget.viewLogic().GetViewNode()
            model.GetDisplayNode().AddViewNodeID(viewNode.GetID())
            model.GetDisplayNode().GetDisplayableNode().SetDisplayVisibility(True)
            threeDView = threeDWidget.threeDView()
            threeDView.rotateToViewAxis(3)
            threeDView.resetFocalPoint()
            threeDView.resetCamera()
            threeDWidget.viewLabel = f" Model {i + 1} - {model.GetName()} "

        slicer.app.setRenderPaused(False)

    def buildLayout(self, models=()):
        layout = self.generateLayoutDescriptor(models)
        layoutManager = slicer.app.layoutManager()
        layoutId = random.randint(10**8, (10**9) - 1)
        layoutManager.layoutLogic().GetLayoutNode().AddLayoutDescription(layoutId, layout)
        layoutManager.setLayout(layoutId)
        slicer.app.processEvents()
        qt.QTimer.singleShot(self.REFRESH_DELAY, self.finishBuildLayout)

    def finishBuildLayout(self):
        self.threeDWidgets = self.getThreeDWidgets()
        for threeDWidget in self.threeDWidgets:
            controller = threeDWidget.threeDController()
            controller.setBlackBackground()
            controller.set3DAxisVisible(False)
            controller.set3DAxisLabelVisible(False)
            controller.setOrientationMarkerType(slicer.vtkMRMLAbstractViewNode.OrientationMarkerTypeAxes)
            controller.setOrientationMarkerSize(slicer.vtkMRMLAbstractViewNode.OrientationMarkerSizeSmall)
            viewNode = threeDWidget.viewLogic().GetViewNode()
            viewNode.LinkedControlOn()

        self.sliceWidgets = self.getSliceWidgets()
        for sliceWidget in self.sliceWidgets:
            sliceCompositeNode = sliceWidget.sliceLogic().GetSliceCompositeNode()
            sliceCompositeNode.SetLinkedControl(True)

    def generateLayoutDescriptor(self, models=()):
        layout = """<layout type="vertical" split="true">"""
        layout += """<item splitSize="500">"""
        layout += """<layout type="horizontal">"""
        for i, model in enumerate(models):
            layout += f"""
                <item>
                    <view class="vtkMRMLViewNode" singletontag="PoreNetworkCompare{i + 1}">
                        <property name="viewlabel" action="default"> Model {i + 1} </property>
                    </view>
                </item>
            """
        layout += """</layout>"""
        layout += """</item>"""
        layout += """<item splitSize="500">"""
        layout += f"""
            <layout type="horizontal">
                <item>
                    <view class="vtkMRMLSliceNode" singletontag="PoreNetworkCompareRed">
                        <property name="orientation" action="default">XY</property>
                        <property name="viewlabel" action="default">R</property>
                        <property name="viewcolor" action="default">#F34A33</property>
                    </view>
                </item>
                <item>
                    <view class="vtkMRMLSliceNode" singletontag="PoreNetworkCompareGreen">
                        <property name="orientation" action="default">XZ</property>"
                        <property name="viewlabel" action="default">G</property>"
                        <property name="viewcolor" action="default">#6EB04B</property>"
                    </view>
                </item>
                <item>
                    <view class="vtkMRMLSliceNode" singletontag="PoreNetworkCompareYellow">
                        <property name="orientation" action="default">YZ</property>"
                        <property name="viewlabel" action="default">Y</property>"
                        <property name="viewcolor" action="default">#EDD54C</property>"
                    </view>
                </item>
            </layout>
        """
        layout += """</item>"""
        layout += """</layout>"""
        return layout

    def getThreeDWidgets(self):
        threeDWidgetNames = [f"ThreeDWidgetPoreNetworkCompare{i + 1}" for i in range(len(self.models))]
        threeDWidgets = []
        layoutManager = slicer.app.layoutManager()
        for threeDWidgetName in threeDWidgetNames:
            for i in range(layoutManager.threeDViewCount):
                threeDWidget = layoutManager.threeDWidget(i)
                if threeDWidget.name == threeDWidgetName:
                    threeDWidgets.append(threeDWidget)
                    break
        return threeDWidgets

    def getSliceWidgets(self):
        sliceWidgetsNames = ["PoreNetworkCompareRed", "PoreNetworkCompareGreen", "PoreNetworkCompareYellow"]
        sliceWidgets = []
        layoutManager = slicer.app.layoutManager()
        for sliceWidgetName in sliceWidgetsNames:
            sliceWidgets.append(layoutManager.sliceWidget(sliceWidgetName))
        return sliceWidgets

    ###########################################################################
    # Generate compare data
    ###########################################################################

    def apply(
        self,
        poreTable,
        poreLabelMap,
        watershedPoreLabelMap,
        cycleNodeModel,
        drainageOilLabelmaps,
        imbibitionOilLabelmaps,
        downsamplingFactor,
        outputFolderName,
        numNearestNeighbors,
    ):
        self.processStartTime = datetime.datetime.now()
        self.cancelProcess = False
        self.newSaturationIndex = 0

        # Pore table
        poreTableDataFrame = slicer.util.dataframeFromTable(poreTable)

        # Pore labelmap
        poreLabelMapArray = slicer.util.arrayFromVolume(poreLabelMap)

        # Input label map
        rasToIJKMatrix = vtk.vtkMatrix4x4()
        watershedPoreLabelMap.GetRASToIJKMatrix(rasToIJKMatrix)
        watershedPoreLabelMapArray = slicer.util.arrayFromVolume(watershedPoreLabelMap)
        # Input label map - transformation matrix
        transformationMatrix = vtk.vtkMatrix4x4()
        watershedPoreLabelMap.GetIJKToRASDirectionMatrix(transformationMatrix)
        poresLabelMapOrigin = watershedPoreLabelMap.GetOrigin()
        transformationMatrix.SetElement(0, 3, poresLabelMapOrigin[0])
        transformationMatrix.SetElement(1, 3, poresLabelMapOrigin[1])
        transformationMatrix.SetElement(2, 3, poresLabelMapOrigin[2])

        # Input cycle node from PN two phase simulation
        modelCoordinates = slicer.util.arrayFromModelPoints(cycleNodeModel)
        modelIds = slicer.util.arrayFromModelPointData(cycleNodeModel, "id")
        modelTypes = slicer.util.arrayFromModelPointData(cycleNodeModel, "type")
        uniquePoreModelIds = np.unique(modelIds[modelTypes == PORE_TYPE])
        uniqueThroatModelIds = np.unique(modelIds[modelTypes == TUBE_TYPE])
        modelPositions = slicer.util.arrayFromModelPointData(cycleNodeModel, "position")

        # Output cycle node with real and synthetic data
        shn = slicer.mrmlScene.GetSubjectHierarchyNode()
        itemIDToClone = shn.GetItemByDataNode(cycleNodeModel)
        clonedItemID = slicer.modules.subjecthierarchy.logic().CloneSubjectHierarchyItem(shn, itemIDToClone)
        cycleNodeModelSynthetic = shn.GetItemDataNode(clonedItemID)
        cycleNodeModelSynthetic.SetName(cycleNodeModel.GetName() + " - Synthetic")
        cycleNodeModelSynthetic.SetAttribute("PoreNetworkCompare", "True")
        clonedItemID = slicer.modules.subjecthierarchy.logic().CloneSubjectHierarchyItem(shn, itemIDToClone)
        cycleNodeModelReal = shn.GetItemDataNode(clonedItemID)
        cycleNodeModelReal.SetName(cycleNodeModel.GetName() + " - Real")
        cycleNodeModelReal.SetAttribute("PoreNetworkCompare", "True")
        remove_scalars(cycleNodeModelSynthetic, "saturation_")
        remove_scalars(cycleNodeModelSynthetic, "data_points")
        remove_scalars(cycleNodeModelSynthetic, "data_cycles")
        remove_scalars(cycleNodeModelReal, "saturation_")
        remove_scalars(cycleNodeModelReal, "data_points")
        remove_scalars(cycleNodeModelReal, "data_cycles")

        data_points = slicer.util.arrayFromModelPointData(cycleNodeModel, "data_points")
        data_cycles = slicer.util.arrayFromModelPointData(cycleNodeModel, "data_cycles")

        baseSyntheticSaturationVectorVolume = create_vector_volume_from_scalar(
            watershedPoreLabelMap, downsamplingFactor
        )

        shn = slicer.mrmlScene.GetSubjectHierarchyNode()
        outputFolderId = shn.CreateFolderItem(shn.GetSceneItemID(), outputFolderName)
        shn.SetItemParent(shn.GetItemByDataNode(cycleNodeModelSynthetic), outputFolderId)
        shn.SetItemParent(shn.GetItemByDataNode(cycleNodeModelReal), outputFolderId)

        # Getting the saturations from the oil injection phase (drainage - cycle 1)
        modelSaturations = getModelSaturations(cycleNodeModel, cycle=1)
        self.calculateSaturations(
            oilLabelMaps=drainageOilLabelmaps,
            poreLabelMapArray=poreLabelMapArray,
            modelSaturations=modelSaturations,
            modelCoordinates=modelCoordinates,
            uniquePoreModelIds=uniquePoreModelIds,
            uniqueThroatModelIds=uniqueThroatModelIds,
            modelPositions=modelPositions,
            modelIds=modelIds,
            poreTableDataFrame=poreTableDataFrame,
            transformationMatrix=transformationMatrix,
            rasToIJKMatrix=rasToIJKMatrix,
            watershedPoreLabelMapArray=watershedPoreLabelMapArray,
            data_points=data_points,
            data_cycles=data_cycles,
            cycleNodeModel=cycleNodeModel,
            cycleNodeModelSynthetic=cycleNodeModelSynthetic,
            cycleNodeModelReal=cycleNodeModelReal,
            baseSyntheticSaturationVectorVolume=baseSyntheticSaturationVectorVolume,
            downsamplingFactor=downsamplingFactor,
            outputFolderId=outputFolderId,
            numNearestNeighbors=numNearestNeighbors,
        )

        # Getting the saturations from the water injection phase (imbibition - cycle 2)
        modelSaturations = getModelSaturations(cycleNodeModel, cycle=2)
        self.calculateSaturations(
            oilLabelMaps=imbibitionOilLabelmaps,
            poreLabelMapArray=poreLabelMapArray,
            modelSaturations=modelSaturations,
            modelCoordinates=modelCoordinates,
            uniquePoreModelIds=uniquePoreModelIds,
            uniqueThroatModelIds=uniqueThroatModelIds,
            modelPositions=modelPositions,
            modelIds=modelIds,
            poreTableDataFrame=poreTableDataFrame,
            transformationMatrix=transformationMatrix,
            rasToIJKMatrix=rasToIJKMatrix,
            watershedPoreLabelMapArray=watershedPoreLabelMapArray,
            data_points=data_points,
            data_cycles=data_cycles,
            cycleNodeModel=cycleNodeModel,
            cycleNodeModelSynthetic=cycleNodeModelSynthetic,
            cycleNodeModelReal=cycleNodeModelReal,
            baseSyntheticSaturationVectorVolume=baseSyntheticSaturationVectorVolume,
            downsamplingFactor=downsamplingFactor,
            outputFolderId=outputFolderId,
            numNearestNeighbors=numNearestNeighbors,
        )

        # Cleanup
        slicer.mrmlScene.RemoveNode(baseSyntheticSaturationVectorVolume)

        return True

    def calculateSaturations(
        self,
        oilLabelMaps,
        poreLabelMapArray,
        modelSaturations,
        modelCoordinates,
        uniquePoreModelIds,
        uniqueThroatModelIds,
        modelPositions,
        modelIds,
        poreTableDataFrame,
        transformationMatrix,
        rasToIJKMatrix,
        watershedPoreLabelMapArray,
        data_points,
        data_cycles,
        cycleNodeModel,
        cycleNodeModelSynthetic,
        cycleNodeModelReal,
        baseSyntheticSaturationVectorVolume,
        downsamplingFactor,
        outputFolderId,
        numNearestNeighbors,
    ):
        self.modelPositionToPointIJK = {}
        new_data_points = []
        new_data_cycles = []

        for oilLabelMap in oilLabelMaps:
            self.poreSaturations = {}

            shn = slicer.mrmlScene.GetSubjectHierarchyNode()
            itemIDToClone = shn.GetItemByDataNode(baseSyntheticSaturationVectorVolume)
            clonedItemID = slicer.modules.subjecthierarchy.logic().CloneSubjectHierarchyItem(shn, itemIDToClone)
            syntheticSaturationVectorVolume = shn.GetItemDataNode(clonedItemID)
            syntheticSaturationVectorVolume.SetName(f"{self.newSaturationIndex} - {oilLabelMap.GetName()}")
            syntheticSaturationVectorVolumeArray = slicer.util.arrayFromVolume(syntheticSaturationVectorVolume).copy()
            shn.SetItemParent(shn.GetItemByDataNode(syntheticSaturationVectorVolume), outputFolderId)

            oilLabelMapArray = slicer.util.arrayFromVolume(oilLabelMap)

            downSampledOilLabelMapArray = downsample_array(oilLabelMapArray, downsamplingFactor)
            downSampledOilLabelMapArray = np.expand_dims(downSampledOilLabelMapArray, axis=-1)
            downSampledOilLabelMapArray = np.repeat(downSampledOilLabelMapArray, 3, axis=-1)

            labelMapSaturation = getLabelMapSaturation(poreLabelMapArray, oilLabelMapArray)
            saturationIndex = getClosestModelSaturationIndex(modelSaturations, labelMapSaturation)
            saturationScalarName = "saturation_" + str(saturationIndex)
            saturationValues = np.zeros(len(modelCoordinates))

            saturationValuesSynthetic = slicer.util.arrayFromModelPointData(cycleNodeModel, saturationScalarName).copy()

            newSaturationScalarName = f"saturation_{self.newSaturationIndex}"
            add_scalar_to_model_node(cycleNodeModelSynthetic, newSaturationScalarName, saturationValuesSynthetic)

            if numNearestNeighbors > 0:
                self.smoothSyntheticModelSaturation(
                    cycleNodeModelSynthetic, newSaturationScalarName, poreTableDataFrame, numNearestNeighbors
                )
            saturationValuesSynthetic = slicer.util.arrayFromModelPointData(
                cycleNodeModelSynthetic, newSaturationScalarName
            )

            for i, modelId in enumerate(uniquePoreModelIds):
                if self.cancelProcess:
                    break

                if i % 25 == 0:
                    end = datetime.datetime.now()
                    elapsed = end - self.processStartTime
                    self.statusLabel.setText(
                        f"Status: Calculating pore saturations for {oilLabelMap.GetName()} ("
                        + str(np.round(elapsed.total_seconds(), 1))
                        + ")"
                    )
                    self.progressBar.setValue(round(100 * (i / len(uniquePoreModelIds))))
                    slicer.app.processEvents()

                modelPosition = modelPositions[modelIds == modelId][0]

                pointIJK = self.getPointIJK(poreTableDataFrame, modelPosition, transformationMatrix, rasToIJKMatrix)

                if not pointIJK:
                    continue

                try:
                    poreLabel = watershedPoreLabelMapArray[pointIJK]
                    if poreLabel == 0:
                        continue
                except:
                    continue

                saturationValue = self.getSaturationValueFromArray(
                    watershedPoreLabelMapArray, oilLabelMapArray, pointIJK
                )

                saturationValues[modelIds == modelId] = saturationValue

                # Calculations for the voxel domain

                saturationValueSynthetic = saturationValuesSynthetic[modelIds == modelId][0]
                saturationWaterOccupiedRGB, saturationOilOccupiedRGB = convert_saturation_to_rgb_value(
                    saturationValueSynthetic
                )

                waterOccupiedMask = np.all(
                    np.logical_and(
                        syntheticSaturationVectorVolumeArray == [poreLabel, poreLabel, poreLabel],
                        downSampledOilLabelMapArray == [0, 0, 0],
                    ),
                    axis=3,
                )
                syntheticSaturationVectorVolumeArray[waterOccupiedMask] = saturationWaterOccupiedRGB

                oilOccupiedMask = np.all(
                    np.logical_and(
                        syntheticSaturationVectorVolumeArray == [poreLabel, poreLabel, poreLabel],
                        downSampledOilLabelMapArray == [1, 1, 1],
                    ),
                    axis=3,
                )
                syntheticSaturationVectorVolumeArray[oilOccupiedMask] = saturationOilOccupiedRGB

            clean_non_accessed_labels(syntheticSaturationVectorVolumeArray)
            slicer.util.updateVolumeFromArray(syntheticSaturationVectorVolume, syntheticSaturationVectorVolumeArray)

            for i, modelId in enumerate(uniqueThroatModelIds):
                if self.cancelProcess:
                    break

                if i % 25 == 0:
                    end = datetime.datetime.now()
                    elapsed = end - self.processStartTime
                    self.statusLabel.setText(
                        f"Status: Calculating throat saturations for {oilLabelMap.GetName()} ("
                        + str(np.round(elapsed.total_seconds(), 1))
                        + ")"
                    )
                    self.progressBar.setValue(round(100 * (i / len(uniqueThroatModelIds))))
                    slicer.app.processEvents()

                modelPosition = np.unique(modelPositions[modelIds == modelId], axis=0)

                point1IJK = self.getPointIJK(poreTableDataFrame, modelPosition[0], transformationMatrix, rasToIJKMatrix)
                point2IJK = self.getPointIJK(poreTableDataFrame, modelPosition[1], transformationMatrix, rasToIJKMatrix)

                if not point1IJK or not point2IJK:
                    continue

                try:
                    pore1Label = watershedPoreLabelMapArray[point1IJK]
                    pore2Label = watershedPoreLabelMapArray[point2IJK]
                    if pore1Label == 0 or pore2Label == 0:
                        continue
                except:
                    continue

                saturationValue1 = self.getSaturationValueFromArray(
                    watershedPoreLabelMapArray, oilLabelMapArray, point1IJK
                )
                saturationValue2 = self.getSaturationValueFromArray(
                    watershedPoreLabelMapArray, oilLabelMapArray, point2IJK
                )

                saturationValues[modelIds == modelId] = (saturationValue1 + saturationValue2) / 2

            new_data_points.append(data_points[saturationIndex])
            new_data_cycles.append(data_cycles[saturationIndex])

            add_scalar_to_model_node(cycleNodeModelReal, newSaturationScalarName, saturationValues)

            self.newSaturationIndex += 1

        add_scalar_to_model_node(cycleNodeModelSynthetic, "data_points", new_data_points)
        add_scalar_to_model_node(cycleNodeModelSynthetic, "data_cycles", new_data_cycles)
        add_scalar_to_model_node(cycleNodeModelReal, "data_points", new_data_points)
        add_scalar_to_model_node(cycleNodeModelReal, "data_cycles", new_data_cycles)

    def getPointIJK(self, poreTableDataFrame, modelPosition, transformationMatrix, rasToIJKMatrix):
        modelPosition = tuple(modelPosition)
        if modelPosition in self.modelPositionToPointIJK:
            return self.modelPositionToPointIJK[modelPosition]

        poreDataFrame = select_rows_within_delta(
            poreTableDataFrame,
            [
                ["pore.coords_0", modelPosition[0], 0.001],
                ["pore.coords_1", modelPosition[1], 0.001],
                ["pore.coords_2", modelPosition[2], 0.001],
            ],
        )

        if len(poreDataFrame) != 1:
            return False

        # Getting the global peaks coordinates
        pointRAS = poreDataFrame[["pore.global_peak_0", "pore.global_peak_1", "pore.global_peak_2"]].values
        # Updating RAS to account for any transformations on the labelmap
        pointRASUpdated = transformPoints(transformationMatrix, pointRAS, False)
        # Converting to IJK
        pointIJK = tuple(transformPoints(rasToIJKMatrix, pointRASUpdated, True)[0])[::-1]

        self.modelPositionToPointIJK[modelPosition] = pointIJK

        return pointIJK

    def getSaturationValueFromArray(self, watershedPoreLabelMapArray, oilLabelMapArray, pointIJK):
        subRegionSize = int(np.ceil(max(oilLabelMapArray.shape) / 4))
        oilLabelMapArraySubRegion = extract_cube(oilLabelMapArray, pointIJK, subRegionSize)
        watershedPoreLabelMapArraySubRegion = extract_cube(watershedPoreLabelMapArray, pointIJK, subRegionSize)
        poreLabel = watershedPoreLabelMapArray[pointIJK]
        if poreLabel in self.poreSaturations:
            return self.poreSaturations[poreLabel]
        saturationValue = getLabelMapPoreSaturation(
            oilLabelMapArraySubRegion, watershedPoreLabelMapArraySubRegion, poreLabel
        )
        self.poreSaturations[poreLabel] = saturationValue
        return saturationValue

    def cancel(self):
        self.cancelProcess = True

    def smoothSyntheticModelSaturation(
        self, cycleNodeModel, saturationScalarName, poreTableDataFrame, numNearestNeighbors
    ):
        modelIds = slicer.util.arrayFromModelPointData(cycleNodeModel, "id")
        modelTypes = slicer.util.arrayFromModelPointData(cycleNodeModel, "type")
        uniquePoreModelIds = np.unique(modelIds[modelTypes == PORE_TYPE])
        uniqueThroatModelIds = np.unique(modelIds[modelTypes == TUBE_TYPE])
        modelPositions = slicer.util.arrayFromModelPointData(cycleNodeModel, "position")
        uniquePoreModelPositions = np.unique(modelPositions[modelTypes == PORE_TYPE], axis=0)

        oldSaturationValues = slicer.util.arrayFromModelPointData(cycleNodeModel, saturationScalarName).copy()
        newSaturationValues = slicer.util.arrayFromModelPointData(cycleNodeModel, saturationScalarName).copy()

        # Pore saturations
        for i, modelId in enumerate(uniquePoreModelIds):
            if i % 50 == 0:
                end = datetime.datetime.now()
                elapsed = end - self.processStartTime
                self.statusLabel.setText(
                    f"Status: Smoothing pore saturations for {cycleNodeModel.GetName()} ("
                    + str(np.round(elapsed.total_seconds(), 1))
                    + ")"
                )
                self.progressBar.setValue(round(100 * (i / len(uniquePoreModelIds))))
                slicer.app.processEvents()

            modelPosition = modelPositions[modelIds == modelId][0]

            nearestPoresProperties = find_nearest_pores(
                modelPosition, uniquePoreModelPositions, poreTableDataFrame, numNearestNeighbors
            )

            saturationData = []
            for dist, pos, vol in nearestPoresProperties:
                poreModelId = modelIds[np.logical_and(np.all(modelPositions == pos, axis=1), modelTypes == PORE_TYPE)]
                poreModelId = poreModelId[0]
                poreSaturationValue = oldSaturationValues[modelIds == poreModelId][0]
                saturationData.append([dist, pos, vol, poreSaturationValue])

            # Pore distance * pore volume * pore saturation
            newSaturationValue = sum(vol * (1 / (dist + 1)) * sat for dist, _, vol, sat in saturationData) / sum(
                vol * (1 / (dist + 1)) for dist, _, vol, _ in saturationData
            )

            newSaturationValues[modelIds == modelId] = newSaturationValue

        # Throats saturations
        for i, modelId in enumerate(uniqueThroatModelIds):
            if i % 50 == 0:
                end = datetime.datetime.now()
                elapsed = end - self.processStartTime
                self.statusLabel.setText(
                    f"Status: Smoothing throat saturations for {cycleNodeModel.GetName()} ("
                    + str(np.round(elapsed.total_seconds(), 1))
                    + ")"
                )
                self.progressBar.setValue(round(100 * (i / len(uniqueThroatModelIds))))
                slicer.app.processEvents()

            modelPosition = np.unique(modelPositions[modelIds == modelId], axis=0)

            pore1Id = modelIds[
                np.logical_and(np.all(modelPositions == modelPosition[0], axis=1), modelTypes == PORE_TYPE)
            ][0]
            pore2Id = modelIds[
                np.logical_and(np.all(modelPositions == modelPosition[1], axis=1), modelTypes == PORE_TYPE)
            ][0]

            pore1SaturationValue = newSaturationValues[modelIds == pore1Id][0]
            pore2SaturationValue = newSaturationValues[modelIds == pore2Id][0]

            newSaturationValue = np.mean([pore1SaturationValue, pore2SaturationValue])
            newSaturationValues[modelIds == modelId] = newSaturationValue

        add_scalar_to_model_node(cycleNodeModel, saturationScalarName, newSaturationValues)


def getPoreVolume(poreTableDataFrame, modelPosition):
    modelPosition = tuple(modelPosition)

    poreDataFrame = select_rows_within_delta(
        poreTableDataFrame,
        [
            ["pore.coords_0", modelPosition[0], 0.001],
            ["pore.coords_1", modelPosition[1], 0.001],
            ["pore.coords_2", modelPosition[2], 0.001],
        ],
    )

    if len(poreDataFrame) != 1:
        return False

    # Getting the global peaks coordinates
    poreVolume = poreDataFrame[["pore.volume"]].values[0, 0]

    return poreVolume


def find_nearest_pores(input_pos, position_list, poreTableDataframe, N):
    # Calculate properties and store them with their corresponding coordinates
    properties = [(distance.euclidean(input_pos, pos), pos) for pos in position_list]

    # Sort the list of coordinates by distance
    properties.sort(key=lambda x: x[0])
    min_dist = properties[0][0]
    max_dist = properties[-1][0]

    properties = properties[: N + 1]

    # Normalizing the distances
    properties = [
        ((dist - min_dist) / (max_dist - min_dist), pos, getPoreVolume(poreTableDataframe, pos))
        for dist, pos in properties
    ]

    return properties


def extract_cube(array, center, side_length):
    x, y, z = center
    half_length = side_length // 2
    min_x = max(x - half_length, 0)
    max_x = min(x + half_length + 1, array.shape[0])
    min_y = max(y - half_length, 0)
    max_y = min(y + half_length + 1, array.shape[1])
    min_z = max(z - half_length, 0)
    max_z = min(z + half_length + 1, array.shape[2])
    cube = array[min_x:max_x, min_y:max_y, min_z:max_z]
    return cube


def select_rows_within_delta(data_frame, columns_info):
    selected_rows = data_frame.copy()

    for column_info in columns_info:
        column_name, target_value, fraction = column_info
        delta = target_value * fraction
        selected_rows = selected_rows[
            (selected_rows[column_name] >= target_value - delta) & (selected_rows[column_name] <= target_value + delta)
        ]

    return selected_rows


def remove_scalars(model_node, filter_string):
    point_data = model_node.GetPolyData().GetPointData()
    num_arrays = point_data.GetNumberOfArrays()
    arrays_to_remove = []

    for i in range(num_arrays):
        array_name = point_data.GetArrayName(i)
        if array_name.startswith(filter_string):
            arrays_to_remove.append(array_name)

    for array_name in arrays_to_remove:
        point_data.RemoveArray(array_name)

    model_node.Modified()


def add_scalar_to_model_node(model_node, scalar_name, scalar_values):
    new_scalar_array = vtk.vtkDoubleArray()
    new_scalar_array.SetName(scalar_name)
    new_scalar_array.SetNumberOfComponents(1)
    new_scalar_array.SetNumberOfTuples(len(scalar_values))

    for i in range(len(scalar_values)):
        new_scalar_array.SetTuple1(i, scalar_values[i])

    model_node.GetPolyData().GetPointData().AddArray(new_scalar_array)
    model_node.Modified()


def getClosestModelSaturationIndex(modelSaturations, targetSaturation):
    closestDifference = float("inf")
    for i, modelSaturation in enumerate(modelSaturations):
        difference = abs(targetSaturation - modelSaturation)
        if difference < closestDifference:
            index = i
            closestDifference = difference
    return index


def getLabelMapSaturation(poreLabelMapArray, oilLabelMapArray):
    poreVolumeInPixels = np.count_nonzero(poreLabelMapArray == 1)
    oilVolumeInPixels = np.count_nonzero(oilLabelMapArray == 1)
    return 1 - (oilVolumeInPixels / poreVolumeInPixels)


def getLabelMapPoreSaturation(oilLabelMapArray, inspectorLabelMapArray, poreLabel):
    poreVolumeInPixels = np.count_nonzero(inspectorLabelMapArray == poreLabel)
    oilVolumeInPixels = len(
        oilLabelMapArray[np.logical_and(oilLabelMapArray == 1, inspectorLabelMapArray == poreLabel)]
    )
    return 1 - (oilVolumeInPixels / poreVolumeInPixels)


def getModelSaturations(cycleNode, cycle):
    data_cycles = slicer.util.arrayFromModelPointData(cycleNode, "data_cycles")
    data_points = slicer.util.arrayFromModelPointData(cycleNode, "data_points").copy()
    data_points[data_cycles != cycle] = -1
    return data_points


def get_scalar_names_from_model_node(model_node, filter_string=None):
    scalar_names = []
    poly_data = model_node.GetPolyData()

    if poly_data:
        point_data = poly_data.GetPointData()
        cell_data = poly_data.GetCellData()

        # Function to check if the filter string is present in the scalar name
        def contains_filter(scalar_name):
            return filter_string is None or (filter_string in scalar_name)

        # Get scalar names from point data
        for i in range(point_data.GetNumberOfArrays()):
            scalar_name = point_data.GetArrayName(i)
            if contains_filter(scalar_name):
                scalar_names.append(scalar_name)

        # Get scalar names from cell data
        for i in range(cell_data.GetNumberOfArrays()):
            scalar_name = cell_data.GetArrayName(i)
            if contains_filter(scalar_name):
                scalar_names.append(scalar_name)

    return scalar_names


def create_vector_volume_from_scalar(scalar_volume, downsampling_factor):
    array = slicer.util.arrayFromVolume(scalar_volume)

    array = downsample_array(array, downsampling_factor)
    array = array.astype(float)  # this is needed to solve a bug when saving this volume on the scene

    expanded_array = np.expand_dims(array, axis=-1)
    expanded_array = np.repeat(expanded_array, 3, axis=-1)

    vector_volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode")
    vector_volume.SetName(scalar_volume.GetName())
    matrix = vtk.vtkMatrix4x4()
    scalar_volume.GetIJKToRASMatrix(matrix)
    vector_volume.SetIJKToRASMatrix(matrix)
    vector_volume.SetSpacing(np.array(vector_volume.GetSpacing()) / downsampling_factor)

    slicer.util.updateVolumeFromArray(vector_volume, expanded_array)

    return vector_volume


def downsample_array(array, downsampling_factor):
    return zoom(array, downsampling_factor, order=0, cval=np.min(array))


def convert_saturation_to_rgb_value(saturation):
    def hsv_to_rgb(h, s, v):
        return tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h, s, v))

    h = saturation * 0.16

    saturationWaterOccupiedRGB = hsv_to_rgb(h, 1, 0.75)
    saturationOilOccupiedRGB = hsv_to_rgb(h, 1, 0.3)

    return saturationWaterOccupiedRGB, saturationOilOccupiedRGB


def clean_non_accessed_labels(array):
    mask = np.all(array == array[..., :1], axis=-1)
    array[mask] = [0, 0, 0]


def get_sorted_nodes_from_folder(folderId, node_type=None):
    shn = slicer.mrmlScene.GetSubjectHierarchyNode()
    nodes = vtk.vtkCollection()
    sorted_nodes = []
    shn.GetDataNodesInBranch(folderId, nodes)
    for i in range(nodes.GetNumberOfItems()):
        node = nodes.GetItemAsObject(i)
        if not node_type or (node_type and type(node) is node_type):
            sorted_nodes.append(node)
    sorted_nodes = sorted(sorted_nodes, key=lambda x: x.GetName())
    return sorted_nodes


class ApplyInfo(RuntimeError):
    pass


class CompareInfo(RuntimeError):
    pass
