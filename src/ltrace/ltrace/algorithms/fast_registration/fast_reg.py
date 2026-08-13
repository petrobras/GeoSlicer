"""Rigid registration of paired microCT core volumes via bright-blob constellation matching.

Detects compact, high-attenuation inclusions ("blobs") in both volumes and matches them using a
3-D-distance affinity, which is invariant under arbitrary rotation (not just rotation about one
axis). Candidate correspondences are fit with RANSAC + Kabsch, then confirmed out-of-sample by
re-matching every blob under the candidate transform. A transform is only accepted if enough
independent blob correspondences agree on it at sub-voxel residual.

Public entry point: `register(fixed, moving) -> 4x4 index-space transform matrix`.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy import ndimage
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


# Mass-compatibility gate for a candidate blob correspondence, and the minimum affinity vote
# count for a mutual-best correspondence to be considered a candidate at all.
_MASS_RATIO = (0.2, 5.0)
_MIN_VOTE = 3
_RANSAC_ITERS = 2000

# Floors for the scale-derived parameters below: the small-N asymptote of irreducible
# blob-localization error (a mass-weighted centroid stays sub-voxel regardless of volume size)
# and the minimum safe count gates, so nothing becomes unsatisfiable on small volumes.
_FLOOR = dict(
    tol_dist=1.0, tol_inlier=1.5, tol_nn=0.75, max_residual=0.6, r_lo=8.0, min_inliers=8, seed_floor=4, min_blobs=12
)


def _inplane_size(shape):
    return 0.5 * (shape[1] + shape[2])


def _scale_params(fixed_shape, moving_shape, n0=1000.0):
    """Derive size-dependent thresholds from a characteristic size N (the smaller in-plane size
    of the two volumes), so the same tolerances work from ~250**3 to ~2000**3 volumes. Using the
    MIN (not mean) across the two volumes matters when one is a larger field of view at the same
    resolution: it keeps the tolerances tied to the volume with the (relatively) smaller blobs.

    Calibrated so N == n0 reproduces the fixed tolerances tuned on ~1000**3 reference volumes.
    """
    n = min(_inplane_size(fixed_shape), _inplane_size(moving_shape))
    s = n / n0
    pool = int(np.clip(round(4 * s), 1, 4))
    return dict(
        n=n,
        s=s,
        pool_factor=pool,
        tol_dist=max(2.0 * s, _FLOOR["tol_dist"]),
        tol_inlier=max(3.0 * s, _FLOOR["tol_inlier"]),
        tol_nn=max(1.5 * s, _FLOOR["tol_nn"]),
        max_residual=max(1.2 * s, _FLOOR["max_residual"]),
        r_lo=max(30.0 * s, _FLOOR["r_lo"]),
        min_inliers=max(int(round(15 * s)), _FLOOR["min_inliers"]),
        seed_floor=max(int(round(8 * s)), _FLOOR["seed_floor"]),
        min_blobs=max(int(round(20 * s)), _FLOOR["min_blobs"]),
    )


def _max_pool(volume, pool, workers=None, chunk_z=16, progress=None):
    """P x P x P max-pool of a (z, y, x) volume, parallelized over z-slabs. numpy's `.max`
    releases the GIL, so this scales close to linearly with core count on large volumes.

    `progress`, if given, is called with a fraction in (0, 1] as each z-slab completes. The
    ThreadPoolExecutor results are consumed on the calling thread, so `progress` runs there too.
    """
    if pool <= 1:
        if progress:
            progress(1.0)
        return np.ascontiguousarray(volume)
    nz, ny, nx = (d // pool * pool for d in volume.shape)
    workers = workers or min(16, os.cpu_count() or 4)
    out = np.empty((nz // pool, ny // pool, nx // pool), volume.dtype)

    def _reduce_slab(z0):
        z1 = min(z0 + chunk_z * pool, nz)
        reduced = (
            volume[z0:z1, :ny, :nx]
            .reshape((z1 - z0) // pool, pool, ny // pool, pool, nx // pool, pool)
            .max(axis=(1, 3, 5))
        )
        return z0 // pool, reduced

    slab_starts = list(range(0, nz, chunk_z * pool))
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool_exec:
        for z0_pooled, reduced in pool_exec.map(_reduce_slab, slab_starts):
            out[z0_pooled : z0_pooled + reduced.shape[0]] = reduced
            done += 1
            if progress:
                progress(done / len(slab_starts))
    return out


def _detect_blobs(volume, threshold, max_blobs, pool, progress=None):
    """Detect compact bright inclusions: max-pool -> threshold -> connected components ->
    full-resolution intensity-weighted centroid + mass per component. Returns the `max_blobs`
    most massive components as (points (N, 3) in (x, y, z) index coords, masses (N,)).

    `progress`, if given, is called with a fraction in (0, 1] over the course of detection.
    """
    # Max-pooling dominates detection time on large volumes; give it the bulk of the progress
    # budget, reserving the tail for labeling and the per-component centroid pass.
    pooled = _max_pool(volume, pool, progress=(lambda f: progress(0.8 * f)) if progress else None)
    if threshold is None:
        threshold = float(np.percentile(pooled, 99.9))
    labels, n_components = ndimage.label(pooled > threshold)
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
        mask = (box > threshold) & own
        if not mask.any():
            continue
        weights = box * mask
        zz, yy, xx = np.mgrid[z0 : z0 + box.shape[0], y0 : y0 + box.shape[1], x0 : x0 + box.shape[2]]
        total = weights.sum()
        if total <= 0:
            continue
        points.append(((xx * weights).sum() / total, (yy * weights).sum() / total, (zz * weights).sum() / total))
        masses.append(mask.sum())

    points, masses = np.array(points), np.array(masses, np.float32)
    order = np.argsort(masses)[::-1][:max_blobs]
    if progress:
        progress(1.0)
    logger.debug(
        "detected %d components above threshold=%.0f, kept top %d by mass", n_components, threshold, len(order)
    )
    return points[order], masses[order]


def _pair_table(points, r_lo, r_hi):
    """All point pairs with 3-D separation in (r_lo, r_hi). Returns (i, j, distance)."""
    ii, jj = np.triu_indices(len(points), 1)
    d = np.linalg.norm(points[jj] - points[ii], axis=1)
    keep = (d > r_lo) & (d < r_hi)
    return ii[keep], jj[keep], d[keep]


def _distance_affinity(pairs_m, pairs_f, n_m, n_f, mass_m, mass_f, tol):
    """Vote for blob-to-blob correspondences from distance-matched pairs.

    3-D distance is invariant under any rigid motion, so for each moving pair (a, b) every fixed
    pair at a matching separation votes for BOTH assignment orientations, (a~c, b~d) and
    (a~d, b~c), into an (n_m, n_f) affinity matrix, gated on blob-mass compatibility. A true
    correspondence accumulates a vote from every other true correspondence sharing that
    separation, so it stands out sharply from chance matches.
    """
    i_m, j_m, r_m = pairs_m
    i_f, j_f, r_f = pairs_f
    order = np.argsort(r_f)
    i_f, j_f, r_f = i_f[order], j_f[order], r_f[order]

    lo = np.searchsorted(r_f, r_m - tol, side="left")
    hi = np.searchsorted(r_f, r_m + tol, side="right")
    counts = hi - lo
    total = int(counts.sum())
    if total == 0:
        return np.zeros((n_m, n_f), np.float32)

    k_rep = np.repeat(np.arange(len(r_m)), counts)
    starts = np.cumsum(counts) - counts
    f_pos = np.repeat(lo, counts) + (np.arange(total) - np.repeat(starts, counts))
    a, b = i_m[k_rep], j_m[k_rep]
    c, d = i_f[f_pos], j_f[f_pos]

    r_min, r_max = _MASS_RATIO
    mass_a, mass_b = mass_m[a], mass_m[b]
    orient1 = (
        (mass_f[c] / mass_a > r_min)
        & (mass_f[c] / mass_a < r_max)
        & (mass_f[d] / mass_b > r_min)
        & (mass_f[d] / mass_b < r_max)
    )
    orient2 = (
        (mass_f[d] / mass_a > r_min)
        & (mass_f[d] / mass_a < r_max)
        & (mass_f[c] / mass_b > r_min)
        & (mass_f[c] / mass_b < r_max)
    )
    rows = np.concatenate([a[orient1], b[orient1], a[orient2], b[orient2]])
    cols = np.concatenate([c[orient1], d[orient1], d[orient2], c[orient2]])
    flat = np.bincount(rows.astype(np.int64) * n_f + cols, minlength=n_m * n_f)
    return flat.reshape(n_m, n_f).astype(np.float32)


def _mutual_candidates(affinity, min_votes):
    """Candidate one-to-one correspondences: (m, f) that are each other's best affinity match."""
    best_f_of_m = affinity.argmax(1)
    best_m_of_f = affinity.argmax(0)
    candidates = []
    for m in range(affinity.shape[0]):
        f = best_f_of_m[m]
        votes = affinity[m, f]
        if votes >= min_votes and best_m_of_f[f] == m:
            candidates.append((int(m), int(f), float(votes)))
    candidates.sort(key=lambda c: -c[2])
    return candidates


