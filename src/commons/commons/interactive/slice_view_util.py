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

    @property
    def orientation(self):
        return self._node.GetOrientation()

    def set_orientation(self, name):
        self._node.SetOrientation(name)

    @property
    def offset(self):
        return self._logic.GetSliceOffset()

    def set_offset(self, value):
        self._logic.SetSliceOffset(value)

    def snap_to_ijk(self):
        self._logic.SnapSliceOffsetToIJK()

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

    # The view collapses along whichever IJK axis is most aligned with the slice
    # normal (column 2 of XYToIJK), not necessarily K -- e.g. an XZ or YZ slice
    # collapses along J or I instead.
    normal_axis = int(np.argmax([abs(xy_to_ijk.GetElement(r, 2)) for r in range(3)]))

    slice_index = int(round((min_ijk[normal_axis] + max_ijk[normal_axis]) / 2))
    slice_index = max(vol_ext[2 * normal_axis], slice_index)
    slice_index = min(vol_ext[2 * normal_axis + 1], slice_index)

    extent = [0, 0, 0, 0, 0, 0]
    for axis in range(3):
        if axis == normal_axis:
            extent[2 * axis] = slice_index
            extent[2 * axis + 1] = slice_index
        else:
            extent[2 * axis] = int(max(vol_ext[2 * axis], np.floor(min_ijk[axis])))
            extent[2 * axis + 1] = int(min(vol_ext[2 * axis + 1], np.ceil(max_ijk[axis])))

    in_plane_axes = [axis for axis in range(3) if axis != normal_axis]
    if any(extent[2 * axis] > extent[2 * axis + 1] for axis in in_plane_axes):
        return [0, 0, 0, 0, 0, 0]

    extent[1] += 1
    extent[3] += 1
    extent[5] += 1

    return extent
