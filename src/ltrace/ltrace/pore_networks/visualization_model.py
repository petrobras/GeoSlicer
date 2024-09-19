import os
import re

import numba as nb
import numpy as np
import vtk
from vtk.util import numpy_support


PORE_TYPE = 1
TUBE_TYPE = 2
ARROW_TYPE = 3


def visualize_vtu(
    unstructured_grid,
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

    # Spheres glyphs
    polydata = vtk.vtkPolyData()
    polydata.SetPoints(model_elements["coordinates"])
    polydata.SetLines(model_elements["link_elements"])
    polydata.GetPointData().AddArray(model_elements["radii"])
    polydata.GetPointData().AddArray(model_elements["saturation"])
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
        arrows_direction.InsertTuple3(i, 0, 0, 1)
        arrows_position.InsertTuple3(i, *arrow_position)
        arrows_type.InsertTuple1(i, ARROW_TYPE)
        arrows_id.InsertTuple1(i, object_id)
        object_id += 1
        i += 1

    arrow_polydata = vtk.vtkPolyData()
    arrow_polydata.SetPoints(arrows_coordinates)
    arrow_polydata.GetPointData().AddArray(arrows_radii)
    arrow_polydata.GetPointData().AddArray(arrows_saturations)
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


def generate_model_variable_scalar(temp_folder, min_saturation_delta=0.005, is_multiscale=False):
    file_names = sorted([i for i in os.listdir(temp_folder) if i[-4:] == ".vtu"])

    pressures = []
    reader = vtk.vtkXMLUnstructuredGridReader()

    base_filepath = os.path.join(temp_folder, file_names[0])
    reader.SetFileName(base_filepath)
    reader.Update()
    mesh = reader.GetOutput()
    pressure, pore_mesh = visualize_vtu(
        mesh, create_model=False, cycle=file_names[0][2].lower(), normalize_radius=is_multiscale
    )
    point_data = pore_mesh.GetOutput().GetPointData()
    pressures.append(pressure)
    point_data.GetArray("saturation").SetName("saturation_0")

    previous_array = vtk.util.numpy_support.vtk_to_numpy(point_data.GetArray("saturation_0"))
    data_points = []
    data_cycles = []
    i = 0

    for data_point, file_name in enumerate(file_names[1:], start=1):
        filepath = os.path.join(temp_folder, file_name)
        reader.SetFileName(filepath)
        reader.Update()
        mesh = reader.GetOutput()
        pressure, poly_data = visualize_vtu(
            mesh, cycle=file_name[2].lower(), create_model=False, normalize_radius=is_multiscale
        )
        saturation = poly_data.GetOutput().GetPointData().GetArray("saturation")
        new_array = vtk.util.numpy_support.vtk_to_numpy(saturation)

        if np.mean(np.abs(new_array - previous_array)) >= min_saturation_delta:
            saturation.SetName(f"saturation_{(i:=i+1)}")
            point_data.AddArray(saturation)
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
    n_points = unstructured_grid.GetNumberOfPoints()
    n_cells = unstructured_grid.GetNumberOfCells()

    pores = {}  # only points that are in the edges of quadratic edge cells on grid
    throats = {}  # only points that are in the center of quadratic edge cells on grid
    pore_mapper = {}

    linear_size_reduction = 10**-6

    bounds = unstructured_grid.GetPoints().GetBounds()
    x_min = bounds[0]
    x_max = bounds[1]
    x_length = x_max - x_min
    x_min += x_length * linear_size_reduction
    x_max -= x_length * linear_size_reduction

    z_min = bounds[4]
    z_max = bounds[5]
    # z_length = z_max - z_min
    # z_min -= z_length * linear_size_reduction
    # z_max += z_length * linear_size_reduction

    y_min = bounds[2]
    y_max = bounds[3]
    # y_length = y_max - y_min
    # y_min -= y_length * linear_size_reduction
    # y_max += y_length * linear_size_reduction

    throat_id_list = np.empty(n_cells, dtype=np.int64)
    throat_index_list = np.empty(n_cells, dtype=np.int64)
    neighbors_id_list = np.empty((n_cells, 2), dtype=np.int64)
    throat_radius_list = np.empty(n_cells, dtype=np.float64)

    position_list = np.empty((n_points, 3), dtype=np.float64)
    pore_radius_list = np.empty(n_points, dtype=np.float64)
    sw_list = np.empty(n_points, dtype=np.float64)
    inlet_bool_list = np.full(n_points, False, dtype=np.bool_)
    outlet_bool_list = np.full(n_points, False, dtype=np.bool_)

    throat_count = 0
    pore_count = 0

    for i in range(n_cells):
        left_pore_id = unstructured_grid.GetCell(i).GetPointIds().GetId(0)
        right_pore_id = unstructured_grid.GetCell(i).GetPointIds().GetId(1)
        left_pos = unstructured_grid.GetPoint(left_pore_id)
        right_pos = unstructured_grid.GetPoint(right_pore_id)
        if (
            left_pos[2] < z_min
            or left_pos[2] > z_max
            or right_pos[2] < z_min
            or right_pos[2] > z_max
            or left_pos[1] < y_min
            or left_pos[1] > y_max
            or right_pos[1] < y_min
            or right_pos[1] > y_max
            or (left_pos[0] > x_max and right_pos[0] > x_max)
        ):
            continue

        throat_id = unstructured_grid.GetCell(i).GetPointIds().GetId(2)
        throat_radius = unstructured_grid.GetCellData().GetArray("RRR").GetComponent(i, 0)

        throat_id_list[throat_count] = throat_id
        throat_index_list[throat_count] = i
        neighbors_id_list[throat_count] = (left_pore_id, right_pore_id)
        throat_radius_list[throat_count] = throat_radius

        throat_count += 1

        for pore_position in (left_pore_id, right_pore_id):
            if pore_position not in pore_mapper.keys():
                position = unstructured_grid.GetPoint(pore_position)
                x_pos = position[0]
                if axis == "x":
                    position = position[-1::-1]
                radius = unstructured_grid.GetPointData().GetArray("radius").GetComponent(pore_position, 0)

                pore_mapper[pore_position] = pore_count
                if x_pos < x_min:
                    if cycle == "w":
                        sw = 1
                    else:  # cycle == 'o'
                        sw = 0
                    inlet_bool_list[pore_count] = True
                elif x_pos > x_max:
                    if pore_position == left_pore_id:
                        sw = unstructured_grid.GetPointData().GetArray("Sw").GetComponent(right_pore_id, 0)
                        other_x = unstructured_grid.GetPoint(right_pore_id)[2]
                    else:
                        sw = unstructured_grid.GetPointData().GetArray("Sw").GetComponent(left_pore_id, 0)
                        other_x = unstructured_grid.GetPoint(left_pore_id)[2]
                    if other_x < x_max:
                        outlet_bool_list[pore_count] = True
                else:
                    sw = unstructured_grid.GetPointData().GetArray("Sw").GetComponent(pore_position, 0)

                position_list[pore_count] = position
                pore_radius_list[pore_count] = radius
                sw_list[pore_count] = sw

                pore_count += 1

    if normalize_radius:
        volume = (x_max - x_min) * (y_max - y_min) * (z_max - z_min)
        volume_pore_ratio = (volume / n_points) ** (1.0 / 3.0)

        max_pore_radius_factor = 850
        min_pore_radius_factor = 200
        max_throat_radius_factor = 110
        min_throat_radius_factor = 30

        max_pore_radius = max_pore_radius_factor * volume_pore_ratio
        min_pore_radius = min_pore_radius_factor * volume_pore_ratio
        max_throat_radius = max_throat_radius_factor * volume_pore_ratio
        min_throat_radius = min_throat_radius_factor * volume_pore_ratio

        pore_radius_list[:pore_count] = np.interp(
            pore_radius_list[:pore_count],
            (pore_radius_list[:pore_count].min(), pore_radius_list[:pore_count].max()),
            (min_pore_radius, max_pore_radius),
        )

        throat_radius_list[:throat_count] = np.interp(
            throat_radius_list[:throat_count],
            (throat_radius_list[:throat_count].min(), throat_radius_list[:throat_count].max()),
            (min_throat_radius, max_throat_radius),
        )
    else:
        pore_radius_list[:pore_count] *= pore_scale
        throat_radius_list[:throat_count] *= throat_scale

    volume = (x_max - x_min) * (y_max - y_min) * (z_max - z_min)
    volume_side = volume ** (1.0 / 3.0)

    inlet_arrows_positions = position_list[inlet_bool_list] * scale_factor
    inlet_arrows_positions[:, 2] -= volume_side * arrow_scale + pore_radius_list[inlet_bool_list] / 2
    outlet_arrows_positions = position_list[outlet_bool_list] * scale_factor
    outlet_arrows_positions[:, 2] += pore_radius_list[outlet_bool_list] / 2

    arrows = []
    for i, sw in enumerate(sw_list[inlet_bool_list]):
        arrows.append((inlet_arrows_positions[i], sw))
    for i, sw in enumerate(sw_list[outlet_bool_list]):
        arrows.append((outlet_arrows_positions[i], sw))

    pores = {}
    for i in range(pore_count):
        pores[i] = {
            "position": position_list[i],
            "radius": pore_radius_list[i],
            "Sw": sw_list[i],
        }

    throats = {}
    for i in range(throat_count):
        throat_index = throat_index_list[i]
        throat_id = throat_id_list[i]
        left_pore_id, right_pore_id = neighbors_id_list[i]
        throats[throat_index] = {
            "first_conn": pore_mapper[left_pore_id],
            "second_conn": pore_mapper[right_pore_id],
            "radius": throat_radius_list[i],
            "Sw": unstructured_grid.GetPointData().GetArray("Sw").GetComponent(throat_id, 0),
            "Sw_cell": unstructured_grid.GetCellData().GetArray("Sw").GetComponent(throat_index, 0),
        }

    coordinates = vtk.vtkPoints()
    radii = vtk.vtkFloatArray()
    radii.SetName("radius")
    saturation = vtk.vtkFloatArray()
    saturation.SetName("saturation")
    pore_position = vtk.vtkFloatArray()
    pore_position.SetNumberOfComponents(3)
    pore_position.SetName("position")
    pore_type = vtk.vtkIntArray()
    pore_type.SetName("type")
    pore_id = vtk.vtkIntArray()
    pore_id.SetName("id")

    object_id = 0
    for pore_index, pore_data in pores.items():
        pos_x, pos_y, pos_z = pore_data["position"]
        pos_x = pos_x * scale_factor
        pos_y = pos_y * scale_factor
        pos_z = pos_z * scale_factor
        coordinates.InsertPoint(pore_index, pos_x, pos_y, pos_z)
        radii.InsertTuple1(pore_index, pore_data["radius"])
        saturation.InsertTuple1(pore_index, pore_data["Sw"])
        pore_position.InsertTuple3(pore_index, pos_x, pos_y, pos_z)
        pore_type.InsertTuple1(pore_index, PORE_TYPE)
        pore_id.InsertTuple1(pore_index, object_id)
        object_id += 1

    max_radius = 0
    min_radius = np.inf
    link_elements = vtk.vtkCellArray()
    tubes_coordinates = vtk.vtkPoints()
    tubes_radii = vtk.vtkFloatArray()
    tubes_radii.SetName("radius")
    tubes_saturation = vtk.vtkFloatArray()
    tubes_saturation.SetName("saturation")
    tubes_position = vtk.vtkFloatArray()
    tubes_position.SetNumberOfComponents(3)
    tubes_position.SetName("position")
    tubes_type = vtk.vtkIntArray()
    tubes_type.SetName("type")
    tubes_id = vtk.vtkIntArray()
    tubes_id.SetName("id")
    for i, throat in enumerate(throats.values()):
        first_conn = throat["first_conn"]
        second_conn = throat["second_conn"]
        throat_radius = throat["radius"]
        throat_sw = throat["Sw_cell"]

        pos_x, pos_y, pos_z = pores[first_conn]["position"]
        pos_x = pos_x * scale_factor
        pos_y = pos_y * scale_factor
        pos_z = pos_z * scale_factor
        point_0_index = i * 2
        tubes_coordinates.InsertPoint(point_0_index, pos_x, pos_y, pos_z)
        tubes_position.InsertTuple3(point_0_index, pos_x, pos_y, pos_z)
        tubes_radii.InsertTuple1(point_0_index, throat_radius)
        tubes_saturation.InsertTuple1(point_0_index, throat_sw)

        pos_x, pos_y, pos_z = pores[second_conn]["position"]
        pos_x = pos_x * scale_factor
        pos_y = pos_y * scale_factor
        pos_z = pos_z * scale_factor
        point_1_index = i * 2 + 1
        tubes_coordinates.InsertPoint(point_1_index, pos_x, pos_y, pos_z)
        tubes_position.InsertTuple3(point_1_index, pos_x, pos_y, pos_z)
        tubes_radii.InsertTuple1(point_1_index, throat_radius)
        tubes_saturation.InsertTuple1(point_1_index, throat_sw)

        elementIdList = vtk.vtkIdList()
        _ = elementIdList.InsertNextId(point_0_index)
        _ = elementIdList.InsertNextId(point_1_index)
        _ = link_elements.InsertNextCell(elementIdList)
        if throat_radius > 0:
            min_radius = min(min_radius, throat_radius)
        max_radius = max(max_radius, throat_radius)
        tubes_type.InsertTuple1(point_0_index, TUBE_TYPE)
        tubes_type.InsertTuple1(point_1_index, TUBE_TYPE)
        tubes_id.InsertTuple1(point_0_index, object_id)
        tubes_id.InsertTuple1(point_1_index, object_id)
        object_id += 1

    return {
        "last_object_id": object_id,
        "coordinates": coordinates,
        "link_elements": link_elements,
        "radii": radii,
        "saturation": saturation,
        "pore_position": pore_position,
        "pore_type": pore_type,
        "pore_id": pore_id,
        "tubes_saturation": tubes_saturation,
        "tubes_position": tubes_position,
        "tubes_type": tubes_type,
        "tubes_id": tubes_id,
        "tubes_radii": tubes_radii,
        "tubes_coordinates": tubes_coordinates,
        "max_radius": max_radius,
        "min_radius": min_radius,
        "arrows": arrows,
        "volume_side": volume_side,
    }
