#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
import vtk, slicer, slicer.util, mrml
import json
import logging
import numpy as np
import time
import pandas as pd

from ltrace.slicer import cli_utils
from ltrace.slicer.equations.line_equation import LineEquation
from ltrace.slicer.equations.timur_coates_equation import TimurCoatesEquation
from ltrace.slicer.equations.schema import validateSchema
from ltrace.wrappers import sanitize_file_path
from pathvalidate.argparse import sanitize_filepath_arg


class PermeabilityCli:
    def __init__(self):
        pass

    def apply(self, reference_volume_node, label_map_node, segment_equation_dict):
        reference_voxel_array = slicer.util.arrayFromVolume(reference_volume_node)
        labelmap_voxel_array = slicer.util.arrayFromVolume(label_map_node)

        output_voxel_array = np.copy(reference_voxel_array)
        for segment_id, equation_table_json in segment_equation_dict.items():
            validateSchema(equation_table_json)
            segment_indexes = np.where(labelmap_voxel_array == int(segment_id))
            equation, data = self.__get_equation_from_dataframe(pd.read_json(equation_table_json))
            result = equation.equation(reference_voxel_array[segment_indexes], data.parameters)
            output_voxel_array[segment_indexes] = result
        output_voxel_array[output_voxel_array < 0] = 0
        return output_voxel_array

    @staticmethod
    def __get_equation_from_dataframe(dataframe):
        equation_type = dataframe["Fitting equation"][0]

        if equation_type == TimurCoatesEquation.NAME:
            return TimurCoatesEquation(), TimurCoatesEquation.from_df("", dataframe)
        elif equation_type == LineEquation.NAME:
            return LineEquation(), LineEquation.from_df("", dataframe)
        else:
            logging.error(f"Some selected table has no equation related to it. Invalid equation type")
            return None, None

    @staticmethod
    def __get_segment_id_from_name(segment_name, invmap):
        for id, name, color in invmap:
            if name == segment_name:
                return id
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument(
        "-i",
        "--input_volume",
        type=sanitize_filepath_arg,
        dest="input_volume",
        required=True,
        help="Input LabelMap volume",
    )
    parser.add_argument(
        "-s",
        "--segmentation_volume",
        type=sanitize_filepath_arg,
        dest="segmentation_volume",
        required=True,
        help="Segmentation volume",
    )
    parser.add_argument(
        "-o",
        "--output_volume",
        type=sanitize_filepath_arg,
        dest="output_volume",
        default=None,
        help="Output LabelMap volume",
    )
    parser.add_argument("-e", "--segment_equation_dict", type=json.loads, default={}, help="Equation for each segment")

    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument(
        "--returnparameterfile",
        type=sanitize_filepath_arg,
        default=None,
        help="File destination to store an execution outputs",
    )

    args = parser.parse_args()

    if args.input_volume is None:
        raise ValueError("Missing input volume node")

    if args.segmentation_volume is None:
        raise ValueError("Missing segmentation volume node")

    if not isinstance(args.segment_equation_dict, dict):
        raise ValueError("Missing segment equation dictionary")

    args.input_volume = sanitize_file_path(args.input_volume)
    args.segmentation_volume = sanitize_file_path(args.segmentation_volume)
    args.output_volume = sanitize_file_path(args.output_volume)
    # message += f"AFTER: args.input_volume {args.input_volume} \n args.segmentation_volume {args.segmentation_volume} \n args.output_volume {args.output_volume} \n args.segment_equation_dict {args.segment_equation_dict}\n\n@@@@\n\n"
    # raise RuntimeError(message)
    # Read as slicer node (copy)
    master_volume_node = cli_utils.readFrom(args.input_volume, mrml.vtkMRMLLabelMapVolumeNode)

    label_map_node = cli_utils.readFrom(args.segmentation_volume, mrml.vtkMRMLLabelMapVolumeNode)

    # Progress Bar example
    for i in range(0, 100, 10):
        cli_utils.progressUpdate(value=i / 100.0)
        time.sleep(0.1)

    # Do something with your input
    permeability_cli = PermeabilityCli()
    output = permeability_cli.apply(master_volume_node, label_map_node, args.segment_equation_dict)

    # Get output node ID
    output_node_id = args.output_volume
    if output_node_id is None:
        raise ValueError("Missing output volume node")

    # Write output data
    cli_utils.writeDataInto(output_node_id, output, mrml.vtkMRMLScalarVolumeNode, reference=master_volume_node)

    print("Done")
