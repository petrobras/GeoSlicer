#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
import vtk, slicer, slicer.util, mrml
import argparse
import os
import json
import numpy as np

from ltrace.multiscaleLib.bychunks.sequential_mps import SequentialMPS
from ltrace.multiscaleLib.bychunks.log import init_output_logging
import time
import datetime
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument(
    "--patches",
    type=int,
    dest="patches",
    required=True,
    help="Number of image chunks that the image will be splitted for simulation",
)
parser.add_argument("--nreal", type=int, dest="nreal", required=True, help="Number of realizations")
parser.add_argument("--ncond", type=int, dest="ncond", required=True, help="Number of conditioning points")
parser.add_argument("--iterations", type=int, dest="iterations", required=True, help="Max number of iterations")
parser.add_argument("--rseed", type=int, dest="rseed", required=True, help="Random seed")
parser.add_argument(
    "--mpsTime",
    type=float,
    dest="mpsTime",
    default=0.0,
    required=False,
    help="Output parameter that returns the MPS execution time in seconds",
)
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
    help="Set the distance power to weight the conditioning data",
)
parser.add_argument(
    "--distanceMeasure",
    type=int,
    dest="distanceMeasure",
    required=True,
    help="Set if data is continuous or discrete.",
)

parser.add_argument("--ti", type=str, dest="ti", required=True, help="Training image")
parser.add_argument("--hd", type=str, dest="hd", required=True, help="Hard data")

parser.add_argument(
    "--suffix",
    type=str,
    dest="suffix",
    default="suffix",
    required=False,
)
parser.add_argument(
    "--neighbor_size",
    type=int,
    dest="neighbor_size",
    default=10,
    required=False,
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

opt = parser.parse_args()

date = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
name = f"{date}_ncond_{opt.ncond}_nmaxite_{opt.iterations}" f"_np_{opt.patches}_ns_{opt.neighbor_size}"

opt = vars(opt)

opt["fname"] = name
opt["root_path"] = str(Path(opt["temporaryPath"]).joinpath(name))


os.makedirs(opt["root_path"], exist_ok=True)
init_output_logging(f'{opt["root_path"]}/log.txt')
print(f"{opt}\n")

start_time = time.time()
print(f"start: {datetime.datetime.now()}")

mps_time = 0

for realization in range(opt["nreal"]):
    seq_mps = SequentialMPS(opt)
    realization_time = seq_mps.run_3d(realization)

    if opt["rseed"] > 0:
        opt["rseed"] = opt["rseed"] + 1

    mps_time += realization_time

with open(opt["returnparameterfile"], "a") as returnFile:
    returnFile.write("mpsTime=" + str(mps_time) + "\n")

end_time = time.time()
print(f"end: {datetime.datetime.now()}")
print(f"Generation time (s): {end_time - start_time}")
