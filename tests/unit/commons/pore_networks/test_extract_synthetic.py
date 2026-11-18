"""Pore network extraction checked against synthetic geometries with analytically known networks.

The 27-sphere grid (see ``commons.pore_networks.synthetic``) has a known topology (27 pores, 54
throats) and known pore volumes, radii and throat necks. Assertions are split in two kinds:

- exact: values that follow directly from the definition of a property (e.g. throat volume is
  total length times area) or from the discrete geometry (e.g. throat area is the count of shared
  voxel faces). These must only change when a property definition is deliberately changed.
- toleranced: comparisons against continuous analytic geometry, which the voxelized volume only
  approximates. Tolerances are named constants below, each with the reason it is needed.

The first extraction in a session is slow because numba compiles the extraction kernels.
"""

from collections import deque

import numpy as np
import pytest

from commons.pore_networks.functions_extract import general_pn_extract
from commons.pore_networks.synthetic import (
    DEFAULT_RADII,
    face_area,
    match_pores,
    mapped_throat_pairs,
    open_pore_volume,
    pore_coords_zyx,
    snap_to_volume_faces,
    sphere_grid_3x3x3,
    spheres_with_subresolution_channel,
    touched_volume_faces,
)

SPACING = 0.01  # mm, isotropic voxel size of the base extraction
EXACT = 1e-6  # relative tolerance for values that must match up to floating point error

# Marching cubes volume vs. the continuous truncated sphere, on spheres ~14 voxels in radius.
VOLUME_RTOL = 0.03
# Pore radius is the max of the EDT, which is sampled on voxel centers.
RADIUS_ATOL_VOXELS = 0.5
# Throat inscribed radius is the max EDT over the interface voxels of the lower labeled pore, which
# sit up to one voxel away from the radical plane toward its center, where the cross section is
# wider: ``throat.inner_neck_radius`` bounds it from above, and this tolerance from below.
NECK_ATOL_VOXELS = 1.0
# A voxelized disk of radius ~6-9 voxels has a staircase border; its face count overestimates the
# area of the continuous disk.
NECK_AREA_RTOL = 0.30
# Watershed results are compared loosely, as the partition is allowed to change with the method.
WATERSHED_RTOL = 0.10

# Face flag set by the extractor on the pores touching each volume face, as (axis, side) in numpy
# order (z, y, x), side 0 being the face at index 0. The extractor calls axis 0 "x" and its index 0 face "max".
FACE_FLAGS = {"xmax": (0, 0), "xmin": (0, 1), "ymax": (1, 0), "ymin": (1, 1), "zmax": (2, 0), "zmin": (2, 1)}


def _small_sphere_grid():
    # Scaled-down grid (73^3 voxels) keeping all the geometric constraints of the default one.
    return sphere_grid_3x3x3(distance=24, radii=np.array(DEFAULT_RADII) * 24 / 84, size=73)


def _extract(scalar=None, labels=None, spacing=(SPACING,) * 3, is_multiscale=False):
    df_pores, df_throats, df_network, _, _ = general_pn_extract(
        scalar,
        labels,
        np.asarray(spacing, dtype=float),
        watershed_blur={"1": 0.4, "2": 0.8},
        is_multiscale=is_multiscale,
        force_cpu=True,
        divs=0,
    )
    return df_pores, df_throats, df_network.iloc[0]


def _assert_pore_radius(pores, grid, spacing):
    """Pore radius is the max of the EDT, which treats the volume border as solid.

    It matches the sphere radius for the spheres inside the volume. For the ones cut by the volume
    faces it is bounded by the nearest cutting plane and by the sphere itself.
    """
    radius = pores["pore.radius"].to_numpy() / spacing
    inside = grid.expected["pore.boundary_face_count"] == 0
    np.testing.assert_allclose(radius[inside], grid.radii[inside], atol=RADIUS_ATOL_VOXELS, err_msg="pore.radius")
    cut = ~inside
    assert np.all(radius[cut] >= grid.expected["pore.min_plane_distance"][cut] - RADIUS_ATOL_VOXELS)
    assert np.all(radius[cut] <= grid.radii[cut] + RADIUS_ATOL_VOXELS)


