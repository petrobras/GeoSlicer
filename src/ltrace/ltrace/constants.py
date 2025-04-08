"""
This module contains the constants used in the ltrace library and the GeoSlicer modules.
"""

from enum import Enum


MAX_LOOP_ITERATIONS = 100000
SIDE_BY_SIDE_IMAGE_LAYOUT_ID = 200
SIDE_BY_SIDE_SEGMENTATION_LAYOUT_ID = 201


class ImageLogConst:
    """
    Constants for the ImageLogData module.
    """

    # The default layout ID value for the ImageLogData module.
    DEFAULT_LAYOUT_ID_START_VALUE = 15000


class ImageLogInpaintConst:
    """
    Constants for ImageLogInpaint module
    """

    SEGMENT_ID = "Segment_1"
    TEMP_SEGMENTATION_NAME = "Inpaint_Segmentation_ImageLog"
    TEMP_LABEL_MAP_NAME = "Inpaint_Mask_ImageLog"
    TEMP_VOLUME_NAME = "Inpaint_Volume_ImageLog"


class DLISImportConst:
    SCALAR_VOLUME_TYPE = "ScalarVolumeType"
    WELL_PROFILE_TAG = "WellProfile"
    NULL_VALUE_TAG = "NullValue"
    LOGICAL_FILE_TAG = "LogicalFile"
    FRAME_TAG = "Frame"
    WELL_NAME_TAG = "WellName"
    UNITS_TAG = "Units"
    DEPTH_LABEL = "DEPTH"


class SaveStatus(Enum):
    IN_PROGRESS = 0
    SUCCEED = 1
    CANCELLED = 2
    FAILED = 3
    FAILED_FILE_ALREADY_EXISTS = 4
