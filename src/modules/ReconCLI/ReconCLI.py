#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

import os
import glob
import numpy as np
import tomopy
import astra
import tifffile
import argparse
from skimage import io


def parse_skyscan_log(log_path):
    """Parses a Bruker/SkyScan .log file to extract geometry and scan parameters."""
    params = {}
    with open(log_path, "r", encoding="latin-1") as f:
        for line in f:
            if "Source to Object" in line:
                params["SOD"] = float(line.split("=")[1].strip().split()[0])  # mm
            elif "Source to Camera" in line or "Source to Detector" in line:
                params["SDD"] = float(line.split("=")[1].strip().split()[0])  # mm
            elif "Image Pixel Size" in line:
                params["pixel_size"] = float(line.split("=")[1].strip().split()[0])  # um
            elif "Rotation Step" in line:
                params["rot_step"] = float(line.split("=")[1].strip().split()[0])  # degrees

    # Convert pixel size to mm for consistency
    if "pixel_size" in params:
        params["pixel_size_mm"] = params["pixel_size"] / 1000.0

    return params


def correct_beam_hardening(prj, factor=0.05):
    """
    Applies a simple polynomial correction for beam hardening.
    Bruker's NRecon uses a similar polynomial approach to flatten the 'cupping' effect.
    """
    # p' = p + factor * p^2
    return prj + factor * (prj**2)


def reconstruct_skyscan(input_dir, output_dir=None, log_path=None, machine="Bruker Skyscan 1173"):
    print(f"--- Starting Reconstruction Pipeline for {machine} ---")

    # 1. Path Management
    if output_dir is None:
        output_dir = os.path.join(input_dir, "reconstruction_output")
    os.makedirs(output_dir, exist_ok=True)

    if log_path is None:
        log_files = glob.glob(os.path.join(input_dir, "*.log"))
        if not log_files:
            raise FileNotFoundError("No .log file found in the input directory.")
        log_path = log_files[0]

    print(f"Reading log file: {log_path}")
    geom = parse_skyscan_log(log_path)

    # 2. Load TIFF Projections
    tiff_files = sorted(glob.glob(os.path.join(input_dir, "*.tif*")))
    if not tiff_files:
        raise FileNotFoundError("No TIFF files found in the input directory.")

    print(f"Loading {len(tiff_files)} projection images...")
    # Load as [z, y, x] where z is angles
    prj = io.imread_collection(tiff_files)
    prj = io.concatenate_images(prj).astype(np.float32)

    # Determine dimensions
    num_projs, height, width = prj.shape

    # 3. Pre-processing with TomoPy
    print("Applying TomoPy pre-processing...")

    # SkyScan TIFFs are usually transmission images (I/I0). We need to convert to absorption (-log).
    # We add a small constant to prevent log(0)
    prj[prj <= 0] = 1e-6
    # Max value for 16-bit is 65535. Normalizing assuming flat-field is already applied by SkyScan
    prj = prj / 65535.0
    prj = tomopy.minus_log(prj)

    # Remove black dots / dead pixels (Outlier removal)
    print("- Removing outliers (black dots)...")
    prj = tomopy.misc.corr.remove_outlier(prj, dif=0.1, size=3)

    # Beam Hardening Correction
    print("- Applying beam hardening correction...")
    prj = correct_beam_hardening(prj, factor=0.1)

    # Ring Artifact Removal (Fourier-Wavelet method is highly effective for microCT)
    print("- Removing ring artifacts...")
    prj = tomopy.prep.stripe.remove_stripe_fw(prj, level=5, wname="db5", sigma=1, pad=True)

    # 4. Set up ASTRA Cone-Beam Geometry
    print("Configuring ASTRA Cone-Beam geometry...")
    # ASTRA requires distances in units of pixels
    dist_source_origin = geom["SOD"] / geom["pixel_size_mm"]
    dist_origin_det = (geom["SDD"] - geom["SOD"]) / geom["pixel_size_mm"]

    # Calculate angles based on rotation step
    theta = np.linspace(0, num_projs * geom["rot_step"], num_projs, endpoint=False)
    theta_rad = np.deg2rad(theta)

    # Create geometries
    # ASTRA projection geometry: 'cone', det_width, det_height, num_det_y, num_det_x, angles, SOD, ODD
    proj_geom = astra.create_proj_geom("cone", 1.0, 1.0, height, width, theta_rad, dist_source_origin, dist_origin_det)

    # Reconstructed volume geometry (Center of rotation is assumed to be at the center of the detector)
    vol_geom = astra.create_vol_geom(width, width, height)

    # 5. Execute ASTRA Reconstruction (FDK)
    print("Running ASTRA FDK Reconstruction on GPU...")
    proj_id = astra.data3d.create("-sino", proj_geom, prj)
    rec_id = astra.data3d.create("-vol", vol_geom)

    # Set up the FDK algorithm
    cfg = astra.astra_dict("FDK_CUDA")
    cfg["ReconstructionDataId"] = rec_id
    cfg["ProjectionDataId"] = proj_id

    alg_id = astra.algorithm.create(cfg)
    astra.algorithm.run(alg_id)

    # Retrieve the reconstructed volume
    recon_vol = astra.data3d.get(rec_id)

    # Clean up ASTRA memory
    astra.algorithm.delete(alg_id)
    astra.data3d.delete(proj_id)
    astra.data3d.delete(rec_id)

    # 6. Save Output Slices
    print(f"Saving reconstructed slices to {output_dir}...")
    # Slices are saved along the Z-axis (height)
    for i in range(height):
        slice_data = recon_vol[:, i, :]
        # Clip negative artifacts and scale for 16-bit TIFF
        slice_data = np.clip(slice_data, 0, np.max(slice_data))
        slice_data = (slice_data / np.max(slice_data) * 65535).astype(np.uint16)

        filename = os.path.join(output_dir, f"recon_slice_{i:04d}.tiff")
        tifffile.imwrite(filename, slice_data)

    print("Reconstruction Complete!")


if __name__ == "__main__":
    # Set up argument parsing for command line execution
    parser = argparse.ArgumentParser(description="MicroCT Reconstruction for Bruker SkyScan")
    parser.add_argument("input_dir", help="Directory containing TIFFs and .log file")
    parser.add_argument("--output_dir", "-o", default=None, help="Output directory for slices")
    parser.add_argument("--log_path", "-l", default=None, help="Specific path to the .log file if outside input_dir")
    parser.add_argument("--machine", "-m", default="Bruker Skyscan 1173", help="Machine brand/model")

    args = parser.parse_args()

    reconstruct_skyscan(
        input_dir=args.input_dir, output_dir=args.output_dir, log_path=args.log_path, machine=args.machine
    )
