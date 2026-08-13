import os
import sys
import time
import numpy as np
import json
import psutil
import cv2
import dask.array as da
import ltrace.algorithms.feature_extraction as fe
from scipy.ndimage import gaussian_filter, binary_dilation
from sklearn.ensemble import RandomForestClassifier
import argparse
from dataclasses import dataclass
from pathlib import Path

from ltrace.interactive.seg_ipc import (
    InterprocessPaths,
    safe_save_npz,
    FeatureIndex,
    safe_dump_json,
    FEATURE_NAMES,
    compute_preview_factor,
)

SLEEP_TIME = 0.03

PREDICT_N_JOBS = 4
# Confidence margin (top class probability minus the runner-up) below which a
# preview pixel is flagged as "uncertain" in the annotation view. Pixels in this
# band are where the classifier is least sure and the most useful to annotate.
UNCERTAINTY_MARGIN = 0.5
# Cap on the number of annotated pixels used for training (subsampled deterministically beyond it)
TRAIN_MAX_SAMPLES = 200_000
# Cap on annotated pixels extracted through per-point patches (widely scattered annotations)
SPARSE_TRAIN_MAX = 10_000
# Tile size used to group annotated pixels when computing training features (2D lazy mode)
TRAIN_TILE_SIZE = 256
# Number of patches gathered per filtering pass when extracting sparse training features
MOSAIC_BATCH = 2048
# Full-resolution tile size for full-image 2D inference
FULL_INFERENCE_TILE = 1024
# Full-resolution region size up to which preview features are computed contiguously (exactly)
CONTIG_MAX_PIXELS = 4_000_000
# Truncate the contiguous-path gaussian kernels at 3 sigma instead of cv2's
# default 4 sigma. Measured ~1.4x faster on the large-sigma blurs at a small
# accuracy cost (~0.1 on a 0..255 scale). Set False to restore the exact
# 4-sigma kernels and compare segmentation outputs.
GAUSSIAN_TRUNCATE_3SIGMA = True

# 3D features are computed out-of-core: each feature is filtered in slabs along
# the volume's longest axis with a halo equal to the filter radius (so each slab
# reproduces the whole-volume result exactly), and every slab is streamed straight
# into its plane of the feature memmap. Peak memory is a bounded set of haloed
# slabs rather than several full-volume float32 intermediates, so it no longer
# grows with the volume size or the number of features. These two knobs trade
# parallelism against that peak working set.
FEATURE_SLAB_BYTES = 32 * 1024 * 1024  # target core-slab size, excluding halo
FEATURE_MEM_BUDGET_BYTES = 1024 * 1024 * 1024  # cap on the concurrent working set

# Base (1x) feature kernel sizes, tuned for typical microCT. A hi-res thin
# section whose structures span many more pixels needs proportionally larger
# kernels for the same semantics; the session "feature scale" multiplier (1/2/4)
# scales these (see FeatureScale).
BASE_GAUSSIAN_SIGMAS = {
    FeatureIndex.GAUSSIAN_A: 1,
    FeatureIndex.GAUSSIAN_B: 2,
    FeatureIndex.GAUSSIAN_C: 4,
    FeatureIndex.GAUSSIAN_D: 8,
}

BASE_WINVAR_SIZES = {
    FeatureIndex.WINVAR_A: 5,
    FeatureIndex.WINVAR_B: 9,
    FeatureIndex.WINVAR_C: 13,
}


def _odd(value):
    """Nearest odd integer >= 3 (window-variance boxes must be odd-sized)."""
    n = max(3, int(round(value)))
    return n if n % 2 else n + 1


