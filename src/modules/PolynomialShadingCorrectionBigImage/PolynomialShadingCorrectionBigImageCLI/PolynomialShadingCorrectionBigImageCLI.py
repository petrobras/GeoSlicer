#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
import vtk, slicer, slicer.util, mrml
import argparse
import dask.array as da
import json
import ltrace.slicer.netcdf as netcdf
import numpy as np
import random
import xarray as xr

from dask.callbacks import Callback
from ltrace.slicer.lazy import lazy
from ltrace.slicer.cli_utils import progressUpdate
from typing import Union, Dict
from scipy.optimize import curve_fit


class DaskCLICallback(Callback):
    def _pretask(self, key, dask, state) -> None:
        if not state:
            return

        nDone = len(state["finished"])
        nTotal = sum(len(state[k]) for k in ("ready", "waiting", "running")) + nDone
        progressValue = nDone / nTotal if nTotal else 0
        progressUpdate(value=progressValue)


def polynomialShadingCorrection(
    inputImageArray: "dask.array.core.Array",
    inputMaskArray: "dask.array.core.Array",
    inputShadingMaskArray: "dask.array.core.Array",
    params: dict = None,
) -> Union[None, "dask.array.core.Array"]:
    def isValid(arr):
        return arr is not None and len(arr) > 0

    if not isValid(inputImageArray) or not isValid(inputMaskArray) or not isValid(inputShadingMaskArray):
        return None

    sliceGroupSize = params["sliceGroupSize"]
    numberOfFittingPoints = params["numberFittingPoints"]
    inputNullValue = params.get("nullValue", 0)
    outputImageArray = inputImageArray.copy()

    array = inputImageArray[inputShadingMaskArray != 0]

    inputArrayShadingMaskMax = np.max(array) if array.size != 0 else 1
    inputArrayShadingMaskMean = np.mean(array) if array.size != 0 else 1
    initialParameters = [
        1,
        inputImageArray.shape[1] / 2,
        1,
        inputImageArray.shape[2] / 2,
        1,
        1,
        1,
        inputArrayShadingMaskMax,
    ]

    x, y = np.meshgrid([i for i in range(inputImageArray.shape[1])], [j for j in range(inputImageArray.shape[2])])

    iterationIndexes = np.arange(sliceGroupSize // 2, len(inputImageArray), sliceGroupSize)
    for i in iterationIndexes:
        # Selecting random points
        xData, yData = np.where(inputShadingMaskArray[i] != 0)
        if len(xData) == 0:  # if no indexes where found
            continue
        data = [(x, y) for x, y in zip(xData, yData)]
        data = random.sample(data, min(len(data), numberOfFittingPoints))
        xData, yData = list(zip(*data))
        zData = inputImageArray[i][(xData, yData)]

        # Fitting
        function = polynomial
        try:
            fittedParameters, pcov = curve_fit(function, [xData, yData], zData, p0=initialParameters)
            initialParameters = fittedParameters
        except:
            # If the polynomial fitting fails, try to fit a simple plane
            function = plane
            try:
                fittedParameters, pcov = curve_fit(
                    function,
                    [xData, yData],
                    zData,
                    p0=[1, inputImageArray.shape[1] / 2, 1, inputImageArray.shape[2] / 2, inputArrayShadingMaskMax],
                )
            except:
                # If nothing can be fitted, skip
                continue

        # Applying function
        z = function((x, y), *fittedParameters)
        z = np.swapaxes(z, 0, 1)
        zz = z / inputArrayShadingMaskMean

        # Adjusting slice data
        for j in range(i - sliceGroupSize // 2, i + 1):
            outputImageArray[j] = inputImageArray[j] / zz

        # In the last iteration, proceed to apply the function in all the remaining slices
        if i == iterationIndexes[-1]:
            end = len(inputImageArray)
        else:
            end = i + sliceGroupSize // 2 + 1

        for j in range(i + 1, end):
            outputImageArray[j] = inputImageArray[j] / zz

    outputImageArray[inputMaskArray == 0] = inputNullValue

    return outputImageArray


def polynomial(data, a, b, c, d, e, f, g, h) -> int:
    x, y = data
    return a * (x - b) ** 2 + c * (y - d) ** 2 + e * (x - b) + f * (y - d) + g * (x - b) * (y - d) + h


def plane(data, a, b, c, d, e) -> int:
    x, y = data
    return a * (x - b) + c * (y - d) + e


def getEncoding(array: "xr.DataArray") -> Dict:
    def getDim(dim):
        return min(dim, 128)

    shape = array.shape
    chunk_size = (getDim(shape[0]), getDim(shape[1]), getDim(shape[2]))
    return {array.name: {"chunksizes": chunk_size}}


def run(params: Dict) -> None:
    inputLazyData = lazy.LazyNodeData(params["inputLazyNodeUrl"], params["inputLazyNodeVar"])
    inputMaskLazyData = lazy.LazyNodeData(params["inputMaskLazyNodeUrl"], params["inputMaskLazyNodeVar"])
    inputShadingMaskLazyData = lazy.LazyNodeData(
        params["inputShadingMaskLazyNodeUrl"], params["inputShadingMaskLazyNodeVar"]
    )

    inputLazyNodeHost = params["inputLazyNodeHost"]
    inputMaskLazyNodeHost = params["inputMaskLazyNodeHost"]
    inputShadingMaskLazyNodeHost = params["inputShadingMaskLazyNodeHost"]

    inputDataArray = inputLazyData.to_data_array(**inputLazyNodeHost)
    inputMaskDataArray = inputMaskLazyData.to_data_array(**inputMaskLazyNodeHost)
    inputShadingMaskDataArray = inputShadingMaskLazyData.to_data_array(**inputShadingMaskLazyNodeHost)

    # Convert xarray.DataArray to dask.Array
    shape = inputDataArray.shape
    if len(shape) != 3:
        raise ValueError(f"Expected a 3D input image. Current image dimensions: {shape}")

    # Calculate slice chuncksize to have blocks with 100mb size at most.
    sliceChunkSize = int(400 * 400 * 100 / (shape[1] * shape[2]))
    sliceChunkSize = min(shape[0], sliceChunkSize)
    sliceChunkSize = max(1, sliceChunkSize)
    chunkSize = (sliceChunkSize, shape[1], shape[2])

    daskInputDataArray = da.from_array(inputDataArray, chunks=chunkSize)
    daskInputMaskDataArray = da.from_array(inputMaskDataArray, chunks=chunkSize)
    daskInputShadingMaskDataArray = da.from_array(inputShadingMaskDataArray, chunks=chunkSize)

    filteredDaskArray = da.map_blocks(
        polynomialShadingCorrection,
        daskInputDataArray,
        daskInputMaskDataArray,
        daskInputShadingMaskDataArray,
        params=params,
        dtype=np.dtype("uint16"),
    )

    # Re-convert from dask.Array to xarray.DataArray
    filteredArray = xr.DataArray(filteredDaskArray, coords=inputDataArray.coords)

    # Set the xarray.DataArray attributes the same as the segmentation array used as input
    filteredArray.attrs = inputDataArray.attrs

    # Update xarray.DataArray name
    name = f"{inputLazyData.var}_filtered"
    filteredArray.name = name

    # Create xarray.DataSet
    dataset = filteredArray.to_dataset(name=name)
    dataset.attrs["geoslicer_version"] = params["geoslicerVersion"]

    inputDims = netcdf.get_dims(inputDataArray)
    outputDims = netcdf.get_dims(filteredArray)
    dataset = dataset.rename(
        {
            inputDims[0]: outputDims[0],
            inputDims[1]: outputDims[1],
            inputDims[2]: outputDims[2],
        }
    )

    # Export xarray.DataSet to .nc file
    encoding = getEncoding(filteredArray)
    task = dataset.to_netcdf(params["exportPath"], encoding=encoding, format="NETCDF4", compute=False)

    # Compute
    with DaskCLICallback():
        task.compute()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("-p", "--params", type=str, dest="params", required=True, help="JSON-like information")
    args = parser.parse_args()
    argParams = json.loads(args.params)
    run(argParams)
