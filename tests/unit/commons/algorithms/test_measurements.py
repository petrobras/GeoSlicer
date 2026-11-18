import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from commons.algorithms.measurements import (
    AXIS_LENGTH_COLUMNS,
    ORIENTATION_COLUMNS,
    PRINCIPAL_AXES,
    LabelStatistics2D,
    LabelStatistics3D,
    orient_axes,
)


@pytest.fixture
def sample_3d_image():
    """Create a 3D image with a central label surrounded by 4 other labels."""
    image = np.zeros((10, 10, 10), dtype=np.uint8)
    image[4:7, 4:7, 4:7] = 1  # Central label
    image[4:7, 7:9, 4:7] = 2  # Neighbor 1
    image[4:7, 2:4, 4:7] = 3  # Neighbor 2
    image[7:9, 4:7, 4:7] = 4  # Neighbor 3
    image[2:4, 4:7, 4:7] = 5  # Neighbor 4
    return image


@pytest.fixture
def sample_2d_image():
    """Create a 2D image with a central label surrounded by 4 other labels."""
    image = np.zeros((10, 10), dtype=np.uint8)
    image[4:7, 4:7] = 1  # Central label
    image[4:7, 7:9] = 2  # Neighbor 1
    image[4:7, 2:4] = 3  # Neighbor 2
    image[7:9, 4:7] = 4  # Neighbor 3
    image[2:4, 4:7] = 5  # Neighbor 4
    return image


class TestLabelStatistics3D:
    def test_get_coordination_number_simple(self, sample_3d_image):
        spacing = np.array([1.0, 1.0, 1.0])
        stats = LabelStatistics3D(im=sample_3d_image, spacing=spacing, is_pore=True)
        coordination_number = stats.get_coordination_number(label=1)
        assert coordination_number == 4

    def test_get_coordination_number_isolated(self, sample_3d_image):
        spacing = np.array([1.0, 1.0, 1.0])
        image = np.zeros_like(sample_3d_image)
        image[4:7, 4:7, 4:7] = 1
        stats = LabelStatistics3D(im=image, spacing=spacing, is_pore=True)
        coordination_number = stats.get_coordination_number(label=1)
        assert coordination_number == 0

    def test_get_coordination_number_empty_points(self, sample_3d_image):
        spacing = np.array([1.0, 1.0, 1.0])
        stats = LabelStatistics3D(im=sample_3d_image, spacing=spacing, is_pore=True)
        coordination_number = stats.get_coordination_number(label=99)
        assert coordination_number == 0

    def test_get_coordination_number_with_background(self, sample_3d_image):
        spacing = np.array([1.0, 1.0, 1.0])
        # Add background label 0 as a neighbor
        sample_3d_image[4:7, 7:9, 4:7] = 0
        stats = LabelStatistics3D(im=sample_3d_image, spacing=spacing, is_pore=True)
        coordination_number = stats.get_coordination_number(label=1)
        assert coordination_number == 3  # Should not count label 0


class TestLabelStatistics2D:
    def test_get_coordination_number_simple(self, sample_2d_image):
        spacing = np.array([1.0, 1.0])
        stats = LabelStatistics2D(im=sample_2d_image, spacing=spacing, direction=None, is_pore=True)
        coordination_number = stats.get_coordination_number(label=1)
        assert coordination_number == 4

    def test_get_coordination_number_isolated(self, sample_2d_image):
        spacing = np.array([1.0, 1.0])
        image = np.zeros_like(sample_2d_image)
        image[4:7, 4:7] = 1
        stats = LabelStatistics2D(im=image, spacing=spacing, direction=None, is_pore=True)
        coordination_number = stats.get_coordination_number(label=1)
        assert coordination_number == 0

    def test_get_coordination_number_empty_points(self, sample_2d_image):
        spacing = np.array([1.0, 1.0])
        stats = LabelStatistics2D(im=sample_2d_image, spacing=spacing, direction=None, is_pore=True)
        coordination_number = stats.get_coordination_number(label=99)
        assert coordination_number == 0

    def test_get_coordination_number_with_background(self, sample_2d_image):
        spacing = np.array([1.0, 1.0])
        # Add background label 0 as a neighbor
        sample_2d_image[4:7, 7:9] = 0
        stats = LabelStatistics2D(im=sample_2d_image, spacing=spacing, direction=None, is_pore=True)
        coordination_number = stats.get_coordination_number(label=1)
        assert coordination_number == 3  # Should not count label 0


# Principal axes (3D): orientation, axis lengths, elongation and flatness


def voxelized_ellipsoid(semi_axes, rotation_degrees, spacing):
    """World (z, y, x) points of the voxels inside an ellipsoid centered at the origin, and its axes as rows.

    semi_axes go from the major to the minor axis; the axes are the rotated z, y and x unit vectors, in that order.
    """
    axes = Rotation.from_euler("xyz", rotation_degrees, degrees=True).as_matrix()  # columns are the rotated axes
    axes = axes[:, ::-1].T  # rows, in (z, y, x) order
    axes = axes[:, ::-1]
    extent = max(semi_axes)
    grid = np.arange(-extent - spacing, extent + 2 * spacing, spacing)
    points = np.stack(np.meshgrid(grid, grid, grid, indexing="ij"), axis=-1).reshape(-1, 3)
    inside = (((points @ axes.T) / np.array(semi_axes)) ** 2).sum(axis=1) <= 1
    return points[inside], axes


