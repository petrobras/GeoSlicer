import os
import re

import numba as nb
import numpy as np
import vtk
from vtk.util import numpy_support


PORE_TYPE = 1
TUBE_TYPE = 2
ARROW_TYPE = 3


def _visualize_vtu(
    filepath,
    cycle,
    scale_factor=10**3,
    pore_scale=2000,
    throat_scale=500,
    arrow_scale=150,
    axis="x",
    normalize_radius=False,
    **kwargs,
):
    """
    unstructured_grid (vtkUnstructuredGrid)
        VtkUnstructured grid, as loaded from the output folder of PNFlow
    cycle (str)
        Must be 'w' for wetting phase (usually waater) injection cycles and 'o'
        for non-wetting phase (usually oil) injection cycles
    """
    if axis == "x":
        arrow_x = 0
        arrow_y = 0
        arrow_z = 1
    elif axis == "y":
        arrow_x = 0
        arrow_y = 1
        arrow_z = 0
    elif axis == "z":
        arrow_x = 1
        arrow_y = 0
        arrow_z = 0

    reader = vtk.vtkXMLUnstructuredGridReader()
    reader.SetFileName(filepath)
    reader.Update()
    unstructured_grid = reader.GetOutput()

    # large networks are dominated by geometry cost, so drop tesselation detail past this
    # size to keep import fast; smaller networks stay at full quality since it's cheap
    LARGE_NETWORK_PORE_COUNT = 100_000
    if unstructured_grid.GetNumberOfPoints() > LARGE_NETWORK_PORE_COUNT:
        sphere_theta_resolution = 5
        sphere_phi_resolution = 5
        arrow_tip_resolution = 4
        arrow_shaft_resolution = 4
        tubes_resolution = 4
    else:
        sphere_theta_resolution = 8
        sphere_phi_resolution = 8
        arrow_tip_resolution = 8
        arrow_shaft_resolution = 8
        tubes_resolution = 6

    model_elements = _model_elements_from_grid(
        unstructured_grid,
        cycle,
        scale_factor,
        pore_scale,
        throat_scale,
        arrow_scale,
        axis=axis,
        normalize_radius=normalize_radius,
    )
    object_id = model_elements["last_object_id"]
    if "volume_side" in model_elements:
        arrow_scale *= model_elements["volume_side"]

    ### Set up point coordinates and scalars for spheres and tubes ###
    spheres_condW = vtk.vtkFloatArray()
    spheres_condW.SetName("condW")
    spheres_condW.SetNumberOfValues(model_elements["radii"].GetNumberOfTuples())
    spheres_condW.Fill(0)
    spheres_condO = vtk.vtkFloatArray()
    spheres_condO.SetName("condO")
    spheres_condO.SetNumberOfValues(model_elements["radii"].GetNumberOfTuples())
    spheres_condO.Fill(0)

    # Spheres glyphs
    polydata = vtk.vtkPolyData()
    polydata.SetPoints(model_elements["coordinates"])
    polydata.SetLines(model_elements["link_elements"])
    polydata.GetPointData().AddArray(model_elements["radii"])
    polydata.GetPointData().AddArray(model_elements["saturation"])
    polydata.GetPointData().AddArray(spheres_condW)
    polydata.GetPointData().AddArray(spheres_condO)
    polydata.GetPointData().AddArray(model_elements["pore_position"])
    polydata.GetPointData().AddArray(model_elements["pore_type"])
    polydata.GetPointData().AddArray(model_elements["pore_id"])
    polydata.GetPointData().SetActiveScalars("radius")

    sphereSource = vtk.vtkSphereSource()
    sphereSource.SetThetaResolution(sphere_theta_resolution)
    sphereSource.SetPhiResolution(sphere_phi_resolution)
    glyph3D = vtk.vtkGlyph3D()
    glyph3D.SetScaleModeToScaleByScalar()
    glyph3D.SetScaleFactor(1)
    glyph3D.SetSourceConnection(sphereSource.GetOutputPort())
    glyph3D.SetInputData(polydata)
    glyph3D.Update()

    # Arrows glyphs
    arrows_coordinates = vtk.vtkPoints()
    arrows_radii = vtk.vtkFloatArray()
    arrows_radii.SetName("radius")
    arrows_saturations = vtk.vtkFloatArray()
    arrows_saturations.SetName("saturation")
    arrows_condW = vtk.vtkFloatArray()
    arrows_condW.SetName("condW")
    arrows_condO = vtk.vtkFloatArray()
    arrows_condO.SetName("condO")
    arrows_direction = vtk.vtkFloatArray()
    arrows_direction.SetName("direction")
    arrows_direction.SetNumberOfComponents(3)
    arrows_position = vtk.vtkFloatArray()
    arrows_position.SetNumberOfComponents(3)
    arrows_position.SetName("position")
    arrows_type = vtk.vtkIntArray()
    arrows_type.SetName("type")
    arrows_id = vtk.vtkIntArray()
    arrows_id.SetName("id")

    i = 0
    for arrow_position, arrow_saturation in model_elements["arrows"]:
        arrows_coordinates.InsertPoint(i, *arrow_position)
        arrows_radii.InsertTuple1(i, 1)
        arrows_saturations.InsertTuple1(i, arrow_saturation)
        arrows_condW.InsertTuple1(i, 0)
        arrows_condO.InsertTuple1(i, 0)
        arrows_direction.InsertTuple3(i, arrow_x, arrow_y, arrow_z)
        arrows_position.InsertTuple3(i, *arrow_position)
        arrows_type.InsertTuple1(i, ARROW_TYPE)
        arrows_id.InsertTuple1(i, object_id)
        object_id += 1
        i += 1

    arrow_polydata = vtk.vtkPolyData()
    arrow_polydata.SetPoints(arrows_coordinates)
    arrow_polydata.GetPointData().AddArray(arrows_radii)
    arrow_polydata.GetPointData().AddArray(arrows_saturations)
    arrow_polydata.GetPointData().AddArray(arrows_condW)
    arrow_polydata.GetPointData().AddArray(arrows_condO)
    arrow_polydata.GetPointData().AddArray(arrows_position)
    arrow_polydata.GetPointData().AddArray(arrows_type)
    arrow_polydata.GetPointData().AddArray(arrows_id)
    arrow_polydata.GetPointData().SetActiveScalars("radius")
    arrow_polydata.GetPointData().AddArray(arrows_direction)
    arrow_polydata.GetPointData().SetActiveVectors("direction")

    arrowSource = vtk.vtkArrowSource()
    arrowSource.SetTipResolution(arrow_tip_resolution)
    arrowSource.SetShaftResolution(arrow_shaft_resolution)
    arrowSource.SetTipRadius(0.15)
    arrow_glyph3D = vtk.vtkGlyph3D()
    arrow_glyph3D.SetScaleFactor(arrow_scale)
    arrow_glyph3D.SetSourceConnection(arrowSource.GetOutputPort())
    arrow_glyph3D.SetInputData(arrow_polydata)
    arrow_glyph3D.SetVectorModeToUseVector()
    arrow_glyph3D.Update()

    # Tubes filter

    tubes_polydata = vtk.vtkPolyData()
    tubes_polydata.SetPoints(model_elements["tubes_coordinates"])
    tubes_polydata.SetLines(model_elements["link_elements"])
    tubes_polydata.GetPointData().AddArray(model_elements["tubes_radii"])
    tubes_polydata.GetPointData().AddArray(model_elements["tubes_saturation"])
    tubes_polydata.GetPointData().AddArray(model_elements["tubes_condW"])
    tubes_polydata.GetPointData().AddArray(model_elements["tubes_condO"])
    tubes_polydata.GetPointData().AddArray(model_elements["tubes_position"])
    tubes_polydata.GetPointData().AddArray(model_elements["tubes_type"])
    tubes_polydata.GetPointData().AddArray(model_elements["tubes_id"])
    tubes_polydata.GetPointData().SetActiveScalars("radius")

    tubes = vtk.vtkTubeFilter()
    tubes.SetInputData(tubes_polydata)
    tubes.SetNumberOfSides(tubes_resolution)
    tubes.SetVaryRadiusToVaryRadiusByScalar()
    tubes.SetRadius(model_elements["min_radius"])  # Actually this sets the minimum radius
    tubes.SetRadiusFactor((model_elements["max_radius"] / model_elements["min_radius"]) ** (1.0))
    tubes.Update()

    normals = tubes.GetOutput().GetPointData().GetNormals()
    normals.SetName("Normals")
    normals = glyph3D.GetOutput().GetPointData().GetNormals()
    normals.SetName("Normals")

    arrow_glyph3D_with_normals = vtk.vtkPolyDataNormals()
    arrow_glyph3D_with_normals.SetSplitting(False)
    arrow_glyph3D_with_normals.SetInputConnection(arrow_glyph3D.GetOutputPort())
    arrow_glyph3D_with_normals.Update()

    normals = arrow_glyph3D_with_normals.GetOutput().GetPointData().GetNormals()
    normals.SetName("Normals")

    merger = vtk.vtkAppendPolyData()
    merger.AddInputConnection(tubes.GetOutputPort())
    merger.AddInputConnection(glyph3D.GetOutputPort())
    merger.AddInputConnection(arrow_glyph3D_with_normals.GetOutputPort())
    merger.Update()

    pressure = unstructured_grid.GetCellData().GetArray("Pc").GetComponent(0, 0)

    return pressure, merger


