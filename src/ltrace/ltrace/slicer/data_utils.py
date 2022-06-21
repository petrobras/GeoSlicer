import numpy as np
import pandas as pd

import vtk, slicer


def dataFrameToTableNode(dataFrame: pd.DataFrame, tableNode=None):
    def is_float(value):
        return value.dtype in [np.dtype("float32")]

    def is_double(value):
        return value.dtype in [np.dtype("float64")]

    def is_int(value):
        return value.dtype in [
            np.dtype("int64"),
            np.dtype("int32"),
            np.dtype("uint16"),
            np.dtype("uint8"),
        ]

    def is_bool(value):
        return value.dtype in [np.dtype("bool")]

    if tableNode is None:
        tableNode = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTableNode.__name__)
    tableWasModified = tableNode.StartModify()
    for ind, column in enumerate(dataFrame.columns):
        serie = dataFrame[column]
        if is_float(serie):
            arrX = vtk.vtkFloatArray()
        elif is_double(serie):
            arrX = vtk.vtkDoubleArray()
        elif is_int(serie):
            arrX = vtk.vtkIntArray()
        elif is_bool(serie):
            arrX = vtk.vtkBitArray()
        else:
            arrX = vtk.vtkStringArray()
        for value in serie:
            try:
                arrX.InsertNextValue(value)
            except TypeError:
                arrX.InsertNextValue(str(value))
        arrX.SetName(str(column) if column is not None else "--")
        tableNode.AddColumn(arrX)
    tableNode.Modified()
    tableNode.EndModify(tableWasModified)
    return tableNode
