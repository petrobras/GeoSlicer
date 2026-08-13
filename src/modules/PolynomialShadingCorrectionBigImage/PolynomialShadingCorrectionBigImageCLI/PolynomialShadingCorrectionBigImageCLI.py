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
import xarray as xr

from dask.callbacks import Callback

from ltrace.algorithms.shading_correction import compute_polynomial_shading_correction
from ltrace.slicer.lazy import lazy
from ltrace.slicer.cli_utils import progressUpdate
from typing import Union, Dict


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
    inputShadingMaskArray: "dask.array.core.Array",
    params: dict = None,
) -> Union[None, "dask.array.core.Array"]:

    # Check for valid inputs before sending to the algorithm
    if inputImageArray is None or len(inputImageArray) == 0:
        return None
    if inputShadingMaskArray is None or len(inputShadingMaskArray) == 0:
        return None

    return compute_polynomial_shading_correction(
        inputImageArray=inputImageArray,
        inputShadingMaskArray=inputShadingMaskArray,
        sliceGroupSize=params["sliceGroupSize"],
        fittingPointsPercentage=params["fittingPointsPercentage"],
        functionType=params["functionType"],
        polynomialOrder=params.get("polynomialOrder", 4),
        useCustomCenter=params.get("useCustomCenter", False),
        centerX=params.get("centerX", 0),
        centerY=params.get("centerY", 0),
        inputNullValue=params.get("nullValue", 0),
    )


def getEncoding(array: "xr.DataArray") -> Dict:
    def getDim(dim):
        return min(dim, 128)

    shape = array.shape
    chunk_size = (getDim(shape[0]), getDim(shape[1]), getDim(shape[2]))
    return {array.name: {"chunksizes": chunk_size}}


def run(params: Dict) -> None:
    inputLazyData = lazy.LazyNodeData(params["inputLazyNodeUrl"], params["inputLazyNodeVar"])
    inputShadingMaskLazyData = lazy.LazyNodeData(
        params["inputShadingMaskLazyNodeUrl"], params["inputShadingMaskLazyNodeVar"]
    )

    inputLazyNodeHost = params["inputLazyNodeHost"]
    inputShadingMaskLazyNodeHost = params["inputShadingMaskLazyNodeHost"]

    inputDataArray = inputLazyData.to_data_array(**inputLazyNodeHost)
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
    daskInputShadingMaskDataArray = da.from_array(inputShadingMaskDataArray, chunks=chunkSize)

    filteredDaskArray = da.map_blocks(
        polynomialShadingCorrection,
        daskInputDataArray,
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
    task = dataset.to_netcdf(
        params["exportPath"], encoding=encoding, format="NETCDF4", compute=False, engine="h5netcdf"
    )

    # Compute
    with DaskCLICallback():
        task.compute()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("-p", "--params", type=str, dest="params", required=True, help="JSON-like information")
    args = parser.parse_args()
    argParams = json.loads(args.params)
    run(argParams)