def _kabsch(a, b):
    """Closed-form rigid transform (R, t) minimizing sum ||R @ a_i + t - b_i||^2."""
    ca, cb = a.mean(0), b.mean(0)
    u, _, vt = np.linalg.svd((a - ca).T @ (b - cb))
    r = vt.T @ np.diag([1, 1, np.sign(np.linalg.det(vt.T @ u.T))]) @ u.T
    return r, cb - r @ ca


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


def _ransac_kabsch(points_m, points_f, candidates, tol, iters, rng=None):
    """RANSAC over candidate correspondences: sample 3, fit, count inliers within tol.
    Returns (inlier_index_into_candidates, R, t), or (None, None, None) if nothing is consistent.
    """
    if len(candidates) < 3:
        return None, None, None
    rng = rng or np.random.default_rng(0)
    a = np.array([points_m[m] for m, _, _ in candidates])
    b = np.array([points_f[f] for _, f, _ in candidates])
    n = len(candidates)
    best_inliers = None
    for _ in range(iters):
        sample = rng.choice(n, 3, replace=False)
        e1, e2 = a[sample[1]] - a[sample[0]], a[sample[2]] - a[sample[0]]
        if np.linalg.norm(np.cross(e1, e2)) < 1e-3:
            continue  # near-collinear triplet, degenerate for Kabsch
        r, t = _kabsch(a[sample], b[sample])
        resid = np.linalg.norm((r @ a.T).T + t - b, axis=1)
        inliers = resid < tol
        if best_inliers is None or inliers.sum() > best_inliers.sum():
            best_inliers = inliers
    if best_inliers is None or best_inliers.sum() < 3:
        return None, None, None
    r, t = _kabsch(a[best_inliers], b[best_inliers])
    return np.where(best_inliers)[0], r, t


