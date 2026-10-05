"""The 2D lazy session: features are computed on demand rather than over the whole
image, so a 100k-pixel thin section still previews instantly.

Owns the session state, which pixels get filtered to train on, and the preview and
full-image predictions. Computing a feature plane lives in features_2d.
"""

import json
import os
import time

import numpy as np
from scipy.ndimage import binary_dilation

from ltrace.interactive.features import FeatureScale, feature_base_names, feature_display_name
from ltrace.interactive.features_2d import build_mean_pyramid, compute_features_2d, sampled_features_2d
from ltrace.interactive.ipc import (
    FeatureIndex,
    InterprocessPaths,
    compute_preview_factor,
    safe_dump_json,
    safe_save_npz,
)
from ltrace.interactive.forest import PREDICT_N_JOBS, make_model, predict_in_batches, uncertainty_mask_from_proba
from ltrace.interactive.reporting import apply_plan_line, log_apply, update_progress


TRAIN_MAX_SAMPLES = 200_000  # annotated pixels used for training, subsampled beyond it
SPARSE_TRAIN_MAX = 10_000  # annotated pixels reached through per-point patches
TRAIN_TILE_SIZE = 256  # tile grouping annotated pixels into dense vs sparse
MOSAIC_BATCH = 2048  # patches per filtering pass when gathering sparse training features
FULL_INFERENCE_TILE = 1024
CONTIG_MAX_PIXELS = 4_000_000  # region size up to which preview features are filtered contiguously


def _gather_patch_features(source, i_points, j_points, feature_indices, margin, scale):
    """Feature vectors at sparse pixels: one (2*margin+1)^2 patch per pixel, stacked into
    a tall mosaic, filtered once, read back at each patch center. The patch radius covers
    every filter's support, so neighbouring patches cannot affect a center."""
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
        features = compute_features_2d(mosaic, feature_indices, scale)

        center_rows = margin + np.arange(batch_i.size) * patch
        X[start : start + MOSAIC_BATCH] = features[:, center_rows, margin].T

    return X


def _training_features_2d(source, annotation, feature_indices, scale, subsample=True):
    """Feature vectors at the annotated pixels, without touching the rest of the image:
    dense tiles are filtered as one bounding-box sample, scattered points as per-point
    patches. `subsample` caps the annotation set for interactive previews; the full apply
    passes False to train on every annotated pixel."""
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
        features = compute_features_2d(sample, feature_indices, scale)

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
    """Geometry-only mirror of _training_features_2d for the debug report: the regions it
    WOULD filter, without filtering them. Returns (dense_bboxes, sparse_i, sparse_j,
    margin)."""
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


class Lazy2DState:
    """Per-session state: source mmap, feature scale, pyramid, annotation and models."""

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
            self.pyramid = build_mean_pyramid(self.source, self.paths, self.scale, progress_callback)

    def reset(self):
        self.annotation = None
        self.models.clear()

    def get_model(self, feature_indices):
        """The cached preview model for this feature set, trained on demand."""
        key = tuple(feature_indices)
        model = self.models.get(key)
        if model is None and self.annotation is not None:
            model = self._train(feature_indices, subsample=True)
            self.models[key] = model
        return model

    def train_full(self, feature_indices):
        """Train on the complete annotation set for the full apply. Not cached, so the
        preview keeps its faster subsampled model."""
        if self.annotation is None:
            return None
        return self._train(feature_indices, subsample=False)

    def _train(self, feature_indices, subsample):
        start = time.perf_counter()
        X_train, y_train = _training_features_2d(
            self.source, self.annotation, feature_indices, self.scale, subsample=subsample
        )
        model = make_model(PREDICT_N_JOBS)
        model.fit(X_train, y_train)
        safe_dump_json({"is_trained": True}, self.paths.model_status)
        print(
            f"[{os.getpid()}] 2D model trained on {y_train.size} samples "
            f"in {time.perf_counter() - start:.4f} seconds",
            flush=True,
        )
        return model


DEBUG_THUMB_MAX = 1200  # longest side of the source thumbnail stored in a debug capture


