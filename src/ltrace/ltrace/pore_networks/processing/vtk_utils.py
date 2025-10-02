import vtk
import os

import numpy as np


class GlyphCreator:
    def __init__(self, glyph_filter, length_array, radius):
        self.glyph_filter = glyph_filter
        self.length_array = length_array
        self.radius = radius

    def __call__(self):
        point_coords = self.glyph_filter.GetPoint()
        point_id = self.glyph_filter.GetPointId()
        length = self.length_array[point_id]

        source = vtk.vtkLineSource()
        source.SetPoint1(point_coords)
        source.SetPoint2(
            point_coords[0] * (1.41 + length), point_coords[1] * (1.41 + length), point_coords[2] * (1.41 + length)
        )
        tube = vtk.vtkTubeFilter()
        tube.SetNumberOfSides(6)
        tube.SetRadius(self.radius)
        tube.SetCapping(True)
        tube.SetInputConnection(source.GetOutputPort())
        self.glyph_filter.SetSourceConnection(tube.GetOutputPort())


def create_flow_model(
    project,
    pore_values,
    throat_values,
    sizes,
    pore_diameters=None,
    throat_diameters=None,
    IJKTORAS=(-1, -1, 1),
    throat_radius_reduction=5,
):
    if sizes:
        offset = [10 * sizes[axis] if IJKTORAS[i] < 0 else 0 for i, axis in enumerate(["x", "y", "z"])]
    else:
        offset = [0 for i, axis in enumerate(["x", "y", "z"])]

    ##### Create pores #####
    coordinates = vtk.vtkPoints()
    diameters = vtk.vtkFloatArray()
    diameters.SetName("diameters")
    pore_scalar = vtk.vtkFloatArray()
    pore_scalar.SetName("value")

    resolved_coordinates = vtk.vtkPoints()
    resolved_diameters = vtk.vtkFloatArray()
    resolved_diameters.SetName("diameters")
    resolved_pore_scalar = vtk.vtkFloatArray()
    resolved_pore_scalar.SetName("value")

    unresolved_coordinates = vtk.vtkPoints()
    unresolved_diameters = vtk.vtkFloatArray()
    unresolved_diameters.SetName("diameters")
    unresolved_pore_scalar = vtk.vtkFloatArray()
    unresolved_pore_scalar.SetName("value")

    default_pore_diameter = (
        min(
            (project.network["pore.coords"][:, 0].max() - project.network["pore.coords"][:, 0].min()),
            (project.network["pore.coords"][:, 1].max() - project.network["pore.coords"][:, 1].min()),
            (project.network["pore.coords"][:, 2].max() - project.network["pore.coords"][:, 2].min()),
        )
        / 20
    )
    for pore_index in range(len(project.network["pore.all"])):
        coordinates.InsertPoint(
            pore_index,
            project.network["pore.coords"][pore_index][0] * IJKTORAS[0] + offset[0],
            project.network["pore.coords"][pore_index][1] * IJKTORAS[1] + offset[1],
            project.network["pore.coords"][pore_index][2] * IJKTORAS[2] + offset[2],
        )
        pore_value = pore_values[pore_index]
        pore_scalar.InsertTuple1(pore_index, pore_value)
        if pore_diameters is None:
            diameters.InsertTuple1(pore_index, default_pore_diameter)
        else:
            diameters.InsertTuple1(pore_index, pore_diameters[pore_index])
        phase = (project.network["pore.subresolution_porosity"][pore_index] < 1) + 1
        if phase == 1:
            second_coordinates = resolved_coordinates
            second_diameters = resolved_diameters
            second_scalar = resolved_pore_scalar
        elif phase == 2:
            second_coordinates = unresolved_coordinates
            second_diameters = unresolved_diameters
            second_scalar = unresolved_pore_scalar
        second_coordinates.InsertPoint(
            pore_index,
            project.network["pore.coords"][pore_index][0] * IJKTORAS[0] + offset[0],
            project.network["pore.coords"][pore_index][1] * IJKTORAS[1] + offset[1],
            project.network["pore.coords"][pore_index][2] * IJKTORAS[2] + offset[2],
        )
        pore_value = pore_values[pore_index]
        second_scalar.InsertTuple1(pore_index, pore_value)
        if pore_diameters is None:
            second_diameters.InsertTuple1(pore_index, default_pore_diameter)
        else:
            second_diameters.InsertTuple1(pore_index, pore_diameters[pore_index])

    ### Setup VTK filters ###
    ### Resolved pores
    polydata = vtk.vtkPolyData()
    polydata.SetPoints(resolved_coordinates)
    polydata.GetPointData().AddArray(resolved_diameters)
    polydata.GetPointData().AddArray(resolved_pore_scalar)
    polydata.GetPointData().SetActiveScalars("diameters")

    sphereSource = vtk.vtkSphereSource()
    glyph3D = vtk.vtkGlyph3D()
    glyph3D.SetSourceConnection(sphereSource.GetOutputPort())
    glyph3D.SetInputData(polydata)
    glyph3D.SetScaleModeToScaleByScalar()
    glyph3D.Update()

    polydata.GetPointData().SetActiveScalars("value")

    resolved_model = glyph3D.GetOutput()

    ### Unresolved pores
    polydata = vtk.vtkPolyData()
    polydata.SetPoints(unresolved_coordinates)
    polydata.GetPointData().AddArray(unresolved_diameters)
    polydata.GetPointData().AddArray(unresolved_pore_scalar)
    polydata.GetPointData().SetActiveScalars("diameters")

    sphereSource = vtk.vtkSphereSource()
    glyph3D = vtk.vtkGlyph3D()
    glyph3D.SetSourceConnection(sphereSource.GetOutputPort())
    glyph3D.SetInputData(polydata)
    glyph3D.SetScaleModeToScaleByScalar()
    glyph3D.Update()

    polydata.GetPointData().SetActiveScalars("value")

    unresolved_model = glyph3D.GetOutput()

    ### All pores
    polydata = vtk.vtkPolyData()
    polydata.SetPoints(coordinates)
    polydata.GetPointData().AddArray(diameters)
    polydata.GetPointData().AddArray(pore_scalar)
    polydata.GetPointData().SetActiveScalars("diameters")

    sphereSource = vtk.vtkSphereSource()
    glyph3D = vtk.vtkGlyph3D()
    glyph3D.SetSourceConnection(sphereSource.GetOutputPort())
    glyph3D.SetInputData(polydata)
    glyph3D.SetScaleModeToScaleByScalar()
    glyph3D.Update()

    polydata.GetPointData().SetActiveScalars("value")

    pores_model = glyph3D.GetOutput()

    ### Read and extract throat properties from table node ###
    nodes_list = []
    links_list = []
    diameters_list = []
    values_list = []
    log_values_list = []
    diameter = default_pore_diameter / 12

    for throat_index in range(len(project.network["throat.all"])):

        left_pore_index = project.network["throat.conns"][throat_index][0]
        right_pore_index = project.network["throat.conns"][throat_index][1]
        if (left_pore_index < 0) or (right_pore_index < 0):
            continue

        nodes_list.append(
            (
                throat_index * 2,
                *[(a[0] * a[1] + a[2]) for a in zip(project.network["pore.coords"][left_pore_index], IJKTORAS, offset)],
            )
        )

        nodes_list.append(
            (
                throat_index * 2 + 1,
                *[
                    (a[0] * a[1] + a[2])
                    for a in zip(project.network["pore.coords"][right_pore_index], IJKTORAS, offset)
                ],
            )
        )

        if throat_diameters is None:
            diameters_list.append((throat_index * 2, diameter))
            diameters_list.append((throat_index * 2 + 1, diameter))
        else:
            diameters_list.append((throat_index * 2, throat_diameters[throat_index]))
            diameters_list.append((throat_index * 2 + 1, throat_diameters[throat_index]))

        values_list.append((throat_index * 2, throat_values[throat_index]))
        values_list.append((throat_index * 2 + 1, throat_values[throat_index]))
        log_values_list.append((throat_index * 2, np.log10(throat_values[throat_index])))
        log_values_list.append((throat_index * 2 + 1, np.log10(throat_values[throat_index])))
        links_list.append((throat_index * 2, throat_index * 2 + 1))

    ### Create VTK data types from lists ###
    coordinates = vtk.vtkPoints()
    for i, j, k, l in nodes_list:
        coordinates.InsertPoint(i, j, k, l)

    elements = vtk.vtkCellArray()
    for i, j in links_list:
        elementIdList = vtk.vtkIdList()
        _ = elementIdList.InsertNextId(i)
        _ = elementIdList.InsertNextId(j)
        _ = elements.InsertNextCell(elementIdList)

    radius_array = vtk.vtkFloatArray()
    radius_array.SetName("radius")
    for i, j in diameters_list:
        radius_array.InsertTuple1(i, j / throat_radius_reduction)
    value_array = vtk.vtkFloatArray()
    value_array.SetName("value array")
    for i, j in values_list:
        value_array.InsertTuple1(i, j)
    log_value_array = vtk.vtkFloatArray()
    log_value_array.SetName("log value array")
    for i, j in log_values_list:
        log_value_array.InsertTuple1(i, j)

    ### Setup VTK filters ###
    polydata = vtk.vtkPolyData()
    polydata.SetPoints(coordinates)
    polydata.SetLines(elements)
    polydata.GetPointData().AddArray(radius_array)
    polydata.GetPointData().AddArray(value_array)
    polydata.GetPointData().AddArray(log_value_array)
    polydata.GetPointData().SetActiveScalars("radius")

    tubes = vtk.vtkTubeFilter()
    tubes.SetInputData(polydata)
    tubes.SetNumberOfSides(6)
    # tubes.SetRadius(diameter)  # Actually this sets the minimum radius
    # tubes.SetVaryRadiusToVaryRadiusByScalar()
    tubes.SetVaryRadiusToVaryRadiusByAbsoluteScalar()
    tubes.Update()

    polydata.GetPointData().SetActiveScalars("log value array")

    throats_model = tubes.GetOutput()

    ### Create and configure MRML nodes ###
    # throats_model_node.SetPolyDataConnection(tubes.GetOutputPort())
    # throats_model_node.CreateDefaultDisplayNodes()
    # throats_display_node = throats_model_node.GetDisplayNode()
    # throats_display_node.SetScalarVisibility(True)

    return pores_model, throats_model, resolved_model, unresolved_model