@dataclass
class FeatureScale:
    """
    The feature-kernel layout for one session, derived once from the scale
    multiplier and passed explicitly to every feature function. This replaces the
    former module-global kernel tables (rewritten in place by a setup call), so
    the kernel sizes are immutable session data with no hidden temporal coupling:
    nothing depends on a global being set "earlier and elsewhere", and two scales
    can coexist in one process (a second image, a unit test) without one silently
    computing with the other's kernels.

    Gaussian sigmas scale linearly; window sizes scale and snap to odd. Each large
    gaussian is mapped to the pyramid level whose 2x2-mean decimation leaves only a
    small residual blur (~floor(log2 sigma)), and the pyramid is built deep enough
    for the largest one. The smallest gaussian stays on the exact sampled-feature
    path (it is the one _sampled_features_2d evaluates exactly as GAUSSIAN_A). At
    scale 1 these reproduce the original constants.
    """

    multiplier: int
    gaussian_sigmas: dict  # FeatureIndex -> sigma
    winvar_sizes: dict  # FeatureIndex -> odd window size
    gaussian_pyramid_level: dict  # large gaussian FeatureIndex -> pyramid level it is approximated on
    pyramid_levels: int  # mean-pyramid depth; raised for large scales
    definitions: dict  # FeatureIndex -> calc_func(array) for the 3D/inference precompute

    @classmethod
    def from_multiplier(cls, multiplier):
        gaussian_sigmas = {f: s * multiplier for f, s in BASE_GAUSSIAN_SIGMAS.items()}
        winvar_sizes = {f: _odd(w * multiplier) for f, w in BASE_WINVAR_SIZES.items()}

        smallest_gaussian = min(gaussian_sigmas, key=gaussian_sigmas.get)
        gaussian_pyramid_level = {
            f: max(1, int(np.floor(np.log2(s)))) for f, s in gaussian_sigmas.items() if f != smallest_gaussian
        }
        pyramid_levels = max([3, *gaussian_pyramid_level.values()])

        definitions = {
            FeatureIndex.SOURCE: lambda arr: arr,
            **{f: (lambda arr, s=s: gaussian_filter(arr, sigma=s)) for f, s in gaussian_sigmas.items()},
            **{f: (lambda arr, w=w: fe.win_var_3d(arr, w)) for f, w in winvar_sizes.items()},
        }
        return cls(multiplier, gaussian_sigmas, winvar_sizes, gaussian_pyramid_level, pyramid_levels, definitions)

    def halo(self, feature_enum):
        """
        Halo (in voxels) a slab must overlap its neighbors by so the filter sees
        the same neighborhood it would over the whole volume: the gaussian kernel
        radius (scipy's truncate=4) or the window-variance half-window. SOURCE
        needs none.
        """
        if feature_enum in self.gaussian_sigmas:
            return int(4 * self.gaussian_sigmas[feature_enum] + 0.5)
        if feature_enum in self.winvar_sizes:
            return self.winvar_sizes[feature_enum] // 2
        return 0

    def margin(self, feature_indices):
        """
        Margin (in sample pixels) covering the support of every selected filter,
        so a pixel that is at least this far from the sample border gets the same
        feature values it would get if the whole image had been filtered.
        """
        margin = 1
        for index in feature_indices:
            feature = FeatureIndex(index)
            if feature in self.gaussian_sigmas:
                # cv2.GaussianBlur derives its kernel radius as 4*sigma for float inputs
                margin = max(margin, 4 * self.gaussian_sigmas[feature] + 1)
            elif feature in self.winvar_sizes:
                margin = max(margin, self.winvar_sizes[feature] // 2 + 1)
        return margin


def feature_display_name(feature, scale=1):
    """
    Human-readable feature name with kernel sizes scaled by `scale`, for the UI
    feature list. Derived from the base sizes the same way FeatureScale derives
    the active kernels, so the displayed text matches what the consumer actually
    computes at that scale.
    """
    if feature in BASE_GAUSSIAN_SIGMAS:
        return f"Gaussian Filter (sigma={BASE_GAUSSIAN_SIGMAS[feature] * scale})"
    if feature in BASE_WINVAR_SIZES:
        return f"Window Variance (size {_odd(BASE_WINVAR_SIZES[feature] * scale)})"
    return FEATURE_NAMES[feature]


def update_progress(path, progress, message):
    print(f"[{os.getpid()}] Progress {progress}%: {message}", flush=True)
    safe_dump_json({"progress": progress, "message": message}, path)


def _uncertainty_mask_from_proba(proba):
    """
    Binary mask (1 = uncertain) flagging samples where the random forest's two
    most probable classes are within UNCERTAINTY_MARGIN of each other. A small
    gap between the top two classes means the classifier could not commit to a
    label, so these are the pixels most worth annotating next.
    """
    if proba.shape[1] < 2:
        return np.zeros(proba.shape[0], dtype=np.uint8)
    top2 = np.partition(proba, -2, axis=1)[:, -2:]
    margin = top2[:, 1] - top2[:, 0]
    return (margin < UNCERTAINTY_MARGIN).astype(np.uint8)


def _make_model(n_jobs):
    return RandomForestClassifier(
        n_estimators=64,
        n_jobs=n_jobs,
        warm_start=False,
        random_state=42,
        bootstrap=True,
        oob_score=True,
        min_impurity_decrease=0.001,
        class_weight="balanced",
    )


# ---------------------------------------------------------------------------
# 3D mode: all features are precomputed over the full volume into a memory map
# ---------------------------------------------------------------------------


def _max_worker_threads():
    """
    Cap on worker threads for feature computation: one fewer than the number of
    PHYSICAL cores, so a full-volume parallel filter always leaves a core for the
    OS/UI and never freezes the desktop. Uses physical (not logical) cores because
    these filters are compute-bound and gain nothing from hyperthreads while still
    competing for them. Falls back conservatively when the count is unavailable.
    """
    physical = psutil.cpu_count(logical=False) or os.cpu_count() or 2
    return max(1, physical - 1)


def _filter_into_plane(channel_array, calc_func, halo, out_plane):
    """
    Filter a single 3D channel out-of-core and stream the result into `out_plane`
    (a writable view of the feature memmap, shape K, J, I). The array is chunked
    into slabs along its longest axis with `halo` overlap on that axis only -- the
    other two axes stay full-width, so no interior boundary is introduced and the
    slabbed result is identical (bit-for-bit) to filtering the whole volume at
    once. dask runs the slabs across threads (the scipy filters release the GIL),
    and the worker count is capped so the concurrent haloed working set stays
    within FEATURE_MEM_BUDGET_BYTES regardless of volume size or feature count.

    Features are NOT rescaled: the random forest splits on per-feature thresholds,
    so a feature's absolute range is irrelevant, and training and prediction read
    the same raw planes -- exactly as the 2D lazy path already operates.
    """
    channel_array = np.asarray(channel_array)
    axis = int(np.argmax(channel_array.shape))
    n = channel_array.shape[axis]
    plane_bytes = (channel_array.size // n) * 4

    chunk_len = max(halo + 1, FEATURE_SLAB_BYTES // plane_bytes)
    if chunk_len >= n:
        # Whole volume fits in one slab (or the kernel is too large to slab):
        # filter it directly and skip the dask machinery.
        out_plane[...] = np.asarray(calc_func(channel_array), dtype=np.float32)
        return

    # Explicit slab sizes along `axis`, all >= halo+1 (map_overlap requires every
    # chunk to be at least the overlap depth): fold any short final remainder back
    # into the previous slab rather than leaving an undersized chunk.
    sizes = [chunk_len] * (n // chunk_len)
    rem = n - chunk_len * len(sizes)
    if rem:
        if rem >= halo + 1:
            sizes.append(rem)
        else:
            sizes[-1] += rem

    haloed_bytes = (max(sizes) + 2 * halo) * plane_bytes  # ~4 working copies per slab
    workers = max(1, min(int(FEATURE_MEM_BUDGET_BYTES // (haloed_bytes * 4)), _max_worker_threads()))

    chunks = tuple(tuple(sizes) if i == axis else channel_array.shape[i] for i in range(channel_array.ndim))
    depth = {i: (halo if i == axis else 0) for i in range(channel_array.ndim)}
    darr = da.from_array(channel_array, chunks=chunks)
    filtered = darr.map_overlap(
        lambda block: np.asarray(calc_func(block), dtype=np.float32),
        depth=depth,
        boundary="reflect",
        dtype=np.float32,
    )
    da.store(filtered, out_plane, scheduler="threads", num_workers=workers)


def _calculate_features(source_array, mmap_path, scale, progress_callback, feature_indices_to_calc=None):
    """
    Calculates features into a compacted memory-mapped file of shape
    (n_channels, n_requested_features, K, J, I), where plane [:, i] holds the
    i-th requested feature. Used for the inference image, whose features are all
    consumed (prediction passes feature_indices=None). The main session uses the
    staged helpers below, which keep the full global layout.
    """
    progress_callback(0, "Starting feature calculation...")

    all_feature_enums = list(FeatureIndex)

    if feature_indices_to_calc is None:
        features_to_process = all_feature_enums
    else:
        features_to_process = [fi for fi in all_feature_enums if fi.value in feature_indices_to_calc]

    num_to_calc = len(features_to_process)
    n_channels = source_array.shape[3] if source_array.ndim == 4 else 1
    spatial_shape = source_array.shape[:3]

    mmap_shape = (n_channels, num_to_calc) + spatial_shape
    features_mmap = np.memmap(mmap_path, dtype=np.float32, mode="w+", shape=mmap_shape)
    print(f"[{os.getpid()}] Created memory-mapped file at {mmap_path} with shape {mmap_shape}", flush=True)

    progress_step = 90 / (num_to_calc * n_channels)
    current_progress = 0

    for i, feature_enum in enumerate(features_to_process):
        calc_func = scale.definitions[feature_enum]
        halo = scale.halo(feature_enum)
        for channel in range(n_channels):
            channel_array = source_array[..., channel] if source_array.ndim == 4 else source_array
            _filter_into_plane(channel_array, calc_func, halo, features_mmap[channel, i])

            current_progress += progress_step
            progress_callback(int(current_progress), f"{FEATURE_NAMES[feature_enum]} done")

    features_mmap.flush()
    progress_callback(100, "Features calculated and saved to disk.")
    return features_mmap


def _allocate_feature_mmap(source_array, mmap_path):
    """
    Allocate the full-layout feature memmap for the main session, of shape
    (n_channels, n_features, K, J, I) with one plane per (channel, feature) for
    ALL features, so each feature lands at the fixed index [:, feature.value]
    regardless of when it is computed. This lets features be filled in stages and
    in any order while the layout the trainer/predictor relies on stays fixed.
    """
    n_channels = source_array.shape[3] if source_array.ndim == 4 else 1
    spatial_shape = source_array.shape[:3]
    mmap_shape = (n_channels, len(FeatureIndex)) + spatial_shape
    features_mmap = np.memmap(mmap_path, dtype=np.float32, mode="w+", shape=mmap_shape)
    print(f"[{os.getpid()}] Created memory-mapped file at {mmap_path} with shape {mmap_shape}", flush=True)
    return features_mmap, n_channels


def _compute_feature_planes(source_array, features_mmap, n_channels, feature_enums, scale, progress_callback=None):
    """
    Compute `feature_enums` into their fixed planes of `features_mmap` (feature f
    at [:, f.value]). Each feature is written independently, so the
    remaining-feature pass may run in a background thread while the main loop
    trains/predicts on the features already filled.
    """
    total = len(feature_enums) * n_channels
    done = 0
    for feature_enum in feature_enums:
        calc_func = scale.definitions[feature_enum]
        halo = scale.halo(feature_enum)
        for channel in range(n_channels):
            channel_array = source_array[..., channel] if source_array.ndim == 4 else source_array
            _filter_into_plane(channel_array, calc_func, halo, features_mmap[channel, feature_enum.value])
            done += 1
            if progress_callback:
                progress_callback(int(100 * done / total), f"{FEATURE_NAMES[feature_enum]} done")
    features_mmap.flush()


def _train_model(features, paths, feature_indices, is_full_inference):
    print(f"[{os.getpid()}] Loading annotation data...", flush=True)
    training_data = np.load(paths.annotation)

    y_train = training_data[0, :].astype(np.uint8)
    i_coords, j_coords, k_coords = training_data[1:4, :].astype(int)

    # features is (n_channels, n_features, K, J, I). Sample the annotated voxels
    # (mmap reads only those from disk), keep the selected features, then flatten
    # (channel, feature) into one column per pair so each row is a voxel's vector.
    sampled = features[:, :, k_coords, j_coords, i_coords]  # (n_channels, n_features, n_samples)
    sampled = sampled[:, feature_indices, :]  # (n_channels, n_selected, n_samples)
    X_train = sampled.reshape(-1, sampled.shape[2]).T  # (n_samples, n_channels * n_selected)

    print(f"[{os.getpid()}] Training data shape: {X_train.shape}, y_train shape: {y_train.shape}", flush=True)
    print(f"[{os.getpid()}] Training RandomForest on {len(y_train)} samples...", flush=True)

    n_jobs = 4 if is_full_inference else 1
    start = time.perf_counter()
    model = _make_model(n_jobs)
    model.fit(X_train, y_train)
    safe_dump_json({"is_trained": True}, paths.model_status)
    print(f"[{os.getpid()}] Model trained in {time.perf_counter() - start:.4f} seconds", flush=True)
    return model


def _predict_and_save(
    model, features, current_shape, extents, feature_indices, paths, compute_uncertainty=False, capture=None
):
    print(f"[{os.getpid()}] Predicting on the extents area...", flush=True)
    i_min, i_max, j_min, j_max, k_min, k_max = extents

    mask_zyx = np.zeros(current_shape, dtype=bool)
    mask_zyx[k_min:k_max, j_min:j_max, i_min:i_max] = True

    # features is (n_channels, n_features, K, J, I). Pick the voxels in the extent,
    # then flatten (channel, feature) into one column per pair (same order as
    # _train_model) so each row is a voxel's feature vector.
    n_channels, n_features = features.shape[0], features.shape[1]
    voxel_features = features.reshape(n_channels, n_features, -1)[:, :, mask_zyx.ravel()]

    # feature_indices is None only for the inference-image apply: its compacted
    # mmap already holds exactly the selected features, so there is nothing to
    # sub-select. The interactive/main-session path passes the sorted subset.
    if feature_indices is not None:
        voxel_features = voxel_features[:, feature_indices, :]
    X_predict = voxel_features.reshape(-1, voxel_features.shape[2]).T
    print(f"[{os.getpid()}] Extracted {X_predict.shape[0]} samples for prediction.", flush=True)

    uncertainty_labelmap = None
    if X_predict.shape[0] > 0:
        start = time.perf_counter()
        extent_shape = (k_max - k_min, j_max - j_min, i_max - i_min)
        if compute_uncertainty:
            # predict() computes the same per-tree proba internally, so deriving
            # the label from predict_proba costs nothing extra and gives us the
            # uncertainty map for free.
            proba = model.predict_proba(X_predict)
            predictions_flat = model.classes_[np.argmax(proba, axis=1)]
            uncertainty_labelmap = _uncertainty_mask_from_proba(proba).reshape(extent_shape)
        else:
            predictions_flat = model.predict(X_predict)
        result_labelmap = predictions_flat.reshape(extent_shape)
        print(f"[{os.getpid()}] Predictions made in {time.perf_counter() - start:.4f} seconds", flush=True)
    else:
        print(f"[{os.getpid()}] No data to predict within extents. Writing empty result.", flush=True)
        result_labelmap = np.array([], dtype=np.uint8)

    if capture is not None and result_labelmap.size > 0:
        _capture_preview_3d(capture, features, feature_indices, extents, result_labelmap, uncertainty_labelmap)
        safe_save_npz(paths.debug_capture, **capture)
        print(f"[{os.getpid()}] Debug capture written to {paths.debug_capture}", flush=True)

    print(f"[{os.getpid()}] Saving result labelmap of shape {result_labelmap.shape}", flush=True)
    start = time.perf_counter()
    extra = {} if uncertainty_labelmap is None else {"uncertainty": uncertainty_labelmap.astype(np.uint8)}
    safe_save_npz(paths.result, result=result_labelmap.astype(np.uint8), extents=extents, factor=1, **extra)
    print(f"[{os.getpid()}] Result saved in {time.perf_counter() - start:.4f} seconds", flush=True)


def _capture_preview_3d(capture, features, feature_indices, extents, result_labelmap, uncertainty_labelmap):
    """
    Fill `capture` with the data the 3D debug report shows: for the previewed
    plane (the 3D preview always covers a single K slice -- the slice the user is
    viewing), the feature plane of every selected feature (one per channel) and
    the predicted/uncertainty labelmaps. Only this plane is stored, not the whole
    volume, so the capture stays small.

    Feature planes are laid out feature-major / channel-minor and stored under the
    same keys the 2D capture uses ("features"/"result"/"uncertainty"), so the
    renderer reuses the 2D page layout (minus the whole-image overview).
    """
    n_channels = features.shape[0]
    K, J, I = features.shape[2], features.shape[3], features.shape[4]
    i_min, i_max, j_min, j_max, k_min, k_max = extents
    i0, i1 = max(0, i_min), min(I, i_max)
    j0, j1 = max(0, j_min), min(J, j_max)
    kmid = min(max(0, (k_min + k_max) // 2), K - 1)

    capture["n_channels"] = n_channels

    planes = []
    for index in feature_indices:
        for channel in range(n_channels):
            planes.append(np.asarray(features[channel, index, kmid, j0:j1, i0:i1], dtype=np.float32))
    capture["features"] = np.stack(planes, axis=0)

    # The labelmaps are extent-local and span a single K slice; take its middle
    # plane (length 1 along the first axis in normal use).
    capture["result"] = np.asarray(result_labelmap[result_labelmap.shape[0] // 2], dtype=np.uint8)
    if uncertainty_labelmap is not None:
        capture["uncertainty"] = np.asarray(uncertainty_labelmap[uncertainty_labelmap.shape[0] // 2], dtype=np.uint8)


def _handle_task(task_params, paths, model, features, original_shape, scale):
    action = task_params["action"]
    is_full_inference = task_params.get("is_full_inference", False)
    feature_indices = task_params.get("features")
    # Sort so the feature column order is identical between training and the
    # full-image apply: _calculate_features lays its compacted inference mmap out
    # in FeatureIndex order, while training selects features in feature_indices
    # order -- these agree only if feature_indices is sorted. The 2D path sorts
    # likewise. feature_indices is None only for the "write_empty" action, which
    # carries no features and returns before any feature selection.
    if feature_indices is not None:
        feature_indices = sorted(feature_indices)

    current_features = features
    current_shape = original_shape
    predict_feature_indices = feature_indices

    # Handle inference on a different source image
    if paths.inference_source.exists():
        print(f"[{os.getpid()}] Inference source found. Calculating features for it.", flush=True)
        inference_source_array = np.load(paths.inference_source)
        paths.inference_source.unlink()

        def progress(p, m):
            update_progress(paths.progress, round(p * 0.4), m)

        # Use a temporary mmap file and calculate ONLY the required features
        inference_mmap_path = paths.features_mmap.with_suffix(".inference.mmap")
        current_features = _calculate_features(
            inference_source_array, inference_mmap_path, scale, progress, feature_indices_to_calc=feature_indices
        )
        current_shape = inference_source_array.shape[:3]
        # All features in the mmap file are used for prediction, so we pass None
        predict_feature_indices = None
        update_progress(paths.progress, 50, "Running inference on the full image...")

    if action == "write_empty":
        print(f"[{os.getpid()}] No training data available. Writing empty result.", flush=True)
        result_labelmap = np.zeros(current_shape, dtype=np.uint8)
        extents = np.array([0, current_shape[2], 0, current_shape[1], 0, current_shape[0]])
        safe_save_npz(paths.result, result=result_labelmap, extents=extents, factor=1)
        safe_dump_json({"is_trained": False}, paths.model_status)
        return None  # Reset model

    if action == "train":
        # Training is always done on the original features cache
        model = _train_model(features, paths, feature_indices, is_full_inference)

    if model is None:
        print(f"[{os.getpid()}] Model not trained yet. Skipping prediction.", flush=True)
        return None

    extents = task_params["extents"]

    # A debug request runs the normal preview prediction with a capture sink, so
    # the report reflects production behavior. Only the interactive preview path
    # captures (the inference-image apply rebinds predict_feature_indices to None,
    # and the full apply carries no debug flag).
    capture = None
    if task_params.get("debug") and not is_full_inference and predict_feature_indices is not None:
        capture = {
            "is_3d": True,
            "feature_names": json.dumps(
                [feature_display_name(FeatureIndex(i), scale.multiplier) for i in predict_feature_indices]
            ),
            "feature_scale": scale.multiplier,
            "extents": np.asarray(extents),
        }
        if task_params.get("image_channels"):
            capture["image_channels"] = np.asarray(task_params["image_channels"], dtype=np.int32)
            capture["image_names"] = json.dumps(task_params.get("image_names", []))

    _predict_and_save(
        model,
        current_features,
        current_shape,
        extents,
        predict_feature_indices,
        paths,
        compute_uncertainty=not is_full_inference,
        capture=capture,
    )

    if is_full_inference:
        update_progress(paths.progress, 100, "Full segmentation complete.")

    return model


# ---------------------------------------------------------------------------
# 2D lazy mode: features are calculated on demand instead of being precomputed
# over the whole image, so very large images (e.g. 100k-pixel thin sections)
# get near-instantaneous preview updates.
#
# The preview OUTPUT is downsampled (one prediction per stride-`factor` pixel),
# but every feature keeps FULL-RESOLUTION semantics regardless of the factor:
# window variances, the sigma-1 gaussian and the raw value are computed exactly
# from the full-resolution neighborhood of each sampled pixel, and the larger
# gaussians are approximated from a mean pyramid. A single model therefore
# serves every zoom level and the full-image apply, and the preview is a
# subsampled view of the final result rather than a rescaled reinterpretation
# of it. This matters because rock textures are scale-dependent: features
# computed on a decimated image would alias and could classify very
# differently from the final full-resolution segmentation.
# ---------------------------------------------------------------------------


def _gaussian_ksize(sigma):
    """
    Kernel size for cv2.GaussianBlur at `sigma`. Returns an explicit 3-sigma
    kernel when GAUSSIAN_TRUNCATE_3SIGMA is set, otherwise (0, 0) so cv2 derives
    its default 4-sigma kernel (the exact, slower behavior).
    """
    if not GAUSSIAN_TRUNCATE_3SIGMA:
        return (0, 0)
    radius = max(1, int(round(3 * sigma)))
    size = 2 * radius + 1
    return (size, size)


def _compute_features_2d(sample, feature_indices, scale):
    """
    Compute the selected features over a 2D sample of shape (h, w) or (h, w, c).
    Multi-channel (e.g. RGB) inputs produce one feature plane per channel.
    Returns a float32 array of shape (n_feature_planes, h, w).

    Values are NOT rescaled: samples are computed independently for training and
    for each preview update, so any normalization based on per-sample statistics
    would make them inconsistent. Random forests do not require normalized
    features (the 3D path likewise stores raw filter outputs).
    """
    if sample.ndim == 2:
        sample = sample[:, :, np.newaxis]
    sample = np.ascontiguousarray(sample, dtype=np.float32)

    # The squared image is shared across every window-variance size (and `sample`
    # is already contiguous float32), so compute it once instead of letting each
    # fe.win_var call redo the cast and the squaring.
    sample_sq = None
    # Cascade state for the gaussians: blurring with sigma_a then sigma_b equals
    # blurring once with sqrt(sigma_a**2 + sigma_b**2). Selected sigmas are
    # visited in increasing order (FeatureIndex order matches sigma order), so
    # each larger gaussian is one small incremental blur on top of the previous
    # result rather than a large-kernel blur of the raw sample.
    gauss_running = None
    gauss_prev_sigma = 0.0

    planes = []
    for index in sorted(feature_indices):
        feature = FeatureIndex(index)
        if feature == FeatureIndex.SOURCE:
            result = sample
        elif feature in scale.gaussian_sigmas:
            sigma = scale.gaussian_sigmas[feature]
            incremental_sigma = np.sqrt(sigma * sigma - gauss_prev_sigma * gauss_prev_sigma)
            base = sample if gauss_running is None else gauss_running
            ksize = _gaussian_ksize(incremental_sigma)
            gauss_running = cv2.GaussianBlur(base, ksize, sigmaX=incremental_sigma, sigmaY=incremental_sigma)
            gauss_prev_sigma = sigma
            result = gauss_running
        elif feature in scale.winvar_sizes:
            if sample_sq is None:
                sample_sq = sample * sample
            wlen = scale.winvar_sizes[feature]
            wmean = cv2.boxFilter(sample, -1, (wlen, wlen), borderType=cv2.BORDER_REFLECT)
            wsqmean = cv2.boxFilter(sample_sq, -1, (wlen, wlen), borderType=cv2.BORDER_REFLECT)
            result = wsqmean - wmean * wmean
        else:
            raise ValueError(f"Unsupported feature: {feature}")

        if result.ndim == 2:
            result = result[:, :, np.newaxis]
        for channel in range(result.shape[2]):
            planes.append(np.asarray(result[:, :, channel], dtype=np.float32))

    return np.stack(planes, axis=0)


def _gather_patch_features(source, i_points, j_points, feature_indices, margin, scale):
    """
    Full-resolution feature vectors at sparse pixels: gather one (2*margin+1)^2
    patch per pixel, stack the patches into one tall mosaic, filter it once,
    and read each patch center. The patch radius covers every filter's support,
    so centers are unaffected by neighboring patches in the mosaic.
    """
    height, width = source.shape[1], source.shape[2]
    image = source[0]
    patch = 2 * margin + 1
    offsets = np.arange(patch) - margin

    n_channels = source.shape[3] if source.ndim == 4 else 1
    X = np.empty((i_points.size, len(feature_indices) * n_channels), dtype=np.float32)

    for start in range(0, i_points.size, MOSAIC_BATCH):
        batch_i = i_points[start : start + MOSAIC_BATCH]
        batch_j = j_points[start : start + MOSAIC_BATCH]

        cols = np.clip(batch_i[:, np.newaxis] + offsets, 0, width - 1)
        rows = np.clip(batch_j[:, np.newaxis] + offsets, 0, height - 1)
        patches = image[rows[:, :, np.newaxis], cols[:, np.newaxis, :]]  # (n, patch, patch[, c])

        mosaic = patches.reshape((batch_i.size * patch,) + patches.shape[2:])
        features = _compute_features_2d(mosaic, feature_indices, scale)

        center_rows = margin + np.arange(batch_i.size) * patch
        X[start : start + MOSAIC_BATCH] = features[:, center_rows, margin].T

    return X


def _training_features_2d(source, annotation, feature_indices, scale, subsample=True):
    """
    Compute full-resolution feature vectors at annotated pixels without touching
    the rest of the image. Annotated pixels are grouped into tiles; dense tiles
    are filtered as a single sample around the points' bounding box, while
    sparse points are gathered into per-point patches. Both use the exact
    filters, so training matches the full-image apply exactly.

    With `subsample` (the default, used for interactive previews) the annotation
    set is capped for speed; the final full-image apply passes subsample=False to
    train on every annotated pixel.
    """
    height, width = source.shape[1], source.shape[2]

    labels = annotation[0, :].astype(np.uint8)
    i_points = np.clip(annotation[1, :].astype(np.int64), 0, width - 1)
    j_points = np.clip(annotation[2, :].astype(np.int64), 0, height - 1)

    if subsample and labels.size > TRAIN_MAX_SAMPLES:
        rng = np.random.default_rng(42)
        selection = rng.choice(labels.size, TRAIN_MAX_SAMPLES, replace=False)
        labels, i_points, j_points = labels[selection], i_points[selection], j_points[selection]

    margin = scale.margin(feature_indices)
    patch_area = (2 * margin + 1) ** 2

    tiles_per_row = width // TRAIN_TILE_SIZE + 1
    tile_ids = (j_points // TRAIN_TILE_SIZE) * tiles_per_row + (i_points // TRAIN_TILE_SIZE)
    order = np.argsort(tile_ids, kind="stable")
    unique_tiles, group_starts = np.unique(tile_ids[order], return_index=True)
    group_bounds = np.append(group_starts, tile_ids.size)

    X_train = None
    keep = np.ones(labels.size, dtype=bool)
    sparse_selections = []
    for tile_index in range(unique_tiles.size):
        selection = order[group_bounds[tile_index] : group_bounds[tile_index + 1]]
        tile_i, tile_j = i_points[selection], j_points[selection]

        i_min, i_max = tile_i.min(), tile_i.max()
        j_min, j_max = tile_j.min(), tile_j.max()
        bbox_cost = (i_max - i_min + 1 + 2 * margin) * (j_max - j_min + 1 + 2 * margin)
        if selection.size * patch_area < bbox_cost:
            sparse_selections.append(selection)
            continue

        si0, sj0 = max(0, i_min - margin), max(0, j_min - margin)
        si1, sj1 = min(width, i_max + margin + 1), min(height, j_max + margin + 1)

        sample = np.asarray(source[0, sj0:sj1, si0:si1])
        features = _compute_features_2d(sample, feature_indices, scale)

        if X_train is None:
            X_train = np.empty((labels.size, features.shape[0]), dtype=np.float32)

        X_train[selection] = features[:, tile_j - sj0, tile_i - si0].T

    if sparse_selections:
        selection = np.concatenate(sparse_selections)
        if subsample and selection.size > SPARSE_TRAIN_MAX:
            print(
                f"[{os.getpid()}] Subsampling {selection.size} scattered annotated pixels to {SPARSE_TRAIN_MAX}.",
                flush=True,
            )
            rng = np.random.default_rng(42)
            keep[selection] = False
            selection = selection[rng.choice(selection.size, SPARSE_TRAIN_MAX, replace=False)]
            keep[selection] = True
        X_sparse = _gather_patch_features(
            source, i_points[selection], j_points[selection], feature_indices, margin, scale
        )
        if X_train is None:
            X_train = np.empty((labels.size, X_sparse.shape[1]), dtype=np.float32)
        X_train[selection] = X_sparse

    if not keep.all():
        X_train, labels = X_train[keep], labels[keep]
    return X_train, labels


def _training_regions_2d(source, annotation, feature_indices, scale):
    """
    Geometry-only mirror of _training_features_2d: returns the regions whose
    features it WOULD compute to train the preview model, without doing any
    filtering. Used by the debug report to show every area touched for training,
    including annotations far outside the current preview region. Mirrors the
    subsample=True (interactive) path that trains the cached preview model.

    Returns (dense_bboxes, sparse_i, sparse_j, margin): dense tiles filtered as
    one bounding-box sample, plus the centers of the per-point sparse patches
    (each covering +/- margin pixels).
    """
    height, width = source.shape[1], source.shape[2]
    i_points = np.clip(annotation[1, :].astype(np.int64), 0, width - 1)
    j_points = np.clip(annotation[2, :].astype(np.int64), 0, height - 1)

    if i_points.size > TRAIN_MAX_SAMPLES:
        rng = np.random.default_rng(42)
        selection = rng.choice(i_points.size, TRAIN_MAX_SAMPLES, replace=False)
        i_points, j_points = i_points[selection], j_points[selection]

    margin = scale.margin(feature_indices)
    patch_area = (2 * margin + 1) ** 2

    tiles_per_row = width // TRAIN_TILE_SIZE + 1
    tile_ids = (j_points // TRAIN_TILE_SIZE) * tiles_per_row + (i_points // TRAIN_TILE_SIZE)
    order = np.argsort(tile_ids, kind="stable")
    unique_tiles, group_starts = np.unique(tile_ids[order], return_index=True)
    group_bounds = np.append(group_starts, tile_ids.size)

    dense_bboxes = []
    sparse_selections = []
    for tile_index in range(unique_tiles.size):
        selection = order[group_bounds[tile_index] : group_bounds[tile_index + 1]]
        tile_i, tile_j = i_points[selection], j_points[selection]
        i_min, i_max = tile_i.min(), tile_i.max()
        j_min, j_max = tile_j.min(), tile_j.max()
        bbox_cost = (i_max - i_min + 1 + 2 * margin) * (j_max - j_min + 1 + 2 * margin)
        if selection.size * patch_area < bbox_cost:
            sparse_selections.append(selection)
            continue
        si0, sj0 = max(0, i_min - margin), max(0, j_min - margin)
        si1, sj1 = min(width, i_max + margin + 1), min(height, j_max + margin + 1)
        dense_bboxes.append((si0, si1, sj0, sj1))

    if sparse_selections:
        selection = np.concatenate(sparse_selections)
        if selection.size > SPARSE_TRAIN_MAX:
            rng = np.random.default_rng(42)
            selection = selection[rng.choice(selection.size, SPARSE_TRAIN_MAX, replace=False)]
        sparse_i, sparse_j = i_points[selection], j_points[selection]
    else:
        sparse_i = np.empty(0, dtype=np.int64)
        sparse_j = np.empty(0, dtype=np.int64)

    return dense_bboxes, sparse_i, sparse_j, margin


def _build_mean_pyramid(source, paths, scale, progress_callback=None):
    """
    2x2 mean pyramid (levels 1..scale.pyramid_levels) of the source image, stored
    as memory-mapped files. Used to evaluate the large-sigma gaussian features at
    sampled positions without reading their full-resolution neighborhoods.
    """
    image = source[0]
    pyramid = {}
    previous = image
    total_rows = sum(image.shape[0] // (2**level) for level in range(1, scale.pyramid_levels + 1))
    done_rows = 0
    dtype = np.uint8 if image.dtype == np.uint8 else np.float32
    for level in range(1, scale.pyramid_levels + 1):
        out_h, out_w = previous.shape[0] // 2, previous.shape[1] // 2
        if out_h < 2 or out_w < 2:
            break
        out = np.lib.format.open_memmap(
            str(paths.pyramid_level(level)), mode="w+", dtype=dtype, shape=(out_h, out_w) + image.shape[2:]
        )
        chunk = max(1, 4_000_000 // max(1, out_w))
        for block_start in range(0, out_h, chunk):
            block_end = min(out_h, block_start + chunk)
            block = np.asarray(previous[2 * block_start : 2 * block_end, : 2 * out_w])
            a, b = block[0::2, 0::2], block[0::2, 1::2]
            c, d = block[1::2, 0::2], block[1::2, 1::2]
            if dtype == np.uint8:
                out[block_start:block_end] = ((a.astype(np.uint16) + b + c + d + 2) >> 2).astype(np.uint8)
            else:
                out[block_start:block_end] = (a.astype(np.float32) + b + c + d) * 0.25
            done_rows += block_end - block_start
            if progress_callback:
                progress_callback(int(99 * done_rows / total_rows), "Preparing image pyramid...")
        out.flush()
        pyramid[level] = out
        previous = out
    return pyramid


def _gaussian_kernel(sigma, radius):
    return cv2.getGaussianKernel(2 * radius + 1, float(sigma)).ravel().astype(np.float32)


def _axis_selector(centers, offset, size):
    """
    Selector for positions `centers + offset` along one axis, clipped to the
    image. Uses a slice when the positions are uniform and in bounds (fast
    strided reads from the memmap), falling back to index arrays otherwise.
    """
    indices = centers + offset
    if indices[0] >= 0 and indices[-1] < size:
        if indices.size == 1:
            return slice(int(indices[0]), int(indices[0]) + 1)
        steps = np.diff(indices)
        step = int(steps[0])
        if step > 0 and np.all(steps == step):
            return slice(int(indices[0]), int(indices[-1]) + 1, step)
    return np.clip(indices, 0, size - 1)


def _sampled_features_2d(source, pyramid, i0, j0, out_w, out_h, factor, feature_indices, scale):
    """
    Full-resolution-semantics features evaluated at the downsampled output grid
    (positions i0 + n*factor, j0 + m*factor), without reading the full image:

    - SOURCE, the sigma-1 gaussian and all window variances are EXACT: each
      output pixel's value is accumulated from its true full-resolution
      neighborhood via shifted strided reads, shared across the whole grid.
    - The sigma 2/4/8 gaussians are band-limited, so they are approximated from
      the mean pyramid with a residual gaussian (error ~1%, vs. the kernel
      cv2 applies at full resolution).

    This keeps the preview classification consistent with the full-resolution
    result at any zoom level; only the output sampling density changes.
    """
    height, width = source.shape[1], source.shape[2]
    image = source[0]
    rows = j0 + np.arange(out_h, dtype=np.int64) * factor
    cols = i0 + np.arange(out_w, dtype=np.int64) * factor

    selected = [FeatureIndex(index) for index in sorted(feature_indices)]
    winvars = [scale.winvar_sizes[feature] for feature in selected if feature in scale.winvar_sizes]
    has_source = FeatureIndex.SOURCE in selected
    has_g1 = FeatureIndex.GAUSSIAN_A in selected

    plane_shape = (out_h, out_w) + image.shape[2:]
    results = {}

    # Exact pass over the full-resolution image
    g1_radius = 4 * scale.gaussian_sigmas[FeatureIndex.GAUSSIAN_A]  # matches cv2's kernel radius
    base_radius = max([0] + ([g1_radius] if has_g1 else []) + [w // 2 for w in winvars])
    if has_source or has_g1 or winvars:
        g1_kernel = _gaussian_kernel(scale.gaussian_sigmas[FeatureIndex.GAUSSIAN_A], g1_radius) if has_g1 else None
        g1_acc = np.zeros(plane_shape, dtype=np.float32) if has_g1 else None
        sums = {w: np.zeros(plane_shape, dtype=np.float32) for w in winvars}
        square_sums = {w: np.zeros(plane_shape, dtype=np.float32) for w in winvars}
        square_buffer = np.empty(plane_shape, dtype=np.float32)
        column_selectors = {di: _axis_selector(cols, di, width) for di in range(-base_radius, base_radius + 1)}

        for dj in range(-base_radius, base_radius + 1):
            row_block = image[_axis_selector(rows, dj, height)]
            for di in range(-base_radius, base_radius + 1):
                use_g1 = has_g1 and abs(dj) <= g1_radius and abs(di) <= g1_radius
                use_winvars = [w for w in winvars if abs(dj) <= w // 2 and abs(di) <= w // 2]
                use_source = has_source and dj == 0 and di == 0
                if not (use_g1 or use_winvars or use_source):
                    continue

                shifted = np.asarray(row_block[:, column_selectors[di]], dtype=np.float32)
                if use_source:
                    results[FeatureIndex.SOURCE] = shifted.copy()
                if use_winvars:
                    np.multiply(shifted, shifted, out=square_buffer)
                    for w in use_winvars:
                        np.add(sums[w], shifted, out=sums[w])
                        np.add(square_sums[w], square_buffer, out=square_sums[w])
                if use_g1:
                    # `shifted` is a private copy at this point; scale it in place
                    shifted *= g1_kernel[dj + g1_radius] * g1_kernel[di + g1_radius]
                    np.add(g1_acc, shifted, out=g1_acc)

        if has_g1:
            results[FeatureIndex.GAUSSIAN_A] = g1_acc
        for feature in selected:
            if feature in scale.winvar_sizes:
                w = scale.winvar_sizes[feature]
                mean = sums[w] / (w * w)
                results[feature] = square_sums[w] / (w * w) - mean * mean

    # Pyramid pass for the band-limited gaussians
    for feature in selected:
        level = scale.gaussian_pyramid_level.get(feature)
        if level is None:
            continue
        level_image = pyramid[level]
        level_h, level_w = level_image.shape[0], level_image.shape[1]
        level_factor = 2**level
        sigma = scale.gaussian_sigmas[feature]
        # 2x2 mean pooling acts as a box filter; remove its variance from the target sigma
        box_variance = (level_factor * level_factor - 1) / 12.0
        sigma_level = np.sqrt(sigma * sigma - box_variance) / level_factor
        radius = max(1, int(np.ceil(3 * sigma_level)))
        kernel = _gaussian_kernel(sigma_level, radius)
        center_offset = (level_factor - 1) / 2.0
        level_rows = np.round((rows - center_offset) / level_factor).astype(np.int64)
        level_cols = np.round((cols - center_offset) / level_factor).astype(np.int64)

        accumulator = np.zeros(plane_shape, dtype=np.float32)
        column_selectors = {di: _axis_selector(level_cols, di, level_w) for di in range(-radius, radius + 1)}
        for dj in range(-radius, radius + 1):
            row_block = level_image[_axis_selector(level_rows, dj, level_h)]
            for di in range(-radius, radius + 1):
                shifted = np.asarray(row_block[:, column_selectors[di]], dtype=np.float32)
                shifted *= kernel[dj + radius] * kernel[di + radius]
                np.add(accumulator, shifted, out=accumulator)
        results[feature] = accumulator

    planes = []
    for feature in selected:
        result = results[feature]
        if result.ndim == 2:
            result = result[:, :, np.newaxis]
        for channel in range(result.shape[2]):
            planes.append(result[:, :, channel])
    return np.stack(planes, axis=0)


class Lazy2DState:
    """Per-session state for 2D lazy mode: source mmap, feature scale, pyramid,
    annotation and trained model."""

    def __init__(self, source, paths: InterprocessPaths, scale: FeatureScale = None):
        self.source = source  # shape (1, H, W) or (1, H, W, C)
        self.paths = paths
        self.scale = scale if scale is not None else FeatureScale.from_multiplier(1)
        self.pyramid = {}
        self.annotation = None
        self.models = {}  # tuple(feature_indices) -> trained model

    def build_pyramid(self, progress_callback=None):
        height, width = self.source.shape[1], self.source.shape[2]
        if height * width > CONTIG_MAX_PIXELS:
            self.pyramid = _build_mean_pyramid(self.source, self.paths, self.scale, progress_callback)

    def reset(self):
        self.annotation = None
        self.models.clear()

    def get_model(self, feature_indices):
        """Return the cached preview model for this feature set, training it on
        demand (subsampled for interactive speed). Factor-independent."""
        key = tuple(feature_indices)
        model = self.models.get(key)
        if model is None and self.annotation is not None:
            model = self._train(feature_indices, subsample=True)
            self.models[key] = model
        return model

    def train_full(self, feature_indices):
        """Train on the COMPLETE annotation set (no subsampling) for the final
        full-image apply, where accuracy matters more than latency. Not cached,
        so the preview keeps its fast subsampled model."""
        if self.annotation is None:
            return None
        return self._train(feature_indices, subsample=False)

    def _train(self, feature_indices, subsample):
        start = time.perf_counter()
        X_train, y_train = _training_features_2d(
            self.source, self.annotation, feature_indices, self.scale, subsample=subsample
        )
        model = _make_model(PREDICT_N_JOBS)
        model.fit(X_train, y_train)
        safe_dump_json({"is_trained": True}, self.paths.model_status)
        print(
            f"[{os.getpid()}] 2D model trained on {y_train.size} samples "
            f"in {time.perf_counter() - start:.4f} seconds",
            flush=True,
        )
        return model


def _feature_base_names(feature_indices, scale):
    """
    One human-readable name per selected feature (sorted order), with kernel
    sizes scaled by the session's feature scale. The feature planes are laid out
    feature-major / channel-minor, so the renderer pairs these names with
    consecutive channel groups to rebuild RGB feature views.
    """
    return [feature_display_name(FeatureIndex(index), scale.multiplier) for index in sorted(feature_indices)]


DEBUG_THUMB_MAX = 1200  # longest side of the source thumbnail stored in a debug capture


def _capture_preview_context(capture, state, rect, factor, feature_indices):
    """
    Record the whole-image context shared by both preview branches: a decimated
    source thumbnail, the requested preview rectangle (full-resolution coords),
    a thumbnail-resolution map of the annotated (training) pixels, and a mask of
    every region where features were computed to TRAIN the model (which may sit
    well outside the preview region).

    The annotations and training coverage are rasterized into small images rather
    than shipped as point/box lists: the user may paint hundreds of thousands of
    pixels, and scattering one marker each would make the report's PDF crawl. The
    rasters overlay cleanly and show the painted/computed regions truthfully.
    """
    source = state.source
    height, width = source.shape[1], source.shape[2]
    thumb_stride = max(1, max(height, width) // DEBUG_THUMB_MAX)
    thumb = np.asarray(source[0, ::thumb_stride, ::thumb_stride])
    # For a multi-image stack, the thumbnail shows only the first input image;
    # all channels stacked together aren't displayable as a single picture.
    if thumb.ndim == 3 and "image_channels" in capture:
        thumb = thumb[..., : int(capture["image_channels"][0])]
    capture["thumb"] = thumb
    capture["thumb_stride"] = thumb_stride
    capture["rect"] = np.array(rect)  # i0, i1, j0, j1
    th, tw = thumb.shape[:2]

    if state.annotation is not None:
        annotation = state.annotation
        labels = annotation[0].astype(np.uint16)
        ai = np.clip(annotation[1].astype(np.int64) // thumb_stride, 0, tw - 1)
        aj = np.clip(annotation[2].astype(np.int64) // thumb_stride, 0, th - 1)
        # 0 means "unannotated"; class c is stored as c + 1 so label 0 is usable.
        overlay = np.zeros((th, tw), dtype=np.uint16)
        overlay[aj, ai] = labels + 1
        capture["ann_overlay"] = overlay

        # Mask of every region whose features were computed for training, drawn
        # at thumbnail resolution: dense-tile bounding boxes filled directly,
        # sparse per-point patches marked then dilated by the (downscaled) margin.
        dense_bboxes, sparse_i, sparse_j, margin = _training_regions_2d(
            source, annotation, feature_indices, state.scale
        )
        coverage = np.zeros((th, tw), dtype=bool)
        for si0, si1, sj0, sj1 in dense_bboxes:
            coverage[
                sj0 // thumb_stride : (sj1 - 1) // thumb_stride + 1, si0 // thumb_stride : (si1 - 1) // thumb_stride + 1
            ] = True
        if sparse_i.size:
            points = np.zeros((th, tw), dtype=bool)
            points[np.clip(sparse_j // thumb_stride, 0, th - 1), np.clip(sparse_i // thumb_stride, 0, tw - 1)] = True
            radius = max(1, int(np.ceil(margin / thumb_stride)))
            coverage |= binary_dilation(points, structure=np.ones((2 * radius + 1, 2 * radius + 1), dtype=bool))
        capture["train_coverage"] = coverage.astype(np.uint8)


def _predict_preview_2d(model, state: Lazy2DState, extents, factor, feature_indices, paths, capture=None):
    """
    Predict the visible region on a downsampled output grid and save the result.
    Small regions are filtered contiguously at full resolution (exact); large
    regions use the sampled-feature path. Either way the features have
    full-resolution semantics, so the preview agrees with the final result.

    When `capture` is a dict, intermediate arrays describing how the preview was
    computed are recorded into it (the real code path is used unchanged, so the
    capture cannot drift from production behavior).
    """
    start = time.perf_counter()
    source = state.source
    height, width = source.shape[1], source.shape[2]
    n_channels = source.shape[3] if source.ndim == 4 else 1
    i0, i1 = max(0, extents[0]), min(width, extents[1])
    j0, j1 = max(0, extents[2]), min(height, extents[3])

    out_w = -(-(i1 - i0) // factor) if i1 > i0 else 0
    out_h = -(-(j1 - j0) // factor) if j1 > j0 else 0
    if out_w <= 0 or out_h <= 0:
        print(f"[{os.getpid()}] No data to predict within extents. Writing empty result.", flush=True)
        safe_save_npz(paths.result, result=np.array([], dtype=np.uint8), extents=extents, factor=factor)
        return

    if capture is not None:
        _capture_preview_context(capture, state, (i0, i1, j0, j1), factor, feature_indices)

    margin = state.scale.margin(feature_indices)
    region_pixels = (i1 - i0 + 2 * margin) * (j1 - j0 + 2 * margin)
    if factor == 1 or region_pixels <= CONTIG_MAX_PIXELS or not state.pyramid:
        si0, sj0 = max(0, i0 - margin), max(0, j0 - margin)
        si1, sj1 = min(width, i1 + margin), min(height, j1 + margin)
        sample = np.asarray(source[0, sj0:sj1, si0:si1])
        features = _compute_features_2d(sample, feature_indices, state.scale)
        features = features[
            :,
            j0 - sj0 : j0 - sj0 + (out_h - 1) * factor + 1 : factor,
            i0 - si0 : i0 - si0 + (out_w - 1) * factor + 1 : factor,
        ]
        if capture is not None:
            capture["branch"] = "contiguous"
            capture["sample_rect"] = np.array([si0, si1, sj0, sj1])
            capture["region_pixels"] = region_pixels
            capture["contig_max_pixels"] = CONTIG_MAX_PIXELS
    else:
        features = _sampled_features_2d(
            source, state.pyramid, i0, j0, out_w, out_h, factor, feature_indices, state.scale
        )
        if capture is not None:
            capture["branch"] = "sampled"
            capture["grid_cols"] = i0 + np.arange(out_w, dtype=np.int64) * factor
            capture["grid_rows"] = j0 + np.arange(out_h, dtype=np.int64) * factor
            capture["region_pixels"] = region_pixels
            capture["contig_max_pixels"] = CONTIG_MAX_PIXELS
            pyramid_levels = [
                [
                    feature_display_name(FeatureIndex(i), state.scale.multiplier),
                    state.scale.gaussian_pyramid_level[FeatureIndex(i)],
                ]
                for i in sorted(feature_indices)
                if FeatureIndex(i) in state.scale.gaussian_pyramid_level
            ]
            capture["pyramid_levels"] = json.dumps(pyramid_levels)

    X_predict = features.reshape(features.shape[0], -1).T
    # predict() derives the label from this same proba, so we get the
    # uncertainty map for the annotation-view overlay at no extra cost.
    proba = model.predict_proba(X_predict)
    predictions = model.classes_[np.argmax(proba, axis=1)].astype(np.uint8)
    result_labelmap = predictions.reshape(1, out_h, out_w)
    uncertainty_labelmap = _uncertainty_mask_from_proba(proba).reshape(1, out_h, out_w)

    if capture is not None:
        capture["features"] = features.astype(np.float32)
        capture["feature_names"] = json.dumps(_feature_base_names(feature_indices, state.scale))
        capture["n_channels"] = n_channels
        capture["result"] = result_labelmap[0]
        capture["uncertainty"] = uncertainty_labelmap[0]
        capture["margin"] = margin
        capture["factor"] = factor
        capture["feature_scale"] = state.scale.multiplier
        safe_save_npz(paths.debug_capture, **capture)
        print(f"[{os.getpid()}] Debug capture written to {paths.debug_capture}", flush=True)

    safe_save_npz(
        paths.result,
        result=result_labelmap,
        extents=[i0, i1, j0, j1, 0, 1],
        factor=factor,
        uncertainty=uncertainty_labelmap,
    )
    print(
        f"[{os.getpid()}] Preview predicted at factor {factor} over {out_w}x{out_h} pixels "
        f"in {time.perf_counter() - start:.4f} seconds",
        flush=True,
    )


def _predict_full_2d(model, source, feature_indices, paths, scale):
    """Predict the whole image at full resolution, tile by tile, with progress updates."""
    height, width = source.shape[1], source.shape[2]
    result = np.memmap(paths.full_result_mmap, dtype=np.uint8, mode="w+", shape=(1, height, width))

    margin = scale.margin(feature_indices)
    tiles_i = -(-width // FULL_INFERENCE_TILE)
    tiles_j = -(-height // FULL_INFERENCE_TILE)
    total_tiles = tiles_i * tiles_j

    update_progress(paths.progress, 0, "Applying segmentation to the full image...")
    for tile_index in range(total_tiles):
        i0 = (tile_index % tiles_i) * FULL_INFERENCE_TILE
        j0 = (tile_index // tiles_i) * FULL_INFERENCE_TILE
        i1, j1 = min(width, i0 + FULL_INFERENCE_TILE), min(height, j0 + FULL_INFERENCE_TILE)

        si0, sj0 = max(0, i0 - margin), max(0, j0 - margin)
        si1, sj1 = min(width, i1 + margin), min(height, j1 + margin)

        sample = np.asarray(source[0, sj0:sj1, si0:si1])
        features = _compute_features_2d(sample, feature_indices, scale)
        features = features[:, j0 - sj0 : j1 - sj0, i0 - si0 : i1 - si0]

        X_predict = features.reshape(features.shape[0], -1).T
        predictions = model.predict(X_predict).astype(np.uint8)
        result[0, j0:j1, i0:i1] = predictions.reshape(j1 - j0, i1 - i0)

        progress = min(99, round(100 * (tile_index + 1) / total_tiles))
        update_progress(paths.progress, progress, f"Tile {tile_index + 1} of {total_tiles}")

    safe_save_npz(paths.result, result=result, extents=[0, width, 0, height, 0, 1], factor=1)


def _handle_task_2d(task_params, paths, state: Lazy2DState):
    action = task_params["action"]

    if action == "write_empty":
        # Carries no features, so handle it before any feature selection (the
        # train/predict branches below need the sorted feature list).
        print(f"[{os.getpid()}] No training data available. Writing empty result.", flush=True)
        state.reset()
        safe_save_npz(paths.result, result=np.array([], dtype=np.uint8), extents=np.zeros(6, dtype=int), factor=1)
        safe_dump_json({"is_trained": False}, paths.model_status)
        return

    feature_indices = sorted(task_params["features"])

    if action == "train":
        state.annotation = np.load(paths.annotation)
        state.models.clear()

    if task_params.get("is_full_inference", False):
        inference_source = state.source
        if paths.inference_source.exists():
            inference_source = np.load(paths.inference_source, mmap_mode="r")

        # The full apply trains on every annotated pixel (no subsampling).
        model = state.train_full(feature_indices)
        if model is None:
            print(f"[{os.getpid()}] Model not trained yet. Skipping prediction.", flush=True)
            return

        _predict_full_2d(model, inference_source, feature_indices, paths, state.scale)

        if inference_source is not state.source:
            del inference_source
            try:
                paths.inference_source.unlink()
            except OSError:
                pass

        update_progress(paths.progress, 100, "Full segmentation complete.")
        return

    extents = task_params["extents"]
    factor = compute_preview_factor(extents)
    model = state.get_model(feature_indices)
    if model is None:
        print(f"[{os.getpid()}] Model not trained yet. Skipping prediction.", flush=True)
        return

    capture = None
    if task_params.get("debug", False):
        capture = {}
        # Per-image channel layout (source node first, then extras), so the
        # renderer can split the flat channel stack into one image per input.
        if task_params.get("image_channels"):
            capture["image_channels"] = np.asarray(task_params["image_channels"], dtype=np.int32)
            capture["image_names"] = json.dumps(task_params.get("image_names", []))
    _predict_preview_2d(model, state, extents, factor, feature_indices, paths, capture=capture)


def run_consumer(data_dir: str, parent_pid: int, scale: FeatureScale, initial_features=None):
    paths = InterprocessPaths(Path(data_dir))
    print(f"[{os.getpid()}] Consumer process started. Monitoring directory: {data_dir}", flush=True)
    print(f"[{os.getpid()}] Monitoring parent process with PID: {parent_pid}", flush=True)

    print(f"[{os.getpid()}] Waiting for source image...", flush=True)
    while not paths.source.exists():
        time.sleep(SLEEP_TIME)

    print(f"[{os.getpid()}] Loading source image.", flush=True)
    # mmap keeps very large 2D mosaics out of memory; the 3D path copies it to RAM as before.
    source = np.load(paths.source, mmap_mode="r")
    is_2d = source.shape[0] == 1

    state = None
    features = None
    original_shape = None
    model = None

    if is_2d:
        print(f"[{os.getpid()}] 2D source detected (shape {source.shape}). Using lazy feature mode.", flush=True)
        state = Lazy2DState(source, paths, scale)
        state.build_pyramid(lambda p, m: update_progress(paths.progress, p, m))
        update_progress(paths.progress, 100, "Ready")
        # 2D computes features lazily per preset, so every preset is immediately
        # available: preview-ready and features-complete coincide.
        safe_dump_json({"ready": True}, paths.preview_ready)
        safe_dump_json({"complete": True}, paths.features_complete)
    else:

        def progress(p, m):
            update_progress(paths.progress, p, m)

        # Feature computation is now parallel and out-of-core, so the whole set is
        # ready quickly. Compute every feature up front in a single pass rather
        # than splitting into a priority preset plus a background fill: it makes
        # every preset immediately available (no recompute on preset switch) and,
        # crucially, avoids a background writer thread saturating the cores and
        # contending with the interactive train/predict loop -- which made the
        # preview stall while the extra features were being written.
        # (initial_features is accepted for launch-interface compatibility but no
        # longer drives any ordering, since all features are computed regardless.)
        source_array = np.asarray(source)
        features, n_channels = _allocate_feature_mmap(source_array, paths.features_mmap)
        original_shape = source.shape[:3]

        _compute_feature_planes(source_array, features, n_channels, list(FeatureIndex), scale, progress)
        safe_dump_json({"ready": True}, paths.preview_ready)
        safe_dump_json({"complete": True}, paths.features_complete)
        print(f"[{os.getpid()}] All {len(list(FeatureIndex))} features computed.", flush=True)

    while True:
        if not psutil.pid_exists(parent_pid):
            print(f"[{os.getpid()}] Parent process {parent_pid} not found. Exiting.", flush=True)
            break

        try:
            task_file = paths.task
            if not task_file.exists():
                time.sleep(SLEEP_TIME)
                continue

            with task_file.open("r") as f:
                task_params = json.load(f)
            task_file.unlink()

            if task_params.get("action") == "stop":
                print(f"[{os.getpid()}] Stop signal detected. Exiting.", flush=True)
                break

            if is_2d:
                _handle_task_2d(task_params, paths, state)
            else:
                model = _handle_task(task_params, paths, model, features, original_shape, scale)

        except Exception as e:
            print(f"[{os.getpid()}] An error occurred in the consumer loop: {e}", flush=True)
            import traceback

            traceback.print_exc(file=sys.stdout)

        time.sleep(SLEEP_TIME)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Real-time segmentation consumer process.")
    parser.add_argument("--data-dir", type=str, required=True, help="Path to the directory for exchanging data.")
    parser.add_argument("--parent-pid", type=int, required=True, help="PID of the parent process to monitor.")
    parser.add_argument(
        "--initial-features",
        type=str,
        default="",
        help=(
            "Comma-separated feature indices (3D) to compute before the preview is ready; "
            "the rest follow in the background."
        ),
    )
    parser.add_argument(
        "--feature-scale",
        type=int,
        default=1,
        help="Multiplier (1/2/4) applied to every feature kernel size for coarser-textured images.",
    )
    args = parser.parse_args()

    initial_features = [int(x) for x in args.initial_features.split(",") if x.strip() != ""] or None
    scale = FeatureScale.from_multiplier(args.feature_scale)
    print(
        f"[{os.getpid()}] Feature scale {args.feature_scale}x: "
        f"sigmas={scale.gaussian_sigmas}, winvars={scale.winvar_sizes}",
        flush=True,
    )

    try:
        run_consumer(args.data_dir, args.parent_pid, scale, initial_features)
    except Exception as e:
        import traceback

        print(f"[{os.getpid()}] Fatal error in consumer process: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        sys.exit(1)
