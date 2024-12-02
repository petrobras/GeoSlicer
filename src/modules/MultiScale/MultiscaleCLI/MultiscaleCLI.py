#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
import vtk, slicer, slicer.util, mrml
import os
import json

import mpslib as mps
import numpy as np

MRML_TYPES = {
    "vtkMRMLScalarVolumeNode": mrml.vtkMRMLScalarVolumeNode,
    "vtkMRMLLabelMapVolumeNode": mrml.vtkMRMLLabelMapVolumeNode,
}


def MPS(args):
    temporaryPath = args.temporaryPath
    params = json.loads(args.params) if args.params is not None else {}

    mpslib = mps.mpslib(method="mps_genesim")
    mpslib.parameter_filename = os.path.join(temporaryPath, "mps.txt")
    mpslib.par["ti_fnam"] = os.path.join(temporaryPath, "ti.dat")
    mpslib.par["out_folder"] = temporaryPath
    mpslib.par["simulation_grid_size"] = np.array(params["finalImageSize"])
    mpslib.par["grid_cell_size"] = np.array(params["finalImageResolution"])
    mpslib.par["n_cond"] = args.ncond
    mpslib.par["n_real"] = args.nreal
    mpslib.par["n_max_ite"] = args.iterations
    mpslib.par["rseed"] = args.rseed
    mpslib.par["hard_data_fnam"] = os.path.join("hard.dat")
    mpslib.par["mask_fnam"] = os.path.join(temporaryPath, "mask.dat")
    mpslib.par["colocate_dimension"] = args.colocateDimensions
    mpslib.par["max_search_radius"] = args.maxSearchRadius
    mpslib.par["distance_max"] = args.distanceMax
    mpslib.par["distance_pow"] = args.distancePower
    mpslib.par["distance_measure"] = args.distanceMeasure
    mpslib.run_parallel()

    for realization in range(args.nreal):
        np.save(os.path.join(temporaryPath, f"sim_data_{realization}.npy"), mpslib.sim[realization])

    with open(args.returnparameterfile, "a") as returnFile:
        returnFile.write("mpsTime=" + str(mpslib.time) + "\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    # Inputs

    # Params
    parser.add_argument(
        "--params",
        type=str,
        default=None,
        help="Dictionary with lists required by the algorithm. Including: Hard data resolution and values and Final image size and resolution",
    )
    parser.add_argument("--nreal", type=int, dest="nreal", required=True, help="Number of realizations")
    parser.add_argument("--ncond", type=int, dest="ncond", required=True, help="Number of conditioning points")
    parser.add_argument("--iterations", type=int, dest="iterations", required=True, help="Max number of iterations")
    parser.add_argument("--rseed", type=int, dest="rseed", required=True, help="Random seed")
    parser.add_argument(
        "--colocateDimensions",
        type=int,
        dest="colocateDimensions",
        required=True,
        help="Dimension that will be priorized",
    )
    parser.add_argument(
        "--maxSearchRadius",
        type=int,
        dest="maxSearchRadius",
        required=True,
        help="Max radius that the data will be considered as conditional data",
    )
    parser.add_argument(
        "--distanceMax",
        type=float,
        dest="distanceMax",
        required=True,
        help="Maximum distance what will lead to accepting a conditional template match",
    )
    parser.add_argument(
        "--distancePower",
        type=int,
        dest="distancePower",
        required=True,
        help="Set the distace power to weight the conditioning data",
    )
    parser.add_argument(
        "--distanceMeasure",
        type=int,
        dest="distanceMeasure",
        required=True,
        help="Set if data is continuous or discrete.",
    )
    parser.add_argument(
        "--mpsTime",
        type=float,
        dest="mpsTime",
        default=0.0,
        required=False,
        help="Set if data is continuous or discrete.",
    )

    parser.add_argument(
        "--temporaryPath",
        type=str,
        dest="temporaryPath",
        default=None,
        help="Directory to be used to save temporary files for the algorithm. Should be the same with the ti.dat file.",
    )

    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument(
        "--returnparameterfile", type=str, default=None, help="File destination to store an execution outputs"
    )

    args = parser.parse_args()

    MPS(args)
