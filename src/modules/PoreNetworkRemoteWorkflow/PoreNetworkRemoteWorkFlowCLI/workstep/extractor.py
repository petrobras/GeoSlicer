import gc
import json
import subprocess
import sys

import nrrd
import numpy as np

from ltrace.remote.slurm import calculate_slurm_parameters
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

    def _export_input_nrrd(self):
        extractor_input_path = self.context.working_dir / "extractor_input.nrrd"
        # Need to swap axes if nrrd input is directly loaded by extractor CLI. To load by GeoSlicer, np.swapaxes is not needed
        nrrd.write(str(extractor_input_path), np.swapaxes(self.context.porosity_map, 0, 2), self.context.nrrd_header)
        self.logger.info(f"Saved extractor input to: {extractor_input_path}")

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

    def _run_extractor_cli(self, volume_shape, volume_size, volume_itemsize):
        # 1. Automatically calculate `divs` based on the volume size
        TARGET_CHUNK_BYTES = 200 * 1024 * 1024
        volume_bytes = volume_size * volume_itemsize
        chunks_needed = max(1.0, volume_bytes / TARGET_CHUNK_BYTES)
        # divs = max(1, round(chunks_needed ** (1 / 3)))
        divs = 1  # Temporary forcing divs 1 for the DS factor studies

        self.logger.info(f"Calculated optimal divs: {divs} (Volume size: {volume_bytes / 1024**2:.2f} MB)")

        calculated_slurm_params = calculate_slurm_parameters(
            volume_shape=volume_shape, itemsize=volume_itemsize, divs=divs
        )

        cli_script = self.cli_modules_dir / "PoreNetworkExtractorCLI" / "PoreNetworkExtractorCLI.py"
        cli_params = {
            "scalar": str(self.context.working_dir / "extractor_input.nrrd"),
            "cwd": str(self.context.working_dir),
            "slurm": False,
            "no_save_watershed": True,
            "divs": str(divs),
            # "slurm_jobs": str(calculated_slurm_params["slurm_jobs"]),
            # "slurm_cores": str(calculated_slurm_params["slurm_cores"]),
            # "slurm_memory": f"{calculated_slurm_params['slurm_memory_gb']}GB",
        }

        args = []
        for k, v in cli_params.items():
            if isinstance(v, bool):
                if v:
                    args.append(f"--{k}")
            else:
                args.extend([f"--{k}", str(v)])

        cmd = [sys.executable, str(cli_script)] + args
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        self.logger.info(f"Extractor cli call result: {result}")

    def execute(self):
        try:
            params = self.context.workflow_params["extractor_params"]
            self._update_extractor_params(params)

            with open(self.context.working_dir / "extractor_params_dict.json", "w") as f:
                json.dump(params, f, indent=4)

            self._export_input_nrrd()

            vol_shape = self.context.porosity_map.shape
            vol_size = self.context.porosity_map.size
            vol_itemsize = self.context.porosity_map.itemsize

            self.context.porosity_map = None
            gc.collect()

            self.logger.info(f"Running extractor for {self.context.working_dir.name}")
            self._run_extractor_cli(volume_shape=vol_shape, volume_size=vol_size, volume_itemsize=vol_itemsize)

        finally:
            # Clean up the input file after execution or error
            input_file = self.context.working_dir / "extractor_input.nrrd"
            if input_file.exists():
                input_file.unlink()
                self.logger.info(f"Cleaned up input file: {input_file}")
