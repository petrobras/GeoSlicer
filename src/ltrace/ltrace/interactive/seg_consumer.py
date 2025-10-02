import os
import sys
import time
import numpy as np
import json
import ltrace.algorithms.feature_extraction as fe
from scipy.ndimage import gaussian_filter
from sklearn.ensemble import RandomForestClassifier
import argparse
from pathlib import Path

from ltrace.interactive.seg_ipc import (
    InterprocessPaths,
    safe_save_npz,
    FeatureIndex,
    safe_dump_json,
    FEATURE_NAMES,
)

SLEEP_TIME = 0.03


def update_progress(path, progress, message):
    print(f"[{os.getpid()}] Progress {progress}%: {message}", flush=True)
    safe_dump_json({"progress": progress, "message": message}, path)


def _calculate_features(source_array, mmap_path, progress_callback, feature_indices_to_calc=None):
    """Calculates features and saves them to a memory-mapped file."""
    progress_callback(0, "Starting feature calculation...")

    feature_definitions = {
        FeatureIndex.SOURCE: lambda arr: arr,
        FeatureIndex.GAUSSIAN_A: lambda arr: gaussian_filter(arr, sigma=1),
        FeatureIndex.GAUSSIAN_B: lambda arr: gaussian_filter(arr, sigma=2),
        FeatureIndex.GAUSSIAN_C: lambda arr: gaussian_filter(arr, sigma=4),
        FeatureIndex.GAUSSIAN_D: lambda arr: gaussian_filter(arr, sigma=8),
        FeatureIndex.WINVAR_A: lambda arr: fe.win_var_3d(arr, 5),
        FeatureIndex.WINVAR_B: lambda arr: fe.win_var_3d(arr, 9),
        FeatureIndex.WINVAR_C: lambda arr: fe.win_var_3d(arr, 13),
    }

    all_feature_enums = list(FeatureIndex)

    if feature_indices_to_calc is None:
        features_to_process = all_feature_enums
    else:
        features_to_process = [fi for fi in all_feature_enums if fi.value in feature_indices_to_calc]

    num_to_calc = len(features_to_process)

    mmap_shape = (num_to_calc,) + source_array.shape
    features_mmap = np.memmap(mmap_path, dtype=np.float32, mode="w+", shape=mmap_shape)
    print(f"[{os.getpid()}] Created memory-mapped file at {mmap_path} with shape {mmap_shape}", flush=True)

    progress_step = 90 / num_to_calc
    current_progress = 0

    for i, feature_enum in enumerate(features_to_process):
        calc_func = feature_definitions[feature_enum]
        result = fe.rescale(calc_func(source_array)).astype(np.float32)
        features_mmap[i, :, :, :] = result
        features_mmap.flush()

        current_progress += progress_step
        progress_callback(int(current_progress), f"{FEATURE_NAMES[feature_enum]} done")

    progress_callback(100, "Features calculated and saved to disk.")
    return features_mmap


def _get_initial_features(paths: InterprocessPaths):
    """Waits for the source image, calculates ALL features, and saves them to a memory-mapped file."""
    print(f"[{os.getpid()}] Waiting for source image...", flush=True)
    while not paths.source.exists():
        time.sleep(SLEEP_TIME)

    print(f"[{os.getpid()}] Loading source image.", flush=True)
    source_array = np.load(paths.source)

    def progress(progress, message):
        update_progress(paths.progress, progress, message)

    # For the initial cache, calculate all features to allow interactive changes.
    features_mmap = _calculate_features(source_array, paths.features_mmap, progress, feature_indices_to_calc=None)
    print(f"[{os.getpid()}] Features calculated and saved to {paths.features_mmap}.", flush=True)
    return features_mmap


def _train_model(features, paths, feature_indices, is_full_inference):
    print(f"[{os.getpid()}] Loading annotation data...", flush=True)
    training_data = np.load(paths.annotation)

    y_train = training_data[0, :].astype(np.uint8)
    i_coords, j_coords, k_coords = training_data[1:4, :].astype(int)

    # Sample from the feature array. For mmap, this reads only the required data from disk.
    X_train_all_features = features[:, k_coords, j_coords, i_coords]

    X_train = X_train_all_features[feature_indices, :].T

    print(f"[{os.getpid()}] Training data shape: {X_train.shape}, y_train shape: {y_train.shape}", flush=True)
    print(f"[{os.getpid()}] Training RandomForest on {len(y_train)} samples...", flush=True)

    n_jobs = 4 if is_full_inference else 1
    start = time.perf_counter()
    model = RandomForestClassifier(
        n_estimators=64,
        n_jobs=n_jobs,
        warm_start=False,
        random_state=42,
        bootstrap=True,
        oob_score=True,
        min_impurity_decrease=0.001,
        class_weight="balanced",
    )
    model.fit(X_train, y_train)
    safe_dump_json({"is_trained": True}, paths.model_status)
    print(f"[{os.getpid()}] Model trained in {time.perf_counter() - start:.4f} seconds", flush=True)
    return model


