import importlib
import json
import os
from pathlib import Path
import re
from ltrace.slicer.helpers import save_path
from ltrace.slicer.ui import numberParam
import markdown
import logging

import ctk
from SegmentInspector import IslandsSettingsWidget, OSWatershedSettingsWidget
import qt
import slicer
from ltrace.assets_utils import get_trained_models_with_metadata, get_metadata, get_pth
from ltrace.slicer import ui, helpers, widgets
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget
from slicer.ScriptedLoadableModule import *


# $TODO: Tests PoreStats
"""
# Checks if closed source code is available
try:
    from Test.PoreStatsTest import PoreStatsTest 
except ImportError:
    PoreStatsTest = None  # tests not deployed to final version or closed source
"""


class PoreStats(LTracePlugin):
    SETTING_KEY = "PoreStats"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "PoreStats"  # TODO make this more human readable by adding spaces
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]  # replace with "Firstname Lastname (Organization)"
        self.parent.helpText = PoreStats.help()
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = ""  # replace with organization, grant and thanks.

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PoreStatsWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

        self.cliNode = None
        self.refNodeId = None
        self.filterUpdateThread = None
        self.inputsSelector = None
        self.inputSelectorMode = None
        self.imageLogMode = False
        self.deterministicPreTrainedModels = False

        self.hideWhenCreatingClassifier = []
        self.hideWhenLoadingClassifier = []

        self.process = None

    def onReload(self) -> None:
        LTracePluginWidget.onReload(self)
        importlib.reload(ui)
        importlib.reload(widgets)
        importlib.reload(helpers)

    def setup(self):
        LTracePluginWidget.setup(self)

        self.layout.addWidget(self._setupClassifierSection())
        self.layout.addWidget(self._setupInputsSection())
        self.layout.addWidget(self._setupSettingsSection())
        self.layout.addWidget(self._setupOutputSection())
        self.layout.addWidget(self._setupApplySection())

        # Add vertical spacer
        self.layout.addStretch(1)

    def _setupClassifierSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Classifier"
        formLayout = qt.QFormLayout(widget)

        self.classifierInput = qt.QComboBox()

        self.classifierInput.objectName = "Classifier Input ComboBox"

        self.classifierInput.activated.connect(self._onChangedClassifier)
        self.classifierInput.setToolTip("Select pre-trained model for segmentation")
        self.classifierInput.currentIndexChanged.connect(lambda _: self.classifierInput.setStyleSheet(""))

        self.classifierInfo = qt.QLabel()
        self.classifierInfo.setTextFormat(qt.Qt.RichText)
        self.classifierInfo.setOpenExternalLinks(True)
        self.classifierInfo.setTextInteractionFlags(qt.Qt.TextBrowserInteraction)
        self.classifierInfo.setWordWrap(True)
        self.classifierInfoGroupBox = ctk.ctkCollapsibleGroupBox()
        self.classifierInfoGroupBox.setLayout(qt.QVBoxLayout())
        self.classifierInfoGroupBox.layout().addWidget(self.classifierInfo)
        self.classifierInfoGroupBox.collapsed = True
        self.hideWhenCreatingClassifier.append(self.classifierInfoGroupBox)

        formLayout.addRow("Input model:", self.classifierInput)
        formLayout.addRow("", self.classifierInfoGroupBox)

        return widget

    def _setupInputsSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Inputs"
        formLayout = qt.QFormLayout(widget)

        self.inputDirectoryLineEdit = ctk.ctkPathLineEdit()
        self.inputDirectoryLineEdit.filters = ctk.ctkPathLineEdit.Dirs
        self.inputDirectoryLineEdit.visible = True
        self.inputDirectoryLineEdit.settingKey = "PoreStats/InputDirectory"
        self.inputDirectoryLineEdit.currentPathChanged.connect(self._savePath)
        self.inputDirectoryLineEdit.validInputChanged.connect(self._checkRequirementsForApply)

        formLayout.addRow("Input directory:", self.inputDirectoryLineEdit)

        return widget

    def _setupSettingsSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Parameters"

        formLayout = qt.QFormLayout(widget)

        self.imageSpacingLineEdit = qt.QLineEdit()
        self.imageSpacingValidator = qt.QRegExpValidator(qt.QRegExp("[+]?[0-9]*\\.?[0-9]+([eE][-+]?[0-9]+)?"))
        self.imageSpacingLineEdit.setValidator(self.imageSpacingValidator)
        self.imageSpacingLineEdit.setToolTip("Pixel size in millimeters")
        self.imageSpacingLineEdit.textEdited.connect(self._checkRequirementsForApply)

        self.methodSelector = ui.StackedSelector(text="Partitioning method:")
        self.methodSelector.addWidget(IslandsSettingsWidget(voxelSizeGetter=lambda: self._getSpacing()))
        self.methodSelector.addWidget(OSWatershedSettingsWidget(voxelSizeGetter=lambda: self._getSpacing()))
        self.methodSelector.objectName = "Methods Selector"
        self.methodSelector.selector.objectName = "Methods ComboBox"

        self.removeSpuriousCheckbox = qt.QCheckBox("Remove spurious")
        self.removeSpuriousCheckbox.toolTip = "Detect and remove spurious predictions."
        self.removeSpuriousCheckbox.checked = True
        self.removeSpuriousCheckbox.objectName = "Remove spurious CheckBox"

        self.cleanResinCheckbox = qt.QCheckBox("Clean resin")
        self.cleanResinCheckbox.toolTip = "Detect and clean bubbles and residues in pore resin."
        self.cleanResinCheckbox.checked = True
        self.cleanResinCheckbox.objectName = "Clean resin CheckBox"
        self.cleanResinCheckbox.connect("toggled(bool)", self._enableCleaningOptions)

        self.usePXCheckbox = qt.QCheckBox("Use PX")
        self.usePXCheckbox.toolTip = (
            "Combine PP and PX images for more accurate resin cleaning. If not checked, only the PP image is used."
        )
        self.usePXCheckbox.checked = True
        self.usePXCheckbox.objectName = "Use PX CheckBox"
        self.usePXCheckbox.connect("toggled(bool)", self._enableSmartRegistration)

        self.regMethodCheckbox = qt.QCheckBox("Smart registration")
        self.regMethodCheckbox.toolTip = "Method for registrating PP and PX images for pore resin cleaning. If unchecked, the images will be overlapped so that \
            each one's center will share the same location: recommended when the images seem to be naturally registered already. \
            If checked, the algorithm will decide between just centralizing the images (as in the unchecked case) or cropping their \
            rock region before: recommended when PP and PX have different dimensions or do not seem to overlap naturally."
        self.regMethodCheckbox.checked = False
        self.regMethodCheckbox.objectName = "Smart registration CheckBox"

        self.exportImagesCheckbox = qt.QCheckBox("Export images")
        self.exportImagesCheckbox.toolTip = (
            "Save PNG images of the input thin sections (PP) with the predicted instances randomly colored."
        )
        self.exportImagesCheckbox.checked = True
        self.exportImagesCheckbox.objectName = "Export images CheckBox"

        self.exportSheetsCheckbox = qt.QCheckBox("Export sheets")
        self.exportSheetsCheckbox.toolTip = "Save sheets containing the geological properties of the predicted instances and their statistics for each thin section. \
            The 'AllStats' sheets store the properties of each instance individually, while the 'GroupsStats' sheets group them by size similarity and store \
            different descriptive statistics in different pages."
        self.exportSheetsCheckbox.checked = True
        self.exportSheetsCheckbox.objectName = "Export sheets CheckBox"

        self.exportLASCheckbox = qt.QCheckBox("Export LAS")
        self.exportLASCheckbox.toolTip = (
            "Create LAS files relating depth and descriptive statistics of the geological properties of the whole well."
        )
        self.exportLASCheckbox.checked = True
        self.exportLASCheckbox.objectName = "Export LAS CheckBox"

        self.limitFragsCheckbox = qt.QCheckBox("Limit maximum number of fragments")
        self.limitFragsCheckbox.toolTip = "Define the maximum number of rock fragments to be analyzed, from largest to smallest. If not checked, all fragments are considered."
        self.limitFragsCheckbox.checked = False
        self.limitFragsCheckbox.objectName = "Limit maximum number of fragments CheckBox"
        self.limitFragsCheckbox.connect("toggled(bool)", self._enableFragsLimitation)

        self.limitFragsHBoxLayout = qt.QHBoxLayout()
        self.limitFragsHBoxLayout.addWidget(numberParam((1, 20), value=1, step=1, decimals=0))
        self._enableFragsLimitation()

        formLayout.addRow(self.exportImagesCheckbox)
        formLayout.addRow(self.exportSheetsCheckbox)
        formLayout.addRow(self.exportLASCheckbox)
        formLayout.addRow(self.removeSpuriousCheckbox)
        formLayout.addRow(self.cleanResinCheckbox)
        formLayout.addRow("", self.usePXCheckbox)
        formLayout.addRow("", self.regMethodCheckbox)
        formLayout.addRow(self.limitFragsCheckbox)
        formLayout.addRow(self.limitFragsHBoxLayout)
        formLayout.addRow(self.methodSelector)
        formLayout.addRow("Pixel size\n(mm):", self.imageSpacingLineEdit)

        return widget

    def _setupOutputSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Output"
        formLayout = qt.QFormLayout(widget)

        self.outputDirectoryLineEdit = ctk.ctkPathLineEdit()
        self.outputDirectoryLineEdit.filters = ctk.ctkPathLineEdit.Dirs
        self.outputDirectoryLineEdit.visible = True
        self.outputDirectoryLineEdit.settingKey = "PoreStats/OutputDirectory"
        self.outputDirectoryLineEdit.currentPathChanged.connect(self._savePath)
        self.outputDirectoryLineEdit.validInputChanged.connect(self._checkRequirementsForApply)

        formLayout.addRow("Output directory:", self.outputDirectoryLineEdit)

        return widget

    def _setupApplySection(self):
        widget = qt.QWidget()
        vlayout = qt.QVBoxLayout(widget)

        self.applyButton = ui.ButtonWidget(
            text="Apply", tooltip="Run segmenter on input data limited by ROI", onClick=self._onApplyClicked
        )
        self.applyButton.objectName = "Apply Button"

        self.applyButton.setStyleSheet("QPushButton {font-size: 11px; font-weight: bold; padding: 8px; margin: 0px}")
        self.applyButton.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)

        self.applyButton.enabled = False

        self.progressBar = LocalProgressBar()

        hlayout = qt.QHBoxLayout()
        hlayout.addWidget(self.applyButton)
        hlayout.setContentsMargins(0, 8, 0, 8)

        vlayout.addLayout(hlayout)
        vlayout.addWidget(self.progressBar)

        return widget

    def _enableCleaningOptions(self):
        self.usePXCheckbox.visible = self.cleanResinCheckbox.checked
        self._enableSmartRegistration()

    def _enableSmartRegistration(self):
        self.regMethodCheckbox.visible = self.usePXCheckbox.visible and self.usePXCheckbox.checked

    def _enableFragsLimitation(self):
        self.limitFragsHBoxLayout.itemAt(0).widget().visible = self.limitFragsCheckbox.checked

    def _getSpacing(self):
        if len(self.imageSpacingLineEdit.text) == 0:
            return 1
        else:
            if self.imageSpacingLineEdit.text == ".":
                return 0.0
            else:
                return float(self.imageSpacingLineEdit.text)

    """ Handlers """

    def enter(self) -> None:
        super().enter()

        # Add pretrained models
        self._addPretrainedModelsIfAvailable()
        self._onChangedClassifier()

    def _addPretrainedModelsIfAvailable(self):
        def _getNetNameFromModelName(model_name):
            return re.search(r"\(([^()]*)\)", model_name).group(1)

        env = slicer.util.selectedModule()
        envs = tuple(map(lambda x: x.value, NodeEnvironment))

        if env not in envs:
            return

        model_dirs = get_trained_models_with_metadata(env)
        for model_dir in model_dirs:
            try:
                metadata = get_metadata(model_dir)
                if (
                    metadata["is_segmentation_model"]
                    and "Pore" in metadata["title"]
                    and "Siliciclastics" not in metadata["title"]
                ):
                    title = _getNetNameFromModelName(metadata["title"])
                    self.classifierInput.addItem(title, model_dir.as_posix())
            except RuntimeError as error:
                logging.error(error)

    def _onChangedClassifier(self, selected=None):
        if self.classifierInput.currentData is None:
            return

        metadata = get_metadata(self.classifierInput.currentData)
        model_inputs = metadata["inputs"]
        model_outputs = metadata["outputs"]
        model_input_names = list(model_inputs.keys())
        model_output_names = list(model_outputs.keys())
        # temporary limitationonly taking one output
        model_output = model_outputs[model_output_names[0]]
        model_classes = model_output["class_names"]

        space = 2 * " "

        if "description" in metadata:
            model_description = "\n".join([f"**Description:**", "\n", metadata["description"], "\n"])
        else:
            model_description = ""

        model_inputs_description = [f"**Inputs ({len(model_inputs)}):**", "\n"]
        for name, description in model_inputs.items():
            model_inputs_description += [f"{space}- {name}:"]
            spatial_dims = description.get("spatial_dims")
            if spatial_dims is not None:
                model_inputs_description += [f"{2*space}- Dimensions: {spatial_dims}"]

            n_channels = description.get("n_channels", 1)
            if n_channels is not None:
                model_inputs_description += [f"{2*space}- Channels: {n_channels}"]
        model_inputs_description = "\n".join(model_inputs_description)

        model_outputs_description = [f"**Outputs ({len(model_outputs)}):**", "\n"]
        for name, description in model_outputs.items():
            is_segmentation = description.get("is_segmentation", True)
            if is_segmentation and len(model_outputs) == 1:
                name = "Segmentation"
            model_outputs_description += [
                f"{space}- {name}:",
            ]
            spatial_dims = description.get("spatial_dims")
            if spatial_dims is not None:
                model_outputs_description += [f"{2*space}- Dimensions: {spatial_dims}"]

            if is_segmentation:
                models_classes = description.get("model_classes", 1)
                if models_classes is not None:
                    model_outputs_description += [f"{2*space}- Classes:"]
                    for model_class in model_classes:
                        model_outputs_description += [f"{4*space}- {model_class}"]
            else:
                n_channels = description.get("n_channels", 1)
                if n_channels is not None:
                    model_outputs_description += [f"{2*space}- Channels: {n_channels}"]
        model_outputs_description = "\n".join(model_outputs_description)

        msg = "\n\n".join(
            [
                model_description,
                model_inputs_description,
                model_outputs_description,
            ]
        )

        html = markdown.markdown(msg)
        self.classifierInfo.setText(html)
        self.classifierInfo.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Fixed)
        summary = f"Model info: {len(model_classes)} segments"
        self.classifierInfoGroupBox.setTitle(summary)

    def _savePath(self):
        save_path(self.inputDirectoryLineEdit)
        save_path(self.outputDirectoryLineEdit)

    def _checkRequirementsForApply(self):
        if self.methodSelector.currentWidget() == None:
            return

        inputDirectoryProvided = len(self.inputDirectoryLineEdit.currentPath) > 0
        outputDirectoryProvided = len(self.outputDirectoryLineEdit.currentPath) > 0
        spacingTextExists = len(self.imageSpacingLineEdit.text) > 0
        processIsRunning = self.process is not None and self.process.poll() is None

        if self.cliNode is None or not self.cliNode.IsBusy():
            self.applyButton.enabled = (
                inputDirectoryProvided and outputDirectoryProvided and spacingTextExists and not processIsRunning
            )
        else:
            self.applyButton.enabled = False

    def _onScriptFinished(self, caller, event):
        if caller is None:
            return

        if caller.GetStatusString() == "Completed":
            slicer.util.infoDisplay("Batch porosity analysis completed.")
        elif caller.GetStatusString() == "Completed with errors":
            slicer.util.errorDisplay(
                f"Batch porosity analysis failed:\n\n{caller.GetErrorText().strip().splitlines()[-1]}"
            )

        self._checkRequirementsForApply()

        if not caller.IsBusy():
            print("ExecCmd CLI %s" % caller.GetStatusString())

    def _validateDirs(self, inputDir, outputDir):
        if not os.path.exists(inputDir):
            slicer.util.errorDisplay("Input directory does not exist.")
            return False

        checkpointPath = os.path.join(outputDir, "checkpoint.txt")
        if os.path.exists(checkpointPath):
            resumeMessageBox = qt.QMessageBox()
            resumeMessageBox.setWindowTitle("Resume execution")
            resumeMessageBox.setText(
                "A previous unfinished execution was detected on the selected output directory. What do you want to do?"
            )

            resumeButton = resumeMessageBox.addButton("Resume", qt.QMessageBox.ActionRole)
            restartButton = resumeMessageBox.addButton("Restart", qt.QMessageBox.ActionRole)
            cancelButton = resumeMessageBox.addButton("Cancel", qt.QMessageBox.ActionRole)

            resumeMessageBox.exec_()
            if resumeMessageBox.clickedButton() == resumeButton:
                return True
            elif resumeMessageBox.clickedButton() == restartButton:
                os.remove(checkpointPath)
                return True
            elif resumeMessageBox.clickedButton() == cancelButton:
                return False

        elif os.path.exists(outputDir) and bool(os.listdir(outputDir)):
            return slicer.util.confirmYesNoDisplay("The selected output directory is not empty. Proceed?")

        return True

    def _onApplyClicked(self):
        def _getSegCLIPath(model_name):
            if "bayes" in model_name.lower():
                cliModule = slicer.modules.bayesianinferencecli
            else:
                cliModule = slicer.modules.monaimodelscli
            return cliModule.path

        def _getModelFilePath(model_path):
            return str(model_path if os.path.isfile(model_path) else get_pth(model_path))

        inputDir = self.inputDirectoryLineEdit.currentPath
        outputDir = self.outputDirectoryLineEdit.currentPath
        if not self._validateDirs(inputDir, outputDir):
            return

        try:
            cliConf = dict(
                inputDir=inputDir,
                outputDir=outputDir,
                params=json.dumps(
                    dict(
                        algorithm=self.methodSelector.selector.currentText.split()[-1].lower(),
                        pixelSize=str(self._getSpacing()),
                        minSize=str(self.methodSelector.currentWidget().sizeFilterThreshold.value),
                        usePx="all" if self.usePXCheckbox.checked else "none",
                        regMethod="auto" if self.regMethodCheckbox.checked else "centralized",
                        maxFrags="all"
                        if not self.limitFragsCheckbox.checked
                        else int(self.limitFragsHBoxLayout.itemAt(0).widget().value),
                    )
                ),
                flags=json.dumps(
                    dict(
                        keepSpurious=not self.removeSpuriousCheckbox.checked,
                        keepResidues=not self.cleanResinCheckbox.checked,
                        noImages=not self.exportImagesCheckbox.checked,
                        noSheets=not self.exportSheetsCheckbox.checked,
                        noLAS=not self.exportLASCheckbox.checked,
                    )
                ),
                poreModel=_getModelFilePath(self.classifierInput.currentData),
                segCLI=_getSegCLIPath(self.classifierInput.currentText),
                inspectorCLI=slicer.modules.segmentinspectorcli.path,
            )
            if hasattr(self.methodSelector.currentWidget(), "smoothFactor"):
                cliConf.update(
                    dict(
                        sigma=str(self.methodSelector.currentWidget().smoothFactor.value),
                        minDistance=str(self.methodSelector.currentWidget().minimumDistance.value),
                    )
                )

            self.cliNode = slicer.cli.run(slicer.modules.porestatscli, None, cliConf, wait_for_completion=False)
            self.cliNode.AddObserver("ModifiedEvent", self._onScriptFinished)
            self.progressBar.setCommandLineModuleNode(self.cliNode)
        except Exception as e:
            slicer.util.errorDisplay(f"Failed to complete execution: {e}")
            self._checkRequirementsForApply()
            raise