def _quantize_to_uint16(vtk_float_array):
    """Rescale a float array to the uint16 range, halving its memory footprint.

    Safe only for arrays whose consumer reads the color range from the data itself
    (e.g. vtkMRMLDisplayNode's SetScalarRangeFlag(1)) rather than a fixed physical range,
    since the absolute values are not preserved, only their relative order/spacing.
    """
    values = vtk.util.numpy_support.vtk_to_numpy(vtk_float_array)
    value_min = values.min()
    value_max = values.max()
    if value_max > value_min:
        scaled = (values - value_min) / (value_max - value_min) * 65535
    else:
        scaled = np.zeros_like(values)
    quantized_array = vtk.util.numpy_support.numpy_to_vtk(scaled.astype(np.uint16), deep=True)
    quantized_array.SetName(vtk_float_array.GetName())
    return quantized_array


def generate_model_variable_scalar(temp_folder, is_multiscale=False, **kwargs):
    file_names = sorted([i for i in os.listdir(temp_folder) if i[-4:] == ".vtu"])

    pressures = []
    base_filepath = os.path.join(temp_folder, file_names[0])
    pressure, pore_mesh = _visualize_vtu(
        base_filepath,
        create_model=False,
        cycle=file_names[0][2].lower(),
        normalize_radius=is_multiscale,
        **kwargs,
    )
    point_data = pore_mesh.GetOutput().GetPointData()
    pressures.append(pressure)
    point_data.GetArray("saturation").SetName("saturation_0")
    condW_0 = _quantize_to_uint16(point_data.GetArray("condW"))
    condW_0.SetName("condW_0")
    condO_0 = _quantize_to_uint16(point_data.GetArray("condO"))
    condO_0.SetName("condO_0")
    point_data.RemoveArray("condW")
    point_data.RemoveArray("condO")
    point_data.AddArray(condW_0)
    point_data.AddArray(condO_0)

    previous_array = vtk.util.numpy_support.vtk_to_numpy(point_data.GetArray("saturation_0"))
    data_points = []
    data_cycles = []
    i = 0

    for data_point, file_name in enumerate(file_names[1:], start=1):
        filepath = os.path.join(temp_folder, file_name)
        pressure, poly_data = _visualize_vtu(
            filepath,
            cycle=file_name[2].lower(),
            create_model=False,
            normalize_radius=is_multiscale,
            **kwargs,
        )
        saturation = poly_data.GetOutput().GetPointData().GetArray("saturation")
        new_array = vtk.util.numpy_support.vtk_to_numpy(saturation)
        condW = poly_data.GetOutput().GetPointData().GetArray("condW")
        condO = poly_data.GetOutput().GetPointData().GetArray("condO")

        if data_point == 1 or np.mean(np.abs(new_array - previous_array)) != 0.0:
            saturation.SetName(f"saturation_{(i:=i+1)}")
            condW_quantized = _quantize_to_uint16(condW)
            condW_quantized.SetName(f"condW_{i}")
            condO_quantized = _quantize_to_uint16(condO)
            condO_quantized.SetName(f"condO_{i}")
            point_data.AddArray(saturation)
            point_data.AddArray(condW_quantized)
            point_data.AddArray(condO_quantized)
            pressures.append(pressure)
            previous_array = new_array
            file = open(filepath, "r")
            result = re.search("<!--[^#]+# Sw: ([\\d\\.e-]+) Cycle: (\\d+) -->", file.read())
            data_points.append(float(result.group(1)))
            data_cycles.append(float(result.group(2)))
            file.close()

    saturation_steps = i

    bounds = pore_mesh.GetOutput().GetBounds()
    box = vtk.vtkBox()
    box.SetBounds(*bounds)
    extract = vtk.vtkExtractPolyDataGeometry()
    extract.SetImplicitFunction(box)
    extract.ExtractBoundaryCellsOn()
    extract.SetInputConnection(pore_mesh.GetOutputPort())
    extract.ExtractInsideOn()
    extract.Update()

    data_points_vtk = vtk.util.numpy_support.numpy_to_vtk(np.array(data_points))
    data_points_vtk.SetName("data_points")
    data_cycles_vtk = vtk.util.numpy_support.numpy_to_vtk(np.array(data_cycles))
    data_cycles_vtk.SetName("data_cycles")
    extract.GetOutput().GetPointData().AddArray(data_points_vtk)
    extract.GetOutput().GetPointData().AddArray(data_cycles_vtk)

    return extract.GetOutputDataObject(0), saturation_steps


