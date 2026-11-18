import numpy as np
import slicer
import shutil
import tempfile
import os
import qt
import lasio
import vtk

from dlisio import dlis
from commons.slicer.helpers import (
    arrayFromVisibleSegmentsBinaryLabelmap,
    arrayPartsFromNode,
    tryGetNode,
    getAttributeFromNodeOrReferencedNode,
)
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, process_events
from commons.image.dlis import export_dlis, extract_dlis_info_from_node, logger
from commons.image.las import export_las, retrieve_depth_curve
from pathlib import Path

from commons.image.optimized_transforms import handle_null_values, ANP_880_2022_DEFAULT_NULL_VALUE
from commons.slicer import metadata
from commons.constants import DLISImportConst

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
UBIAMP_PROJECT_FILE = TEST_RESOURCES_DIR / "UBI_AMP" / "UBI_AMP.mrml"
ANONYMIZED_SCENE_FILE = os.path.join(
    TEST_RESOURCES_DIR, "ANONYMIZED_DATA_vol_label_curve_and_hist", "ANONYMIZED_SCENE_vol_label_curve_and_hist.mrml"
)
COMPLEX_SCENE_FILE = os.path.join(
    TEST_RESOURCES_DIR, "nodes_from_LAS_CSV_DLIS_multiple_wells", "nodes_from_LAS_CSV_DLIS_multiple_wells.mrml"
)
EXPORT_TEMP_DIR = Path(tempfile.TemporaryDirectory().name)

DATA_TOLERANCE_HIGH = 1e-10  # In fact the data to which we test for this tolerance pass the np.testing.assert_array_equal, but we shouldn't compare floats without a margin
DATA_TOLERANCE_LOW = 1e-05  # Some data are degraded. Pay attention to whether this deviation can be tolerated or not.