def statistics_3d(points, spacing, **options):
    statistics = LabelStatistics3D(im=None, spacing=np.full(3, spacing), is_pore=True, **options)
    return dict(zip(statistics.attributes, statistics(1, points)))


@pytest.mark.parametrize(
    "axis, expected",
    [
        ((0.6, 0.0, -0.8), (0.6, 0.0, -0.8)),  # points toward +z
        ((-0.6, 0.0, 0.8), (0.6, 0.0, -0.8)),
        ((0.0, -0.8, 0.6), (0.0, 0.8, -0.6)),  # horizontal: toward +y
        ((0.0, 0.0, -1.0), (0.0, 0.0, 1.0)),  # along x: toward +x
        ((-4e-6, -0.8, 0.6), (4e-6, 0.8, -0.6)),  # z below the report's rounding counts as zero
    ],
)
def test_orient_axes_points_each_axis_toward_positive_z_then_y_then_x(axis, expected):
    np.testing.assert_allclose(orient_axes([axis])[0], expected)


def test_principal_axes_columns_are_optional():
    points, _ = voxelized_ellipsoid((8, 5, 3), (0, 0, 0), spacing=0.5)

    default = LabelStatistics3D(im=None, spacing=np.full(3, 0.5), is_pore=True)
    everything = LabelStatistics3D(
        im=None, spacing=np.full(3, 0.5), is_pore=True, include_orientation=True, include_axis_lengths=True
    )

    assert default.attributes == LabelStatistics3D.ATTRIBUTES
    assert len(default(1, points)) == len(default.attributes)
    assert everything.attributes == LabelStatistics3D.ATTRIBUTES + ORIENTATION_COLUMNS + AXIS_LENGTH_COLUMNS
    assert len(everything(1, points)) == len(everything.attributes)


@pytest.mark.parametrize("rotation", [(0, 0, 0), (25, -40, 70), (90, 30, 0)])
def test_principal_axes_match_the_ellipsoid(rotation):
    semi_axes = (10.0, 6.0, 3.5)
    points, true_axes = voxelized_ellipsoid(semi_axes, rotation, spacing=0.25)

    stats = statistics_3d(points, 0.25, include_orientation=True, include_axis_lengths=True)

    found_axes = np.array([[stats[f"{axis}_axis_{c}"] for c in "zyx"] for axis in PRINCIPAL_AXES])
    np.testing.assert_allclose(found_axes @ found_axes.T, np.eye(3), atol=1e-9)  # orthonormal
    np.testing.assert_allclose(np.abs(np.sum(found_axes * true_axes, axis=1)), 1, atol=1e-3)  # along the true axes
    np.testing.assert_allclose(found_axes, orient_axes(found_axes))  # sign convention applied

    lengths = np.array([stats[f"{axis}_axis_length"] for axis in PRINCIPAL_AXES])
    np.testing.assert_allclose(lengths, 2 * np.array(semi_axes), rtol=0.02)
    assert stats["ellipsoid_volume"] == pytest.approx(np.pi / 6 * np.prod(lengths))


@pytest.mark.parametrize(
    "semi_axes, elongation, flatness",
    [
        ((6.0, 6.0, 6.0), 0.0, 0.0),  # sphere
        ((12.0, 4.0, 4.0), 2 / 3, 0.0),  # prolate: elongated, round cross-section
        ((8.0, 8.0, 2.0), 0.0, 3 / 4),  # oblate: flat
        ((12.0, 6.0, 2.0), 1 / 2, 2 / 3),
    ],
)
def test_elongation_and_flatness_follow_kong_and_fonseca(semi_axes, elongation, flatness):
    points, _ = voxelized_ellipsoid(semi_axes, (10, 20, 30), spacing=0.25)

    stats = statistics_3d(points, 0.25)

    assert stats["elongation"] == pytest.approx(elongation, abs=0.02)
    assert stats["flatness"] == pytest.approx(flatness, abs=0.02)
    assert stats["aspect_ratio"] == pytest.approx(semi_axes[2] / semi_axes[0], rel=0.02)


# Voxels measured as boxes (3D): thin segments and Feret diameters


def statistics_3d_on_voxels(mask, spacing, ras_to_ijk_transform=None):
    """Statistics of the voxels of a (K, J, I) mask, given as the points the Segment Inspector CLI passes: the
    (S, A, R) coordinates of the voxel indices, for an axis aligned volume with spacing in (K, J, I) order."""
    points = np.argwhere(mask) * np.asarray(spacing, dtype=float)
    statistics = LabelStatistics3D(im=None, spacing=spacing, is_pore=True, ras_to_ijk_transform=ras_to_ijk_transform)
    result = statistics(1, points)
    return None if result is None else dict(zip(statistics.attributes, result))