def _unstructured_grid_to_arrays(
    unstructured_grid,
    cycle,
    scale_factor=10**3,
    pore_scale=2000,
    throat_scale=20,
    arrow_scale=0.2,
    axis="x",
    normalize_radius=False,
    **kwargs,
):
    """Vectorized equivalent of the old per-element _unstructured_grid_to_dict.

    Reads pore/throat data straight from the vtk arrays with numpy, instead of looping
    over every point/cell in Python and calling the vtk API one element at a time
    (which dominated import time on large networks).

    Args:
        unstructured_grid (vtkUnstructuredGrid): unstructured_grid
        cycle (char): "w" for water injection, "o" for oil injection
        scale_factor (float): Scales entire network
        pore_scale (float): Scales pore sizes
        throat_scale (float): Scale throat sizes
        arrow_scale (float): Scale arrow sizes
        axis (char): axis
        normalize_radius (bool): If true, ignore throats and pores scale factors and normalize their size by the grid volume

    Returns:
        dict: model elements data, in flat numpy-array form
    """
    if axis == "x":
        arrow_displacement_axis = 2
    elif axis == "y":
        arrow_displacement_axis = 1
    elif axis == "z":
        arrow_displacement_axis = 0

    n_points = unstructured_grid.GetNumberOfPoints()

    bounds = unstructured_grid.GetPoints().GetBounds()
    x_min, x_max = bounds[0], bounds[1]
    y_min, y_max = bounds[2], bounds[3]
    z_min, z_max = bounds[4], bounds[5]

    point_data = unstructured_grid.GetPointData()
    cell_data = unstructured_grid.GetCellData()

    connectivity = numpy_support.vtk_to_numpy(unstructured_grid.GetCells().GetConnectivityArray())
    n_cells = unstructured_grid.GetNumberOfCells()
    assert connectivity.size == 2 * n_cells, (
        "expected every cell to be a 2-point line (VTK_LINE); got a connectivity array "
        f"of size {connectivity.size} for {n_cells} cells"
    )
    neighbors_id_list = connectivity.reshape(-1, 2).astype(np.int64)
    throat_radius_list = numpy_support.vtk_to_numpy(cell_data.GetArray("RRR")).astype(np.float64).copy()
    throat_sw_list = numpy_support.vtk_to_numpy(cell_data.GetArray("Sw")).astype(np.float64)
    throat_condW_list = numpy_support.vtk_to_numpy(cell_data.GetArray("condW")).astype(np.float64)
    throat_condO_list = numpy_support.vtk_to_numpy(cell_data.GetArray("condO")).astype(np.float64)

    position_list = numpy_support.vtk_to_numpy(unstructured_grid.GetPoints().GetData()).astype(np.float64)
    position_list = position_list[:, ::-1].copy()
    radius_arr = numpy_support.vtk_to_numpy(point_data.GetArray("radius")).astype(np.float64)
    sw_list = numpy_support.vtk_to_numpy(point_data.GetArray("Sw")).astype(np.float64)
    inlet_bool_list = numpy_support.vtk_to_numpy(point_data.GetArray("inlets")) == 1
    outlet_bool_list = numpy_support.vtk_to_numpy(point_data.GetArray("outlets")) == 1

    pore_radius_list = np.where(sw_list == 0.5, 0.0, radius_arr)

    if normalize_radius:
        volume = (x_max - x_min) * (y_max - y_min) * (z_max - z_min)
        volume_pore_ratio = (volume / n_points) ** (1.0 / 3.0)

        max_pore_radius = 850 * volume_pore_ratio
        min_pore_radius = 200 * volume_pore_ratio
        max_throat_radius = 110 * volume_pore_ratio
        min_throat_radius = 30 * volume_pore_ratio

        pore_radius_list = np.interp(
            pore_radius_list,
            (pore_radius_list.min(), pore_radius_list.max()),
            (min_pore_radius, max_pore_radius),
        )
        throat_radius_list = np.interp(
            throat_radius_list,
            (throat_radius_list.min(), throat_radius_list.max()),
            (min_throat_radius, max_throat_radius),
        )
    else:
        pore_radius_list = pore_radius_list * pore_scale
        throat_radius_list = throat_radius_list * throat_scale

    volume = (x_max - x_min) * (y_max - y_min) * (z_max - z_min)
    volume_side = volume ** (1.0 / 3.0)

    inlet_arrows_positions = position_list[inlet_bool_list] * scale_factor
    inlet_arrows_positions[:, arrow_displacement_axis] -= (
        volume_side * arrow_scale + pore_radius_list[inlet_bool_list] / 2
    )
    outlet_arrows_positions = position_list[outlet_bool_list] * scale_factor
    outlet_arrows_positions[:, arrow_displacement_axis] += pore_radius_list[outlet_bool_list] / 2

    arrows = list(zip(inlet_arrows_positions, sw_list[inlet_bool_list])) + list(
        zip(outlet_arrows_positions, sw_list[outlet_bool_list])
    )

    return {
        "position_list": position_list,
        "pore_radius_list": pore_radius_list,
        "sw_list": sw_list,
        "neighbors_id_list": neighbors_id_list,
        "throat_radius_list": throat_radius_list,
        "throat_sw_list": throat_sw_list,
        "throat_condW_list": throat_condW_list,
        "throat_condO_list": throat_condO_list,
        "arrows": arrows,
        "volume_side": volume_side,
    }


