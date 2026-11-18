import json
import shutil
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import qt
import slicer
import vtk
from commons.slicer.helpers import tryGetNode
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events
from commons.slicer_utils import dataFrameToTableNode


class GeologEnvTest(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = {
            # import
            # connection
            "importGeologDirectory": self.find_widget("import Geolog Directory Browser"),
            "importProjectDirectory": self.find_widget("import Geolog Projects Directory Browser"),
            "importProjectsComboBox": self.find_widget("import Geolog Project Selector ComboBox"),
            "importSearchButton": self.find_widget("import Geolog Connect Button"),
            "wellImportComboBox": self.find_widget("Import Well Selector ComboBox"),
            "wellDiameterLineEdit": self.find_widget("Import Well Diameter LineEdit"),
            "nullValuesLineEdit": self.find_widget("Import Null Values LineEdit"),
            "dataTableView": self.find_widget("dataTableView"),
            # export
            # connection
            "exportGeologDirectory": self.find_widget("export Geolog Directory Browser"),
            "exportProjectDirectory": self.find_widget("export Geolog Projects Directory Browser"),
            "exportProjectsComboBox": self.find_widget("export Geolog Project Selector ComboBox"),
            "exportSearchButton": self.find_widget("export Geolog Connect Button"),
            "wellExportComboBox": self.find_widget("Export Well Selector ComboBox"),
            "wellExportNameLineEdit": self.find_widget("Export Well Name LineEdit"),
            "newSetNameLineEdit": self.find_widget("Export Set Name LineEdit"),
            "overwriteCheckBox": self.find_widget("Export Allow Set Overwrite CheckBox"),
            "subjectHierarchyTreeView": self.find_widget("Export Node Selector TreeView"),
            "exportButton": self.find_widget("Export Button"),
        }

    def tear_down(self):
        pass

    def test_default_interface_configuration(self):
        # connection
        assert self._widgets["importGeologDirectory"].directory != ""
        assert self._widgets["importProjectDirectory"].directory != ""
        assert self._widgets["importProjectsComboBox"].count > 0

        # import
        assert self._widgets["nullValuesLineEdit"].text == "-9999.25, -999.25, -9999.0"
        assert self._widgets["wellDiameterLineEdit"].text == ""
        assert self._widgets["dataTableView"].loadButton.enabled is False

        # export
        assert self._widgets["wellExportComboBox"].currentText == "New Well"
        assert self._widgets["wellExportNameLineEdit"].text == ""
        assert self._widgets["newSetNameLineEdit"].text == ""
        assert self._widgets["overwriteCheckBox"].isChecked() is False

    @patch("numpy.load")
    @patch("GeologLib.GeologImportLogic._runProcess")
    @patch("GeologLib.GeologConnectLogic.getGeologData")
    def test_read_project_and_import_data(self, mockConnect, mockImportProcess, mockLoad):
        searchButton = self._widgets["importSearchButton"]
        wellImportComboBox = self._widgets["wellImportComboBox"]
        wellDiameterLineEdit = self._widgets["wellDiameterLineEdit"]
        dataTableView = self.find_widget("dataTableView")
        exportWellComboBox = self._widgets["wellExportComboBox"]
        wellExportNameLineEdit = self._widgets["wellExportNameLineEdit"]

        connect_output_file = Path(__file__).resolve().parent / "resources" / "connect_output.json"
        with open(connect_output_file, "r") as f:
            mockConnect.return_value = json.load(f)
        mockImportProcess.return_value = 0

        wellName = "TEST_WELL"

        with patch("GeologLib.GeologConnectWidget.GeologConnectWidget.checkEnvViability") as mock_temp_path:
            mock_temp_path.return_value = True
            searchButton.clicked()
            process_events()

        assert wellImportComboBox.currentText == wellName
        assert dataTableView.tableWidget.rowCount == 5
        assert exportWellComboBox.findText(wellName) != -1

        exportWellComboBox.setCurrentText(wellName)
        assert wellExportNameLineEdit.text == wellName

        wellDiameterLineEdit.text = 10

        mockLoad.return_value = np.random.randint(4, size=(1001, 200))
        dataTableView.tableWidget.cellWidget(2, 0).findChild(qt.QCheckBox).setChecked(qt.Qt.Checked)
        dataTableView.loadButton.clicked()
        importedScalarNode = tryGetNode(f"{wellName}_TEST_SCALAR [UNITS]")

        assert importedScalarNode is not None
        assert isinstance(importedScalarNode, slicer.vtkMRMLScalarVolumeNode)
        dataTableView.tableWidget.cellWidget(2, 0).findChild(qt.QCheckBox).setChecked(qt.Qt.Unchecked)

        mockLoad.return_value = np.random.randint(4, size=(1001, 200))
        dataTableView.tableWidget.cellWidget(3, 0).findChild(qt.QCheckBox).setChecked(qt.Qt.Checked)
        dataTableView.tableWidget.cellWidget(3, 6).findChild(qt.QCheckBox).setChecked(qt.Qt.Checked)
        dataTableView.loadButton.clicked()
        importedLabelNode = tryGetNode(f"{wellName}_TEST_LABELMAP")

        assert importedLabelNode is not None
        assert isinstance(importedLabelNode, slicer.vtkMRMLLabelMapVolumeNode)
        dataTableView.tableWidget.cellWidget(3, 0).findChild(qt.QCheckBox).setChecked(qt.Qt.Unchecked)
        dataTableView.tableWidget.cellWidget(3, 6).findChild(qt.QCheckBox).setChecked(qt.Qt.Unchecked)

        mockLoad.return_value = np.random.randint(4, size=(868, 54))
        dataTableView.tableWidget.cellWidget(4, 0).findChild(qt.QCheckBox).setChecked(qt.Qt.Checked)
        dataTableView.tableWidget.cellWidget(4, 7).findChild(qt.QCheckBox).setChecked(qt.Qt.Checked)
        dataTableView.loadButton.clicked()
        importedTableNode = tryGetNode(f"{wellName}_TEST_TABLE [V/V]")

        assert importedTableNode is not None
        assert isinstance(importedTableNode, slicer.vtkMRMLTableNode)

    @patch("GeologLib.GeologExportLogic._runProcess")
    @patch("GeologLib.GeologConnectWidget.GeologConnectWidget.checkEnvViability", lambda x: True)
    def test_export_data(self, mockExportProcess):
        wellExportNameLineEdit = self._widgets["wellExportNameLineEdit"]
        newSetNameLineEdit = self._widgets["newSetNameLineEdit"]
        subjectHierarchyTreeView = self._widgets["subjectHierarchyTreeView"]
        exportButton = self._widgets["exportButton"]

        mockExportProcess.return_value = 0

        wellName = "TEST_WELL"
        wellExportNameLineEdit.text = wellName
        newSetNameLineEdit.text = "TEST SET"

        mockArray = np.random.randint(4, size=(1001, 200))

        labelmapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "TEST_WELL_TEST_LABELMAP")
        slicer.util.updateVolumeFromArray(labelmapNode, mockArray.reshape(1001, 1, 200).astype(np.int32))
        labelmapNode.SetOrigin([0, 0, -1000000])
        scalarNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "TEST_WELL_TEST_SCALAR [UNITS]")
        slicer.util.updateVolumeFromArray(scalarNode, mockArray.reshape(1001, 1, 200).astype(np.int32))
        scalarNode.SetOrigin([0, 0, -1000000])

        scene = slicer.app.mrmlScene()
        itemList = vtk.vtkIdList()
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(scene)
        itemList.InsertNextId(subjectHierarchyNode.GetItemByName(scalarNode.GetName()))
        itemList.InsertNextId(subjectHierarchyNode.GetItemByName(labelmapNode.GetName()))
        subjectHierarchyTreeView.setCurrentItems(itemList)

        myTempPath = Path(slicer.util.tempDirectory())
        with patch("slicer.util.tempDirectory") as mockTempPath:
            mockTempPath.return_value = myTempPath
            with patch("GeologLib.GeologExportLogic._cleanUp") as mock_export_cleanUp:
                mock_export_cleanUp.return_value = 0
                exportButton.clicked()

        attributeFilePath = myTempPath / "attributes.json"
        assert attributeFilePath.is_file()
        assert (myTempPath / "TEST_WELL_TEST_SCALAR.npy").is_file()
        assert (myTempPath / "TEST_WELL_TEST_LABELMAP.npy").is_file()

        with open(attributeFilePath, "r") as f:
            volumeCreatedAttributes = json.load(f)

        referenceAttributePath = Path(__file__).resolve().parent / "resources"
        with open(referenceAttributePath / "export_attributes_volumes.json", "r") as f:
            volumeReferenceAttributes = json.load(f)

        assert volumeCreatedAttributes == volumeReferenceAttributes

        df = pd.DataFrame(mockArray)
        depthCurve = np.linspace(1000000, 1001000, num=mockArray.shape[0])
        df.insert(0, "DEPTH", depthCurve.astype(float))
        tableNode = dataFrameToTableNode(dataFrame=df)
        tableNode.SetName(f"{wellName}_TEST_TABLE [V/V]")

        subjectHierarchyTreeView.setCurrentNode(tableNode)
        with patch("slicer.util.tempDirectory") as mockTempPath:
            mockTempPath.return_value = myTempPath
            with patch("GeologLib.GeologExportLogic._cleanUp") as mock_export_cleanUp:
                mock_export_cleanUp.return_value = 0
                exportButton.clicked()

        assert attributeFilePath.is_file()
        assert (myTempPath / f"{wellName}_TEST_TABLE.npy").is_file()

        with open(attributeFilePath, "r") as f:
            tableCreatedAttributes = json.load(f)

        referenceAttributePath = Path(__file__).resolve().parent / "resources"
        with open(referenceAttributePath / "export_attributes_table.json", "r") as f:
            tableReferenceAttributes = json.load(f)

        assert tableCreatedAttributes == tableReferenceAttributes

        if myTempPath.is_dir():
            shutil.rmtree(myTempPath, ignore_errors=True)
