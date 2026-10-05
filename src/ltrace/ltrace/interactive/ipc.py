import os
import numpy as np
import json
import time

from pathlib import Path
from dataclasses import dataclass
from enum import Enum

# File names for data exchange
ANNOTATION_NAME = "annotation.npy"
RESULT_NAME = "result.npz"
TASK_NAME = "task.json"
SOURCE_NAME = "source.npy"
PROGRESS_NAME = "progress.json"
INFERENCE_SOURCE_NAME = "inference_source.npy"
MODEL_STATUS_NAME = "model_status.json"
FEATURES_MMAP_NAME = "features.mmap"
FULL_RESULT_MMAP_NAME = "full_result.mmap"
PYRAMID_LEVEL_NAME = "pyramid_level_{}.npy"
# Marker emitted by the consumer once enough features exist to serve a preview
# (the active preset's subset in 3D, the pyramid in 2D). The user may annotate
# before this; the first preview only appears once it is present.
PREVIEW_READY_NAME = "preview_ready.json"
# Marker emitted once every feature has been computed. Until then, switching to a
# feature preset that needs not-yet-computed features must be blocked (3D only).
FEATURES_COMPLETE_NAME = "features_complete.json"
# Intermediate arrays dumped by the 2D preview path when a task carries
# "debug": true, used to render a montage explaining how a preview was computed.
DEBUG_CAPTURE_NAME = "debug_capture.npz"
# Append-only JSON-lines log of what the full apply is doing, drained by the
# widget into the apply log. It is a separate channel from progress.json because
# that one is latest-wins -- two updates between two polls lose the first -- and
# a log that silently drops lines is worse than useless for debugging. The widget
# tails it by byte offset, so lines are never re-read nor lost.
APPLY_LOG_NAME = "apply_log.jsonl"

# Pixel budget for a single preview update. Visible regions larger than this are
# downsampled by a power-of-2 factor so that feature extraction plus prediction
# stays fast enough to feel interactive (target: under ~500 ms per update).
PREVIEW_MAX_PIXELS = 500_000


def compute_preview_factor(extents, max_pixels=PREVIEW_MAX_PIXELS) -> int:
    """
    Power-of-2 downscale factor so the visible region described by `extents`
    ([i_min, i_max, j_min, j_max, k_min, k_max], max-exclusive) fits the preview
    pixel budget. Both the widget and the consumer process use this so they
    agree on the factor without exchanging it.
    """
    i_min, i_max, j_min, j_max, _, _ = extents
    pixels = max(0, i_max - i_min) * max(0, j_max - j_min)
    factor = 1
    while pixels // (factor * factor) > max_pixels:
        factor *= 2
    return factor


class FeatureIndex(Enum):
    SOURCE = 0
    GAUSSIAN_A = 1
    GAUSSIAN_B = 2
    GAUSSIAN_C = 3
    GAUSSIAN_D = 4
    WINVAR_A = 5
    WINVAR_B = 6
    WINVAR_C = 7


FEATURE_NAMES = {
    FeatureIndex.SOURCE: "Raw Image",
    FeatureIndex.GAUSSIAN_A: "Gaussian Filter (sigma=1)",
    FeatureIndex.GAUSSIAN_B: "Gaussian Filter (sigma=2)",
    FeatureIndex.GAUSSIAN_C: "Gaussian Filter (sigma=4)",
    FeatureIndex.GAUSSIAN_D: "Gaussian Filter (sigma=8)",
    FeatureIndex.WINVAR_A: "Window Variance (size 5)",
    FeatureIndex.WINVAR_B: "Window Variance (size 9)",
    FeatureIndex.WINVAR_C: "Window Variance (size 13)",
}

# Single source of truth for the feature-set presets, mapping each preset name
# (in display order) to the features it selects. The UI combobox items and every
# preset->feature lookup (in both the widget and the logic) derive from this, so
# a preset can be added or renamed in one place without the shown list silently
# diverging from the features actually used.
FI = FeatureIndex
PRESETS = {
    "Sharp": [FI.SOURCE, FI.GAUSSIAN_A, FI.GAUSSIAN_B, FI.WINVAR_A],
    "Balanced": [FI.SOURCE, FI.GAUSSIAN_A, FI.GAUSSIAN_B, FI.GAUSSIAN_C, FI.WINVAR_A, FI.WINVAR_B],
    "Smooth": [FI.GAUSSIAN_A, FI.GAUSSIAN_B, FI.GAUSSIAN_C, FI.GAUSSIAN_D, FI.WINVAR_A, FI.WINVAR_B],
    "Extra Smooth": [FI.GAUSSIAN_B, FI.GAUSSIAN_C, FI.GAUSSIAN_D, FI.WINVAR_A, FI.WINVAR_B],
    "Complete": list(FI),
}
del FI