def _model_elements_from_grid(
    unstructured_grid,
    cycle,
    scale_factor=10**3,
    pore_scale=2000,
    throat_scale=20,
    arrow_scale=0.2,
    axis="x",
    normalize_radius=False,
    **kwargs,
):
    """Model elements from unstructured grid

    Args:
        unstructured_grid (vtkUnstructuredGrid): unstructured_grid
        cycle (char): "w" for water injection, "o" for oil injection
        scale_factor (float): Scales entire network
        pore_scale (float): Scales pore sizes
        throat_scale (float): Scale throat sizes
        arrow_scale (float): Scale arrow sizes
        axis (char): axis
        normalize_radius (bool): If true, ignore throats and pores scale factors and normalize their size by the grid volume

    Returns:
        dict: model elements data
    """
    elements = _unstructured_grid_to_arrays(
        unstructured_grid, cycle, scale_factor, pore_scale, throat_scale, arrow_scale, axis, normalize_radius
    )

    n_points = elements["position_list"].shape[0]
    n_throats = elements["neighbors_id_list"].shape[0]

    scaled_positions = (elements["position_list"] * scale_factor).astype(np.float32)

    coordinates = vtk.vtkPoints()
    coordinates.SetData(numpy_support.numpy_to_vtk(scaled_positions, deep=True))

    radii = numpy_support.numpy_to_vtk(elements["pore_radius_list"].astype(np.float32), deep=True)
    radii.SetName("radius")
    saturation = numpy_support.numpy_to_vtk(elements["sw_list"].astype(np.float32), deep=True)
    saturation.SetName("saturation")
    pore_position = numpy_support.numpy_to_vtk(scaled_positions, deep=True)
    pore_position.SetName("position")
    pore_type = numpy_support.numpy_to_vtk(np.full(n_points, PORE_TYPE, dtype=np.int32), deep=True)
    pore_type.SetName("type")
    pore_id = numpy_support.numpy_to_vtk(np.arange(n_points, dtype=np.int32), deep=True)
    pore_id.SetName("id")

    first_idx = elements["neighbors_id_list"][:, 0]
    second_idx = elements["neighbors_id_list"][:, 1]
    tube_positions = np.empty((2 * n_throats, 3), dtype=np.float32)
    tube_positions[0::2] = scaled_positions[first_idx]
    tube_positions[1::2] = scaled_positions[second_idx]

    tubes_coordinates = vtk.vtkPoints()
    tubes_coordinates.SetData(numpy_support.numpy_to_vtk(tube_positions, deep=True))

    tubes_radii = numpy_support.numpy_to_vtk(np.repeat(elements["throat_radius_list"], 2).astype(np.float32), deep=True)
    tubes_radii.SetName("radius")
    tubes_saturation = numpy_support.numpy_to_vtk(
        np.repeat(elements["throat_sw_list"], 2).astype(np.float32), deep=True
    )
    tubes_saturation.SetName("saturation")
    tubes_condW = numpy_support.numpy_to_vtk(np.repeat(elements["throat_condW_list"], 2).astype(np.float32), deep=True)
    tubes_condW.SetName("condW")
    tubes_condO = numpy_support.numpy_to_vtk(np.repeat(elements["throat_condO_list"], 2).astype(np.float32), deep=True)
    tubes_condO.SetName("condO")
    tubes_position = numpy_support.numpy_to_vtk(tube_positions, deep=True)
    tubes_position.SetName("position")
    tubes_type = numpy_support.numpy_to_vtk(np.full(2 * n_throats, TUBE_TYPE, dtype=np.int32), deep=True)
    tubes_type.SetName("type")
    tubes_id = numpy_support.numpy_to_vtk(
        np.repeat(np.arange(n_points, n_points + n_throats, dtype=np.int32), 2), deep=True
    )
    tubes_id.SetName("id")

    # each throat i owns points (2i, 2i+1); build the line cells' offsets/connectivity in bulk
    offsets = np.arange(0, 2 * (n_throats + 1), 2, dtype=np.int64)
    tube_connectivity = np.arange(2 * n_throats, dtype=np.int64)
    link_elements = vtk.vtkCellArray()
    link_elements.SetData(
        numpy_support.numpy_to_vtkIdTypeArray(offsets, deep=True),
        numpy_support.numpy_to_vtkIdTypeArray(tube_connectivity, deep=True),
    )

    throat_radius_list = elements["throat_radius_list"]
    positive_radii = throat_radius_list[throat_radius_list > 0]
    min_radius = float(positive_radii.min()) if positive_radii.size > 0 else np.inf
    max_radius = max(0.0, float(throat_radius_list.max())) if throat_radius_list.size > 0 else 0.0

    return {
        "last_object_id": n_points + n_throats,
        "coordinates": coordinates,
        "link_elements": link_elements,
        "radii": radii,
        "saturation": saturation,
        "pore_position": pore_position,
        "pore_type": pore_type,
        "pore_id": pore_id,
        "tubes_saturation": tubes_saturation,
        "tubes_condW": tubes_condW,
        "tubes_condO": tubes_condO,
        "tubes_position": tubes_position,
        "tubes_type": tubes_type,
        "tubes_id": tubes_id,
        "tubes_radii": tubes_radii,
        "tubes_coordinates": tubes_coordinates,
        "max_radius": max_radius,
        "min_radius": min_radius,
        "arrows": elements["arrows"],
        "volume_side": elements["volume_side"],
    }
