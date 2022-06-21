import os
import qt
import ctk
import slicer
import re
import numpy as np
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer import helpers
from ltrace.slicer.widget.help_button import HelpButton
from collections import OrderedDict
from pathlib import Path
from Export import ExportLogic, Callback
from NetCDFExport import exportNetcdf

# Checks if closed source code is available
try:
    from Test.MicroCTExportTest import MicroCTExportTest
except ImportError:
    MicroCTExportTest = None


class MicroCTExport(LTracePlugin):
    SETTING_KEY = "MicroCTExport"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    FORMAT_RAW = "RAW"
    FORMAT_TIF = "TIF"
    FORMAT_NC = "NetCDF"

    FORMAT_CSV = "CSV"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Micro CT Export"
        self.parent.categories = ["Micro CT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = MicroCTExport.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class MicroCTExportWidget(LTracePluginWidget):
    EXPORTABLE_TYPES = (
        slicer.vtkMRMLLabelMapVolumeNode,
        slicer.vtkMRMLSegmentationNode,
        slicer.vtkMRMLScalarVolumeNode,
        slicer.vtkMRMLTableNode,
    )

    OUTPUT_DIR = "outputDir"
    FORMAT = "format"

    HELP = {
        "BIN": "**BIN** is an 8-bit binary image, where one represents the pore and zero represents the solid. A pore segment should be selected.",
        "BIW": "**BIW** is an 8-bit binary image, where one represents the solid and zero represents the pore. A solid segment should be selected.",
        "MANGO": "**MANGO** is an 8-bit image, where zero and one are pore and 102 and 103 are solid. Values between one and 102 are distributed in the image linearly and inversely proportional to the porosity of the sample.",
        "BASINS": """**BASINS** contains the following segments:

- 1: Pore
- 2: Quartz
- 3: Microporosity
- 4: Calcite
- 5: High attenuation coefficient
""",
        "CT": "**CT** is a 16-bit image with integer values similar to the original image.",
        "CT filtered": "**CT filtered** is a 16-bit image with integer values. It is the result of cropping and filtering the original image (CT).",
        "PSD": "**PSD** is a 16-bit image with integer values that represent the maximum diameter sphere that contains the point and remains completely internal to the segmented porous medium.",
        "MICP": "**MICP** is a 16-bit image with integer values representing the maximum diameter sphere that reached this point from one of the edges of the segmented porous medium.",
        "POR": "**POR** is a 32-bit image with float values representing the point-to-point porosity of the sample, between 0 and 1.",
        "PHI": "**PHI** should be a scalar volume.",
        "LABELS": "**LABELS** should be a label map volume or segmentation.",
        "FLOAT": "**FLOAT** is a 32-bit image with generic float values, which can represent a pressure field or the velocity value in a given direction, point by point in the network.",
        "KABS": "**KABS** is a 64-bit float image with absolute permeability values.",
        "Table (CSV)": """Select a table node to export. The table will be exported as a CSV file with the same name as the table node. The specified image name will be ignored.""",
        "Image name": """Select the name of the exported image. The name will be used as the base name for the exported files.

- For **RAW** and **TIF** formats, the image name should be in the format "WELL_SAMPLE_STATE_TYPE". The files will be exported in the format "WELL_SAMPLE_STATE_TYPE_TYPEOFIMAGE_NX_NY_NZ_RESOLUTION".
- For **NetCDF**, the file name will be the same as the image name. For example, if the image name is "Image", the exported file will be "Image.nc".
""",
        "Image format": """Select the format of the exported images. The options are:

- **RAW**: raw binary files. Supports scalar, labelmap and segmentation volumes. Will export a separate file for each volume with standard nomenclature.
- **TIF**: TIFF files. Supports scalar volumes only. Will export a separate file for each volume with standard nomenclature.
- **NetCDF**: NetCDF files. Supports scalar, labelmap and segmentation volumes. Will export a single .nc file with all volumes.""",
    }

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = MicroCTExportLogic()

    def _addRow(self, name, widget):
        row = self.gridLayout.rowCount()
        if name:
            self.gridLayout.addWidget(qt.QLabel(name + ":"), row, 0)
        self.gridLayout.addWidget(widget, row, 1)
        helpMsg = self.HELP.get(name)
        if helpMsg:
            self.gridLayout.addWidget(HelpButton(helpMsg), row, 2)

    def _addSpace(self):
        row = self.gridLayout.rowCount()
        self.gridLayout.addWidget(qt.QLabel(), row, 0)

    def setup(self):
        LTracePluginWidget.setup(self)

        self.gridLayout = qt.QGridLayout()
        self.layout.addLayout(self.gridLayout)

        self.formatComboBox = qt.QComboBox()
        self.formatComboBox.addItems([MicroCTExport.FORMAT_RAW, MicroCTExport.FORMAT_TIF, MicroCTExport.FORMAT_NC])
        self.formatComboBox.currentIndexChanged.connect(self._onFormatChanged)
        self._addRow("Image format", self.formatComboBox)
        self._addSpace()

        segTypes = ["vtkMRMLSegmentationNode", "vtkMRMLLabelMapVolumeNode"]
        scalarTypes = ["vtkMRMLScalarVolumeNode"]

        self.nodeSelectors = OrderedDict(
            {
                "CT": hierarchyVolumeInput(hasNone=True, nodeTypes=scalarTypes),
                "CT filtered": hierarchyVolumeInput(hasNone=True, nodeTypes=scalarTypes),
                "FLOAT": hierarchyVolumeInput(hasNone=True, nodeTypes=scalarTypes),
                "BIN": hierarchyVolumeInput(hasNone=True, nodeTypes=segTypes, showSegments=True),
                "BIW": hierarchyVolumeInput(hasNone=True, nodeTypes=segTypes, showSegments=True),
                "MANGO": hierarchyVolumeInput(hasNone=True, nodeTypes=scalarTypes),
                "BASINS": hierarchyVolumeInput(hasNone=True, nodeTypes=segTypes, showSegments=True),
                "LABELS": hierarchyVolumeInput(hasNone=True, nodeTypes=segTypes, showSegments=True),
                "PSD": hierarchyVolumeInput(hasNone=True, nodeTypes=scalarTypes),
                "MICP": hierarchyVolumeInput(hasNone=True, nodeTypes=scalarTypes),
                "POR": hierarchyVolumeInput(hasNone=True, nodeTypes=scalarTypes),
                "PHI": hierarchyVolumeInput(hasNone=True, nodeTypes=scalarTypes),
                "KABS": hierarchyVolumeInput(hasNone=True, nodeTypes=scalarTypes),
            }
        )

        for name, selector in self.nodeSelectors.items():
            # Show "None" instead of "Select subject hierarchy item"
            selector.clearSelection()
            selector.currentItemChanged.connect(self._onNodeChanged)
            self._addRow(name, selector)

        self.tableSelector = hierarchyVolumeInput(hasNone=True, nodeTypes=["vtkMRMLTableNode"])
        self.tableSelector.setToolTip("Select table (optional)")
        self.tableSelector.clearSelection()
        self.tableSelector.currentItemChanged.connect(self._onNodeChanged)

        self._addSpace()
        self._addRow("Table (CSV)", self.tableSelector)
        self._addSpace()

        self.imageNameLineEdit = qt.QLineEdit()
        self.imageNameLineEdit.textChanged.connect(self._onImageNameChanged)

        self._addRow("Image name", self.imageNameLineEdit)

        self.warningLabel = qt.QLabel("Warning: image name does not follow the format WELL_SAMPLE_STATE_TYPE")
        color = "yellow" if helpers.themeIsDark() else "#575700"
        self.warningLabel.setStyleSheet(f"color: {color}")
        self.warningLabel.visible = False
        self._addRow(None, self.warningLabel)

        self.exportDirButton = ctk.ctkDirectoryButton()
        self.exportDirButton.directoryChanged.connect(self._updateInterface)
        self._addRow("Export directory", self.exportDirButton)
        self._addSpace()

        self.progressBar = qt.QProgressBar()
        self.progressBar.visible = False
        self.layout.addWidget(self.progressBar)
        self.callback = Callback(on_update=self._onProgress)

        self.statusLabel = qt.QLabel()
        self.layout.addWidget(self.statusLabel)

        self.exportButton = qt.QPushButton("Export")
        self.exportButton.setFixedHeight(40)
        self.exportButton.enabled = False
        self.exportButton.clicked.connect(self._onExportButtonClicked)

        self.layout.addWidget(self.exportButton)
        self.layout.addStretch(1)

        self._loadSettings()
        self._setSegEnabled(self.formatComboBox.currentText != MicroCTExport.FORMAT_TIF)

    def _loadSettings(self):
        outputDir = MicroCTExport.get_setting(self.OUTPUT_DIR, default="")
        if outputDir:
            self.exportDirButton.directory = outputDir

        format_ = MicroCTExport.get_setting(self.FORMAT, default=MicroCTExport.FORMAT_RAW)
        self.formatComboBox.setCurrentText(format_)

    def _saveSettings(self):
        MicroCTExport.set_setting(self.OUTPUT_DIR, self.exportDirButton.directory)
        MicroCTExport.set_setting(self.FORMAT, self.formatComboBox.currentText)

    def _imageDict(self):
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        return {
            name: selector.currentItem()
            for name, selector in self.nodeSelectors.items()
            if selector.enabled and (selector.currentNode() or sh.GetItemAttribute(selector.currentItem(), "segmentID"))
        }

    def _updateInterface(self):
        imageDict = self._imageDict()
        ready = self.logic.readyToExport(
            imageDict, self.tableSelector.currentNode(), self.exportDirButton.directory, self.imageNameLineEdit.text
        )
        showWarning = self.logic.shouldShowWarning(
            imageDict, self.formatComboBox.currentText, self.imageNameLineEdit.text
        )
        self.exportButton.enabled = ready
        self.warningLabel.visible = showWarning

    def _setSegEnabled(self, enabled):
        for name, selector in self.nodeSelectors.items():
            if name in self.logic.SEGMENTATION_TYPES:
                selector.enabled = enabled
                selector.setToolTip(
                    f"Select {name} image (optional)" if enabled else "Segmentations are not supported for TIFF images"
                )
            else:
                selector.setToolTip(f"Select {name} image (optional)")

    def _onNodeChanged(self, _):
        self._updateImageName()

    def _onFormatChanged(self, _):
        self._updateImageName()
        self._setSegEnabled(self.formatComboBox.currentText != MicroCTExport.FORMAT_TIF)

    def _onImageNameChanged(self, _):
        self.logic.userDefinedImageName(self.imageNameLineEdit.text)
        self._updateInterface()

    def _updateImageName(self):
        self.logic.updateImageName(self.formatComboBox.currentText, self._imageDict(), self.imageNameLineEdit)
        self._updateInterface()

    def _onProgress(self, message, progress):
        self.progressBar.value = progress
        self.statusLabel.text = message
        slicer.app.processEvents()

    def _onExportButtonClicked(self):
        self.progressBar.visible = True
        try:
            self.logic.export(
                imageFormat=self.formatComboBox.currentText,
                imageDict=self._imageDict(),
                tableNode=self.tableSelector.currentNode(),
                outputDir=self.exportDirButton.directory,
                imageName=self.imageNameLineEdit.text,
                callback=self.callback,
            )
        except Exception as e:
            self.statusLabel.text = f"Error: {e}"
            raise
        self._saveSettings()


class MicroCTExportLogic(LTracePluginLogic):
    TYPE_TO_NC_NAME = {
        "CT": "microtom",
        "CT filtered": "microtom_filtered",
        "FLOAT": "float",
        "BIN": "bin",
        "BIW": "biw",
        "MANGO": "mango",
        "BASINS": "basins",
        "LABELS": "labels",
        "PSD": "psd",
        "MICP": "micp",
        "POR": "porosity",
        "PHI": "phi",
        "KABS": "kabs",
    }

    TYPE_TO_DTYPE = {
        "CT": np.uint16,
        "CT filtered": np.uint16,
        "FLOAT": np.float32,
        "BIN": np.uint8,
        "BIW": np.uint8,
        "MANGO": np.uint8,
        "BASINS": np.uint8,
        "LABELS": np.uint8,
        "PSD": np.uint16,
        "MICP": np.uint16,
        "POR": np.float32,
        "PHI": np.float32,
        "KABS": np.float64,
    }

    SEGMENTATION_TYPES = {"BIN", "BIW", "BASINS", "LABELS"}

    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.suggestImageName = True

    def export(self, imageFormat, imageDict, tableNode, outputDir, imageName, callback):
        if tableNode:
            callback.on_update("Exporting table…", 0)
            self._exportTable(tableNode, outputDir, "CSV")

        imageDict = self._convertToNodes(imageDict)

        if imageDict:
            if imageFormat == MicroCTExport.FORMAT_NC:
                path = (Path(outputDir) / imageName).with_suffix(".nc")
                images = []
                names = []
                dtypes = []
                for type_, image in imageDict.items():
                    if type_ == "BASINS":
                        isSegmentation = isinstance(image, slicer.vtkMRMLSegmentationNode)
                        image = self._standardize_basins(image)
                        if isSegmentation:
                            # Convert back to segmentation
                            segmentation = helpers.createTemporaryVolumeNode(
                                slicer.vtkMRMLSegmentationNode, "tmp-seg-basins"
                            )
                            helpers.updateSegmentationFromLabelMap(segmentation, image, includeEmptySegments=True)
                            helpers.setSourceVolume(segmentation, helpers.getSourceVolume(image))
                            image = segmentation

                    images.append(image)
                    names.append(self.TYPE_TO_NC_NAME[type_])
                    dtypes.append(self.TYPE_TO_DTYPE[type_])

                exportNetcdf(path, images, nodeNames=names, nodeDtypes=dtypes, callback=callback)
            else:
                for i, (type_, image) in enumerate(imageDict.items()):
                    callback.on_update(f"Exporting {type_} image…", i * 100 / len(imageDict))
                    dtype = self.TYPE_TO_DTYPE[type_]
                    self._exportImage(image, imageName, type_, dtype, outputDir, imageFormat)

        helpers.removeTemporaryNodes()
        callback.on_update("Export complete", 100)

    def updateImageName(self, imageFormat, imageDict, imageNameLineEdit):
        if not self.suggestImageName:
            return

        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        item = next((value for value in imageDict.values() if value), None)
        if imageFormat == MicroCTExport.FORMAT_NC:
            name = sh.GetItemName(item) + ".nc" if item else ""
        else:
            name = self._baseName(sh.GetItemName(item)) if item else ""

        with helpers.BlockSignals(imageNameLineEdit):
            imageNameLineEdit.setText(name)

    def userDefinedImageName(self, imageName):
        self.suggestImageName = not imageName

    @staticmethod
    def readyToExport(imageDict, tableNode, outputDir, imageName):
        validDir = Path(outputDir).is_dir()
        validImages = imageName and any(imageDict.values())
        return (tableNode or validImages) and validDir

    @staticmethod
    def shouldShowWarning(imageDict, imageFormat, imageName):
        readyToExportImages = imageName and any(imageDict.values())
        relevantFormat = imageFormat != MicroCTExport.FORMAT_NC
        if readyToExportImages and relevantFormat:
            pattern = re.compile(r"^([a-zA-Z0-9]+_){3}[a-zA-Z0-9]+$")
            matchesPattern = pattern.match(imageName)
            return not matchesPattern
        return False

    @staticmethod
    def _baseName(name):
        pattern = re.compile(r"(.*)(_[A-Z]+_\d+_\d+_\d+_\d+nm)$")
        return pattern.match(name).group(1) if pattern.match(name) else name

    @staticmethod
    def _standardize_basins(image) -> slicer.vtkMRMLLabelMapVolumeNode:
        if isinstance(image, slicer.vtkMRMLSegmentationNode):
            labelMap = helpers.createTemporaryVolumeNode(slicer.vtkMRMLLabelMapVolumeNode, "tmp-basins")
            slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(
                image, labelMap, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY
            )
            colorNode = labelMap.GetDisplayNode().GetColorNode()
        else:
            assert isinstance(image, slicer.vtkMRMLLabelMapVolumeNode)
            colorNode = image.GetDisplayNode().GetColorNode()
            labelMap = helpers.createTemporaryVolumeNode(slicer.vtkMRMLLabelMapVolumeNode, "tmp-basins", content=image)
            labelMap.GetDisplayNode().SetAndObserveColorNodeID(colorNode.GetID())

        helpers.setSourceVolume(labelMap, helpers.getSourceVolume(image))

        correctColorOrder = ["por", "quartz", "micro", "cal", "high"]
        correctionMap = {}
        unknownLabels = []

        # Get label names
        for i in range(1, colorNode.GetNumberOfColors()):
            label = colorNode.GetColorName(i)
            found = False
            for j, prefix in enumerate(correctColorOrder, start=1):
                if label.lower().startswith(prefix):
                    found = True
                    if i != j:
                        correctionMap[i] = j
                    break
            if not found:
                unknownLabels.append(label)

        if unknownLabels:
            # slicer.util.warningDisplay(
            print(
                f"Unsupported label names found in BASINS image: {', '.join(unknownLabels)}.\n"
                "Image will be exported as-is.\n\n"
                "The following label names are supported in a BASINS image: Pore, Quartz, Microporosity, Calcite, High attenuation coefficient."
            )
            return labelMap

        if not correctionMap:
            return labelMap

        array = slicer.util.arrayFromVolume(labelMap)
        newArray = array.copy()
        for from_, to in correctionMap.items():
            newArray[array == from_] = to
        slicer.util.updateVolumeFromArray(labelMap, newArray)
        colorNode = helpers.getColorMapFromTerminology("tmp-basins-colors", 2, helpers.getTerminologyIndices("BASINS"))
        labelMap.GetDisplayNode().SetAndObserveColorNodeID(colorNode.GetID())
        return labelMap

    @staticmethod
    def _convertToNodes(imageDict):
        nodeDict = {}
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        for type_, itemId in imageDict.items():
            node = sh.GetItemDataNode(itemId)
            if node:
                nodeDict[type_] = node
                continue
            segmentId = sh.GetItemAttribute(itemId, "segmentID")
            parent = sh.GetItemDataNode(sh.GetItemParent(itemId))
            if segmentId and isinstance(parent, slicer.vtkMRMLSegmentationNode):
                segmentNode = helpers.createTemporaryVolumeNode(slicer.vtkMRMLSegmentationNode, "tmp-seg")
                segmentation = segmentNode.GetSegmentation()
                segmentation.CopySegmentFromSegmentation(parent.GetSegmentation(), segmentId)
                helpers.setSourceVolume(segmentNode, helpers.getSourceVolume(parent))
                nodeDict[type_] = segmentNode
        return nodeDict

    def _exportImage(self, image, imageName, imageType, imageDtype, outputDir, imageFormat):
        logic = ExportLogic()
        nodeDir = Path(outputDir)

        if imageType == "BASINS":
            labelMap = self._standardize_basins(image)
            image = labelMap
        elif isinstance(image, slicer.vtkMRMLSegmentationNode):
            labelMap = helpers.createTemporaryVolumeNode(slicer.vtkMRMLLabelMapVolumeNode, "tmp-label")
            slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(
                image, labelMap, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY
            )
            image = labelMap

        if isinstance(image, slicer.vtkMRMLLabelMapVolumeNode) and imageType in self.SEGMENTATION_TYPES:
            format_ = {
                MicroCTExport.FORMAT_RAW: ExportLogic.LABEL_MAP_FORMAT_RAW,
            }[imageFormat]
            logic.exportLabelMap(image, outputDir, nodeDir, format_, imageName, imageType, imageDtype)
        elif isinstance(image, slicer.vtkMRMLScalarVolumeNode):
            format_ = {
                MicroCTExport.FORMAT_RAW: ExportLogic.SCALAR_VOLUME_FORMAT_RAW,
                MicroCTExport.FORMAT_TIF: ExportLogic.SCALAR_VOLUME_FORMAT_TIF,
            }[imageFormat]
            logic.exportScalarVolume(image, outputDir, nodeDir, format_, imageName, imageType, imageDtype)

    def _exportTable(self, table, outputDir, tableFormat):
        logic = ExportLogic()
        nodeDir = Path(outputDir)
        format_ = {
            MicroCTExport.FORMAT_CSV: ExportLogic.TABLE_FORMAT_CSV,
        }[tableFormat]
        logic.exportTable(table, outputDir, nodeDir, format_)
