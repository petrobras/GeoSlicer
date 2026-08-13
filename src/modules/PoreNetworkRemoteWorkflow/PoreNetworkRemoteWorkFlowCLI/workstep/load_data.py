import numpy as np
import xarray as xr
from scipy.ndimage import zoom

from .workstep import Workstep, WorkflowContext
from ltrace.slicer.netcdf import get_origin, get_spacing

TARGET_Z_PREVIEW_SIZE = 400


class LoadDataWorkstep(Workstep):
    def __init__(self, context: WorkflowContext):
        super().__init__(context)

    def execute(self):
        downsampling_factor = self.context.workflow_params["downsampling_factor"]

        self.logger.info(f"Importing NetCDF file: {self.context.netcdf_file_path}")
        self.logger.info(f"Downsampling factor specified in workflow: {downsampling_factor}")

        dataset = xr.open_dataset(str(self.context.netcdf_file_path), engine="h5netcdf")
        var_name = list(dataset.data_vars)[0]
        var_dataset = dataset[var_name]

        self.context.nc_metadata = {
            "var_name": var_name,
            "dims": var_dataset.dims,
            "coords": dict(var_dataset.coords),
            "var_attrs": var_dataset.attrs.copy(),
            "global_attrs": dataset.attrs.copy(),
        }

        self.logger.info("Successfully extracted NetCDF metadata:")
        self.logger.info(f"  Target Variable Name: {var_name}")
        self.logger.info(f"  Dimensions: {var_dataset.dims}")
        self.logger.info(f"  Coordinates: {list(var_dataset.coords.keys())}")

        # Filter out heavy scanner configuration dumps from the logs
        EXCLUDED_LOG_ATTRS = {"pca", "pcr"}

        if var_dataset.attrs:
            self.logger.info("  Variable Attributes:")
            for attr_key, attr_val in var_dataset.attrs.items():
                if attr_key.lower() in EXCLUDED_LOG_ATTRS:
                    continue
                self.logger.info(f"    - {attr_key}: {attr_val}")
        else:
            self.logger.info("  Variable Attributes: None")

        if dataset.attrs:
            self.logger.info("  Global Attributes:")
            for attr_key, attr_val in dataset.attrs.items():
                if attr_key.lower() in EXCLUDED_LOG_ATTRS:
                    continue
                self.logger.info(f"    - {attr_key}: {attr_val}")
        else:
            self.logger.info("  Global Attributes: None")

        self.context.origin = get_origin(var_dataset)
        original_array = var_dataset.values
        base_spacing = get_spacing(var_dataset)

        self.logger.info(f"Original array size: {original_array.shape}")
        self.logger.info(f"Original spacing: {base_spacing}")

        # 1. Apply downsampling to the array first
        if downsampling_factor > 1:
            self.logger.info(
                f"Applying downsampling with a factor of {downsampling_factor} (Zoom zoom: {1 / downsampling_factor:.4f})"
            )

            array = zoom(original_array, 1 / downsampling_factor, order=1)

            # 2. Recalculate spacing using the true physical extent and the new shape
            self.context.spacing = tuple(
                (orig_dim * orig_space) / new_dim
                for orig_dim, orig_space, new_dim in zip(original_array.shape, base_spacing, array.shape)
            )

            self.logger.info(f"Downsampled array size: {array.shape}")
            self.logger.info(f"Downsampled spacing: {self.context.spacing}")
        else:
            array = original_array
            self.context.spacing = base_spacing
            self.logger.info(f"Downsampling factor is {downsampling_factor}; bypassed (no downsampling applied).")

        # 3. Calculate space directions using the updated precision spacing
        self.context.ijk_to_ras_matrix_3_by_3 = ((-1, 0, 0), (0, -1, 0), (0, 0, 1))
        space_directions = np.matmul(self.context.ijk_to_ras_matrix_3_by_3, np.diag(self.context.spacing))

        # 4. Build the NRRD header
        self.context.nrrd_header = {
            "space": "right-anterior-superior",
            "space directions": space_directions,
            "space origin": self.context.origin,
        }

        # Save array to context
        self.context.array = array
        self.context.array_shape = array.shape
        self._export_nc(array, "sample", "sample")
