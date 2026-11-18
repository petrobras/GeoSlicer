"""Rigid registration of paired microCT core volumes via bright-blob constellation matching.

Detects compact, high-attenuation inclusions ("blobs") in both volumes by their contrast against the
local background, and matches small constellations of them: tetrahedra built from each blob and its
nearest neighbours, compared by their six edge lengths and handedness. That is invariant under
arbitrary rotation (not just rotation about one axis) but not under mirroring. Each matching pair of
tetrahedra is a complete rigid hypothesis; the best supported one is only accepted if the blobs that
did not build it line up under it far better than chance would allow (an a-contrario test, see
`_significance`). That acceptance needs no thresholds tuned to the data; the constants below only
steer the search for a hypothesis.

Blob positions are compared in a frame common to both volumes (index * spacing), so the two volumes
may have different (and anisotropic) voxel spacing. Where one is much finer along an axis, it is
first block-averaged to about the other's voxel size, so both resolve the same inclusions. Search tolerances are relative to the volume
size, with a floor in voxels (see `_scale_params`). Each volume gets a blob budget proportional to
the amount of sample it holds, so a cropped volume and a full one have comparable blob densities.

Public entry point: `register(fixed, moving, ...) -> (4x4 index-space transform matrix, info)`.
"""

import itertools
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy import ndimage, special
from scipy.spatial import cKDTree

logger = logging.getLogger(__name__)


class RegistrationFailed(RuntimeError):
    """Raised when no geometrically consistent rigid transform could be found.

    `diagnostics` carries the detection/matching counts at the point of failure, useful for
    troubleshooting (e.g. distinguishing "too few blobs detected" from "no matching geometry").
    """

    def __init__(self, reason, diagnostics=None):
        super().__init__(reason)
        self.diagnostics = diagnostics or {}


# Search tolerances, as (fraction of the in-plane size, floor in voxels); see `_scale_params`.
# They only decide whether the true alignment is found; whether it is accepted is up to
# `_significance`.
_TOLERANCES = dict(
    edge_tol=(0.002, 2.0),  # tetrahedron edge agreement, see `_tetrahedra`
    tol_inlier=(0.003, 1.5),  # a blob lines up under a hypothesis
    tol_nn=(0.0015, 0.75),  # final refit pairing
    sigma_background=(0.025, 8.0),  # smoothing of the local background blobs are measured against
)

# Along an axis where one volume's voxels are at least this many times finer than the other's, the
# finer one is block-averaged to about the coarser voxel size before anything else (see
# `_resolution_factors`).
_RESOLUTION_RATIO = 1.5

# Blob detection max-pools both volumes to the same physical size: the in-plane size / this...
_POOLED_INPLANE_SIZE = 250
# ...unless that leaves a volume with more pooled voxels than this. Detection holds about 9 bytes
# per pooled voxel, so this bounds it to ~2.5 GB, however small the other volume is.
_MAX_POOLED_VOXELS = 256 * 1024**2

# The local background is estimated on a grid this many pooled voxels coarser.
_BACKGROUND_FACTOR = 4

# The volume with less sample gets `max_blobs`; the other proportionally more, up to this ratio.
_MAX_BUDGET_RATIO = 10

# Tetrahedra: each blob with 3 of its k nearest neighbours. The fixed side looks further so that
# blobs detected in one scan only do not break up its neighbourhoods: its _K_FIXED nearest, plus
# any further ones (up to _K_FIXED_MAX) within the reach of most moving neighbourhoods, the
# _REACH_PERCENTILE of the moving blobs' _K_MOVING-th neighbour distance. Where the fixed scan has
# several times more blobs per volume than the moving one (a larger budget for a smaller share of
# blob-bearing sample, or finer features), a moving tetrahedron's partner is still among them.
# An edge matches within `edge_tol` (see _TOLERANCES); flatter tetrahedra than _MIN_SHAPE
# (|det| / longest edge**3, 0.71 for a regular one) are dropped, as their handedness and fit are
# unreliable.
_K_MOVING = 6
_K_FIXED = 9
_K_FIXED_MAX = 20
_REACH_PERCENTILE = 90
_MIN_SHAPE = 0.05
_EDGES = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
_VERTEX_EDGES = np.array([[v in edge for v in range(4)] for edge in _EDGES], float)  # (6, 4) incidence
# Hypotheses are ranked by how many of the anchor's _K_SUPPORT neighbours line up, then the best
# _TOP_HYPOTHESES by how many of all blobs do.
_K_SUPPORT = 12
_TOP_HYPOTHESES = 100
_MAX_HYPOTHESES = 300_000

