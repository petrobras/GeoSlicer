import sys

import numpy as np

import vtk
import slicer
import slicer.util
import mrml
import SimpleITK as sitk
from vtk.util import numpy_support

from ltrace.transforms import clip_to


def progressUpdate(value):
    """
    Progress Bar updates over stdout (Slicer handles the parsing)
    """
    print(f"<filter-progress>{value}</filter-progress>")
    sys.stdout.flush()


""" I/O need to communicate data on CLI to GeoSlicer
    This kind of code is abstracted inside ltrace library, here it is replicated
    to help explain what is going on and enable users to write CLIs independent
    of ltrace library
"""


def _readVectorFrom(volumeFile):
    sitkImage = sitk.ReadImage(volumeFile)
    spacing = sitkImage.GetSpacing()
    origin = sitkImage.GetOrigin()

    imageArray = sitk.GetArrayFromImage(sitkImage)

    vtkImage = vtk.vtkImageData()
    vtkArray = numpy_support.numpy_to_vtk(imageArray.ravel(), deep=True)
    vtkArray.SetNumberOfComponents(3)

    if imageArray.ndim == 3:
        imageArray = imageArray.reshape(1, *imageArray.shape)
    vtkImage.SetDimensions(imageArray.shape[-2::-1])
    vtkImage.GetPointData().SetScalars(vtkArray)

    vectorVolumeNode = mrml.vtkMRMLVectorVolumeNode()
    vectorVolumeNode.SetAndObserveImageData(vtkImage)

    RAS = np.identity(4)
    RAS[0, 0] = -1
    RAS[1, 1] = -1
    directionMatrix = vtk.vtkMatrix4x4()
    for i in range(3):
        for j in range(3):
            directionMatrix.SetElement(i, j, RAS[i, j] * sitkImage.GetDirection()[j + 3 * i])
    vectorVolumeNode.SetIJKToRASMatrix(directionMatrix)

    vectorVolumeNode.SetSpacing(spacing)
    vectorVolumeNode.SetOrigin((-origin[0], -origin[1], origin[2]))

    return vectorVolumeNode


def readFrom(volumeFile, builder, storageNode=slicer.vtkMRMLNRRDStorageNode):
    """Reads data from a GeoSlicer's VolumeNode to another Volume Node visible to this CLI
    use storageNode accordingly. ex. vtkMRMLNRRDStorageNode for volumes and
    vtkMRMLTableStorageNode for tables. Handles the fact that vtkMRMLNRRDStorageNode cannot
    read vtkMRMLVectorVolumeNode directly.
    """
    if builder == mrml.vtkMRMLVectorVolumeNode:
        return _readVectorFrom(volumeFile)

    sn = storageNode()
    sn.SetFileName(volumeFile)
    nodeIn = builder()
    sn.ReadData(nodeIn)  # read data from volumeFile into nodeIn
    return nodeIn


def writeDataInto(volumeFile, dataVoxelArray, builder, reference=None, spacing=None):
    """Writes data from CLI's Volume Node into GeoSlicer Volume Node"""
    sn_out = slicer.vtkMRMLNRRDStorageNode()
    sn_out.SetFileName(volumeFile)
    nodeOut = builder()

    if reference:
        # copy image information
        nodeOut.Copy(reference)
        volumeIJKToRASMatrix = vtk.vtkMatrix4x4()
        reference.GetIJKToRASMatrix(volumeIJKToRASMatrix)
        nodeOut.SetIJKToRASMatrix(volumeIJKToRASMatrix)
        nodeOut.SetOrigin(reference.GetOrigin())
        nodeOut.SetSpacing(spacing if spacing is not None else reference.GetSpacing())
        # reset the attribute dictionary, otherwise it will be transferred over
        attrs = vtk.vtkStringArray()
        nodeOut.GetAttributeNames(attrs)
        for i in range(0, attrs.GetNumberOfValues()):
            nodeOut.SetAttribute(attrs.GetValue(i), None)

    # reset the data array to force resizing, otherwise we will just keep the old data too
    nodeOut.SetAndObserveImageData(None)

    """ VTK can't handle int64 or uint64, so we need to convert to int32 """
    if dataVoxelArray.dtype == np.int64 or dataVoxelArray.dtype == np.uint64:
        dataVoxelArray = clip_to(dataVoxelArray, np.int32)

    slicer.util.updateVolumeFromArray(nodeOut, dataVoxelArray)

    nodeOut.Modified()

    sn_out.WriteData(nodeOut)


def writeToTable(df, tableID, na_rep=""):
    df.to_csv(tableID, sep="\t", header=True, index=False, na_rep=na_rep)
