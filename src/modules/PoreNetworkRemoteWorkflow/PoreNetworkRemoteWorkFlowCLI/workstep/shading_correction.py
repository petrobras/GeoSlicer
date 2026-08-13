import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import xarray as xr

from .workstep import WorkflowContext, Workstep


class ShadingCorrectionWorkstep(Workstep):
    cli_name = "PolynomialShadingCorrectionBigImageCLI"

    def __init__(self, context: WorkflowContext):
        super().__init__(context)

    def _save_nc_file(self, file_path: Path, array: np.ndarray, var_name: str, dims: list, attrs: dict) -> None:
        """Helper method to construct and save a NetCDF dataset to disk."""
        dataset = xr.DataArray(array, dims=dims, name=var_name, attrs=attrs).to_dataset()
        dataset.to_netcdf(file_path, engine="h5netcdf")

    def _run_big_image_shading_correction_cli(self, shading_correction_params):
        cli_script = (
            self.cli_modules_dir
            / "PolynomialShadingCorrectionBigImageCLI"
            / "PolynomialShadingCorrectionBigImageCLI.py"
        )

        absolute_output_path = self.context.working_dir / "output.nc"

        big_image_shading_correction_params = {
            "inputNodeId": "vtkMRMLScalarVolumeNode1",
            "inputShadingMaskNodeId": "vtkMRMLLabelMapVolumeNode2",
            "sliceGroupSize": shading_correction_params["slice_group_size"],
            "fittingPointsPercentage": shading_correction_params["fitting_points_percentage"],
            "functionType": shading_correction_params["function_type"],
            "polynomialOrder": shading_correction_params["polynomial_order"],
            "exportPath": absolute_output_path.as_posix(),
            "geoslicerVersion": "",
            "nullValue": 0,
            "inputLazyNodeUrl": f"file://{(self.context.working_dir / 'input.nc').as_posix()}",
            "inputLazyNodeVar": "input",
            "inputShadingMaskLazyNodeUrl": f"file://{(self.context.working_dir / 'shading.nc').as_posix()}",
            "inputShadingMaskLazyNodeVar": "shading",
            "inputLazyNodeHost": {"username": "", "name": "", "protocol": ""},
            "inputShadingMaskLazyNodeHost": {"username": "", "name": "", "protocol": ""},
        }
        cmd = [sys.executable, cli_script, "--params", json.dumps(big_image_shading_correction_params)]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        self.logger.info(f"Shading correction cli call completed successfully.")

        with xr.open_dataset(str(absolute_output_path), engine="h5netcdf") as output_dataset:
            shading_corrected_array = output_dataset[list(output_dataset.data_vars)[0]].values

        return shading_corrected_array

    def execute(self):
        params = self.context.workflow_params["shading_correction_params"]
        function_type = params["function_type"]

        if function_type == "Auto":
            if self.sample_fills_volume():
                if self.context.workflow_params["crop_sample"] and self.context.blurry_edges:
                    function_type = "Polynomial Radial"
                    self.logger.info("Auto Shading: Crop ON and sample fills volume -> Using Polynomial Radial")
                else:
                    function_type = "Spline Radial"
                    self.logger.info("Auto Shading: Crop OFF and sample fills volume -> Using Spline Radial")
            else:
                function_type = "Polynomial Radial"
                self.logger.info(
                    "Auto Shading: Sample terminates early (does not fill volume) -> Using Polynomial Radial"
                )
            self.context.workflow_params["shading_correction_params"]["function_type"] = function_type

        self.logger.info(f"Executing shading correction for {self.context.working_dir.name}")

        array = self.context.array
        nc_metadata = self.context.nc_metadata

        if self.context.crop_sample_mask_array is not None:
            mask_array = self.context.crop_sample_mask_array
        else:
            mask_array = np.ones_like(array, dtype=np.int16)

        dims = nc_metadata["dims"]
        attrs = nc_metadata["var_attrs"]

        input_nc_path = self.context.working_dir / "input.nc"
        shading_nc_path = self.context.working_dir / "shading.nc"
        output_nc_path = self.context.working_dir / "output.nc"

        try:
            self._save_nc_file(input_nc_path, array, "input", dims, attrs)

            valid_conditions = (mask_array != 0) & (array != 0)
            valid_values = array[valid_conditions]
            p_min = np.nanpercentile(valid_values, params["shading_mask_percentile_min"])
            p_max = np.nanpercentile(valid_values, params["shading_mask_percentile_max"])

            shading_mask_array = ((array >= p_min) & (array < p_max) & valid_conditions).astype(np.int16)
            self._save_nc_file(shading_nc_path, shading_mask_array, "shading", dims, attrs)

            shading_corrected_array = self._run_big_image_shading_correction_cli(params)

            self.context.array = shading_corrected_array

            self._export_nc(
                shading_mask_array, "shading_mask", "shading_mask", labels=["Name,Index,Color", "Mask,1,#0080ff"]
            )
            self._export_nc(shading_corrected_array, "shading_correction", "shading_correction")
        finally:
            for nc_file in (input_nc_path, shading_nc_path, output_nc_path):
                if nc_file.exists():
                    try:
                        nc_file.unlink()
                    except Exception as e:
                        self.logger.warning(f"Failed to remove temporary file {nc_file}: {e}")