def preset_feature_indices(preset_name):
    """
    Integer feature indices selected by a preset. Raises ValueError on an unknown
    name (the combobox is populated from PRESETS, so every name reaching here is
    valid; an unknown one is a programming error, not a user condition).
    """
    if preset_name not in PRESETS:
        raise ValueError(f"Unknown feature set: {preset_name}")
    return [feature.value for feature in PRESETS[preset_name]]


@dataclass
class InterprocessPaths:
    """Manages the paths for data exchange between processes."""

    base_dir: Path

    @property
    def annotation(self) -> Path:
        return self.base_dir / ANNOTATION_NAME

    @property
    def result(self) -> Path:
        return self.base_dir / RESULT_NAME

    @property
    def task(self) -> Path:
        return self.base_dir / TASK_NAME

    @property
    def source(self) -> Path:
        return self.base_dir / SOURCE_NAME

    @property
    def progress(self) -> Path:
        return self.base_dir / PROGRESS_NAME

    @property
    def inference_source(self) -> Path:
        return self.base_dir / INFERENCE_SOURCE_NAME

    @property
    def model_status(self) -> Path:
        return self.base_dir / MODEL_STATUS_NAME

    @property
    def features_mmap(self) -> Path:
        return self.base_dir / FEATURES_MMAP_NAME

    @property
    def full_result_mmap(self) -> Path:
        return self.base_dir / FULL_RESULT_MMAP_NAME

    @property
    def preview_ready(self) -> Path:
        return self.base_dir / PREVIEW_READY_NAME

    @property
    def features_complete(self) -> Path:
        return self.base_dir / FEATURES_COMPLETE_NAME

    def pyramid_level(self, level: int) -> Path:
        return self.base_dir / PYRAMID_LEVEL_NAME.format(level)

    @property
    def debug_capture(self) -> Path:
        return self.base_dir / DEBUG_CAPTURE_NAME

    @property
    def apply_log(self) -> Path:
        return self.base_dir / APPLY_LOG_NAME


def safe_replace(src: Path, dst: Path):
    for _ in range(50):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            time.sleep(0.02)
    raise RuntimeError(f"Failed to replace {src} with {dst} after multiple attempts.")


def safe_unlink(path: Path):
    """Delete a file the consumer may still hold open mid-rewrite on Windows
    (WinError 32). Retries like safe_replace and tolerates an already-gone file.

    Use this wherever the delete must actually happen before proceeding. The
    update loop can instead swallow the error and retry on its next tick, but a
    one-shot caller (e.g. the Apply handler) has no next tick: skipping the
    delete would leave a stale result for the next read to pick up."""
    for _ in range(50):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.02)
    raise RuntimeError(f"Failed to delete {path} after multiple attempts.")


def safe_read_json(path: Path):
    """Read a JSON file the consumer may be mid-rewrite of: its atomic replace
    (see safe_replace) briefly denies readers on Windows (PermissionError).
    Retries like safe_replace. Use where the read must resolve; a periodic caller
    can instead tolerate the error and retry on its next tick."""
    for _ in range(50):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except PermissionError:
            time.sleep(0.02)
    raise RuntimeError(f"Failed to read {path} after multiple attempts.")


def safe_save_numpy(array: np.ndarray, path: Path):
    """
    Saves a numpy array to a temporary file and then atomically renames it
    to the final destination. This prevents race conditions where a consumer
    process might read an incompletely written file.

    Args:
        array (np.ndarray): The numpy array to save.
        path (Path): The final destination path for the file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp.npy")
    np.save(temp_path, array)
    safe_replace(temp_path, path)


def safe_save_numpy_stacked(arrays, path: Path):
    """
    Save multiple co-registered images as one channel-stacked array, writing
    directly to a memory-mapped file so the combined array (which can be
    several GB for large multi-image inputs) never has to fit in memory.
    Arrays of shape (K, J, I) are treated as single-channel (K, J, I, 1).

    Like safe_save_numpy, the file is written to a temporary path and renamed
    atomically so the consumer never reads a partial file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = [array if array.ndim == 4 else array[..., np.newaxis] for array in arrays]
    spatial = arrays[0].shape[:3]
    total_channels = sum(array.shape[3] for array in arrays)
    dtype = np.result_type(*[array.dtype for array in arrays])

    temp_path = path.with_suffix(".tmp.npy")
    stacked = np.lib.format.open_memmap(temp_path, mode="w+", dtype=dtype, shape=spatial + (total_channels,))
    channel = 0
    for array in arrays:
        stacked[..., channel : channel + array.shape[3]] = array
        channel += array.shape[3]
    stacked.flush()
    del stacked
    safe_replace(temp_path, path)


def safe_save_npz(path: Path, **kwargs):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp.npz")
    np.savez(temp_path, **kwargs)
    safe_replace(temp_path, path)


def safe_dump_json(data, path: Path):
    """
    Saves a dictionary to a JSON file atomically.

    Args:
        data (dict): The data to save.
        path (Path): The final destination path for the JSON file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp.json")
    with open(temp_path, "w") as f:
        json.dump(data, f)
    safe_replace(temp_path, path)
