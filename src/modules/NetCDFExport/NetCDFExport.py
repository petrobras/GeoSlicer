import os

import qt
import slicer
import vtk
import ctk
import xarray as xr
import numpy as np

from dataclasses import dataclass
from ltrace.slicer.app import getApplicationVersion
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget
from ltrace.slicer import ui, export
from pathlib import Path
from ltrace.slicer.helpers import (
    createTemporaryVolumeNode,
    removeTemporaryNodes,
    getSourceVolume,
    save_path,
    safe_convert_array,
    checkUniqueNames,
)
from ltrace.slicer import netcdf
from ltrace.utils.callback import Callback
from typing import List, Tuple


class NetCDFExport(LTracePlugin):
    SETTING_KEY = "NetCDFExport"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "NetCDF Export"
        self.parent.categories = ["Tools", "MicroCT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = NetCDFExport.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class NetCDFExportWidget(LTracePluginWidget):
    EXPORTABLE_TYPES = (
        slicer.vtkMRMLLabelMapVolumeNode,
        slicer.vtkMRMLSegmentationNode,
        slicer.vtkMRMLVectorVolumeNode,
        slicer.vtkMRMLScalarVolumeNode,
    )

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)

        self.formLayout = qt.QFormLayout()
        self.formLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.subjectHierarchyTreeView = slicer.qMRMLSubjectHierarchyTreeView()
        self.subjectHierarchyTreeView.setMRMLScene(slicer.app.mrmlScene())
        self.subjectHierarchyTreeView.hideColumn(2)
        self.subjectHierarchyTreeView.hideColumn(3)
        self.subjectHierarchyTreeView.hideColumn(4)
        self.subjectHierarchyTreeView.hideColumn(5)
        self.subjectHierarchyTreeView.setFocusPolicy(qt.Qt.NoFocus)
        self.subjectHierarchyTreeView.setMinimumHeight(300)
        self.subjectHierarchyTreeView.currentItemChanged.connect(lambda _: self.onSelectionChanged())
        self.formLayout.addRow(self.subjectHierarchyTreeView)
        self.formLayout.addRow("", None)

        coordsGroup = qt.QGroupBox()
        coordsLayout = qt.QFormLayout(coordsGroup)

        self.singleCoordsCheckBox = qt.QCheckBox("Use the same coordinate system for all images")
        self.singleCoordsCheckBox.setToolTip(
            "Export images in the same coordinate system, making the arrays spatially aligned. Uncheck to avoid padding images and thus reduce file size."
        )
        self.singleCoordsCheckBox.stateChanged.connect(
            lambda state: self.netcdfReferenceNodeBox.setEnabled(state == qt.Qt.Checked)
        )
        coordsLayout.addRow(self.singleCoordsCheckBox)

        self.netcdfReferenceNodeBox = ui.volumeInput(
            hasNone=True,
            nodeTypes=[cls.__name__ for cls in self.EXPORTABLE_TYPES],
        )
        self.netcdfReferenceNodeBox.setToolTip(
            "When exporting images using a single coordinate system, all images within the directory will be "
            "resampled and aligned to the reference node."
        )
        self.netcdfReferenceNodeBox.setEnabled(False)
        coordsLayout.addRow("Reference node:", self.netcdfReferenceNodeBox)

        self.formLayout.addRow(coordsGroup)

        self.compressionCheckBox = qt.QCheckBox("Use compression")
        self.compressionCheckBox.setToolTip(
            "Use compression when exporting to NetCDF. Reduces file size but makes file slower to load."
        )
        self.formLayout.addRow(self.compressionCheckBox)

        self.exportPathEdit = ctk.ctkPathLineEdit()
        self.exportPathEdit.filters = ctk.ctkPathLineEdit.Files | ctk.ctkPathLineEdit.Writable
        self.exportPathEdit.nameFilters = ["*.nc"]
        self.exportPathEdit.settingKey = "NetCDFExport/ExportPath"
        self.formLayout.addRow("Export path:", self.exportPathEdit)
        self.formLayout.addRow("", None)

        self.exportNetCDFButton = qt.QPushButton("Export")
        self.exportNetCDFButton.setFixedHeight(40)
        self.exportNetCDFButton.clicked.connect(self.onExportNetcdfButtonClicked)
        self.formLayout.addRow(self.exportNetCDFButton)

        self.layout.addLayout(self.formLayout)

        statusLabel = qt.QLabel("Status: ")
        self.currentStatusLabel = qt.QLabel("Idle")
        statusHBoxLayout = qt.QHBoxLayout()
        statusHBoxLayout.addStretch(1)
        statusHBoxLayout.addWidget(statusLabel)
        statusHBoxLayout.addWidget(self.currentStatusLabel)
        self.layout.addLayout(statusHBoxLayout)

        self.progressBar = qt.QProgressBar()
        self.layout.addWidget(self.progressBar)
        self.progressBar.hide()

        self.layout.addStretch(1)

    def getItemsToExport(self):
        selected_items = vtk.vtkIdList()
        self.subjectHierarchyTreeView.currentItems(selected_items)
        return export.getDataNodes(selected_items, self.EXPORTABLE_TYPES)

    def onSelectionChanged(self):
        selected_items = self.getItemsToExport()
        if not selected_items:
            return
        current = self.netcdfReferenceNodeBox.currentNode()
        if current not in selected_items:
            current = None

        is_good_ref = lambda node: type(node) in (slicer.vtkMRMLScalarVolumeNode, slicer.vtkMRMLVectorVolumeNode)
        if current and is_good_ref(current):
            return

        # Find a reference node if not specified. Prefer scalar/vector volumes over label maps.
        ref_node = current or selected_items[0]
        for node in selected_items:
            if is_good_ref(node):
                ref_node = node
                break

        self.netcdfReferenceNodeBox.setCurrentNode(ref_node)

    def onExportNetcdfButtonClicked(self):
        callback = Callback(on_update=lambda message, percent: self.updateStatus(message, progress=percent))
        try:
            exportPath = self.exportPathEdit.currentPath
            save_path(self.exportPathEdit)

            dataNodes = self.getItemsToExport()

            referenceItem = self.netcdfReferenceNodeBox.currentNode()
            useCompression = self.compressionCheckBox.checked
            singleCoords = self.singleCoordsCheckBox.checked

            warnings = netcdf.exportNetcdf(exportPath, dataNodes, referenceItem, singleCoords, useCompression, callback)
            callback.on_update("", 100)

            if warnings:
                slicer.util.warningDisplay("\n".join(warnings), windowTitle="NetCDF export warnings")
            else:
                slicer.util.infoDisplay("Export completed.")
        except Exception as e:
            slicer.util.errorDisplay(str(e))
            raise
        finally:
            callback.on_update("", 100)
            self.exportPathEdit.setCurrentPath("")

    def updateStatus(self, message, progress=None):
        self.progressBar.show()
        self.currentStatusLabel.text = message
        if not progress:
            return
        self.progressBar.setValue(progress)
        if self.progressBar.value == 100:
            self.progressBar.hide()
            self.currentStatusLabel.text = "Idle"
        slicer.app.processEvents()


