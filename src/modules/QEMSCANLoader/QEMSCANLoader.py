import json
import os
from collections import namedtuple
from pathlib import Path
from threading import Lock

import ctk
import numpy as np
import pandas as pd
import qt
import slicer
import vtk
from ltrace.slicer import ui

from slicer.util import MRMLNodeNotFoundException
from slicer.util import dataframeFromTable

from ltrace.file_utils import read_csv
from ltrace.slicer import helpers
from ltrace.slicer_utils import *
from ltrace.slicer_utils import getResourcePath
from ltrace.units import global_unit_registry as ureg, SLICER_LENGTH_UNIT
from ltrace.utils.callback import Callback


class QEMSCANLoader(LTracePlugin):
    SETTING_KEY = "QEMSCANLoader"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "QEMSCAN Loader"
        self.parent.categories = ["Thin Section"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.set_manual_path("Modules/Thin_section/QemscanLoader.html")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class QEMSCANLoaderWidget(LTracePluginWidget):
    LOOKUP_COLOR_TABLE_NONE_LABEL = "Use local CSV file"

    # Settings constants
    LOOKUP_COLOR_TABLE_NAME = "lookupColorTableName"
    IMAGE_SPACING = "imageSpacing"
    FILL_MISSING = "fillMissing"

    LoadParameters = namedtuple(
        "LoadParameters",
        [
            "callback",
            "lookupColorTableNode",
            FILL_MISSING,
            IMAGE_SPACING,
        ],
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def getFillMissing(self):
        return QEMSCANLoader.get_setting(self.FILL_MISSING, default=str(True))

    def getLookupColorTableName(self):
        return QEMSCANLoader.get_setting(self.LOOKUP_COLOR_TABLE_NAME, default=self.LOOKUP_COLOR_TABLE_NONE_LABEL)

    def getImageSpacing(self):
        return QEMSCANLoader.get_setting(self.IMAGE_SPACING, default="0.01")

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = QEMSCANLoaderLogic()

        self.frame = qt.QFrame()
        self.frame.setMaximumHeight(400)
        self.layout.addWidget(self.frame)
        loadFormLayout = qt.QFormLayout(self.frame)
        loadFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        loadFormLayout.setContentsMargins(0, 0, 0, 0)

        globs = [f"*{ext}" for ext in self.logic.QEMSCAN_LOADER_FILE_EXTENSIONS]
        self.pathWidget = ctk.ctkPathLineEdit()
        self.pathWidget.filters = ctk.ctkPathLineEdit.Files
        self.pathWidget.nameFilters = [f"Image files ({' '.join(globs)});;Any files (*)"]
        self.pathWidget.settingKey = "QEMSCANLoader/InputFile"

        self.pathWidget.currentPathChanged.connect(self.onPathSelected)
        loadFormLayout.addRow("Import path:", self.pathWidget)

        loadFormLayout.addRow(" ", None)

        self.lookupColorTable = slicer.qMRMLNodeComboBox()
        self.lookupColorTable.nodeTypes = ["vtkMRMLTableNode"]
        self.lookupColorTable.selectNodeUponCreation = True
        self.lookupColorTable.addEnabled = False
        self.lookupColorTable.removeEnabled = False
        self.lookupColorTable.noneEnabled = True
        self.lookupColorTable.noneDisplay = self.LOOKUP_COLOR_TABLE_NONE_LABEL
        self.lookupColorTable.showHidden = True
        self.lookupColorTable.showChildNodeTypes = False
        self.lookupColorTable.setMRMLScene(slicer.mrmlScene)
        self.lookupColorTable.setToolTip("Table that relates colors to minerals or segments.")
        self.lookupColorTable.currentNodeChanged.connect(self.onLookupColorTableChanged)
        self.lookupColorTable.addAttribute("vtkMRMLTableNode", "MineralColors")

        self.addLookupColorTableButton = qt.QPushButton("Add new")
        self.addLookupColorTableButton.setToolTip("Select the CSV file to load as a new lookup color table")
        self.addLookupColorTableButton.setMinimumWidth(130)
        self.addLookupColorTableButton.clicked.connect(self.onAddLookupColorTableButtonClicked)

        self.deleteLookupColorTableButton = qt.QPushButton("Delete current")
        self.deleteLookupColorTableButton.setToolTip("Delete current lookup color table")
        self.deleteLookupColorTableButton.setMinimumWidth(130)
        self.deleteLookupColorTableButton.clicked.connect(self.onDeleteLookupColorTableButtonClicked)

        lookupColorTableHBoxLayout = qt.QHBoxLayout()
        lookupColorTableHBoxLayout.addWidget(self.lookupColorTable)
        lookupColorTableHBoxLayout.addWidget(self.addLookupColorTableButton)
        lookupColorTableHBoxLayout.addWidget(self.deleteLookupColorTableButton)
        loadFormLayout.addRow("Lookup color table:", lookupColorTableHBoxLayout)

        self.fillMissingCheckBox = qt.QCheckBox('Fill missing colors from "Default mineral colors" lookup table')
        self.fillMissingCheckBox.setChecked(self.getFillMissing() == "True")
        loadFormLayout.addRow(None, self.fillMissingCheckBox)

        loadFormLayout.addRow(" ", None)

        self.imageSpacingLineEdit = qt.QLineEdit(self.getImageSpacing())
        self.imageSpacingValidator = qt.QDoubleValidator()
        self.imageSpacingValidator.bottom = 0
        self.imageSpacingLocale = qt.QLocale()
        self.imageSpacingLocale.setNumberOptions(qt.QLocale.RejectGroupSeparator)
        self.imageSpacingValidator.setLocale(self.imageSpacingLocale)
        self.imageSpacingLineEdit.setValidator(self.imageSpacingValidator)
        self.imageSpacingLineEdit.setToolTip("Pixel size in millimeters")
        loadFormLayout.addRow("Pixel size (mm):", self.imageSpacingLineEdit)

        loadFormLayout.addRow(" ", None)

        self.applyCancelButtons = ui.ApplyCancelButtons(
            onApplyClick=self.onLoadButtonClicked,
            onCancelClick=self.onCancelButtonClicked,
            applyTooltip="Load QEMSCANs",
            cancelTooltip="Cancel",
            applyText="Load QEMSCANs",
            cancelText="Cancel",
            enabled=True,
            applyObjectName=None,
            cancelObjectName=None,
        )
        self.layout.addWidget(self.applyCancelButtons)

        statusLabel = qt.QLabel("Status: ")
        self.currentStatusLabel = qt.QLabel("Idle")
        statusHBoxLayout = qt.QHBoxLayout()
        statusHBoxLayout.addStretch(1)
        statusHBoxLayout.addWidget(statusLabel)
        statusHBoxLayout.addWidget(self.currentStatusLabel)
        self.layout.addLayout(statusHBoxLayout)

        self.progressBar = qt.QProgressBar()
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)
        self.layout.addWidget(self.progressBar)
        self.layout.addStretch(1)
        self.progressBar.hide()

        self.progressMux = Lock()

    def onPathSelected(self, lastPathString):
        self.pathWidget.setStyleSheet("")

    def onLookupColorTableChanged(self):
        currentNode = self.lookupColorTable.currentNode()
        if currentNode is None or currentNode.GetName() != "Default mineral colors":
            self.fillMissingCheckBox.visible = True
        else:
            self.fillMissingCheckBox.visible = False
        if currentNode is None or currentNode.GetName() == "Default mineral colors":
            self.deleteLookupColorTableButton.visible = False
        else:
            self.deleteLookupColorTableButton.visible = True
        self.lookupColorTable.setStyleSheet("")

    def onAddLookupColorTableButtonClicked(self):
        file = Path(qt.QFileDialog.getOpenFileName(self.frame, "Select a CSV file", "", "CSV file (*.csv)"))
        if file != Path():
            tableNode = self.logic.addQEMSCANLookupColorTable(file)
            self.lookupColorTable.setCurrentNode(tableNode)

    def validateInput(self):
        if not Path(self.pathWidget.currentPath).is_file():
            helpers.highlight_error(self.pathWidget)
            return False
        return True

    def enter(self) -> None:
        super().enter()
        self.initializeLookupColorTables()

    def initializeLookupColorTables(self):
        self.logic.loadQEMSCANLookupColorTables()
        self.onLookupColorTableChanged()
        try:
            currentLookupColorTableNode = slicer.util.getNode(self.getLookupColorTableName())
            self.lookupColorTable.setCurrentNode(currentLookupColorTableNode)
        except:
            pass

    def onDeleteLookupColorTableButtonClicked(self):
        tableNode = self.lookupColorTable.currentNode()
        self.logic.deleteQEMSCANLookupColorTable(tableNode)
        self.addLookupColorTableButton.setFocus(True)  # To avoid focusing the pixel size input after deleting an item

    def onCancelButtonClicked(self):
        self.logic.onCancel()

    def onLoadButtonClicked(self):
        if not self.validateInput():
            return

        callback = Callback(
            on_update=lambda message, percent, processEvents=True: self.updateStatus(
                message,
                progress=percent,
                processEvents=processEvents,
            )
        )
        callback.on_update("", 0)
        try:
            path = self.pathWidget.currentPath
            if not (self.imageSpacingLineEdit.text):
                raise LoadInfo("Pixel size is required.")
            if self.lookupColorTable.currentNode() is None:
                lookupColorTableName = self.LOOKUP_COLOR_TABLE_NONE_LABEL
            else:
                lookupColorTableName = self.lookupColorTable.currentNode().GetName()
            QEMSCANLoader.set_setting(self.LOOKUP_COLOR_TABLE_NAME, lookupColorTableName)
            QEMSCANLoader.set_setting(self.IMAGE_SPACING, self.imageSpacingLineEdit.text)
            QEMSCANLoader.set_setting(self.FILL_MISSING, str(self.fillMissingCheckBox.isChecked()))
            helpers.save_path(self.pathWidget)
            loadParameters = self.LoadParameters(
                callback,
                self.lookupColorTable.currentNode(),
                self.fillMissingCheckBox.isChecked(),
                float(self.imageSpacingLineEdit.text) * ureg.millimeter,
            )
            print(loadParameters)
            self.logic.load(path, loadParameters)
            self.pathWidget.currentPath = Path(path).parent.resolve()
        except LoadInfo as e:
            slicer.util.infoDisplay(str(e))
            return
        except LoadError as e:
            slicer.util.errorDisplay(str(e))
            return
        finally:
            callback.on_update("", 100)

    def updateStatus(self, message, progress=None, processEvents=True):
        self.progressBar.show()
        self.currentStatusLabel.text = message
        if progress == -1:
            self.progressBar.setRange(0, 0)
        else:
            self.progressBar.setRange(0, 100)
            self.progressBar.setValue(progress)
            if self.progressBar.value == 100:
                self.progressBar.hide()
                self.currentStatusLabel.text = "Idle"
        if not processEvents:
            return
        if self.progressMux.locked():
            return
        with self.progressMux:
            slicer.app.processEvents()


class QEMSCANLoaderLogic(LTracePluginLogic):
    QEMSCAN_LOOKUP_COLOR_TABLES_PATH = getResourcePath("QEMSCAN") / "LookupColorTables"
    ROOT_DATASET_DIRECTORY_NAME = "Thin Section"
    QEMSCAN_LOADER_FILE_EXTENSIONS = [".tif", ".tiff"]

    def __init__(self):
        LTracePluginLogic.__init__(self)

    def load(self, path, p):
        path = Path(path)
        if path.is_file():
            return self.loadImage(path, p, path.parent.name)
        else:
            files = []
            for extension in self.QEMSCAN_LOADER_FILE_EXTENSIONS:
                files.extend(list(path.glob("*" + extension)))
            for file in files:
                return self.loadImage(file, p, path.name)

    def configureInitialNodeMetadata(self, node, baseName, p):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        rootDirID = subjectHierarchyNode.GetItemByName(self.ROOT_DATASET_DIRECTORY_NAME)
        if rootDirID == 0:
            rootDirID = subjectHierarchyNode.CreateFolderItem(
                subjectHierarchyNode.GetSceneItemID(), self.ROOT_DATASET_DIRECTORY_NAME
            )
        dirID = subjectHierarchyNode.GetItemChildWithName(rootDirID, baseName)
        if dirID == 0:
            dirID = subjectHierarchyNode.CreateFolderItem(rootDirID, baseName)
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(node),
            dirID,
        )

    def loadImage(self, file, p, baseName):
        self.cancel = False
        outputVolumeNode = None
        segmentationNode = None
        try:
            outputVolumeNode = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLScalarVolumeNode.__name__)
            outputVolumeNode.SetName(file.stem)
            labelMapVolumeNode = self.getLabelMap(outputVolumeNode)
            labelMapVolumeNode.SetName(file.stem)

            if p.lookupColorTableNode is not None:
                if p.fillMissing and p.lookupColorTableNode.GetName() != "Default mineral colors":
                    df = self.fillMissingValuesFromDefaultLookupTable(dataframeFromTable(p.lookupColorTableNode))
                else:
                    df = dataframeFromTable(p.lookupColorTableNode)
            else:
                localDataframe = self.loadQEMSCANDataframeFromQEMSCANImageFileLocation(file)
                if p.fillMissing:
                    df = self.fillMissingValuesFromDefaultLookupTable(localDataframe)
                else:
                    df = localDataframe

            if df is None:  # Fill missing is not checked and there is no local CSV file available
                raise LoadError(
                    "There is no local CSV file for QEMSCAN image: " + str(file) + ". Loading will not continue."
                )

            lookupColorTableCSV = df.to_csv(index=False)

            cliParams = {
                "file1": str(file),
                "csvstring": lookupColorTableCSV,
                "outputVolume": outputVolumeNode.GetID(),
                "labelVolume": labelMapVolumeNode.GetID(),
            }
            self.cliNode = slicer.cli.runSync(slicer.modules.qemscancli, None, cliParams)

            p.callback.on_update("Loading " + file.name + "...", 33)

            self.setImageSpacing(outputVolumeNode, p.imageSpacing)
            self.setImageSpacing(labelMapVolumeNode, p.imageSpacing)

            dirMat = vtk.vtkMatrix4x4()
            dirMat.DeepCopy(list(np.array([[-1, 0, 0, 0], [0, -1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 0]]).flat))
            outputVolumeNode.SetRASToIJKMatrix(dirMat)
            labelMapVolumeNode.SetRASToIJKMatrix(dirMat)

            segmentationNode = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLSegmentationNode", f"{outputVolumeNode.GetName()}-Segmentation"
            )
            segmentationNode.SetName(file.stem)

            # Extract segmentation from labelmap
            slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelMapVolumeNode, segmentationNode)
            segmentationNode.CreateDefaultDisplayNodes()
            segmentationNode.GetDisplayNode().SetSliceIntersectionThickness(0)
            segmentationNode.GetDisplayNode().SetAllSegmentsOpacity2DFill(2)

            p.callback.on_update("Loading " + file.name + "...", 66)

            lookupTable = json.loads(self.cliNode.GetParameterAsString("lookup_table"))

            segmentation = segmentationNode.GetSegmentation()
            for i in range(segmentation.GetNumberOfSegments()):
                slicerSegment = segmentation.GetNthSegment(i)
                slicerSegment.RemoveTag("TerminologyEntry")  # Removing anatomy related tag
                segment = lookupTable[str(slicerSegment.GetLabelValue())]
                slicerSegment.SetName(segment["name"])
                colorRGB = np.array(segment["color_rgb"], dtype=float) / 255
                slicerSegment.SetColor(colorRGB)

            slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(segmentationNode, labelMapVolumeNode)
            self.setImageSpacing(labelMapVolumeNode, p.imageSpacing)
            self.configureInitialNodeMetadata(labelMapVolumeNode, baseName, p)
            if self.cancel:
                slicer.mrmlScene.RemoveNode(labelMapVolumeNode)
                slicer.util.resetSliceViews()
                p.callback.on_update("Cancelled", 100)
                return
            return labelMapVolumeNode

        except Exception as e:
            raise e
            slicer.mrmlScene.RemoveNode(labelMapVolumeNode)
            raise LoadError("The format of the input file is invalid.")
        finally:
            slicer.mrmlScene.RemoveNode(segmentationNode)
            slicer.mrmlScene.RemoveNode(outputVolumeNode)
            slicer.util.resetSliceViews()

    def onCancel(self):
        self.cancel = True

    def setImageSpacing(self, node, imageSpacing):
        node.SetSpacing(
            imageSpacing.m_as(SLICER_LENGTH_UNIT),
            imageSpacing.m_as(SLICER_LENGTH_UNIT),
            imageSpacing.m_as(SLICER_LENGTH_UNIT),
        )

    def fillMissingValuesFromDefaultLookupTable(self, df):
        try:
            # If default color table exists
            defaultLookupColorTableNode = slicer.util.getNode("Default mineral colors")
            df2 = dataframeFromTable(defaultLookupColorTableNode)
            return pd.concat([df, df2]).drop_duplicates().reset_index(drop=True)
        except slicer.util.MRMLNodeNotFoundException:
            return df

    def getLabelMap(self, sourceVolume):
        labelmapNodeName = f"TMP-{sourceVolume.GetName()}-LabelMap"
        try:
            lbnode = slicer.util.getNode(labelmapNodeName)
        except:
            lbnode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", labelmapNodeName)
        lbnode.SetSpacing(sourceVolume.GetSpacing())
        return lbnode

    def configureLookupColorTableNodeMetadata(self, tableNode):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        rootDirID = subjectHierarchyNode.GetItemByName(self.ROOT_DATASET_DIRECTORY_NAME)
        if rootDirID == 0:
            rootDirID = subjectHierarchyNode.CreateFolderItem(
                subjectHierarchyNode.GetSceneItemID(), self.ROOT_DATASET_DIRECTORY_NAME
            )
        lookupColorTablesDirName = "Lookup color tables"
        dirID = subjectHierarchyNode.GetItemChildWithName(rootDirID, lookupColorTablesDirName)
        if dirID == 0:
            dirID = subjectHierarchyNode.CreateFolderItem(rootDirID, lookupColorTablesDirName)
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(tableNode),
            dirID,
        )

    @staticmethod
    def csv_to_df(file):
        nrows = 3
        without_header = read_csv(file, header=None, nrows=nrows)
        with_header = read_csv(file, nrows=nrows)
        hasHeader = tuple(without_header.dtypes) != tuple(with_header.dtypes)
        df = read_csv(file, header=0 if hasHeader else None)

        # Standardize column names so they are concatenated correctly
        df.columns = ["Mineral", "R", "G", "B"]

        return df

    def loadQEMSCANLookupColorTables(self):
        files = [x for x in self.QEMSCAN_LOOKUP_COLOR_TABLES_PATH.iterdir() if x.is_file()]
        for file in files:
            self.loadLookupColorTable(file)

    def loadQEMSCANDataframeFromQEMSCANImageFileLocation(self, file):
        files = [x for x in file.parent.iterdir() if x.is_file()]
        csvFiles = [file for file in files if file.suffix.lower() in [".csv"]]
        if len(csvFiles) > 1:
            raise LoadError(
                "Multiple local CSV files detected for the QEMSCAN image: " + str(file) + ". Loading will not continue."
            )
        elif len(csvFiles) == 1:
            try:
                df = self.csv_to_df(str(csvFiles[0]))
                return df
            except:
                raise LoadError(
                    "Error while loading local CSV file for QEMSCAN image: "
                    + str(file)
                    + ". Loading will not continue."
                )
        else:
            return None  # If there is no local CSV file

    def loadLookupColorTable(self, file):
        tableNode = slicer.util.getFirstNodeByClassByName("vtkMRMLTableNode", file.stem)
        if tableNode:
            df = dataframeFromTable(tableNode)
        else:
            df = self.csv_to_df(str(file))
            tableNode = dataFrameToTableNode(df)
            tableNode.SetHideFromEditors(True)  # Only show in the QEMSCAN Loader combo box
            tableNode.SetAttribute("MineralColors", "")
            tableNode.SetName(file.stem)
        return df, tableNode

    def addQEMSCANLookupColorTable(self, file):
        df, tableNode = self.loadLookupColorTable(file)
        tableNode.SetHideFromEditors(True)  # Only show in the QEMSCAN Loader combo box
        tableNode.SetAttribute("MineralColors", "")
        df.to_csv(str(self.QEMSCAN_LOOKUP_COLOR_TABLES_PATH / file.name), index=False)
        return tableNode

    def deleteQEMSCANLookupColorTable(self, tableNode):
        slicer.mrmlScene.RemoveNode(tableNode)
        files = [x for x in self.QEMSCAN_LOOKUP_COLOR_TABLES_PATH.iterdir() if x.is_file()]
        for file in files:
            if file.stem == tableNode.GetName():
                file.unlink()


class LoadInfo(RuntimeError):
    pass


class LoadError(RuntimeError):
    pass