def _capture_preview_context(capture, state, rect, factor, feature_indices):
    """Record the whole-image context both preview branches share: a source thumbnail,
    the preview rectangle, and thumbnail-resolution rasters of the annotated pixels and
    of every region filtered to train the model (which may sit outside the preview)."""
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

        # Dense-tile boxes fill directly; sparse patch centers are marked then dilated
        # by the downscaled margin.
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
    """Predict the visible region on a downsampled grid and save it. Small regions are
    filtered contiguously at full resolution, large ones take the sampled-feature path;
    either way the features have full-resolution semantics. A `capture` dict collects
    intermediates for the debug report off the unmodified code path."""
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
        features = compute_features_2d(sample, feature_indices, state.scale)
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
        features = sampled_features_2d(
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
    # predict() derives the label from this same proba, so the uncertainty map is free.
    proba = model.predict_proba(X_predict)
    predictions = model.classes_[np.argmax(proba, axis=1)].astype(np.uint8)
    result_labelmap = predictions.reshape(1, out_h, out_w)
    uncertainty_labelmap = uncertainty_mask_from_proba(proba).reshape(1, out_h, out_w)

    if capture is not None:
        capture["features"] = features.astype(np.float32)
        capture["feature_names"] = json.dumps(feature_base_names(feature_indices, state.scale))
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

    n_columns = len(feature_indices) * (source.shape[3] if source.ndim == 4 else 1)
    tile_j, tile_i = min(height, FULL_INFERENCE_TILE), min(width, FULL_INFERENCE_TILE)
    log_apply(
        paths.apply_log,
        apply_plan_line(
            total_tiles,
            (1, tile_j, tile_i),
            tile_j * tile_i * n_columns * 4,
            f"{model.n_jobs} prediction threads",
            unit="tile",
        ),
        slabs=total_tiles,
    )
    update_progress(paths.progress, 0, "Applying segmentation to the full image...")
    for tile_index in range(total_tiles):
        i0 = (tile_index % tiles_i) * FULL_INFERENCE_TILE
        j0 = (tile_index // tiles_i) * FULL_INFERENCE_TILE
        i1, j1 = min(width, i0 + FULL_INFERENCE_TILE), min(height, j0 + FULL_INFERENCE_TILE)

        si0, sj0 = max(0, i0 - margin), max(0, j0 - margin)
        si1, sj1 = min(width, i1 + margin), min(height, j1 + margin)

        log_apply(
            paths.apply_log,
            f"Tile {tile_index + 1}/{total_tiles} - calculating features",
            slab=tile_index + 1,
            slabs=total_tiles,
        )
        sample = np.asarray(source[0, sj0:sj1, si0:si1])
        features = compute_features_2d(sample, feature_indices, scale)
        features = features[:, j0 - sj0 : j1 - sj0, i0 - si0 : i1 - si0]

        log_apply(
            paths.apply_log,
            f"Tile {tile_index + 1}/{total_tiles} - calculating prediction",
            slab=tile_index + 1,
            slabs=total_tiles,
        )
        X_predict = features.reshape(features.shape[0], -1).T
        predictions = predict_in_batches(model, X_predict).astype(np.uint8)
        result[0, j0:j1, i0:i1] = predictions.reshape(j1 - j0, i1 - i0)

        progress = min(99, round(100 * (tile_index + 1) / total_tiles))
        update_progress(paths.progress, progress, f"Tile {tile_index + 1} of {total_tiles}")

    safe_save_npz(paths.result, result=result, extents=[0, width, 0, height, 0, 1], factor=1)


def handle_task_2d(task_params, paths, state: Lazy2DState):
    action = task_params["action"]

    if action == "write_empty":
        # Carries no features, so it must come before the feature selection below.
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
        # Per-image channel layout, so the renderer can split the flat channel stack.
        if task_params.get("image_channels"):
            capture["image_channels"] = np.asarray(task_params["image_channels"], dtype=np.int32)
            capture["image_names"] = json.dumps(task_params.get("image_names", []))
    _predict_preview_2d(model, state, extents, factor, feature_indices, paths, capture=capture)