def box_mask(voxels):
    mask = np.zeros(np.array(voxels) + 4, dtype=bool)
    mask[tuple(slice(2, 2 + n) for n in voxels)] = True
    return mask


@pytest.mark.parametrize("voxels", [(1, 1, 1), (1, 20, 30), (3, 1, 8), (10, 6, 3)])
@pytest.mark.parametrize("spacing", [(1.0, 1.0, 1.0), (2.0, 1.0, 0.5), (3.0, 0.5, 0.5)])
def test_box_of_voxels_is_measured_exactly(voxels, spacing):
    """A box of voxels is a solid box: its Feret diameter is its diagonal, and its variance along each side of length L
    is L^2 / 12. Boxes one voxel thick, including a single voxel, are measured instead of dropped."""
    sides = np.array(voxels) * np.array(spacing)

    stats = statistics_3d_on_voxels(box_mask(voxels), spacing)

    assert stats is not None
    assert stats["volume"] == pytest.approx(np.prod(sides))
    assert stats["max_feret"] == pytest.approx(np.linalg.norm(sides))
    semi_axes = np.sort(np.sqrt(5 / 12) * sides)
    assert stats["ellipsoid_volume"] == pytest.approx(4 / 3 * np.pi * np.prod(semi_axes))
    assert stats["aspect_ratio"] == pytest.approx(semi_axes[0] / semi_axes[2])


@pytest.mark.parametrize("spacing", [(1.0, 1.0, 1.0), (3.0, 1.0, 1.0)])
def test_nearly_flat_segment_keeps_its_thickness(spacing):
    """A plate one slice thick with a few voxels in the next slice: as points, its variance across the plate is almost
    zero, which made its ellipsoid volume and aspect ratio one or more orders of magnitude too small."""
    mask = np.zeros((6, 64, 64), dtype=bool)
    mask[2, 2:62, 2:62] = True
    mask[3, 30, 30:33] = True

    stats = statistics_3d_on_voxels(mask, spacing)

    assert stats["ellipsoid_volume"] / stats["volume"] == pytest.approx(np.pi / 6 * (5 / 3) ** 1.5, rel=0.02)
    plate_semi_axes = np.sqrt(5 / 12) * np.array([spacing[0], 60, 60])
    assert stats["aspect_ratio"] == pytest.approx(plate_semi_axes[0] / plate_semi_axes[2], rel=0.02)


@pytest.mark.parametrize("spacing", [(1.0, 1.0, 1.0), (2.0, 1.0, 0.5), (0.5, 0.5, 3.0)])
def test_thin_ellipsoid_volume_and_axes_match_at_coarse_spacing(spacing):
    semi_axes = np.array([4.5, 20.0, 40.0])  # thin along K: 3 to 18 slices thick
    grids = np.meshgrid(*[np.arange(-45 // s, 45 // s + 1) * s for s in spacing], indexing="ij")
    mask = sum((g / a) ** 2 for g, a in zip(grids, semi_axes)) <= 1

    stats = statistics_3d_on_voxels(mask, spacing)

    assert stats is not None
    assert stats["ellipsoid_volume"] == pytest.approx(4 / 3 * np.pi * np.prod(semi_axes), rel=0.1)
    assert stats["ellipsoid_volume"] / stats["volume"] == pytest.approx(1, rel=0.1)
    assert stats["aspect_ratio"] == pytest.approx(semi_axes[0] / semi_axes[2], rel=0.15)


def test_voxel_extent_follows_the_volume_orientation():
    """In a rotated volume, the voxel boxes are rotated too: a segment measures the same as in an axis aligned one."""
    spacing_kji = np.array([3.0, 1.0, 0.5])
    mask = np.zeros((5, 40, 40), dtype=bool)
    mask[2, 5:35, 10:25] = True  # one slice thick: its thickness comes only from the voxel extent
    mask[3, 18, 15:18] = True

    ijk_to_ras = np.eye(4)
    rotation = Rotation.from_euler("xyz", (20, -35, 50), degrees=True).as_matrix()
    ijk_to_ras[:3, :3] = rotation @ np.diag(spacing_kji[::-1])
    ijk_to_ras[:3, 3] = (10.0, -4.0, 7.0)
    points_operator = np.eye(4)  # as VolumeOperator.ijkToRasOperator: (K, J, I) indices to (S, A, R)
    points_operator[:3, :3] = ijk_to_ras[:3, :3][::-1, ::-1]
    points_operator[:3, 3] = ijk_to_ras[:3, 3][::-1]
    points = (points_operator @ np.c_[np.argwhere(mask), np.ones(mask.sum())].T).T[:, :3]

    rotated = LabelStatistics3D(
        im=None, spacing=spacing_kji, is_pore=True, ras_to_ijk_transform=np.linalg.inv(ijk_to_ras).tolist()
    )
    rotated_stats = dict(zip(rotated.attributes, rotated(1, points)))
    aligned_stats = statistics_3d_on_voxels(mask, spacing_kji)

    for column in ("volume", "max_feret", "aspect_ratio", "elongation", "flatness", "ellipsoid_volume"):
        assert rotated_stats[column] == pytest.approx(aligned_stats[column]), column
