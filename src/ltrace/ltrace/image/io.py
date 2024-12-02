import os

import cv2
from natsort import natsorted
import numpy as np
from PIL import Image, ExifTags
from pathlib import Path
import slicer


def walk_files(dirpath: str):
    for i, file in enumerate(natsorted(os.listdir(dirpath))):
        yield i, os.path.join(dirpath, file)


def load_from_files(dirpath: str):
    for i, file in walk_files(dirpath):
        yield i, cv2.imread(file)


def volume_from_image(filepath):
    new_node = slicer.util.loadVolume(str(filepath), properties={"singleFile": True})
    new_node.SetName(Path(filepath).stem)

    with Image.open(filepath) as image:
        if image.format == "PNG":
            # Remove alpha channel from RGBA array
            array = slicer.util.arrayFromVolume(new_node)
            array = array[:, :, :, :3]
            slicer.util.updateVolumeFromArray(new_node, array)
        elif image.format != "JPEG":
            return new_node

        try:
            exif = image._getexif()
        except AttributeError:
            # Image file has no exif
            return new_node

    for orientation in ExifTags.TAGS.keys():
        if ExifTags.TAGS[orientation] == "Orientation":
            break
    try:
        image_orientation = exif[orientation]
    except (KeyError, IndexError, TypeError):
        # Exif has no orientation info
        return new_node

    image_array = slicer.util.arrayFromVolume(new_node)
    if image_orientation == 3:  # 180
        image_array = np.rot90(image_array, 2, (1, 2))
    elif image_orientation == 6:  # 270
        image_array = np.rot90(image_array, 3, (1, 2))
    elif image_orientation == 8:  # 90
        image_array = np.rot90(image_array, 1, (1, 2))
    slicer.util.updateVolumeFromArray(new_node, image_array)

    return new_node
