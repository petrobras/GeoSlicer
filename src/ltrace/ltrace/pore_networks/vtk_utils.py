# fmt: off
import vtk
import os

import numpy as np
import slicer
import matplotlib.pyplot as plt

from .constants import *


def create_flow_model(project, pore_values, throat_values):

    ##### Create pores #####
    coordinates = vtk.vtkPoints()
    diameters = vtk.vtkFloatArray()
    diameter = project.network["pore.coords"].max() / 20
    for pore_index in range(len(project.network["pore.all"])):
        coordinates.InsertPoint(
            pore_index,
            project.network["pore.coords"][pore_index][0]*IJKTORAS[0],
            project.network["pore.coords"][pore_index][1]*IJKTORAS[1],
            project.network["pore.coords"][pore_index][2]*IJKTORAS[2],
        )
        pore_value = pore_values[pore_index]
        diameters.InsertTuple1(pore_index, pore_value)

    ### Setup VTK filters ###
    polydata = vtk.vtkPolyData()
    polydata.SetPoints(coordinates)
    polydata.GetPointData().SetScalars(diameters)

    sphereSource = vtk.vtkSphereSource()
    glyph3D = vtk.vtkGlyph3D()
    glyph3D.SetSourceConnection(sphereSource.GetOutputPort())
    glyph3D.SetInputData(polydata)
    glyph3D.SetScaleModeToDataScalingOff()
    glyph3D.SetScaleFactor(diameter)
    glyph3D.Update()

    ### Create and configure MRML nodes ###
    pores_model_node_name = slicer.mrmlScene.GenerateUniqueName("pore_permeability_model")
    pores_model_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", pores_model_node_name)

    pores_model_node.SetPolyDataConnection(glyph3D.GetOutputPort())
    pores_model_node.CreateDefaultDisplayNodes()
    pores_model_display = pores_model_node.GetDisplayNode()
    pores_model_node.SetDisplayVisibility(True)
    pores_model_display.SetScalarVisibility(True)

    ##### Create throats #####
    throats_model_node_name = slicer.mrmlScene.GenerateUniqueName("throat_permeability_model")
    throats_model_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", throats_model_node_name)

    ### Read and extract throat properties from table node ###
    nodes_list = []
    links_list = []
    diameters_list = []
    diameter /= 12

    for throat_index in range(len(project.network["throat.all"])):

        left_pore_index = project.network["throat.conns"][throat_index][0]
        right_pore_index = project.network["throat.conns"][throat_index][1]
        if (left_pore_index < 0) or (right_pore_index < 0):
            continue

        nodes_list.append((throat_index * 2, 
            *[(a[0]/a[1]) for a in zip(project.network["pore.coords"][left_pore_index], IJKTORAS)]))

        nodes_list.append((throat_index * 2 + 1,
            *[(a[0]/a[1]) for a in zip(project.network["pore.coords"][right_pore_index], IJKTORAS)]))

        diameters_list.append((throat_index * 2, throat_values[throat_index]))
        diameters_list.append((throat_index * 2 + 1, throat_values[throat_index]))
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

    radius = vtk.vtkFloatArray()
    for i, j in diameters_list:
        radius.InsertTuple1(i, j)

    ### Setup VTK filters ###
    polydata = vtk.vtkPolyData()
    polydata.SetPoints(coordinates)
    polydata.SetLines(elements)
    polydata.GetPointData().SetScalars(radius)

    tubes = vtk.vtkTubeFilter()
    tubes.SetInputData(polydata)
    tubes.SetNumberOfSides(6)
    tubes.SetRadius(diameter)  # Actually this sets the minimum radius
    tubes.Update()

    ### Create and configure MRML nodes ###
    throats_model_node.SetPolyDataConnection(tubes.GetOutputPort())
    throats_model_node.CreateDefaultDisplayNodes()
    throats_display_node = throats_model_node.GetDisplayNode()
    throats_display_node.SetScalarVisibility(True)

    return pores_model_node, throats_model_node


