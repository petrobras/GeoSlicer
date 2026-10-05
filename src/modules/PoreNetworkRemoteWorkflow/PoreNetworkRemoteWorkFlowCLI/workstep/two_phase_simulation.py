import json
import shutil
import subprocess
import sys

from .workstep import Workstep, WorkflowContext, deep_update

# UI Spacing Heuristics Constants
SPACING_TO_MEAN_RADIUS = 0.5
SPACING_TO_STD_DEV = 0.5
SPACING_TO_MIN_RADIUS = 0.05
SPACING_TO_MAX_RADIUS = 5.0
SPACING_TO_CUTOFF_RADIUS = 2.0


def estimate_and_update_subscale_params(simulation_params: dict, spacing: list or tuple or dict) -> dict:
    """
    Estimates and updates subscale parameters based on the volume voxel spacing
    and the selected subscale model, matching the UI's 'on_estimate_clicked' behavior.
    """
    if isinstance(spacing, dict):
        min_spacing_mm = min(spacing["x"], spacing["y"], spacing["z"])
    else:
        min_spacing_mm = min(spacing)

    min_spacing_microns = min_spacing_mm * 1000.0
    model_name = simulation_params.get("subres_model_name", "Fixed Radius")

    if "subres_params" not in simulation_params or simulation_params["subres_params"] is None:
        simulation_params["subres_params"] = {}

    subres_params = simulation_params["subres_params"]
    existing_subres = subres_params.copy()

    if model_name == "Fixed Radius":
        radius_microns = round(min_spacing_microns * SPACING_TO_MEAN_RADIUS, 6)
        subres_params["radius"] = radius_microns * 0.001

    elif model_name == "Truncated Gaussian":
        subres_params["mean radius"] = round(min_spacing_microns * SPACING_TO_MEAN_RADIUS, 6) * 0.001
        subres_params["standard deviation"] = round(min_spacing_microns * SPACING_TO_STD_DEV, 6) * 0.001
        subres_params["min radius"] = round(min_spacing_microns * SPACING_TO_MIN_RADIUS, 6) * 0.001
        subres_params["max radius"] = round(min_spacing_microns * SPACING_TO_MAX_RADIUS, 6) * 0.001

    elif model_name == "Log Truncated Gaussian":
        subres_params["standard deviation"] = existing_subres.get("standard deviation", 0.5)
        subres_params["mean radius"] = round(min_spacing_microns * SPACING_TO_MEAN_RADIUS, 6) * 0.001
        subres_params["min radius"] = round(min_spacing_microns * SPACING_TO_MIN_RADIUS, 6) * 0.001
        subres_params["max radius"] = round(min_spacing_microns * SPACING_TO_MAX_RADIUS, 6) * 0.001

    elif model_name in ["Throat Radius Curve", "Pressure Curve"]:
        cutoff_microns = round(min_spacing_microns * SPACING_TO_CUTOFF_RADIUS, 6)
        subres_params["radii_cutoff_mm"] = cutoff_microns * 0.001

        for array_key in ["node id", "throat radii", "capillary pressure", "dsn"]:
            if array_key in existing_subres:
                subres_params[array_key] = existing_subres[array_key]

    return simulation_params


class TwoPhaseSimulationWorkstep(Workstep):
    SIRR_REMOTE_PATH = "/nethome/drp/servicos/LTRACE/ROMULO/Giovanni/micp/filtrados"
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
            "remote_execution": "T",
            "timeout_enabled": "F",
            "subres_model_name": params.get("subres_model_name", "Fixed Radius"),
            "subres_params": params.get("subres_params", {}) or {},
            "extraction_algorithm": "porespy",
            "save_tables": False,
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
        """Public entry point for Two-Phase simulation."""
        try:
            params = self.context.workflow_params["two_phase_simulation_params"]
            self._update_simulation_params(params)

            with open(self.context.working_dir / "two_phase_simulation_params_dict.json", "w") as f:
                json.dump(params, f, indent=4)

            self.logger.info(f"Running two-phase simulation for {self.context.working_dir.name}")
            self._run_simulation_cli("TwoPhaseSensibilityTest")
        finally:
            if self.context.working_dir.exists():
                removed_dirs = []
                for item in self.context.working_dir.iterdir():
                    if item.is_dir() and item.name.startswith("two_phase_sim_"):
                        shutil.rmtree(item)
                        removed_dirs.append(item.name)

                if removed_dirs:
                    self.logger.info(f"Cleaned up subprocess directories.")
