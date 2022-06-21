#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above
#
# Doubts: 1) Does porosity have the same depth scale than the imagelog? If not, interpolated is required for next version.
# Or the proportion should be computed for a depth range

from __future__ import print_function

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
import vtk, slicer, slicer.util, mrml

import io
import json
import numpy as np
import sys

from pathvalidate.argparse import sanitize_filepath_arg
from PIL import Image
from ltrace.file_utils import read_csv
from ltrace.wrappers import sanitize_file_path


def progressUpdate(value):
    """
    Progress Bar updates over stdout (Slicer handles the parsing)
    """
    print(f"<filter-progress>{value}</filter-progress>")
    sys.stdout.flush()


def writeDataInto(volumeFile, dataVoxelArray, builder, reference=None):
    sn_out = slicer.vtkMRMLNRRDStorageNode()
    sn_out.SetFileName(volumeFile)
    nodeOut = builder()

    if reference:
        # copy image information
        nodeOut.Copy(reference)
        # reset the attribute dictionary, otherwise it will be transferred over
        attrs = vtk.vtkStringArray()
        nodeOut.GetAttributeNames(attrs)
        for i in range(0, attrs.GetNumberOfValues()):
            nodeOut.SetAttribute(attrs.GetValue(i), None)

    # reset the data array to force resizing, otherwise we will just keep the old data too
    nodeOut.SetAndObserveImageData(None)
    slicer.util.updateVolumeFromArray(nodeOut, dataVoxelArray)
    nodeOut.Modified()

    sn_out.WriteData(nodeOut)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument(
        "--file1", type=sanitize_filepath_arg, dest="file1", required=True, help="QEMSCAN image file path"
    )
    parser.add_argument(
        "--file2", type=sanitize_filepath_arg, dest="file2", required=False, help="Lookup iolor table file path"
    )
    parser.add_argument(
        "--csvstring", type=sanitize_filepath_arg, dest="csvstring", required=False, help="Lookup color table string"
    )
    parser.add_argument(
        "--outputvolume",
        type=sanitize_filepath_arg,
        dest="outputVolume",
        default=None,
        help="Output scalar values",
    )
    parser.add_argument(
        "--labelvolume",
        type=sanitize_filepath_arg,
        dest="labelVolume",
        default=None,
        help="Output labelmap values",
    )

    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument(
        "--returnparameterfile",
        type=sanitize_filepath_arg,
        default=None,
        help="File destination to store an execution outputs",
    )
    args = parser.parse_args()
    args.file1 = sanitize_file_path(args.file1).as_posix()
    args.file2 = sanitize_file_path(args.file2).as_posix()
    args.csvstring = sanitize_file_path(args.csvstring).as_posix()
    args.outputVolume = sanitize_file_path(args.outputVolume).as_posix()
    args.labelVolume = sanitize_file_path(args.labelVolume).as_posix()

    # read tif
    try:
        img = Image.open(args.file1)
        if img.getpalette() is None:  # image not quantized
            img = img.convert("RGB")  # force RGB to remove alpha channel
            img = img.quantize()  # convert to an image with palette
        imarray_1chanel = np.array(img)[::-1, ::-1]

        paleta = img.getpalette()
        paleta = np.array(paleta).reshape(256, 3)
    except RuntimeError:
        raise RuntimeError("The format of the input file is invalid.")
    finally:
        if img:
            img.close()

    if args.file2 is not None:
        data = read_csv(args.file2).values
    elif args.csvstring is not None:
        data = read_csv(io.StringIO(args.csvstring)).values
    else:
        raise ValueError("Either file2 or csvstring is required")

    mineral_segment_ids = data[:, 0]
    colors_csv = data[:, 1:]

    progressUpdate(0.2)

    # MAKE LIST AND VOLUME BASED ON TABLE IDS
    segments = {}
    imarray_1chanel_made = np.zeros(imarray_1chanel.shape)  # imarray_1chanel
    for mineral_csv in range(mineral_segment_ids.shape[0]):
        mineral_label = mineral_csv + 1  # offset to let 0 be the backgroundon slicer
        index_paleta = np.where(
            (paleta[:, 0] == colors_csv[mineral_csv, 0])
            & (paleta[:, 1] == colors_csv[mineral_csv, 1])
            & (paleta[:, 2] == colors_csv[mineral_csv, 2])
        )
        for id_ in index_paleta[0]:
            index_image = np.where(imarray_1chanel == id_)
            imarray_1chanel_made[index_image] = mineral_label

        # values2 = [mineral_segment_ids[mineral_csv], mineral_csv ]

        segments[mineral_label] = {
            "name": mineral_segment_ids[mineral_csv],
            "color_rgb": tuple(colors_csv[mineral_csv, :]),
        }

        progressUpdate(0.2 + 0.6 * mineral_csv / mineral_segment_ids.shape[0])

    outputArray = np.flip(imarray_1chanel_made, axis=(0, 1)).reshape(
        1, imarray_1chanel_made.shape[0], imarray_1chanel_made.shape[1]
    )

    # Get output node ID
    outputNodeID = args.outputVolume
    if outputNodeID is None:
        raise ValueError("Missing output node")

    # Get labels node ID
    labelsNodeID = args.labelVolume
    if labelsNodeID is None:
        raise ValueError("Missing output node")

    # Write output data
    writeDataInto(
        outputNodeID,
        np.flip(imarray_1chanel, axis=(0, 1)).reshape(1, *imarray_1chanel.shape),
        mrml.vtkMRMLScalarVolumeNode,
    )

    progressUpdate(0.8)

    # Write output data
    writeDataInto(labelsNodeID, outputArray, mrml.vtkMRMLLabelMapVolumeNode)

    returnParameterFile = sanitize_file_path(args.returnparameterfile)
    with open(returnParameterFile.as_posix(), "w") as outputStream:
        outputStream.write("lookup_table=" + json.dumps(segments) + "\n")

    progressUpdate(1.0)

    print("Done")