def _model_elements_from_grid(unstructured_grid, cycle, scale_factor=10**3, axis="x", size_reduction=True, **kwargs):

    n_points = unstructured_grid.GetNumberOfPoints()
    n_cells = unstructured_grid.GetNumberOfCells()

    pores = {}  # only points that are in the edges of quadratic edge cells on grid
    throats = {}  # only points that are in the center of quadratic edge cells on grid
    pore_mapper = {}
    arrows = []

    if size_reduction and (n_points > kwargs["max_pores"]):
        size_reduction_value = kwargs["max_pores"] / n_points
        linear_size_reduction = (1 - size_reduction_value**(1/2)) / 2
    else:
        linear_size_reduction = 10**-6

    bounds = unstructured_grid.GetPoints().GetBounds()
    x_min = bounds[4]
    x_max = bounds[5]
    x_length = x_max - x_min
    x_min += x_length * 10**-6
    x_max -= x_length * 10**-6

    z_min = bounds[0]
    z_max = bounds[1]
    z_length = z_max - z_min
    z_min += z_length * linear_size_reduction
    z_max -= z_length * linear_size_reduction

    y_min = bounds[2]
    y_max = bounds[3]
    y_length = y_max - y_min
    y_min += y_length * linear_size_reduction
    y_max -= y_length * linear_size_reduction

    for i in range(n_cells):
        left_pore_id = unstructured_grid.GetCell(i).GetPointIds().GetId(0)
        right_pore_id = unstructured_grid.GetCell(i).GetPointIds().GetId(1)
        throat_id = unstructured_grid.GetCell(i).GetPointIds().GetId(2)
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

        for pore_id in (left_pore_id, right_pore_id):
            new_id = len(pores)
            if pore_id not in pore_mapper.keys():
                position = unstructured_grid.GetPoint(pore_id)
                if axis == "x":
                    position = position[-1::-1]
                radius = unstructured_grid.GetPointData().GetArray("radius").GetComponent(pore_id, 0)
                sw = unstructured_grid.GetPointData().GetArray("Sw").GetComponent(pore_id, 0)
                pores[new_id] = {
                    "position": position,
                    "radius": radius,
                    "Sw": sw,
                }
                pore_mapper[pore_id] = new_id
                x_pos = position[2]
                if x_pos < x_min:
                    if cycle == "w":
                        sw = 1
                    else:  # cycle == 'o'
                        sw = 0
                    arrow_position = [i * scale_factor * 1 for i in position]
                    arrow_position[2] -= 0.200 + radius * scale_factor
                    arrows.append(
                        (arrow_position, sw),
                    )
                    pores[new_id]["Sw"] = sw
                elif x_pos > x_max:
                    if pore_id == left_pore_id:
                        sw = unstructured_grid.GetPointData().GetArray("Sw").GetComponent(right_pore_id, 0)
                        other_x = unstructured_grid.GetPoint(right_pore_id)[2]
                    else:
                        sw = unstructured_grid.GetPointData().GetArray("Sw").GetComponent(left_pore_id, 0)
                        other_x = unstructured_grid.GetPoint(left_pore_id)[2]
                    if other_x < x_max:
                        arrows.append(
                            ([i * scale_factor * 1 for i in position], sw),
                        )

        throats[i] = {
            "first_conn": pore_mapper[left_pore_id],
            "second_conn": pore_mapper[right_pore_id],
            "radius": unstructured_grid.GetCellData().GetArray("RRR").GetComponent(i, 0),
            "Sw": unstructured_grid.GetPointData().GetArray("Sw").GetComponent(throat_id, 0),
            "Sw_cell": unstructured_grid.GetCellData().GetArray("Sw").GetComponent(i, 0),
        }

    coordinates = vtk.vtkPoints()
    radii = vtk.vtkFloatArray()
    radii.SetName("radius")
    saturation = vtk.vtkFloatArray()
    saturation.SetName("saturation")

    for pore_index in pores.keys():
        pos_x, pos_y, pos_z = pores[pore_index]["position"]
        coordinates.InsertPoint(
            pore_index, pos_x * scale_factor, pos_y * scale_factor, pos_z * scale_factor
        )
        radii.InsertTuple1(pore_index, pores[pore_index]["radius"])
        saturation.InsertTuple1(pore_index, pores[pore_index]["Sw"])

    max_radius = 0
    min_radius = np.inf
    link_elements = vtk.vtkCellArray()
    tubes_coordinates = vtk.vtkPoints()
    tubes_radii = vtk.vtkFloatArray()
    tubes_radii.SetName("radius")
    tubes_saturation = vtk.vtkFloatArray()
    tubes_saturation.SetName("saturation")
    for i, throat in enumerate(throats.values()):
        first_conn = throat["first_conn"]
        second_conn = throat["second_conn"]
        throat_radius = throat["radius"]
        pos_x, pos_y, pos_z = pores[first_conn]["position"]
        tubes_coordinates.InsertPoint(
            i * 2, pos_x * scale_factor, pos_y * scale_factor, pos_z * scale_factor
        )
        tubes_radii.InsertTuple1(i * 2, throat_radius)
        tubes_saturation.InsertTuple1(i * 2, throat["Sw_cell"])
        pos_x, pos_y, pos_z = pores[second_conn]["position"]
        tubes_coordinates.InsertPoint(
            i * 2 + 1, pos_x * scale_factor, pos_y * scale_factor, pos_z * scale_factor
        )
        tubes_radii.InsertTuple1(i * 2 + 1, throat_radius)
        tubes_saturation.InsertTuple1(i * 2 + 1, throat["Sw_cell"])
        elementIdList = vtk.vtkIdList()
        _ = elementIdList.InsertNextId(i * 2)
        _ = elementIdList.InsertNextId(i * 2 + 1)
        _ = link_elements.InsertNextCell(elementIdList)
        if (throat_radius < min_radius) and (throat_radius > 0):
            min_radius = throat_radius
        if throat_radius > max_radius:
            max_radius = throat_radius

    return {
        "coordinates": coordinates,
        "link_elements": link_elements,
        "radii": radii,
        "saturation": saturation,
        "tubes_saturation": tubes_saturation,
        "tubes_radii": tubes_radii,
        "tubes_coordinates": tubes_coordinates,
        "max_radius": max_radius,
        "min_radius": min_radius,
        "arrows": arrows,
    }