# `_significance` estimates each blob's local fixed-blob density from its `_KNN` nearest fixed
# neighbours, and assumes blobs are spread over a surface (`_NULL_DIM` = 2) rather than a volume:
# inclusions often concentrate on fractures or laminae, where chance matches grow like tau**2, and
# a 3-D model then lets a wrong alignment through. For a 3-D spread, 2 is merely conservative.
_KNN = 10
_NULL_DIM = 2


def _scale_params(fixed_shape, fixed_spacing, moving_shape, moving_spacing):
    """Pool factors for each volume and search tolerances (in index * spacing units).

    Everything scales with the in-plane size L of the SMALLER volume: blobs are the same physical
    size in both scans, so when one is a larger field of view at the same resolution, its own L
    would make the tolerances too loose for the blobs. Both volumes are max-pooled to the same
    physical size, L / _POOLED_INPLANE_SIZE, so blobs merge alike in both, except that a volume
    much larger than the other (a full scan against a small crop or a finer sub-volume) is pooled
    further, to at most _MAX_POOLED_VOXELS. Each tolerance is a fraction of L, but never less than
    its floor in voxels of the COARSER volume, below which blobs cannot be located. Shapes are
    (z, y, x), spacings (x, y, z).
    """
    volumes = [(fixed_shape, np.asarray(fixed_spacing, float)), (moving_shape, np.asarray(moving_spacing, float))]
    inplane = min(0.5 * (shape[1] * spacing[1] + shape[2] * spacing[0]) for shape, spacing in volumes)
    voxel = max(spacing.max() for _, spacing in volumes)
    pooled = inplane / _POOLED_INPLANE_SIZE
    pools = []
    for shape, spacing in volumes:
        pool = int(np.clip(round(pooled / (0.5 * (spacing[0] + spacing[1]))), 1, 4))
        while np.prod([d // pool for d in shape], dtype=np.int64) > _MAX_POOLED_VOXELS:
            pool += 1
        pools.append(pool)
    params = {name: max(fraction * inplane, floor * voxel) for name, (fraction, floor) in _TOLERANCES.items()}
    return dict(pool_fixed=pools[0], pool_moving=pools[1], voxel=voxel, **params)


def _resolution_factors(spacing_f, spacing_m):
    """Per-axis (x, y, z) block-mean factors for the fixed and the moving volume that bring the
    finer one, along each axis where they differ by _RESOLUTION_RATIO or more, to about the
    coarser voxel size. A finer scan resolves inclusions too small to show in the coarser one;
    detected, they would crowd out the blobs both scans share.
    """
    ratio = np.asarray(spacing_m, float) / np.asarray(spacing_f, float)
    factors_f = np.where(ratio >= _RESOLUTION_RATIO, np.floor(ratio + 0.5), 1).astype(int)
    factors_m = np.where(1 / ratio >= _RESOLUTION_RATIO, np.floor(1 / ratio + 0.5), 1).astype(int)
    return factors_f, factors_m


def _block_index(factors):
    """Index transform from a block-reduced volume back to the original: block i along an axis
    with factor f covers original voxels f*i .. f*i + f-1, so its centre is at f*i + (f-1)/2."""
    matrix = np.diag([*np.asarray(factors, float), 1.0])
    matrix[:3, 3] = (np.asarray(factors, float) - 1) / 2
    return matrix


def _block_reduce(volume, factor, reduce, workers=None, chunk_z=4, progress=None, dtype=None):
    """Block reduction (`reduce` is "max" or "mean") of a (z, y, x) volume by `factor`, one int for
    all axes or one per (z, y, x) axis, parallelized over z-slabs of `chunk_z` output slices.
    numpy's reductions release the GIL, so this scales close to linearly with core count on large
    volumes. "max" keeps the volume's dtype; "mean" returns float32 unless `dtype` says otherwise.

    Each slab is reduced one axis at a time, z first: reducing over a leading axis is an
    element-wise operation on whole rows, which numpy vectorizes, while a single reduction over
    axes (1, 3, 5) of the 6-D block view is several times slower.

    `progress`, if given, is called with a fraction in (0, 1] as each z-slab completes. The
    ThreadPoolExecutor results are consumed on the calling thread, so `progress` runs there too.
    """
    fz, fy, fx = (int(factor),) * 3 if np.isscalar(factor) else (int(f) for f in factor)
    dtype = volume.dtype if reduce == "max" else (dtype or np.float32)
    if fz == fy == fx == 1:
        if progress:
            progress(1.0)
        return np.ascontiguousarray(volume, dtype=dtype)
    nz, ny, nx = (d // f * f for d, f in zip(volume.shape, (fz, fy, fx)))
    workers = workers or min(16, os.cpu_count() or 4)
    out = np.empty((nz // fz, ny // fy, nx // fx), dtype)

    def _reduce_slab(z0):
        z1 = min(z0 + chunk_z * fz, nz)
        n = (z1 - z0) // fz
        slab = volume[z0:z1, :ny, :nx]
        if reduce == "max":
            slab = slab.reshape(n, fz, ny, nx).max(1)
            slab = slab.reshape(n, ny // fy, fy, nx).max(2)
            reduced = slab.reshape(n, ny // fy, nx // fx, fx).max(3)
        else:
            slab = slab.reshape(n, fz, ny, nx).sum(1, dtype=np.float32)
            slab = slab.reshape(n, ny // fy, fy, nx).sum(2)
            reduced = slab.reshape(n, ny // fy, nx // fx, fx).sum(3) / np.float32(fz * fy * fx)
            if np.issubdtype(dtype, np.integer):
                reduced = np.rint(reduced)
        return z0 // fz, reduced

    slab_starts = list(range(0, nz, chunk_z * fz))
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool_exec:
        for z0_reduced, reduced in pool_exec.map(_reduce_slab, slab_starts):
            out[z0_reduced : z0_reduced + reduced.shape[0]] = reduced
            done += 1
            if progress:
                progress(done / len(slab_starts))
    return out


def _max_pool(volume, pool, **kwargs):
    return _block_reduce(volume, pool, "max", **kwargs)


def _sample_background(volume, spacing, pool, sigma, progress=None):
    """Where the sample is, and its local background level, on a coarse grid.

    The sample mask keeps coarse blocks of at least half the 90th-percentile block level: air,
    masked-out corners and other empty space reconstruct far below the sample's bulk level. The
    background is a Gaussian average (`sigma` in spacing units) over sample blocks only, so neither
    beam-hardening cupping nor the sample edge biases it. Returns a dict with the grid `factor` (in
    voxels), the `mask` and `background` arrays and the `sample_volume` (in spacing units cubed).
    """
    factor = _BACKGROUND_FACTOR * pool
    coarse = _block_reduce(volume, factor, "mean", progress=progress)
    mask = coarse >= 0.5 * np.percentile(coarse, 90)
    sigma_zyx = sigma / (factor * np.asarray(spacing, float)[::-1])
    weight = ndimage.gaussian_filter(mask.astype(np.float32), sigma_zyx)
    background = ndimage.gaussian_filter(np.where(mask, coarse, 0).astype(np.float32), sigma_zyx)
    background /= np.maximum(weight, 1e-6)
    sample_volume = float(mask.sum()) * factor**3 * float(np.prod(spacing))
    return dict(factor=factor, mask=mask, background=background, sample_volume=sample_volume)


def _subtract_background(pooled, background, mask, factor, workers=None, chunk_z=16):
    """In place: pooled -= background, trilinearly upsampled by `factor`; -inf outside the mask."""
    axes = []
    for n_out, n_in in zip(pooled.shape, background.shape):
        coord = np.clip((np.arange(n_out) + 0.5) / factor - 0.5, 0, n_in - 1)
        lo = np.minimum(np.floor(coord).astype(np.intp), max(n_in - 2, 0))
        axes.append(
            (
                lo,
                np.minimum(lo + 1, n_in - 1),
                (coord - lo).astype(np.float32),
                np.minimum(np.arange(n_out) // factor, n_in - 1),
            )
        )
    (lz, hz, wz, nz), (ly, hy, wy, ny), (lx, hx, wx, nx) = axes

    def _slab(z0):
        z1 = min(z0 + chunk_z, pooled.shape[0])
        w = wz[z0:z1, None, None]
        b = background[lz[z0:z1]] * (1 - w) + background[hz[z0:z1]] * w
        b = b[:, ly] * (1 - wy)[None, :, None] + b[:, hy] * wy[None, :, None]
        b = b[:, :, lx] * (1 - wx) + b[:, :, hx] * wx
        slab = pooled[z0:z1]
        slab -= b
        slab[~mask[nz[z0:z1]][:, ny][:, :, nx]] = -np.inf

    with ThreadPoolExecutor(max_workers=workers or min(16, os.cpu_count() or 4)) as pool_exec:
        list(pool_exec.map(_slab, range(0, pooled.shape[0], chunk_z)))


def _detect_blobs(volume, background, max_blobs, pool, progress=None):
    """Detect compact bright inclusions: max-pool -> subtract the local background -> threshold the
    contrast at its 99.9th percentile inside the sample -> connected components -> full-resolution
    contrast-weighted centroid + mass per component. `background` is `_sample_background`'s result.
    Returns the `max_blobs` most massive components as (points (N, 3) in (x, y, z) index coords,
    masses (N,)).

    `progress`, if given, is called with a fraction in (0, 1] over the course of detection.
    """
    # Max-pooling dominates detection time on large volumes; give it the bulk of the progress
    # budget, reserving the tail for labeling and the per-component centroid pass.
    contrast = _max_pool(volume, pool, progress=(lambda f: progress(0.7 * f)) if progress else None).astype(np.float32)
    coarse_bg, factor = background["background"], background["factor"]
    _subtract_background(contrast, coarse_bg, background["mask"], factor // pool)
    stride = max(1, int(np.ceil((contrast.size / 3e7) ** (1 / 3))))  # the percentile needs no more
    values = contrast[::stride, ::stride, ::stride]
    # A blob is brighter than its surroundings, whatever the percentile says on a flat background.
    threshold = max(float(np.percentile(values[np.isfinite(values)], 99.9)), 0.0)
    del values
    labels, n_components = ndimage.label(contrast > threshold)
    del contrast
    if progress:
        progress(0.85)

    points, masses = [], []
    for label_id, box_slice in enumerate(ndimage.find_objects(labels), start=1):
        z0, y0, x0 = (s.start * pool for s in box_slice)
        box = volume[
            z0 : box_slice[0].stop * pool, y0 : box_slice[1].stop * pool, x0 : box_slice[2].stop * pool
        ].astype(np.float32)
        own = labels[box_slice] == label_id
        own = np.repeat(np.repeat(np.repeat(own, pool, 0), pool, 1), pool, 2)
        own = own[: box.shape[0], : box.shape[1], : box.shape[2]]
        # The background is smooth on the scale of a blob: its value at the box centre will do.
        centre = [
            min((start + size // 2) // factor, n - 1)
            for start, size, n in zip((z0, y0, x0), box.shape, coarse_bg.shape)
        ]
        box -= coarse_bg[tuple(centre)]
        mask = (box > threshold) & own
        if not mask.any():
            continue
        weights = box * mask
        zz, yy, xx = np.mgrid[z0 : z0 + box.shape[0], y0 : y0 + box.shape[1], x0 : x0 + box.shape[2]]
        total = weights.sum()
        points.append(((xx * weights).sum() / total, (yy * weights).sum() / total, (zz * weights).sum() / total))
        masses.append(mask.sum())

    points, masses = np.array(points).reshape(-1, 3), np.array(masses, np.float32)
    order = np.argsort(masses)[::-1][:max_blobs]
    if progress:
        progress(1.0)
    logger.debug("detected %d components above contrast=%.0f, kept top %d by mass", n_components, threshold, len(order))
    return points[order], masses[order]


def _kabsch(a, b):
    """Closed-form rigid transform (R, t) minimizing sum ||R @ a_i + t - b_i||^2."""
    ca, cb = a.mean(0), b.mean(0)
    u, _, vt = np.linalg.svd((a - ca).T @ (b - cb))
    r = vt.T @ np.diag([1, 1, np.sign(np.linalg.det(vt.T @ u.T))]) @ u.T
    return r, cb - r @ ca


def _kabsch_batch(a, b):
    """`_kabsch` over a batch: a, b (H, n, 3) -> R (H, 3, 3), t (H, 3)."""
    ca, cb = a.mean(1), b.mean(1)
    u, _, vt = np.linalg.svd(np.einsum("hni,hnj->hij", a - ca[:, None], b - cb[:, None]))
    v, ut = np.swapaxes(vt, 1, 2), np.swapaxes(u, 1, 2)
    d = np.ones((len(a), 3))
    d[:, 2] = np.sign(np.linalg.det(v @ ut))
    r = (v * d[:, None, :]) @ ut
    return r, cb - np.einsum("hij,hj->hi", r, ca)


def _fit_rigid(a, b, inlier_tol):
    """Kabsch fit with iterative outlier rejection. Returns (R, t, inlier_mask, residuals)."""
    r, t = _kabsch(a, b)
    resid = np.linalg.norm((r @ a.T).T + t - b, axis=1)
    for _ in range(3):
        inliers = resid < max(inlier_tol, float(np.median(resid)))
        if inliers.sum() < 4:
            break
        r, t = _kabsch(a[inliers], b[inliers])
        resid = np.linalg.norm((r @ a.T).T + t - b, axis=1)
    return r, t, resid < inlier_tol, resid


def _edge_lengths(points, verts):
    x = points[verts]
    return np.stack([np.linalg.norm(x[:, i] - x[:, j], axis=1) for i, j in _EDGES], 1)


def _tetrahedra(points, k, edge_tol, ambiguous, reach=0.0, k_max=None):
    """Tetrahedra of each point with 3 of its neighbours, as (vertices (T, 4), keys (T, 7)). The
    neighbours are its k nearest, plus any further ones within `reach`, up to `k_max` in all.

    Vertices are ordered by their summed edge length, so the key -- the six edge lengths in that
    order, plus the sign of the volume -- does not depend on
    which blob was the anchor, and mirror images never match. When two vertices' sums are too close
    to order reliably, `ambiguous` decides: "drop" the tetrahedron, or "both" orders (one side of
    the match does each, so a tie in either scan still matches).
    """
    k_max = min(max(k, k_max or k), len(points) - 1)
    dist, nn = cKDTree(points).query(points, k_max + 1)
    counts = np.clip((dist[:, 1:] <= reach).sum(1), min(k, k_max), k_max)
    verts = []
    for n in np.unique(counts):
        anchors = np.flatnonzero(counts == n)
        combos = np.array(list(itertools.combinations(range(n), 3)))
        verts.append(
            np.column_stack([np.repeat(anchors, len(combos)), nn[anchors, 1 : n + 1][:, combos].reshape(-1, 3)])
        )
    verts = np.unique(np.sort(np.concatenate(verts), 1), axis=0)

    sums = _edge_lengths(points, verts) @ _VERTEX_EDGES
    order = np.argsort(sums, 1)
    verts = np.take_along_axis(verts, order, 1)
    tied = np.diff(np.take_along_axis(sums, order, 1), axis=1) < 3 * edge_tol  # (T, 3)
    del sums, order
    if ambiguous == "drop":
        verts = verts[~tied.any(1)]
    else:
        swapped = []
        for g in range(3):
            v = verts[tied[:, g]].copy()
            v[:, [g, g + 1]] = v[:, [g + 1, g]]
            swapped.append(v)
        verts = np.concatenate([verts, *swapped])

    edges = _edge_lengths(points, verts)
    x = points[verts]
    det = np.linalg.det(x[:, 1:] - x[:, :1])
    del x
    keep = np.abs(det) > _MIN_SHAPE * edges.max(1, initial=0) ** 3
    # Same-handed keys agree in the 7th coordinate; mirrored ones differ by 2 * edge_tol, beyond the query radius.
    return verts[keep], np.column_stack([edges[keep], np.sign(det[keep]) * edge_tol])


def _match_tetrahedra(points_m, points_f, edge_tol, inlier_tol):
    """Best-supported rigid hypothesis from congruent tetrahedra.

    Every moving tetrahedron is looked up among the fixed ones by its key; each hit is a full rigid
    hypothesis (a 4-point Kabsch fit). Hypotheses are ranked by how many of the anchor's
    neighbours line up, and the best few by how many of all moving blobs do. Returns
    (R, t, builder moving indices, diagnostics), with R None if no tetrahedra match.
    """
    verts_m, keys_m = _tetrahedra(points_m, _K_MOVING, edge_tol, "drop")
    reach = np.percentile(cKDTree(points_m).query(points_m, _K_MOVING + 1)[0][:, -1], _REACH_PERCENTILE) + edge_tol
    verts_f, keys_f = _tetrahedra(points_f, _K_FIXED, edge_tol, "both", reach=reach, k_max=_K_FIXED_MAX)
    diagnostics = dict(tetrahedra_moving=len(verts_m), tetrahedra_fixed=len(verts_f), hits=0)
    if not len(verts_m) or not len(verts_f):
        return None, None, None, diagnostics
    hits = cKDTree(keys_f).query_ball_point(keys_m, r=edge_tol, p=np.inf)
    i_m = np.repeat(np.arange(len(verts_m)), [len(h) for h in hits])
    i_f = np.fromiter(itertools.chain.from_iterable(hits), np.intp, count=len(i_m))
    diagnostics["hits"] = len(i_m)
    if not len(i_m):
        return None, None, None, diagnostics
    if len(i_m) > _MAX_HYPOTHESES:
        pick = np.random.default_rng(0).choice(len(i_m), _MAX_HYPOTHESES, replace=False)
        i_m, i_f = i_m[pick], i_f[pick]

    a, b = points_m[verts_m[i_m]], points_f[verts_f[i_f]]
    r, t = _kabsch_batch(a, b)
    fit = np.linalg.norm(np.einsum("hij,hnj->hni", r, a) + t[:, None] - b, axis=2).max(1) < 2 * edge_tol
    i_m, r, t = i_m[fit], r[fit], t[fit]
    if not len(i_m):
        return None, None, None, diagnostics

    tree_f = cKDTree(points_f)
    _, neighbours = cKDTree(points_m).query(points_m, min(_K_SUPPORT, len(points_m) - 1) + 1)
    local = points_m[neighbours[verts_m[i_m, 0]]]
    moved = np.einsum("hij,hnj->hni", r, local) + t[:, None]
    support = np.isfinite(tree_f.query(moved.reshape(-1, 3), distance_upper_bound=inlier_tol)[0])
    best = np.argsort(-support.reshape(len(i_m), -1).sum(1))[:_TOP_HYPOTHESES]
    moved = np.einsum("hij,nj->hni", r[best], points_m) + t[best, None]
    support = np.isfinite(tree_f.query(moved.reshape(-1, 3), distance_upper_bound=inlier_tol)[0])
    support = support.reshape(len(best), -1).sum(1)
    h = best[int(np.argmax(support))]
    diagnostics.update(hypotheses=len(i_m), support=int(support.max()))
    return r[h], t[h], verts_m[i_m[h]], diagnostics


def _significance(moved, points_f, exclude):
    """A-contrario test of a candidate transform: could this many blobs line up by chance?

    `moved` are the moving blobs under the candidate transform; `exclude` indexes the ones that
    built it (they match by construction). For each remaining blob, the chance that some fixed blob
    falls within tau of it is estimated from the local fixed-blob density: `_KNN` neighbours within
    radius r_i means about `_KNN * (tau / r_i) ** _NULL_DIM` expected within tau. Only ratios of
    lengths enter, so the test is independent of units, voxel size and volume size. Neighbours are
    counted from the second one on, so a true match does not inflate its own density.

    For every tau (each observed match distance), the number of blobs matched within tau is
    compared with a Poisson of the summed chances (whose tail is heavier than the true one, so this
    errs towards rejecting). The minimum tail probability is multiplied by the number of tests --
    every triplet of correspondences a hypothesis could be built from, times every tau tried --
    giving the expected number of false alarms (NFA). Tetrahedron hypotheses are far fewer than
    that, so the count errs towards rejecting too. Returns (log10_nfa, tau, matched, tested); a
    log10_nfa below 0 means fewer than one false alarm expected.
    """
    tree = cKDTree(points_f)
    keep = np.ones(len(moved), bool)
    keep[list(exclude)] = False
    dist = tree.query(moved[keep], k=_KNN + 1)[0]
    radius = dist[:, _KNN]
    tau = np.sort(dist[:, 0])
    n = len(tau)
    matched = np.arange(1, n + 1)
    # Per-blob chance of a fixed blob within tau, capped at 1, summed over blobs.
    lam = (-np.expm1(-_KNN * (tau[:, None] / radius[None, :]) ** _NULL_DIM)).sum(1)
    lam = np.maximum(lam, np.finfo(float).tiny)
    # log P(Poisson(lam) >= k), summed in log space: a real alignment's tail underflows a float.
    # When lam >= k the tail is of order 1, so log10 0 is used (and the truncated sum is not).
    j = matched[:, None] + np.arange(400)[None, :]
    log_terms = j * np.log(lam)[:, None] - lam[:, None] - special.gammaln(j + 1)
    log10_tail = np.where(lam < matched, np.minimum(special.logsumexp(log_terms, axis=1), 0) / np.log(10), 0.0)
    log10_tests = 3 * np.log10(len(moved) * len(points_f)) + np.log10(n)
    log10_nfa = log10_tests + log10_tail
    best = int(np.argmin(log10_nfa))
    return float(log10_nfa[best]), float(tau[best]), int(matched[best]), n


def _nn_reassign(points_m, points_f, r, t, tol):
    """Refit on every blob pair: transform ALL moving blobs by (R, t) and greedily match each to
    its nearest fixed blob within `tol` (closest first, one-to-one), then refit Kabsch on the
    harvested pairs. Returns (pairs, R, t, residuals).
    """
    transformed = (r @ points_m.T).T + t
    dist, nearest = cKDTree(points_f).query(transformed, k=1)
    used_f, pairs = set(), []
    for m in np.argsort(dist):
        if dist[m] < tol and nearest[m] not in used_f:
            used_f.add(int(nearest[m]))
            pairs.append((int(m), int(nearest[m])))
    if len(pairs) < 3:
        return pairs, r, t, np.zeros(0)
    a = points_m[[m for m, _ in pairs]]
    b = points_f[[f for _, f in pairs]]
    r2, t2 = _kabsch(a, b)
    resid = np.linalg.norm((r2 @ a.T).T + t2 - b, axis=1)
    return pairs, r2, t2, resid


def register(
    fixed,
    moving,
    *,
    fixed_spacing=(1.0, 1.0, 1.0),
    moving_spacing=(1.0, 1.0, 1.0),
    max_blobs=400,
    progress_callback=None,
):
    """Compute the rigid transform mapping `moving` index coordinates onto `fixed` index
    coordinates.

    Both `fixed` and `moving` are (z, y, x) volumes containing a shared set of compact,
    high-attenuation inclusions visible in both scans. `fixed_spacing` and `moving_spacing` are
    their voxel sizes in (x, y, z) order (as Slicer's GetSpacing returns them), in any common unit;
    they may differ between the volumes and be anisotropic. The registration itself is rigid in
    physical space: the spacings are assumed correct, not estimated. Along an axis where one volume
    is much finer, a block-averaged copy of it is registered instead (see `_resolution_factors`);
    K still maps the original index coordinates.

    `max_blobs` is the blob budget of the volume holding less sample; the other gets
    proportionally more (up to `_MAX_BUDGET_RATIO` times), so equal-sized volumes both get
    `max_blobs`.

    Returns `(K, info)`. K is the 4x4 transform such that, for a moving index coordinate
    p = (x, y, z, 1), `K @ p` is the corresponding fixed index coordinate. With different spacings K
    is not a pure rotation plus translation; its physical counterpart is. `info` reports how well
    the blobs agree: `matched` of `tested` blobs lined up in the significance test (`log10_nfa`),
    and the final refit left an RMS residual of `rms` (spacing units) or `rms_voxels` (voxels of
    the coarser volume, after resolution matching) over `refit_pairs` blob pairs. The RMS mostly reflects how precisely blobs
    are located in each scan; the transform itself, fitted on many pairs, is more precise.

    `progress_callback`, if given, is called as `progress_callback(fraction, message)` with
    `fraction` in [0, 1] and a human-readable stage message, so a caller can drive a progress bar
    without this module depending on any UI. It is never called from a background thread.

    Raises RegistrationFailed if no significant rigid alignment is found; its `.diagnostics` dict
    carries the detection/matching counts for troubleshooting. Enable
    `logging.getLogger("commons.algorithms.fast_registration.fast_reg").setLevel(logging.DEBUG)` for
    detection details.
    """

    def _report(fraction, message):
        if progress_callback:
            progress_callback(fraction, message)

    def _stage(start, span, message):
        return (lambda f: _report(start + span * f, message)) if progress_callback else None

    spacing_f = np.asarray(fixed_spacing, float)
    spacing_m = np.asarray(moving_spacing, float)
    factors_f, factors_m = _resolution_factors(spacing_f, spacing_m)
    if (factors_f > 1).any() or (factors_m > 1).any():
        message = "Matching resolutions..."
        _report(0.0, message)
        fixed = _block_reduce(fixed, factors_f[::-1], "mean", dtype=fixed.dtype, progress=_stage(0.0, 0.05, message))
        moving = _block_reduce(
            moving, factors_m[::-1], "mean", dtype=moving.dtype, progress=_stage(0.05, 0.05, message)
        )
        spacing_f, spacing_m = spacing_f * factors_f, spacing_m * factors_m
    params = _scale_params(fixed.shape, spacing_f, moving.shape, spacing_m)

    message = "Locating the sample..."
    _report(0.1, message)
    sigma = params["sigma_background"]
    background_f = _sample_background(fixed, spacing_f, params["pool_fixed"], sigma, _stage(0.1, 0.05, message))
    background_m = _sample_background(moving, spacing_m, params["pool_moving"], sigma, _stage(0.15, 0.05, message))
    smaller = min(background_f["sample_volume"], background_m["sample_volume"])
    budgets = [
        int(min(round(max_blobs * b["sample_volume"] / smaller), _MAX_BUDGET_RATIO * max_blobs))
        for b in (background_f, background_m)
    ]

    message = "Detecting features in fixed volume..."
    _report(0.2, message)
    index_f, _ = _detect_blobs(fixed, background_f, budgets[0], params["pool_fixed"], _stage(0.2, 0.3, message))
    message = "Detecting features in moving volume..."
    _report(0.5, message)
    index_m, _ = _detect_blobs(moving, background_m, budgets[1], params["pool_moving"], _stage(0.5, 0.3, message))
    # `_significance` needs a local density from _KNN + 1 neighbours.
    if len(index_f) <= _KNN or len(index_m) <= _KNN:
        raise RegistrationFailed(
            "too few blobs detected in one or both volumes",
            dict(fixed_blobs=len(index_f), moving_blobs=len(index_m), min_blobs=_KNN + 1),
        )
    points_f, points_m = index_f * spacing_f, index_m * spacing_m

    _report(0.8, "Matching features and verifying alignment...")
    r, t, builders, diagnostics = _match_tetrahedra(
        points_m, points_f, edge_tol=params["edge_tol"], inlier_tol=params["tol_inlier"]
    )
    diagnostics.update(fixed_blobs=len(points_f), moving_blobs=len(points_m))
    if r is None:
        raise RegistrationFailed("no matching blob constellations", diagnostics)

    log10_nfa, tau, matched, tested = _significance((r @ points_m.T).T + t, points_f, exclude=builders)
    diagnostics.update(matched=matched, tested=tested, match_distance=tau, log10_nfa=log10_nfa)
    if log10_nfa >= 0:
        raise RegistrationFailed("no significant alignment: blob matches are consistent with chance", diagnostics)

    dist, nearest = cKDTree(points_f).query((r @ points_m.T).T + t)
    lined_up = dist < params["tol_inlier"]
    r, t, _, _ = _fit_rigid(points_m[lined_up], points_f[nearest[lined_up]], inlier_tol=params["tol_inlier"])
    pairs, r, t, resid = _nn_reassign(points_m, points_f, r, t, params["tol_nn"])

    k_physical = np.eye(4)
    k_physical[:3, :3], k_physical[:3, 3] = r, t
    k = np.diag([*1 / spacing_f, 1.0]) @ k_physical @ np.diag([*spacing_m, 1.0])
    k = _block_index(factors_f) @ k @ np.linalg.inv(_block_index(factors_m))
    rms = float(np.sqrt(np.mean(resid**2)))
    info = dict(
        matched=matched,
        tested=tested,
        log10_nfa=log10_nfa,
        refit_pairs=len(pairs),
        rms=rms,
        rms_voxels=rms / params["voxel"],
    )
    _report(1.0, "Registration complete.")
    logger.info("registration locked: %s", info)
    return k, info
