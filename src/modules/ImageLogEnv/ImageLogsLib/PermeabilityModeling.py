import os

import ctk
import markdown2 as markdown
import qt
import slicer
from ltrace.slicer import helpers, ui
from ltrace.slicer.helpers import highlight_error, reset_style_on_valid_node
from ltrace.slicer.helpers import reset_style_on_valid_text
from ltrace.slicer.node_attributes import ImageLogDataSelectable
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from vtk.util.numpy_support import vtk_to_numpy


class PermeabilityModelingWidget(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.logic = PermeabilityModelingLogic(self)

        self.onOutputNodeReady = lambda volumes: None

        layout = qt.QVBoxLayout()
        self.setLayout(layout)

        self.progressBar = None
        self.ioFileInputLineEdit = None
        self.depthLogNameLineEdit = None
        self.porosityLogNameLineEdit = None
        self.ioPlugFileInputLineEdit = None
        self.missingValuePlaceholderInput = None

        self.subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        self.inputSection()
        self.paramsSection()
        self.measurementSection()
        self.outputSection()

        self.applyButton = ui.ButtonWidget(text="Apply", onClick=self.onApply)

        self.applyButton.setStyleSheet("QPushButton {font-size: 11px; font-weight: bold; padding: 8px; margin: 4px}")
        self.applyButton.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Preferred)

        self.progressBar = LocalProgressBar()

        layout.addWidget(self.applyButton)

        layout.addWidget(self.progressBar)

        layout.addStretch(1)

    @classmethod
    def help(cls):
        htmlHelp = ""
        with open(cls.readme_path(), "r", encoding="utf-8") as docfile:
            md = markdown.Markdown(extras=["fenced-code-blocks"])
            htmlHelp = md.convert(docfile.read())
        return htmlHelp

    @classmethod
    def readme_path(cls):
        dir_path = os.path.dirname(os.path.realpath(__file__))
        return str(dir_path + "/" + "PermeabilityModeling.md")

    def inputSection(self):
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Input Images"
        self.layout().addWidget(parametersCollapsibleButton)

        # Layout within the dummy collapsible button
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

        self._porosity_log_input = hierarchyVolumeInput(onChange=lambda i: self.__on_porosity_table_changed(i))
        self._porosity_log_input.setNodeTypes(["vtkMRMLTableNode"])
        reset_style_on_valid_node(self._porosity_log_input)
        self._porosity_log_combo_box = qt.QComboBox()
        reset_style_on_valid_node(self._porosity_log_combo_box)
        self.segmented_image_input = hierarchyVolumeInput(onChange=self.onSegmentedImageSelected)
        self.segmented_image_input.setNodeTypes(["vtkMRMLSegmentationNode", "vtkMRMLLabelMapVolumeNode"])
        reset_style_on_valid_node(self.segmented_image_input)

        parametersFormLayout.addRow("Well logs (.las):", self._porosity_log_input)
        parametersFormLayout.addRow("Porosity Log:", self._porosity_log_combo_box)
        parametersFormLayout.addRow("Segmented Image:", self.segmented_image_input)

    def __on_porosity_table_changed(self, node_id):
        node = self.subjectHierarchyNode.GetItemDataNode(node_id)

        if node is None:
            return

        logs = [node.GetColumnName(index) for index in range(node.GetNumberOfColumns())]
        if "DEPTH" not in logs:
            message = (
                "The selected table doesn't have a column related to the 'Depth' data."
                "\nPlease select another table or load a log file."
            )
            slicer.util.errorDisplay(message, windowTitle="Error", parent=self.__mainWindow)
            return

        logs.remove("DEPTH")
        # populate porosity log combo box
        self._porosity_log_combo_box.clear()
        self._porosity_log_combo_box.addItems(logs)

    def paramsSection(self):
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Parameters"
        self.layout().addWidget(parametersCollapsibleButton)

        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

        self.modelSelector = qt.QComboBox()
        self.modelSelector.enabled = False
        self.modelSelector.connect("currentIndexChanged(int)", lambda v: self.onNumericChanged("class1", v))

        self.missingSelector = qt.QComboBox()
        self.missingSelector.enabled = False
        self.missingSelector.connect("currentIndexChanged(int)", lambda v: self.onNumericChanged("nullable", v))

        parametersFormLayout.addRow("Macro Pore Segment: ", self.modelSelector)
        parametersFormLayout.addRow("Ignored/null Segment: ", self.missingSelector)

    def measurementSection(self):
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Reference Permeability"
        self.layout().addWidget(parametersCollapsibleButton)

        # Layout within the dummy collapsible button
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

        self._plugs_permeability_table_combo_box = hierarchyVolumeInput(
            onChange=lambda i: self.__on_plugs_permeability_table_changed(i)
        )
        reset_style_on_valid_node(self._plugs_permeability_table_combo_box)
        self._plugs_permeability_table_combo_box.setNodeTypes(["vtkMRMLTableNode"])
        self._plugs_permeability_log_combo_box = qt.QComboBox()
        parametersFormLayout.addRow("Plugs measurements:", self._plugs_permeability_table_combo_box)
        parametersFormLayout.addRow("Plugs Permeability Log:", self._plugs_permeability_log_combo_box)

    def __on_plugs_permeability_table_changed(self, node_id):
        node = self.subjectHierarchyNode.GetItemDataNode(node_id)

        if node is None:
            return

        logs = [node.GetColumnName(index) for index in range(node.GetNumberOfColumns())]
        if "DEPTH" not in logs:
            message = (
                "The selected table doesn't have a column related to the 'Depth' data."
                "\nPlease select another table or load a log file."
            )
            slicer.util.errorDisplay(message, windowTitle="Error", parent=slicer.util.mainWindow())
            return

        logs.remove("DEPTH")
        # Populate porosity log combo box
        self._plugs_permeability_log_combo_box.clear()
        self._plugs_permeability_log_combo_box.addItems(logs)

    def outputSection(self):
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Output"
        self.layout().addWidget(parametersCollapsibleButton)

        self.outputNameLineEdit = qt.QLineEdit()
        reset_style_on_valid_text(self.outputNameLineEdit)
        self.outputNameLineEdit.setToolTip("Type the text to be used as the output node's name.")

        # Layout within the dummy collapsible button
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.addRow("Output Name: ", self.outputNameLineEdit)

    def setDefaults(self, **kwargs):
        pass

    def onPLUGPathChanged(self, p):
        self.onTextChanged("file", p)

    def onApply(self):
        if self._porosity_log_input.currentNode() is None:
            highlight_error(self._porosity_log_input)
            return

        if self._porosity_log_combo_box.currentText == "":
            highlight_error(self._porosity_log_combo_box)
            return

        if self.segmented_image_input.currentNode() is None:
            highlight_error(self.segmented_image_input)
            return

        if self._plugs_permeability_table_combo_box.currentNode() is None:
            highlight_error(self._plugs_permeability_table_combo_box)
            return

        if self.outputNameLineEdit.text.strip() == "":
            highlight_error(self.outputNameLineEdit)
            return

        self.logic.model["outputVolumeName"] = self.outputNameLineEdit.text

        # Update model parameters
        porosity_log_scalar_node = helpers.createTemporaryVolumeNode(
            slicer.vtkMRMLScalarVolumeNode, "POROSITY_LOG_TMP_NODE", hidden=True
        )
        porosity_depth_scalar_node = helpers.createTemporaryVolumeNode(
            slicer.vtkMRMLScalarVolumeNode, "POROSITY_DEPTH_TMP_NODE", hidden=True
        )
        permeability_plug_log_scalar_node = helpers.createTemporaryVolumeNode(
            slicer.vtkMRMLScalarVolumeNode, "PERMEABILITY_PLUG_TMP_NODE", hidden=True
        )
        permeability_plug_depth_scalar_node = helpers.createTemporaryVolumeNode(
            slicer.vtkMRMLScalarVolumeNode, "PERMEABILITY_PLUG_DEPTH_TMP_NODE", hidden=True
        )
        permeability_output = slicer.mrmlScene.AddNewNodeByClass(
            slicer.vtkMRMLTableNode.__name__, self.logic.model["outputVolumeName"]
        )
        permeability_output.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)

        porosity_log_table_node = self.subjectHierarchyNode.GetItemDataNode(self._porosity_log_input.currentItem())
        porosity_log_array = vtk_to_numpy(
            porosity_log_table_node.GetTable().GetColumnByName(self._porosity_log_combo_box.currentText)
        )
        porosity_depth_array = vtk_to_numpy(porosity_log_table_node.GetTable().GetColumnByName("DEPTH"))

        permeability_plug_log_table_node = self.subjectHierarchyNode.GetItemDataNode(
            self._plugs_permeability_table_combo_box.currentItem()
        )
        permeability_plug_log_array = vtk_to_numpy(
            permeability_plug_log_table_node.GetTable().GetColumnByName(
                self._plugs_permeability_log_combo_box.currentText
            )
        )
        permeability_plug_depth_array = vtk_to_numpy(
            permeability_plug_log_table_node.GetTable().GetColumnByName("DEPTH")
        )

        porosity_log_array = porosity_log_array.reshape(porosity_log_array.shape[0], 1, 1)
        porosity_depth_array = porosity_depth_array.reshape(porosity_depth_array.shape[0], 1, 1)
        permeability_plug_log_array = permeability_plug_log_array.reshape(permeability_plug_log_array.shape[0], 1, 1)
        permeability_plug_depth_array = permeability_plug_depth_array.reshape(
            permeability_plug_depth_array.shape[0], 1, 1
        )

        slicer.util.updateVolumeFromArray(porosity_log_scalar_node, porosity_log_array)
        slicer.util.updateVolumeFromArray(porosity_depth_scalar_node, porosity_depth_array)
        slicer.util.updateVolumeFromArray(permeability_plug_log_scalar_node, permeability_plug_log_array)
        slicer.util.updateVolumeFromArray(permeability_plug_depth_scalar_node, permeability_plug_depth_array)

        self.logic.model["log_por"] = porosity_log_scalar_node.GetID()
        self.logic.model["depth_por"] = porosity_depth_scalar_node.GetID()
        self.logic.model["perm_plugs"] = permeability_plug_log_scalar_node.GetID()
        self.logic.model["depth_plugs"] = permeability_plug_depth_scalar_node.GetID()
        self.logic.model["outputVolume"] = permeability_output.GetID()

        self.logic.run()

    def onCancel(self):
        self.logic.cancelCLI()

    def onSegmentedImageSelected(self, itemId):
        node = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        volumeNode = node.GetItemDataNode(itemId)

        if volumeNode is None or (
            not volumeNode.IsA(slicer.vtkMRMLLabelMapVolumeNode.__name__)
            and not volumeNode.IsA(slicer.vtkMRMLSegmentationNode.__name__)
        ):
            self.logic.model["inputVolume1"] = None
            self.modelSelector.enabled = False
            self.missingSelector.enabled = False
            return

        self.modelSelector.clear()
        self.missingSelector.clear()

        segments_dict = helpers.extractLabels(volumeNode)

        for selector in [self.modelSelector, self.missingSelector]:
            selector.addItems(list(segments_dict.values()))

        self.logic.model["inputVolume1"] = volumeNode.GetID()
        self.outputNameLineEdit.setText(f"{volumeNode.GetName()}_Permeability_Output")
        self.modelSelector.enabled = True
        self.missingSelector.enabled = True

    def onNumericChanged(self, key, value):
        self.logic.model[key] = value

    def onTextChanged(self, key, value):
        self.logic.model[key] = str(value)

    def onComplete(self):
        self.remove_temporary_nodes()

        output_node_id = self.logic.model["outputVolume"]
        self.onOutputNodeReady([self.logic.model["outputVolume"]])

        output_node = helpers.tryGetNode(output_node_id)
        helpers.autoDetectColumnType(output_node)

    def onCompletedWithErrors(self, *args, **kwargs):
        self.remove_temporary_nodes()

    def onCancelled(self):
        self.remove_temporary_nodes()

    def remove_temporary_nodes(self):
        temp_nodes_name = [
            "POROSITY_LOG_TMP_NODE",
            "POROSITY_DEPTH_TMP_NODE",
            "PERMEABILITY_PLUG_TMP_NODE",
            "PERMEABILITY_PLUG_DEPTH_TMP_NODE",
        ]
        for node_name in temp_nodes_name:
            node = helpers.tryGetNode(node_name)
            if node is None:
                continue

            slicer.mrmlScene.RemoveNode(node)


