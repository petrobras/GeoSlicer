from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import load_project, check_for_message_box, process_events
from commons.slicer import netcdf, metadata
from pathlib import Path

import tempfile
import shutil
import slicer
import xarray as xr
import numpy as np
import pandas as pd
import vtk

RESOURCES = Path(__file__).parent / "Resources"


def compare_netcdf_files(file1, file2):
    with xr.open_dataset(file1, engine="h5netcdf") as ds1, xr.open_dataset(file2, engine="h5netcdf") as ds2:
        return ds1.equals(ds2)


def compare_netcdf_files_and_attrs(file1, file2):
    with xr.open_dataset(file1, engine="h5netcdf") as ds1, xr.open_dataset(file2, engine="h5netcdf") as ds2:
        if "geoslicer_version" in ds1.attrs:
            del ds1.attrs["geoslicer_version"]
        if "geoslicer_version" in ds2.attrs:
            del ds2.attrs["geoslicer_version"]

        return ds1.identical(ds2)


class NetCDFTest(LTracePluginTest):
    def test_import(self):
        files = "img1_ref.nc", "img2_ref.nc", "no_ref.nc"
        all_dims = (
            ((449, 442, 1), (581, 694, 1), (494, 553, 1)),
            ((449, 442, 1), (581, 694, 1), (494, 553, 1)),
            ((449, 442, 1), (416, 594, 1), (416, 594, 1)),
        )

        for file, dims in zip(files, all_dims):
            netcdf.import_file(RESOURCES / "nc" / file)

            img1 = slicer.util.getNode("img1")
            img2 = slicer.util.getNode("img2")
            seg1 = slicer.util.getNode("seg1")
            seg2 = slicer.util.getNode("seg2-label")

            # Get dimensions
            self.assertEqual(img1.GetImageData().GetDimensions(), dims[0])
            self.assertEqual(img2.GetImageData().GetDimensions(), dims[1])
            self.assertEqual(seg2.GetImageData().GetDimensions(), dims[2])

            seg = seg1.GetSegmentation()
            self.assertEqual(seg.GetNumberOfSegments(), 2)
            sky = seg.GetSegment("Sky")
            trees = seg.GetSegment("Trees")
            self.assertEqual(sky.GetColor(), (1.0, 0.0, 0.0))
            self.assertEqual(trees.GetColor(), (0.0, 1.0, 1.0))

    def test_export(self):
        load_project(RESOURCES / "netcdf_test" / "netcdf_test.mrml")

        out_dir = RESOURCES / "out"
        out_dir.mkdir(exist_ok=True)

        ref_dir = RESOURCES / "nc"

        img1 = slicer.util.getNode("img1")
        img2 = slicer.util.getNode("img2")
        seg1 = slicer.util.getNode("seg1")
        seg2 = slicer.util.getNode("seg2-label")

        nodes = [img1, img2, seg1, seg2]

        netcdf.exportNetcdf(out_dir / "img1_ref.nc", nodes, img1, single_coords=True)
        self.assertTrue(compare_netcdf_files(out_dir / "img1_ref.nc", ref_dir / "img1_ref.nc"))

        netcdf.exportNetcdf(out_dir / "img2_ref.nc", nodes, img2, single_coords=True)
        self.assertTrue(compare_netcdf_files(out_dir / "img2_ref.nc", ref_dir / "img2_ref.nc"))

        netcdf.exportNetcdf(out_dir / "no_ref.nc", nodes, None, single_coords=False)
        self.assertTrue(compare_netcdf_files(out_dir / "no_ref.nc", ref_dir / "no_ref.nc"))

        shutil.rmtree(out_dir, ignore_errors=True)

    def test_export_tables(self):
        load_project(RESOURCES / "tables_example" / "tables_example.mrml")

        export_widget = self._module_widget.exportModule.self()
        item = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemByName("Well Logs")
        export_widget.subjectHierarchyTreeView.setCurrentItem(item)
        export_widget.singleCoordsCheckBox.checked = True

        self.assertEqual(export_widget.netcdfReferenceNodeBox.nodeCount(), 3)
        export_widget.netcdfReferenceNodeBox.setCurrentNode(slicer.util.getNode("AMP"))

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            out_dir.mkdir(exist_ok=True)
            export_widget.exportPathEdit.setCurrentPath(out_dir / "tables_example.nc")

            with check_for_message_box("Export completed."):
                export_widget.exportNetCDFButton.click()

            ref_dir = RESOURCES / "nc"
            self.assertTrue(compare_netcdf_files(out_dir / "tables_example.nc", ref_dir / "tables_example.nc"))

    def test_export_only_table(self):
        load_project(RESOURCES / "tables_example" / "tables_example.mrml")

        export_widget = self._module_widget.exportModule.self()
        item = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemByName("Inspector_Variables")
        export_widget.subjectHierarchyTreeView.setCurrentItem(item)
        export_widget.singleCoordsCheckBox.checked = False

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            out_dir.mkdir(exist_ok=True)
            export_widget.exportPathEdit.setCurrentPath(out_dir / "single_table.nc")

            with check_for_message_box("Export completed."):
                export_widget.exportNetCDFButton.click()

            ref_dir = RESOURCES / "nc"
            self.assertTrue(compare_netcdf_files(out_dir / "single_table.nc", ref_dir / "single_table.nc"))

    def test_export_sanitized_names(self):
        load_project(RESOURCES / "sanitize_names" / "sanitize_names.mrml")

        export_widget = self._module_widget.exportModule.self()
        item = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemByName("Well Logs")
        export_widget.subjectHierarchyTreeView.setCurrentItem(item)
        export_widget.singleCoordsCheckBox.checked = True

        self.assertEqual(export_widget.netcdfReferenceNodeBox.nodeCount(), 3)
        export_widget.netcdfReferenceNodeBox.setCurrentNode(slicer.util.getNode("vtkMRMLScalarVolumeNode3"))

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            out_dir.mkdir(exist_ok=True)
            export_widget.exportPathEdit.setCurrentPath(out_dir / "sanitize_names.nc")

            with check_for_message_box("Export completed."):
                export_widget.exportNetCDFButton.click()

            ref_dir = RESOURCES / "nc"
            self.assertTrue(compare_netcdf_files(out_dir / "sanitize_names.nc", ref_dir / "sanitize_names.nc"))

    def test_import_tables(self):
        path = RESOURCES / "nc" / "tables_example.nc"
        node_names = {node.GetName() for node in netcdf.import_file(path)}
        self.assertEqual(
            node_names, {"AMP", "TT", "WellLog_Instances", "Inspector_Variables", "WellLog_Instances_Report_Expected"}
        )

        table = slicer.util.getNode("Inspector_Variables")
        self.assertEqual(table.GetNumberOfColumns(), 2)
        self.assertEqual(table.GetNumberOfRows(), 16)

        self.assertEqual(table.GetCellText(7, 0), "Function")
        self.assertEqual(table.GetCellText(7, 1), "'snow'")

        table = slicer.util.getNode("WellLog_Instances_Report_Expected")
        self.assertEqual(table.GetNumberOfColumns(), 9)
        self.assertEqual(table.GetNumberOfRows(), 11)

    def test_import_sanitized_names(self):
        path = RESOURCES / "nc" / "sanitize_names.nc"
        node_names = {node.GetName() for node in netcdf.import_file(path)}
        self.assertEqual(
            node_names,
            {
                "SAME_NAME",
                "SAME_NAME_1",
                "_!WellLog_Instances\u2215",
                "WellLog_Instances_Report_Expected",
                "Inspector_Variables",
                "Inspector_Report",
                "Same Name Table",
                "Same Name Table_1",
            },
        )

        for table_name in ("Inspector_Report", "Same Name Table"):
            table = slicer.util.getNode(table_name)
            self.assertEqual(table.GetNumberOfColumns(), 16)
            self.assertEqual(table.GetNumberOfRows(), 43)

            self.assertEqual(table.GetColumnName(13), "perimeter_over_area (1\u2215mm)")

        table = slicer.util.getNode("WellLog_Instances_Report_Expected")
        self.assertEqual(table.GetNumberOfColumns(), 9)
        self.assertEqual(table.GetNumberOfRows(), 15)

    def _test_import_then_save_netcdf(self, input_filename, output_filename):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file = Path(temp_dir) / input_filename

            # Copy the original file to the temporary directory
            original_file = RESOURCES / "nc" / input_filename
            shutil.copy(original_file, temp_file)

            # Import the temp file
            import_module = self._module_widget.importModule.self()
            import_module.file_selector.setCurrentPath(temp_file)
            import_module.apply_button.click()

            # Create new volume
            scalar = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "new_img")
            data = np.eye(5)
            slicer.util.updateVolumeFromArray(scalar, data)

            # Add it to the imported folder
            sh = slicer.mrmlScene.GetSubjectHierarchyNode()
            scalar_id = sh.GetItemByDataNode(scalar)
            folder_id = sh.GetItemByName(Path(input_filename).stem)
            sh.SetItemParent(scalar_id, folder_id)

            # Save folder
            save_module = self._module_widget.saveModule
            save_module.show()
            save_module.folderSelector.setCurrentItem(folder_id)
            self.assertTrue(save_module.saveButton.enabled)
            save_module.saveButton.click()

            # Check the arrays are correct
            expected_file = RESOURCES / "nc" / output_filename
            self.assertTrue(compare_netcdf_files(temp_file, expected_file))

            # Attributes should be preserved
            with xr.open_dataset(temp_file, engine="h5netcdf") as ds:
                self.assertEqual(ds.attrs["description"], "Test dataset")
                self.assertEqual(ds["img1"].attrs["full_name"], "Image 1")

    def test_import_then_save_netcdf(self):
        self._test_import_then_save_netcdf("save_file_input.nc", "save_file_output.nc")

    def test_import_then_save_netcdf_custom_dim_name(self):
        self._test_import_then_save_netcdf("save_file_input_custom_dim.nc", "save_file_output_custom_dim.nc")

    def test_import_kabs_result(self):
        file = "atena_kabs.nc"
        netcdf.import_file(RESOURCES / "nc" / file)

        bin_ = slicer.util.array("bin")
        velocity = slicer.util.array("velocity")
        pressure = slicer.util.array("pressure")

        self.assertEqual(bin_.shape, (25, 25, 25))
        self.assertEqual(velocity.shape, (25, 25, 25))
        self.assertEqual(pressure.shape, (25, 25, 25))
        self.assertEqual(bin_.dtype, "uint8")
        self.assertEqual(velocity.dtype, "float64")
        self.assertEqual(pressure.dtype, "float64")

        table = slicer.util.getNode("atena_4992630_stokes_kabs_Variables")
        df = slicer.util.dataframeFromTable(table)
        path = RESOURCES / "atena_kabs_variables.pkl"
        expected_df = pd.read_pickle(path)
        self.assertTrue(expected_df.equals(df))

    def test_import_porosimetry_result(self):
        file = "atena_porosimetry.nc"
        netcdf.import_file(RESOURCES / "nc" / file)

        bin_ = slicer.util.array("bin")
        imbibition = slicer.util.array("imbibition_incompressible")

        self.assertEqual(bin_.shape, (12, 63, 63))
        self.assertEqual(imbibition.shape, (12, 63, 63))
        self.assertEqual(bin_.dtype, "uint8")
        self.assertEqual(imbibition.dtype, "float64")

        table = slicer.util.getNode("atena_5049696_imbibition_incompressible_Variables")
        df = slicer.util.dataframeFromTable(table)
        path = RESOURCES / "atena_porosimetry_variables.pkl"
        expected_df = pd.read_pickle(path)
        self.assertTrue(expected_df.equals(df))

    def test_import_hdf5_file(self):
        """Test loading an HDF5 file through the NetCDF loader."""
        file_path = RESOURCES / "h5" / "test_sample.hdf5"
        self.assertTrue(file_path.exists(), "Test HDF5 file not found")

        import_module = self._module_widget.importModule.self()
        import_module.file_selector.setCurrentPath(str(file_path))

        import_module.apply_button.click()

        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        folder_id = sh.GetItemByName("test_sample")
        self.assertNotEqual(folder_id, 0, "HDF5 import folder not found")

        children = vtk.vtkIdList()
        sh.GetItemChildren(folder_id, children)
        self.assertGreater(children.GetNumberOfIds(), 0, "No nodes imported from HDF5")

        data_node_id = children.GetId(0)
        data_node = sh.GetItemDataNode(data_node_id)
        self.assertIsNotNone(data_node, "Data node not found")

        self.assertIsInstance(data_node, slicer.vtkMRMLScalarVolumeNode, "Expected a scalar volume node")
        data_array = slicer.util.array(data_node.GetName())
        self.assertEqual(data_array.shape, (10, 20, 20), "Unexpected data dimensions")
        self.assertEqual(data_array.dtype, np.float32, "Unexpected data type")

        spacing = data_node.GetSpacing()
        self.assertEqual(spacing[0], 0.05, "X pixel spacing not correctly extracted")
        self.assertEqual(spacing[1], 0.06, "Y pixel spacing not correctly extracted")

    def test_import_hdf5_without_pixel_size(self):
        """Test loading an HDF5 file that doesn't have pixel size information."""
        file_path = RESOURCES / "h5" / "test_no_pixel_size.hdf5"
        self.assertTrue(file_path.exists(), "Test HDF5 file not found")

        import_module = self._module_widget.importModule.self()
        import_module.file_selector.setCurrentPath(str(file_path))

        import_module.apply_button.click()

        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        folder_id = sh.GetItemByName("test_no_pixel_size")
        self.assertNotEqual(folder_id, 0, "HDF5 import folder not found")

        children = vtk.vtkIdList()
        sh.GetItemChildren(folder_id, children)
        self.assertGreater(children.GetNumberOfIds(), 0, "No nodes imported from HDF5")

        data_node_id = children.GetId(0)
        data_node = sh.GetItemDataNode(data_node_id)
        self.assertIsNotNone(data_node, "Data node not found")

        self.assertIsInstance(data_node, slicer.vtkMRMLScalarVolumeNode, "Expected a scalar volume node")
        data_array = slicer.util.array(data_node.GetName())
        self.assertEqual(data_array.shape, (5, 15, 15), "Unexpected data dimensions")
        self.assertEqual(data_array.dtype, np.float32, "Unexpected data type")

        spacing = data_node.GetSpacing()
        self.assertEqual(spacing[0], 1.0, "Default X pixel spacing should be 1.0")
        self.assertEqual(spacing[1], 1.0, "Default Y pixel spacing should be 1.0")
        self.assertEqual(spacing[2], 1.0, "Default Z pixel spacing should be 1.0")

    def _assert_imported_attributes_state(self):
        """
        Verifies that the data and attributes from 'attributes_test.nc'
        have been correctly imported into the Slicer scene.

        This function checks the dataset-level attributes, the sub-folder structure,
        the attributes of each sub-item, and special node references like PCR.

        Returns:
            int: The subject hierarchy item ID for the main 'attributes_test' folder.
        """
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()

        # Verify top-level dataset folder and its attributes
        dataset_folder_id = sh.GetItemByName("attributes_test")
        self.assertNotEqual(dataset_folder_id, 0, "Dataset folder 'attributes_test' not found.")

        dataset_attrs = metadata.get_item_metadata(dataset_folder_id)
        expected_dataset_attrs = {
            "dataset_description": "This is a test dataset for attribute handling.",
            "dataset_version": 1.2,
            "dataset_long_string": "d" * 600,
            "pcr": "IsMock=True\nIsReal=False",
        }
        self.assertEqual(dataset_attrs, expected_dataset_attrs)

        # Verify that image nodes are direct children of the dataset folder
        children = vtk.vtkIdList()
        sh.GetItemChildren(dataset_folder_id, children)
        child_names = []
        for i in range(children.GetNumberOfIds()):
            child_id = children.GetId(i)
            child_names.append(sh.GetItemName(child_id))

        self.assertCountEqual(child_names, ["image_with_attrs", "image_simple"])

        # Verify 'image_with_attrs' and its attributes
        image1_node = slicer.util.getNode("image_with_attrs")
        self.assertIsNotNone(image1_node)
        image1_attrs = metadata.get_node_metadata(image1_node)
        expected_image1_attrs = {
            "author": "LTrace Tester",
            "acquisition_date": "2023-10-27",
            "is_valid": 1,
            "long_string_attr": "i" * 600,
            "long_list_attr": list(range(200)),
            "pcr": "IsMock=True\nIsReal=False",
        }
        self.assertEqual(image1_attrs, expected_image1_attrs)

        # Verify 'image_simple' and its attributes
        image2_node = slicer.util.getNode("image_simple")
        self.assertIsNotNone(image2_node)
        image2_attrs = metadata.get_node_metadata(image2_node)
        expected_image2_attrs = {"source": "synthetic", "value": 5, "pcr": "IsMock=True\nIsReal=False"}
        self.assertEqual(image2_attrs, expected_image2_attrs)

        # Check that there is a metadata node for the dataset
        metadata_node_id = sh.GetItemAttribute(dataset_folder_id, "MetadataNode")
        self.assertIsNotNone(metadata_node_id, "MetadataNode attribute not found on dataset folder.")
        metadata_node = slicer.mrmlScene.GetNodeByID(metadata_node_id)
        self.assertIsNotNone(metadata_node, "Dataset metadata node not found.")

        return dataset_folder_id

    def test_attributes_import_and_export_lib(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_nc_path = RESOURCES / "nc" / "attributes_test.nc"
            exported_nc_path = Path(temp_dir) / "exported_attributes_test.nc"

            netcdf.import_file(original_nc_path)

            # Verify the imported data and attributes in the Slicer scene
            self._assert_imported_attributes_state()

            # Export using the library function
            nodes_to_export = [slicer.util.getNode("image_with_attrs"), slicer.util.getNode("image_simple")]
            netcdf.exportNetcdf(
                exportPath=exported_nc_path,
                dataNodes=nodes_to_export,
                single_coords=True,
                referenceItem=nodes_to_export[0],
            )

            self.assertTrue(
                compare_netcdf_files_and_attrs(original_nc_path, exported_nc_path),
                "Roundtrip failed: Exported NetCDF file does not match the original.",
            )

    def test_attributes_import_and_export_ui(self):
        """
        Tests the round-trip of importing a NetCDF file with complex attributes,
        verifying their representation in the Slicer scene, and then exporting
        it back by selecting the parent folder in the UI.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            original_nc_path = RESOURCES / "nc" / "attributes_test.nc"
            exported_nc_path = Path(temp_dir) / "exported_attributes_test.nc"

            # Import the NetCDF file using the UI
            import_module = self._module_widget.importModule.self()
            import_module.file_selector.setCurrentPath(str(original_nc_path))
            import_module.apply_button.click()

            # Verify the imported data and get the folder ID for the export step
            dataset_folder_id = self._assert_imported_attributes_state()

            # Export by selecting the parent folder in the UI
            export_widget = self._module_widget.exportModule.self()
            export_widget.subjectHierarchyTreeView.setCurrentItem(dataset_folder_id)

            export_widget.singleCoordsCheckBox.checked = True
            reference_node = slicer.util.getNode("image_with_attrs")
            export_widget.netcdfReferenceNodeBox.setCurrentNode(reference_node)
            export_widget.exportPathEdit.setCurrentPath(str(exported_nc_path))

            with check_for_message_box("Export completed."):
                export_widget.exportNetCDFButton.click()

            self.assertTrue(
                compare_netcdf_files_and_attrs(original_nc_path, exported_nc_path),
                "Roundtrip failed: Exported NetCDF file does not match the original.",
            )

    def _test_import_solo_segmentation_extent(self, single_coords):
        shape = (10, 12, 14)
        origin = (37.5, -12.25, 100.0)
        spacing = (0.5, 0.75, 1.25)

        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "ref_img")
        slicer.util.updateVolumeFromArray(volume, np.zeros(shape, dtype=np.uint8))
        volume.SetOrigin(origin)
        volume.SetSpacing(spacing)
        volume.SetIJKToRASDirections(-1, 0, 0, 0, -1, 0, 0, 0, 1)

        label_array = np.zeros(shape, dtype=np.uint8)
        label_array[2:8, 3:9, 4:10] = 1
        labelmap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "solo_seg_label")
        labelmap.CreateDefaultDisplayNodes()
        slicer.util.updateVolumeFromArray(labelmap, label_array)
        labelmap.SetOrigin(origin)
        labelmap.SetSpacing(spacing)
        labelmap.SetIJKToRASDirections(-1, 0, 0, 0, -1, 0, 0, 0, 1)

        seg_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "solo_seg")
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmap, seg_node)
        seg_node.SetReferenceImageGeometryParameterFromVolumeNode(volume)

        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "solo_seg.nc"
            if single_coords:
                netcdf.exportNetcdf(out_path, [seg_node], referenceItem=seg_node, single_coords=True)
            else:
                netcdf.exportNetcdf(out_path, [seg_node], single_coords=False)

            slicer.mrmlScene.Clear(0)
            imported = netcdf.import_file(out_path)[0]

            exported_labelmap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "check_label")
            slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(
                imported, exported_labelmap, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY
            )
            self.assertEqual(exported_labelmap.GetImageData().GetDimensions(), shape[::-1])
            np.testing.assert_allclose(exported_labelmap.GetOrigin(), origin)
            np.testing.assert_allclose(exported_labelmap.GetSpacing(), spacing)

    def test_import_solo_segmentation_extent(self):
        self._test_import_solo_segmentation_extent(single_coords=False)

    def test_import_solo_segmentation_extent_single_coords(self):
        self._test_import_solo_segmentation_extent(single_coords=True)

    def test_select_tab(self):
        self._module_widget.selectTab("Import")
        process_events()
        self.assertEqual(self._module_widget.mainTab.currentWidget(), self._module_widget.importModule)

        self._module_widget.selectTab("Export")
        process_events()
        self.assertEqual(self._module_widget.mainTab.currentWidget(), self._module_widget.exportModule)

        self._module_widget.selectTab("Save")
        process_events()
        self.assertEqual(self._module_widget.mainTab.currentWidget(), self._module_widget.saveModule)

    def test_export_import_spacing_precision(self):
        volume_size = (10, 10, 10)
        spacings = np.arange(0.1, 2.0, 0.01245)

        volume_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "SpacingTestVolume")
        array = np.zeros(volume_size, dtype=np.uint8)
        slicer.util.updateVolumeFromArray(volume_node, array)

        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "test_spacing.nc"

            for spacing_val in spacings:
                spacing = [spacing_val] * 3
                volume_node.SetSpacing(spacing)

                # Export
                netcdf.exportNetcdf(out_path, [volume_node], referenceItem=volume_node, single_coords=True)

                # Verify
                with xr.open_dataset(out_path, engine="h5netcdf") as ds:
                    var_name = "SpacingTestVolume"
                    self.assertIn(var_name, ds)
                    data_array = ds[var_name]
                    self.assertEqual(data_array.shape, volume_size, f"Shape mismatch for spacing {spacing_val}")
