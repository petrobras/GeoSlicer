import cv2
import re
import vtk

from array import array
from ltrace.image.core_box.core_box import CoreBox
import numpy as np

from ltrace.image.core_box.core_boxes_image_file import CoreBoxesImageFile
from ltrace.image.core_box.core_box_depth_table_file import CoreBoxDepthTableFile
from ltrace.slicer.helpers import concatenateImageArrayVertically
import slicer


class CoreImage:
    def __init__(
        self,
        core_boxes_files_dict,
        fixed_box_height_meter,
        user_defined_start_depth,
        input_depth_table_file,
        gpuEnabled=True,
    ):
        self.__array = None
        self.__total_height = None
        self.__spacing = None
        self.__origin = 0
        self.__core_boxes_list = list()
        self.__core_boxes_files_dict = core_boxes_files_dict
        self.__fixed_box_height_meter = fixed_box_height_meter
        self.__user_defined_start_depth = user_defined_start_depth
        self.__input_depth_table_file = input_depth_table_file
        self.__gpuEnabled = gpuEnabled

    @property
    def array(self):
        if self.__array is None:
            self.__array = self.__create_array_from_images()

        return self.__array

    @property
    def total_height(self):
        if self.__total_height is None:
            self.__total_height = self.__get_total_height()

        return self.__total_height

    @property
    def origin(self):
        return self.__origin

    @property
    def spacing(self):
        return self.__spacing

    def __get_total_height(self):
        total_height = 0
        for core_boxes in self.__core_boxes_list:
            total_height += core_boxes.total_height

        return total_height

    def __create_array_from_images(self):
        # Load depth table file, if there is one.
        # Otherwise, will check for user defined start depth.
        # One of those options should be available. If none of them were, then the process should fail
        depth_table_file = None
        core_boxes_depth_list = None
        if self.__input_depth_table_file != "" and self.__input_depth_table_file is not None:
            depth_table_file = CoreBoxDepthTableFile(self.__input_depth_table_file)
            core_boxes_depth_list = depth_table_file.core_boxes_depth_list

        # Start concatenating the core boxes
        core_boxes_list = []
        current_depth = self.__user_defined_start_depth
        core_ids = sorted(self.__core_boxes_files_dict.keys())
        for id in core_ids:
            core_boxes_files_list = self.__core_boxes_files_dict[id]
            cores_box_from_id = list()
            for core_boxes_file in core_boxes_files_list:
                core_boxes = CoreBoxesImageFile(
                    core_boxes_file,
                    default_depth=self.__fixed_box_height_meter,
                    load=True,
                    core_boxes_depth_list=core_boxes_depth_list,
                    start_depth=current_depth,
                    gpuEnabled=self.__gpuEnabled,
                )
                if current_depth is not None:
                    current_depth += core_boxes.total_height
                cores_box_from_id.append(core_boxes)

            # Sort in asceding order by box number
            cores_box_from_id.sort(key=lambda core_boxes: core_boxes.first_box_number)

            # Group core boxes with the other core box with different core ID
            core_boxes_list.extend(cores_box_from_id)

        if len(core_boxes_list) <= 0:
            message = "No core image was detected in the input files."
            raise RuntimeError(message)

        self.__core_boxes_list = core_boxes_list
        # Concatenate all arrays vertically
        full_array, spacing, origin = self.__concatenate_core_boxes_images(core_boxes_list)

        # Create report table with the vector volume node attributes
        self.__origin = -origin * 1000  # mm
        self.__spacing = spacing * 1000  # m to mm

        # old way to force interface selection
        # Create report table with the vector volume node attributes
        # self.__origin = -core_boxes_list[0].start_depth * 1000 # mm
        # total_height_pixel_size = full_array.shape[0]
        # if total_height_pixel_size != 0:
        #     self.__spacing = 1000*self.total_height/total_height_pixel_size  # mm
        # else:
        #     self.__spacing = self.__fixed_box_height_meter * 1000 # mm
        #     raise RuntimeError("Invalid depth calculation for completed core image.")

        return full_array

    def __concatenate_core_boxes_images(self, image_core_boxes_list):
        single_core_boxes_list = []
        for core_boxes in image_core_boxes_list:
            single_core_boxes_list.extend(core_boxes.list)
        return concatenate_core_boxes(single_core_boxes_list)


def concatenate_core_boxes(single_core_boxes_list):
    core_boxes_array_list = []

    # gather the minimum spacing (smaller pixel size)
    min_spacing = np.inf
    max_width = 0
    for core_box in single_core_boxes_list:
        max_width = max(max_width, core_box.pixels_width())
        min_spacing = min(min_spacing, core_box.spacing())
        n_data = core_box.array.shape[2]

    initial_depth = single_core_boxes_list[0].start_depth
    final_depth = single_core_boxes_list[-1].end_depth

    total_height_pixels = (final_depth - initial_depth) / min_spacing
    cores_array = np.zeros([round(total_height_pixels), round(max_width), n_data])

    # reds = np.zeros((10,round(max_width),3)) ## red stripe at the beggining of cores for debug
    # reds[:,:,0] = 255

    for core_box in single_core_boxes_list:
        core_box.resize_vertical_spacing(min_spacing)
        core_box.resize_horizontal(max_width)
        core_boxes_array_list.append(core_box.array)

        pixel_index_top = round((core_box.start_depth - initial_depth) / min_spacing)
        cores_array[pixel_index_top : pixel_index_top + core_box.pixels_height(), :, :] = core_box.array
        # cores_array[pixel_index_top:pixel_index_top + 10, :, :] = reds

    return cores_array, min_spacing, initial_depth