def _canonical(df_pores, df_throats, reference_zyx, spacing, max_distance=1.0):
    """Orders pores by reference index and throats as ``pairs``, so results can be compared by position.

    Returns (pores, throats, pairs, mapping) where ``mapping[k]`` is the reference index of pore row k.
    """
    mapping = match_pores(pore_coords_zyx(df_pores, spacing), reference_zyx, max_distance)
    pairs = mapped_throat_pairs(df_throats, mapping)
    pores = df_pores.iloc[np.argsort(mapping)].reset_index(drop=True)
    throats = df_throats.iloc[np.argsort([p[0] * 100 + p[1] for p in pairs])].reset_index(drop=True)
    return pores, throats, sorted(pairs), mapping


def _is_connected(n_pores, conns):
    neighbors = {i: set() for i in range(n_pores)}
    for a, b in conns:
        neighbors[a].add(b)
        neighbors[b].add(a)
    seen, queue = {0}, deque([0])
    while queue:
        for n in neighbors[queue.popleft()] - seen:
            seen.add(n)
            queue.append(n)
    return len(seen) == n_pores


@pytest.fixture(scope="module")
def grid():
    return _small_sphere_grid()


@pytest.fixture(scope="module")
def labeled_network(grid):
    return _extract(labels=grid.labels)


# --- Pre-partitioned labelmap (single scale) ---


def test_labeled_topology(grid, labeled_network):
    df_pores, df_throats, network = labeled_network
    assert len(df_pores) == len(grid.radii)
    assert len(df_throats) == len(grid.pairs)
    assert network["network.number_of_pores"] == len(grid.radii)
    assert network["network.number_of_throats"] == len(grid.pairs)

    _, _, pairs, _ = _canonical(df_pores, df_throats, grid.expected["pore.coords"], grid.spacing * SPACING)
    assert pairs == sorted(grid.pairs)

    conns = df_throats[["throat.conns_0", "throat.conns_1"]].to_numpy()
    assert np.all(conns[:, 0] != conns[:, 1])
    assert len({tuple(sorted(c)) for c in conns}) == len(conns), "Duplicated throats"


def test_labeled_pore_properties(grid, labeled_network):
    df_pores, df_throats, _ = labeled_network
    expected = grid.expected
    pores, _, _, _ = _canonical(df_pores, df_throats, expected["pore.coords"], grid.spacing * SPACING)

    np.testing.assert_allclose(
        pore_coords_zyx(pores, (SPACING,) * 3), expected["pore.coords"], atol=0.05, err_msg="pore.coords"
    )
    np.testing.assert_allclose(pores["pore.volume"], open_pore_volume(grid) * SPACING**3, rtol=VOLUME_RTOL)
    np.testing.assert_allclose(
        pores["pore.equivalent_diameter"], 2 * (3 * pores["pore.volume"] / (4 * np.pi)) ** (1 / 3), rtol=EXACT
    )
    _assert_pore_radius(pores, grid, SPACING)
    np.testing.assert_allclose(pores["pore.extended_diameter"], 2 * pores["pore.radius"], rtol=EXACT)

    # The largest ball inside a truncated sphere is at least as large as the distance from its
    # center to the nearest cutting plane, and at most the sphere itself.
    inscribed_radius = pores["pore.inscribed_diameter"] / 2 / SPACING
    assert np.all(inscribed_radius >= expected["pore.min_plane_distance"] - 1)
    assert np.all(inscribed_radius <= grid.radii)

    assert np.all(pores["pore.phase"] == 1)
    np.testing.assert_allclose(pores["pore.subresolution_porosity"], 1.0)
    np.testing.assert_allclose(pores["pore.effective_volume"], pores["pore.volume"], rtol=EXACT)
    for face, (axis, side) in FACE_FLAGS.items():
        np.testing.assert_array_equal(
            pores[f"pore.{face}"], expected["pore.boundary_sides"][:, axis, side], err_msg=f"pore.{face}"
        )


