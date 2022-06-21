import os
import json
import logging
from pathlib import Path

import markdown2 as markdown
import numpy as np
import qt
import slicer
import vtk
from slicer import ScriptedLoadableModule
from SegmentEditorEffects import *

from ltrace.slicer.application_observables import ApplicationObservables
from ltrace.slicer.tests.ltrace_plugin_test import LTracePluginTest
from ltrace.slicer.tests.ltrace_tests_widget import LTraceTestsWidget
from typing import Union, Callable

__all__ = [
    "LTracePlugin",
    "LTracePluginWidget",
    "LTracePluginLogic",
    "LTracePluginTest",
    "slicer_is_in_developer_mode",
    "dataFrameToTableNode",
    "print_debug",
]


class LTraceSegmentEditorEffectMixin:
    def SetSourceVolumeIntensityMaskOff(self):
        """Override for AbstractScriptedSegmentEditorEffect activate method."""
        try:
            parameterSetNode = self.scriptedEffect.parameterSetNode()
            parameterSetNode.SourceVolumeIntensityMaskOff()
        except Exception as e:
            pass


class LTracePlugin(ScriptedLoadableModule.ScriptedLoadableModule):
    SETTING_KEY = None

    HOME_DIR = os.path.join(str(Path.home()), ".ltrace")

    def __init__(self, *args, **kwargs):
        ScriptedLoadableModule.ScriptedLoadableModule.__init__(self, *args, **kwargs)
        if self.SETTING_KEY is None:
            raise NotImplementedError

    @classmethod
    def help(cls):
        htmlHelp = ""
        with open(cls.readme_path(), "r", encoding="utf-8") as docfile:
            docs = docfile.read().replace("$README_DIR", str(Path(cls.readme_path()).parent.absolute()))
            md = markdown.Markdown(extras=["fenced-code-blocks"])
            htmlHelp = md.convert(docs)
            htmlHelp = htmlHelp.replace("{base_version}", base_version())
        return htmlHelp

    @classmethod
    def readme_path(cls):
        return "README.md"

    def runTest(self, useGui=True, msec=100, **kwargs):
        """Override for ScriptedLoadableModule.ScriptedLoadableModule runTest method.
           Adds option to open the Test GUI.

        Args:
            msec: delay to associate with :func:`ScriptedLoadableModuleTest.delayDisplay()`.
        """
        if useGui:
            tests_widget = LTraceTestsWidget(parent=slicer.util.mainWindow(), current_module=self.__class__.__name__)
            tests_widget.exec()
            return

        super().runTest(msec, **kwargs)

    @classmethod
    def get_setting(cls, key, default=None):
        return slicer.app.settings().value(f"{cls.SETTING_KEY}/{key}", default)

    @classmethod
    def set_setting(cls, key, value):
        slicer.app.settings().setValue(f"{cls.SETTING_KEY}/{key}", value)


class LTracePluginWidget(ScriptedLoadableModule.ScriptedLoadableModuleWidget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def isReloading(self) -> bool:
        return slicer.reloadingWidget.get(self.moduleName, False) if hasattr(slicer, "reloadingWidget") else False

    def onReload(self) -> None:
        slicer.reloadingWidget[self.moduleName] = True
        ScriptedLoadableModule.ScriptedLoadableModuleWidget.onReload(self)
        slicer.reloadingWidget[self.moduleName] = False

    def enter(self) -> None:
        ApplicationObservables().moduleWidgetEnter.emit(self)


class LTracePluginLogicMeta(type(qt.QObject), type(ScriptedLoadableModule.ScriptedLoadableModuleLogic)):
    pass


class LTracePluginLogic(
    qt.QObject,
    ScriptedLoadableModule.ScriptedLoadableModuleLogic,
    metaclass=LTracePluginLogicMeta,
):
    def __init__(self, parent=None):
        super(qt.QObject, self).__init__()
        super(ScriptedLoadableModule.ScriptedLoadableModuleLogic, self).__init__()


def slicer_is_in_developer_mode():
    return slicer.util.settingsValue("Developer/DeveloperMode", False, converter=slicer.util.toBool)


def is_tensorflow_gpu_enabled():
    return slicer.util.settingsValue("TensorFlow/GPUEnabled", True, converter=slicer.util.toBool)


def dataFrameToTableNode(dataFrame, tableNode=None):
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


def tableNodeToDict(tableNode):
    """
    Returns a dictionary of 1D numpy arrays
    Dictionary is accessed as dict[column][row]
    """

    dataTypes = {}
    columnNames = {}
    n_rows = tableNode.GetNumberOfRows()
    outputDict = {}

    for i in range(tableNode.GetNumberOfColumns()):
        column_name = tableNode.GetColumnName(i)
        columnNames[i] = column_name
        dataType = tableNode.GetValueTypeAsString(tableNode.GetColumnType(column_name))
        if dataType == "bit":
            dataType = "bool"
        elif dataType == "string":
            dataType = "str"
        dataTypes[column_name] = dataType

    for column_name, column_type in dataTypes.items():
        outputDict[column_name] = np.empty((n_rows,), dtype=column_type)

    intColumns = [i for i in columnNames.values() if dataTypes[i] == "int"]
    floatColumns = [i for i in columnNames.values() if dataTypes[i] == "float"]
    doubleColumns = [i for i in columnNames.values() if dataTypes[i] == "double"]
    boolColumns = [i for i in columnNames.values() if dataTypes[i] == "bool"]
    vtkTable = tableNode.GetTable()

    for row in range(tableNode.GetNumberOfRows()):
        for col in intColumns:
            outputDict[col][row] = vtkTable.GetValueByName(row, col).ToInt()
        for col in floatColumns:
            outputDict[col][row] = vtkTable.GetValueByName(row, col).ToFloat()
        for col in doubleColumns:
            outputDict[col][row] = vtkTable.GetValueByName(row, col).ToDouble()
        for col in boolColumns:
            outputDict[col][row] = vtkTable.GetValueByName(row, col).ToInt()

    return outputDict


def restartSlicerIn2s():
    text = "Slicer has been successfully configured and must be restarted."
    mb = qt.QMessageBox(slicer.util.mainWindow())
    mb.text = text
    mb.setWindowTitle("Configuration finished")
    qt.QTimer.singleShot(2000, lambda: killSlicer(mb))
    mb.show()


def killSlicer(messagebox=None):
    if messagebox is not None:
        messagebox.close()
        messagebox.delete()
    slicer.app.restart()


def get_json_data():
    folders = [
        *(os.path.dirname(slicer.app.launcherExecutableFilePath).split("/")),
        *(f"lib\\{base_version()}\\qt-scripted-modules\\Resources\\json\\WelcomeGeoSlicer.json".split("\\")),
    ]
    JSON_PATH = os.path.join(folders[0], os.sep, *folders[1:])
    with open(JSON_PATH, "r") as json_file:
        JSON_DATA = json.load(json_file)

    return JSON_DATA


def addNodeToSubjectHierarchy(node, dirPaths: list = None):
    """Add node to the subject hierarchy list regarding the folder hierarchy specified at 'dirPaths' argument.
       ex: dirPaths = ["folder_a", "folder_b"] means that node will be displayed inside folder hierarchy: folder_a > folder_b > node.
           dirPaths = None or [] means node will be displayed at the subject hierarcy's root folder.

    Args:
        node (vtkMRMLNode): the node object.
        dirPaths (list, optional): The folders name hierarchy list. Defaults to None.
    """
    subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    parentDirID = subjectHierarchyNode.GetSceneItemID()
    if dirPaths is not None and len(dirPaths) > 0:
        for dirName in dirPaths:
            dirID = subjectHierarchyNode.GetItemChildWithName(parentDirID, dirName)

            if dirID == 0:
                dirID = subjectHierarchyNode.CreateFolderItem(parentDirID, dirName)

            parentDirID = dirID

    subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(node), parentDirID)


