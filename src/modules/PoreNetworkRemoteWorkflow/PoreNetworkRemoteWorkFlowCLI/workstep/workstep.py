import collections.abc
import json
import logging
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import xarray as xr

# Attempt to import psutil for accurate OS-level process memory monitoring
try:
    import psutil
except ImportError:
    psutil = None


def deep_update(d, u):
    """Recursively updates a dictionary."""
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = deep_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


class DaskMemoryLoggerFilter(logging.Filter):
    """
    A logging filter that dynamically intercepts log records and prefixes them
    with the current working directory's disk usage and the Dask worker's memory consumption.
    """

    def __init__(self, working_dir: Optional[Path] = None):
        super().__init__()
        self.working_dir = working_dir

    def filter(self, record):
        # 1. Calculate disk space used by the current working directory
        disk_str = "   N/A   "  # 9-character alignment fallback
        if self.working_dir and self.working_dir.exists():
            try:
                disk_bytes = sum(f.stat().st_size for f in self.working_dir.rglob("*") if f.is_file())
                if disk_bytes >= 1024**3:
                    disk_str = f"{disk_bytes / (1024**3):>5.1f} GB"
                else:
                    disk_str = f"{int(disk_bytes / (1024**2)):>5d} MB"
            except Exception:
                pass

        # 2. Calculate process memory consumption
        if psutil is not None:
            try:
                process = psutil.Process()
                mem_bytes = process.memory_info().rss

                # Convert bytes to human-readable format, 6 digits wide, right-aligned
                if mem_bytes >= 1024**3:
                    mem_str = f"{mem_bytes / (1024**3):>5.1f} GB"
                else:
                    mem_str = f"{int(mem_bytes / (1024**2)):>5d} MB"

                # Check if we are executing within an active Dask worker process
                try:
                    from dask.distributed import get_worker

                    prefix = f"[Disk: {disk_str}] [Mem: {mem_str}]"
                except (ValueError, ImportError):
                    # Fallback if executing outside an active Dask distributed worker
                    prefix = f"[Disk: {disk_str}] [Local Process Mem: {mem_str}]"
            except Exception:
                prefix = f"[Disk: {disk_str}] [Mem: N/A]"
        else:
            prefix = f"[Disk: {disk_str}] [Mem: psutil missing]"

        # Inject the prefix right before the log gets written
        record.msg = f"{prefix} {record.msg}"
        return True


@dataclass
class WorkflowContext:
    # 0. Configuration & Inputs
    working_dir: Path
    workflow_params: dict
    netcdf_file_path: Optional[Path] = None

    # 1. Base Data
    array: Optional[np.ndarray] = None
    array_shape: Optional[Tuple[int, ...]] = None

    # 2. Spatial Information
    spacing: Optional[Tuple[float, float, float]] = None
    origin: Optional[Tuple[float, float, float]] = None
    ijk_to_ras_matrix_3_by_3: Optional[Tuple[Tuple[int, int, int], ...]] = None

    # 3. Metadata
    nrrd_header: Optional[Dict[str, Any]] = None
    nc_metadata: Optional[Dict[str, Any]] = None

    # 4. Workstep-Specific Outputs
    crop_sample_mask_array: Optional[np.ndarray] = None
    porosity_map: Optional[np.ndarray] = None

    # 5. Shared Computed Flags
    sample_fills_volume: Optional[bool] = None
    blurry_edges: Optional[bool] = None

    def __post_init__(self):
        self.configs_dir = self.working_dir.parent

    def save_params(self):
        """Universally writes the updated parameters dictionary down to disk."""
        output_path = self.working_dir / "workflow_params_dict.json"
        with open(output_path, "w") as file:
            json.dump(self.workflow_params, file, indent=4)