def test_labeled_throat_properties(grid, labeled_network):
    df_pores, df_throats, _ = labeled_network
    expected = grid.expected
    pores, throats, pairs, mapping = _canonical(df_pores, df_throats, expected["pore.coords"], grid.spacing * SPACING)
    order = [grid.pairs.index(pair) for pair in pairs]
    neck_radius = expected["throat.neck_radius"][order]

    area = throats["throat.cross_sectional_area"].to_numpy()
    np.testing.assert_allclose(area, face_area(expected["throat.face_counts"][order], (SPACING,) * 3), rtol=EXACT)
    np.testing.assert_allclose(area, np.pi * (neck_radius * SPACING) ** 2, rtol=NECK_AREA_RTOL)
    np.testing.assert_allclose(throats["throat.equivalent_diameter"], np.sqrt(4 * area / np.pi), rtol=EXACT)
    inscribed_radius = throats["throat.inscribed_diameter"].to_numpy() / 2 / SPACING
    assert np.all(inscribed_radius >= neck_radius - NECK_ATOL_VOXELS)
    assert np.all(inscribed_radius <= expected["throat.inner_neck_radius"][order])

    # Lengths: direct length joins the two pore positions, and the total length goes through the throat.
    coords = pores[["pore.coords_0", "pore.coords_1", "pore.coords_2"]].to_numpy()
    first = [pair[0] for pair in pairs]
    second = [pair[1] for pair in pairs]
    np.testing.assert_allclose(
        throats["throat.direct_length"], np.linalg.norm(coords[first] - coords[second], axis=1), rtol=EXACT
    )
    analytic_centroids = snap_to_volume_faces(
        expected["pore.centroid"], expected["pore.boundary_sides"], grid.labels.shape
    )
    np.testing.assert_allclose(
        throats["throat.direct_length"] / SPACING,
        np.linalg.norm(analytic_centroids[first] - analytic_centroids[second], axis=1),
        atol=0.5,
    )
    assert np.all(throats["throat.total_length"] >= throats["throat.direct_length"] * (1 - EXACT))

    # Derived properties follow their definitions.
    np.testing.assert_allclose(throats["throat.volume"], throats["throat.total_length"] * area, rtol=EXACT)
    raw_conns = throats[["throat.conns_0", "throat.conns_1"]].to_numpy().astype(int)
    radius = df_pores["pore.radius"].to_numpy()
    np.testing.assert_allclose(throats["throat.conns_0_length"], radius[raw_conns[:, 0]], rtol=EXACT)
    np.testing.assert_allclose(throats["throat.conns_1_length"], radius[raw_conns[:, 1]], rtol=EXACT)
    assert np.all(throats["throat.mid_length"] > 0)
    assert np.all((throats["throat.shape_factor"] >= 0.01) & (throats["throat.shape_factor"] <= 0.09))
    np.testing.assert_allclose(throats["throat.subresolution_porosity"], 1.0)


def test_labeled_network_summary(grid, labeled_network):
    df_pores, _, network = labeled_network
    np.testing.assert_allclose(df_pores["pore.volume"].sum(), open_pore_volume(grid).sum() * SPACING**3, rtol=0.01)
    np.testing.assert_allclose(network["network.input_volume_porosity"], grid.binary.mean() * 100, rtol=EXACT)
    np.testing.assert_allclose(network["network.input_subscale_porosity"], 0.0)
    np.testing.assert_allclose(network["network.voxel_volume"], SPACING**3, rtol=EXACT)
    np.testing.assert_allclose(network["network.input_total_volume"], grid.binary.size * SPACING**3, rtol=EXACT)


