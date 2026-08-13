import json
import subprocess
import sys

import numpy as np

from .two_phase_simulation import estimate_and_update_subscale_params
from .workstep import Workstep, WorkflowContext, deep_update


class OnePhaseSimulationWorkstep(Workstep):
    cli_name = "PoreNetworkSimulationCLI"

    def __init__(self, context: WorkflowContext):
        super().__init__(context)

    def _update_simulation_params(self, params):
        axis_keys = ["x", "y", "z"]
        spacing = self.context.spacing
        shape = self.context.array_shape

        new_params = {
            "spacing": dict(zip(axis_keys, spacing)),
            "size": dict(zip(axis_keys, [float(shape * spacing) for shape, spacing in zip(shape, spacing)])),
            "ijktoras": np.sign(self.context.ijk_to_ras_matrix_3_by_3).tolist(),
            "subres_model_name": params.get("subres_model_name", "Fixed Radius"),
            "subres_params": params.get("subres_params", {}) or {},
            "is_multiscale": True,
            "advanced visualization": False,
        }
        new_params = estimate_and_update_subscale_params(new_params, spacing)
        deep_update(params, new_params)

    def _run_simulation_cli(self, model):
        cli_script = self.cli_modules_dir / "PoreNetworkSimulationCLI" / "PoreNetworkSimulationCLI.py"
        cli_params = {"model": model, "cwd": str(self.context.working_dir), "tempDir": str(self.context.working_dir)}
        args = [item for k, v in cli_params.items() for item in (f"--{k}", v)]
        cmd = [sys.executable, str(cli_script)] + args
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        self.logger.info(f"Simulation cli call result for {model}: {result}")

    def execute(self):
        """Public entry point for One-Phase simulation."""
        params = self.context.workflow_params["one_phase_simulation_params"]
        self._update_simulation_params(params)

        with open(self.context.working_dir / "one_phase_simulation_params_dict.json", "w") as f:
            json.dump(params, f, indent=4)

        self.logger.info(f"Running one-phase simulation for {self.context.working_dir.name}")
        self._run_simulation_cli("onePhase")
