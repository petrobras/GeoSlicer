"""Synthetic pore-space geometries with analytically known pore network properties.

Used as ground truth by the pore network extraction tests. Everything here is pure numpy and
works in voxel index space with numpy axis order (z, y, x), the same order used by
``general_pn_extract`` for its ``scale`` argument.
"""

from dataclasses import dataclass, field
from itertools import product
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

# Radii of the 27 spheres, all different so pore size ranks are unambiguous. The order is
# shuffled so that radius does not correlate with grid position.
DEFAULT_RADII = (
    52.0, 52.9, 46.9, 51.1, 49.9, 49.6, 53.5, 49.3, 46.0,
    50.5, 48.4, 48.7, 51.4, 47.8, 46.3, 49.0, 46.6, 53.8,
    50.8, 50.2, 47.2, 48.1, 52.6, 47.5, 52.3, 51.7, 53.2,
)  # fmt: skip
GRID_SIDE = 3  # spheres along each axis


@dataclass
class SphereGrid:
    """Union of overlapping spheres together with its exact radical-plane partition."""

    binary: np.ndarray  # uint8, 1 inside the union of the spheres
    labels: np.ndarray  # int32, sphere i -> label i + 1, 0 outside
    centers: np.ndarray  # (n, 3) sphere centers, voxel index space, (z, y, x)
    radii: np.ndarray  # (n,) sphere radii, voxels
    pairs: List[Tuple[int, int]]  # overlapping (lattice neighbor) sphere pairs, i < j
    spacing: np.ndarray  # (3,) voxel size, (z, y, x)
    boundary_height: float  # distance from the outer sphere centers to the volume faces cutting them, voxels
    expected: Dict[str, np.ndarray] = field(default_factory=dict)


@dataclass
class _Cap:
    """Spherical cap cut by a plane normal to ``axis``, on the ``side`` (-1 or 1) of the sphere center."""

    axis: int
    side: int
    height: float  # distance from the sphere center to the cutting plane
    neighbor: Optional[int]  # sphere on the other side of the plane, None for a volume face


def _cap_volume(radius: float, height: float) -> float:
    return np.pi * height**2 * (3 * radius - height) / 3


def _cap_centroid_distance(radius: float, height: float) -> float:
    """Distance from the sphere center to the centroid of a spherical cap of the given height."""
    return 3 * (2 * radius - height) ** 2 / (4 * (3 * radius - height))


def sphere_grid_3x3x3(
    distance: float = 84.0,
    radii: Sequence[float] = DEFAULT_RADII,
    size: int = 251,
    spacing: Sequence[float] = (1.0, 1.0, 1.0),
) -> SphereGrid:
    """Builds 27 spheres centered on a 3x3x3 lattice with step ``distance``, in a cube of ``size`` voxels.

    Lattice neighbors along an axis overlap and no other spheres do, so the expected network has
    27 pores and 54 throats. Each voxel is assigned to the sphere with the smallest power distance
    |x - c|^2 - r^2, which splits overlapping spheres exactly at their radical plane, the plane
    containing the intersection circle.

    The lattice is centered in the volume, whose faces cut the outer spheres at
    ``(size - 2 * distance) / 2`` from their centers. With the defaults that is close to
    ``distance / 2``, so the cross sections on the volume faces are similar to the necks between
    the spheres. Only the central sphere is not cut by any face. The faces are the outer voxel faces,
    half a voxel beyond the centers of the first and last voxels. An odd ``size`` with an integer
    ``distance`` puts the sphere centers on voxel centers, where the distance transform is sampled.

    Expected values in ``SphereGrid.expected`` are in voxel units; multiply by the spacing (lengths),
    spacing^2 (areas) or spacing^3 (volumes) when the spacing is isotropic.
    """
    n = GRID_SIDE**3
    radii = np.asarray(radii, dtype=float)
    assert radii.shape == (n,), f"Exactly {n} radii are needed"
    spacing = np.asarray(spacing, dtype=float)
    boundary_height = (size - (GRID_SIDE - 1) * distance) / 2
    assert boundary_height > 0, "The volume is too small for the lattice"
    assert np.all(boundary_height < radii), "The volume faces must cut every outer sphere"

    lattice = np.array(list(product(range(GRID_SIDE), repeat=3)))
    centers = boundary_height - 0.5 + distance * lattice.astype(float)
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n) if np.abs(lattice[i] - lattice[j]).sum() == 1]
    assert len(pairs) == 3 * GRID_SIDE**2 * (GRID_SIDE - 1)
    for i in range(n):
        for j in range(i + 1, n):
            if (i, j) not in pairs:
                gap = np.linalg.norm(centers[i] - centers[j]) - radii[i] - radii[j]
                assert gap > 2, f"Spheres {i} and {j} touch, but they are not lattice neighbors"

    # Distance from each sphere center to each radical plane, h_ij, measured from sphere i.
    heights = {}
    for i, j in pairs:
        heights[i, j] = (distance**2 + radii[i] ** 2 - radii[j] ** 2) / (2 * distance)
        heights[j, i] = distance - heights[i, j]
        assert 0 < heights[i, j] < radii[i] and 0 < heights[j, i] < radii[j], f"Spheres {i} and {j} don't overlap"

    # Every sphere is cut on each of its 6 sides, by a radical plane or by a volume face.
    index = {tuple(cell): i for i, cell in enumerate(lattice)}
    caps = []
    for i in range(n):
        sphere_caps = []
        for axis, side in product(range(3), (-1, 1)):
            cell = lattice[i].copy()
            cell[axis] += side
            j = index.get(tuple(cell))
            sphere_caps.append(_Cap(axis, side, boundary_height if j is None else heights[i, j], j))
        for a, b in product(sphere_caps, repeat=2):
            # Caps cut by planes normal to different axes must not intersect, otherwise the analytic
            # volume (sphere minus independent caps) would subtract their intersection twice. Checked
            # with the volume faces moved to the outer voxel centers too, see ``open_pore_volume``.
            if a.axis != b.axis:
                height_a = a.height - 0.5 * (a.neighbor is None)
                height_b = b.height - 0.5 * (b.neighbor is None)
                assert height_a**2 + height_b**2 > radii[i] ** 2, f"Caps of sphere {i} intersect"
        caps.append(sphere_caps)

    labels, power = _power_partition((int(size),) * 3, centers, radii)
    inside = power <= 0
    labels[~inside] = 0

    result = SphereGrid(
        binary=inside.astype(np.uint8),
        labels=labels,
        centers=centers,
        radii=radii,
        pairs=pairs,
        spacing=spacing,
        boundary_height=boundary_height,
    )
    result.expected = _expected_network(result, heights, caps)
    return result