# --- Watershed (snow2) on a binary porosity map ---


@pytest.mark.parametrize("resolved_value", [1.0, 100.0], ids=["ratio", "percentage"])
def test_watershed_sphere_grid(grid, resolved_value):
    df_pores, df_throats, network = _extract(scalar=grid.binary.astype(np.float32) * resolved_value, is_multiscale=True)

    # Topology must be exact: the necks are narrow enough that any sensible watershed splits the spheres.
    assert len(df_pores) == len(grid.radii)
    assert len(df_throats) == len(grid.pairs)
    expected = grid.expected
    pores, throats, pairs, _ = _canonical(
        df_pores, df_throats, expected["pore.coords"], grid.spacing * SPACING, max_distance=3.0
    )
    assert pairs == sorted(grid.pairs)
    assert np.all(pores["pore.phase"] == 1)
    np.testing.assert_allclose(pores["pore.subresolution_porosity"], 1.0, atol=1e-3)
    assert network["network.input_subscale_porosity"] == pytest.approx(0.0)

    # Geometry only approximately, the watershed ridge does not need to be the radical plane.
    np.testing.assert_allclose(pores["pore.volume"], open_pore_volume(grid) * SPACING**3, rtol=WATERSHED_RTOL)
    _assert_pore_radius(pores, grid, SPACING)
    order = [grid.pairs.index(pair) for pair in pairs]
    ideal_area = face_area(expected["throat.face_counts"][order], (SPACING,) * 3)
    np.testing.assert_allclose(throats["throat.cross_sectional_area"], ideal_area, rtol=WATERSHED_RTOL)


# --- Invariances ---


def test_isotropic_spacing_scaling(grid, labeled_network):
    factor = 3.0
    base_pores, base_throats, _ = labeled_network
    pores, throats, _ = _extract(labels=grid.labels, spacing=(SPACING * factor,) * 3)

    assert len(pores) == len(base_pores) and len(throats) == len(base_throats)
    for column, power in (
        ("pore.volume", 3),
        ("pore.surface_area", 2),
        ("pore.radius", 1),
        ("pore.inscribed_diameter", 1),
        ("pore.equivalent_diameter", 1),
        ("pore.coords_0", 1),
    ):
        np.testing.assert_allclose(pores[column], base_pores[column] * factor**power, rtol=EXACT, err_msg=column)
    for column, power in (
        ("throat.cross_sectional_area", 2),
        ("throat.volume", 3),
        ("throat.total_length", 1),
        ("throat.direct_length", 1),
        ("throat.inscribed_diameter", 1),
        ("throat.perimeter", 1),
    ):
        np.testing.assert_allclose(throats[column], base_throats[column] * factor**power, rtol=EXACT, err_msg=column)
    for column in ("throat.shape_factor", "pore.shape_factor"):
        frame = throats if column.startswith("throat") else pores
        base = base_throats if column.startswith("throat") else base_pores
        np.testing.assert_allclose(frame[column], base[column], rtol=EXACT, err_msg=column)


def test_anisotropic_spacing(grid, labeled_network):
    spacing_zyx = np.array([1.0, 1.3, 1.7]) * SPACING
    base_pores, _, _ = labeled_network
    df_pores, df_throats, network = _extract(labels=grid.labels, spacing=spacing_zyx)

    expected = grid.expected
    pores, throats, pairs, _ = _canonical(df_pores, df_throats, expected["pore.coords"], spacing_zyx)
    assert pairs == sorted(grid.pairs)
    # Each coordinate column must be scaled by the spacing of its own axis.
    np.testing.assert_allclose(pore_coords_zyx(pores, spacing_zyx), expected["pore.coords"], atol=0.05)
    order = [grid.pairs.index(pair) for pair in pairs]
    np.testing.assert_allclose(
        throats["throat.cross_sectional_area"],
        face_area(expected["throat.face_counts"][order], spacing_zyx),
        rtol=EXACT,
    )
    voxel_volume = np.prod(spacing_zyx)
    np.testing.assert_allclose(
        df_pores["pore.volume"].sum(), base_pores["pore.volume"].sum() / SPACING**3 * voxel_volume, rtol=EXACT
    )
    np.testing.assert_allclose(network["network.voxel_volume"], voxel_volume, rtol=EXACT)


