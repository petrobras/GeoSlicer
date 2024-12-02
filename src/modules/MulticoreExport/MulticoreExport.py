import logging
import os
from pathlib import Path

import ctk
import cv2
import numpy as np
import qt
import slicer
import vtk
from MulticoreExportLib import MulticoreCSV
from ltrace.slicer import export
from ltrace.slicer.helpers import getNodeDataPath, checkUniqueNames
from ltrace.slicer_utils import LTracePlugin, LTracePluginLogic, LTracePluginWidget
from ltrace.transforms import getRoundedInteger, transformPoints
from ltrace.units import global_unit_registry as ureg
from ltrace.utils.report_builder import ReportBuilder


class MulticoreExport(LTracePlugin):
    SETTING_KEY = "MulticoreExport"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    FORMAT_MATRIX_CSV = "CSV (matrix format)"
    FORMAT_TECHLOG_CSV = "CSV (Techlog format)"
    FORMAT_PNG = "PNG"
    FORMAT_TIF = "TIF"
    FORMAT_SUMMARY = "Summary"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Multicore Export"
        self.parent.categories = ["Core", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = MulticoreExport.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class MulticoreExportWidget(LTracePluginWidget):
    EXPORT_DIR = "exportDir"
    IGNORE_DIR_STRUCTURE = "ignoreDirStructure"

    EXPORTABLE_TYPES = (slicer.vtkMRMLScalarVolumeNode,)

    def __init__(self, widgetName):
        super(MulticoreExportWidget, self).__init__(widgetName)
        self.cancel = False

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = MultiCoreExportLogic()

        self.subjectHierarchyTreeView = slicer.qMRMLSubjectHierarchyTreeView()
        self.subjectHierarchyTreeView.setMRMLScene(slicer.app.mrmlScene())
        self.subjectHierarchyTreeView.header().setVisible(False)
        for i in range(2, 6):
            self.subjectHierarchyTreeView.hideColumn(i)
        self.subjectHierarchyTreeView.setEditMenuActionVisible(False)
        self.subjectHierarchyTreeView.setFocusPolicy(qt.Qt.NoFocus)

        self.formatComboBox = qt.QComboBox()
        self.formatComboBox.addItem(MulticoreExport.FORMAT_SUMMARY)
        self.formatComboBox.addItem(MulticoreExport.FORMAT_MATRIX_CSV)
        self.formatComboBox.addItem(MulticoreExport.FORMAT_TECHLOG_CSV)
        self.formatComboBox.addItem(MulticoreExport.FORMAT_PNG)
        self.formatComboBox.addItem(MulticoreExport.FORMAT_TIF)
        self.formatComboBox.currentIndexChanged.connect(self._updateNodesAndExportButton)

        self.ignoreDirStructureCheckbox = qt.QCheckBox()
        self.ignoreDirStructureCheckbox.checked = (
            MulticoreExport.get_setting(self.IGNORE_DIR_STRUCTURE, "False") == "True"
        )
        self.ignoreDirStructureCheckbox.setToolTip(
            "Export all data ignoring the directory structure. Only one node with the same name and type will be exported."
        )

        self.directorySelector = ctk.ctkDirectoryButton()
        self.directorySelector.setMaximumWidth(374)
        self.directorySelector.caption = "Export directory"
        self.directorySelector.directory = MulticoreExport.get_setting(
            self.EXPORT_DIR, Path(slicer.mrmlScene.GetRootDirectory()).parent
        )

        self.progressBar = qt.QProgressBar()
        self.progressBar.setValue(0)
        self.progressBar.hide()

        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.hide()

        progressLayout = qt.QHBoxLayout()
        progressLayout.addWidget(self.progressBar)
        progressLayout.addWidget(self.cancelButton)

        self.exportButton = qt.QPushButton("Export")
        self.exportButton.setFixedHeight(40)
        self.exportButton.enabled = False

        self.exportButton.clicked.connect(self.onExportClicked)
        self.cancelButton.clicked.connect(self.onCancelClicked)
        self.subjectHierarchyTreeView.currentItemChanged.connect(self.onSelectionChanged)

        formLayout = qt.QFormLayout()
        formLayout.addRow(self.subjectHierarchyTreeView)
        formLayout.addRow("Type:", self.formatComboBox)
        formLayout.addRow("Ignore directory structure:", self.ignoreDirStructureCheckbox)
        formLayout.addRow("Export directory:", self.directorySelector)
        formLayout.addRow(self.exportButton)
        formLayout.addRow(progressLayout)

        statusLabel = qt.QLabel("Status: ")
        self.currentStatusLabel = qt.QLabel("Idle")
        statusHBoxLayout = qt.QHBoxLayout()
        statusHBoxLayout.addStretch(1)
        statusHBoxLayout.addWidget(statusLabel)
        statusHBoxLayout.addWidget(self.currentStatusLabel)
        formLayout.addRow(statusHBoxLayout)

        self.layout.addLayout(formLayout)

        self.layout.addStretch(1)

        self._updateNodesAndExportButton()

    def _startExport(self):
        self.progressBar.setValue(0)
        self.progressBar.show()
        self.cancelButton.show()
        self.cancel = False
        self.cancelButton.enabled = True
        self.exportButton.enabled = False

    def _stopExport(self):
        self.cancelButton.enabled = False
        self._updateNodesAndExportButton()

    def _updateNodesAndExportButton(self):
        items = vtk.vtkIdList()
        self.subjectHierarchyTreeView.currentItems(items)
        self.nodes = export.getDataNodes(items, self.EXPORTABLE_TYPES)

        format = self.formatComboBox.currentText

        if format == MulticoreExport.FORMAT_SUMMARY:
            self.exportButton.enabled = True
            return

        exportableNodesByFormat = []
        for node in self.nodes:
            if format == MulticoreExport.FORMAT_TECHLOG_CSV or format == MulticoreExport.FORMAT_MATRIX_CSV:
                if (
                    node.GetAttribute("Volume type") == "Core unwrap"
                    or node.GetAttribute("Volume type") == "Well unwrap"
                ):
                    exportableNodesByFormat.append(node)
            elif format == MulticoreExport.FORMAT_PNG or format == MulticoreExport.FORMAT_TIF:
                if (
                    node.GetAttribute("Volume type") == "Core"
                    or node.GetAttribute("Volume type") == "Core unwrap"
                    or node.GetAttribute("Volume type") == "Well unwrap"
                ):
                    exportableNodesByFormat.append(node)

        self.nodes = exportableNodesByFormat
        self.exportButton.enabled = self.nodes

    def onExportClicked(self):
        self.currentStatusLabel.text = "Exporting..."
        slicer.app.processEvents()

        checkUniqueNames(self.nodes)
        outputDir = self.directorySelector.directory
        ignoreDirStructure = self.ignoreDirStructureCheckbox.checked
        MulticoreExport.set_setting(self.EXPORT_DIR, outputDir)
        MulticoreExport.set_setting(self.IGNORE_DIR_STRUCTURE, str(ignoreDirStructure))

        format = self.formatComboBox.currentText

        self._startExport()

        processFailed = False
        try:
            if format == MulticoreExport.FORMAT_TECHLOG_CSV or format == MulticoreExport.FORMAT_MATRIX_CSV:
                self.exportCSV(format, outputDir, ignoreDirStructure)
            elif format == MulticoreExport.FORMAT_SUMMARY:
                self.exportSummary(outputDir, ignoreDirStructure)
            elif format == MulticoreExport.FORMAT_TIF or format == MulticoreExport.FORMAT_PNG:
                self.exportImages(format, outputDir, ignoreDirStructure)
        except Exception as error:
            slicer.util.errorDisplay(f"Failed to export:\n{error}")
            processFailed = True

        self._stopExport()
        self.progressBar.setValue(100)
        self.currentStatusLabel.text = "Export completed." if not processFailed else "Export completed with errors."

    def exportImages(self, format, outputDir, ignoreDirStructure):
        for i, node in enumerate(self.nodes):
            nodeDir = Path(outputDir) if ignoreDirStructure else Path(outputDir) / getNodeDataPath(node).parent
            progressOffset = i / len(self.nodes)
            try:
                if node.GetAttribute("Volume type") == "Core":
                    self.logic.exportCoreSlice(node, nodeDir, format.lower())
                elif node.GetAttribute("Volume type") == "Core unwrap":
                    self.logic.exportCoreUnwrap(node, nodeDir, format.lower())
                self.progressBar.setValue(round(100 * progressOffset))
                slicer.app.processEvents()
                if self.cancel:
                    self._stopExport()
                    return
            except Exception as exc:
                self._stopExport()
                self.currentStatusLabel.text = "Export failed."
                raise exc

    def exportSummary(self, outputDir, ignoreDirStructure):
        if not ignoreDirStructure:
            outputDir = Path(outputDir).absolute() / "Multicore" / "Summary"
        else:
            outputDir = Path(outputDir)
        self.logic.exportSummary(outputDir)

    def exportCSV(self, format, outputDir, ignoreDirStructure):
        isTechlog = format == MulticoreExport.FORMAT_TECHLOG_CSV

        for i, node in enumerate(self.nodes):
            nodeDir = Path(outputDir) if ignoreDirStructure else Path(outputDir) / getNodeDataPath(node).parent
            task = MulticoreCSV.exportCSV(node, nodeDir, isTechlog)
            progressOffset = i / len(self.nodes)
            try:
                for progress in task:
                    self.progressBar.setValue(round(100 * (progressOffset + progress / len(self.nodes))))
                    if self.cancel:
                        self._stopExport()
                        return
            except Exception as exc:
                self._stopExport()
                self.currentStatusLabel.text = "Export failed."
                raise exc

    def onCancelClicked(self):
        self.cancel = True

    def onSelectionChanged(self, _):
        self._updateNodesAndExportButton()


class MultiCoreExportLogic(LTracePluginLogic):
    """ """

    CORONAL_SLICE_ORIENTATION = "Coronal"
    SAGITTAL_SLICE_ORIENTATION = "Sagittal"
    ORIENTATION_ANGLE = "Orientation angle"
    IMAGE_FORMAT_TIF = 0
    IMAGE_FORMAT_PNG = 1

    # Keys
    BASE_NAME = "Base name"
    WELL_DIAMETER = "Well diameter"

    processFinished = qt.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.multicore_logic = slicer.modules.multicore.widgetRepresentation().self().logic

        self.getDepth = self.multicore_logic.getDepth
        self.getCoreVolumes = self.multicore_logic.getCoreVolumes
        self.getCoreVolumesSortedByDepth = self.multicore_logic.getCoreVolumesSortedByDepth
        self.setOrientationAngle = self.multicore_logic.setOrientationAngle
        self.getIntraSliceSpacing = self.multicore_logic.getIntraSliceSpacing
        self.getInterSliceSpacing = self.multicore_logic.getInterSliceSpacing
        self.getLength = self.multicore_logic.getLength
        self.getCoreDiameter = self.multicore_logic.getCoreDiameter
        self.getUnwrapVolume = self.multicore_logic.getUnwrapVolume
        self.getWellUnwrapVolume = self.multicore_logic.getWellUnwrapVolume
        self.getUnwrapVolumes = self.multicore_logic.getUnwrapVolumes
        self.around = self.multicore_logic.around

    def exportCoreSlice(self, coreNode, nodeDir, imageFormat):
        sagittalSliceImage = self.generateVolumeCentralSliceImage(coreNode, orientation=self.SAGITTAL_SLICE_ORIENTATION)
        coronalSliceImage = self.generateVolumeCentralSliceImage(coreNode, orientation=self.CORONAL_SLICE_ORIENTATION)
        sliceImageBaseName = coreNode.GetName() + " - "
        sagittalSliceImageName = sliceImageBaseName + "YZ"
        coronalSliceImageName = sliceImageBaseName + "XZ"

        nodeDir.mkdir(parents=True, exist_ok=True)

        cv2.imwrite(str(nodeDir.absolute() / sagittalSliceImageName) + "." + imageFormat, sagittalSliceImage)
        cv2.imwrite(str(nodeDir.absolute() / coronalSliceImageName) + "." + imageFormat, coronalSliceImage)

    def exportCoreUnwrap(self, unwrapNode, nodeDir, imageFormat):
        sliceImage = self.generateUnwrapImage(unwrapNode)
        nodeDir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(nodeDir.absolute() / unwrapNode.GetName()) + "." + imageFormat, sliceImage)

    def exportSummary(self, exportSummaryPath):
        exportSummaryPath.mkdir(parents=True, exist_ok=True)

        coreNodes = self.getCoreVolumesSortedByDepth()
        if len(coreNodes) == 0:
            raise ExportInfo("There is no information available to export.")
        cores = []
        for coreNode in coreNodes:
            cores.append(
                {
                    "name": coreNode.GetAttribute(self.BASE_NAME),
                    "depth": self.getDepth(coreNode),
                    "orientation": self.getOrientationAngle(coreNode),
                    "length": self.getLength(coreNode),
                    "diameter": self.getCoreDiameter(coreNode),
                }
            )

            # Slice images
            sagittalSliceImage = self.generateVolumeCentralSliceImage(
                coreNode, orientation=self.SAGITTAL_SLICE_ORIENTATION, whiteBackground=True
            )
            coronalSliceImage = self.generateVolumeCentralSliceImage(
                coreNode, orientation=self.CORONAL_SLICE_ORIENTATION, whiteBackground=True
            )
            encodedSagittalSliceImage = ReportBuilder.encode_image_by_variable(sagittalSliceImage)
            encodedCoronalSliceImage = ReportBuilder.encode_image_by_variable(coronalSliceImage)
            cores[-1].update({"sagittalSliceImage": encodedSagittalSliceImage})
            cores[-1].update({"coronalSliceImage": encodedCoronalSliceImage})

            # Unwrap image
            unwrapVolume = self.getUnwrapVolume(coreNode)
            if len(unwrapVolume) == 1:
                unwrapImage = self.generateUnwrapImage(unwrapVolume[0], whiteBackground=True)
                encodedUnwrapImage = ReportBuilder.encode_image_by_variable(unwrapImage)
                cores[-1].update({"unwrapImage": encodedUnwrapImage})

        well = {}
        wellUnwrapVolume = self.getWellUnwrapVolume()
        assert len(wellUnwrapVolume) == 0 or len(wellUnwrapVolume) == 1
        if len(wellUnwrapVolume) == 1:
            well.update(
                {
                    "diameter": wellUnwrapVolume[0].GetAttribute(self.WELL_DIAMETER),
                    "depth": self.getDepth(wellUnwrapVolume[0]),
                }
            )
            wellUnwrapImage = self.generateUnwrapImage(wellUnwrapVolume[0], whiteBackground=True)
            encodedWellUnwrapImage = ReportBuilder.encode_image_by_variable(wellUnwrapImage)
            well.update({"wellUnwrapImage": encodedWellUnwrapImage})

        summaryTemplatePath = Path(__file__).parent.absolute() / "Resources"
        summaryTemplateFilePath = summaryTemplatePath / "multicore_summary_template.html"
        reportBuilder = ReportBuilder(summaryTemplateFilePath)
        reportBuilder.add_image_file("lTrace.logo", str(summaryTemplatePath / "LTrace-logo-original.png"))
        reportBuilder.add_variable("cores", cores)
        reportBuilder.add_variable("well", well)
        reportBuilder.generate(str(exportSummaryPath / "multicore_summary.html"))

    def exportImage(self, image, name, path, format):
        cv2.imwrite(str(path.absolute() / name) + "." + format, image)

    def generateUnwrapImage(self, volume, whiteBackground=False):
        displayNode = volume.GetDisplayNode()
        window = displayNode.GetWindow()
        level = displayNode.GetLevel()
        volumeArray = slicer.util.arrayFromVolume(volume)[::-1, ::-1, ::-1]
        middleSliceIndex = getRoundedInteger((len(volumeArray[0]) - 1) / 2)
        volumeImage = volumeArray[:, middleSliceIndex, :]
        volumeImage = self.normalize(self.windowScale(volumeImage, window, level))
        volumeImage = self.resize(volumeImage, self.getIntraSliceSpacing(volume), self.getInterSliceSpacing(volume))
        if whiteBackground:
            volumeImage[volumeImage == 0] = 255
        return volumeImage

    def generateVolumeCentralSliceImage(self, volume, orientation=CORONAL_SLICE_ORIENTATION, whiteBackground=False):
        volumeArray = slicer.util.arrayFromVolume(volume)
        bounds = np.zeros(6)
        volume.GetBounds(bounds)

        spacing = volume.GetSpacing()

        """
        Since the volume can be rotated, we cannot use the bounds as the delimiter for the middle slice, since they are the bounds at the 
        extremes of the volume, which may be larger than the bounds at the central slice. We always delimit the bounds by the array size 
        multiplied by spacing.
        """
        coronalSize = spacing[1] * volumeArray.shape[1] / 2
        sagitalSize = spacing[0] * volumeArray.shape[2] / 2

        bounds[0], bounds[1] = -coronalSize, coronalSize
        bounds[2], bounds[3] = -sagitalSize, sagitalSize

        """
        We will use the minimum spacing for all axes to reconstruct the image at the highest resolution possible. For a smaller resolution,
        use a value larger.
        """
        minSpacing = np.min(spacing)

        """
        Building the fist line of points.
        """
        if orientation == self.CORONAL_SLICE_ORIENTATION:
            middlePoint = (bounds[2] + bounds[3]) / 2
            linePoints = [(s, middlePoint) for s in np.arange(bounds[1] - minSpacing / 2, bounds[0], -minSpacing)]
        elif orientation == self.SAGITTAL_SLICE_ORIENTATION:
            middlePoint = (bounds[0] + bounds[1]) / 2
            linePoints = [(middlePoint, s) for s in np.arange(bounds[3] - minSpacing / 2, bounds[2], -minSpacing)]
        else:
            raise MulticoreExportError("Invalid orientation.")

        """
        Building the image plane points by repeating the line for all depths of the volume.
        """
        centralSlicePoints = []
        for s in np.arange(bounds[4] + minSpacing / 2, bounds[5], minSpacing):
            centralSlicePoints.insert(0, np.c_[linePoints, np.full(len(linePoints), s)])

        """
        Converting the RAS points to IJK points and getting the values from the array (the final image).
        """
        volumeRASToIJKMatrix = vtk.vtkMatrix4x4()
        volume.GetRASToIJKMatrix(volumeRASToIJKMatrix)
        pointsIJK = transformPoints(volumeRASToIJKMatrix, np.reshape(centralSlicePoints, (-1, 3)), True)
        volumeArray = slicer.util.arrayFromVolume(volume)
        centralSliceArray = volumeArray[tuple(pointsIJK.T)[::-1]].reshape(len(centralSlicePoints), -1)

        displayNode = volume.GetDisplayNode()
        window = displayNode.GetWindow()
        level = displayNode.GetLevel()
        volumeImage = self.normalize(self.windowScale(centralSliceArray, window, level))

        if whiteBackground:
            volumeImage[volumeImage == 0] = 255
        return volumeImage

    def resize(self, image, intraSliceSpacing, interSliceSpacing):
        width = getRoundedInteger(np.shape(image)[1] * intraSliceSpacing.m)
        height = getRoundedInteger(np.shape(image)[0] * interSliceSpacing.m)
        return cv2.resize(image, (width, height))

    def getOrientationAngle(self, node):
        return ureg.parse_expression(node.GetAttribute(self.ORIENTATION_ANGLE))

    def normalize(self, image):
        normalizedImage = cv2.normalize(
            image, None, alpha=0, beta=2**16 - 1, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_16U
        )
        return normalizedImage.astype(np.uint16)

    def windowScale(self, data, window, level):
        out_range = [np.min(data), np.max(data)]
        data_new = np.empty(data.shape, dtype=np.double)
        data_new.fill(out_range[1] - 1)
        data_new[data <= (level - window / 2)] = out_range[0]
        data_new[(data > (level - window / 2)) & (data <= (level + window / 2))] = (
            (data[(data > (level - window / 2)) & (data <= (level + window / 2))] - (level - 0.5)) / (window - 1) + 0.5
        ) * (out_range[1] - out_range[0]) + out_range[0]
        data_new[data > (level + window / 2)] = out_range[1] - 1
        return data_new.astype(np.int16)


class ExportInfo(RuntimeError):
    pass


class ProcessInfo(RuntimeError):
    pass


class MulticoreExportError(RuntimeError):
    pass