def create_permeability_sphere(permeabilities, radius, verbose=False):

    area_per_marker = (4 * np.pi * radius**2) / len(permeabilities)
    marker_radius = np.sqrt(area_per_marker / (2 * np.pi))

    permeation_points = vtk.vtkPoints()
    permeation_color = vtk.vtkFloatArray()
    permeation_color.SetNumberOfComponents(1)
    permeation_color.SetName("Permeability")
    permeation_lengths = []
    max_length = 0
    min_length = np.inf

    center_of_mass = np.zeros(3)

    for _, _, _, length in permeabilities:
        if length > max_length:
            max_length = length
        if length < min_length:
            min_length = length

    for px, py, pz, length in permeabilities:
        center_of_mass[0] += px * length
        center_of_mass[1] += py * length
        center_of_mass[2] += pz * length
    center_of_mass /= len(permeabilities)

    relative_points = np.empty((len(permeabilities), 3))
    for i, vals in enumerate(permeabilities):
        relative_points[i, :] = vals[:-1]
        relative_points[i, :] *= vals[-1]
        relative_points[i, :] -= center_of_mass

    for px, py, pz, length in permeabilities:
        permeation_points.InsertNextPoint(px, py, pz)
        relative_length = (length - min_length) / (max_length - min_length)
        permeation_color.InsertNextTuple1(length)
        permeation_lengths.append(relative_length)

    permeation_lengths = np.array(permeation_lengths)

    polydata = vtk.vtkPolyData()
    polydata.SetPoints(permeation_points)
    polydata.GetPointData().AddArray(permeation_color)
    polydata.GetPointData().SetActiveScalars("Permeability")

    glyph_filter = vtk.vtkProgrammableGlyphFilter()
    glyph_filter.SetInputData(polydata)
    observer = GlyphCreator(glyph_filter, permeation_lengths, marker_radius)
    glyph_filter.SetGlyphMethod(observer)
    cone_source = vtk.vtkConeSource()  # A required, though unused, default glyph
    glyph_filter.SetSourceConnection(cone_source.GetOutputPort())
    glyph_filter.Update()

    multiangle_model = glyph_filter.GetOutput()
    multiangle_model_range = permeation_color.GetRange()[1]

    sphere = vtk.vtkSphereSource()
    sphere.SetRadius(radius)
    sphere.Update()

    multiangle_sphere_model = sphere.GetOutput()

    plane_distance = radius * 2
    plane = vtk.vtkPlaneSource()
    plane.SetPoint1(0, -plane_distance, plane_distance)
    plane.SetPoint2(0, plane_distance, -plane_distance)
    plane.SetOrigin(0, -plane_distance, -plane_distance)
    plane.Update()

    multiangle_plane_model = plane.GetOutput()

    inertia_tensor = np.zeros((3, 3))
    inertia_tensor[0, 0] = np.sum(relative_points[:, 1] ** 2 + relative_points[:, 2] ** 2)
    inertia_tensor[1, 1] = np.sum(relative_points[:, 0] ** 2 + relative_points[:, 2] ** 2)
    inertia_tensor[2, 2] = np.sum(relative_points[:, 0] ** 2 + relative_points[:, 1] ** 2)
    inertia_tensor[0, 1] = -np.sum(relative_points[:, 0] * relative_points[:, 1])
    inertia_tensor[1, 0] = -np.sum(relative_points[:, 0] * relative_points[:, 1])
    inertia_tensor[0, 2] = -np.sum(relative_points[:, 0] * relative_points[:, 2])
    inertia_tensor[2, 0] = -np.sum(relative_points[:, 0] * relative_points[:, 2])
    inertia_tensor[1, 2] = -np.sum(relative_points[:, 1] * relative_points[:, 2])
    inertia_tensor[2, 1] = -np.sum(relative_points[:, 1] * relative_points[:, 2])

    ei_val, ei_vec = np.linalg.eigh(inertia_tensor)
    direction = ei_vec[:, np.argmin(ei_val)]
    direction *= radius * 15
    if verbose:
        print(ei_val)
        print(ei_vec)
        print(inertia_tensor)

    arrow_center = vtk.vtkPoints()
    arrow_center.InsertNextPoint(0, 0, 0)
    arrows_direction = vtk.vtkFloatArray()
    arrows_direction.SetName("direction")
    arrows_direction.SetNumberOfComponents(3)
    arrows_direction.InsertNextTuple3(*direction)

    arrow_polydata = vtk.vtkPolyData()
    arrow_polydata.SetPoints(arrow_center)
    arrow_polydata.GetPointData().AddArray(arrows_direction)
    arrow_polydata.GetPointData().SetActiveVectors("direction")

    arrowSource = vtk.vtkArrowSource()
    arrowSource.SetTipResolution(8)
    arrowSource.SetShaftResolution(8)
    arrowSource.SetTipRadius(0.15)
    arrow_glyph3D = vtk.vtkGlyph3D()
    arrow_glyph3D.SetScaleFactor(radius * 3)
    arrow_glyph3D.SetSourceConnection(arrowSource.GetOutputPort())
    arrow_glyph3D.SetInputData(arrow_polydata)
    arrow_glyph3D.SetVectorModeToUseVector()
    arrow_glyph3D.Update()

    arrow_glyph3D_with_normals = vtk.vtkPolyDataNormals()
    arrow_glyph3D_with_normals.SetSplitting(False)
    arrow_glyph3D_with_normals.SetInputConnection(arrow_glyph3D.GetOutputPort())
    arrow_glyph3D_with_normals.Update()

    multiangle_arrow_model = arrow_glyph3D_with_normals.GetOutput()

    if verbose:
        rotated_points = np.transpose(np.linalg.inv(ei_vec) @ np.transpose(relative_points))
        inertia_tensor_2 = np.empty((3, 3))
        inertia_tensor_2[0, 0] = np.sum(rotated_points[:, 1] ** 2 + rotated_points[:, 2] ** 2)
        inertia_tensor_2[1, 1] = np.sum(rotated_points[:, 0] ** 2 + rotated_points[:, 2] ** 2)
        inertia_tensor_2[2, 2] = np.sum(rotated_points[:, 0] ** 2 + rotated_points[:, 1] ** 2)
        inertia_tensor_2[0, 1] = -np.sum(rotated_points[:, 0] * rotated_points[:, 1])
        inertia_tensor_2[1, 0] = -np.sum(rotated_points[:, 0] * rotated_points[:, 1])
        inertia_tensor_2[0, 2] = -np.sum(rotated_points[:, 0] * rotated_points[:, 2])
        inertia_tensor_2[2, 0] = -np.sum(rotated_points[:, 0] * rotated_points[:, 2])
        inertia_tensor_2[1, 2] = -np.sum(rotated_points[:, 1] * rotated_points[:, 2])
        inertia_tensor_2[2, 1] = -np.sum(rotated_points[:, 1] * rotated_points[:, 2])
        T_prime = inertia_tensor_2
        print(T_prime)

        v = ei_vec[:, np.argmin(ei_val)]
        fig = plt.figure()
        ax = fig.add_subplot(111, projection="3d")
        ax.plot([0, v[0]], [0, v[1]], [0, v[2]], c="b")
        ax.scatter(relative_points[:, 0], relative_points[:, 1], relative_points[:, 2], c="k", marker="o")
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_zlabel("Z")
        ax.set_xlim3d([-radius, radius])
        ax.set_ylim3d([-radius, radius])
        ax.set_zlim3d([-radius, radius])
        plt.show()

    return (
        multiangle_model,
        multiangle_model_range,
        multiangle_sphere_model,
        multiangle_plane_model,
        multiangle_arrow_model,
        list(direction),
    )
