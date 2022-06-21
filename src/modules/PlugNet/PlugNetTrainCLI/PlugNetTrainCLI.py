#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

import vtk

import sys
from argparse import ArgumentParser

import h5py
import numpy as np
import tensorflow as tf
from tensorflow.keras.layers import Conv3D, Flatten, Dense, Input, Lambda, Normalization

from PlugNetTrainLib.Generator3D import Generator3D
from ltrace.plug_net.output_processing import preprocess

EPOCHS = 20


class CLIProgressCallback(tf.keras.callbacks.Callback):
    def on_epoch_end(self, epoch, logs=None):
        print(f"<filter-progress>{epoch / EPOCHS}</filter-progress>")
        sys.stdout.flush()


def train(inputFileName, outputFileName, gpuEnabled):
    # Hide GPU from visible devices
    if not gpuEnabled:
        tf.config.set_visible_devices([], "GPU")

    params = {
        "subcubeSize": 32,
        "batchSize": 64,
        "nChannels": 1,
        "nOutputs": 3,
        "nSamplesPerCase": 100,
    }

    with h5py.File(inputFileName) as f:
        X = np.array(f.get("X"))
        Y = np.array(f.get("Y"))

    X = X.astype("float32")
    Y = preprocess(Y)

    normalization = Normalization(axis=None)
    normalization.adapt(X)
    removeOutliers = Lambda(lambda x: tf.clip_by_value(x, -2, 2))

    model = tf.keras.Sequential(
        [
            Input(shape=(32, 32, 32, 1)),
            normalization,
            removeOutliers,
            Conv3D(8, (3, 3, 3), activation="relu"),
            Conv3D(8, (3, 3, 3), activation="relu", strides=(2, 2, 2)),
            Conv3D(16, (3, 3, 3), activation="relu"),
            Conv3D(32, (3, 3, 3), activation="relu", strides=(2, 2, 2)),
            Conv3D(128, (3, 3, 3), activation="relu"),
            Conv3D(128, (3, 3, 3), activation="relu"),
            Flatten(),
            Dense(params["nOutputs"], activation="tanh"),
        ]
    )

    model.compile(loss=["mse"], optimizer="adam")
    model.summary()

    print(X.shape)
    trainingGenerator = Generator3D(X, Y, **params)

    model.fit(
        trainingGenerator,
        epochs=EPOCHS,
        callbacks=[CLIProgressCallback()],
    )

    tf.keras.models.save_model(model, outputFileName, save_format="tf")
    model.evaluate(trainingGenerator)


if __name__ == "__main__":
    parser = ArgumentParser(description="LTrace plug upscaling trainer for GeoSlicer.")
    for argName in "input", "output":
        parser.add_argument(
            f"--{argName}",
            type=str,
            dest=argName,
        )
    parser.add_argument("--gpuEnabled", action="store_true")
    args = parser.parse_args()
    train(args.input, args.output, args.gpuEnabled)
