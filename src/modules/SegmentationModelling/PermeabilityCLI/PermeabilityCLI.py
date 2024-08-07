#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

import json
import logging
import time

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
import mrml
import numpy as np
import pandas as pd
import slicer
import slicer.util

from ltrace.slicer.equations.line_equation import LineEquation
from ltrace.slicer.equations.timur_coates_equation import TimurCoatesEquation

from ltrace.slicer import cli_utils


class PermeabilityCli:
    def __init__(self):
        pass

    def apply(self, reference_volume_node, label_map_node, segment_equation_dict):
        reference_voxel_array = slicer.util.arrayFromVolume(reference_volume_node)
        labelmap_voxel_array = slicer.util.arrayFromVolume(label_map_node)

        output_voxel_array = np.copy(reference_voxel_array)
        for segment_id, equation_table_json in segment_equation_dict.items():
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
            logging.error(f"Some selected table has no equation related to it. Invalid equation type: {equation_type}")
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
        "-i", "--input_volume", type=str, dest="input_volume", required=True, help="Input LabelMap volume"
    )
    parser.add_argument(
        "-s", "--segmentation_volume", type=str, dest="segmentation_volume", required=True, help="Segmentation volume"
    )
    parser.add_argument(
        "-o", "--output_volume", type=str, dest="output_volume", default=None, help="Output LabelMap volume"
    )
    parser.add_argument("-e", "--segment_equation_dict", type=json.loads, default={}, help="Equation for each segment")

    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument(
        "--returnparameterfile", type=str, default=None, help="File destination to store an execution outputs"
    )

    args = parser.parse_args()

    if args.input_volume is None:
        raise ValueError("Missing input volume node")

    if args.segmentation_volume is None:
        raise ValueError("Missing segmentation volume node")

    output_volume_node_ID = args.output_volume

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
    if output_volume_node_ID is None:
        raise ValueError("Missing output volume node")

    # Write output data
    cli_utils.writeDataInto(output_volume_node_ID, output, mrml.vtkMRMLScalarVolumeNode, reference=master_volume_node)

    print("Done")
