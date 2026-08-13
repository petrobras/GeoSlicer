import gc
import json
import subprocess
import sys

import nrrd
import numpy as np
from scipy.ndimage import binary_erosion
from skimage.filters.thresholding import threshold_otsu, threshold_multiotsu

from .workstep import Workstep, WorkflowContext


class PorosityMapWorkstep(Workstep):
    def __init__(self, context: WorkflowContext):
        super().__init__(context)

    def _generate_multiotsu_porosity_map(self, array, porosity_map_params):
        """Fallback method using 3-phase Multi-Otsu when experimental porosity is missing."""
        self.logger.info("Experimental phi is None. Using 3-phase Multi-Otsu for porosity map.")

        mask = self.context.crop_sample_mask_array
        if mask is not None and self.context.workflow_params.get("crop_sample", False):
            sample_pixels = array[mask]
        else:
            sample_pixels = array.flatten()

        upper_limit = np.quantile(sample_pixels, 0.9)
        clipped_pixels = np.clip(sample_pixels, a_min=None, a_max=upper_limit)

        thresholds = threshold_multiotsu(clipped_pixels, classes=3)
        t1, t2 = thresholds[0], thresholds[1]

        fraction1 = np.mean(sample_pixels <= t1)
        fraction2 = np.mean(sample_pixels <= t2)

        shift1 = porosity_map_params.get("multi_otsu_shift1", 0.0) / 100.0
        shift2 = porosity_map_params.get("multi_otsu_shift2", 0.0) / 100.0

        fraction1_shifted = np.clip(fraction1 + shift1, 0.0, 1.0)
        fraction2_shifted = np.clip(fraction2 + shift2, 0.0, 1.0)

        if fraction1_shifted >= fraction2_shifted:
            fraction2_shifted = np.clip(fraction1_shifted + 1e-5, 0.0, 1.0)
            if fraction1_shifted >= fraction2_shifted:
                fraction1_shifted = fraction2_shifted - 1e-5

        t1_shifted = np.quantile(sample_pixels, fraction1_shifted)
        t2_shifted = np.quantile(sample_pixels, fraction2_shifted)

        self.logger.info(
            f"Multi-Otsu base thresholds: t1={t1:.4f} (frac: {fraction1:.4f}), t2={t2:.4f} (frac: {fraction2:.4f})"
        )
        self.logger.info(
            f"Multi-Otsu shifted thresholds: t1={t1_shifted:.4f} (frac: {fraction1_shifted:.4f}), t2={t2_shifted:.4f} (frac: {fraction2_shifted:.4f})"
        )

        bins = [t1_shifted, t2_shifted]
        label_array = np.digitize(array, bins).astype(np.uint8) + 1

        image_input_path = self.context.working_dir / "microporosity_image_input.nrrd"
        label_input_path = self.context.working_dir / "microporosity_label_input.nrrd"
        output_path = self.context.working_dir / "microporosity_output.nrrd"

        try:
            label_header = self.context.nrrd_header.copy()
            label_header.pop("type", None)

            nrrd.write(str(image_input_path), array, self.context.nrrd_header)
            nrrd.write(str(label_input_path), label_array, label_header)

            del label_array

            cli_path = self.cli_modules_dir / "MicroporosityCLI" / "MicroporosityCLI.py"

            cli_params = {
                "labels": {"Macroporosity": [1], "Microporosity": [2], "Reference Solid": [3]},
                "intrinsic_porosity": 0,
                "method": "microporosity",
                "microporosityLowerLimit": None,
                "microporosityUpperLimit": None,
                "returnVolume": True,
            }

            cmd = [
                sys.executable,
                str(cli_path),
                "--input",
                str(image_input_path),
                "--labelmap",
                str(label_input_path),
                "--params",
                json.dumps(cli_params),
                "--output",
                str(output_path),
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            self.logger.info(f"Microporosity CLI call result: {result}")

            porosity_map, _ = nrrd.read(str(output_path))
            self.logger.info(f"Porosity map final mean (Multi-Otsu CLI): {porosity_map.mean():.6f}")

            return porosity_map

        finally:
            for path in [image_input_path, label_input_path, output_path]:
                if path.exists():
                    try:
                        path.unlink()
                        self.logger.info(f"Cleaned up temporary Multi-Otsu file: {path.name}")
                    except Exception as e:
                        self.logger.warning(f"Failed to delete temporary file {path}: {e}")

    def _generate_porosity_map(self, array, porosity_map_params):
        sample_phi = self.context.workflow_params.get("sample_phi")
        experimental_sample_porosity = sample_phi / 100.0

        self.logger.info(f"Using experimental phi: {sample_phi}% (Target fraction: {experimental_sample_porosity:.4f})")

        min_subres_fraction = porosity_map_params.get("min_subres_porosity_fraction", 0.0)
        min_subres_porosity = min_subres_fraction * experimental_sample_porosity
        max_resolved_porosity = experimental_sample_porosity - min_subres_porosity

        mask = self.context.crop_sample_mask_array
        if mask is not None and self.context.workflow_params.get("crop_sample", False):
            sample_pixels = array[mask]
        else:
            sample_pixels = array.flatten()

        otsu_value = threshold_otsu(sample_pixels)
        array_resolved_porosity = np.mean(sample_pixels <= otsu_value)

        self.logger.info(f"Otsu value: {otsu_value:.4f} (Resolved fraction: {array_resolved_porosity:.4f})")

        if array_resolved_porosity <= max_resolved_porosity:
            resolved_threshold = otsu_value
        else:
            resolved_threshold = np.quantile(sample_pixels, max_resolved_porosity)
            self.logger.info(
                f"Capping resolved threshold to: {resolved_threshold:.4f} to maintain minimum sub-resolution porosity."
            )

        hist, bin_edges = np.histogram(sample_pixels, bins=2048, density=True)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0
        bin_widths = np.diff(bin_edges)

        def compute_mean_porosity(upper_thresh):
            if upper_thresh <= resolved_threshold:
                p = (bin_centers <= resolved_threshold).astype(float)
            else:
                p = (upper_thresh - bin_centers) / (upper_thresh - resolved_threshold)
                p = np.clip(p, 0.0, 1.0)
            return np.sum(p * hist * bin_widths)

        valid_upper_thresholds = bin_centers[bin_centers > resolved_threshold]
        subresolution_threshold = resolved_threshold

        best_diff = float("inf")

        for upper_thresh in valid_upper_thresholds:
            current_porosity = compute_mean_porosity(upper_thresh)

            if current_porosity >= experimental_sample_porosity:
                subresolution_threshold = upper_thresh
                break

            diff = abs(current_porosity - experimental_sample_porosity)
            if diff < best_diff:
                best_diff = diff
                subresolution_threshold = upper_thresh

        self.logger.info(
            f"Final Thresholds -> Resolved: {resolved_threshold:.4f}, Sub-Res: {subresolution_threshold:.4f}"
        )

        if subresolution_threshold == resolved_threshold:
            porosity_map = array <= resolved_threshold
        else:
            porosity_map = (subresolution_threshold - array) / (subresolution_threshold - resolved_threshold)
            np.clip(porosity_map, 0.0, 1.0, out=porosity_map)

        self.logger.info(
            f"Porosity map final mean: {porosity_map.mean():.6f} (Target: {experimental_sample_porosity:.6f})"
        )

        return porosity_map

    def _apply_gradient_anisotropic_diffusion(self, array, gad_params):
        input_path = self.context.working_dir / "gradient_anisotropic_diffusion_input.nrrd"
        output_path = self.context.working_dir / "gradient_anisotropic_diffusion_output.nrrd"

        try:
            gad_header = self.context.nrrd_header.copy()
            gad_header.pop("space directions", None)
            gad_header.pop("spacings", None)
            gad_header.pop("space origin", None)
            gad_header.pop("space", None)

            nrrd.write(str(input_path), array, gad_header)

            cli_path = self.cli_modules_dir / "GradientAnisotropicDiffusion"

            cmd = [
                str(cli_path),
                "--conductance",
                str(gad_params["conductance"]),
                "--iterations",
                str(gad_params["number_of_iterations"]),
                "--timeStep",
                str(gad_params["time_step"]),
                str(input_path),
                str(output_path),
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            self.logger.info(f"Gradient Anisotropic Diffusion cli call result: {result}")

            processed_array, _ = nrrd.read(str(output_path))
            return processed_array

        finally:
            for path in [input_path, output_path]:
                if path.exists():
                    try:
                        path.unlink()
                        self.logger.info(f"Cleaned up temporary GAD file: {path.name}")
                    except Exception as e:
                        self.logger.warning(f"Failed to delete temporary file {path}: {e}")

    def execute(self):
        params = self.context.workflow_params.get("porosity_map_params", {})
        sample_phi = self.context.workflow_params.get("sample_phi")

        self.logger.info(f"Creating porosity map for {self.context.working_dir.name}")

        array = self.context.array
        mask = self.context.crop_sample_mask_array

        erode_iterations = 1
        if self.context.workflow_params.get("crop_sample", False) and mask is not None and erode_iterations > 0:
            self.logger.info(f"Eroding mask by {erode_iterations} voxel(s) to remove edge effects.")
            mask = binary_erosion(mask, iterations=erode_iterations)
            self.context.crop_sample_mask_array = mask

        apply_gad = params.get("gradient_anisotropic_diffusion", False)
        if apply_gad:
            gad_params = params.get("gradient_anisotropic_diffusion_params", {})
            self.logger.info("Applying Gradient Anisotropic Diffusion to input array...")
            array = self._apply_gradient_anisotropic_diffusion(array, gad_params)
            self._export_nc(array, "gad_pre_porosity_map", "gad_pre_porosity_map")

        if sample_phi is None:
            porosity_map_array = self._generate_multiotsu_porosity_map(array, params)
        else:
            porosity_map_array = self._generate_porosity_map(array, params)

        if self.context.workflow_params.get("crop_sample", False) and mask is not None:
            porosity_map_array[~mask] = 0.0

        self.context.porosity_map = porosity_map_array.astype(np.float32)

        self.context.porosity_map[0, :, :] = self.context.porosity_map[1, :, :]
        self.context.porosity_map[-1, :, :] = self.context.porosity_map[-2, :, :]

        self._export_nc(self.context.porosity_map, "porosity_map", "porosity_map")

        self.context.crop_sample_mask_array = None
        self.context.array = None
        gc.collect()
