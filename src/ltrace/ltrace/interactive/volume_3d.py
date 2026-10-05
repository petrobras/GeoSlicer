"""The 3D session: training on the feature memmap, predicting the previewed extent from
it, and the fused out-of-core apply for a separate inference volume.

Feature columns are (channel outer, feature inner) everywhere here, which only lines up
because the caller sorted `feature_indices`.
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from humanize import naturalsize

from ltrace.interactive.features import feature_display_name
from ltrace.interactive.ipc import FeatureIndex, safe_dump_json, safe_save_npz, safe_unlink
from ltrace.interactive.forest import make_model, predict_in_batches, uncertainty_mask_from_proba
from ltrace.interactive.reporting import (
    apply_plan_line,
    apply_timing_summary,
    log_apply,
    step_timing_line,
    update_progress,
)
from ltrace.interactive.resources import available_cores, feature_mem_budget, slab_thickness_override


PREDICT_FILTER_COPIES = 2  # haloed float32 copies a filter worker holds: its output and the cast
PREDICT_SLAB_BUFFERS = 2  # design matrices live at once: the one predicting, the one filtering ahead


def train_model(features, paths, feature_indices):
    print(f"[{os.getpid()}] Loading annotation data...", flush=True)
    training_data = np.load(paths.annotation)

    y_train = training_data[0, :].astype(np.uint8)
    i_coords, j_coords, k_coords = training_data[1:4, :].astype(int)

    # features is (n_channels, n_features, K, J, I): sample the annotated voxels, keep the
    # selected features, then flatten (channel, feature) into one column per pair.
    sampled = features[:, :, k_coords, j_coords, i_coords]  # (n_channels, n_features, n_samples)
    sampled = sampled[:, feature_indices, :]  # (n_channels, n_selected, n_samples)
    X_train = sampled.reshape(-1, sampled.shape[2]).T  # (n_samples, n_channels * n_selected)

    print(f"[{os.getpid()}] Training data shape: {X_train.shape}, y_train shape: {y_train.shape}", flush=True)
    print(f"[{os.getpid()}] Training RandomForest on {len(y_train)} samples...", flush=True)

    start = time.perf_counter()
    model = make_model(1)
    model.fit(X_train, y_train)
    safe_dump_json({"is_trained": True}, paths.model_status)
    print(f"[{os.getpid()}] Model trained in {time.perf_counter() - start:.4f} seconds", flush=True)
    return model


def _filter_into_row(calc_func, block, k0, k1, out_row):
    """Filter one haloed slab, trim it to its core K slices and flatten it into its column
    of the design matrix. The float32 cast comes AFTER the filter, as in the precompute,
    or the model would see different values from the ones it trained on."""
    out_row[:] = np.asarray(calc_func(block), dtype=np.float32)[k0:k1].ravel()


def fused_slab_plan(K, plane_bytes, margin, n_columns, n_channels, budget, cores):
    """Slab thickness and filter-worker count for the fused apply, chosen together by
    minimizing halo redundancy over worker count -- they compete for the same budget."""
    best = None
    for workers in range(1, max(1, min(cores, n_columns)) + 1):
        haloed_copies = PREDICT_FILTER_COPIES * workers + n_channels
        thickness = (budget // plane_bytes - haloed_copies * 2 * margin) // (
            haloed_copies + PREDICT_SLAB_BUFFERS * n_columns
        )
        thickness = max(1, min(K, thickness))
        cost = (1 + 2 * margin / thickness) / workers
        if best is None or cost < best[0]:
            best = (cost, thickness, workers)
    return best[1], best[2]


def predict_full_3d(model, source, feature_indices, scale, paths):
    """Predict a whole inference volume out-of-core: each slab is filtered, predicted,
    written and discarded, with the next slab filtered while the current one predicts.
    `source` must be a memmap and is never materialized.

    Each slab carries `scale.margin(feature_indices)` slices of context on both sides, so
    its trimmed core matches whole-volume filtering exactly.
    """
    K, J, I = source.shape[:3]
    n_channels = source.shape[3] if source.ndim == 4 else 1
    n_columns = n_channels * len(feature_indices)
    margin = scale.margin(feature_indices)
    calc_funcs = [scale.definitions[FeatureIndex(index)] for index in feature_indices]

    thickness, workers = fused_slab_plan(
        K, J * I * 4, margin, n_columns, n_channels, feature_mem_budget(), available_cores()
    )
    thickness = slab_thickness_override() or thickness

    result = np.memmap(paths.full_result_mmap, dtype=np.uint8, mode="w+", shape=(K, J, I))
    slabs = -(-K // thickness)
    print(
        f"[{os.getpid()}] Fused apply over {(K, J, I)}: {slabs} slabs of {thickness} slices, "
        f"margin {margin}, {workers} filter workers, {n_columns} columns.",
        flush=True,
    )
    log_apply(
        paths.apply_log,
        apply_plan_line(
            slabs,
            (thickness, J, I),
            thickness * J * I * n_columns * 4,
            f"{workers} feature threads overlapped with {model.n_jobs} prediction threads",
        ),
        slabs=slabs,
    )

    update_progress(paths.progress, 0, "Applying segmentation to the full image...")
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool, ThreadPoolExecutor(max_workers=1) as driver:

        def build_slab(slab):
            """Filter one slab into its design matrix, one column per worker. Runs on the
            driver thread, one slab ahead of the loop below."""
            k0 = slab * thickness
            k1 = min(K, k0 + thickness)
            s0, s1 = max(0, k0 - margin), min(K, k1 + margin)
            # Only the first slab's features are on the critical path; tagging the later
            # ones would make the widget's status line jump between two slabs.
            position = {"slab": slab + 1, "slabs": slabs} if slab == 0 else {"slabs": slabs}
            log_apply(paths.apply_log, f"Slab {slab + 1}/{slabs} - calculating features", **position)
            X = np.empty((n_columns, (k1 - k0) * J * I), dtype=np.float32)
            jobs = []
            for channel in range(n_channels):
                block = np.asarray(source[s0:s1, :, :, channel] if source.ndim == 4 else source[s0:s1])
                for calc_func in calc_funcs:
                    jobs.append(pool.submit(_filter_into_row, calc_func, block, k0 - s0, k1 - s0, X[len(jobs)]))
            for job in jobs:
                job.result()  # the columns are complete only once every filter has landed
            return X, k0, k1

        pending = driver.submit(build_slab, 0)
        for slab in range(slabs):
            slab_started = time.perf_counter()
            X, k0, k1 = pending.result()
            # Queued before the current X is released, hence PREDICT_SLAB_BUFFERS.
            if slab + 1 < slabs:
                pending = driver.submit(build_slab, slab + 1)

            log_apply(paths.apply_log, f"Slab {slab + 1}/{slabs} - calculating prediction", slab=slab + 1, slabs=slabs)
            result[k0:k1] = predict_in_batches(model, X.T).reshape(k1 - k0, J, I)
            del X
            log_apply(
                paths.apply_log,
                step_timing_line(f"Slab {slab + 1}/{slabs}", (k1 - k0) * J * I, time.perf_counter() - slab_started),
                slab=slab + 1,
                slabs=slabs,
            )
            update_progress(paths.progress, min(99, round(100 * (slab + 1) / slabs)), f"Slab {slab + 1} of {slabs}")

    log_apply(paths.apply_log, apply_timing_summary(K * J * I, time.perf_counter() - started))
    print(f"[{os.getpid()}] Saving result labelmap of shape {result.shape}", flush=True)
    safe_save_npz(paths.result, result=result, extents=[0, I, 0, J, 0, K], factor=1)


def predict_and_save(
    model, features, extents, feature_indices, paths, compute_uncertainty=False, capture=None, full_apply=False
):
    """Predict `extents` from the feature memmap and save the labelmap. Above the memory
    budget it is predicted in K slabs streamed into the result memmap; the interactive
    preview keeps the in-RAM path, which is the only one that can produce the uncertainty
    map."""
    print(f"[{os.getpid()}] Predicting on the extents area...", flush=True)
    i_min, i_max, j_min, j_max, k_min, k_max = extents
    extent_shape = (k_max - k_min, j_max - j_min, i_max - i_min)

    if min(extent_shape) <= 0:
        print(f"[{os.getpid()}] No data to predict within extents. Writing empty result.", flush=True)
        safe_save_npz(paths.result, result=np.array([], dtype=np.uint8), extents=extents, factor=1)
        return

    # feature_indices is None only for the inference-image apply, whose compacted mmap
    # already holds exactly the selected features.
    selected = slice(None) if feature_indices is None else feature_indices
    n_columns = features.shape[0] * (features.shape[1] if feature_indices is None else len(feature_indices))

    def columns(k0, k1):
        """Feature rows for K slices [k0, k1) of the extent, one row per voxel."""
        block = features[:, selected, k_min + k0 : k_min + k1, j_min:j_max, i_min:i_max]
        return block.reshape(n_columns, -1).T

    plane_bytes = extent_shape[1] * extent_shape[2] * n_columns * 4
    thickness = slab_thickness_override() or max(1, feature_mem_budget() // plane_bytes)

    if compute_uncertainty or thickness >= extent_shape[0]:
        if full_apply:
            log_apply(
                paths.apply_log,
                f"Features are already computed; predicting all "
                f"{extent_shape[2]}x{extent_shape[1]}x{extent_shape[0]} voxels in one pass "
                f"({naturalsize(extent_shape[0] * plane_bytes, binary=True)} of features), "
                f"over {model.n_jobs} prediction threads",
                slabs=1,
            )
            log_apply(paths.apply_log, "Slab 1/1 - calculating prediction", slab=1, slabs=1)
        X_predict = columns(0, extent_shape[0])
        print(f"[{os.getpid()}] Extracted {X_predict.shape[0]} samples for prediction.", flush=True)

        start = time.perf_counter()
        uncertainty_labelmap = None
        if compute_uncertainty:
            # predict() computes this proba internally, so the uncertainty map is free.
            proba = model.predict_proba(X_predict)
            predictions_flat = model.classes_[np.argmax(proba, axis=1)]
            uncertainty_labelmap = uncertainty_mask_from_proba(proba).reshape(extent_shape)
        else:
            predictions_flat = predict_in_batches(model, X_predict)
        result_labelmap = predictions_flat.reshape(extent_shape)
        predict_seconds = time.perf_counter() - start
        print(f"[{os.getpid()}] Predictions made in {predict_seconds:.4f} seconds", flush=True)
        if full_apply:
            voxels = int(np.prod(extent_shape, dtype=np.int64))
            log_apply(paths.apply_log, step_timing_line("Slab 1/1", voxels, predict_seconds), slab=1, slabs=1)
            log_apply(paths.apply_log, apply_timing_summary(voxels, predict_seconds))

        if capture is not None:
            _capture_preview_3d(capture, features, feature_indices, extents, result_labelmap, uncertainty_labelmap)
            safe_save_npz(paths.debug_capture, **capture)
            print(f"[{os.getpid()}] Debug capture written to {paths.debug_capture}", flush=True)

        extra = {} if uncertainty_labelmap is None else {"uncertainty": uncertainty_labelmap.astype(np.uint8)}
        print(f"[{os.getpid()}] Saving result labelmap of shape {result_labelmap.shape}", flush=True)
        safe_save_npz(paths.result, result=result_labelmap.astype(np.uint8), extents=extents, factor=1, **extra)
        return

    result = np.memmap(paths.full_result_mmap, dtype=np.uint8, mode="w+", shape=extent_shape)
    slabs = -(-extent_shape[0] // thickness)
    print(f"[{os.getpid()}] Predicting {extent_shape} in {slabs} slabs of {thickness} slices.", flush=True)
    if full_apply:
        log_apply(paths.apply_log, "Features are already computed; only the prediction is left to do", slabs=slabs)
        log_apply(
            paths.apply_log,
            apply_plan_line(
                slabs,
                (thickness, extent_shape[1], extent_shape[2]),
                thickness * plane_bytes,
                f"{model.n_jobs} prediction threads",
            ),
            slabs=slabs,
        )
    started = time.perf_counter()
    for slab in range(slabs):
        k0 = slab * thickness
        k1 = min(extent_shape[0], k0 + thickness)
        if full_apply:
            log_apply(paths.apply_log, f"Slab {slab + 1}/{slabs} - calculating prediction", slab=slab + 1, slabs=slabs)
        slab_started = time.perf_counter()
        result[k0:k1] = predict_in_batches(model, columns(k0, k1)).reshape(k1 - k0, *extent_shape[1:])
        slab_voxels = (k1 - k0) * extent_shape[1] * extent_shape[2]
        if full_apply:
            log_apply(
                paths.apply_log,
                step_timing_line(f"Slab {slab + 1}/{slabs}", slab_voxels, time.perf_counter() - slab_started),
                slab=slab + 1,
                slabs=slabs,
            )
        update_progress(paths.progress, min(99, round(100 * (slab + 1) / slabs)), f"Slab {slab + 1} of {slabs}")

    if full_apply:
        log_apply(
            paths.apply_log,
            apply_timing_summary(int(np.prod(extent_shape, dtype=np.int64)), time.perf_counter() - started),
        )

    print(f"[{os.getpid()}] Saving result labelmap of shape {result.shape}", flush=True)
    safe_save_npz(paths.result, result=result, extents=extents, factor=1)


def _capture_preview_3d(capture, features, feature_indices, extents, result_labelmap, uncertainty_labelmap):
    """Fill `capture` with what the 3D debug report shows for the previewed K slice: one
    feature plane per (feature, channel) plus the labelmaps, under the same keys the 2D
    capture uses so the renderer reuses its layout."""
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

    # The labelmaps are extent-local and span a single K slice; take its middle plane.
    capture["result"] = np.asarray(result_labelmap[result_labelmap.shape[0] // 2], dtype=np.uint8)
    if uncertainty_labelmap is not None:
        capture["uncertainty"] = np.asarray(uncertainty_labelmap[uncertainty_labelmap.shape[0] // 2], dtype=np.uint8)


def handle_task(task_params, paths, model, features, original_shape, scale):
    action = task_params["action"]
    is_full_inference = task_params.get("is_full_inference", False)
    feature_indices = task_params.get("features")
    # Sorted so training, the memmap layout and the fused apply agree on column order.
    # None only for "write_empty", which returns before any feature selection.
    if feature_indices is not None:
        feature_indices = sorted(feature_indices)

    if action == "write_empty":
        print(f"[{os.getpid()}] No training data available. Writing empty result.", flush=True)
        result_labelmap = np.zeros(original_shape, dtype=np.uint8)
        extents = np.array([0, original_shape[2], 0, original_shape[1], 0, original_shape[0]])
        safe_save_npz(paths.result, result=result_labelmap, extents=extents, factor=1)
        safe_dump_json({"is_trained": False}, paths.model_status)
        return None  # Reset model

    if action == "train":
        model = train_model(features, paths, feature_indices)

    if model is None:
        print(f"[{os.getpid()}] Model not trained yet. Skipping prediction.", flush=True)
        safe_unlink(paths.inference_source)  # nothing will consume it, so don't leave it for a later task
        return None

    extents = task_params["extents"]

    # A debug request runs the normal preview prediction with a capture sink, so the
    # report cannot drift from production behavior.
    capture = None
    if task_params.get("debug") and not is_full_inference:
        capture = {
            "is_3d": True,
            "feature_names": json.dumps(
                [feature_display_name(FeatureIndex(i), scale.multiplier) for i in feature_indices]
            ),
            "feature_scale": scale.multiplier,
            "extents": np.asarray(extents),
        }
        if task_params.get("image_channels"):
            capture["image_channels"] = np.asarray(task_params["image_channels"], dtype=np.int32)
            capture["image_names"] = json.dumps(task_params.get("image_names", []))

    # The batch apply has no UI to starve, so it takes every core; restored afterwards
    # because the same model serves interactive previews.
    previous_n_jobs = model.n_jobs
    if is_full_inference:
        model.n_jobs = available_cores()
    try:
        if paths.inference_source.exists():
            print(f"[{os.getpid()}] Inference source found. Applying to it out-of-core.", flush=True)
            inference_source = np.load(paths.inference_source, mmap_mode="r")
            predict_full_3d(model, inference_source, feature_indices, scale, paths)
            del inference_source
            safe_unlink(paths.inference_source)
        else:
            predict_and_save(
                model,
                features,
                extents,
                feature_indices,
                paths,
                compute_uncertainty=not is_full_inference,
                capture=capture,
                full_apply=is_full_inference,
            )
    finally:
        model.n_jobs = previous_n_jobs

    if is_full_inference:
        update_progress(paths.progress, 100, "Full segmentation complete.")

    return model
