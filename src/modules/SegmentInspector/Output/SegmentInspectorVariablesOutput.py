from collections import Counter

import slicer
import numpy as np
import pandas as pd

from ltrace.slicer.helpers import getCountForLabels


class SegmentInspectorVariablesOutput:
    def __init__(
        self, label_map_node, labels, params, report_data, target_labels=None, roi_node=None, segment_map=None
    ):
        self.__label_map_node = label_map_node
        self.__target_labels = target_labels
        self.__roi_node = roi_node
        self.__labels = labels
        self.__params = params
        self.__report_data = report_data
        self.__data = None
        self.__segment_map = segment_map

        self.__check_inputs()
        self.__generate_data()

    @property
    def data(self):
        """Get output as pandas.DataFrame."""
        return self.__data

    def __check_inputs(self):
        if self.__label_map_node is None:
            raise RuntimeError("Invalid input node for Segment Inspector report generator")

    def __generate_data(self):
        """Create report as a pandas.DataFrame and store it"""
        input_voxel_array = slicer.util.arrayFromVolume(self.__label_map_node)
        shape = input_voxel_array.shape
        spacing = np.array(self.__label_map_node.GetSpacing())[np.where(shape != 1)]
        vixel_dim_tag = "Volume (mm^3)" if len(spacing) > 2 else "Area (mm^2)"
        voxel_size = np.prod(spacing)
        method = self.__params["method"]

        if self.__segment_map is None:
            segment_map = getCountForLabels(self.__label_map_node, self.__roi_node)
        else:
            segment_map = self.__segment_map

        total_voxel_count = segment_map["total"]
        del segment_map["total"]
        segment_voxel_count = sum([segment_map[k]["count"] for k in segment_map])

        data = {
            f"Pixel {vixel_dim_tag}": voxel_size,
            "ROI Voxel Count (#px)": total_voxel_count,
            "Segment Voxel Count (#px)": segment_voxel_count,
        }

        for idx in segment_map:
            count = segment_map[idx]["count"]
            percentage = np.round(count * 100 / total_voxel_count, decimals=5)
            data[f"Segment {idx}: Name"] = self.__labels[idx]
            data[f"Segment {idx}: %"] = percentage
            if int(total_voxel_count) != int(segment_voxel_count):
                soi_percentage = np.round(count * 100 / segment_voxel_count, decimals=5)
                data[f"Segment {idx}: % SOI"] = soi_percentage

            data[f"Segment {idx}: #px"] = count

        data["Function"] = method

        if self.__target_labels:
            data["Targets"] = ", ".join([str(k) for k, _ in self.__target_labels.items()])

        if method != "mineralogy":
            for k, v in self.__get_pore_size_class_proportions().items():
                data[k] = v

        # Adjust direction parameter
        direction = self.__params.get("direction", None)
        if direction is not None and len(direction) <= 0:
            self.__params["direction"] = None

        params_black_list = ("method", "throatOutputReport", "throatOutputLabelVolume")
        data.update({f"parameter.{key}": self.__params[key] for key in self.__params if key not in params_black_list})

        self.__data = pd.DataFrame(
            data={"Properties": [key for key in data], "Values": [repr(val) for val in data.values()]}, dtype=str
        )

    def __get_pore_size_class_proportions(self):
        """Create dictionray with the (percent) proportion of pore size class
           from the input's report data.

        Raises:
            RuntimeError: If data related to the pore size class doesn't exist at the report data.

        Returns:
            dict: a dictionary containing the proportion for each pore size class.
        """
        if self.__report_data is None:
            return dict()

        pore_class_list = []
        try:
            pore_class_list = self.__report_data["pore_size_class"].tolist()
        except KeyError:
            raise RuntimeError("Invalid Segment Inspector report output")

        pore_class_list.sort()
        pore_class_counter = Counter(pore_class_list)
        total_pore_class = len(pore_class_list)
        pore_class_proportion_dict = {
            f"{k} (%)": round(100 * v / total_pore_class, 3) for k, v in dict(pore_class_counter).items()
        }

        return pore_class_proportion_dict
