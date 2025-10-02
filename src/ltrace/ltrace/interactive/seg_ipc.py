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
    FeatureIndex.WINVAR_A: "Window Variance (5x5x5)",
    FeatureIndex.WINVAR_B: "Window Variance (9x9x9)",
    FeatureIndex.WINVAR_C: "Window Variance (13x13x13)",
}


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


def safe_replace(src: Path, dst: Path):
    for _ in range(50):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            time.sleep(0.02)
    raise RuntimeError(f"Failed to replace {src} with {dst} after multiple attempts.")


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
