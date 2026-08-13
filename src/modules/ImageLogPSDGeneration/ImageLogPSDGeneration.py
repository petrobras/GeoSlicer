import os
import qt
import slicer
import slicer.util
import logging
import uuid
import json
import math

from functools import partial
from ltrace.slicer import ui, widgets, helpers
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widget.preset_widget import Preset, PresetWidget
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer.node_attributes import Tag, ImageLogDataSelectable
from ltrace.slicer.metadata import Metadata
from ltrace.constants import PSDLib
from pathlib import Path
from CustomResampleScalarVolume import CustomResampleScalarVolumeLogic, ResampleScalarVolumeData
from ImageLogPSDGenerationParameterWidgets.ParameterWidgets import MicrotomParameters, PorespyParameters
from typing import Dict

try:
    from Test.ImageLogPSDGenerationTest import ImageLogPSDGenerationTest
except ImportError:
    ImageLogPSDGenerationTest = None  # tests not deployed to final version or closed source


class ImageLogPSDGenerationPreset(Preset):
    def __init__(
        self,
        id=None,
        name=None,
        satResMicrotom=None,
        radResMicrotom=None,
        sizesPorespy=None,
        smoothPorespy=None,
        methodPorespy=None,
        **kargs,
    ):
        super().__init__(id, name)

        # Microtom parameters
        self.satResMicrotom = satResMicrotom
        self.radResMicrotom = radResMicrotom

        # Porespy parameters
        self.sizesPorespy = sizesPorespy
        self.smoothPorespy = smoothPorespy
        self.methodPorespy = methodPorespy