def _nn_reassign(points_m, points_f, r, t, tol):
    """Out-of-sample confirmation: transform ALL moving blobs by (R, t) and greedily match each
    to its nearest fixed blob within `tol` (closest first, one-to-one), then refit Kabsch on the
    harvested pairs. Single pass (no ICP iteration), so the resulting count is an honest test of
    the RANSAC transform against blobs that did not build it.
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


def register(fixed, moving, *, max_blobs=400, n0=1000.0, progress_callback=None):
    """Compute the rigid transform mapping `moving` index coordinates onto `fixed` index
    coordinates.

    Both `fixed` and `moving` are (z, y, x) volumes on the same voxel grid/spacing, containing a
    shared set of compact, high-attenuation inclusions visible in both scans.

    Returns the 4x4 transform K such that, for a moving index coordinate p = (x, y, z, 1), `K @ p`
    is the corresponding fixed index coordinate.

    `progress_callback`, if given, is called as `progress_callback(fraction, message)` with
    `fraction` in [0, 1] and a human-readable stage message, so a caller can drive a progress bar
    without this module depending on any UI. It is never called from a background thread.

    Raises RegistrationFailed if no geometrically consistent transform is found; its
    `.diagnostics` dict carries the detection/matching counts for troubleshooting. Enable
    `logging.getLogger("fast_reg").setLevel(logging.DEBUG)` for detection details.
    """

    def _report(fraction, message):
        if progress_callback:
            progress_callback(fraction, message)

    params = _scale_params(fixed.shape, moving.shape, n0=n0)
    pool = params["pool_factor"]

    _report(0.0, "Detecting features in fixed volume...")
    points_f, mass_f = _detect_blobs(
        fixed,
        None,
        max_blobs,
        pool,
        progress=(lambda f: _report(0.4 * f, "Detecting features in fixed volume...")) if progress_callback else None,
    )
    _report(0.4, "Detecting features in moving volume...")
    points_m, mass_m = _detect_blobs(
        moving,
        None,
        max_blobs,
        pool,
        progress=(lambda f: _report(0.4 + 0.4 * f, "Detecting features in moving volume..."))
        if progress_callback
        else None,
    )
    if len(points_f) < params["min_blobs"] or len(points_m) < params["min_blobs"]:
        raise RegistrationFailed(
            "too few blobs detected in one or both volumes",
            dict(fixed_blobs=len(points_f), moving_blobs=len(points_m), min_blobs=params["min_blobs"]),
        )

    _report(0.8, "Matching features and verifying alignment...")
    r_hi = 0.7 * max(fixed.shape[1], fixed.shape[2])
    pairs_f = _pair_table(points_f, params["r_lo"], r_hi)
    pairs_m = _pair_table(points_m, params["r_lo"], r_hi)
    affinity = _distance_affinity(
        pairs_m, pairs_f, len(points_m), len(points_f), mass_m, mass_f, tol=params["tol_dist"]
    )
    candidates = _mutual_candidates(affinity, _MIN_VOTE)

    seed_idx, r, t = _ransac_kabsch(points_m, points_f, candidates, tol=params["tol_inlier"], iters=_RANSAC_ITERS)
    if seed_idx is None:
        raise RegistrationFailed(
            "no RANSAC consensus among candidate correspondences", dict(candidates=len(candidates))
        )
    consensus = len(seed_idx)
    if consensus < params["seed_floor"]:
        raise RegistrationFailed(
            "RANSAC consensus too low to trust",
            dict(candidates=len(candidates), consensus=consensus, seed_floor=params["seed_floor"]),
        )

    a = np.array([points_m[m] for m, _, _ in candidates])[seed_idx]
    b = np.array([points_f[f] for _, f, _ in candidates])[seed_idx]
    r, t, _, _ = _fit_rigid(a, b, inlier_tol=params["tol_inlier"])

    pairs, r, t, resid = _nn_reassign(points_m, points_f, r, t, params["tol_nn"])
    inliers = len(pairs)
    mean_resid = float(resid.mean()) if len(resid) else float("inf")
    if inliers < params["min_inliers"] or mean_resid >= params["max_residual"]:
        raise RegistrationFailed(
            "no geometric lock: blob correspondences do not agree on one rigid transform",
            dict(
                consensus=consensus,
                inliers=inliers,
                residual=mean_resid,
                min_inliers=params["min_inliers"],
                max_residual=params["max_residual"],
            ),
        )

    k = np.eye(4)
    k[:3, :3], k[:3, 3] = r, t
    _report(1.0, "Registration complete.")
    logger.info("registration locked: %d inliers, residual %.2f vox", inliers, mean_resid)
    return k