@pytest.mark.parametrize(
    "name, transform, transform_points",
    [
        ("transpose", lambda a: np.transpose(a, (2, 0, 1)), lambda p, shape: p[:, [2, 0, 1]]),
        ("flip_z", lambda a: a[::-1], lambda p, shape: p * [-1, 1, 1] + [shape[0] - 1, 0, 0]),
        ("flip_x", lambda a: a[:, :, ::-1], lambda p, shape: p * [1, 1, -1] + [0, 0, shape[2] - 1]),
        ("pad", lambda a: np.pad(a, ((5, 0), (2, 7), (0, 4))), lambda p, shape: p + [5, 2, 0]),
    ],
)
def test_geometric_invariance(grid, labeled_network, name, transform, transform_points):
    base_pores, base_throats, _ = labeled_network
    labels = np.ascontiguousarray(transform(grid.labels))
    df_pores, df_throats, _ = _extract(labels=labels)

    base, base_t, base_pairs, _ = _canonical(base_pores, base_throats, grid.expected["pore.coords"], (SPACING,) * 3)
    # Pores are placed on the faces of the transformed volume, which the padding moves away from some pores.
    moved_coords = snap_to_volume_faces(
        transform_points(grid.expected["pore.voxel_centroid"], grid.labels.shape),
        touched_volume_faces(labels, len(grid.radii)),
        labels.shape,
    )
    pores, throats, pairs, _ = _canonical(df_pores, df_throats, moved_coords, (SPACING,) * 3)

    assert pairs == base_pairs
    np.testing.assert_allclose(pore_coords_zyx(pores, (SPACING,) * 3), moved_coords, atol=0.05)
    pore_columns = ["pore.radius", "pore.inscribed_diameter"]
    throat_columns = ["throat.cross_sectional_area", "throat.inscribed_diameter"]
    if name == "pad":
        # Padding closes the pore surfaces on the faces it moves away from the volume border, adding
        # volume and area to those pores, and changes the pore positions, which the throat lengths follow.
        open_sides = touched_volume_faces(labels, len(grid.radii))
        closed = (grid.expected["pore.boundary_sides"] & ~open_sides).any(axis=(1, 2))
        np.testing.assert_allclose(
            pores["pore.volume"], open_pore_volume(grid, open_sides) * SPACING**3, rtol=VOLUME_RTOL, err_msg=name
        )
        for column in ("pore.volume", "pore.surface_area"):
            np.testing.assert_allclose(
                pores.loc[~closed, column], base.loc[~closed, column], rtol=EXACT, err_msg=f"{name}: {column}"
            )
            assert np.all(pores.loc[closed, column] > base.loc[closed, column]), f"{name}: {column}"
    else:
        pore_columns += ["pore.volume", "pore.surface_area"]
        throat_columns.append("throat.total_length")
    for column in pore_columns:
        np.testing.assert_allclose(pores[column], base[column], rtol=EXACT, err_msg=f"{name}: {column}")
    for column in throat_columns:
        np.testing.assert_allclose(throats[column], base_t[column], rtol=EXACT, err_msg=f"{name}: {column}")