def print_debug(text, channel: Callable = logging.debug):
    if not slicer_is_in_developer_mode():
        return

    channel(text)


def print_stack():
    if not slicer_is_in_developer_mode():
        return

    import traceback

    text = traceback.format_exc()
    logging.debug(text)


def base_version():
    return f"{slicer.app.mainApplicationName}-{slicer.app.majorVersion}.{slicer.app.minorVersion}"


def singleton(class_):
    """Singleton decorator. Allow a class to behave like a singleton. QObject compatible."""
    instances = {}

    def getinstance(*args, **kwargs):
        if class_ not in instances:
            instances[class_] = class_(*args, **kwargs)
        return instances[class_]

    return getinstance


def hide_nodes_of_type(mrml_node_type):
    n_nodes = slicer.mrmlScene.GetNumberOfNodesByClass(mrml_node_type)
    for i in range(n_nodes):
        node = slicer.mrmlScene.GetNthNodeByClass(i, mrml_node_type)
        node.SetDisplayVisibility(False)


def dataframeFromTable(tableNode):
    """Optimized version from slicer.util.dataframeFromTable

    Convert table node content to pandas dataframe.

    Table content is copied. Therefore, changes in table node do not affect the dataframe,
    and dataframe changes do not affect the original table node.
    """
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


def imageToHtml(image: Union[qt.QImage, qt.QPixmap], imageFormat=None, quality=-1) -> str:
    """Bufferize a Qt Image object to an html string.

    Args:
        image (Union[qt.QImage, qt.QPixmap]): The Qt image object.
        imageFormat (_type_, optional): The format to export the image (png, jpg, etc...). Defaults to a format Qt will attempt to identify by the image's filepath suffix.
        quality (int, optional): Specify 0 to obtain small compressed files, 100 for large uncompressed files, and -1 (the default) to use the default settings.

    Raises:
        TypeError: When unable to buffer the related file.

    Returns:
        str: the buffered image as html.
    """
    byteArray = qt.QByteArray()
    buffer = qt.QBuffer(byteArray)
    buffer.open(qt.QIODevice.WriteOnly)
    image.save(buffer, imageFormat, quality)
    try:
        bufferedImage = byteArray.toBase64().data().decode("utf-8")
    except TypeError as e:
        raise e

    buffer.close()
    html = f'<img src="data:image/png;base64,{bufferedImage}"/>'
    return html


def loadImage(
    imagePath: Union[str, Path],
    cls: Union[qt.QImage, qt.QPixmap],
    size: qt.QSize = None,
    aspectRatio: qt.Qt.AspectRatioMode = qt.Qt.KeepAspectRatio,
):
    """Load an image file as a Qt object.

    Args:
        imagePath (Union[str, Path]): the image's file path.
        cls (Union[qt.QImage, qt.QPixmap]): the desired Qt class output.
        size (qt.QSize, optional): The size to scale the image. Defaults to maintain the original size.
        aspectRatio (qt.Qt.AspectRatioMode, optional): The aspect ratio based on the rescale size. Defaults to qt.Qt.KeepAspectRatio.

    Returns:
        qt.QImage or qt.QPixmap: the Qt object file.
    """
    if isinstance(imagePath, str):
        imagePath = Path(imagePath)

    imageReader = qt.QImageReader(imagePath.as_posix())

    if size:
        originalSize = imageReader.size()
        scaledSize = originalSize.scaled(size, aspectRatio)
        imageReader.setScaledSize(scaledSize)

    obj = imageReader.read() if cls == qt.QImage else qt.QPixmap.fromImageReader(imageReader)
    return obj
