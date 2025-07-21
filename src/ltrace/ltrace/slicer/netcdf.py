import vtk
import slicer
import logging
import h5py
import re
import xarray as xr
import logging
import numpy as np
import pandas as pd
import toml

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from PIL import ImageColor
from pint import UnitRegistry
from ltrace.readers import microtom
from ltrace.slicer import export
from ltrace.slicer.helpers import (
    autoDetectColumnType,
    create_color_table,
    createTemporaryVolumeNode,
    makeTemporaryNodePermanent,
    removeTemporaryNodes,
    updateSegmentationFromLabelMap,
    getSourceVolume,
    safe_convert_array,
)
from ltrace.utils.callback import Callback
from scipy import ndimage
from typing import List, Tuple
from ltrace.slicer.data_utils import dataFrameToTableNode, tableNodeToDataFrame

MIN_CHUNKING_SIZE_BYTES = 2**33  # 8 GiB
CHUNK_SIZE_BYTES = 2**21  # 2 MiB


@dataclass
class DataArrayTransform:
    ijk_to_ras: np.ndarray
    transform: np.ndarray
    ras_min: np.ndarray
    ras_max: np.ndarray


def _sanitize_var_name(name: str) -> str:
    # Add _ if first char is not alphanumeric or underscore
    if not name or (not (name[0].isalnum() or name[0] == "_")):
        name = "_" + name

    # Trim trailing spaces
    name = name.rstrip()

    # Replace / with similar symbol
    name = name.replace("/", "\u2215")

    # Replace consecutive underscores with single underscore
    # ('__' is reserved for table columns, e.g. table_name__column_name)
    name = re.sub("_+", "_", name)

    # Remove ASCII control characters (codes 0-31 and 127)
    result = ""
    for char in name:
        if ord(char) > 31 and ord(char) != 127:
            result += char

    # Ensure not empty
    if not result:
        return "_"
    return result


def _deduplicate_names(names):
    unique_names = []
    name_counts = defaultdict(int)
    for name in names:
        if name in unique_names:
            name_counts[name] += 1
            name = f"{name}_{name_counts[name]}"
        unique_names.append(name)
    return unique_names


def _sanitize_var_names(names):
    names = [_sanitize_var_name(name) for name in names]
    return _deduplicate_names(names)


def _crop_value(array: xr.DataArray, value: int):
    crop_where = array == value
    slice_dict = {}
    for dim in array.dims:
        if dim == "c":
            continue
        crop_over_dim = crop_where.all(dim=tuple(set(array.dims) - set([dim])))
        first = crop_over_dim.argmin()
        last = array[dim].size - crop_over_dim[::-1].argmin()
        slice_dict[dim] = slice(int(first), int(last))
    return array[slice_dict]


def get_dims(array: xr.DataArray) -> Tuple[str, str, str]:
    z, y, x = array.dims[:3]
    return x, y, z


def get_spacing(array: xr.DataArray) -> List[int]:
    z, y, x = get_dims(array)
    spacing = [array[dim][1] - array[dim][0] if len(array[dim]) > 1 else 1 for dim in (x, y, z)]
    spacing = [val.data.item() if isinstance(val, xr.DataArray) else val for val in spacing]

    return spacing


def get_origin(array: xr.DataArray) -> List[int]:
    z, y, x = get_dims(array)
    origin = [-array[x][0], -array[y][0], array[z][0]]
    origin = [val.data.item() if isinstance(val, xr.DataArray) else val for val in origin]

    return origin


def get_dims(array: xr.DataArray) -> List[str]:
    return array.dims[:3]


def _array_to_node(array: xr.DataArray, node: slicer.vtkMRMLVolumeNode) -> None:
    ijk_to_ras = array.attrs.get("transform")
    origin = get_origin(array)
    spacing = get_spacing(array)
    slicer.util.updateVolumeFromArray(node, array.data)
    node.SetOrigin(*origin)
    node.SetSpacing(*spacing)

    if ijk_to_ras is not None:
        # Convert from flattened array to vtk 4x4 matrix
        vtk_matrix = vtk.vtkMatrix4x4()
        vtk_matrix.DeepCopy(ijk_to_ras)
        node.SetIJKToRASMatrix(vtk_matrix)
    else:
        node.SetIJKToRASDirections(-1, 0, 0, 0, -1, 0, 0, 0, 1)


def nc_labels_to_color_node(labels, name="nc_labels"):
    colors = []
    colorNames = []
    if isinstance(labels, str):
        # This happens when there are no labels
        labels = [labels]
    for label in labels[1:]:
        try:
            seg_name, index, color = label.split(",")
        except Exception as error:
            logging.info(f"Failed to parse label string: {label}. Error: {error}")
            continue

        colorNames.append(seg_name)
        colors.append(tuple(x / 255 for x in ImageColor.getrgb(color)))

    color_table = create_color_table(f"{name}_ColorTable", colors=colors, color_names=colorNames, add_background=True)
    return color_table


