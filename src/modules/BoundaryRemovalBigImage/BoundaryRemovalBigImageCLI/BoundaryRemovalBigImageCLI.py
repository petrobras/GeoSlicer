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

from ltrace.algorithms.big_image.boundary_removal import remove_boundaries
from ltrace.algorithms.big_image.common import DaskCLICallback
from ltrace.slicer.cli_utils import progressUpdate
from ltrace.slicer.lazy import lazy
from typing import Dict


def getEncoding(array: "xr.DataArray") -> Dict:
    def getDim(dim):
        return min(dim, 128)

    shape = array.shape
    chunk_size = (getDim(shape[0]), getDim(shape[1]), getDim(shape[2]))
    return {array.name: {"chunksizes": chunk_size}}


def run(params: dict) -> None:
    inputLazyData = lazy.LazyNodeData(params["inputLazyNodeUrl"], params["inputLazyNodeVar"])
    segmentationLazyData = lazy.LazyNodeData(params["segmentationLazyNodeUrl"], params["segmentationLazyNodeVar"])
    inputLazyNodeHost = params["inputLazyNodeHost"]
    segmentationLazyNodeHost = params["segmentationLazyNodeHost"]
    dataArray = inputLazyData.to_data_array(**inputLazyNodeHost)
    segmentDataArray = segmentationLazyData.to_data_array(**segmentationLazyNodeHost)

    # Convert xarray.DataArray to dask.Array
    daskDataArray = da.from_array(dataArray, chunks=256)
    daskSegmentDataArray = da.from_array(segmentDataArray, chunks=256)

    # Get information from the array
    origin = netcdf.get_origin(dataArray)
    spacing = netcdf.get_spacing(dataArray)

    thresholds = params["thresholdMinimumValue"], params["thresholdMaximumValue"]

    # Process data
    boundaryRemovalDaskArray = da.map_overlap(
        remove_boundaries,
        daskDataArray,
        daskSegmentDataArray,
        origin=origin,
        spacing=spacing,
        thresholds=thresholds,
        dtype=np.uint8,
        align_arrays=True,
        depth=1,
    )

    # Re-convert from dask.Array to xarray.DataArray
    boundaryRemovalArray = xr.DataArray(boundaryRemovalDaskArray, coords=dataArray.coords)

    # Set the xarray.DataArray attributes the same as the segmentation array used as input
    boundaryRemovalArray.attrs = segmentDataArray.attrs

    # Update xarray.DataArray name
    name = f"{segmentationLazyData.var}_filtered"
    boundaryRemovalArray.name = name

    # Create xarray.DataSet
    dataset = boundaryRemovalArray.to_dataset(name=name)
    dataset.attrs["geoslicer_version"] = params["geoslicerVersion"]

    inputDims = netcdf.get_dims(dataArray)
    outputDims = netcdf.get_dims(boundaryRemovalArray)
    dataset = dataset.rename(
        {
            inputDims[0]: outputDims[0],
            inputDims[1]: outputDims[1],
            inputDims[2]: outputDims[2],
        }
    )

    # Export xarray.DataSet to .nc file
    encoding = getEncoding(boundaryRemovalArray)
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
