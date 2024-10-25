import vtk
import slicer
import logging
import xarray as xr
import logging

from PIL import ImageColor
from pathlib import Path
from ltrace.slicer.helpers import (
    autoDetectColumnType,
    create_color_table,
    createTemporaryVolumeNode,
    makeTemporaryNodePermanent,
    removeTemporaryNodes,
    updateSegmentationFromLabelMap,
)
from typing import List, Tuple

from ltrace.readers import microtom


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


def import_dataset(dataset, images="all"):
    has_reference = []
    other = []

    for name, array in dataset.items():
        add_to = has_reference if "reference" in array.attrs else other
        add_to.append((name, array))

    # Import nodes with references last so the nodes they reference are already loaded
    all_items = other + has_reference

    role = slicer.vtkMRMLSegmentationNode.GetReferenceImageGeometryReferenceRole()
    imported = {}
    first_scalar = None
    first_label_map = None
    for name, array in all_items:
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

        imported[name] = node
        yield node

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
        yield node
