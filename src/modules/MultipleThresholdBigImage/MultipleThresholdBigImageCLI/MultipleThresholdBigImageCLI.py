#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
import vtk, slicer, slicer.util, mrml
import json

from ltrace.slicer.lazy import lazy
from ltrace.algorithms.big_image.multiple_threshold import apply_multiple_threshold
from ltrace.algorithms.big_image.common import DaskCLICallback

import xarray as xr
import slicer


def multithresh(lazy_data, threshs, colors, names, url, version, hostData):
    data_array = lazy_data.to_data_array(**hostData)
    array = data_array.data
    segmented = apply_multiple_threshold(array, threshs)

    data_array = xr.DataArray(segmented, coords=data_array.coords)
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
    hostData = params["lazyDataNodeHost"]
    multithresh(
        lazy_data,
        params["threshs"],
        params["colors"],
        params["names"],
        params["output_url"],
        params["geoslicerVersion"],
        hostData,
    )