class GlyphCreator():
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
            point_coords[0]*(1.41+length),
            point_coords[1]*(1.41+length),
            point_coords[2]*(1.41+length))
        tube = vtk.vtkTubeFilter()
        tube.SetNumberOfSides(6)
        tube.SetRadius(self.radius)
        tube.SetCapping(True)
        tube.SetInputConnection(source.GetOutputPort())
        self.glyph_filter.SetSourceConnection(tube.GetOutputPort())


def create_permeability_sphere(permeabilities, target_dir, radius, verbose=False):

    area_per_marker = (4 * np.pi * radius**2) / len(permeabilities)
    marker_radius = np.sqrt(area_per_marker / (2*np.pi))

    permeation_points = vtk.vtkPoints()
    permeation_color = vtk.vtkFloatArray()
    permeation_color.SetNumberOfComponents(1)
    permeation_color.SetName('Permeability')
    permeation_lengths = []
    max_length = 0
    min_length = np.inf

    center_of_mass = np.zeros(3)

    for _, _, _, length in permeabilities:
        if length > max_length: max_length = length
        if length < min_length: min_length = length

    for  px, py, pz, length in permeabilities:
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
    cone_source = vtk.vtkConeSource() # A required, though unused, default glyph
    glyph_filter.SetSourceConnection(cone_source.GetOutputPort())

    model_node_name = slicer.mrmlScene.GenerateUniqueName("multiangle_model")
    model_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", model_node_name)
    model_node.CreateDefaultDisplayNodes()
    model_display = model_node.GetDisplayNode()
    model_node.SetDisplayVisibility(True)
    model_display.SetScalarVisibility(1)
    model_display.SetScalarRange(0, permeation_color.GetRange()[1])
    model_display.SetAndObserveColorNodeID(slicer.util.getNode("Viridis").GetID())
    model_display.SetScalarRangeFlag(0)
    model_display.SetScalarRange(0, permeation_color.GetRange()[1])
    #model_display.SetColor(0.1, 0.1, 0.9)
    #model_display.SetAmbient(0.15)
    #model_display.SetDiffuse(0.85)
    model_node.SetPolyDataConnection(glyph_filter.GetOutputPort())

    sphere = vtk.vtkSphereSource()
    sphere.SetRadius(radius)

    sphere_node_name = slicer.mrmlScene.GenerateUniqueName("multiangle_sphere_model")
    sphere_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", sphere_node_name)
    sphere_node.CreateDefaultDisplayNodes()
    sphere_node.SetPolyDataConnection(sphere.GetOutputPort())
    sphere_node.SetDisplayVisibility(True)
    sphere_display = sphere_node.GetDisplayNode()
    sphere_display.SetColor(0.63, 0.63, 0.63)
    
    plane_distance = radius*2
    plane = vtk.vtkPlaneSource()
    plane.SetPoint1(0, -plane_distance, plane_distance)
    plane.SetPoint2(0, plane_distance, -plane_distance)
    plane.SetOrigin(0, -plane_distance, -plane_distance)

    plane_node_name = slicer.mrmlScene.GenerateUniqueName("multiangle_plane_model")
    plane_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", plane_node_name)
    plane_node.CreateDefaultDisplayNodes()
    plane_node.SetPolyDataConnection(plane.GetOutputPort())
    plane_node.SetDisplayVisibility(True)
    plane_display = plane_node.GetDisplayNode()
    plane_display.SetOpacity(0.3)

    inertia_tensor = np.zeros((3,3))
    inertia_tensor[0, 0] = np.sum(relative_points[:, 1]**2 + relative_points[:, 2]**2)
    inertia_tensor[1, 1] = np.sum(relative_points[:, 0]**2 + relative_points[:, 2]**2)
    inertia_tensor[2, 2] = np.sum(relative_points[:, 0]**2 + relative_points[:, 1]**2)
    inertia_tensor[0, 1] = -np.sum(relative_points[:, 0] * relative_points[:, 1])
    inertia_tensor[1, 0] = -np.sum(relative_points[:, 0] * relative_points[:, 1])
    inertia_tensor[0, 2] = -np.sum(relative_points[:, 0] * relative_points[:, 2])
    inertia_tensor[2, 0] = -np.sum(relative_points[:, 0] * relative_points[:, 2])
    inertia_tensor[1, 2] = -np.sum(relative_points[:, 1] * relative_points[:, 2])
    inertia_tensor[2, 1] = -np.sum(relative_points[:, 1] * relative_points[:, 2])

    ei_val, ei_vec = np.linalg.eigh(inertia_tensor)
    direction = ei_vec[:, np.argmin(ei_val)]
    direction *= radius*15
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
    arrow_glyph3D.SetScaleFactor(radius*3)
    arrow_glyph3D.SetSourceConnection(arrowSource.GetOutputPort())
    arrow_glyph3D.SetInputData(arrow_polydata)
    arrow_glyph3D.SetVectorModeToUseVector()
    arrow_glyph3D.Update()

    arrow_glyph3D_with_normals = vtk.vtkPolyDataNormals()
    arrow_glyph3D_with_normals.SetSplitting(False)
    arrow_glyph3D_with_normals.SetInputConnection(arrow_glyph3D.GetOutputPort())
    arrow_glyph3D_with_normals.Update()

    arrow_node_name = slicer.mrmlScene.GenerateUniqueName("multiangle_arrow_model")
    arrow_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", arrow_node_name)
    arrow_node.CreateDefaultDisplayNodes()
    arrow_node.SetPolyDataConnection(arrow_glyph3D_with_normals.GetOutputPort())
    arrow_node.SetDisplayVisibility(True)
    arrow_display = arrow_node.GetDisplayNode()
    arrow_display.SetColor(0, 0, 1)
    arrow_display.SetAmbient(0.15)
    arrow_display.SetDiffuse(0.85)

    folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    _ = folderTree.CreateItem(target_dir, model_node)
    _ = folderTree.CreateItem(target_dir, sphere_node)
    _ = folderTree.CreateItem(target_dir, plane_node)
    _ = folderTree.CreateItem(target_dir, arrow_node)

    if verbose:
        rotated_points = np.transpose(np.linalg.inv(ei_vec)@np.transpose(relative_points))
        inertia_tensor_2 = np.empty((3,3))
        inertia_tensor_2[0, 0] = np.sum(rotated_points[:, 1]**2 + rotated_points[:, 2]**2)
        inertia_tensor_2[1, 1] = np.sum(rotated_points[:, 0]**2 + rotated_points[:, 2]**2)
        inertia_tensor_2[2, 2] = np.sum(rotated_points[:, 0]**2 + rotated_points[:, 1]**2)
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
        ax = fig.add_subplot(111, projection='3d')
        ax.plot([0, v[0]], [0, v[1]], [0, v[2]], c='b')
        ax.scatter(relative_points[:,0], relative_points[:,1], relative_points[:,2], c='k', marker='o')
        ax.set_xlabel('X')
        ax.set_ylabel('Y')
        ax.set_zlabel('Z')
        ax.set_xlim3d([-radius, radius])
        ax.set_ylim3d([-radius, radius])
        ax.set_zlim3d([-radius, radius])
        plt.show()
