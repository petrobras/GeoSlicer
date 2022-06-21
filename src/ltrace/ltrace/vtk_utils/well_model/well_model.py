import slicer
import vtk
import numpy as np
from ltrace.slicer import helpers


def create_well_model_from_node(node):
    previous_model = helpers.tryGetNode(f"{node.GetName()} - Well Model")

    if previous_model is not None and isinstance(previous_model, slicer.vtkMRMLModelNode):
        slicer.mrmlScene.RemoveNode(previous_model)

    array = slicer.util.arrayFromVolume(node)
    array_colors = np.flip(np.flip(array, 1), 0).flatten()
    bounds = [0, 0, 0, 0, 0, 0]
    node.GetBounds(bounds)

    spacing = node.GetSpacing()
    shape = array.shape

    height = array.shape[0]
    radius = shape[2] * spacing[0] / (np.pi * 2)
    num_faces = shape[2]

    coordinates = vtk.vtkPoints()
    colors = vtk.vtkFloatArray()
    colors.SetName("Values")

    index = 0
    for i in range(num_faces):
        angle = 2.0 * np.pi * i / num_faces
        x = radius * np.cos(angle)
        y = radius * np.sin(angle)
        for j in range(height):
            coordinates.InsertNextPoint(x, y, j * spacing[2] + bounds[4])
            colors.InsertTuple1(index, array_colors[index])
            index += 1

    cells = vtk.vtkCellArray()

    for row in range(height - 1):
        for col in range(num_faces):
            square = vtk.vtkQuad()
            square.GetPointIds().SetId(0, row + col * height)
            square.GetPointIds().SetId(1, row + col * height + 1)
            square.GetPointIds().SetId(2, (row + (col + 1) * height + 1) % (height * num_faces))
            square.GetPointIds().SetId(3, (row + (col + 1) * height) % (height * num_faces))
            cells.InsertNextCell(square)

    polydata = vtk.vtkPolyData()
    polydata.SetPoints(coordinates)
    polydata.SetPolys(cells)
    polydata.GetCellData().SetScalars(colors)

    well_model_node = slicer.mrmlScene.CreateNodeByClass("vtkMRMLModelNode")
    well_model_node.SetName(f"{node.GetName()} - Well Model")
    slicer.mrmlScene.AddNode(well_model_node)

    well_model_node.SetAndObservePolyData(polydata)
    well_model_node.CreateDefaultDisplayNodes()
    well_model_display = well_model_node.GetDisplayNode()
    well_model_node.SetDisplayVisibility(True)
    well_model_display.SetScalarVisibility(True)
    well_model_display.SetActiveScalarName("Values")
    well_model_display.SetAndObserveColorNodeID(node.GetDisplayNode().GetColorNodeID())

    if isinstance(node, slicer.vtkMRMLLabelMapVolumeNode):
        well_model_display.SetScalarRangeFlagFromString("UseColorNode")
