from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, process_events, compare_ignore_line_endings
from pathlib import Path
from unittest.mock import patch

import shutil
import filecmp
import slicer
import xarray as xr
import numpy as np

RESOURCES = Path(__file__).parent / "Resources"
ITEMS = {
    "CT": "Volume",
    "BIN": "Segmentation",
    "BIW": "bar",
    "BASINS": "Basins",
    "LABELS": "Labelmap",
}


def compare_netcdf_files(file1, file2):
    ds1 = xr.open_dataset(file1, engine="h5netcdf")
    ds2 = xr.open_dataset(file2, engine="h5netcdf")

    if not ds1.equals(ds2):
        return False

    for key in ds1.data_vars.keys():
        attrs1 = ds1[key].attrs
        attrs2 = ds2[key].attrs
        for key, value in attrs1.items():
            if key not in attrs2:
                return False
            if isinstance(value, np.ndarray):
                if not np.array_equal(value, attrs2[key]):
                    return False
            else:
                if value != attrs2[key]:
                    return False

    return True


class MicroCTExportTest(LTracePluginTest):
    def post_setup(self):
        load_project(RESOURCES / "microct_export_test" / "microct_export_test.mrml")

        self.out_dir = RESOURCES / "out"
        self.out_dir.mkdir(exist_ok=True)

        widget = self._module_widget
        self.selectors = widget.nodeSelectors
        self.table_selector = widget.tableSelector
        self.image_name_edit = widget.imageNameLineEdit
        self.export_button = widget.exportButton
        self.format_box = widget.formatComboBox
        self.single_coords_checkbox = widget.singleCoordsCheckBox
        self.sh = slicer.mrmlScene.GetSubjectHierarchyNode()

        widget.exportDirButton.directory = str(self.out_dir)

    def set_format(self, format_):
        self.format_box.setCurrentText(format_)
        process_events()

    def export(self):
        process_events()
        self.assertTrue(self.export_button.enabled)
        self.export_button.click()
        process_events()

    def tear_down(self):
        shutil.rmtree(self.out_dir)

    def test_export_all_nc_separate_coords(self):
        self.set_format("NetCDF")
        for key, item in ITEMS.items():
            self.selectors[key].setCurrentItem(self.sh.GetItemByName(item))
        self.image_name_edit.setText("test")
        self.single_coords_checkbox.checked = False
        self.export()

        out_file = self.out_dir / "test.nc"
        ref_file = RESOURCES / "all_separate_coords.nc"

        self.assertTrue(compare_netcdf_files(out_file, ref_file))

    def test_export_all_nc_same_coords(self):
        self.set_format("NetCDF")
        for key, item in ITEMS.items():
            self.selectors[key].setCurrentItem(self.sh.GetItemByName(item))
        self.image_name_edit.setText("test")
        self.assertTrue(self.single_coords_checkbox.checked)
        self.export()

        out_file = self.out_dir / "test.nc"
        ref_file = RESOURCES / "all_same_coords.nc"

        self.assertTrue(compare_netcdf_files(out_file, ref_file))

    def test_export_tiff_16(self):
        self.set_format("TIF")
        self.selectors["CT"].setCurrentItem(self.sh.GetItemByName("Volume"))
        self.image_name_edit.setText("A_B_C_D")
        self.export()

        name = "A_B_C_D_CT.tif"
        out_file = self.out_dir / name
        ref_file = RESOURCES / name

        out = slicer.util.arrayFromVolume(slicer.util.loadVolume(str(out_file)))
        ref = slicer.util.arrayFromVolume(slicer.util.loadVolume(str(ref_file)))
        np.testing.assert_array_equal(out, ref)
        self.assertEqual(out.dtype, np.uint16)

    def test_export_tiff_32(self):
        for type_ in ("uint32", "int32", "float32", "float64"):
            self.set_format("TIF")
            self.selectors["FLOAT"].setCurrentItem(self.sh.GetItemByName(f"Volume_{type_}"))
            self.image_name_edit.setText("A_B_C_D")
            self.export()

            name = "A_B_C_D_FLOAT.tif"
            out_file = self.out_dir / name
            ref_file = RESOURCES / name

            # Import both files and compare them
            out = slicer.util.arrayFromVolume(slicer.util.loadVolume(str(out_file)))
            ref = slicer.util.arrayFromVolume(slicer.util.loadVolume(str(ref_file)))
            np.testing.assert_array_equal(out, ref)
            self.assertEqual(out.dtype, np.float32)

    def test_export_all_raw(self):
        self.set_format("RAW")
        for key, item in ITEMS.items():
            self.selectors[key].setCurrentItem(self.sh.GetItemByName(item))
        self.image_name_edit.setText("A_B_C_D")
        self.export()

        raw_files = self.out_dir.glob("*.raw")
        for raw_file in raw_files:
            ref_file = RESOURCES / raw_file.name
            self.assertTrue(filecmp.cmp(raw_file, ref_file, shallow=False))

        csv_files = self.out_dir.glob("*.csv")
        for csv_file in csv_files:
            ref_file = RESOURCES / csv_file.name
            self.assertTrue(compare_ignore_line_endings(csv_file, ref_file))

    def test_export_nc_keeps_scene_dtype(self):
        labelmap = slicer.util.getNode("Labelmap")
        array = slicer.util.arrayFromVolume(labelmap)
        self.assertEqual(array.dtype, np.int16)
        array[0, 0, 0] = 300
        slicer.util.arrayFromVolumeModified(labelmap)
        self.selectors["LABELS"].setCurrentItem(self.sh.GetItemByName("Labelmap"))

        self.set_format("NetCDF")
        self.image_name_edit.setText("test")
        self.export()

        with xr.open_dataset(self.out_dir / "test.nc", engine="h5netcdf") as dataset:
            labels = dataset["labels"]
            self.assertEqual(labels.dtype, np.int16)
            self.assertEqual(int(labels.max()), 300)

    def test_export_segmentation_raw(self):
        self.set_format("RAW")
        self.selectors["BIN"].setCurrentItem(self.sh.GetItemByName("Segmentation"))
        self.image_name_edit.setText("A_B_C_D")
        self.export()

        name = "A_B_C_D_BIN_0005_0008_0010_1000000nm"
        filename = name + ".raw"
        out_file = self.out_dir / filename
        ref_file = RESOURCES / filename
        self.assertTrue(filecmp.cmp(out_file, ref_file, shallow=False))

        filename = name + ".csv"
        out_file = self.out_dir / filename
        ref_file = RESOURCES / filename
        self.assertTrue(compare_ignore_line_endings(out_file, ref_file))

    def test_export_single_segment_raw(self):
        self.set_format("RAW")
        self.selectors["BIW"].setCurrentItem(self.sh.GetItemByName("bar"))
        self.image_name_edit.setText("A_B_C_D")
        self.export()

        name = "A_B_C_D_BIW_0005_0008_0010_1000000nm"
        filename = name + ".raw"
        out_file = self.out_dir / filename
        ref_file = RESOURCES / filename
        self.assertTrue(filecmp.cmp(out_file, ref_file, shallow=False))

        filename = name + ".csv"
        out_file = self.out_dir / filename
        ref_file = RESOURCES / filename
        self.assertTrue(compare_ignore_line_endings(out_file, ref_file))

    def test_export_basins_raw(self):
        self.set_format("RAW")
        self.selectors["BASINS"].setCurrentItem(self.sh.GetItemByName("Basins"))
        self.image_name_edit.setText("A_B_C_D")
        self.export()

        name = "A_B_C_D_BASINS_0005_0008_0010_1000000nm"

        filename = name + ".raw"
        out_file = self.out_dir / filename
        ref_file = RESOURCES / filename
        self.assertTrue(filecmp.cmp(out_file, ref_file, shallow=False))

        filename = name + ".csv"
        out_file = self.out_dir / filename
        ref_file = RESOURCES / filename
        self.assertTrue(compare_ignore_line_endings(out_file, ref_file))

    def test_export_correct_basins_nc(self):
        self.set_format("NetCDF")
        self.selectors["BASINS"].setCurrentItem(self.sh.GetItemByName("Basins (correct)"))
        self.image_name_edit.setText("test")
        self.single_coords_checkbox.checked = False
        self.export()

        out_file = self.out_dir / "test.nc"
        ref_file = RESOURCES / "basins.nc"

        self.assertTrue(compare_netcdf_files(out_file, ref_file))

    def test_table(self):
        self.table_selector.setCurrentItem(self.sh.GetItemByName("Table"))
        self.image_name_edit.setText("Table")
        self.export()

        out_file = self.out_dir / "Table.csv"
        ref_file = RESOURCES / "Table.csv"
        self.assertTrue(compare_ignore_line_endings(out_file, ref_file))

    def test_sequence_tif_and_table(self):
        n = 2
        scalar_sequence = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "scalar sequence")
        table_sequence = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", "table sequence")

        for i in range(n):
            array = np.random.randint(3, size=(16, 16, 16), dtype=np.uint8)
            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", f"scalar_{i}")
            slicer.util.updateVolumeFromArray(node, array)
            scalar_sequence.SetDataNodeAtValue(node, str(i))

            table_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", f"table_{i}")
            slicer.util.updateTableFromArray(table_node, array[0, :, :])
            table_sequence.SetDataNodeAtValue(table_node, str(i))

        scalar_browser = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "scalar browser")
        scalar_browser.SetAndObserveMasterSequenceNodeID(scalar_sequence.GetID())
        scalar_proxy = scalar_browser.GetProxyNode(scalar_sequence)
        scalar_proxy.SetName("scalar_proxy")

        table_browser = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", "table browser")
        table_browser.SetAndObserveMasterSequenceNodeID(table_sequence.GetID())
        table_proxy = table_browser.GetProxyNode(table_sequence)
        table_proxy.SetName("table_proxy")

        self.set_format("TIF")
        self.selectors["FLOAT"].setCurrentItem(self.sh.GetItemByName("scalar_proxy"))
        self.table_selector.setCurrentItem(self.sh.GetItemByName("table_proxy"))
        self.image_name_edit.setText("scalar")
        self.export()

        for i in range(n):
            self.assertTrue((self.out_dir / f"scalar_{i}_FLOAT.tif").is_file())
            self.assertTrue((self.out_dir / f"table_{i}.csv").is_file())

    @patch("slicer.util.errorDisplay")
    def test_export_invalid_output_dir(self, mock_error_display):
        self.set_format("RAW")
        self.selectors["BIN"].setCurrentItem(self.sh.GetItemByName("Segmentation"))
        self.image_name_edit.setText("A_B_C_D")

        invalid_path = "/tmp/non_existent_dir_for_test"
        assert Path(invalid_path).exists() is False, "This path should not exist."
        self._module_widget.exportDirButton.directory = invalid_path
        self.export_button.click()
        process_events()
        mock_error_display.assert_called_once()

    @patch("slicer.util.errorDisplay")
    def test_export_no_input_selected(self, mock_error_display):
        self.set_format("RAW")
        for key in self.selectors:
            self.selectors[key].setCurrentItem(0)
        self.table_selector.setCurrentItem(0)
        self.image_name_edit.setText("A_B_C_D")
        self.export_button.click()
        process_events()
        mock_error_display.assert_called_once_with("Please select an image or a table to export.")

    @patch("slicer.util.errorDisplay")
    def test_export_no_image_name(self, mock_error_display):
        self.set_format("RAW")
        self.selectors["BIN"].setCurrentItem(self.sh.GetItemByName("Segmentation"))
        self.image_name_edit.setText("")
        self.export_button.click()
        process_events()
        mock_error_display.assert_called_once_with("Please enter an image name.")