class PermeabilityModelingLogic(object):
    def __init__(self, widget):
        self.model = PermeabilityModelingModel()
        self.cliNode = None
        self.widget = widget

    def cancelCLI(self):
        if self.cliNode:
            self.cliNode.Cancel()
            self.cliNode = None

    def eventHandler(self, caller, event):
        if self.cliNode is None:
            return

        status = caller.GetStatusString()
        try:
            if status == "Completed":
                self.widget.onComplete()
                self.cliNode = None
            elif "Completed" in status:
                self.widget.onCompletedWithErrors()
                self.cliNode = None
            elif status == "Cancelled":
                self.widget.onCancelled()
                self.cliNode = None
        except Exception as e:
            print(f'Exception on Event Handler: {repr(e)} with status "{status}"')
            self.widget.onCompletedWithErrors()

    def run(self):
        self.cliNode = slicer.cli.run(
            slicer.modules.permeabilitymodelingcli,
            None,
            {k: v for k, v in self.model.items()},
            wait_for_completion=False,
        )

        self.cliNode.AddObserver("ModifiedEvent", lambda c, e: self.eventHandler(c, e))
        self.widget.progressBar.setCommandLineModuleNode(self.cliNode)
        return self.cliNode


def PermeabilityModelingModel():
    return dict(
        log_por=None,
        depth_por=None,
        inputVolume1=None,
        class1=1,
        depth_plugs=None,
        perm_plugs=None,
        outputVolume=None,
        nullable=0,
        outputVolumeName=None,
    )
