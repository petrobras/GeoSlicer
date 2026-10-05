"""The consumer process: load the source image, prepare what the mode needs up front,
then serve one task file at a time until the parent exits."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import psutil

from ltrace.interactive.features import FeatureScale
from ltrace.interactive.features_3d import allocate_feature_mmap, compute_feature_planes
from ltrace.interactive.ipc import FeatureIndex, InterprocessPaths, safe_dump_json
from ltrace.interactive.lazy_2d import Lazy2DState, handle_task_2d
from ltrace.interactive.reporting import update_progress
from ltrace.interactive.resources import available_cores
from ltrace.interactive.volume_3d import handle_task


SLEEP_TIME = 0.03


def run_consumer(data_dir: str, parent_pid: int, scale: FeatureScale):
    paths = InterprocessPaths(Path(data_dir))
    print(f"[{os.getpid()}] Consumer process started. Monitoring directory: {data_dir}", flush=True)
    print(f"[{os.getpid()}] Monitoring parent process with PID: {parent_pid}", flush=True)
    print(
        f"[{os.getpid()}] {available_cores()} usable cores "
        f"(affinity, capped by {psutil.cpu_count(logical=False)} physical)",
        flush=True,
    )

    print(f"[{os.getpid()}] Waiting for source image...", flush=True)
    while not paths.source.exists():
        time.sleep(SLEEP_TIME)

    print(f"[{os.getpid()}] Loading source image.", flush=True)
    # mmap keeps very large 2D mosaics out of memory; the 3D path copies it to RAM.
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
        # Features are lazy here, so preview-ready and features-complete coincide.
        safe_dump_json({"ready": True}, paths.preview_ready)
        safe_dump_json({"complete": True}, paths.features_complete)
    else:

        def progress(p, m):
            update_progress(paths.progress, p, m)

        # Every feature is computed up front, so switching preset never recomputes and no
        # background writer competes with the preview.
        source_array = np.asarray(source)
        features, n_channels = allocate_feature_mmap(source_array, paths.features_mmap)
        original_shape = source.shape[:3]

        compute_feature_planes(source_array, features, n_channels, list(FeatureIndex), scale, progress)
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
                handle_task_2d(task_params, paths, state)
            else:
                model = handle_task(task_params, paths, model, features, original_shape, scale)

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
        "--feature-scale",
        type=int,
        default=1,
        help="Multiplier (1/2/4) applied to every feature kernel size for coarser-textured images.",
    )
    args = parser.parse_args()

    scale = FeatureScale.from_multiplier(args.feature_scale)
    print(
        f"[{os.getpid()}] Feature scale {args.feature_scale}x: "
        f"sigmas={scale.gaussian_sigmas}, winvars={scale.winvar_sizes}",
        flush=True,
    )

    try:
        run_consumer(args.data_dir, args.parent_pid, scale)
    except Exception as e:
        import traceback

        print(f"[{os.getpid()}] Fatal error in consumer process: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        sys.exit(1)
