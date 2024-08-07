import numpy as np

try:
    # Suppress "lzma compression not available" UserWarning when loading pandas
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter(action="ignore", category=UserWarning)
        import pandas as pd
except ImportError:
    raise ImportError(
        "Failed to convert to pandas dataframe. Please install pandas by running `slicer.util.pip_install('pandas')`"
    )

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


def tableNodeToDataFrame(tableNode):
    """Optimized version from slicer.util.dataframeFromTable

    Convert table node content to pandas dataframe.

    Table content is copied. Therefore, changes in table node do not affect the dataframe,
    and dataframe changes do not affect the original table node.
    """

    if tableNode is None:
        return pd.DataFrame()

    vtable = tableNode.GetTable()
    data = []
    columns = []
    for columnIndex in range(vtable.GetNumberOfColumns()):
        vcolumn = vtable.GetColumn(columnIndex)
        numberOfComponents = vcolumn.GetNumberOfComponents()
        column_name = vcolumn.GetName()
        columns.append(column_name)

        if numberOfComponents == 1:
            column_data = [vcolumn.GetValue(rowIndex) for rowIndex in range(vcolumn.GetNumberOfValues())]
        else:
            column_data = []
            for rowIndex in range(vcolumn.GetNumberOfTuples()):
                item = [vcolumn.GetValue(rowIndex, componentIndex) for componentIndex in range(numberOfComponents)]
                column_data.append(tuple(item))
        data.append(column_data)

    dataframe = pd.DataFrame(zip(*data), columns=columns)

    return dataframe
