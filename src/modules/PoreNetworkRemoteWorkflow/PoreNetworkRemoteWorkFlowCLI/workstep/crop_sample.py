import math

import SimpleITK as sitk
import numpy as np

from .workstep import Workstep, WorkflowContext

TARGET_Z_PREVIEW_SIZE = 400


class CropSampleWorkstep(Workstep):
    def __init__(self, context: WorkflowContext):
        super().__init__(context)

    def _sample_segmentation(self):
        sitk_image = sitk.GetImageFromArray(self.context.array)

        # ---------------------------------------------------------
        # 1. Downsampling
        # ---------------------------------------------------------
        downsampling_factor = 0.5  # For faster sample segmentation
        original_spacing = sitk_image.GetSpacing()
        original_size = sitk_image.GetSize()
        new_spacing = [s / downsampling_factor for s in original_spacing]
        new_size = [
            int(math.ceil((orig_sz - 1) * orig_spc / new_spc)) + 1
            for orig_sz, orig_spc, new_spc in zip(original_size, original_spacing, new_spacing)
        ]

        # Prevent downsampling if the smallest dimension drops below 300
        if min(new_size) < 300:
            self.logger.info(
                f"Crop Sample downsampling skipped: minimum dimension would be {min(new_size)} pixels (threshold is 300)."
            )
            downsampling_factor = 1.0  # Reset so upsampling is also skipped in step 4
            working_image = sitk_image
        else:
            resample = sitk.ResampleImageFilter()
            resample.SetOutputSpacing(new_spacing)
            resample.SetSize(new_size)
            resample.SetOutputDirection(sitk_image.GetDirection())
            resample.SetOutputOrigin(sitk_image.GetOrigin())
            resample.SetInterpolator(sitk.sitkLinear)
            working_image = resample.Execute(sitk_image)

        # ---------------------------------------------------------
        # 2. Thresholding
        # ---------------------------------------------------------
        multi_otsu = sitk.OtsuMultipleThresholdsImageFilter()
        multi_otsu.SetNumberOfThresholds(3)
        labeled_image = multi_otsu.Execute(working_image)
        mask = sitk.BinaryThreshold(labeled_image, lowerThreshold=2, upperThreshold=3, insideValue=1, outsideValue=0)

        # ---------------------------------------------------------
        # 3. Morphological Cleanup (Slicer Logic)
        # ---------------------------------------------------------

        def keep_largest_island(sitk_mask):
            cc_filter = sitk.ConnectedComponentImageFilter()
            cc_filter.SetFullyConnected(True)
            cc = cc_filter.Execute(sitk_mask)
            relabel_filter = sitk.RelabelComponentImageFilter()
            relabel_filter.SetSortByObjectSize(True)
            relabeled = relabel_filter.Execute(cc)
            return sitk.BinaryThreshold(relabeled, lowerThreshold=1, upperThreshold=1, insideValue=1, outsideValue=0)

        def invert(sitk_mask):
            return sitk.BinaryThreshold(sitk_mask, lowerThreshold=0, upperThreshold=0, insideValue=1, outsideValue=0)

        def margin(sitk_mask, radius_pixels):
            radius = int(round(radius_pixels))
            if radius == 0:
                return sitk_mask

            if radius < 0:
                morph_filter = sitk.BinaryErodeImageFilter()
            else:
                morph_filter = sitk.BinaryDilateImageFilter()

            morph_filter.SetKernelType(sitk.sitkBall)
            morph_filter.SetKernelRadius([abs(radius)] * 3)
            morph_filter.SetForegroundValue(1)
            return morph_filter.Execute(sitk_mask)

        # Execute initial clean to isolate the main sample body
        mask = keep_largest_island(mask)  # Clear external specks

        # --- AUTO ERODE CALCULATION ---
        # View the mask array (Z, Y, X) without copying memory
        temp_mask_array = sitk.GetArrayViewFromImage(mask)
        # % of the smallest volume dimension
        smallest_dim = min(temp_mask_array.shape)
        erode_pixels = int(round(0.1 * smallest_dim / 2))
        self.logger.info(f"Auto Sample Segmentation: Calculated erode_pixels = {erode_pixels}")

        # ---------------------------------------------------------
        # Apply blank margin (padding)
        # ---------------------------------------------------------
        pad_amount = 2 * erode_pixels
        padding = [pad_amount, pad_amount, pad_amount]

        pad_filter = sitk.ConstantPadImageFilter()
        pad_filter.SetPadLowerBound(padding)
        pad_filter.SetPadUpperBound(padding)
        pad_filter.SetConstant(0)  # Blank margin
        mask = pad_filter.Execute(mask)

        # Continue cleaning sequence
        mask = invert(mask)
        mask = margin(mask, -erode_pixels)  # Fill internal vugs/pores by eroding the background
        mask = keep_largest_island(mask)
        mask = margin(mask, erode_pixels)  # Restore the external boundary
        mask = invert(mask)

        # ---------------------------------------------------------
        # Clip back to the original size
        # ---------------------------------------------------------
        crop_filter = sitk.CropImageFilter()
        crop_filter.SetLowerBoundaryCropSize(padding)
        crop_filter.SetUpperBoundaryCropSize(padding)
        mask = crop_filter.Execute(mask)

        # ---------------------------------------------------------
        # 4. Upsampling & Final Polish
        # ---------------------------------------------------------
        if downsampling_factor != 1.0:
            resample = sitk.ResampleImageFilter()
            resample.SetOutputSpacing(sitk_image.GetSpacing())
            resample.SetSize(sitk_image.GetSize())
            resample.SetOutputDirection(sitk_image.GetDirection())
            resample.SetOutputOrigin(sitk_image.GetOrigin())
            resample.SetInterpolator(sitk.sitkNearestNeighbor)
            mask = resample.Execute(mask)

        final_erosion_voxels = 2
        mask = margin(mask, -final_erosion_voxels)

        mask_array = sitk.GetArrayFromImage(mask).astype(bool)

        # ---------------------------------------------------------
        # 5. Clip Empty Z-Slices (Occupancy Threshold)
        # ---------------------------------------------------------
        slice_occupancy_threshold = 0.25
        z_dim, y_dim, x_dim = mask_array.shape
        min_required_pixels = slice_occupancy_threshold * y_dim * x_dim

        valid_slices = np.where(mask_array.sum(axis=(1, 2)) >= min_required_pixels)[0]

        if len(valid_slices) > 0:
            z_start = valid_slices[0]
            z_end = valid_slices[-1] + 1

            mask_array = mask_array[z_start:z_end, :, :]
            self.context.array = self.context.array[z_start:z_end, :, :]

        # Update context
        self.context.crop_sample_mask_array = mask_array
        self.context.array = np.where(mask_array, self.context.array, 0)

    def _cylindrical_crop(self):
        params = self.context.workflow_params["crop_sample_params"]

        # Assuming context.array is organized as (Z, Y, X)
        z_dim, y_dim, x_dim = self.context.array.shape

        center_x = params.get("center_x", -1)
        center_y = params.get("center_y", -1)
        radius = params.get("radius", -1)
        auto_reduction_percent = params.get("auto_radius_reduction", 5)

        # Apply default/Auto values if they are set to -1
        if center_x == -1:
            center_x = x_dim / 2.0
        if center_y == -1:
            center_y = y_dim / 2.0

        if radius == -1:
            # Calculate the max possible radius
            max_radius = min(x_dim, y_dim) / 2.0
            # Apply the dynamically defined percentage reduction
            reduction_factor = (100 - auto_reduction_percent) / 100.0
            radius = max_radius * reduction_factor

        # Create a fast 2D mask using numpy open grid
        y_indices, x_indices = np.ogrid[:y_dim, :x_dim]
        distance_squared = (x_indices - center_x) ** 2 + (y_indices - center_y) ** 2
        mask_2d = distance_squared <= radius**2

        # Broadcast the 2D circular mask to 3D cylinder
        mask_array = np.broadcast_to(mask_2d, (z_dim, y_dim, x_dim)).copy()

        # Update context
        self.context.crop_sample_mask_array = mask_array
        self.context.array = np.where(mask_array, self.context.array, 0)

    def _apply_z_discard(self):
        """
        Slices the context array and the context mask array along the Z-axis
        based on top and bottom discard percentages.
        """
        params = self.context.workflow_params["crop_sample_params"]
        z_bottom_pct = params.get("z_discard_bottom", 0)
        z_top_pct = params.get("z_discard_top", 0)

        if z_bottom_pct > 0 or z_top_pct > 0:
            z_dim_current = self.context.array.shape[0]

            if z_bottom_pct + z_top_pct >= 100:
                raise ValueError("Z crop percentages sum to 100% or more, resulting in an empty volume.")

            z_bottom_pixels = int(z_dim_current * (z_bottom_pct / 100.0))
            z_top_pixels = int(z_dim_current * (z_top_pct / 100.0))
            end_idx = z_dim_current - z_top_pixels

            # Update context
            self.context.crop_sample_mask_array = self.context.crop_sample_mask_array[z_bottom_pixels:end_idx, :, :]
            self.context.array = self.context.array[z_bottom_pixels:end_idx, :, :]

    def _fit_to_mask(self):
        """
        Crops the X, Y, and Z dimensions of the volume and mask arrays
        to tightly fit the bounding box of the active mask, removing
        unnecessary background data.
        """
        mask = self.context.crop_sample_mask_array

        # Guard against an entirely empty mask to prevent errors
        if not np.any(mask):
            self.logger.warning("Fit to Mask: Mask is completely empty. Skipping volume reduction.")
            return

        # Get all coordinates where the mask is active
        z_indices, y_indices, x_indices = np.where(mask)

        # Determine the bounding box (min and max across all 3 dimensions)
        z_min, z_max = z_indices.min(), z_indices.max()
        y_min, y_max = y_indices.min(), y_indices.max()
        x_min, x_max = x_indices.min(), x_indices.max()

        # Slice both arrays to the bounding box (+1 because upper bounds are exclusive)
        self.context.crop_sample_mask_array = mask[z_min : z_max + 1, y_min : y_max + 1, x_min : x_max + 1]
        self.context.array = self.context.array[z_min : z_max + 1, y_min : y_max + 1, x_min : x_max + 1]

        self.logger.info(
            f"Bounding Box Fit: Reduced volume bounds to Z[{z_min}:{z_max}], Y[{y_min}:{y_max}], X[{x_min}:{x_max}]"
        )

    def execute(self):
        params = self.context.workflow_params["crop_sample_params"]
        method = params["method"]

        # 1. Resolve "Auto" to a concrete method
        if method == "Auto":
            if self.sample_fills_volume():
                if self.blurry_edges():
                    method = "Cylindrical crop"
                    self.logger.info("Auto Crop: Sample fills volume and has blurry edges -> Using Cylindrical crop")
                else:
                    method = "None"
                    self.logger.info("Auto Crop: Sample fills volume but edges are sharp -> Skipping XY crop")
            else:
                method = "Sample segmentation"
                self.logger.info("Auto Crop: Sample terminates early -> Using Sample segmentation")

            # Update params so downstream logs/steps know what was automatically chosen
            self.context.workflow_params["crop_sample_params"]["method"] = method

        # 2. Execute the chosen method (whether set manually or resolved by Auto)
        if method == "Cylindrical crop":
            self._cylindrical_crop()
        elif method == "Sample segmentation":
            self._sample_segmentation()
        elif method == "None":
            self.context.crop_sample_mask_array = np.ones(self.context.array.shape, dtype=bool)
        else:
            raise ValueError(f"Unknown crop sample method: {method}")

        # 3. Apply Z discard and tight bounding box fit
        self._apply_z_discard()
        self._fit_to_mask()

        # Print the final array shape after all cropping is completed
        self.logger.info(f"Final array size after cropping: {self.context.array.shape}")

        # --- NEW: UPDATE CACHED SHAPE ---
        self.context.array_shape = self.context.array.shape

        # 4. Export results
        self._export_nc(
            self.context.crop_sample_mask_array.astype(np.uint8),
            "cropped_sample_mask",
            "cropped_sample_mask",
            labels=["Name,Index,Color", "Mask,1,#0080ff"],
        )
        self._export_nc(self.context.array, "cropped_sample", "cropped_sample")