def test_label_permutation_invariance(grid, labeled_network):
    base_pores, base_throats, _ = labeled_network
    permutation = np.concatenate([[0], np.random.default_rng(0).permutation(len(grid.radii)) + 1])
    df_pores, df_throats, _ = _extract(labels=permutation[grid.labels].astype(np.int32))

    coords = grid.expected["pore.coords"]
    base, base_t, base_pairs, _ = _canonical(base_pores, base_throats, coords, (SPACING,) * 3)
    pores, throats, pairs, _ = _canonical(df_pores, df_throats, coords, (SPACING,) * 3)
    assert pairs == base_pairs
    for column in ("pore.volume", "pore.radius", "pore.coords_0", "pore.coords_1", "pore.coords_2"):
        np.testing.assert_allclose(pores[column], base[column], rtol=EXACT, err_msg=column)
    np.testing.assert_allclose(
        throats["throat.cross_sectional_area"], base_t["throat.cross_sectional_area"], rtol=EXACT
    )
    # The throat point is found on the interface voxels of the lower labeled pore, so swapping
    # labels moves it to the other side of the interface, changing the length by a fraction of a voxel.
    np.testing.assert_allclose(throats["throat.total_length"], base_t["throat.total_length"], atol=0.1 * SPACING)


# --- Multiscale: resolved spheres joined by a subresolution channel ---


@pytest.fixture(scope="module")
def channel():
    return spheres_with_subresolution_channel()


@pytest.mark.parametrize("porosity_scale", [1.0, 100.0], ids=["ratio", "percentage"])
@pytest.mark.parametrize("with_labels", [False, True], ids=["watershed", "labels"])
def test_multiscale_channel(channel, porosity_scale, with_labels):
    porosity = channel.channel_porosity
    df_pores, df_throats, network = _extract(
        scalar=channel.porosity_map * porosity_scale,
        labels=channel.labels if with_labels else None,
        spacing=(SPACING,) * 3,
        is_multiscale=True,
    )

    resolved = df_pores["pore.phase"] == 1
    subresolution = df_pores["pore.phase"] == 2
    assert resolved.sum() == 2, "Each resolved sphere must be a single pore"
    assert subresolution.sum() >= 1
    if with_labels:
        assert len(df_pores) == 3 and len(df_throats) == 2

    np.testing.assert_allclose(df_pores.loc[resolved, "pore.subresolution_porosity"], 1.0, atol=1e-3)
    np.testing.assert_allclose(df_pores.loc[subresolution, "pore.subresolution_porosity"], porosity, atol=1e-3)
    np.testing.assert_allclose(
        df_pores["pore.effective_volume"],
        df_pores["pore.volume"] * df_pores["pore.subresolution_porosity"],
        rtol=EXACT,
    )
    np.testing.assert_allclose(
        np.sort(df_pores.loc[resolved, "pore.volume"]), channel.sphere_volume * SPACING**3, rtol=VOLUME_RTOL
    )
    np.testing.assert_allclose(
        df_pores.loc[subresolution, "pore.volume"].sum(), channel.channel_volume * SPACING**3, rtol=VOLUME_RTOL
    )

    # The two spheres are only connected through the channel.
    conns = df_throats[["throat.conns_0", "throat.conns_1"]].to_numpy().astype(int)
    assert _is_connected(len(df_pores), conns)
    phase = df_pores["pore.phase"].to_numpy()
    assert not any(phase[a] == 1 and phase[b] == 1 for a, b in conns), "Spheres must not be directly connected"
    touches_channel = (phase[conns[:, 0]] == 2) | (phase[conns[:, 1]] == 2)
    np.testing.assert_allclose(df_throats.loc[touches_channel, "throat.subresolution_porosity"], porosity, atol=1e-3)

    total_volume = channel.porosity_map.size
    np.testing.assert_allclose(
        network["network.input_resolved_porosity"], channel.sphere_volume.sum() / total_volume * 100, rtol=EXACT
    )
    np.testing.assert_allclose(
        network["network.input_subscale_porosity"],
        channel.channel_volume * porosity / total_volume * 100,
        rtol=1e-4,
    )
