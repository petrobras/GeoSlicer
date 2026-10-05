import gc
import json
import math
import shutil
import subprocess
import sys

import numpy as np

from ltrace.remote.object_transfer import JsonObjectTransfer, NumpyArrayObjectTransfer
from .workstep import Workstep, WorkflowContext, deep_update


class ExtractorWorkstep(Workstep):
    def __init__(self, context: WorkflowContext):
        super().__init__(context)

    @staticmethod
    def _bounds_from_geometry(spacing, origin, shape):
        spacing = np.array(spacing)
        origin = np.array(origin)
        shape = np.array(shape)
        min_bounds = origin - 0.5 * spacing
        max_bounds = origin + (shape - 0.5) * spacing
        return min_bounds[0], max_bounds[0], min_bounds[1], max_bounds[1], min_bounds[2], max_bounds[2]

    @staticmethod
    def _parse_walltime_to_seconds(walltime_str: str) -> int:
        """Parse SLURM walltime formats (D-HH:MM:SS, HH:MM:SS, MM:SS) into total seconds."""
        if not isinstance(walltime_str, str):
            return 72 * 3600  # Default fallback (72 hours)

        days = 0
        if "-" in walltime_str:
            days_str, walltime_str = walltime_str.split("-", 1)
            days = int(days_str)

        parts = list(map(int, walltime_str.split(":")))
        if len(parts) == 3:
            hours, minutes, seconds = parts
        elif len(parts) == 2:
            hours, minutes, seconds = 0, parts[0], parts[1]
        elif len(parts) == 1:
            hours, minutes, seconds = parts[0], 0, 0
        else:
            return 72 * 3600

        return days * 86400 + hours * 3600 + minutes * 60 + seconds

    @staticmethod
    def _format_seconds_to_walltime(seconds: int) -> str:
        """Format total seconds into HH:MM:SS string format."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _get_fractional_walltime(self, fraction: float = 0.25, default: str = "72:00:00") -> str:
        """Retrieve workflow walltime and calculate the specified fraction (25%)."""
        workflow_walltime = (
            self.context.workflow_params.get("walltime") or getattr(self.context, "walltime", None) or default
        )
        total_seconds = self._parse_walltime_to_seconds(str(workflow_walltime))
        fractional_seconds = max(60, int(total_seconds * fraction))  # Ensure minimum 1 minute
        return self._format_seconds_to_walltime(fractional_seconds)

    def _export_input_files(self):
        base_name = "extractor_input"
        with NumpyArrayObjectTransfer(str(self.context.working_dir), base_name) as transfer:
            transfer.save(self.context.porosity_map)
        with JsonObjectTransfer(str(self.context.working_dir), f"{base_name}.json") as transfer:
            transfer.save({"spacing": self.context.spacing})
        self.logger.info(f"Saved extractor input files to: {self.context.working_dir}")

    def _update_extractor_params(self, params):
        ijk_to_ras_matrix = np.eye(4)
        ijk_to_ras_matrix[:3, :3] = self.context.ijk_to_ras_matrix_3_by_3
        bounds_tuple = self._bounds_from_geometry(
            self.context.spacing, self.context.origin, self.context.porosity_map.shape
        )

        new_params = {
            "metadata": {
                "spacing": self.context.spacing,
                "origin": self.context.origin,
                "ijktorasmatrix": ijk_to_ras_matrix.tolist(),
                "bounds": bounds_tuple,
            },
            "is_multiscale": True,
        }
        deep_update(params, new_params)

    def _run_extractor_cli(self, volume_shape):
        # Calculate anisotropic divisions per axis
        divs = [math.ceil(s / 600) for s in volume_shape]

        cli_script = self.cli_modules_dir / "PoreNetworkExtractorCLI" / "PoreNetworkExtractorCLI.py"
        cli_params = {
            "scalar": str(self.context.working_dir / "extractor_input"),
            "cwd": str(self.context.working_dir),
            "slurm": True,
            "no_save_watershed": True,
            "divs": json.dumps(divs),
        }

        total_chunks = math.prod(divs)

        # Estimate memory consumption per chunk
        chunk_shape = [math.ceil(s / d) for s, d in zip(volume_shape, divs)]
        voxels_per_chunk = math.prod(chunk_shape)
        bytes_per_voxel = 8
        overhead_factor = 20
        chunk_mem_bytes = voxels_per_chunk * bytes_per_voxel * overhead_factor
        chunk_mem_gb = math.ceil(chunk_mem_bytes / (1024**3))

        slurm_memory_gb = min(256, chunk_mem_gb)
        slurm_memory = f"{slurm_memory_gb}GB"
        slurm_jobs = math.ceil(total_chunks / 3)

        # Compute 25% of workflow walltime
        slurm_walltime = self._get_fractional_walltime(fraction=0.25)

        self.logger.info(
            f"SLURM parameters: divs={divs}, total_chunks={total_chunks}, chunk_shape={chunk_shape}, "
            f"voxels_per_chunk={voxels_per_chunk}, bytes_per_voxel={bytes_per_voxel}, overhead_factor={overhead_factor}, "
            f"chunk_mem_bytes={chunk_mem_bytes}, chunk_mem_gb={chunk_mem_gb}, slurm_memory_gb={slurm_memory_gb}, "
            f"slurm_memory='{slurm_memory}', slurm_jobs={slurm_jobs}, slurm_walltime='{slurm_walltime}'"
        )

        cli_params.update(
            {
                "slurm_jobs": str(slurm_jobs),
                "slurm_cores": str(1),
                "slurm_memory": slurm_memory,
                "slurm_walltime": slurm_walltime,
            }
        )

        args = []
        for k, v in cli_params.items():
            if isinstance(v, bool):
                if v:
                    args.append(f"--{k}")
            else:
                args.extend([f"--{k}", str(v)])

        cmd = [sys.executable, str(cli_script)] + args
        result = subprocess.run(cmd, cwd=str(self.context.working_dir), capture_output=True, text=True, check=True)
        self.logger.info(f"Extractor CLI completed successfully: {result}")

    def execute(self):
        try:
            params = self.context.workflow_params["extractor_params"]
            self._update_extractor_params(params)

            with open(self.context.working_dir / "extractor_params_dict.json", "w") as f:
                json.dump(params, f, indent=4)

            self._export_input_files()

            vol_shape = self.context.porosity_map.shape
            self.context.porosity_map = None
            gc.collect()

            self.logger.info(f"Running extractor for {self.context.working_dir.name}")
            self._run_extractor_cli(volume_shape=vol_shape)

        finally:
            # Clean up all generated input sidecars after execution
            for fname in ["extractor_input.npy", "extractor_input.json"]:
                input_file = self.context.working_dir / fname
                if input_file.exists():
                    input_file.unlink()
                    self.logger.info(f"Cleaned up input file: {input_file}")

            # Clean up the regions_npy_stack directory and all its contents
            regions_dir = self.context.working_dir / "regions_npy_stack"
            if regions_dir.exists() and regions_dir.is_dir():
                shutil.rmtree(regions_dir)
                self.logger.info(f"Cleaned up directory: {regions_dir}")
