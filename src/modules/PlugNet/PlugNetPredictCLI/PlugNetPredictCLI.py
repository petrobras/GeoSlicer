#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

import vtk

import sys
from argparse import ArgumentParser

import numpy as np
import pandas as pd

from PlugNetPredictLib.GeneratorNrrd import GeneratorNrrd
from ltrace.plug_net.output_processing import postprocess
from ltrace.slicer.cli_utils import writeToTable


def predict(modelPath, coreDirPath, tableId, gpuEnabled):
    import tensorflow as tf

    # Hide GPU from visible devices
    if not gpuEnabled:
        tf.config.set_visible_devices([], "GPU")

    model = tf.keras.models.load_model(modelPath)
    model.summary()

    valueBatches = []
    depthBatches = []
    generator = GeneratorNrrd(coreDirPath)
    for i, (depthBatch, cubeBatch) in enumerate(generator):
        valueBatches.append(model(cubeBatch))
        depthBatches.append(depthBatch)

        print(f"<filter-progress>{i / len(generator)}</filter-progress>")
        sys.stdout.flush()

    result = postprocess(np.vstack(valueBatches))
    depths = np.concatenate(depthBatches)

    data = np.column_stack([-depths, result])
    df = pd.DataFrame(data, columns=["DEPTH", "PERMEABILITY", "POROSITY", "DENSITY"])
    writeToTable(df, tableId)


if __name__ == "__main__":
    parser = ArgumentParser(description="LTrace plug upscaler for GeoSlicer.")
    for argName in "model", "coreDir", "outputTable":
        parser.add_argument(f"--{argName}", type=str, dest=argName)
    parser.add_argument("--gpuEnabled", action="store_true")
    args = parser.parse_args()
    predict(args.model, args.coreDir, args.outputTable, args.gpuEnabled)
