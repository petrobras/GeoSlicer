"""3D Slicer / GeoSlicer integration for fast_reg.

Usage (Slicer Python console):
    transform_node, ras_matrix = register_volume_nodes(getNode("dry"), getNode("sat"))
"""

import numpy as np
import slicer
import vtk

from ltrace.algorithms.fast_registration import fast_reg


def _ijk_to_ras(node):
    matrix = vtk.vtkMatrix4x4()
    node.GetIJKToRASMatrix(matrix)
    return np.array([[matrix.GetElement(i, j) for j in range(4)] for i in range(4)])


def _as_vtk_matrix(array_4x4):
    matrix = vtk.vtkMatrix4x4()
    for i in range(4):
        for j in range(4):
            matrix.SetElement(i, j, float(array_4x4[i, j]))
    return matrix


def build_transform_node(fixed_node, moving_node, index_matrix, transform_name=None):
    """Turn an index-space rigid transform into an attached RAS transform node.

    `index_matrix` is the 4x4 transform K mapping moving index coordinates onto fixed index
    coordinates (i.e. what `fast_reg.register` returns). Creates a vtkMRMLLinearTransformNode
    holding the corresponding RAS transform (moving RAS -> fixed RAS), sets it as the transform
    observed by moving_node (not hardened), and returns `(transform_node, ras_matrix)`.

    Split out from `register_volume_nodes` so a caller that already has the index-space matrix --
    the module UI, which gets it from FastRegistrationLogic -- can build the transform with the
    same math.
    """
    index_matrix = np.asarray(index_matrix)
    # index-space rigid transform -> RAS transform (moving RAS -> fixed RAS)
    t_ras = _ijk_to_ras(fixed_node) @ index_matrix @ np.linalg.inv(_ijk_to_ras(moving_node))

    name = transform_name or f"{moving_node.GetName()} to {fixed_node.GetName()} - Registration transform"
    transform_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", name)
    transform_node.SetMatrixTransformToParent(_as_vtk_matrix(t_ras))
    moving_node.SetAndObserveTransformNodeID(transform_node.GetID())
    return transform_node, t_ras


def register_volume_nodes(fixed_node, moving_node, transform_name=None, progress_callback=None):
    """Register moving_node onto fixed_node, in-process (console / test convenience).

    Runs the algorithm on the calling thread and returns `(transform_node, ras_matrix)`. The module
    UI does the same work in two steps so it can report progress and failures separately (see
    FastRegistrationLogic); this path stays for the Python console and tests.

    `progress_callback` is forwarded to `fast_reg.register` (see its docstring).

    Raises ValueError if the volumes' voxel spacing differs, or fast_reg.RegistrationFailed if no
    reliable registration is found (see its `.diagnostics` for details).
    """
    if not np.allclose(fixed_node.GetSpacing(), moving_node.GetSpacing(), rtol=1e-3):
        raise ValueError("fixed and moving volumes must have the same voxel spacing")

    fixed_arr = slicer.util.arrayFromVolume(fixed_node)
    moving_arr = slicer.util.arrayFromVolume(moving_node)
    index_matrix = fast_reg.register(fixed_arr, moving_arr, progress_callback=progress_callback)

    return build_transform_node(fixed_node, moving_node, index_matrix, transform_name)