class Workstep(ABC):
    def __init__(self, context: WorkflowContext):
        self.context = context
        self.cli_modules_dir = Path(__file__).resolve().parent.parent.parent

        logger_name = self.__class__.__name__.replace("Workstep", "")
        self.logger = logging.getLogger(logger_name)

        # Automatically attach or update the tracking filter on this step's logger
        existing_filter = next((f for f in self.logger.filters if isinstance(f, DaskMemoryLoggerFilter)), None)
        if existing_filter:
            existing_filter.working_dir = self.context.working_dir
        else:
            self.logger.addFilter(DaskMemoryLoggerFilter(self.context.working_dir))

        # Centralized execution wrapper with graceful failure isolation
        orig_execute = self.execute

        def wrapper(*args, **kwargs):
            try:
                # 1. Attempt to run the actual workstep logic
                result = orig_execute(*args, **kwargs)

                # 2. Only mark as done if execution completes with absolutely no errors
                self.save_workflow_params()
                return result

            except subprocess.CalledProcessError as e:
                # Handle and log CLI failures, but do NOT raise. Let the pipeline continue.
                stderr_msg = e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr
                self.logger.error(f"CLI execution failed in {logger_name}: {stderr_msg}")
                return None

            except Exception as e:
                # Handle and log Python runtime bugs, but do NOT raise. Let the pipeline continue.
                self.logger.error(f"Unhandled exception in {logger_name}: {e}", exc_info=True)
                return None

        self.execute = wrapper

    @abstractmethod
    def execute(self) -> None:
        pass

    def save_workflow_params(self):
        class_name = self.__class__.__name__
        self.context.workflow_params[f"{class_name}_done"] = True
        self.context.save_params()
        self.logger.info(f"Successfully auto-saved workflow parameters configuration.")

    def sample_fills_volume(self) -> bool:
        """
        Determines if the physical sample extends completely to the edges of the 3D volume,
        evaluating the 4 lateral (X and Y) faces individually.
        Compares the mean intensity of each face to the mean intensity of the 50% interior.
        Returns False immediately if any single face fails the density check.
        Caches the result in the context so it only executes once per workflow.
        """
        if self.context.sample_fills_volume is not None:
            return self.context.sample_fills_volume

        sample_array = self.context.array[::2, ::2, ::2]
        z_dim, y_dim, x_dim = sample_array.shape

        z_int_margin = max(1, int(z_dim * 0.25))
        y_int_margin = max(1, int(y_dim * 0.25))
        x_int_margin = max(1, int(x_dim * 0.25))

        interior_voxels = sample_array[
            z_int_margin:-z_int_margin, y_int_margin:-y_int_margin, x_int_margin:-x_int_margin
        ]
        interior_mean = np.mean(interior_voxels)

        if interior_mean <= 0:
            self.context.sample_fills_volume = False
            return False

        y_face_margin = max(1, int(y_dim * 0.05))
        x_face_margin = max(1, int(x_dim * 0.05))

        faces = {
            "Y-front": sample_array[:, :y_face_margin, :],
            "Y-back": sample_array[:, -y_face_margin:, :],
            "X-left": sample_array[:, :, :x_face_margin],
            "X-right": sample_array[:, :, -x_face_margin:],
        }

        for face_name, face_voxels in faces.items():
            face_mean = np.mean(face_voxels)
            density_ratio = face_mean / interior_mean

            self.logger.info(f"sample_fills_volume density ratio ({face_name}): {density_ratio:.4f}")

            if density_ratio < 0.75:
                self.context.sample_fills_volume = False
                return False

        self.context.sample_fills_volume = True
        return True

    def blurry_edges(self):
        """
        Determines if the corners outside an inscribed Z-axis cylinder have a lower
        relative intensity compared to the core inside the cylinder. Evaluates only
        the central 50% of the Z-axis height.
        """
        if self.context.sample_fills_volume is False:
            return None

        if self.context.blurry_edges is not None:
            return self.context.blurry_edges

        sample_array = self.context.array[::2, ::2, ::2]
        z_dim, y_dim, x_dim = sample_array.shape

        z_margin = max(1, int(z_dim * 0.25))
        core_z_array = sample_array[z_margin:-z_margin, :, :]

        cy, cx = y_dim / 2.0, x_dim / 2.0
        y_indices, x_indices = np.ogrid[:y_dim, :x_dim]
        dist_sq = (y_indices - cy) ** 2 + (x_indices - cx) ** 2

        r_max = min(y_dim, x_dim) / 2.0
        r_50 = r_max * 0.5

        center_mask_2d = dist_sq <= (r_50**2)
        r_outside = r_max * 1.15
        outside_mask_2d = dist_sq > (r_outside**2)

        center_intensities = core_z_array[:, center_mask_2d]
        outside_intensities = core_z_array[:, outside_mask_2d]

        if outside_intensities.size == 0 or center_intensities.size == 0:
            self.context.blurry_edges = False
            return False

        baseline = np.percentile(core_z_array, 5)
        center_val = np.median(center_intensities) - baseline
        outside_val = np.median(outside_intensities) - baseline
        outside_val = max(0, outside_val)

        if center_val <= 0:
            result = False
        else:
            intensity_ratio = outside_val / center_val
            self.logger.info(f"blurry_edges intensity ratio: {intensity_ratio:.3f}")
            result = bool(intensity_ratio < 0.60)

        self.context.blurry_edges = result
        return result

    def _export_nc(self, array, file_name, var_name=None, labels=None):
        if not self.context.workflow_params.get("save_workstep_image_data", False):
            return

        if self.context.nc_metadata is None:
            raise ValueError("nc_metadata is not set in context")

        var_name = var_name or self.context.nc_metadata.get("var_name", "data")
        dims = self.context.nc_metadata.get("dims")
        original_coords = self.context.nc_metadata.get("coords", {})
        var_attrs = self.context.nc_metadata.get("var_attrs", {}).copy()
        global_attrs = self.context.nc_metadata.get("global_attrs", {})

        if labels is not None:
            var_attrs["labels"] = labels

        new_coords = {}
        if original_coords:
            for i, dim in enumerate(dims):
                if dim in original_coords:
                    old_coord_array = np.asarray(original_coords[dim])
                    new_len = array.shape[i]
                    if len(old_coord_array) == new_len:
                        new_coords[dim] = old_coord_array
                    else:
                        start_val = old_coord_array[0]
                        direction = 1 if old_coord_array[-1] >= old_coord_array[0] else -1
                        step = direction * self.context.spacing[i]
                        new_coords[dim] = start_val + np.arange(new_len) * step

        new_dataarray = xr.DataArray(array, dims=dims, coords=new_coords if new_coords else None, attrs=var_attrs)
        new_dataset = xr.Dataset({var_name: new_dataarray}, attrs=global_attrs)

        output_path = self.context.working_dir / f"{file_name}.nc"
        encoding_dict = {var_name: {"zlib": True, "complevel": 4}}
        new_dataset.to_netcdf(str(output_path), encoding=encoding_dict, engine="h5netcdf")

        self.logger.info(f"Saved NetCDF to: {output_path}")
        return output_path