class ImageLogExportTest(LTracePluginTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def post_setup(self):
        """Test suite setup"""
        EXPORT_TEMP_DIR.mkdir(parents=True, exist_ok=True)

        self._widgets = {
            "logComboBox": self.find_widget("Log Format ComboBox"),
            "tableComboBox": self.find_widget("Table Format ComboBox"),
            "ignoreStructureCheckBox": self.find_widget("Ignore Structure CheckBox"),
            "directorySelector": self.find_widget("Directory Selector"),
            "treeView": self.find_widget("Tree View"),
            "proportionsCheckBox": self.find_widget("Proportions CheckBox"),
            "exportButton": self.find_widget("Export Button"),
        }

    def tear_down(self) -> None:
        """Test suite tear down"""

        if EXPORT_TEMP_DIR.exists():
            handlers = logger.handlers[:]
            for handler in handlers:
                logger.removeHandler(handler)
                handler.close()
            shutil.rmtree(EXPORT_TEMP_DIR)

    def export_node_to_dlis(self, input_node):
        """Helper method to export node to dlis and retrieve its data

        Args:
            input_node (slicer.vtkMRMLNode): the node object.

        Returns:
            np.ndarray: the array from exported dlis file.
        """

        image_name = input_node.GetName()
        output_file = (EXPORT_TEMP_DIR / image_name).as_posix()

        print(f"exporting {image_name} to dlis")

        export_dlis(
            [input_node],
            EXPORT_TEMP_DIR,
            image_name,
            EXPORT_TEMP_DIR,
        )

        # Get DLIS data
        dlis_reader = dlis.load(f"{output_file}.dlis")
        dlis_data = dlis_reader[0].channels[1].curves()  # channel 0 will be the depths\
        dlis_reader.close()

        dlis_info_from_node = extract_dlis_info_from_node(input_node)

        return dlis_data, dlis_info_from_node["units"], dlis_info_from_node["well_name"]

    def export_node_to_las(self, input_node):
        """Helper method to export node to LAS and retrieve its data

        Args:
            input_node (slicer.vtkMRMLNode): the node object.

        Returns:
            np.ndarray: the array from exported LAS file.
        """
        image_name = input_node.GetName()
        output_file = (EXPORT_TEMP_DIR / image_name).as_posix()

        # Export LAS file
        export_las([input_node], f"{output_file}.las")

        # Get LAS data
        las_reader = lasio.read(f"{output_file}.las")
        las_data = np.array(las_reader.values()).transpose()[:, 1:]
        las_depths = np.array(las_reader.values()).transpose()[:, 0]

        return las_depths, las_data

    def _handleNulls(self, data, isSegmentation, nullValues) -> np.ndarray:
        if isSegmentation:
            for value in nullValues:
                value = int(value)
                data[np.where(data == int(value))] = 0
        else:
            if nullValues is not None:
                handle_null_values(data, nullValues)

    def __get_array(self, node: slicer.vtkMRMLNode, nullValues: set, dtype) -> np.ndarray:
        """Helper method to get the array from the node with adapted null values.

        Args:
            node (slicer.vtkMRMLNode): the input node object.

        Returns:
            np.ndarray: the array with modified null values.
        """
        if isinstance(node, slicer.vtkMRMLSegmentationNode):
            node_data = arrayFromVisibleSegmentsBinaryLabelmap(node)[0].squeeze().astype(dtype)
        else:
            node_data = slicer.util.arrayFromVolume(node).squeeze().astype(dtype)

        # In a similar fashion as in ImageLogImportLogic, addVolumeFromData:
        if isinstance(node, slicer.vtkMRMLLabelMapVolumeNode) or isinstance(node, slicer.vtkMRMLSegmentationNode):
            for value in nullValues:
                value = int(value)
                node_data[np.where(node_data == value)] = 0
        else:
            if nullValues is not None:
                handle_null_values(node_data, nullValues)

        return node_data

    def test_export_through_interface(self):
        load_project(UBIAMP_PROJECT_FILE)
        input_node = slicer.util.getNode("UBI_AMP")

        treeView = self._widgets["treeView"]
        ignoreStructureCheckBox = self._widgets["ignoreStructureCheckBox"]
        logComboBox = self._widgets["logComboBox"]
        directorySelector = self._widgets["directorySelector"]
        exportButton = self._widgets["exportButton"]

        scene = slicer.app.mrmlScene()
        itemList = vtk.vtkIdList()
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(scene)
        itemList.InsertNextId(subjectHierarchyNode.GetItemByName(input_node.GetName()))
        treeView.setCurrentItems(itemList)

        output_file = Path(EXPORT_TEMP_DIR)
        directorySelector.directory = output_file.as_posix()

        logComboBox.currentText == "DLIS"
        ignoreStructureCheckBox.setChecked(qt.Qt.Unchecked)

        exportButton.clicked()
        process_events()

        assert (output_file / "Well Logs/AMP" / f"{input_node.GetName()}.dlis").is_file()

        ignoreStructureCheckBox.setChecked(qt.Qt.Checked)
        exportButton.clicked()
        process_events()

        assert (output_file / f"{input_node.GetName()}.dlis").is_file()

    def test_export_dlis(self):
        load_project(UBIAMP_PROJECT_FILE)
        input_node = slicer.util.getNode("UBI_AMP")
        np.testing.assert_equal(float(metadata.Metadata(input_node)[DLISImportConst.NULL_VALUE_TAG]), -91.0)

        dlis_data, units, well_name = self.export_node_to_dlis(input_node)
        self._handleNulls(dlis_data, isSegmentation=False, nullValues={ANP_880_2022_DEFAULT_NULL_VALUE})

        node_data = self.__get_array(
            input_node,
            nullValues={ANP_880_2022_DEFAULT_NULL_VALUE},
            dtype=dlis_data.dtype,  # -91.0
        )  # this node comes from the MRML scene with this atypical invalid value

        np.testing.assert_array_equal(node_data, dlis_data)

        if DLISImportConst.UNITS_TAG in metadata.Metadata(input_node):
            assert units == metadata.Metadata(input_node)[DLISImportConst.UNITS_TAG]
        else:
            assert units == "NONE"

        if DLISImportConst.WELL_NAME_TAG in metadata.Metadata(input_node):
            assert well_name == metadata.Metadata(input_node)[DLISImportConst.WELL_NAME_TAG]
        else:
            assert well_name == "UBI", (
                "No `WellName` attribute in the node. `UBI` well name got inferred from the node name `UBI_AMP` (extract_dlis_info_from_node method)."
            )

    def test_export_complex_scene_to_dlis(self):
        """
        Export to a single DLIS file a scene that contains nodes that span several logical files, origins, frames and wells, and
        nodes that were imported from DLIS, CSV and LAS files.
        This will test if the nodes were written to the file and if the logical files, origins, frames, and wells were preserved at
        export (in the import side, this is tested in ImageLogImportTest.py)
        """

        load_project(COMPLEX_SCENE_FILE)

        # 1. Verifying if the nodes were loaded and their attributes were set correctly
        scene_nodes = []

        scene_nodes.append(slicer.util.getNodes()["DEPTH [m]"])
        self.assertIsNotNone(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.WELL_NAME_TAG] == "XYZ"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.UNITS_TAG] == "m"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.FRAME_TAG] == "FRAME1"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.LOGICAL_FILE_TAG] == "LF1"

        """ There are two nodes named "RPM [None]". tryGetNode("RPM [None]") will get the last one, not this
        node = tryGetNode("RPM [None]")
        self.assertIsNotNone(node)
        # assert node.GetAttribute(DLISImportConst.WELL_NAME_TAG) == "XYZ"
        assert node.GetAttribute(DLISImportConst.UNITS_TAG) is None
        assert node.GetAttribute(DLISImportConst.FRAME_TAG) == "FRAME1"
        assert node.GetAttribute(DLISImportConst.LOGICAL_FILE_TAG) == "LF1"
        """
        # Note that, for volumes, we are appending the well name to the beginning of the node name
        scene_nodes.append(slicer.util.getNodes()["XYZ_AMPLITUDE [None]"])
        self.assertIsNotNone(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.WELL_NAME_TAG] == "XYZ"
        assert DLISImportConst.UNITS_TAG not in metadata.Metadata(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.FRAME_TAG] == "FRAME1"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.LOGICAL_FILE_TAG] == "LF1"

        scene_nodes.append(slicer.util.getNodes()["COMPUTED_CHANNEL [None]"])
        self.assertIsNotNone(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.WELL_NAME_TAG] == "XYZ"
        assert DLISImportConst.UNITS_TAG not in metadata.Metadata(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.FRAME_TAG] == "FRAME1"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.LOGICAL_FILE_TAG] == "LF1"
        scene_nodes.append(slicer.util.getNodes()["DEPTH2 [m]"])
        self.assertIsNotNone(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.WELL_NAME_TAG] == "XYZ"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.UNITS_TAG] == "m"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.FRAME_TAG] == "FRAME2"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.LOGICAL_FILE_TAG] == "LF1"
        scene_nodes.append(slicer.util.getNodes()["TEMPERATURE [degC]"])
        self.assertIsNotNone(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.WELL_NAME_TAG] == "XYZ"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.UNITS_TAG] == "degC"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.FRAME_TAG] == "FRAME2"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.LOGICAL_FILE_TAG] == "LF1"
        scene_nodes.append(slicer.util.getNodes()["DEPTH3 [m]"])
        self.assertIsNotNone(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.WELL_NAME_TAG] == "XYZ2"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.UNITS_TAG] == "m"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.FRAME_TAG] == "FRAME3"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.LOGICAL_FILE_TAG] == "LF2"
        scene_nodes.append(slicer.util.getNodes()["TEMPERATURE2 [degC]"])
        self.assertIsNotNone(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.WELL_NAME_TAG] == "XYZ2"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.UNITS_TAG] == "degC"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.FRAME_TAG] == "FRAME3"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.LOGICAL_FILE_TAG] == "LF2"
        scene_nodes.append(slicer.util.getNodes()["DEPTH4 [m]"])
        self.assertIsNotNone(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.WELL_NAME_TAG] == "XYZ3"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.UNITS_TAG] == "m"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.FRAME_TAG] == "FRAME4"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.LOGICAL_FILE_TAG] == "LF2"
        scene_nodes.append(slicer.util.getNodes()["RPM [None]"])
        self.assertIsNotNone(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.WELL_NAME_TAG] == "XYZ3"
        assert DLISImportConst.UNITS_TAG not in metadata.Metadata(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.FRAME_TAG] == "FRAME4"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.LOGICAL_FILE_TAG] == "LF2"

        #
        # scene_nodes originated from LAS file

        scene_nodes.append(slicer.util.getNodes()["DUMMY1D[ft3/ft3]"])
        self.assertIsNotNone(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.WELL_NAME_TAG] == "DummyWell"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.UNITS_TAG] == "ft3/ft3"
        assert DLISImportConst.FRAME_TAG not in metadata.Metadata(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.LOGICAL_FILE_TAG] == "DummyWell"

        scene_nodes.append(slicer.util.getNodes()["T2_DIST[ft3/ft3]"])
        self.assertIsNotNone(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.WELL_NAME_TAG] == "DummyWell"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.UNITS_TAG] == "ft3/ft3"
        assert DLISImportConst.FRAME_TAG not in metadata.Metadata(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.LOGICAL_FILE_TAG] == "DummyWell"

        scene_nodes.append(slicer.util.getNodes()["DummyWell_DUMMYLOGIMAGE[ft3/ft3]"])
        self.assertIsNotNone(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.WELL_NAME_TAG] == "DummyWell"
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.UNITS_TAG] == "ft3/ft3"
        assert DLISImportConst.FRAME_TAG not in metadata.Metadata(scene_nodes[-1])
        assert metadata.Metadata(scene_nodes[-1])[DLISImportConst.LOGICAL_FILE_TAG] == "DummyWell"

        #
        # Node originated from CSV file

        scene_nodes.append(slicer.util.getNodes()["AMP_2"])
        self.assertIsNotNone(scene_nodes[-1])
        assert scene_nodes[-1].GetAttribute(DLISImportConst.WELL_NAME_TAG) == "AMP_2"
        assert DLISImportConst.UNITS_TAG not in metadata.Metadata(scene_nodes[-1])
        assert DLISImportConst.FRAME_TAG not in metadata.Metadata(scene_nodes[-1])
        assert scene_nodes[-1].GetAttribute(DLISImportConst.LOGICAL_FILE_TAG) == "AMP_2"

        # 2. Writing the nodes to a DLIS file (dliswriter lib)

        fname_no_extension = "complex_scene"

        export_dlis(
            scene_nodes,
            EXPORT_TEMP_DIR,
            fname_no_extension,
            EXPORT_TEMP_DIR,
            allow_multiple_wells=True,
        )

        output_file = (EXPORT_TEMP_DIR / fname_no_extension).as_posix()

        # 3. And then reading (with dlisio lib) the DLIS file just written and asserting the data are there

        logical_files = dlis.load(f"{output_file}.dlis")

        assert len(logical_files) == 4

        assert logical_files[0].origins[0].file_id == "LF1"
        assert logical_files[1].origins[0].file_id == "LF2"
        assert logical_files[1].origins[1].file_id == "LF2"
        assert logical_files[2].origins[0].file_id == "DummyWell"
        assert logical_files[3].origins[0].file_id == "AMP_2"

        assert logical_files[0].origins[0].well_name == "XYZ"
        assert logical_files[1].origins[0].well_name == "XYZ2"
        assert logical_files[1].origins[1].well_name == "XYZ3"
        assert logical_files[2].origins[0].well_name == "DummyWell"
        assert logical_files[3].origins[0].well_name == "AMP_2"

        found = False
        for channel in logical_files[0].channels:
            if channel.name == "DEPTH [m]":
                found = True
                break
        assert found
        assert channel.frame.name == "FRAME1"
        assert channel.units == "m"
        assert channel.origin == 1

        found = False
        for channel in logical_files[0].channels:
            if channel.name == "XYZ_AMPLITUDE [None]":
                found = True
                break
        assert found
        assert channel.frame.name == "FRAME1"
        assert channel.units == "None"
        assert channel.origin == 1

        found = False
        for channel in logical_files[0].channels:
            if channel.name == "COMPUTED_CHANNEL [None]":
                found = True
                break
        assert found
        assert channel.frame.name == "FRAME1"
        assert channel.units == "None"
        assert channel.origin == 1

        found = False
        for channel in logical_files[0].channels:
            if channel.name == "DEPTH2 [m]":
                found = True
                break
        assert found
        assert channel.frame.name == "FRAME2"
        assert channel.units == "m"
        assert channel.origin == 1

        found = False
        for channel in logical_files[0].channels:
            if channel.name == "TEMPERATURE [degC]":
                found = True
                break
        assert found
        assert channel.frame.name == "FRAME2"
        assert channel.units == "degC"
        assert channel.origin == 1

        found = False
        for channel in logical_files[1].channels:
            if channel.name == "DEPTH3 [m]":
                found = True
                break
        assert found
        assert channel.frame.name == "FRAME3"
        assert channel.units == "m"
        assert channel.origin == 2

        found = False
        for channel in logical_files[1].channels:
            if channel.name == "TEMPERATURE2 [degC]":
                found = True
                break
        assert found
        assert channel.frame.name == "FRAME3"
        assert channel.units == "degC"
        assert channel.origin == 2

        found = False
        for channel in logical_files[1].channels:
            if channel.name == "DEPTH4 [m]":
                found = True
                break
        assert found
        assert channel.frame.name == "FRAME4"
        assert channel.units == "m"
        assert channel.origin == 3

        found = False
        for channel in logical_files[1].channels:
            if channel.name == "RPM [None]":
                found = True
                break
        assert found
        assert channel.frame.name == "FRAME4"
        assert channel.units == "None"
        assert channel.origin == 3

        # The nodes below came from a LAS file, and hence have no "Frame" attribute.
        # It is set to its directory in the MRML hierarchy in dlis.py's extract_dlis_info_from_node.
        # In the case below, "ANONYMIZED__vol_label_curve_and_hist"

        found = False
        for channel in logical_files[2].channels:
            if channel.name == "DUMMY1D[ft3/ft3]":
                found = True
                break
        assert found
        assert channel.frame.name == "ANONYMIZED__vol_label_curve_and_hist"
        assert channel.units == "ft3/ft3"
        assert channel.origin == 0

        found = False
        for channel in logical_files[2].channels:
            if channel.name == "T2_DIST[ft3/ft3]":
                found = True
                break
        assert found
        assert channel.frame.name == "ANONYMIZED__vol_label_curve_and_hist"
        assert channel.units == "ft3/ft3"
        assert channel.origin == 0

        found = False
        for channel in logical_files[2].channels:
            if channel.name == "DummyWell_DUMMYLOGIMAGE[ft3/ft3]":
                found = True
                break
        assert found
        assert channel.frame.name == "ANONYMIZED__vol_label_curve_and_hist"
        assert channel.units == "ft3/ft3"
        assert channel.origin == 0

        # The node below came from a LAS file, and hence have no "Frame" attribute.
        # It is set to its directory in the MRML hierarchy in dlis.py's extract_dlis_info_from_node.
        # In the case below, "AMP_2"

        found = False
        for channel in logical_files[3].channels:
            if channel.name == "AMP_2":
                found = True
                break
        assert found
        assert channel.frame.name == "AMP_2"
        assert channel.units == "NONE"
        assert channel.origin == 0

        logical_files.close()

    def test_export_las(self):
        load_project(ANONYMIZED_SCENE_FILE)
        input_node = slicer.util.getNode("DummyWell_DummyLogImage")
        las_depths, las_data = self.export_node_to_las(input_node)
        self._handleNulls(las_data, isinstance(input_node, slicer.vtkMRMLSegmentationNode), {-9999.25})

        node_data = self.__get_array(input_node, {-9999.25}, las_data.dtype)
        node_depths = retrieve_depth_curve([input_node])

        # NOTE - Precision degraded...
        np.testing.assert_allclose(node_data, las_data, rtol=0.5, atol=5e-06)

        # NOTE - Precision degraded... Here we expect some deviation because depths from volumes are re-generated
        subtr = np.subtract(node_depths, las_depths)
        assert len(node_depths[abs(subtr) > DATA_TOLERANCE_LOW]) == 0

    def test_export_labelmap_to_dlis(self):
        load_project(UBIAMP_PROJECT_FILE)
        input_node = slicer.util.getNode("Segmentation-label")
        dlis_data, units, well_name = self.export_node_to_dlis(input_node)
        self._handleNulls(dlis_data, isSegmentation=True, nullValues={ANP_880_2022_DEFAULT_NULL_VALUE})

        node_data = self.__get_array(input_node, nullValues={ANP_880_2022_DEFAULT_NULL_VALUE}, dtype=dlis_data.dtype)

        np.testing.assert_array_equal(node_data, dlis_data)

        if getAttributeFromNodeOrReferencedNode(input_node, DLISImportConst.UNITS_TAG):
            assert units == getAttributeFromNodeOrReferencedNode(input_node, DLISImportConst.UNITS_TAG)
        else:
            assert units == "NONE"

        if getAttributeFromNodeOrReferencedNode(input_node, DLISImportConst.WELL_NAME_TAG):
            assert well_name == getAttributeFromNodeOrReferencedNode(input_node, DLISImportConst.WELL_NAME_TAG)
        else:
            assert well_name == ""

    def test_export_labelmap_to_las(self):
        load_project(ANONYMIZED_SCENE_FILE)
        input_node = slicer.util.getNode("Segmentation-label")
        las_depths, las_data = self.export_node_to_las(input_node)
        node_data = self.__get_array(input_node, {}, las_data.dtype)
        node_depths = retrieve_depth_curve([input_node])

        subtr = np.subtract(node_data, las_data)
        assert len(node_data[abs(subtr) > DATA_TOLERANCE_HIGH]) == 0, (
            f"Expected: 0, Actual: {len(node_data[abs(subtr) > DATA_TOLERANCE_HIGH])}.\n{node_data}\n{las_data}"
        )

        subtr = np.subtract(node_depths, las_depths)
        assert len(node_depths[abs(subtr) > DATA_TOLERANCE_HIGH]) == 0, (
            f"Expected: 0, Actual: {len(node_depths[abs(subtr) > DATA_TOLERANCE_HIGH])}\n{node_data}\n{las_data}"
        )

    def test_export_segmentation_to_dlis(self):
        load_project(UBIAMP_PROJECT_FILE)
        input_node = slicer.util.getNode("Segmentation")
        dlis_data, units, well_name = self.export_node_to_dlis(input_node)
        self._handleNulls(dlis_data, isSegmentation=True, nullValues={ANP_880_2022_DEFAULT_NULL_VALUE})

        node_data = self.__get_array(
            input_node, nullValues={ANP_880_2022_DEFAULT_NULL_VALUE}, dtype=dlis_data.dtype
        ).astype(int)

        np.testing.assert_array_equal(node_data, dlis_data)

        if getAttributeFromNodeOrReferencedNode(input_node, DLISImportConst.UNITS_TAG):
            assert units == getAttributeFromNodeOrReferencedNode(input_node, DLISImportConst.UNITS_TAG)
        else:
            assert units == "NONE"

        if getAttributeFromNodeOrReferencedNode(input_node, DLISImportConst.WELL_NAME_TAG):
            assert well_name == getAttributeFromNodeOrReferencedNode(input_node, DLISImportConst.WELL_NAME_TAG)
        else:
            assert well_name == ""

    def test_export_segmentation_to_las(self):
        load_project(ANONYMIZED_SCENE_FILE)
        input_node = slicer.util.getNode("Segmentation")
        las_depths, las_data = self.export_node_to_las(input_node)
        self._handleNulls(
            las_data, isinstance(input_node, slicer.vtkMRMLSegmentationNode), {ANP_880_2022_DEFAULT_NULL_VALUE}
        )

        node_depths = retrieve_depth_curve([input_node])
        node_data = self.__get_array(input_node, {ANP_880_2022_DEFAULT_NULL_VALUE}, las_data.dtype).astype(int)

        subtr = np.subtract(node_data, las_data)

        assert len(node_data[abs(subtr) > DATA_TOLERANCE_HIGH]) == 0

        subtr = np.subtract(node_depths, las_depths)
        assert (
            len(node_depths[abs(subtr) > DATA_TOLERANCE_LOW]) == 0
        )  # NOTE - Precision degraded... We had to use DATA_TOLERANCE_LOW

    def test_export_histogram_in_depth_to_las(self):
        load_project(ANONYMIZED_SCENE_FILE)
        input_node = tryGetNode("DummyWell_T2_DIST")
        las_depths, las_data = self.export_node_to_las(input_node)

        node_depths, node_data = arrayPartsFromNode(input_node)

        subtr = np.subtract(node_data, las_data)
        assert (
            len(node_data[abs(subtr) > DATA_TOLERANCE_LOW]) == 0
        )  # NOTE - Precision degraded... We had to use DATA_TOLERANCE_LOW

        subtr = np.subtract(node_depths, las_depths)
        # NOTE - On the other hand, depths are expected to be better than when reading from a volume (in those cases the depths are re-generated at node creation).
        # We can use here the DATA_TOLERANCE_HIGH
        assert len(node_depths[abs(subtr) > DATA_TOLERANCE_HIGH]) == 0

    def test_export_1d_curve_to_las(self):
        load_project(ANONYMIZED_SCENE_FILE)
        input_node = tryGetNode("DummyWell_Dummy1D")
        las_depths, las_data = self.export_node_to_las(input_node)
        las_data = las_data.squeeze()

        node_depths, node_data = arrayPartsFromNode(input_node)

        subtr = np.subtract(node_data, las_data)
        assert (
            len(node_data[abs(subtr) > DATA_TOLERANCE_LOW]) == 0
        )  # NOTE - Precision degraded... We had to use DATA_TOLERANCE_LOW

        subtr = np.subtract(node_depths, las_depths)
        assert len(node_depths[abs(subtr) > DATA_TOLERANCE_HIGH]) == 0

    def _test_export_image_as_csv(self, version, format_):
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        scalar = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "test_volume")
        array = np.eye(5)
        array[0, 1] = 7
        array = array.reshape((5, 1, 5))
        slicer.util.updateVolumeFromArray(scalar, array)
        scalar.SetIJKToRASDirections(-1, 0, 0, 0, -1, 0, 0, 0, -1)
        item_id = sh.GetItemByDataNode(scalar)

        widget = self._module_widget
        tree = widget.subjectHierarchyTreeView
        tree.setCurrentItem(item_id)
        widget.logFormatBox.setCurrentText(format_)
        widget.directorySelector.directory = EXPORT_TEMP_DIR
        widget.exportButton.click()

        outputFilePath = EXPORT_TEMP_DIR / "test_volume.csv"
        assert outputFilePath.exists(), f"Expected output file not found in {outputFilePath.as_posix()}"

    def test_export_image_as_csv_matrix_open_source(self):
        self._test_export_image_as_csv(
            "base",
            "CSV (matrix format)",
        )

    def test_export_image_as_csv_matrix_closed_source(self):
        self._test_export_image_as_csv(
            "extended",
            "CSV (matrix format)",
        )

    def test_export_image_as_csv_techlog_open_source(self):
        self._test_export_image_as_csv(
            "base",
            "CSV (Techlog format)",
        )

    def test_export_image_as_csv_techlog_closed_source(self):
        self._test_export_image_as_csv(
            "extended",
            "CSV (Techlog format)",
        )

    def test_proportions_export_through_interface(self):
        load_project(UBIAMP_PROJECT_FILE)

        inputNodes = [slicer.util.getNode("UBI_AMP"), slicer.util.getNode("Segmentation")]

        treeView = self._widgets["treeView"]
        ignoreStructureCheckBox = self._widgets["ignoreStructureCheckBox"]
        logComboBox = self._widgets["logComboBox"]
        proportionsCheckBox = self._widgets["proportionsCheckBox"]
        directorySelector = self._widgets["directorySelector"]
        exportButton = self._widgets["exportButton"]

        scene = slicer.app.mrmlScene()
        itemList = vtk.vtkIdList()
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(scene)

        for node in inputNodes:
            itemList.InsertNextId(subjectHierarchyNode.GetItemByName(node.GetName()))
        treeView.setCurrentItems(itemList)

        ignoreStructureCheckBox.setChecked(qt.Qt.Unchecked)
        proportionsCheckBox.setChecked(qt.Qt.Checked)

        outputDirectory = Path(EXPORT_TEMP_DIR)
        directorySelector.directory = outputDirectory.as_posix()

        logFormats = [
            "DLIS",
            "CSV (matrix format)",
            "CSV (Techlog format)",
            "LAS",
        ]  # "LAS (for Geolog)" only changes the verion and uses same export.
        logFormatsExtensions = [".dlis", ".csv", ".csv", ".las", ".las"]

        for index, format in enumerate(logFormats):
            logComboBox.setCurrentText(format)

            exportButton.clicked()
            process_events()

            if logFormatsExtensions[index] in [".dlis", ".las"]:
                file = (
                    outputDirectory
                    / "Well Logs/AMP"
                    / f"{metadata.Metadata(inputNodes[0])[DLISImportConst.WELL_NAME_TAG]}{logFormatsExtensions[index]}"
                )
                assert file.is_file(), f"Expected {file} to exist"
            else:
                for node in inputNodes:
                    file = outputDirectory / "Well Logs/AMP" / f"{node.GetName()}.csv"
                    assert file.is_file(), f"Expected {file} to exist"
                    if isinstance(node, slicer.vtkMRMLSegmentationNode):
                        file = outputDirectory / "Well Logs/AMP" / f"{node.GetName()}_Proportions.csv"
                        assert file.is_file(), f"Expected {file} to exist"