def _power_partition(shape: Tuple[int, ...], centers: np.ndarray, radii: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Assigns each voxel to the sphere with the smallest power distance, among the spheres covering it.

    Each sphere only updates its bounding box, so memory does not grow with the number of spheres.
    Returns the labels (sphere i -> i + 1, 0 where no sphere covers the voxel) and the power distance.
    """
    best = np.full(shape, np.inf, dtype=np.float32)
    labels = np.zeros(shape, dtype=np.int32)
    for i, (center, radius) in enumerate(zip(centers, radii)):
        low = np.maximum(np.floor(center - radius).astype(int), 0)
        high = np.minimum(np.ceil(center + radius).astype(int) + 1, shape)
        box = tuple(slice(lo, hi) for lo, hi in zip(low, high))
        z, y, x = np.ogrid[box]
        power = ((z - center[0]) ** 2 + (y - center[1]) ** 2 + (x - center[2]) ** 2 - radius**2).astype(np.float32)
        # Strict comparison keeps the lowest index on ties, like argmin.
        closer = power < best[box]
        best[box][closer] = power[closer]
        labels[box][closer] = i + 1
    return labels, best


def _expected_network(
    grid: SphereGrid, heights: Dict[Tuple[int, int], float], caps: List[List[_Cap]]
) -> Dict[str, np.ndarray]:
    """Analytic pore and throat properties of the sphere grid, in voxel units."""
    n = len(grid.radii)
    volume = np.zeros(n)
    centroid = grid.centers.copy()
    # Volume between each volume face and the outer voxel centers, by axis (z, y, x) and side (0 low, 1 high).
    open_face_loss = np.zeros((n, 3, 2))
    for i in range(n):
        r = grid.radii[i]
        volume[i] = 4 / 3 * np.pi * r**3
        moment = np.zeros(3)
        for cap in caps[i]:
            cap_height = r - cap.height
            cap_volume = _cap_volume(r, cap_height)
            volume[i] -= cap_volume
            moment[cap.axis] -= cap_volume * _cap_centroid_distance(r, cap_height) * cap.side
            if cap.neighbor is None:
                open_face_loss[i, cap.axis, (cap.side + 1) // 2] = _cap_volume(r, cap_height + 0.5) - cap_volume
        centroid[i] += moment / volume[i]

    flat_labels = grid.labels.ravel()
    voxel_count = np.bincount(flat_labels, minlength=n + 1)[1:]
    voxel_centroid = np.zeros((n, 3))
    for axis in range(3):
        coordinate = np.arange(grid.labels.shape[axis], dtype=float).reshape([-1 if a == axis else 1 for a in range(3)])
        weights = np.broadcast_to(coordinate, grid.labels.shape).ravel()
        voxel_centroid[:, axis] = np.bincount(flat_labels, weights=weights, minlength=n + 1)[1:]
    voxel_centroid /= voxel_count[:, None]

    # Volume faces cutting each sphere, by axis (z, y, x) and side (0 low, 1 high).
    boundary_sides = np.zeros((n, 3, 2), dtype=bool)
    for i, sphere_caps in enumerate(caps):
        for cap in sphere_caps:
            if cap.neighbor is None:
                boundary_sides[i, cap.axis, (cap.side + 1) // 2] = True

    neck_radius = np.array([np.sqrt(grid.radii[i] ** 2 - heights[i, j] ** 2) for i, j in grid.pairs])
    # Cross section of sphere i one voxel from the radical plane toward its center, the farthest its
    # interface voxels can be from the plane.
    inner_neck_radius = np.array([np.sqrt(grid.radii[i] ** 2 - (heights[i, j] - 1) ** 2) for i, j in grid.pairs])
    boundary_face_count = boundary_sides.sum(axis=(1, 2))
    # Point where the line between the sphere centers crosses the radical plane.
    neck_center = np.array(
        [
            grid.centers[i]
            + heights[i, j] * (grid.centers[j] - grid.centers[i]) / np.linalg.norm(grid.centers[j] - grid.centers[i])
            for i, j in grid.pairs
        ]
    )

    return {
        "throat.face_counts": interface_face_counts(grid.labels, grid.pairs),
        "pore.volume": volume,
        "pore.open_face_loss": open_face_loss,
        "pore.voxel_count": voxel_count,
        "pore.centroid": centroid,
        "pore.voxel_centroid": voxel_centroid,
        "pore.boundary_sides": boundary_sides,
        # Pore positions reported by the extractor: the voxel centroid, moved onto the volume faces it touches.
        "pore.coords": snap_to_volume_faces(voxel_centroid, boundary_sides, grid.labels.shape),
        "pore.min_plane_distance": np.array([min(cap.height for cap in sphere_caps) for sphere_caps in caps]),
        # Number of volume faces cutting each sphere: 3 on the lattice corners down to 0 at its center.
        "pore.boundary_face_count": boundary_face_count,
        # Radius of the disk where the volume faces cut each sphere, NaN for spheres not cut by any face.
        "pore.boundary_radius": np.where(
            boundary_face_count > 0, np.sqrt(grid.radii**2 - grid.boundary_height**2), np.nan
        ),
        "throat.neck_radius": neck_radius,
        "throat.inner_neck_radius": inner_neck_radius,
        "throat.area": np.pi * neck_radius**2,
        "throat.neck_center": neck_center,
        "network.union_volume": volume.sum(),
    }


def open_pore_volume(grid: SphereGrid, open_sides: Optional[np.ndarray] = None) -> np.ndarray:
    """Pore volumes measured by the extractor, in voxel units, when the faces in ``open_sides`` are on the volume border.

    The extractor's pore surface ends on the outer voxel centers at the volume border, half a voxel
    inside the faces, while padding the volume closes it on the faces themselves. ``open_sides`` is
    (n, 3, 2) as in ``snap_to_volume_faces``, by default every face cutting the spheres.
    """
    if open_sides is None:
        open_sides = grid.expected["pore.boundary_sides"]
    return grid.expected["pore.volume"] - (grid.expected["pore.open_face_loss"] * open_sides).sum(axis=(1, 2))


def snap_to_volume_faces(points: np.ndarray, sides: np.ndarray, shape: Sequence[int]) -> np.ndarray:
    """Moves pore positions onto the volume faces the pores touch, as the extractor does with boundary pores.

    ``points`` is (n, 3) in voxel index space (z, y, x) and ``sides`` is (n, 3, 2), True where pore i
    touches the low (0) or high (1) face normal to an axis. The position along that axis becomes the
    center of the outermost voxel layer, index 0 or ``shape[axis] - 1``.
    """
    snapped = np.array(points, dtype=float)
    for axis in range(3):
        snapped[sides[:, axis, 0], axis] = 0
        snapped[sides[:, axis, 1], axis] = shape[axis] - 1
    return snapped


def touched_volume_faces(labels: np.ndarray, n: int) -> np.ndarray:
    """(n, 3, 2) array, True where label i + 1 appears on the low (0) or high (1) face normal to each axis."""
    sides = np.zeros((n, 3, 2), dtype=bool)
    for axis in range(3):
        for side, index in enumerate((0, -1)):
            found = np.unique(np.take(labels, index, axis=axis))
            found = found[(found > 0) & (found <= n)]
            sides[found - 1, axis, side] = True
    return sides


def interface_face_counts(labels: np.ndarray, pairs: Sequence[Tuple[int, int]]) -> np.ndarray:
    """Number of voxel faces shared by each pair of regions, split by the face normal axis (z, y, x).

    Region i is label i + 1. This is the discrete counterpart of the throat cross-section.
    """
    counts = {pair: np.zeros(3) for pair in pairs}
    for axis in range(3):
        before = np.moveaxis(labels, axis, 0)[:-1].ravel()
        after = np.moveaxis(labels, axis, 0)[1:].ravel()
        mask = (before > 0) & (after > 0) & (before != after)
        low = np.minimum(before[mask], after[mask]) - 1
        high = np.maximum(before[mask], after[mask]) - 1
        found, number = np.unique(np.stack([low, high], axis=1), axis=0, return_counts=True)
        for (i, j), n in zip(found, number):
            if (i, j) in counts:
                counts[i, j][axis] = n
    return np.array([counts[pair] for pair in pairs])


def face_area(face_counts: np.ndarray, spacing: Sequence[float]) -> np.ndarray:
    """Throat area as computed by PoreSpy: the norm of the projected areas on each axis."""
    sz, sy, sx = np.asarray(spacing, dtype=float)
    projected = face_counts * np.array([sy * sx, sz * sx, sz * sy])
    return np.linalg.norm(projected, axis=-1)


@dataclass
class SubresolutionChannel:
    """Two resolved spheres joined by a cylinder of subresolution porosity, along the x axis."""

    porosity_map: np.ndarray  # float32, 1 resolved, ``channel_porosity`` in the channel, 0 solid
    labels: np.ndarray  # int32, 1 and 2 for the spheres, 3 for the channel outside them
    channel_porosity: float
    sphere_volume: np.ndarray  # (2,) voxel counts
    channel_volume: int  # voxel count of the channel outside the spheres


def spheres_with_subresolution_channel(
    sphere_radius: float = 10.0,
    distance: float = 40.0,
    channel_radius: float = 5.0,
    channel_porosity: float = 0.3,
    margin: int = 4,
) -> SubresolutionChannel:
    assert channel_radius < sphere_radius
    size_yz = int(2 * (sphere_radius + margin) + 1)
    size_x = int(distance + 2 * (sphere_radius + margin) + 1)
    z, y, x = np.indices((size_yz, size_yz, size_x), dtype=np.float32)
    center_yz = (size_yz - 1) / 2
    center_x = (sphere_radius + margin, sphere_radius + margin + distance)

    radial = (z - center_yz) ** 2 + (y - center_yz) ** 2
    spheres = [radial + (x - cx) ** 2 <= sphere_radius**2 for cx in center_x]
    channel = (radial <= channel_radius**2) & (x >= center_x[0]) & (x <= center_x[1])
    channel &= ~(spheres[0] | spheres[1])

    porosity_map = np.zeros(z.shape, dtype=np.float32)
    porosity_map[channel] = channel_porosity
    labels = np.zeros(z.shape, dtype=np.int32)
    labels[channel] = 3
    for i, sphere in enumerate(spheres):
        porosity_map[sphere] = 1.0
        labels[sphere] = i + 1

    return SubresolutionChannel(
        porosity_map=porosity_map,
        labels=labels,
        channel_porosity=channel_porosity,
        sphere_volume=np.array([np.count_nonzero(s) for s in spheres]),
        channel_volume=int(np.count_nonzero(channel)),
    )


def pore_coords_zyx(df_pores, spacing: Sequence[float]) -> np.ndarray:
    """Pore coordinates from an extracted pore table, converted to voxel index space (z, y, x)."""
    coords_xyz = df_pores[["pore.coords_0", "pore.coords_1", "pore.coords_2"]].to_numpy()
    return coords_xyz[:, ::-1] / np.asarray(spacing, dtype=float)


def match_pores(coords_zyx: np.ndarray, reference_zyx: np.ndarray, max_distance: float) -> np.ndarray:
    """Maps each extracted pore to the index of the nearest reference point.

    Raises AssertionError if two pores map to the same reference or a pore is farther than
    ``max_distance`` voxels from every reference, which means the partition is not the expected one.
    """
    distances = np.linalg.norm(coords_zyx[:, None, :] - reference_zyx[None, :, :], axis=2)
    mapping = np.argmin(distances, axis=1)
    worst = distances[np.arange(len(mapping)), mapping].max() if len(mapping) else 0.0
    assert worst <= max_distance, f"A pore is {worst:.2f} voxels away from every expected position"
    assert len(np.unique(mapping)) == len(mapping), f"Pores don't map one-to-one: {mapping}"
    return mapping


def mapped_throat_pairs(df_throats, mapping: np.ndarray) -> List[Tuple[int, int]]:
    """Throat connections expressed as sorted pairs of reference indices."""
    conns = df_throats[["throat.conns_0", "throat.conns_1"]].to_numpy().astype(int)
    return [tuple(sorted((int(mapping[a]), int(mapping[b])))) for a, b in conns]
