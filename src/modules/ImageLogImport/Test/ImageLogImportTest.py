import os
from pathlib import Path
from unittest.mock import patch
import pytest

import numpy as np
import slicer
from dliswriter import DLISFile, enums

from commons.slicer.helpers import (
    tryGetNode,
    getVolumeNullValue,
    arrayPartsFromNode,
    arrayFromVisibleSegmentsBinaryLabelmap,
)
from commons.constants import DLISImportConst
from commons.image.las import retrieve_depth_curve
from commons.image.optimized_transforms import ANP_880_2022_DEFAULT_NULL_VALUE, DEFAULT_NULL_VALUES
from commons.slicer.image_log.import_logic import add_volume_from_data
from commons.slicer.node_attributes import TableDataTypeAttribute, TableType
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project
from commons.slicer import metadata

TEST_RESOURCES_DIR = os.path.join(os.path.dirname(__file__), "Resources")

SYNTHETIC_DLIS_FILE = os.path.join(TEST_RESOURCES_DIR, "SYNTHETIC_DLIS", "AMP.dlis")
SYNTHETIC_DLIS_FILE2 = os.path.join(
    TEST_RESOURCES_DIR, "SYNTHETIC_DLIS", "synth_dlis_multiple_logical_files_and_origins.dlis"
)
SYNTHETIC_LAS_FILE = os.path.join(TEST_RESOURCES_DIR, "SYNTHETIC_LAS", "AMP.las")
SYNTHETIC_CSV_PATH = os.path.join(TEST_RESOURCES_DIR, "SYNTHETIC_CSV")
SYNTHETIC_LAS_FILE_MIXED = os.path.join(TEST_RESOURCES_DIR, "SYNTHETIC_LAS", "mixed_images_and_curves.las")
ANONYMIZED_SCENE_FILE = os.path.join(
    TEST_RESOURCES_DIR, "ANONYMIZED_DATA_vol_label_curve_and_hist", "ANONYMIZED_SCENE_vol_label_curve_and_hist.mrml"
)
ANONYMIZED_LAS_FILE = os.path.join(
    TEST_RESOURCES_DIR, "ANONYMIZED_DATA_vol_label_curve_and_hist", "ANONYMIZED__vol_label_curve_and_hist.las"
)

GENERATED_DLIS_DIR = Path(slicer.app.temporaryPath) / "ImageLogImportTestGeneratedDlis"


def labels_image(null_value: float, rows: int = 40, columns: int = 8) -> np.ndarray:
    """Image holding labels 0 to 4 and a band of null_value on its first rows."""
    image = np.tile(np.arange(columns, dtype=np.float32) % 5, (rows, 1))
    image[:4, :] = null_value
    return image


def write_synthetic_dlis(name: str, wells: list) -> str:
    """Writes a DLIS with one logical file per (well name, image, absent values) entry."""
    dlis_file = DLISFile()
    for index, (well_name, image, absent_values) in enumerate(wells, start=1):
        # Every set needs a name of its own, otherwise the logical files share their objects
        sets = f"S{index}"
        logical_file = dlis_file.add_logical_file(fh_id=f"LF{index}")
        logical_file.add_origin(f"O{index}", well_name=well_name, set_name=f"O_{sets}")
        depth = np.linspace(1000.0, 1010.0, len(image)).astype(np.float32)
        depth_channel = logical_file.add_channel(f"MD{index}", data=depth, units=enums.Unit.METER, set_name=sets)
        image_channel = logical_file.add_channel(f"SEG{index}", data=image, units="dB", set_name=sets)
        logical_file.add_frame(
            f"FRAME{index}",
            channels=(depth_channel, image_channel),
            index_type=enums.FrameIndexType.BOREHOLE_DEPTH,
            set_name=sets,
        )
        if absent_values:
            zones = [  # A multi-valued parameter is only accepted along with its zones
                logical_file.add_zone(
                    f"Z{index}_{position}",
                    domain=enums.ZoneDomain.BOREHOLE_DEPTH,
                    minimum=1000 + position,
                    maximum=1001 + position,
                    set_name=sets,
                )
                for position in range(len(absent_values))
            ]
            logical_file.add_parameter("ABSENT_VALUE", values=list(absent_values), zones=zones, set_name=sets)

    GENERATED_DLIS_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DLIS_DIR / name
    dlis_file.write(str(path), input_chunk_size=len(wells[0][1]))
    return str(path)


def populate_widgets(cls):
    """Initialize dictionary with module's interface widgets reference."""

    ioFileInputLineEdit = cls.find_widget("File Input")
    wellNameInput = cls.find_widget("Well Name Input")
    wellDiameter = cls.find_widget("Well Diameter Input")
    filterLineEdit = cls.find_widget("Filter Input")
    selectAllButton = cls.find_widget("Select All Button")
    tableWidget = cls.find_widget("Table Widget")
    nullValuesLineEdit = cls.find_widget("Null Values List Text")
    resetNullValuesListButton = cls.find_widget("Reset Null Values List Button")
    loadButton = cls.find_widget("Load Button")
    clearFilterButton = cls.find_widget("Clear filter")
    deselectButton = cls.find_widget("Deselect all")

    # Assert widget existence
    cls.assertIsNotNone(ioFileInputLineEdit)
    cls.assertIsNotNone(wellNameInput)
    cls.assertIsNotNone(wellDiameter)
    cls.assertIsNotNone(filterLineEdit)
    cls.assertIsNotNone(selectAllButton)
    cls.assertIsNotNone(tableWidget)
    cls.assertIsNotNone(nullValuesLineEdit)
    cls.assertIsNotNone(resetNullValuesListButton)
    cls.assertIsNotNone(loadButton)
    cls.assertIsNotNone(clearFilterButton)
    cls.assertIsNotNone(deselectButton)

    cls._widgets["File Input"] = ioFileInputLineEdit
    cls._widgets["Well Name Input"] = wellNameInput
    cls._widgets["Well Diameter Input"] = wellDiameter
    cls._widgets["Filter Input"] = filterLineEdit
    cls._widgets["Select All Button"] = selectAllButton
    cls._widgets["Table Widget"] = tableWidget
    cls._widgets["Null Values List Text"] = nullValuesLineEdit
    cls._widgets["Reset Null Values List Button"] = resetNullValuesListButton
    cls._widgets["Load Button"] = loadButton
    cls._widgets["Clear filter"] = clearFilterButton
    cls._widgets["Deselect all"] = deselectButton