def _vtk_4x4_to_numpy(matrix_vtk):
    matrix_np = np.empty(16)
    matrix_vtk.DeepCopy(matrix_np, matrix_vtk)
    return matrix_np.reshape(4, 4)


def _segmentation_to_label_map(segmentation: slicer.vtkMRMLSegmentationNode) -> slicer.vtkMRMLLabelMapVolumeNode:
    labelMapVolumeNode = createTemporaryVolumeNode(slicer.vtkMRMLLabelMapVolumeNode, segmentation.GetName())
    slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(
        segmentation, labelMapVolumeNode, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY
    )
    return labelMapVolumeNode


def _node_to_data_array(
    node: slicer.vtkMRMLScalarVolumeNode, dim_names: List[str], dtype=None
) -> Tuple[slicer.vtkMRMLScalarVolumeNode, xr.DataArray]:
    attrs = {}
    if isinstance(node, slicer.vtkMRMLSegmentationNode):
        node_name = node.GetName()
        node = _segmentation_to_label_map(node)

        if node.GetImageData().GetPointData().GetScalars() is None:
            return f"Could not export {node_name}: segmentation is empty"

        attrs["type"] = "segmentation"
    elif isinstance(node, slicer.vtkMRMLLabelMapVolumeNode):
        attrs["type"] = "labelmap"
    elif not isinstance(node, slicer.vtkMRMLScalarVolumeNode):
        raise ValueError(f"Unsupported node type: {type(node)}")

    if isinstance(node, slicer.vtkMRMLLabelMapVolumeNode):
        attrs["labels"] = ["Name,Index,Color"] + export.getLabelMapLabelsCSV(node, withColor=True)

    array = slicer.util.arrayFromVolume(node)
    if dtype:
        array = safe_convert_array(array, dtype)
    dims = dim_names[: array.ndim]
    return node, xr.DataArray(array, dims=dims, attrs=attrs)


@dataclass
class DataArrayTransform:
    ijk_to_ras: np.ndarray
    transform: np.ndarray
    ras_min: np.ndarray
    ras_max: np.ndarray


