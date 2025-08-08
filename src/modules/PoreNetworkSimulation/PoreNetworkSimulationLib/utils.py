import slicer
import vtk
from ltrace.slicer.node_attributes import TableType


def save_parameters_to_table(parameters, parent_folder_id):
    parametersTableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
    parametersTableNode.SetName("Subscale parameters")
    parametersTableNode.SetAttribute(TableType.name(), TableType.PNM_SUBSCALE_PARAMETERS.value)

    paramColumn = vtk.vtkStringArray()
    paramColumn.SetName("Parameter")
    parametersTableNode.GetTable().AddColumn(paramColumn)

    valueColumn = vtk.vtkStringArray()
    valueColumn.SetName("Value")
    parametersTableNode.GetTable().AddColumn(valueColumn)

    for key, value in parameters.items():
        rowIndex = parametersTableNode.GetTable().InsertNextBlankRow()
        parametersTableNode.GetTable().SetValue(rowIndex, 0, key)
        parametersTableNode.GetTable().SetValue(rowIndex, 1, str(value))

    folderTree = slicer.mrmlScene.GetSubjectHierarchyNode()
    folderTree.CreateItem(parent_folder_id, parametersTableNode)
