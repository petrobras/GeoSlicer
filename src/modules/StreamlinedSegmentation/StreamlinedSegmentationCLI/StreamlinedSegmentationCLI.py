#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
import vtk, slicer, slicer.util, mrml
import json

from ltrace.slicer.lazy import lazy

import dask
import dask.array as da
from ltrace.slicer import netcdf
from ltrace.algorithms.big_image.multiple_threshold import apply_multiple_threshold
from ltrace.algorithms.big_image.boundary_removal import remove_boundaries
from ltrace.algorithms.big_image.expand_segments import expand_segments
from ltrace.algorithms.big_image.common import DaskCLICallback

import numpy as np
import xarray as xr
import slicer


def _run_all(scalar, origin, spacing, multiple_thresholds, boundary_thresholds, microporosity_index):
    segmentation = apply_multiple_threshold(scalar, multiple_thresholds)
    segmentation = remove_boundaries(scalar, segmentation, origin, spacing, boundary_thresholds, microporosity_index)
    segmentation = expand_segments(segmentation, origin, spacing, microporosity_index)
    return segmentation


def run_all_effects(lazy_data, lazy_data_host, multiple_thresholds, boundary_thresholds, colors, names, url, version):
    data_array = lazy_data.to_data_array(**lazy_data_host)
    array = data_array.data
    array = da.asarray(array).rechunk((256, 256, 256))

    origin = netcdf.get_origin(data_array)
    spacing = netcdf.get_spacing(data_array)

    try:
        microporosity_index = names.index("Microporosity") + 1
    except ValueError:
        microporosity_index = None
    boundary_removed_segmented = da.map_overlap(
        _run_all,
        array,
        origin=origin,
        spacing=spacing,
        multiple_thresholds=multiple_thresholds,
        boundary_thresholds=boundary_thresholds,
        dtype=data_array.dtype,
        align_arrays=True,
        depth=3,
        microporosity_index=microporosity_index,
    )

    data_array = xr.DataArray(boundary_removed_segmented, coords=data_array.coords)
    name = f"{lazy_data.var}_segmented"
    labels = ["Name,Index,Color"]
    for i, color in enumerate(colors):
        color = "#%02x%02x%02x" % tuple(int(ch * 255) for ch in color[:3])
        labels.append(f"{names[i]},{i + 1},{color}")
    data_array.attrs = {
        "type": "labelmap",
        "labels": labels,
    }

    dims = data_array.dims[:3]
    dataset = data_array.to_dataset(name=name)
    if "x" not in dataset.coords:
        dataset = dataset.rename({dims[0]: "z", dims[1]: "y", dims[2]: "x"})
    dataset.attrs["geoslicer_version"] = version

    segment_shape = data_array.shape
    encoding = {
        name: {"chunksizes": (min(128, segment_shape[0]), min(128, segment_shape[1]), min(128, segment_shape[2]))}
    }

    task = dataset.to_netcdf(url, encoding=encoding, format="NETCDF4", compute=False)

    with DaskCLICallback():
        task.compute()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--params", type=str)

    args = parser.parse_args()
    params = json.loads(args.params)
    lazy_data = lazy.LazyNodeData(params["input_url"], params["input_var"])
    lazy_data_host = params["input_host"]
    run_all_effects(
        lazy_data,
        params["input_host"],
        params["multiple_thresholds"],
        params["boundary_thresholds"],
        params["colors"],
        params["names"],
        params["output_url"],
        params["geoslicer_version"],
    )
