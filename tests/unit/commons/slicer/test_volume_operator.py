"""Segment centroids, as the Segment Inspector CLI adds them to its report."""

import numpy as np
import pytest
from scipy import ndimage
from scipy.spatial.transform import Rotation

from commons.algorithms.measurements import (
    CENTROID_COLUMNS,
    LabelStatistics2D,
    LabelStatistics3D,
    calculate_statistics_on_segments,
    is_spatial_column,
)
from commons.slicer import volume_operator
from commons.slicer.volume_operator import SegmentOperator, VolumeOperator


class FakeMatrix:
    def __init__(self):
        self.elements = None

    @staticmethod
    def DeepCopy(output, source):
        output[:] = source.elements.ravel()


class FakeVolumeNode:
    def __init__(self, ijk_to_ras):
        self.ijk_to_ras = ijk_to_ras

    def GetIJKToRASMatrix(self, matrix):
        matrix.elements = self.ijk_to_ras


def ijk_to_ras_matrix(spacing, rotation_degrees, origin):
    """IJK to RAS matrix with the given (i, j, k) spacing, rotation (xyz Euler angles) and origin."""
    matrix = np.eye(4)
    matrix[:3, :3] = Rotation.from_euler("xyz", rotation_degrees, degrees=True).as_matrix() @ np.diag(spacing)
    matrix[:3, 3] = origin
    return matrix


def make_volume_operator(monkeypatch, array, ijk_to_ras):
    monkeypatch.setattr(volume_operator.slicer.util, "arrayFromVolume", lambda node: array)
    monkeypatch.setattr(volume_operator.vtk, "vtkMatrix4x4", FakeMatrix)
    return VolumeOperator(FakeVolumeNode(ijk_to_ras), dtype=array.dtype)


def expected_centroids(array, labels, ijk_to_ras):
    """(S, A, R) centroid of each label: mean voxel index, mapped by the full IJK to RAS matrix."""
    kji = np.array(ndimage.center_of_mass(np.ones_like(array), labels=array, index=labels))
    ijk = np.c_[kji[:, ::-1], np.ones(len(kji))]
    ras = (ijk_to_ras @ ijk.T).T[:, :3]
    return ras[:, ::-1]


def run_statistics(regions, operator, centroid_matrix):
    df, _ = calculate_statistics_on_segments(
        regions,
        SegmentOperator(operator, centroid_matrix[0], centroidMatrix=centroid_matrix[1]),
        callback=lambda i, total: None,
    )
    columns = operator.ATTRIBUTES + CENTROID_COLUMNS if centroid_matrix[1] is not None else operator.ATTRIBUTES
    return df.set_axis(columns, axis=1).sort_values("label")


def blobs_3d():
    """A ball, an anisotropic ellipsoid and a ring (whose centroid is outside it)."""
    k, j, i = np.mgrid[0:40, 0:50, 0:60]
    array = np.zeros((40, 50, 60), dtype=np.uint8)
    array[(k - 10) ** 2 + (j - 12) ** 2 + (i - 14) ** 2 <= 36] = 1
    array[((k - 25) / 8) ** 2 + ((j - 15) / 5) ** 2 + ((i - 40) / 12) ** 2 <= 1] = 2
    radius = np.sqrt((j - 36) ** 2 + (i - 30) ** 2)
    array[(np.abs(k - 20) <= 3) & (radius >= 6) & (radius <= 10)] = 3
    return array


@pytest.mark.parametrize("rotation", [(0, 0, 0), (20, -35, 50)])
def test_3d_centroids_are_the_world_mean_of_the_segment_voxels(monkeypatch, rotation):
    array = blobs_3d()
    ijk_to_ras = ijk_to_ras_matrix(spacing=(0.5, 0.8, 1.3), rotation_degrees=rotation, origin=(-12.0, 30.5, 7.25))
    operator = make_volume_operator(monkeypatch, array, ijk_to_ras)
    statistics = LabelStatistics3D(array, spacing=(1.3, 0.8, 0.5), is_pore=True)

    df = run_statistics(array, statistics, (operator.ijkToRasOperator, operator.ijkToZyxOperator))

    assert list(df["label"]) == [1, 2, 3]
    np.testing.assert_allclose(df[list(CENTROID_COLUMNS)].to_numpy(), expected_centroids(array, [1, 2, 3], ijk_to_ras))


@pytest.mark.parametrize(
    "shape, rotation",
    [
        ((1, 50, 60), (0, 0, 0)),  # axial slice
        ((1, 50, 60), (0, 0, 30)),  # rotated in its plane
        ((50, 1, 60), (0, 0, 0)),  # coronal slice: rows run along S, the slice position is along A
    ],
)
def test_2d_centroids_include_the_slice_position(monkeypatch, shape, rotation):
    rows, columns = np.mgrid[0:50, 0:60]
    image = np.zeros((50, 60), dtype=np.uint8)
    image[(rows - 15) ** 2 + (columns - 20) ** 2 <= 49] = 1
    image[((rows - 35) / 6) ** 2 + ((columns - 42) / 11) ** 2 <= 1] = 2
    array = image.reshape(shape)

    ijk_to_ras = ijk_to_ras_matrix(spacing=(0.25, 0.4, 2.0), rotation_degrees=rotation, origin=(3.0, -8.0, 41.5))
    operator = make_volume_operator(monkeypatch, array, ijk_to_ras)
    statistics = LabelStatistics2D(image, spacing=(0.4, 0.25), direction=None, is_pore=True)

    df = run_statistics(image, statistics, (operator.ijkToRasOperator, operator.ijkToZyxOperator))

    assert list(df["label"]) == [1, 2]
    np.testing.assert_allclose(df[list(CENTROID_COLUMNS)].to_numpy(), expected_centroids(array, [1, 2], ijk_to_ras))


def test_without_centroid_matrix_the_statistics_are_unchanged(monkeypatch):
    array = blobs_3d()
    ijk_to_ras = ijk_to_ras_matrix(spacing=(0.5, 0.8, 1.3), rotation_degrees=(0, 0, 0), origin=(0, 0, 0))
    operator = make_volume_operator(monkeypatch, array, ijk_to_ras)
    statistics = LabelStatistics3D(array, spacing=(1.3, 0.8, 0.5), is_pore=True)

    with_centroids = run_statistics(array, statistics, (operator.ijkToRasOperator, operator.ijkToZyxOperator))
    without_centroids = run_statistics(array, statistics, (operator.ijkToRasOperator, None))

    assert list(without_centroids.columns) == list(LabelStatistics3D.ATTRIBUTES)
    columns = list(LabelStatistics3D.ATTRIBUTES)
    np.testing.assert_allclose(
        without_centroids[columns].to_numpy(dtype=float), with_centroids[columns].to_numpy(dtype=float)
    )


def test_segment_operator_skips_the_centroid_of_rejected_segments():
    operator = SegmentOperator(lambda label, points: None, np.eye(4), centroidMatrix=np.eye(3, 4))
    assert operator(1, [(0, 0, 0), (1, 1, 1)]) is None


@pytest.mark.parametrize(
    "name, expected",
    [
        ("centroid_z", True),
        ("centroid_x (mm)", True),
        ("max_feret (mm)", False),
        ("label", False),
    ],
)
def test_centroid_columns_are_recognized_with_or_without_units(name, expected):
    assert is_spatial_column(name) == expected
