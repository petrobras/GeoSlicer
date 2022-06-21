#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

from __future__ import print_function

import vtk

import pandas as pd
import mrml
import json
import logging
import pytesseract
import sys
import traceback

from ltrace.image.core_box.core_image import CoreImage
from ltrace.slicer.cli_utils import writeDataInto, writeToTable


def update_volume_node(node_id, array):
    """Update volume's array.

    Args:
        node_id (str): the related node ID.
        array (np.ndarray): the numpy's array.
    """
    array = array.reshape(array.shape[0], 1, array.shape[1], array.shape[2])
    writeDataInto(node_id, array, mrml.vtkMRMLVectorVolumeNode, reference=None)


def main(args):
    """Runs the core photograph aggregator process."""
    # Get input informations
    data = json.loads(args.data)
    node_id = args.outputVolume
    table_node_id = args.outputReport
    fixed_box_height_meter = data.get("fixed_box_height_meter")
    user_defined_start_depth = data.get("user_defined_start_depth")
    input_depth_table_file = data.get("input_depth_table_file", "")
    core_boxes_files_dict = data.get("core_boxes_files_dict", dict())
    tesserac_bin_path = data.get("tesseract_bin_path", "")

    pytesseract.pytesseract.tesseract_cmd = tesserac_bin_path

    try:
        full_core_image = CoreImage(
            core_boxes_files_dict=core_boxes_files_dict,
            fixed_box_height_meter=fixed_box_height_meter,
            user_defined_start_depth=user_defined_start_depth,
            input_depth_table_file=input_depth_table_file,
            gpuEnabled=args.gpuEnabled,
        )

        # Update volume node with the concatenated core images array
        update_volume_node(node_id, full_core_image.array)

        node_data = {"x_spacing": [1], "y_spacing": [full_core_image.spacing], "origin": [full_core_image.origin]}

        node_data_df = pd.DataFrame.from_dict(node_data)
        writeToTable(node_data_df, table_node_id)

        exit_code = 0
    except Exception as error:
        logging.error(f"{repr(error)}\n{traceback.print_exc()}")
        exit_code = 1

    return exit_code


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--data", type=str)
    parser.add_argument("--output", type=str, dest="outputVolume", default=None)
    parser.add_argument("--report", type=str, dest="outputReport", default=None)
    parser.add_argument("--gpuEnabled", action="store_true")

    sys.exit(main(parser.parse_args()))