def extract_pixel_sizes_from_hdf5(file_path):
    ureg = UnitRegistry()

    base_path = "Beamline Parameters/snapshot/after/beamline-state/beam-optics/measured"

    with h5py.File(file_path, "r") as f:

        def get_param_as_mm(param_name):
            param_path = f"{base_path}/{param_name}"

            try:
                value = f[f"{param_path}/value"][()]
            except KeyError:
                return 1

            try:
                units = f[f"{param_path}/units"][()]
                units = units.decode("utf-8") if isinstance(units, bytes) else units
            except KeyError:
                units = "mm"

            quantity = value * ureg(units)
            value_in_mm = quantity.to("mm").magnitude

            return value_in_mm

        x_mm = get_param_as_mm("pixel-size-x")
        y_mm = get_param_as_mm("pixel-size-y")
        z_mm = x_mm
        return x_mm, y_mm, z_mm


def _convert_numpy(obj):
    if isinstance(obj, dict):
        return {k: _convert_numpy(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_numpy(i) for i in obj]
    elif isinstance(obj, (np.integer, np.floating, np.ndarray)):
        return obj.tolist()
    else:
        return obj


def _create_attr_text_node(name: str, key: str, value: str) -> slicer.vtkMRMLTextNode:
    text_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTextNode", name)
    text_node.SetText(value)
    text_node.SetAttribute("IsNcAttrs", "1")
    text_node.SetAttribute("AttrKey", key)
    return text_node


def _create_attrs_toml_node(name: str, attrs: dict) -> slicer.vtkMRMLTextNode:
    text_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTextNode", name)
    text_node.SetText(toml.dumps(_convert_numpy(attrs)))
    text_node.SetAttribute("IsNcAttrs", "1")
    return text_node


def _is_attr_node(node: slicer.vtkMRMLNode) -> bool:
    if not isinstance(node, slicer.vtkMRMLTextNode):
        return False
    return node.GetAttribute("IsNcAttrs") == "1"


def _attrs_from_node(node: slicer.vtkMRMLTextNode) -> dict:
    if not _is_attr_node(node):
        raise ValueError(f"Node {node.GetName()} is not a valid attributes node.")
    key = node.GetAttribute("AttrKey")
    text = node.GetText()
    if key:
        return {key: text}
    else:
        return toml.loads(text)


def _create_text_nodes_for_attrs(attrs_dict: dict, base_name: str) -> dict:
    text_nodes = {}

    if not attrs_dict:
        return text_nodes

    small_attrs = {}

    for key, value in attrs_dict.items():
        attr_toml = toml.dumps({key: value})
        if len(attr_toml) > 500 or key.lower() == "pcr":
            node_name = f"{base_name}_attr_{key}"
            if isinstance(value, str):
                text_node = _create_attr_text_node(node_name, key, value)
            else:
                text_node = _create_attrs_toml_node(node_name, {key: value})
            text_nodes[key] = text_node
        else:
            small_attrs[key] = value

    if small_attrs:
        text_node = _create_attrs_toml_node(f"{base_name}_attrs", small_attrs)
        text_nodes[...] = text_node  # Use a non-string key to indicate small attributes

    return text_nodes


def import_dataset(dataset, images="all"):
    has_reference = []
    other = []
    column_items = []

    for name, array in dataset.items():
        if array.dims[0].startswith("table__"):
            column_items.append((name, array))
            continue

        add_to = has_reference if "reference" in array.attrs else other
        add_to.append((name, array))

    # Import nodes with references last so the nodes they reference are already loaded
    array_items = other + has_reference

    role = slicer.vtkMRMLSegmentationNode.GetReferenceImageGeometryReferenceRole()
    imported = {}
    first_scalar = None
    first_label_map = None
    for name, array in array_items:
        if images != "all" and name not in images:
            continue

        if array.ndim < 3:
            continue

        has_labels = "labels" in array.attrs
        is_labelmap = False if "type" not in array.attrs else array.attrs["type"] == "labelmap"
        ijk_to_ras = array.attrs.get("transform")
        single_coords = ijk_to_ras is None
        if single_coords:
            fill_value = 0 if has_labels else 255
            array = _crop_value(array, fill_value)

        if has_labels:
            label_map = createTemporaryVolumeNode(slicer.vtkMRMLLabelMapVolumeNode, name, uniqueName=False)
            _array_to_node(array, label_map)

            color_table = nc_labels_to_color_node(array.labels, name)
            label_map.GetDisplayNode().SetAndObserveColorNodeID(color_table.GetID())

            if is_labelmap:
                makeTemporaryNodePermanent(label_map, show=True)
                node = label_map
                first_label_map = first_label_map or node
            else:
                node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", name)
                updateSegmentationFromLabelMap(node, label_map, includeEmptySegments=True)

            if "reference" in array.attrs:
                master_name = array.attrs["reference"]
                try:
                    master = imported[master_name]
                    node.SetNodeReferenceID(role, master.GetID())
                    if not is_labelmap:
                        node.SetReferenceImageGeometryParameterFromVolumeNode(master)
                except KeyError:
                    pass

            removeTemporaryNodes()
        else:
            class_ = "vtkMRMLVectorVolumeNode" if "c" in array.dims else "vtkMRMLScalarVolumeNode"
            node = slicer.mrmlScene.AddNewNodeByClass(class_, name)
            _array_to_node(array, node)
            first_scalar = first_scalar or node

        special_attrs = {"labels", "type", "reference", "transform"}
        attrs = {k: v for k, v in array.attrs.items() if k not in special_attrs}
        text_nodes = _create_text_nodes_for_attrs(attrs, name) if attrs else {}

        imported[name] = node
        yield (node, list(text_nodes.values()))

    if first_scalar:
        slicer.util.setSliceViewerLayers(background=first_scalar, label=first_label_map, fit=True)
        first_scalar.GetDisplayNode().AutoWindowLevelOn()

    simulation_type = dataset.attrs.get("simulation_type", "")
    if simulation_type.startswith("microtom_"):
        simulator = simulation_type[len("microtom_") :]
        file_name = dataset.attrs.get("simulation_file", "microtom")
        name = f"{Path(file_name).stem}_{simulator}_Variables"

        if "permeability" in dataset.attrs:
            collector = microtom.StokesKabsCompiler()
            attributes = [dataset.attrs]
            node = collector.compile_table(attributes, simulator, name)
        elif f"radii_{simulator}" in dataset:
            collector = microtom.PorosimetryCompiler()
            node = collector.create_table_from(dataset, simulator, name)
        else:
            return

        makeTemporaryNodePermanent(node, show=True)
        autoDetectColumnType(node)
        yield (node, [])

    tables = defaultdict(list)
    for name, column in column_items:
        table_name, column_name = name.split("__")
        tables[table_name].append((column_name, column))

    for table_name, columns in tables.items():
        df = pd.DataFrame({col_name: col.data for col_name, col in columns})
        node = dataFrameToTableNode(df)
        node.SetName(table_name)
        yield (node, [])


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


def _recommended_chunksizes(img):
    chunk_size = round((CHUNK_SIZE_BYTES // img.dtype.itemsize) ** (1 / 3))
    if (
        img.nbytes >= MIN_CHUNKING_SIZE_BYTES
        and img.ndim >= 3
        and all(size >= chunk_size * 4 for size in img.shape[:3])
    ):
        return (chunk_size,) * 3
    return None


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


def _vtk_4x4_to_numpy(matrix_vtk):
    matrix_np = np.empty(16)
    matrix_vtk.DeepCopy(matrix_np, matrix_vtk)
    return matrix_np.reshape(4, 4)


def _get_dataset_main_dims(dataset):
    # Uses a heuristic to find likely zyxc dimensions of a dataset
    for var in dataset:
        array = dataset[var]
        dims = array.dims
        if len(dims) >= 3:
            return dims[:4]


def _get_attrs_from_text_nodes(folder_id, sh):
    attrs = {}

    children = vtk.vtkIdList()
    sh.GetItemChildren(folder_id, children)

    for i in range(children.GetNumberOfIds()):
        child_id = children.GetId(i)

        if sh.GetItemOwnerPluginName(child_id) == "Folder":
            item_name = sh.GetItemName(child_id)
            if not item_name.endswith("_attrs"):
                continue

            sub_children = vtk.vtkIdList()
            sh.GetItemChildren(child_id, sub_children)
            for j in range(sub_children.GetNumberOfIds()):
                sub_child_id = sub_children.GetId(j)
                sub_child_node = sh.GetItemDataNode(sub_child_id)
                if _is_attr_node(sub_child_node):
                    attrs.update(_attrs_from_node(sub_child_node))

    return attrs


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
    sh = slicer.mrmlScene.GetSubjectHierarchyNode()

    callback.on_update("Starting…", 0)

    arrays = {}
    table_arrays = {}
    coords = {}
    nodeNames = nodeNames or [node.GetName() for node in dataNodes]
    nodeNames = _sanitize_var_names(nodeNames)
    nodeDtypes = nodeDtypes or [None] * len(dataNodes)

    id_to_name_map = {node.GetID(): name for node, name in zip(dataNodes, nodeNames)}
    node_attrs = {}
    dataset_attrs = {}
    processed_dataset_folders = set()

    for node, name in zip(dataNodes, nodeNames):
        image_folder_id = sh.GetItemParent(sh.GetItemByDataNode(node))
        if not image_folder_id:
            continue

        attrs = _get_attrs_from_text_nodes(image_folder_id, sh)
        if attrs:
            node_attrs[name] = attrs

        dataset_folder_id = sh.GetItemParent(image_folder_id)
        if dataset_folder_id and dataset_folder_id not in processed_dataset_folders:
            if sh.GetItemAttribute(dataset_folder_id, "netcdf_path"):
                dataset_folder_attrs = _get_attrs_from_text_nodes(dataset_folder_id, sh)
                dataset_attrs.update(dataset_folder_attrs)
                processed_dataset_folders.add(dataset_folder_id)

    if save_in_place:
        existing_dataset = xr.load_dataset(exportPath)
        existing_dims = _get_dataset_main_dims(existing_dataset)

    for node, dtype in zip(dataNodes, nodeDtypes):
        name = id_to_name_map[node.GetID()]

        if isinstance(node, slicer.vtkMRMLTableNode):
            dim_name = f"table__{name}"
            if save_in_place and dim_name in existing_dataset.dims:
                continue

            df = tableNodeToDataFrame(node)

            # Need to deduplicate here otherwise to_xarray will fail
            names = list(df.columns)
            df.columns = _sanitize_var_names(names)

            ds = df.to_xarray()
            ds = ds.rename({"index": dim_name})
            for col_name, data_array in ds.items():
                table_arrays[f"{name}__{col_name}"] = data_array
            continue

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

    if not arrays and not table_arrays:
        raise ValueError("No images to export.\n" + "\n".join(warnings))

    progress_range = np.arange(5, 90, 85 / len(arrays)) if arrays else []
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
    table_dataset = xr.Dataset(table_arrays)
    dataset.update(table_dataset)

    for name in node_attrs:
        if name in dataset:
            dataset[name].attrs.update(node_attrs[name])

    if save_in_place:
        for var in dataset:
            existing_dataset[var] = dataset[var]
        dataset = existing_dataset

    encoding = {}
    for var in dataset:
        img = dataset[var]
        encoding[var] = {"zlib": use_compression, "chunksizes": _recommended_chunksizes(img)}

    dataset.attrs["geoslicer_version"] = slicer.app.applicationVersion
    dataset.attrs.update(dataset_attrs)
    dataset.to_netcdf(exportPath, encoding=encoding, format="NETCDF4")

    return warnings


def import_file(path: Path, callback=lambda *args, **kwargs: None, images="all"):
    """Imports an h5 or nc file."""
    pixel_sizes = None
    if path.suffix in (".h5", ".hdf5"):
        pixel_sizes = extract_pixel_sizes_from_hdf5(path)

    dataset = xr.open_dataset(path)
    dataset_name = path.with_suffix("").name

    sh = slicer.mrmlScene.GetSubjectHierarchyNode()
    scene_id = sh.GetSceneItemID()
    current_dir = sh.CreateFolderItem(scene_id, dataset_name)
    sh.SetItemAttribute(current_dir, "netcdf_path", path.as_posix())

    nodes = []
    for (main_node, aux_nodes), progress in zip(
        import_dataset(dataset, images=images), np.arange(10, 100, 90 / len(dataset))
    ):
        if pixel_sizes:
            main_node.SetSpacing(*pixel_sizes)
        callback("Loading...", progress)

        if aux_nodes:
            image_folder = sh.CreateFolderItem(current_dir, main_node.GetName())
            sh.CreateItem(image_folder, main_node)
            attrs_folder = sh.CreateFolderItem(image_folder, f"{main_node.GetName()}_attrs")
            for aux_node in aux_nodes:
                sh.CreateItem(attrs_folder, aux_node)
        else:
            sh.CreateItem(current_dir, main_node)

        nodes.append(main_node)

    special_dataset_attrs = {"geoslicer_version"}
    dataset_attrs_to_encode = {k: v for k, v in dataset.attrs.items() if k not in special_dataset_attrs}
    if dataset_attrs_to_encode:
        text_nodes = _create_text_nodes_for_attrs(dataset_attrs_to_encode, dataset_name)

        pcr_node = text_nodes.get("pcr") or text_nodes.get("PCR") or text_nodes.get("Pcr")
        if pcr_node is not None:
            for node in nodes:
                node.SetAttribute("PCR", pcr_node.GetID())

        attrs_folder = sh.CreateFolderItem(current_dir, f"{dataset_name}_attrs")
        for _, text_node in text_nodes.items():
            sh.CreateItem(attrs_folder, text_node)
            nodes.append(text_node)

    return nodes