class ImageLogPSDGeneration(LTracePlugin):
    SETTING_KEY = "ImageLogPSDGeneration"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    PRESETS_PATH = Path(slicer.app.slicerUserSettingsFilePath).parent / "ImageLogPSDGenerationPresets.json"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Image Generation"
        self.parent.categories = ["Tools", "ImageLog"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.setHelpUrl("ImageLog/PoreSizeDistribution/PoreSizeDistribution.html#image-generation")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ImageLogPSDGenerationWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

        self.logic = None
        self.presetsFilePath = ImageLogPSDGeneration.PRESETS_PATH
        self.exportPresetsPath = os.path.join(slicer.mrmlScene.GetRootDirectory(), "ImageLogPSDGenerationPresets.json")
        self.importPresetsPath = slicer.mrmlScene.GetRootDirectory()
        self.presets: Dict[uuid.UUID, PSDLib] = {}
        self.psdParameters = {}

    def setup(self):
        LTracePluginWidget.setup(self)

        progressBar = LocalProgressBar()
        progressBar.setContentsMargins(0, 0, 5, 0)

        # Create logic
        self.logic = ImageLogPSDGenerationLogic(self.parent, self, progressBar)
        self.logic.processFinished.connect(self._onProcessFinished)

        # Init presets
        self.presets = self.logic.getPresets(self.presetsFilePath)

        # Psd lib section
        psdLibSection = ui.collapsibleButton("Library")

        self.psdLibSelector = qt.QComboBox()
        self.psdLibSelector.setToolTip("Select the PSD library.")
        self.psdLibSelector.objectName = "PSD Lib Combo Box"
        [self.psdLibSelector.addItem(lib.value, lib) for lib in PSDLib]
        self.psdLibSelector.currentIndexChanged.connect(self._onPsdLibSelected)

        psdLibLayout = qt.QFormLayout(psdLibSection)
        psdLibLayout.setContentsMargins(10, 8, 10, 6)
        psdLibLayout.addRow("PSD Lib: ", self.psdLibSelector)

        # Input section
        inputSection = ui.collapsibleButton("Input")

        self.inputSelector = widgets.SingleShotInputWidget(dimensionsUnits={"px": True, "mm": True})
        self.inputSelector.objectName = "Single Shot Input"
        self.inputSelector.segmentListWidget.setHideBackground(True)
        self.inputSelector.formLayout.setContentsMargins(6, 6, 6, 0)
        self.inputSelector.onMainSelectedSignal.connect(self._onInputSelected)
        self.inputSelector.onReferenceSelectedSignal.connect(self._onReferenceSelected)

        inputLayout = qt.QFormLayout(inputSection)
        inputLayout.addRow(self.inputSelector)

        # Preset section
        presetHelpText = (
            "You can save the parameters to use it later. The parameters of different libraries can be "
            "saved in the same preset.\n\n"
            "**Create:** Create a preset with the current parameters.<br>"
            "**Rename:** Rename a preset.<br>"
            "**Save:** Saves the current parameters in the selected preset.<br>"
            "**Delete:** Delete the selected preset.<br>\n\n"
            "You can also import and export presets in JSON format. When importing, the selected presets in the file "
            "will be added to the existing presets. If a preset with the same name already exists, a unique suffix "
            "will be added to the name of the imported preset."
        )

        self.presetWidget = PresetWidget(
            onPresetSelected=self._onPresetSelected,
            onCreatePresetClicked=self._onCreatePresetClicked,
            onRenamePresetClicked=self._onRenamePresetClicked,
            onSavePresetClicked=self._onSavePresetClicked,
            onDeletePresetClicked=self._onDeletePresetClicked,
            onExportPresetClicked=self._onExportPresetClicked,
            onImportPresetClicked=self._onImportPresetClicked,
            helpText=presetHelpText,
            styledBox=True,
            parent=self.layout.parentWidget(),
        )

        # Warning label of modified presets
        self.warningLabel = qt.QLabel(
            "Warning: Parameters marked with (*) have been modified and are not \nsaved in the selected preset."
        )
        self.warningLabel.setStyleSheet("QLabel { color : yellow; }")
        self.warningLabel.hide()

        # Parameters section
        parametersSection = ui.collapsibleButton("Parameters")

        self.psdParameters[PSDLib.MICROTOM] = MicrotomParameters(self.warningLabel, "Microtom Parameters")
        self.psdParameters[PSDLib.PORESPY] = PorespyParameters(self.warningLabel, "Porespy Parameters")

        self.parametersWidget = qt.QStackedWidget()
        self.parametersWidget.setContentsMargins(6, 0, 6, 0)
        self.parametersWidget.addWidget(self.psdParameters[PSDLib.MICROTOM])
        self.parametersWidget.addWidget(self.psdParameters[PSDLib.PORESPY])

        # Reset buttons
        self.resetPresetBtn = ui.ButtonWidget(
            text="Reload Preset Values",
            onClick=self._onResetPresetClicked,
            object_name="Reset Parameters Preset",
            tooltip="Reset parameters with the preset values",
        )

        self.resetParametersBtn = ui.ButtonWidget(
            text="Reload Default Values",
            onClick=self._onResetParametersClicked,
            object_name="Reset Parameters Default",
            tooltip="Reset parameters with default lib values",
        )

        buttonLayout = qt.QHBoxLayout()
        buttonLayout.setContentsMargins(0, 6, 6, 0)
        buttonLayout.addStretch(1)
        buttonLayout.addWidget(self.resetPresetBtn)
        buttonLayout.addWidget(self.resetParametersBtn)

        # Parameters section widget
        parametersLayout = qt.QFormLayout(parametersSection)
        parametersLayout.addRow(self.presetWidget)
        parametersLayout.addRow(self.parametersWidget)
        parametersLayout.addRow(self.warningLabel)
        parametersLayout.addRow(buttonLayout)

        # Output section
        outputSection = ui.collapsibleButton("Output")

        self.outputPrefixLine = qt.QLineEdit()
        self.outputPrefixLine.objectName = "Output Prefix Line Edit"

        self.manualOutputPrefixCheckBox = ui.CheckBoxWidget(
            "Activate output prefix edition", self._onManualOutputPrefixCheckBoxToggled, checked=False
        )
        self.manualOutputPrefixCheckBox.objectName = "Manual Output Prefix Check Box"

        outputContentWidget = qt.QWidget()
        outputContentLayout = qt.QHBoxLayout(outputContentWidget)
        outputContentLayout.setContentsMargins(0, 0, 0, 0)
        outputContentLayout.addWidget(self.outputPrefixLine)
        outputContentLayout.addWidget(self.manualOutputPrefixCheckBox)

        outputLayout = qt.QFormLayout(outputSection)
        outputLayout.setContentsMargins(9, 8, 5, 6)
        outputLayout.addRow("Output prefix:", outputContentWidget)

        # Apply button
        self.applyCancelButton = ui.ApplyCancelButtons(
            onApplyClick=self._onApplyButtonClicked, onCancelClick=self._onCancelButtonClicked, enabled=False
        )
        self.applyCancelButton.objectName = "Apply and Cancel Buttons"
        self.applyCancelButton.buttonLayout.setContentsMargins(10, 6, 10, 0)
        self.applyCancelButton.applyBtn.setProperty("class", None)
        self.applyCancelButton.applyBtn.setStyleSheet("QPushButton {padding: 8px; margin: 0px; font-weight: bold;}")
        self.applyCancelButton.applyBtn.setFixedHeight(40)
        self.applyCancelButton.cancelBtn.setStyleSheet("QPushButton {padding: 8px; margin: 0px; font-weight: bold;}")
        self.applyCancelButton.cancelBtn.setFixedHeight(40)

        # Update layout
        self.layout.addWidget(psdLibSection)
        self.layout.addWidget(inputSection)
        self.layout.addWidget(parametersSection)
        self.layout.addWidget(outputSection)
        self.layout.addWidget(self.applyCancelButton)
        self.layout.addWidget(progressBar)
        self.layout.addStretch(1)

        # Module configs
        self.presetWidget.loadData(self.presets.values())
        self._onManualOutputPrefixCheckBoxToggled(self.manualOutputPrefixCheckBox, False)

    # Module functions
    def cleanup(self):
        super().cleanup()

        if self.logic:
            self.logic.cleanup()
            self.logic.deleteLater()
            self.logic = None

    # Button events
    def _onResetPresetClicked(self, state):
        if self.presetWidget.getCurrentData() is None:
            return

        psdLib = self.psdLibSelector.currentData
        self.psdParameters[psdLib].presetToFields()

    def _onResetParametersClicked(self, state):
        psdLib = self.psdLibSelector.currentData
        self.psdParameters[psdLib].resetDefaultValues()

    def _onApplyButtonClicked(self, state):
        try:
            psdLib = self.psdLibSelector.currentData
            segmentationNode = self.inputSelector.mainInput.currentNode()
            soiNode = self.inputSelector.soiInput.currentNode()
            refNode = self.inputSelector.referenceInput.currentNode()
            manualOutputPrefix = self.manualOutputPrefixCheckBox.isChecked()
            outputPrefix = self.outputPrefixLine.text.strip()

            selectedLabels = []
            errors = []

            if segmentationNode is None:
                errors.append("Please select the segmentation node.")
            else:
                if segmentationNode.IsA("vtkMRMLSegmentationNode"):
                    segmap = helpers.segmentListAndProportionsFromSegmentation(segmentationNode, soiNode)
                else:
                    segmap = helpers.segmentProportionFromLabelMap(segmentationNode, soiNode)

                labels = sorted(v for v in segmap if v != "total")
                selectedLabels = [labels[i] for i in self.inputSelector.getSelectedSegments()]

            if not selectedLabels:
                helpers.highlight_error(self.inputSelector.segmentListWidget)
                errors.append("Please select at least one segment.")

            if refNode is None:
                errors.append("Please select the reference image.")

            errors.extend(self.psdParameters[psdLib].validateFields())

            if errors:
                slicer.util.errorDisplay("\n".join(errors), "Missing Data")
                return

            self.logic.apply(
                psdLib,
                segmentationNode,
                refNode,
                selectedLabels,
                soiNode,
                manualOutputPrefix,
                outputPrefix,
                params=self.psdParameters[psdLib].getParameters(),
                metadata=self.psdParameters[psdLib].getMetadata(),
            )

            self._changeApplyButtonState(False)
            self._changeCancelButtonState(True)
        except Exception as ex:
            logging.error(repr(ex))
            self._changeCancelButtonState(False)
            self._changeApplyButtonState(True)

    def _onCancelButtonClicked(self, state):
        self.logic.cancel()
        self._changeCancelButtonState(False)
        self._changeApplyButtonState(True)

    def _onManualOutputPrefixCheckBoxToggled(self, checkbox, state):
        if self.manualOutputPrefixCheckBox.isChecked():
            self.outputPrefixLine.enabled = True
        else:
            self.outputPrefixLine.enabled = False
            if self.inputSelector.mainInput.currentNode():
                self.outputPrefixLine.text = self.inputSelector.mainInput.currentNode().GetName()
            else:
                self.outputPrefixLine.text = ""

    # Preset events
    def _onPresetSelected(self, index):
        presetId = self.presetWidget.getCurrentData()

        if presetId is None or not self.presets:
            self.resetPresetBtn.enabled = False
            self._updateParametersCurrentPreset(None)

            for parameter in self.psdParameters.values():
                parameter.removeAllModifiedSpans()

            self._checkShowWarning()
            return

        self.resetPresetBtn.enabled = True

        self._updateParametersCurrentPreset(self.presets[presetId])

    def _onCreatePresetClicked(self, state):
        psdLib = self.psdLibSelector.currentData
        errors = self.psdParameters[psdLib].validateFields()

        if errors:
            slicer.util.errorDisplay("\n".join(errors), "Missing Data")
            return

        name = self.presetWidget.execCreateDialog()

        if name:
            preset = ImageLogPSDGenerationPreset()
            preset.name = slicer.mrmlScene.GenerateUniqueName(name)

            self._updateParametersCurrentPreset(preset, False)

            # Update preset with the parameters values
            for parameter in self.psdParameters.values():
                parameter.fieldsToPreset()

            self.presets[preset.id] = preset

            self.presetWidget.addItem(preset)

            self.logic.savePresets(self.presetsFilePath, self.presets)

            slicer.util.showStatusMessage("Preset Created", 2000)

    def _onRenamePresetClicked(self, state):
        presetId = self.presetWidget.getCurrentData()

        if presetId is None:
            return

        name = self.presetWidget.execRenameDialog()

        if name:
            presetName = slicer.mrmlScene.GenerateUniqueName(name)

            preset = self.presets[presetId]
            preset.name = presetName

            self.presets[presetId] = preset
            self.presetWidget.updateItem(preset)

            self.logic.savePresets(self.presetsFilePath, self.presets)

            slicer.util.showStatusMessage("Preset Renamed", 2000)

    def _onSavePresetClicked(self, state):
        presetId = self.presetWidget.getCurrentData()
        psdLib = self.psdLibSelector.currentData

        if presetId is None:
            return

        errors = self.psdParameters[psdLib].validateFields()

        if errors:
            slicer.util.errorDisplay("\n".join(errors), "Missing Data")
            return False

        self.psdParameters[psdLib].fieldsToPreset()
        self.psdParameters[psdLib].removeAllModifiedSpans()

        self._checkShowWarning()

        self.logic.savePresets(self.presetsFilePath, self.presets)

        slicer.util.showStatusMessage("Preset Saved", 2000)

    def _onDeletePresetClicked(self, state):
        presetId = self.presetWidget.getCurrentData()

        if presetId is None:
            return

        isAccepted = self.presetWidget.execDeleteDialog()

        if isAccepted:
            self.presetWidget.removeItem(self.presets[presetId])
            del self.presets[presetId]

            for parameter in self.psdParameters.values():
                parameter.resetDefaultValues()

            self.logic.savePresets(self.presetsFilePath, self.presets)

            slicer.util.showStatusMessage("Preset Deleted", 2000)

    def _onExportPresetClicked(self, state):
        selectedPresets = self.presetWidget.execExportDialog(data=self.presets.values())

        if selectedPresets:
            filePath = self.presetWidget.execGetSaveFileDialog(directory=self.exportPresetsPath)

            if filePath:
                presets = {key: self.presets[key] for key in selectedPresets}
                self.logic.exportPreset(filePath, presets)

                slicer.util.showStatusMessage("Presets exported successfully.", 2000)

    def _onImportPresetClicked(self, state):
        file = self.presetWidget.execGetOpenFileDialog(directory=self.importPresetsPath)

        if file:
            importedPresets = self.logic.importPreset(file)

            selectedPresets = self.presetWidget.execImportDialog(data=importedPresets.values())

            if selectedPresets:
                conflictPresets = []
                newPresets = []

                for presetId in selectedPresets:
                    if presetId in self.presets:
                        conflictPresets.append(presetId)
                    else:
                        newPresets.append(presetId)

                if conflictPresets:
                    conflicts = [importedPresets[presetId] for presetId in conflictPresets]
                    message = (
                        "The following presets have already been installed on your device. "
                        "Please select the presets that you would like to replace.<br/><span style='color: yellow;'>"
                        "Obs: Please be advised that certain imported presets may possess updated values while "
                        "retaining the same ID.</span>"
                    )
                    selectedConflictPresets = self.presetWidget.execConflictDialog(
                        title="Import Presets", data=conflicts, message=message
                    )

                    if selectedConflictPresets:
                        newPresets = newPresets + selectedConflictPresets

                if newPresets:
                    presetsToAdd = {key: importedPresets[key] for key in newPresets}
                    self.presets.update(presetsToAdd)
                    self.presetWidget.loadData(self.presets.values())

                    self.logic.savePresets(self.presetsFilePath, self.presets)

                slicer.util.showStatusMessage("Presets imported successfully.", 2000)

    # Fields events
    def _onPsdLibSelected(self, index):
        if self.psdLibSelector.currentData == PSDLib.MICROTOM:
            self.parametersWidget.setCurrentIndex(0)
        elif self.psdLibSelector.currentData == PSDLib.PORESPY:
            self.parametersWidget.setCurrentIndex(1)

        self._checkShowWarning()

    def _onInputSelected(self, node):
        if node is None or isinstance(node, str):
            self._changeApplyButtonState(False)
            self._changeCancelButtonState(False)

            if not self.manualOutputPrefixCheckBox.isChecked():
                self.outputPrefixLine.setText("")

            return

        # Get name first to avoid using reference node name
        nodeName = node.GetName()

        if not self.manualOutputPrefixCheckBox.isChecked():
            self.outputPrefixLine.setText(nodeName)

        if node.IsA("vtkMRMLSegmentationNode"):
            node = helpers.getSourceVolume(node)

            if node is None:
                return

        self._changeApplyButtonState(True)
        self._changeCancelButtonState(False)

    def _onReferenceSelected(self, node):
        if node is None:
            self._changeApplyButtonState(False)
            self._changeCancelButtonState(False)
            return

        self._changeApplyButtonState(True)
        self._changeCancelButtonState(False)

    def _onProcessFinished(self):
        self._changeCancelButtonState(False)
        self._changeApplyButtonState(True)

    # Others
    def _changeApplyButtonState(self, isActive):
        self.applyCancelButton.applyBtn.enabled = isActive
        self.applyCancelButton.applyBtn.blockSignals(not isActive)

    def _changeCancelButtonState(self, isActive):
        self.applyCancelButton.cancelBtn.enabled = isActive
        self.applyCancelButton.cancelBtn.blockSignals(not isActive)

    def _checkShowWarning(self):
        psdLib = self.psdLibSelector.currentData

        if self.psdParameters[psdLib].isModified():
            self.warningLabel.show()
        else:
            self.warningLabel.hide()

    def _updateParametersCurrentPreset(self, preset, updateFilds=True):
        for parameter in self.psdParameters.values():
            parameter.setCurrentPreset(preset, updateFilds)


class ImageLogPSDGenerationLogic(LTracePluginLogic):
    processFinished = qt.Signal()

    def __init__(self, parent=None, widget=None, progressBar=None):
        LTracePluginLogic.__init__(self, parent)

        self.widget = widget
        self.progressBar = progressBar
        self.cliNode = None
        self._cliNodeModifiedObserver = None

    def cleanup(self):
        if self.cliNode is not None:
            self.cancel()
            self.cliNode = None

        self.widget = None
        self.progressBar = None
        self._cliNodeModifiedObserver = None

    def cancel(self):
        if self.cliNode is not None:
            self.cliNode.Cancel()

    def apply(
        self,
        psdLib: PSDLib,
        segmentationNode,
        refNode,
        labels,
        soiNode=None,
        manualOutputPrefix=False,
        outputPrefix="",
        params=None,
        metadata=None,
    ):
        try:
            tag = Tag(str(uuid.uuid4()))

            if psdLib not in PSDLib:
                raise ValueError("PSD libray method shoud be one of these:", ", ".join([lib for lib in PSDLib]))

            if not segmentationNode:
                raise ValueError("Missing Segmentation Node.")

            if not refNode:
                raise ValueError("Missing Reference Node.")

            if not labels:
                raise ValueError("At least one label is required.")

            segmentationNode, inputVolumeNode = self._processInput(segmentationNode, labels, soiNode, refNode, tag)

            if not outputPrefix or not manualOutputPrefix:
                outputPrefix = segmentationNode.GetName()

            helpers.mergeSegments(inputVolumeNode)

            outputNodeName = "SIMULATOR_OUTPUT_TMP_NODE"
            outputVolumeNode = helpers.createTemporaryVolumeNode(
                slicer.vtkMRMLScalarVolumeNode, outputNodeName, environment=tag, hidden=True, uniqueName=False
            )

            simInfo = {
                "psdLib": psdLib.value,
                "workspace": tag.value,
                "outPrefix": outputPrefix,
                "inputNodeID": inputVolumeNode.GetID(),
                "outputNodeID": outputVolumeNode.GetID(),
                "metadata": metadata,
            }

            cliParams = {
                "psdLib": psdLib.name,
                "inputVolume": inputVolumeNode.GetID(),
                "outputVolume": outputVolumeNode.GetID(),
                "workspace": tag.value,
                "params": json.dumps(params) if params is not None else None,
            }

            # Run CLI Asynchronous
            self.cliNode = slicer.cli.run(
                slicer.modules.imagelogpsdgenerationcli, None, cliParams, wait_for_completion=False
            )
            self._cliNodeModifiedObserver = self.cliNode.AddObserver(
                "ModifiedEvent", partial(self._onCLIModified, simInfo)
            )

            # Setup progress bar
            if self.progressBar:
                self.progressBar.setCommandLineModuleNode(self.cliNode)

        except ValueError as ve:
            self.processFinished.emit()
            raise ve
        except Exception as e:
            import traceback

            traceback.print_exc()
            helpers.removeTemporaryNodes(environment=tag)
            self.processFinished.emit()

    def exportPreset(self, filePath, presets):
        try:
            presetsData = {ImageLogPSDGeneration.SETTING_KEY: {id: vars(preset) for id, preset in presets.items()}}

            with open(filePath, "w") as f:
                json.dump(presetsData, f, indent=2)
        except Exception as e:
            logging.error(repr(e))
            slicer.util.errorDisplay("An error occurred while exporting presets.", "Export Error")

    def importPreset(self, filePath):
        try:
            with open(filePath, "r") as f:
                presetsData = json.load(f)
                presetsData = presetsData.get(ImageLogPSDGeneration.SETTING_KEY, {})

            presets = {key: ImageLogPSDGenerationPreset(**value) for key, value in presetsData.items()}

            return presets
        except Exception as e:
            logging.error(repr(e))
            slicer.util.errorDisplay("An error occurred while importing presets.", "Import Error")

    def getPresets(self, filePath):
        try:
            if os.path.isfile(filePath):
                with open(filePath, "r") as f:
                    presetsData = json.load(f)
            else:
                presetsData = {ImageLogPSDGeneration.SETTING_KEY: {}}

                with open(filePath, "w") as f:
                    json.dump(presetsData, f, indent=2)

            presetsData = presetsData.get(ImageLogPSDGeneration.SETTING_KEY, {})
            presets = {id: ImageLogPSDGenerationPreset(**preset) for id, preset in presetsData.items()}

            return presets
        except Exception as e:
            logging.error(repr(e))
            slicer.util.errorDisplay("An error occurred while getting presets.", "Error")

    def savePresets(self, filePath, presets):
        try:
            presetsData = {ImageLogPSDGeneration.SETTING_KEY: {id: vars(preset) for id, preset in presets.items()}}

            with open(filePath, "w") as f:
                json.dump(presetsData, f, indent=2)
        except Exception as e:
            logging.error(repr(e))
            slicer.util.errorDisplay("An error occurred while saving presets.", "Error")

    def _onCLIModified(self, simInfo, cliNode, event):
        if self.cliNode is None:
            return

        if cliNode is None:
            self.cliNode = None
            return

        if cliNode.IsBusy():
            return

        try:
            if cliNode.GetStatusString() == "Completed":
                inputNodeID = simInfo["inputNodeID"]
                outputNodeID = simInfo["outputNodeID"]
                prefix = simInfo["outPrefix"]

                inputNode = helpers.tryGetNode(inputNodeID)
                outputNode = helpers.tryGetNode(outputNodeID)

                nodeName = f"{prefix}_PSD"
                nodeName = slicer.mrmlScene.GenerateUniqueName(nodeName)
                outputNode.SetName(nodeName)

                Metadata(outputNode)["psdLib"] = simInfo["psdLib"]

                if simInfo["metadata"]:
                    for key, value in simInfo["metadata"].items():
                        Metadata(outputNode)[key] = value

                outputNode.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)

                helpers.addNodesToScene([outputNode])
                self._setNodeHierarchy(outputNode, inputNode, simInfo["psdLib"])
        except Exception as e:
            raise e
        finally:
            logging.info("Exec CLI %s" % cliNode.GetStatusString())

            if self._cliNodeModifiedObserver is not None:
                self.cliNode.RemoveObserver(self._cliNodeModifiedObserver)
                self._cliNodeModifiedObserver = None

            del self.cliNode
            self.cliNode = None

            helpers.removeTemporaryNodes(environment=Tag(simInfo["workspace"]))

            self.processFinished.emit()

    def _setNodeHierarchy(self, node, referenceNode, dirLabel, projectDirName=None):
        folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        parentItemId = folderTree.GetSceneItemID()
        if referenceNode:
            itemTreeId = folderTree.GetItemByDataNode(referenceNode)
            parentItemId = folderTree.GetItemParent(itemTreeId)

        resultsFolderName = "PSD Results"

        resFolderId = folderTree.GetItemChildWithName(parentItemId, resultsFolderName)
        if not resFolderId:
            resFolderId = folderTree.CreateFolderItem(parentItemId, resultsFolderName)

        folderId = folderTree.GetItemChildWithName(resFolderId, dirLabel)
        if not folderId:
            folderId = folderTree.CreateFolderItem(resFolderId, dirLabel)

        folderTree.CreateItem(folderId, node)

    def _processInput(self, segmentation, labels, soiNode, refNode, tag):
        segmentationLabelMap, _ = helpers.createLabelmapInput(
            segmentationNode=segmentation,
            name=str(uuid.uuid4()),
            segments=labels,
            tag=tag,
            referenceNode=refNode,
        )

        if not math.isclose(segmentationLabelMap.GetSpacing()[0], segmentationLabelMap.GetSpacing()[2]):
            slicer.util.warningDisplay(
                "Input segmentation has non-isotropic spacing. A new resampled node will be created with nearest "
                "neighbor interpolation to have an isotropic spacing to apply the PSD algorithm."
            )

            newSpacing = min(segmentationLabelMap.GetSpacing()[0], segmentationLabelMap.GetSpacing()[2])
            sufix = str(uuid.uuid4())

            resampleLogic = CustomResampleScalarVolumeLogic(progressBar=self.progressBar)
            resampleData = ResampleScalarVolumeData(
                input=segmentationLabelMap,
                outputSuffix=sufix,
                x=newSpacing,
                y=segmentationLabelMap.GetSpacing()[1],
                z=newSpacing,
                interpolationType="Nearest Neighbor",
            )

            resampleLogic.run(resampleData, cli_wait=True)

            resampledSegmentationLabelMap = helpers.tryGetNode(f"{segmentationLabelMap.GetName()}_{sufix}")
            resampledSegmentationLabelMap.SetName(
                slicer.mrmlScene.GenerateUniqueName(f"{segmentation.GetName()}_Resampled")
            )

            helpers.removeTemporaryNodes(environment=tag)

            segmentation = resampledSegmentationLabelMap

            segmentationLabelMap, _ = helpers.createLabelmapInput(
                segmentationNode=resampledSegmentationLabelMap,
                name=str(uuid.uuid4()),
                tag=tag,
                referenceNode=refNode,
            )

            slicer.app.processEvents()

            if self.widget:
                self.widget.inputSelector.mainInput.setCurrentNode(segmentation)
                self.widget.inputSelector.soiInput.setCurrentNode(soiNode)
                self.widget.inputSelector.referenceInput.setCurrentNode(refNode)

                for i in range(self.widget.inputSelector.segmentListWidget.count):
                    self.widget.inputSelector.segmentListWidget.item(i).setCheckState(2)

        if soiNode:
            segmentationLabelMap = helpers.maskInputWithROI(segmentationLabelMap, soiNode)

        helpers.copy_subject_hierarchy_item_parent(segmentation, segmentationLabelMap)

        return segmentation, segmentationLabelMap
