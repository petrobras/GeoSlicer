from builtins import breakpoint
import os
import ctk
import qt
import slicer
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, is_tensorflow_gpu_enabled
from ltrace.slicer import helpers
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from pathlib import Path


class PlugNet(LTracePlugin):
    SETTING_KEY = "PlugNet"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Upscale Plug To Core"
        self.parent.categories = ["Upscaling"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = PlugNet.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PlugNetTrainWidget(qt.QWidget):
    def __init__(self, logic, parent=None):
        super().__init__(parent)

        self.logic = logic
        self.inputSelector = ctk.ctkPathLineEdit()
        self.inputSelector.filters = ctk.ctkPathLineEdit.Files | ctk.ctkPathLineEdit.Readable
        self.inputSelector.nameFilters = ("HDF5 (*.h5)",)
        self.inputSelector.settingKey = "PlugNet/TrainInput"

        self.outputSelector = ctk.ctkPathLineEdit()
        self.outputSelector.filters = ctk.ctkPathLineEdit.Files | ctk.ctkPathLineEdit.Writable
        self.outputSelector.nameFilters = ("TensorFlow SavedModel (*)",)
        self.outputSelector.settingKey = "PlugNet/TrainOutput"

        self.progressBar = LocalProgressBar()

        self.trainButton = qt.QPushButton("Train")
        self.trainButton.setFixedHeight(40)
        self.trainButton.enabled = True

        layout = qt.QFormLayout(self)
        layout.addRow("Input training data:", self.inputSelector)
        layout.addRow("Output model:", self.outputSelector)
        layout.addRow(self.progressBar)
        layout.addRow(self.trainButton)

        self.trainButton.clicked.connect(self.onTrainClicked)

    def onTrainClicked(self):
        helpers.save_path(self.inputSelector)
        helpers.save_path(self.outputSelector)
        cliNode = self.logic.train(self.inputSelector.currentPath, self.outputSelector.currentPath)
        self.progressBar.setCommandLineModuleNode(cliNode)


class PlugNetPredictWidget(qt.QWidget):
    def __init__(self, logic, parent=None):
        super().__init__(parent)

        self.logic = logic

        self.modelSelector = ctk.ctkPathLineEdit()
        self.modelSelector.filters = ctk.ctkPathLineEdit.Dirs
        self.modelSelector.settingKey = "PlugNet/PredictModel"

        self.coreDirSelector = ctk.ctkPathLineEdit()
        self.coreDirSelector.filters = ctk.ctkPathLineEdit.Dirs
        self.coreDirSelector.settingKey = "PlugNet/PredictCoreDir"

        self.outputNameEdit = qt.QLineEdit()

        self.progressBar = LocalProgressBar()

        self.predictButton = qt.QPushButton("Upscale")
        self.predictButton.setFixedHeight(40)
        self.predictButton.enabled = True

        layout = qt.QFormLayout(self)
        layout.addRow("Trained model:", self.modelSelector)
        layout.addRow("Core directory:", self.coreDirSelector)
        layout.addRow("Output name:", self.outputNameEdit)
        layout.addRow(self.progressBar)
        layout.addRow(self.predictButton)

        self.predictButton.clicked.connect(self.onUpscaleClicked)

    def onUpscaleClicked(self):
        helpers.save_path(self.modelSelector)
        helpers.save_path(self.coreDirSelector)
        cliNode = self.logic.predict(
            self.modelSelector.currentPath,
            self.coreDirSelector.currentPath,
            self.outputNameEdit.text,
        )
        self.progressBar.setCommandLineModuleNode(cliNode)


class PlugNetWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = PlugNetLogic()

    def setup(self):
        LTracePluginWidget.setup(self)

        mainTab = qt.QTabWidget()
        trainWidget = PlugNetTrainWidget(self.logic)
        predictWidget = PlugNetPredictWidget(self.logic)
        lasWidget = slicer.modules.upscaletomotolas.createNewWidgetRepresentation()
        mainTab.addTab(trainWidget, "Train")
        mainTab.addTab(predictWidget, "Upscale")
        mainTab.addTab(lasWidget, "LAS")

        self.layout.addWidget(mainTab)


class PlugNetLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def train(self, inputPath: str, outputPath: str):
        params = {"input": inputPath, "output": outputPath, "gpuEnabled": is_tensorflow_gpu_enabled()}
        cliNode = slicer.cli.run(slicer.modules.plugnettraincli, None, params, wait_for_completion=False)
        return cliNode

    def predict(self, modelPath: str, coreDirPath: str, outputName: str):
        table = slicer.vtkMRMLTableNode.__name__
        self._outputTable = slicer.mrmlScene.AddNewNodeByClass(table, outputName)

        params = {
            "model": modelPath,
            "coreDir": coreDirPath,
            "outputTable": self._outputTable.GetID(),
            "gpuEnabled": is_tensorflow_gpu_enabled(),
        }

        cliNode = slicer.cli.run(slicer.modules.plugnetpredictcli, None, params, wait_for_completion=False)
        cliNode.AddObserver("ModifiedEvent", lambda c, e: self._onPredictCliEvent(c, e))

        return cliNode

    def _onPredictCliEvent(self, caller, _):
        status = caller.GetStatusString()
        if status == "Completed":
            helpers.autoDetectColumnType(self._outputTable)
            self._outputTable.SetColumnUnitLabel("DEPTH", "mm")