def _predict_and_save(model, features, current_shape, extents, feature_indices, paths):
    print(f"[{os.getpid()}] Predicting on the extents area...", flush=True)
    i_min, i_max, j_min, j_max, k_min, k_max = extents

    mask_zyx = np.zeros(current_shape, dtype=bool)
    mask_zyx[k_min:k_max, j_min:j_max, i_min:i_max] = True

    n_features = features.shape[0]
    X_full_reshaped = features.reshape(n_features, -1).T
    X_predict = X_full_reshaped[mask_zyx.ravel()]

    if feature_indices is not None:
        X_predict = X_predict[:, feature_indices]
    print(f"[{os.getpid()}] Extracted {X_predict.shape[0]} samples for prediction.", flush=True)

    if X_predict.shape[0] > 0:
        start = time.perf_counter()
        predictions_flat = model.predict(X_predict)
        extent_shape = (k_max - k_min, j_max - j_min, i_max - i_min)
        result_labelmap = predictions_flat.reshape(extent_shape)
        print(f"[{os.getpid()}] Predictions made in {time.perf_counter() - start:.4f} seconds", flush=True)
    else:
        print(f"[{os.getpid()}] No data to predict within extents. Writing empty result.", flush=True)
        result_labelmap = np.array([], dtype=np.uint8)

    print(f"[{os.getpid()}] Saving result labelmap of shape {result_labelmap.shape}", flush=True)
    start = time.perf_counter()
    safe_save_npz(paths.result, result=result_labelmap.astype(np.uint8), extents=extents)
    print(f"[{os.getpid()}] Result saved in {time.perf_counter() - start:.4f} seconds", flush=True)


def _handle_task(task_params, paths, model, features, original_shape):
    action = task_params["action"]
    is_full_inference = task_params.get("is_full_inference", False)
    feature_indices = task_params.get("features")

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
            inference_source_array, inference_mmap_path, progress, feature_indices_to_calc=feature_indices
        )
        current_shape = current_features.shape[1:]
        # All features in the mmap file are used for prediction, so we pass None
        predict_feature_indices = None
        update_progress(paths.progress, 50, "Running inference on the full image...")

    if action == "write_empty":
        print(f"[{os.getpid()}] No training data available. Writing empty result.", flush=True)
        result_labelmap = np.zeros(current_shape, dtype=np.uint8)
        extents = np.array([0, current_shape[2], 0, current_shape[1], 0, current_shape[0]])
        safe_save_npz(paths.result, result=result_labelmap, extents=extents)
        safe_dump_json({"is_trained": False}, paths.model_status)
        return None  # Reset model

    if action == "train":
        # Training is always done on the original features cache
        model = _train_model(features, paths, feature_indices, is_full_inference)

    if model is None:
        print(f"[{os.getpid()}] Model not trained yet. Skipping prediction.", flush=True)
        return None

    extents = task_params["extents"]
    _predict_and_save(model, current_features, current_shape, extents, predict_feature_indices, paths)

    if is_full_inference:
        update_progress(paths.progress, 100, "Full segmentation complete.")

    return model


def run_consumer(data_dir: str):
    paths = InterprocessPaths(Path(data_dir))
    print(f"[{os.getpid()}] Consumer process started. Monitoring directory: {data_dir}", flush=True)

    features = _get_initial_features(paths)
    original_shape = features.shape[1:]
    model = None

    while True:
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

            model = _handle_task(task_params, paths, model, features, original_shape)

        except Exception as e:
            print(f"[{os.getpid()}] An error occurred in the consumer loop: {e}", flush=True)
            import traceback

            traceback.print_exc(file=sys.stdout)

        time.sleep(SLEEP_TIME)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Real-time segmentation consumer process.")
    parser.add_argument("--data-dir", type=str, required=True, help="Path to the directory for exchanging data.")
    args = parser.parse_args()

    try:
        run_consumer(args.data_dir)
    except Exception as e:
        import traceback

        print(f"[{os.getpid()}] Fatal error in consumer process: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        sys.exit(1)
