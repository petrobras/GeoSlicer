import ctk
import os
import qt
import slicer
import configparser

from ltrace.slicer import ui
from ltrace.slicer.helpers import save_path
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget
from pathlib import Path
from ltrace.slicer.metadata import Metadata
from ltrace.slicer.node_attributes import NodeEnvironment

try:
    from Test.AttributeToolsTest import AttributeToolsTest
except ImportError:
    AttributeToolsTest = None


class AttributeTools(LTracePlugin):
    SETTING_KEY = "AttributeTools"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Attribute Tools"
        self.parent.categories = ["MicroCT", "Tools"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.setHelpUrl("Volumes/MoreTools/MoreTools.html#attribute-tools", NodeEnvironment.MICRO_CT)

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class AttributeToolsWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.pcrFileIsValid = False

    def setup(self):
        LTracePluginWidget.setup(self)

        self.toolSelector = qt.QComboBox()
        self.toolSelector.setObjectName("toolSelector")
        self.toolSelector.addItem("Import PCR from file")
        self.toolSelector.currentTextChanged.connect(self.onToolChanged)

        formLayout = qt.QFormLayout()
        formLayout.addRow("Tool:", self.toolSelector)
        self.layout.addLayout(formLayout)

        self.pcrImporterWidget = qt.QGroupBox()
        pcrImporterLayout = qt.QFormLayout(self.pcrImporterWidget)

        self.inputSelector = ui.hierarchyVolumeInput(
            onChange=self.onInputNodeChanged,
            hasNone=True,
            nodeTypes=["vtkMRMLScalarVolumeNode"],
        )
        self.inputSelector.setObjectName("inputSelector")
        self.inputSelector.setMRMLScene(slicer.mrmlScene)
        self.inputSelector.setToolTip("Pick a volume node to add the PCR metadata to.")
        pcrImporterLayout.addRow("Input Volume:", self.inputSelector)

        self.pcrPathLineEdit = ctk.ctkPathLineEdit()
        self.pcrPathLineEdit.setObjectName("pcrPathLineEdit")
        self.pcrPathLineEdit.filters = ctk.ctkPathLineEdit.Files
        self.pcrPathLineEdit.nameFilters = ["*.pcr"]
        self.pcrPathLineEdit.settingKey = "AttributeTools/PcrPath"
        self.pcrPathLineEdit.currentPathChanged.connect(lambda *args: self.onPcrFileChanged())
        self.pcrPathLineEdit.validInputChanged.connect(lambda *args: self.onPcrFileChanged())
        pcrImporterLayout.addRow("PCR File:", self.pcrPathLineEdit)

        self.pcrInfoLabel = qt.QLabel()
        self.pcrInfoLabel.setObjectName("pcrInfoLabel")
        pcrImporterLayout.addRow(self.pcrInfoLabel)

        self.applyButton = qt.QPushButton("Import PCR")
        self.applyButton.setObjectName("applyButton")
        self.applyButton.setProperty("class", "actionButtonBackground")
        self.applyButton.setFixedHeight(40)
        self.applyButton.clicked.connect(self.onApplyButtonClicked)
        pcrImporterLayout.addRow(self.applyButton)

        self.statusLabel = qt.QLabel("")
        self.statusLabel.setObjectName("statusLabel")
        self.statusLabel.alignment = qt.Qt.AlignRight
        pcrImporterLayout.addRow(self.statusLabel)

        self.layout.addWidget(self.pcrImporterWidget)
        self.layout.addStretch(1)

        self.onPcrFileChanged()
        self.updateApplyButtonState()

    def onToolChanged(self, toolName):
        pass

    def onInputNodeChanged(self, itemId):
        self.updateApplyButtonState()

    def onPcrFileChanged(self):
        path = self.pcrPathLineEdit.currentPath
        self.pcrInfoLabel.text = ""
        self.pcrFileIsValid = False

        if not path:
            self.pcrFileIsValid = False
            self.pcrInfoLabel.text = ""
            self.updateApplyButtonState()
            return

        if not Path(path).is_file():
            self.pcrFileIsValid = False
            self.pcrInfoLabel.text = "File does not exist."
            self.updateApplyButtonState()
            return

        try:
            _, (min_val, max_val) = pcrFromFile(Path(path))
            self.pcrInfoLabel.text = f"Valid PCR file. Min: {min_val}; Max: {max_val}"
            self.pcrFileIsValid = True
        except ValueError as e:
            self.pcrInfoLabel.text = str(e)
            self.pcrFileIsValid = False

        self.updateApplyButtonState()

    def updateApplyButtonState(self):
        nodeSelected = self.inputSelector.currentNode() is not None
        self.applyButton.enabled = nodeSelected and self.pcrFileIsValid

    def onApplyButtonClicked(self):
        node = self.inputSelector.currentNode()
        pcrPath = self.pcrPathLineEdit.currentPath

        importPcr(node, Path(pcrPath))
        self.statusLabel.text = "PCR imported successfully."
        save_path(self.pcrPathLineEdit)


def importPcr(node: slicer.vtkMRMLScalarVolumeNode, pcr_path: Path):
    try:
        pcr_content, _ = pcrFromFile(pcr_path)
    except ValueError as e:
        slicer.util.errorDisplay(str(e), windowTitle="Import PCR Error")
        return

    Metadata(node)["pcr"] = pcr_content


def pcrFromFile(pcr_path: Path):
    try:
        content = pcr_path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"Could not read file: {pcr_path}") from e

    config = configparser.ConfigParser()
    try:
        config.read_string(content)
    except configparser.Error as e:
        raise ValueError(f"Could not parse file content: {pcr_path}") from e

    try:
        min_ = config.getfloat("VolumeData", "Min")
        max_ = config.getfloat("VolumeData", "Max")
    except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
        msg = f"File {pcr_path} is missing the [VolumeData] section or valid 'Min'/'Max' keys."
        raise ValueError(msg) from None

    return content, (min_, max_)
