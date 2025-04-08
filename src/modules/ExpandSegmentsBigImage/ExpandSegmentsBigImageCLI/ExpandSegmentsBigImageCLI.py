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

from ltrace.slicer.lazy import lazy
from ltrace.slicer.cli_utils import progressUpdate
from ltrace.algorithms.big_image.expand_segments import expand_segments
from ltrace.algorithms.big_image.common import DaskCLICallback


def run(params: dict) -> None:
    segmentationLazyData = lazy.LazyNodeData(params["segmentationLazyNodeUrl"], params["segmentationLazyNodeVar"])
    segmentationLazyNodeHost = params["segmentationLazyNodeHost"]
    segmentDataArray = segmentationLazyData.to_data_array(**segmentationLazyNodeHost)

    # Convert xarray.DataArray to dask.Array
    daskSegmentDataArray = da.from_array(segmentDataArray, chunks=256)

    # Get information from the array
    origin = netcdf.get_origin(segmentDataArray)
    spacing = netcdf.get_spacing(segmentDataArray)

    # Process data
    expandSegmentsDaskArray = da.map_overlap(
        expand_segments,
        daskSegmentDataArray,
        origin=origin,
        spacing=spacing,
        dtype=np.uint8,
        align_arrays=True,
        depth=3,
    )

    # Re-convert from dask.Array to xarray.DataArray
    expandSegmentsArray = xr.DataArray(expandSegmentsDaskArray, coords=segmentDataArray.coords)

    # Set the xarray.DataArray attributes the same as the segmentation array used as input
    expandSegmentsArray.attrs = segmentDataArray.attrs

    # Update xarray.DataArray name
    name = f"{segmentationLazyData.var}_expanded"
    expandSegmentsArray.name = name

    # Create xarray.DataSet
    dataset = expandSegmentsArray.to_dataset(name=name)
    dataset.attrs["geoslicer_version"] = params["geoslicerVersion"]

    inputDims = netcdf.get_dims(segmentDataArray)
    outputims = netcdf.get_dims(expandSegmentsArray)
    dataset = dataset.rename(
        {
            inputDims[0]: outputims[0],
            inputDims[1]: outputims[1],
            inputDims[2]: outputims[2],
        }
    )

    segmentShape = expandSegmentsArray.shape
    encoding = {name: {"chunksizes": (min(128, segmentShape[0]), min(128, segmentShape[1]), min(128, segmentShape[2]))}}

    # Export xarray.DataSet to .nc file
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