class ImageLogImportTest(LTracePluginTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = dict()
        populate_widgets(self)

    def test_dlis_import(self):
        """
        Test if a DLIS file is loaded correctly, with the expected metadata loaded results and final results.
        """

        # Setting the DLIS file path
        ioFileInputLineEdit = self._widgets["File Input"]
        ioFileInputLineEdit.setCurrentPath(SYNTHETIC_DLIS_FILE)

        # Verifying the loaded well name
        wellNameInput = self._widgets["Well Name Input"]
        assert wellNameInput.text == "POCO"

        tableWidget = self._widgets["Table Widget"]
        # Two rows, AMP and INDEX rows are loaded on this DLIS file
        assert tableWidget.rowCount == 2

        # Setting a required well diameter
        wellDiameter = self._widgets["Well Diameter Input"]
        wellDiameter.setText("8.5")

        # Filter the items by "AMP" keyword
        filterLineEdit = self._widgets["Filter Input"]
        filterLineEdit.setText("AMP")

        # Select all items
        selectAllButton = self._widgets["Select All Button"]
        selectAllButton.clicked()

        # Selecting all the rows after filtering must select just one row
        rowsToLoad = self._module_widget.widget.tableView.rows_to_load()
        assert len(rowsToLoad) == 1

        # Loading the curve - vtkMRMLScalarVolumeNode
        loadButton = self._widgets["Load Button"]
        loadButton.clicked()

        # Verifying if the node was loaded
        node = tryGetNode("POCO_AMP [dB]")
        self.assertIsNotNone(node)

        # The array from the loaded node is just filled with ones. Checking that.
        array = slicer.util.arrayFromVolume(node)
        assert np.all(array == 1)

        # Test LabelMap and As Table are Checked False
        tables = self._module_widget.widget.tableView
        labelmap_column = tables.columns.index("LabelMap")
        loadtable_column = tables.columns.index("As Table")
        for row in tables.rows_to_load():
            labelmap_widget = tables.tableWidget.cellWidget(row, labelmap_column)
            loadtable_widget = tables.tableWidget.cellWidget(row, loadtable_column)
            assert not labelmap_widget.layout().itemAt(0).widget().isChecked()
            assert not loadtable_widget.layout().itemAt(0).widget().isChecked()

        # Loading Table - vtkMRMLTableNode
        for row in tables.rows_to_load():
            # Set loadtable_column as True
            labelmap_widget = tableWidget.cellWidget(row, labelmap_column).layout().itemAt(0).widget()
            loadtable_widget = tableWidget.cellWidget(row, loadtable_column).layout().itemAt(0).widget()
            loadtable_widget.setChecked(True)
            assert not labelmap_widget.isChecked()
            assert loadtable_widget.isChecked()
        loadButton.clicked()

        # Loading Label - vtkMRMLLabelMapVolumeNode
        for row in tables.rows_to_load():
            # Set labelmap_column as True
            labelmap_widget = tableWidget.cellWidget(row, labelmap_column).layout().itemAt(0).widget()
            loadtable_widget = tableWidget.cellWidget(row, loadtable_column).layout().itemAt(0).widget()
            labelmap_widget.setChecked(True)
            assert labelmap_widget.isChecked()
            assert not loadtable_widget.isChecked()
        loadButton.clicked()

        # Verifiying if the node was loaded
        nodeVolume = tryGetNode("POCO_AMP [dB]")
        nodeTable = tryGetNode("AMP [dB]")
        nodeLabelMap = tryGetNode("POCO_AMP [dB]_LabelMap")
        assert isinstance(nodeVolume, slicer.vtkMRMLScalarVolumeNode)
        assert isinstance(nodeTable, slicer.vtkMRMLTableNode)
        assert isinstance(nodeLabelMap, slicer.vtkMRMLLabelMapVolumeNode)

        # Assert node attributes
        assert nodeVolume.GetAttribute("ScalarVolumeType") == "WellProfile"
        assert nodeTable.GetAttribute(TableDataTypeAttribute.name()) == TableDataTypeAttribute.IMAGE_2D.value
        assert nodeTable.GetAttribute(TableType.name()) == TableType.HISTOGRAM_IN_DEPTH.value

        assert metadata.Metadata(nodeVolume)[DLISImportConst.WELL_NAME_TAG] == "POCO"
        assert metadata.Metadata(nodeVolume)[DLISImportConst.LOGICAL_FILE_TAG] == "AMP"
        assert metadata.Metadata(nodeVolume)[DLISImportConst.ORIGIN_TAG] == "1"
        assert metadata.Metadata(nodeVolume)[DLISImportConst.FRAME_TAG] == "AMP"
        assert metadata.Metadata(nodeVolume)[DLISImportConst.UNITS_TAG] == "dB"

        assert metadata.Metadata(nodeTable)[DLISImportConst.WELL_NAME_TAG] == "POCO"
        assert metadata.Metadata(nodeTable)[DLISImportConst.LOGICAL_FILE_TAG] == "AMP"
        assert metadata.Metadata(nodeTable)[DLISImportConst.ORIGIN_TAG] == "1"
        assert metadata.Metadata(nodeTable)[DLISImportConst.FRAME_TAG] == "AMP"
        assert metadata.Metadata(nodeTable)[DLISImportConst.UNITS_TAG] == "dB"

        assert metadata.Metadata(nodeLabelMap)[DLISImportConst.WELL_NAME_TAG] == "POCO"
        assert metadata.Metadata(nodeLabelMap)[DLISImportConst.LOGICAL_FILE_TAG] == "AMP"
        assert metadata.Metadata(nodeLabelMap)[DLISImportConst.ORIGIN_TAG] == "1"
        assert metadata.Metadata(nodeLabelMap)[DLISImportConst.FRAME_TAG] == "AMP"
        assert metadata.Metadata(nodeLabelMap)[DLISImportConst.UNITS_TAG] == "dB"

        # Clear the filter
        clearFilterButton = self._widgets["Clear filter"]
        clearFilterButton.clicked()
        assert filterLineEdit.text == ""

        # Deselect all
        deselectButton = self._widgets["Deselect all"]
        deselectButton.clicked()
        rowsToLoad = self._module_widget.widget.tableView.rows_to_load()
        assert len(rowsToLoad) == 0

        # Test Checkbox LabelMap and As Table
        selectAllButton.clicked()
        rowsToLoad = self._module_widget.widget.tableView.rows_to_load()
        assert len(rowsToLoad) == 2

        # If the checkbox Table is checked, Labelmap must be unchecked
        for row in rowsToLoad:
            tableWidget.cellWidget(row, labelmap_column).layout().itemAt(0).widget().setChecked(True)
            tableWidget.cellWidget(row, loadtable_column).layout().itemAt(0).widget().setChecked(True)
            assert not tableWidget.cellWidget(row, labelmap_column).layout().itemAt(0).widget().isChecked()
            assert tableWidget.cellWidget(row, loadtable_column).layout().itemAt(0).widget().isChecked()

        # If the checkbox Labelmap is checked, Table must be unchecked
        for row in rowsToLoad:
            tableWidget.cellWidget(row, loadtable_column).layout().itemAt(0).widget().setChecked(True)
            tableWidget.cellWidget(row, labelmap_column).layout().itemAt(0).widget().setChecked(True)
            assert tableWidget.cellWidget(row, labelmap_column).layout().itemAt(0).widget().isChecked()
            assert not tableWidget.cellWidget(row, loadtable_column).layout().itemAt(0).widget().isChecked()

    def test_dlis_multiple_logical_files_and_origins(self):
        """
        Test if a more complex DLIS file is loaded correctly, which has multiple logical files, origins and frames
        """

        ioFileInputLineEdit = self._widgets["File Input"]
        ioFileInputLineEdit.setCurrentPath(SYNTHETIC_DLIS_FILE2)

        # Verifying the loaded well name
        wellNameInput = self._widgets["Well Name Input"]
        assert wellNameInput.text == "XYZ3"  # The last of the 3 wells contained in the file ("XYZ", "XYZ2" and "XYZ3")

        tableWidget = self._widgets["Table Widget"]
        # The 10 channels distributed in the logical files and frames
        assert tableWidget.rowCount == 10

        # Setting a required well diameter
        wellDiameter = self._widgets["Well Diameter Input"]
        wellDiameter.setText("8.5")  # dummy

        # Filter the items by "AMP" keyword
        """ filterLineEdit = self._widgets["Filter Input"]
        filterLineEdit.setText("AMP") """

        # Select all items
        selectAllButton = self._widgets["Select All Button"]
        selectAllButton.clicked()

        # Selecting all the rows after filtering must select just one row
        """ rowsToLoad = self._module_widget.widget.tableView.rows_to_load()
        assert len(rowsToLoad) == 1 """

        # Loading the curve - vtkMRMLScalarVolumeNode
        loadButton = self._widgets["Load Button"]
        loadButton.clicked()

        # Verifying if the nodes were loaded and their attributes were set correctly
        node = tryGetNode("DEPTH [m]")
        self.assertIsNotNone(node)
        assert metadata.Metadata(node)[DLISImportConst.WELL_NAME_TAG] == "XYZ"
        assert metadata.Metadata(node)[DLISImportConst.UNITS_TAG] == "m"
        assert metadata.Metadata(node)[DLISImportConst.FRAME_TAG] == "FRAME1"
        assert metadata.Metadata(node)[DLISImportConst.LOGICAL_FILE_TAG] == "LF1"
        assert metadata.Metadata(node)[DLISImportConst.ORIGIN_TAG] == "1"
        node = tryGetNode("RPM [None]")
        self.assertIsNotNone(node)
        # assert node.GetAttribute(DLISImportConst.WELL_NAME_TAG) == "XYZ"
        with pytest.raises(KeyError) as excinfo:
            metadata.Metadata(node)[DLISImportConst.UNITS_TAG] == "foo"
        assert excinfo.type is KeyError
        assert metadata.Metadata(node)[DLISImportConst.FRAME_TAG] == "FRAME1"
        assert metadata.Metadata(node)[DLISImportConst.LOGICAL_FILE_TAG] == "LF1"
        assert metadata.Metadata(node)[DLISImportConst.ORIGIN_TAG] == "1"

        # Note that, for volumes, we are appending the well name to the beginning of the node name
        node = tryGetNode("XYZ_AMPLITUDE [None]")
        self.assertIsNotNone(node)
        assert metadata.Metadata(node)[DLISImportConst.WELL_NAME_TAG] == "XYZ"
        with pytest.raises(KeyError) as excinfo:
            metadata.Metadata(node)[DLISImportConst.UNITS_TAG] == "foo"
        assert excinfo.type is KeyError
        assert metadata.Metadata(node)[DLISImportConst.FRAME_TAG] == "FRAME1"
        assert metadata.Metadata(node)[DLISImportConst.LOGICAL_FILE_TAG] == "LF1"
        assert metadata.Metadata(node)[DLISImportConst.ORIGIN_TAG] == "1"

        node = tryGetNode("COMPUTED_CHANNEL [None]")
        self.assertIsNotNone(node)
        assert metadata.Metadata(node)[DLISImportConst.WELL_NAME_TAG] == "XYZ"
        with pytest.raises(KeyError) as excinfo:
            metadata.Metadata(node)[DLISImportConst.UNITS_TAG] == "foo"
        assert excinfo.type is KeyError
        assert metadata.Metadata(node)[DLISImportConst.FRAME_TAG] == "FRAME1"
        assert metadata.Metadata(node)[DLISImportConst.LOGICAL_FILE_TAG] == "LF1"
        assert metadata.Metadata(node)[DLISImportConst.ORIGIN_TAG] == "1"
        node = tryGetNode("DEPTH2 [m]")
        self.assertIsNotNone(node)
        assert metadata.Metadata(node)[DLISImportConst.WELL_NAME_TAG] == "XYZ"
        assert metadata.Metadata(node)[DLISImportConst.UNITS_TAG] == "m"
        assert metadata.Metadata(node)[DLISImportConst.FRAME_TAG] == "FRAME2"
        assert metadata.Metadata(node)[DLISImportConst.LOGICAL_FILE_TAG] == "LF1"
        assert metadata.Metadata(node)[DLISImportConst.ORIGIN_TAG] == "1"
        node = tryGetNode("TEMPERATURE [degC]")
        self.assertIsNotNone(node)
        assert metadata.Metadata(node)[DLISImportConst.WELL_NAME_TAG] == "XYZ"
        assert metadata.Metadata(node)[DLISImportConst.UNITS_TAG] == "degC"
        assert metadata.Metadata(node)[DLISImportConst.FRAME_TAG] == "FRAME2"
        assert metadata.Metadata(node)[DLISImportConst.LOGICAL_FILE_TAG] == "LF1"
        assert metadata.Metadata(node)[DLISImportConst.ORIGIN_TAG] == "1"

        # Note that it's not possible to select curves from different wells. Because of that we
        # apply filters in filterLineEdit from these nodes on:

        filterLineEdit = self._widgets["Filter Input"]
        filterLineEdit.setText("DEPTH3")
        selectAllButton = self._widgets["Select All Button"]
        selectAllButton.clicked()
        loadButton.clicked()

        node = tryGetNode("DEPTH3 [m]")
        self.assertIsNotNone(node)
        assert metadata.Metadata(node)[DLISImportConst.WELL_NAME_TAG] == "XYZ2"
        assert metadata.Metadata(node)[DLISImportConst.UNITS_TAG] == "m"
        assert metadata.Metadata(node)[DLISImportConst.FRAME_TAG] == "FRAME3"
        assert metadata.Metadata(node)[DLISImportConst.LOGICAL_FILE_TAG] == "LF2"
        assert metadata.Metadata(node)[DLISImportConst.ORIGIN_TAG] == "2"
        filterLineEdit = self._widgets["Filter Input"]
        filterLineEdit.setText("TEMPERATURE2 [degC]")
        selectAllButton = self._widgets["Select All Button"]
        selectAllButton.clicked()
        loadButton.clicked()

        node = tryGetNode("TEMPERATURE2 [degC]")
        self.assertIsNotNone(node)
        assert metadata.Metadata(node)[DLISImportConst.WELL_NAME_TAG] == "XYZ2"
        assert metadata.Metadata(node)[DLISImportConst.UNITS_TAG] == "degC"
        assert metadata.Metadata(node)[DLISImportConst.FRAME_TAG] == "FRAME3"
        assert metadata.Metadata(node)[DLISImportConst.LOGICAL_FILE_TAG] == "LF2"
        assert metadata.Metadata(node)[DLISImportConst.ORIGIN_TAG] == "2"
        filterLineEdit = self._widgets["Filter Input"]
        filterLineEdit.setText("DEPTH4 [m]")
        selectAllButton = self._widgets["Select All Button"]
        selectAllButton.clicked()
        loadButton.clicked()

        node = tryGetNode("DEPTH4 [m]")
        self.assertIsNotNone(node)
        assert metadata.Metadata(node)[DLISImportConst.WELL_NAME_TAG] == "XYZ3"
        assert metadata.Metadata(node)[DLISImportConst.UNITS_TAG] == "m"
        assert metadata.Metadata(node)[DLISImportConst.FRAME_TAG] == "FRAME4"
        assert metadata.Metadata(node)[DLISImportConst.LOGICAL_FILE_TAG] == "LF2"
        assert metadata.Metadata(node)[DLISImportConst.ORIGIN_TAG] == "3"
        """
        # We have two nodes with this name, so this will never get selected this way
        filterLineEdit = self._widgets["Filter Input"]
        filterLineEdit.setText("RPM [None]")
        selectAllButton = self._widgets["Select All Button"]
        selectAllButton.clicked()
        loadButton.clicked()

        node = tryGetNode("RPM [None]")
        self.assertIsNotNone(node)
        assert node.GetAttribute(DLISImportConst.WELL_NAME_TAG) == "XYZ3"
        assert node.GetAttribute(DLISImportConst.UNITS_TAG) is None
        assert node.GetAttribute(DLISImportConst.FRAME_TAG) == "FRAME4"
        assert node.GetAttribute(DLISImportConst.LOGICAL_FILE_TAG) == "LF2"
        assert node.GetAttribute(DLISImportConst.ORIGIN_TAG) == "3" """

    def test_las_import(self):
        """
        Test if a LAS file is loaded correctly, with the expected metadata loaded results and final results.
        """

        # Setting the LAS file path
        ioFileInputLineEdit = self._widgets["File Input"]
        ioFileInputLineEdit.setCurrentPath(SYNTHETIC_LAS_FILE)

        # Verifying the loaded well name
        wellNameInput = self._widgets["Well Name Input"]
        assert wellNameInput.text == "#LTrace Test"

        # Setting a required well diameter
        wellDiameter = self._widgets["Well Diameter Input"]
        wellDiameter.setText("8.5")

        tableWidget = self._widgets["Table Widget"]
        # Two rows, DEPTH and AMP rows are loaded on this LAS file
        assert tableWidget.rowCount == 2

        # Filter the items by "INDEX" keyword
        filterLineEdit = self._widgets["Filter Input"]
        filterLineEdit.setText("INDEX")

        # Select all items
        selectAllButton = self._widgets["Select All Button"]
        selectAllButton.clicked()

        # Selecting all the rows after filtering must select just one row
        rowsToLoad = self._module_widget.widget.tableView.rows_to_load()
        assert len(rowsToLoad) == 1

        # Loading the curve
        loadButton = self._widgets["Load Button"]
        loadButton.clicked()

        # Verifying if the node was loaded
        node = tryGetNode("INDEX[m]")
        self.assertIsNotNone(node)

        # The array from the loaded node is just filled with ones. Checking that.
        Column = slicer.util.arrayFromTableColumn(node, node.GetColumnName(1))
        assert Column.all() == np.arange(1, 6).all()

        # Test LabelMap and As Table are Checked False
        tables = self._module_widget.widget.tableView
        labelmap_column = tables.columns.index("LabelMap")
        loadtable_column = tables.columns.index("As Table")
        for row in tables.rows_to_load():
            labelmap_widget = tables.tableWidget.cellWidget(row, labelmap_column)
            loadtable_widget = tables.tableWidget.cellWidget(row, loadtable_column)
            assert labelmap_widget is None or not labelmap_widget.layout().itemAt(0).widget().checked
            assert loadtable_widget is None or not loadtable_widget.layout().itemAt(0).widget().checked

        # Verifiying if the node was loaded
        assert isinstance(tryGetNode("INDEX[m]"), slicer.vtkMRMLTableNode)

        # Clear the filter
        clearFilterButton = self._widgets["Clear filter"]
        clearFilterButton.clicked()
        assert filterLineEdit.text == ""

        # Deselect all
        deselectButton = self._widgets["Deselect all"]
        deselectButton.clicked()
        rowsToLoad = self._module_widget.widget.tableView.rows_to_load()
        assert len(rowsToLoad) == 0

    def test_las_import_mixed(self):
        """
        test LAS file import, when it contains curves that are meant to be stacked into images and curves that are not
        """

        # Setting the LAS file path
        ioFileInputLineEdit = self._widgets["File Input"]
        ioFileInputLineEdit.setCurrentPath(SYNTHETIC_LAS_FILE_MIXED)

        # Verifying the loaded well name
        wellNameInput = self._widgets["Well Name Input"]
        assert wellNameInput.text == "TESTE"

        tableWidget = self._widgets["Table Widget"]
        # 21 rows: DEPT, 7 DTP rows, TESTE1, TESTE 2, 9 DTI rows, DTP:1 and DTP:2
        assert tableWidget.rowCount == 21

        # Setting a required well diameter
        wellDiameter = self._widgets["Well Diameter Input"]
        wellDiameter.setText("8.5")

        # Asserting all rows were loaded in the table view and that the stacked curves are condensed
        assert self.rowsFilteredBy("DEPT") == 1  # The depth curve
        assert (
            self.rowsFilteredBy("DTP") == 3
        )  # 7 DTP stacked curves condensed to one, plus DTP:1 and DTP:2 (the :1 and :2 is appended by lasio because the curves have the same name)
        assert self.rowsFilteredBy("TESTE") == 2  # TESTE 1 and TESTE2
        assert self.rowsFilteredBy("DTI") == 1  # 9 DTI stacked curves condensed to one

        # Loading all curves
        self.rowsFilteredBy("")  # Show all curves
        selectAllButton = self._widgets["Select All Button"]
        selectAllButton.clicked()
        loadButton = self._widgets["Load Button"]
        loadButton.clicked()

        # Checking the names and that the data is all 1's (it's artificial data for tests), except for the depth curve

        node = tryGetNode("TESTE_DTP[]")
        self.assertIsNotNone(node)
        array = slicer.util.arrayFromVolume(node)
        assert np.all(array == 1)

        node = tryGetNode("TESTE1[]")
        self.assertIsNotNone(node)
        column = slicer.util.arrayFromTableColumn(node, node.GetColumnName(1))
        assert column.all() == np.arange(1, len(column)).all()

        node = tryGetNode("TESTE2[]")
        self.assertIsNotNone(node)
        column = slicer.util.arrayFromTableColumn(node, node.GetColumnName(1))
        assert column.all() == np.arange(1, len(column)).all()

        node = tryGetNode("TESTE_DTI[]")
        self.assertIsNotNone(node)
        array = slicer.util.arrayFromVolume(node)
        assert np.all(array == 1)

        node = tryGetNode("DTP:1[]")
        self.assertIsNotNone(node)
        column = slicer.util.arrayFromTableColumn(node, node.GetColumnName(1))
        assert column.all() == np.arange(1, len(column)).all()

        node = tryGetNode("DTP:2[]")
        self.assertIsNotNone(node)
        column = slicer.util.arrayFromTableColumn(node, node.GetColumnName(1))
        assert column.all() == np.arange(1, len(column)).all()

        # Checking depth data (Slicer uses meters)
        depths = [
            5602050.00,
            5602450.00,
            5603100.00,
            5603450.00,
            5604000.00,
            5607350.00,
            5607950.00,
            5608600.00,
            5608850.00,
            5609200.00,
            5609450.00,
            5610350.00,
            5610450.00,
            5610650.00,
            5611050.00,
            5611800.00,
            5612100.00,
            5612450.00,
            5613200.00,
            5613500.00,
            5614550.00,
            5616150.00,
            5617050.00,
            5618350.00,
            5619000.00,
            5620150.00,
            5621050.00,
            5621750.00,
            5622050.00,
            5623100.00,
            5623650.00,
            5627250.00,
            5627950.00,
            5628250.00,
            5629900.00,
            5631100.00,
            5631550.00,
            5632000.00,
            5632300.00,
            5632950.00,
            5633800.00,
            5634550.00,
            5634900.00,
            5635500.00,
            5636400.00,
            5636650.00,
            5639300.00,
            5643600.00,
            5651100.00,
            5662300.00,
            5666400.00,
            5684200.00,
            5690000.00,
            5699500.00,
            5705100.00,
            5707300.00,
            5711100.00,
            5714400.00,
            5716700.00,
            5720400.00,
            5726300.00,
            5739500.00,
            5749300.00,
            5754000.00,
            5759000.00,
            5765500.00,
            5769200.00,
            5775250.00,
            5780150.00,
            5785150.00,
            5790000.00,
            5790650.00,
            5795050.00,
            5800050.00,
            5802000.00,
            5804700.00,
            5811500.00,
            5822100.00,
            5832700.00,
            5844800.00,
            5851100.00,
            5862000.00,
            5871000.00,
            5881200.00,
        ]

        self.assertIsNotNone(node)

        # TO-DO - MUSA-136 - review arrayPartsFromNode
        """ node_depths, node_data = arrayPartsFromNode(tryGetNode("TESTE_DTP[]"))
        half_spacing_z = tryGetNode("TESTE_DTP[]").GetSpacing()[2]/2.0
        node_depths = (1000.0*(node_depths -half_spacing_z))
        print(node_depths)
        print(tryGetNode("TESTE_DTP[]").GetSpacing())
        subtr = np.subtract(1000.0*(node_depths - half_spacing_z), depths)
        print(1000.0*node_depths - ((tryGetNode("TESTE_DTP[]").GetSpacing()[2])/2.0))
        print(subtr)
        assert len(node_depths[abs(subtr) > 1e-04]) == 0 """
        node_depths = slicer.util.arrayFromTableColumn(node, node.GetColumnName(0))
        subtr = np.subtract(node_depths, depths)

        assert len(node_depths[abs(subtr) > 1e-04]) == 0
        # Clear the filter
        clearFilterButton = self._widgets["Clear filter"]
        clearFilterButton.clicked()
        filterLineEdit = self._widgets["Filter Input"]
        assert filterLineEdit.text == ""

        # Deselect all
        deselectButton = self._widgets["Deselect all"]
        deselectButton.clicked()
        rowsToLoad = self._module_widget.widget.tableView.rows_to_load()
        assert len(rowsToLoad) == 0

    def test_csv_import(self):
        """
        Test if a CSV file is loaded correctly, with the expected metadata loaded results and final results.
        """

        # Setting the first CSV file path
        ioFileInputLineEdit = self._widgets["File Input"]
        name = "AMP.csv"
        SYNTHETIC_CSV_FILE = os.path.join(SYNTHETIC_CSV_PATH, name)
        ioFileInputLineEdit.setCurrentPath(SYNTHETIC_CSV_FILE)

        # Verifying the loaded well name
        wellNameInput = self._widgets["Well Name Input"]
        assert wellNameInput.text == "AMP"

        # Setting a required well diameter
        wellDiameter = self._widgets["Well Diameter Input"]
        wellDiameter.setText("8.5")  # dummy

        tableWidget = self._widgets["Table Widget"]
        # One row, INDEX row are loaded on this CSV file
        assert tableWidget.rowCount == 1

        # Filter the items by "Column" keyword
        # (When the CSV is represents 1D curves, the curves' Ids are set to begin with "Column ")
        filterLineEdit = self._widgets["Filter Input"]
        filterLineEdit.setText("Column 1")

        # Select all items
        selectAllButton = self._widgets["Select All Button"]
        selectAllButton.clicked()

        # Selecting all the rows after filtering must select just one row
        rowsToLoad = self._module_widget.widget.tableView.rows_to_load()
        assert len(rowsToLoad) == 1

        # Test LabelMap and As Table are Checked False
        tables = self._module_widget.widget.tableView
        labelmap_column = tables.columns.index("LabelMap")
        loadtable_column = tables.columns.index("As Table")
        for row in tables.rows_to_load():
            labelmap_widget = tables.tableWidget.cellWidget(row, labelmap_column)
            loadtable_widget = tables.tableWidget.cellWidget(row, loadtable_column)
            assert labelmap_widget is None or not labelmap_widget.layout().itemAt(0).widget().checked
            assert loadtable_widget is None or not loadtable_widget.layout().itemAt(0).widget().checked

        # Loading the curve
        loadButton = self._widgets["Load Button"]
        loadButton.clicked()

        # Verifying if the node was loaded
        node = tryGetNode("AMP")
        self.assertIsNotNone(node)

        # Verifiying if the node was loaded as vtkMRMLTableNode
        assert isinstance(node, slicer.vtkMRMLTableNode)

        # The array from the loaded node is just filled with ones. Checking that.
        Column = slicer.util.arrayFromTableColumn(node, node.GetColumnName(1))
        assert Column.all() == np.arange(1, 6).all()

        # Clear the filter
        clearFilterButton = self._widgets["Clear filter"]
        clearFilterButton.clicked()
        assert filterLineEdit.text == ""

        # Deselect all
        deselectButton = self._widgets["Deselect all"]
        deselectButton.clicked()
        rowsToLoad = self._module_widget.widget.tableView.rows_to_load()
        assert len(rowsToLoad) == 0

    def test_csv_labelmap(self):
        # Setting the first CSV file path
        ioFileInputLineEdit = self._widgets["File Input"]
        name = "AMP3.csv"
        SYNTHETIC_CSV_FILE = os.path.join(SYNTHETIC_CSV_PATH, name)
        ioFileInputLineEdit.setCurrentPath(SYNTHETIC_CSV_FILE)

        # Verifying the loaded well name - In CSV cases, we assume to be the file name
        wellNameInput = self._widgets["Well Name Input"]
        assert wellNameInput.text == "AMP3"

        # Setting a required well diameter
        wellDiameter = self._widgets["Well Diameter Input"]
        wellDiameter.setText("8.5")  # dummy

        tableWidget = self._widgets["Table Widget"]
        # One row, INDEX row are loaded on this CSV file
        assert tableWidget.rowCount == 1

        # When the CSV is comprised of 2D data, the curve Ids is set to "Image"
        filterLineEdit = self._widgets["Filter Input"]
        filterLineEdit.setText("Image")

        # Select all items
        selectAllButton = self._widgets["Select All Button"]
        selectAllButton.clicked()

        # Selecting all the rows after filtering must select just one row
        rowsToLoad = self._module_widget.widget.tableView.rows_to_load()
        assert len(rowsToLoad) == 1

        # Test LabelMap and As Table are not Checked; check LabelMap
        tables = self._module_widget.widget.tableView
        labelmap_column = tables.columns.index("LabelMap")
        loadtable_column = tables.columns.index("As Table")
        row = tables.rows_to_load()[0]
        labelmap_widget = tables.tableWidget.cellWidget(row, labelmap_column)
        loadtable_widget = tables.tableWidget.cellWidget(row, loadtable_column)
        assert labelmap_widget is None or not labelmap_widget.layout().itemAt(0).widget().checked
        assert loadtable_widget is None or not loadtable_widget.layout().itemAt(0).widget().checked

        tableWidget.cellWidget(row, labelmap_column).layout().itemAt(0).widget().setChecked(True)
        # (and make sure this didn't change "As Table")
        assert not tableWidget.cellWidget(row, loadtable_column).layout().itemAt(0).widget().isChecked()

        # Loading the curve
        selectAllButton.clicked()
        loadButton = self._widgets["Load Button"]
        loadButton.clicked()

        # Verifying if the node was loaded
        node = tryGetNode("AMP3")
        node = slicer.util.getNodes()["AMP3_INDEX_LabelMap"]
        self.assertIsNotNone(node)

        # Verifiying if the node was loaded as a LabelMap
        assert isinstance(node, slicer.vtkMRMLLabelMapVolumeNode)

        # Check the numerical data
        actual_data = [
            [1.00, 1.00, 1.00, 1.00, 1.00],
            [2.00, 2.00, 2.00, 2.00, 2.00],
            [3.00, 3.00, 3.00, 3.00, 3.00],
            [4.00, 4.00, 4.00, 4.00, 4.00],
            [5.00, 5.00, 5.00, 5.00, 5.00],
        ]
        depths, data = arrayPartsFromNode(node)
        # TO-DO - MUSA-136 - review arrayPartsFromNode
        # np.testing.assert_allclose(actual_depths, depths, rtol=0.5, atol=5e-06)
        np.testing.assert_allclose(actual_data, data, rtol=0.5, atol=5e-06)

        # Clear the filter
        clearFilterButton = self._widgets["Clear filter"]
        clearFilterButton.clicked()
        assert filterLineEdit.text == ""

        # Deselect all
        deselectButton = self._widgets["Deselect all"]
        deselectButton.clicked()
        rowsToLoad = self._module_widget.widget.tableView.rows_to_load()
        assert len(rowsToLoad) == 0

    def test_las_import_mixed_contents(self):
        """
        Consider a scene file and a LAS file, both containing an image (ScalarVolumeNode), a histogram in depth and a 1D curve.
        Compare the contents between the nodes loaded from the LAS file and from the scene file.

        Note that this deviation is almost always higher than the observed in ImageLogExportTest.
        - In those tests, the nodes are loaded from a scene file and then written to LAS again. The depth and data
        arrays returned from the writing function are then compared to the arrays extracted from the nodes
        - Here, the nodes are also loaded, from the same scene. But the depth and data arrays are obtained from
        reading a LAS file (that was created in the same way as the test above)
        - The conclusion is that this extra deviation is happening at the LAS importing stage
        Pay attention to whether this deviation (absolute tolerance 5e-06, rel. tolerance 0.5) can be tolerated or not.
        """
        # Load from scene

        load_project(ANONYMIZED_SCENE_FILE)

        vol_from_scene = slicer.util.getNode("DummyWell_DummyLogImage")
        vol_from_scene.SetName("vol_from_scene")

        depth_hist_from_scene = slicer.util.getNode("DummyWell_T2_DIST")
        depth_hist_from_scene.SetName("DummyWell_T2_DIST_from_scene")

        curve1D_from_scene = slicer.util.getNode("DummyWell_Dummy1D")
        curve1D_from_scene.SetName("curve1D_from_scene")

        # Load from LAS

        ioFileInputLineEdit = self._widgets["File Input"]
        ioFileInputLineEdit.setCurrentPath(ANONYMIZED_LAS_FILE)

        # Verifying the loaded well name
        wellNameInput = self._widgets["Well Name Input"]
        assert wellNameInput.text == "DummyWell"

        # Setting a required well diameter
        wellDiameter = self._widgets["Well Diameter Input"]
        wellDiameter.setText("8.5")

        # Load the nodes

        assert self.rowsFilteredBy("DUMMY1D") == 1
        self.loadAllSelected()
        assert wellNameInput.text == "DummyWell"
        curve1D_from_LAS = tryGetNode("DUMMY1D[ft3/ft3]")
        self.assertIsNotNone(curve1D_from_LAS)
        curve1D_from_LAS.SetName("curve1D_from_scene")

        assert self.rowsFilteredBy("T2_DIST") == 1
        self.loadAllSelected()
        assert wellNameInput.text == "DummyWell"
        depth_hist_from_LAS = tryGetNode("T2_DIST[ft3/ft3]")
        self.assertIsNotNone(depth_hist_from_LAS)
        depth_hist_from_LAS.SetName("DummyWell_T2_DIST_from_LAS")

        assert self.rowsFilteredBy("DUMMYLOGIMAGE") == 1
        self.loadAllSelected()
        assert wellNameInput.text == "DummyWell"
        vol_from_LAS = tryGetNode("DummyWell_DUMMYLOGIMAGE[ft3/ft3]")
        self.assertIsNotNone(vol_from_LAS)
        vol_from_LAS.SetName("vol_from_LAS")

        # Compare the nodes

        dataType = np.float64
        data_scene = self.__getArray(vol_from_scene, dataType)
        depths_scene = retrieve_depth_curve([vol_from_scene])
        data_LAS = self.__getArray(vol_from_LAS, dataType)
        depths_LAS = retrieve_depth_curve([vol_from_LAS])
        np.testing.assert_allclose(data_scene, data_LAS, rtol=0.5, atol=5e-06)
        np.testing.assert_allclose(depths_scene, depths_LAS, rtol=0.5, atol=5e-06)

        depths_scene, data_scene = arrayPartsFromNode(depth_hist_from_scene)
        depths_LAS, data_LAS = arrayPartsFromNode(depth_hist_from_LAS)
        np.testing.assert_allclose(data_scene, data_LAS, rtol=0.5, atol=5e-06)
        np.testing.assert_allclose(depths_scene, depths_LAS, rtol=0.5, atol=5e-06)

        depths_scene, data_scene = arrayPartsFromNode(curve1D_from_scene)
        depths_LAS, data_LAS = arrayPartsFromNode(curve1D_from_LAS)
        np.testing.assert_allclose(data_scene, data_LAS, rtol=0.5, atol=5e-06)
        np.testing.assert_allclose(depths_scene, depths_LAS, rtol=0.5, atol=5e-06)

        # Clear the filter
        clearFilterButton = self._widgets["Clear filter"]
        clearFilterButton.clicked()
        filterLineEdit = self._widgets["Filter Input"]
        assert filterLineEdit.text == ""

        # Deselect all
        deselectButton = self._widgets["Deselect all"]
        deselectButton.clicked()
        rowsToLoad = self._module_widget.widget.tableView.rows_to_load()
        assert len(rowsToLoad) == 0

    def test_null_values_handling(self):
        nullValuesText = self._widgets["Null Values List Text"]
        ioFileInputLineEdit = self._widgets["File Input"]
        resetNullValuesListButton = self._widgets["Reset Null Values List Button"]

        # Check resetNullValuesListButton:

        nullValuesText.text = "dummy text"
        resetNullValuesListButton.clicked()
        nstr = nullValuesText.text
        assert len(nstr) == 26
        assert "-999.25" in nstr
        assert "-9999.25" in nstr
        assert "-9999.0" in nstr

        # Check ioFileInputLineEdit before and after a loader is created, and also loaded nodes' NullValue attribute:

        # DLIS

        resetNullValuesListButton.clicked()
        ioFileInputLineEdit.setCurrentPath(SYNTHETIC_DLIS_FILE)
        # Setting a required well diameter
        wellDiameter = self._widgets["Well Diameter Input"]
        wellDiameter.setText("8.5")

        # Select all items
        selectAllButton = self._widgets["Select All Button"]
        selectAllButton.clicked()
        # Loading the data
        loadButton = self._widgets["Load Button"]
        loadButton.clicked()

        node = tryGetNode("POCO_AMP [dB]")
        self.assertIsNotNone(node)
        assert (
            node.GetAttribute("NullValue") == "-999.25"
        )  # For volumes loaded by our ImageLogImport module, the NullValue is always ANP_880_2022_DEFAULT_NULL_VALUE

        node = tryGetNode("INDEX [m]")
        self.assertIsNotNone(node)
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        #  For tables, the NullValue attribute is set in the hierarchy, not in the node...
        nullValuesAttr = node.GetAttribute("NullValue")
        assert nullValuesAttr is None
        imageItem = shNode.GetItemByDataNode(node)
        nullValuesAttr = shNode.GetItemAttribute(imageItem, "NullValue")
        # ... so it is the same as that in the interface's ioFileInputLineEdit
        assert len(nullValuesAttr) == 28  # 26 + '{' and '}'
        assert "-999.25" in nullValuesAttr
        assert "-9999.25" in nullValuesAttr
        assert "-9999.0" in nullValuesAttr

        # CSV

        resetNullValuesListButton.clicked()
        ioFileInputLineEdit.setCurrentPath(os.path.join(SYNTHETIC_CSV_PATH, "AMP.csv"))
        # Select all items
        selectAllButton = self._widgets["Select All Button"]
        selectAllButton.clicked()
        # Loading the curve
        loadButton = self._widgets["Load Button"]
        loadButton.clicked()
        node = tryGetNode("AMP")
        self.assertIsNotNone(node)
        #  For tables, the NullValue attribute is set in the hierarchy, not in the node...
        nullValuesAttr = node.GetAttribute("NullValue")
        assert nullValuesAttr is None
        imageItem = shNode.GetItemByDataNode(node)
        nullValuesAttr = shNode.GetItemAttribute(imageItem, "NullValue")
        # ... so it is the same as that in the interface's ioFileInputLineEdit
        assert len(nullValuesAttr) == 28  # 26 + '{' and '}'
        assert "-999.25" in nullValuesAttr
        assert "-9999.25" in nullValuesAttr
        assert "-9999.0" in nullValuesAttr

        # LAS

        resetNullValuesListButton.clicked()
        ioFileInputLineEdit.setCurrentPath(SYNTHETIC_LAS_FILE)
        # Select all items
        selectAllButton = self._widgets["Select All Button"]
        selectAllButton.clicked()
        # Loading the curve
        loadButton = self._widgets["Load Button"]
        loadButton.clicked()
        node = tryGetNode("AMP")
        self.assertIsNotNone(node)

        #  For tables, the NullValue attribute is set in the hierarchy, not in the node...
        nullValuesAttr = node.GetAttribute("NullValue")
        assert nullValuesAttr is None
        imageItem = shNode.GetItemByDataNode(node)
        nullValuesAttr = shNode.GetItemAttribute(imageItem, "NullValue")
        # ... so it is the same as that in the interface's ioFileInputLineEdit
        assert len(nullValuesAttr) == 28  # 26 + '{' and '}'
        assert "-999.25" in nullValuesAttr
        assert "-9999.25" in nullValuesAttr
        assert "-9999.0" in nullValuesAttr

        # LAS again - check if NULL attribute of the LAS file got added to ioFileInputLineEdit

        ioFileInputLineEdit.setCurrentPath("")
        nullValuesText.text = "-9999.25"
        ioFileInputLineEdit.setCurrentPath(SYNTHETIC_LAS_FILE)
        nstr = nullValuesText.text
        assert len(nstr.split(",")) == 2
        assert len(nstr) == 17
        assert "-999.25" in nstr
        assert "-9999.25" in nstr

    def test_dlis_labelmap_null_values(self):
        """A null value must not survive the conversion to labels, in value or in color table size."""
        path = write_synthetic_dlis("labels_with_nulls.dlis", [("SYNTHWELL", labels_image(-9999.0), None)])

        self._widgets["File Input"].setCurrentPath(path)
        self._widgets["Well Diameter Input"].setText("8.5")
        self._widgets["Filter Input"].setText("SEG1")
        self._widgets["Select All Button"].clicked()

        tables = self._module_widget.widget.tableView
        row = tables.rows_to_load()[0]
        labelmapColumn = tables.columns.index("LabelMap")
        tables.tableWidget.cellWidget(row, labelmapColumn).layout().itemAt(0).widget().setChecked(True)
        self._widgets["Select All Button"].clicked()
        self._widgets["Load Button"].clicked()

        nodes = list(slicer.util.getNodesByClass("vtkMRMLLabelMapVolumeNode"))
        assert len(nodes) == 1
        array = slicer.util.arrayFromVolume(nodes[0])
        assert np.array_equal(np.unique(array), np.arange(5))
        assert nodes[0].GetDisplayNode().GetColorNode().GetNumberOfColors() == 5
        assert getVolumeNullValue(nodes[0]) is None

    def test_labelmap_without_declared_null_values(self):
        """Negative and non-finite values are labelmap nulls whether the user declared them or not."""
        data = np.array([-1.0, np.nan, np.inf, -np.inf, 1.0, 2.0], dtype=np.float32).reshape(6, 1, 1)

        node, _ = add_volume_from_data(
            root_folder="Synthetic",
            folder="LF1",
            name="AUTO_NULLS",
            frame="FRAME1",
            data=data,
            is_labelmap=True,
            well_name="SYNTHWELL",
        )

        array = slicer.util.arrayFromVolume(node)
        assert np.array_equal(np.unique(array), [0, 1, 2])

    def test_labelmap_declared_null_values(self):
        """Declared null values are compared against the original data, before it is quantized."""
        data = np.array([-9999.0, np.nan, 1.0, 2.0, 3.0], dtype=np.float32).reshape(5, 1, 1)

        node, _ = add_volume_from_data(
            root_folder="Synthetic",
            folder="LF1",
            name="DECLARED_NULLS",
            frame="FRAME1",
            data=data,
            is_labelmap=True,
            nullValue={-9999.0, float("nan")},
            well_name="SYNTHWELL",
        )

        array = slicer.util.arrayFromVolume(node)
        assert np.array_equal(np.unique(array), [0, 1, 2, 3])
        assert getVolumeNullValue(node) is None

    def test_dlis_absent_value_merge(self):
        """Every ABSENT_VALUE declared by the file joins the user's list, without changing the defaults."""
        path = write_synthetic_dlis(
            "absent_values.dlis",
            [
                ("WELL1", labels_image(-1234.5), [-1234.5, -4321.0]),
                ("WELL2", labels_image(-5678.0), [-5678.0]),
            ],
        )
        defaultNullValues = set(DEFAULT_NULL_VALUES)

        self._widgets["Reset Null Values List Button"].clicked()
        self._widgets["File Input"].setCurrentPath(path)

        listed = {float(item) for item in self._widgets["Null Values List Text"].text.split(",")}
        assert listed == defaultNullValues | {-1234.5, -4321.0, -5678.0}
        assert DEFAULT_NULL_VALUES == defaultNullValues

    def test_null_values_field_parsing(self):
        """The field is parsed the same way on path change and on load, without dialogs or exceptions."""
        nullValuesText = self._widgets["Null Values List Text"]
        ioFileInputLineEdit = self._widgets["File Input"]
        self._widgets["Well Diameter Input"].setText("8.5")

        with patch("slicer.util.warningDisplay") as warningDisplay:
            # A blank item flags the field instead of discarding the list
            nullValuesText.text = ", -9999.0"
            ioFileInputLineEdit.setCurrentPath(SYNTHETIC_DLIS_FILE)
            assert nullValuesText.styleSheet != ""
            assert nullValuesText.text == ", -9999.0"

            # A well-formed list survives the path change
            nullValuesText.text = "-9999.0"
            ioFileInputLineEdit.setCurrentPath(SYNTHETIC_LAS_FILE)
            assert -9999.0 in {float(item) for item in nullValuesText.text.split(",")}

            # Malformed text flags the field on load too, instead of raising
            nullValuesText.text = "not a number"
            self._widgets["Well Diameter Input"].setText("8.5")  # the path change above cleared it
            self._module_widget.widget.onLoadClicked([])
            assert nullValuesText.styleSheet != ""

            # An empty field means no null values, not a missing input
            nullValuesText.text = ""
            self._module_widget.widget.onLoadClicked([])
            assert nullValuesText.styleSheet == ""

            warningDisplay.assert_not_called()

    def rowsFilteredBy(self, filter):
        filterLineEdit = self._widgets["Filter Input"]
        filterLineEdit.setText(filter)

        # Select all items
        selectAllButton = self._widgets["Select All Button"]
        selectAllButton.clicked()

        # Selecting all the rows after filtering must select just one row
        return len(self._module_widget.widget.tableView.rows_to_load())

    def loadAllSelected(self):
        selectAllButton = self._widgets["Select All Button"]
        selectAllButton.clicked()
        loadButton = self._widgets["Load Button"]
        loadButton.clicked()

    def __getArray(self, node: slicer.vtkMRMLNode, dtype) -> np.ndarray:
        """Helper method to get the array from the node with adapted null values.

        Args:
            node (slicer.vtkMRMLNode): the input node object.

        Returns:
            np.ndarray: the array with modified null values.
        """
        if isinstance(node, slicer.vtkMRMLSegmentationNode):
            nodeData = arrayFromVisibleSegmentsBinaryLabelmap(node)[0].squeeze().astype(dtype)
        else:
            nodeData = slicer.util.arrayFromVolume(node).squeeze().astype(dtype)

        nullValue = getVolumeNullValue(node) or 0
        nullIndexes = np.where(nodeData == nullValue)
        nodeData[nullIndexes] = ANP_880_2022_DEFAULT_NULL_VALUE

        return nodeData