def _add_color(transform: xr.DataArray) -> xr.DataArray:
    assert transform.shape == (4, 4)
    ret = np.insert(transform, 3, 0, axis=0)
    ret = np.insert(ret, 3, 0, axis=1)
    ret[3, 3] = 1
    return ret


def _get_transform(node: slicer.vtkMRMLScalarVolumeNode, array_shape: np.ndarray) -> DataArrayTransform:
    default_transform = np.array(
        [
            [-1, 0, 0, 0],
            [0, -1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ]
    )

    transform = vtk.vtkMatrix4x4()
    node.GetIJKToRASMatrix(transform)
    transform = _vtk_4x4_to_numpy(transform)
    ijk_to_ras = transform.copy()

    transform = transform @ default_transform
    transform[:2, 3] *= -1

    # Convert XYZ to ZYX
    transform[:3, :3] = np.flip(transform[:3, :3], axis=(0, 1))
    transform[:3, 3] = np.flip(transform[:3, 3], axis=0)

    pre_shape = np.array(array_shape[:3]) - 1

    # Corners of a unit cube
    unit_corners = [
        [0, 0, 0],
        [0, 0, 1],
        [0, 1, 0],
        [0, 1, 1],
        [1, 0, 0],
        [1, 0, 1],
        [1, 1, 0],
        [1, 1, 1],
    ]
    ijk_corners = unit_corners * pre_shape
    ras_corners = np.array([(transform @ np.concatenate([ijk, [1]]))[:3] for ijk in ijk_corners])

    ras_min, ras_max = ras_corners.min(axis=0), ras_corners.max(axis=0)

    if len(array_shape) == 4:
        transform = _add_color(transform)

    return DataArrayTransform(ijk_to_ras, transform, ras_min, ras_max)


MIN_CHUNKING_SIZE_BYTES = 2**33  # 8 GiB
CHUNK_SIZE_BYTES = 2**21  # 2 MiB


def _recommended_chunksizes(img):
    chunk_size = round((CHUNK_SIZE_BYTES // img.dtype.itemsize) ** (1 / 3))
    if (
        img.nbytes >= MIN_CHUNKING_SIZE_BYTES
        and img.ndim >= 3
        and all(size >= chunk_size * 4 for size in img.shape[:3])
    ):
        return (chunk_size,) * 3
    return None


def _get_dataset_main_dims(dataset):
    # Uses a heuristic to find likely zyxc dimensions of a dataset
    for var in dataset:
        array = dataset[var]
        dims = array.dims
        if len(dims) >= 3:
            return dims[:4]


def exportNetcdf(
    exportPath,
    dataNodes,
    referenceItem=None,
    single_coords=False,
    use_compression=False,
    callback=None,
    nodeNames=None,
    nodeDtypes=None,
    save_in_place=False,
):
    if not dataNodes:
        raise ValueError("No images selected.")

    if callback is None:
        callback = Callback(on_update=lambda *args, **kwargs: None)

    if single_coords and not save_in_place:
        if not referenceItem:
            raise ValueError("No reference node selected.")
        if referenceItem not in dataNodes:
            raise ValueError("Reference image must be in the list of images to export.")

    warnings = []

    callback.on_update("Starting…", 0)
    if not nodeNames:
        checkUniqueNames(dataNodes)

    arrays = {}
    coords = {}
    nodeNames = nodeNames or [node.GetName() for node in dataNodes]
    nodeDtypes = nodeDtypes or [None] * len(dataNodes)

    id_to_name_map = {node.GetID(): name for node, name in zip(dataNodes, nodeNames)}

    if save_in_place:
        existing_dataset = xr.load_dataset(exportPath)
        existing_dims = _get_dataset_main_dims(existing_dataset)

    for node, dtype in zip(dataNodes, nodeDtypes):
        name = id_to_name_map[node.GetID()]
        if save_in_place and name in existing_dataset:
            continue
        is_ref = node == referenceItem

        if save_in_place:
            dims = existing_dims
        elif single_coords or name == "microtom":
            dims = list("zyxc")
        else:
            dims = [f"{d}_{name}" for d in "zyx"] + ["c"]

        source_node = getSourceVolume(node)

        result = _node_to_data_array(node, dims, dtype)
        if isinstance(result, str):
            warnings.append(result)
            continue
        node, data_array = result

        if source_node:
            try:
                source_name = id_to_name_map[source_node.GetID()]
                data_array.attrs["reference"] = source_name
            except KeyError:
                pass

        if is_ref:
            referenceItem = node
        if data_array.ndim == 4:
            coords["c"] = ["r", "g", "b"]
        arrays[name] = (data_array, _get_transform(node, data_array.shape), node)

    if single_coords:
        if save_in_place:
            ref_spacing = []
            ras_min = []
            output_shape = []
            for dim in existing_dims[:3]:
                dim_coords = existing_dataset.coords[dim]
                if len(dim_coords) > 1:
                    ref_spacing.append((dim_coords[1] - dim_coords[0]).item())
                else:
                    ref_spacing.append(1)
                ras_min.append(dim_coords[0].item())
                output_shape.append(len(dim_coords))
        else:
            ref_spacing = np.array(referenceItem.GetSpacing())[::-1]
            ras_min = np.array([tr.ras_min for _, tr, _ in arrays.values()]).min(axis=0)
            ras_max = np.array([tr.ras_max for _, tr, _ in arrays.values()]).max(axis=0)
            output_shape = np.ceil((ras_max - ras_min) / ref_spacing).astype(int) + 1

        output_transform_no_color = np.array(
            [
                [ref_spacing[0], 0, 0, ras_min[0]],
                [0, ref_spacing[1], 0, ras_min[1]],
                [0, 0, ref_spacing[2], ras_min[2]],
                [0, 0, 0, 1],
            ]
        )

        output_transform_with_color = _add_color(output_transform_no_color)

    if not arrays:
        raise ValueError("No images to export.\n" + "\n".join(warnings))

    progress_range = np.arange(5, 90, 85 / len(arrays))
    data_arrays = {}
    for (name, (data_array, transform, _)), progress in zip(arrays.items(), progress_range):
        callback.on_update(f'Processing "{name}"…', round(progress))

        array = data_array.data
        attrs = data_array.attrs

        if single_coords:
            input_transform = transform.transform
            output_transform = output_transform_no_color if data_array.ndim == 3 else output_transform_with_color
            output_to_input = np.linalg.inv(input_transform) @ output_transform

            fill_value = 0 if "labels" in data_array.attrs else 255
            shape = output_shape.copy()
            if data_array.ndim == 4:
                shape = np.append(shape, 3)

            # Transform interpolation does not work on dimensions with size 1
            for i in range(3):
                if data_array.shape[i] == 1:
                    output_to_input[i, :] = 0
                    output_to_input[:, i] = 0
                    output_to_input[i, i] = 1

            identity = np.eye(output_to_input.shape[0])
            if np.allclose(output_to_input, identity):
                if data_array.shape != tuple(shape):
                    pads = []
                    for small, large in zip(data_array.shape, shape):
                        diff = large - small
                        pads.append((0, diff))
                    array = np.pad(array, pads, mode="constant", constant_values=fill_value)

            else:
                array = ndimage.affine_transform(
                    data_array, output_to_input, output_shape=shape, order=0, cval=fill_value, mode="grid-constant"
                )
        else:
            attrs["transform"] = transform.ijk_to_ras.flatten().tolist()

        if "reference" in attrs and attrs["reference"] not in arrays:
            del attrs["reference"]

        new_data_array = xr.DataArray(array, dims=data_array.dims, attrs=attrs)
        data_arrays[name] = new_data_array

    removeTemporaryNodes()
    callback.on_update("Exporting to NetCDF…", 90)

    if save_in_place:
        for dim in existing_dims[:3]:
            coords[dim] = existing_dataset.coords[dim]
    elif single_coords:
        for min_, spacing, size, dim in zip(ras_min, ref_spacing, output_shape, "zyx"):
            max_ = min_ + spacing * (size - 1)
            coords[dim] = np.linspace(min_, max_, size)
    else:
        for name, data_array in data_arrays.items():
            node = arrays[name][2]
            origin_zyx = list(node.GetOrigin()[::-1])
            origin_zyx[1] *= -1
            origin_zyx[2] *= -1
            spacing_zyx = node.GetSpacing()[::-1]
            for origin, spacing, size, dim in zip(origin_zyx, spacing_zyx, data_array.shape, "zyx"):
                coord_name = f"{dim}_{name}" if name != "microtom" else dim
                coords[coord_name] = np.linspace(origin, origin + spacing * (size - 1), size)
    dataset = xr.Dataset(data_arrays, coords=coords)

    if save_in_place:
        for var in dataset:
            existing_dataset[var] = dataset[var]
        dataset = existing_dataset

    encoding = {}
    for var in dataset:
        img = dataset[var]
        encoding[var] = {"zlib": use_compression, "chunksizes": _recommended_chunksizes(img)}

    dataset.attrs["geoslicer_version"] = slicer.app.applicationVersion
    dataset.to_netcdf(exportPath, encoding=encoding, format="NETCDF4")

    return warnings
