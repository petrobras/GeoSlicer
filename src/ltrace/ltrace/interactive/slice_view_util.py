import slicer
import vtk
import numpy as np


class Slice:
    def __init__(self, name):
        self._name = name
        self._widget = slicer.app.layoutManager().sliceWidget(name)
        self._controller = self._widget.sliceController()
        self._logic = self._widget.sliceLogic()
        self._node = self._logic.GetSliceNode()
        self._composite = self._logic.GetSliceCompositeNode()

    @property
    def node(self):
        return self._node

    def set_bg(self, volume_node):
        self._composite.SetBackgroundVolumeID(volume_node.GetID())

    def set_label(self, label_node):
        self._composite.SetLabelVolumeID(label_node.GetID())
        self._composite.SetLabelOpacity(0.5)

    def fit(self):
        self._logic.FitSliceToAll()

    def fit_to_volume(self, volume):
        dims = self._node.GetDimensions()
        width = dims[0]
        height = dims[1]
        self._logic.FitSliceToVolume(volume, width, height)

    def link(self, value=True):
        self._composite.SetLinkedControl(value)
        self._composite.SetHotLinkedControl(value)


def get_volume_extents_in_slice_view(volume_node, slice_obj: Slice):
    slice_node = slice_obj.node
    xy_to_ras = slice_node.GetXYToRAS()
    ijk_to_ras = vtk.vtkMatrix4x4()
    volume_node.GetIJKToRASMatrix(ijk_to_ras)
    transform_node = volume_node.GetParentTransformNode()
    if transform_node:
        ras_to_world = vtk.vtkMatrix4x4()
        transform_node.GetMatrixTransformToWorld(ras_to_world)
        ijk_to_ras = vtk.vtkMatrix4x4.Multiply4x4(ras_to_world, ijk_to_ras, vtk.vtkMatrix4x4())

    ras_to_ijk = vtk.vtkMatrix4x4()
    vtk.vtkMatrix4x4.Invert(ijk_to_ras, ras_to_ijk)
    xy_to_ijk = vtk.vtkMatrix4x4()
    vtk.vtkMatrix4x4.Multiply4x4(ras_to_ijk, xy_to_ras, xy_to_ijk)

    dims = slice_node.GetDimensions()
    corners_xy = [
        [0, 0, 0, 1],
        [dims[0] - 1, 0, 0, 1],
        [0, dims[1] - 1, 0, 1],
        [dims[0] - 1, dims[1] - 1, 0, 1],
    ]
    corners_ijk = [xy_to_ijk.MultiplyPoint(c) for c in corners_xy]

    min_ijk = np.min(corners_ijk, axis=0)[:3]
    max_ijk = np.max(corners_ijk, axis=0)[:3]

    vol_ext = volume_node.GetImageData().GetExtent()

    k_slice_index = int(round((min_ijk[2] + max_ijk[2]) / 2))
    k_slice_index = max(vol_ext[4], k_slice_index)
    k_slice_index = min(vol_ext[5], k_slice_index)

    extent = [
        int(max(vol_ext[0], np.floor(min_ijk[0]))),
        int(min(vol_ext[1], np.ceil(max_ijk[0]))),
        int(max(vol_ext[2], np.floor(min_ijk[1]))),
        int(min(vol_ext[3], np.ceil(max_ijk[1]))),
        k_slice_index,
        k_slice_index,
    ]

    if extent[0] > extent[1] or extent[2] > extent[3]:
        return [0, 0, 0, 0, 0, 0]

    extent[1] += 1
    extent[3] += 1
    extent[5] += 1

    return extent
