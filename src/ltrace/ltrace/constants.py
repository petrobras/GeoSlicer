# TODO move global constants to this file

# ImageLogData.py
# docked_data.py

"""
This module contains the constants used in the ltrace library and the GeoSlicer modules.
"""

MAX_LOOP_ITERATIONS = 100000


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
