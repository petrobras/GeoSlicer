import os
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, List, Dict, Optional

import cv2
import numpy as np
import slicer
from PIL import Image, ExifTags
from natsort import natsorted
from pylibCZIrw import czi


@dataclass
class CziMetadata:
    filename: str
    spacing: List[float]
    num_timepoints: int
    num_channels: int
    channel_names: Dict[int, str]
    scene_idx: Optional[int]
    scene_base_name: str
    channel_base_name: str
    is_vector: bool
    px_components: int


def walk_files(dirpath: str):
    for i, file in enumerate(natsorted(os.listdir(dirpath))):
        yield i, os.path.join(dirpath, file)


def load_from_files(dirpath: str):
    for i, file in walk_files(dirpath):
        yield i, cv2.imread(file)


def volume_from_common_formats(filepath):
    filepath = Path(filepath)
    new_node = slicer.util.loadVolume(str(filepath), properties={"singleFile": True})
    new_node.SetName(filepath.stem)

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


def read_czi_data(filepath, image_size=None):
    """
    Reads a CZI file into numpy arrays.
    Yields:
        tuple: (metadata_dict, vol_data_list)
            metadata_dict contains:
                - filename: str
                - spacing: list of 3 floats
                - num_timepoints: int
                - num_channels: int
                - channel_names: dict
                - scene_idx: int (or None)
                - scene_base_name: str
                - channel_base_name: str
                - is_vector: bool
                - px_components: int
            vol_data_list: list of numpy arrays, one for each timepoint.
    """
    filepath = str(filepath)
    filename = Path(filepath).stem

    with czi.open_czi(filepath) as f:
        # Global Dimensions & Spacing
        total_bbox = f.total_bounding_box
        t_range = total_bbox.get("T", (0, 1))
        z_range = total_bbox.get("Z", (0, 1))
        c_range = total_bbox.get("C", (0, 1))

        num_timepoints = t_range[1] - t_range[0]
        num_channels = c_range[1] - c_range[0]

        # Parse Spacing
        spacing = [1.0, 1.0, 1.0]
        meta = f.metadata or {}
        scaling = meta.get("ImageDocument", {}).get("Metadata", {}).get("Scaling", {})
        items = scaling.get("Items", {}) if scaling else {}

        if items:
            distance_items = items.get("Distance", [])
            if not isinstance(distance_items, list):
                distance_items = [distance_items]

            axis_map = {"X": 0, "Y": 1, "Z": 2}
            for item in distance_items:
                axis_id = item.get("@Id") or item.get("Id")
                val_str = item.get("Value") or item.get("@Value")

                if axis_id in axis_map and val_str:
                    val_float = float(val_str)
                    spacing[axis_map[axis_id]] = val_float * 1000.0

        # Handle Resolution / Zoom
        zoom_factor = 1.0
        if image_size is not None:
            orig_w = total_bbox["X"][1] - total_bbox["X"][0]
            if isinstance(image_size, (int, float)):
                zoom_factor = float(image_size) / orig_w
            else:
                # Assume image_size is a tuple/list (width, height)
                zoom_factor = image_size[0] / orig_w

            # Adjust X and Y spacing to maintain physical size at new resolution
            spacing[0] /= zoom_factor
            spacing[1] /= zoom_factor

        channel_names_map = {}
        channels_meta = (
            meta.get("ImageDocument", {})
            .get("Metadata", {})
            .get("Information", {})
            .get("Image", {})
            .get("Dimensions", {})
            .get("Channels", {})
            .get("Channel", [])
        )
        if isinstance(channels_meta, dict):
            channels_meta = [channels_meta]
        for ch in channels_meta:
            try:
                idx = int(ch.get("@Id", "").replace("Channel:", ""))
                name = ch.get("@Name") or ch.get("Name")
                if name:
                    channel_names_map[idx] = name
            except (ValueError, AttributeError):
                pass

        # Iterate over Scenes
        scene_rects = getattr(f, "scenes_bounding_rectangle", {})
        if callable(scene_rects):
            scene_rects = scene_rects()

        # If populated, grab the keys (e.g., [0, 1]). If empty, use [None] to indicate a global read.
        scenes = list(scene_rects.keys()) if scene_rects else [None]
        has_multiple_scenes = len(scenes) > 1

        for scene_idx in scenes:
            scene_suffix = f"_S{scene_idx}" if (has_multiple_scenes and scene_idx is not None) else ""
            scene_base_name = f"{filename}{scene_suffix}"

            # Iterate Channels
            for c_val in range(c_range[0], c_range[1]):
                if num_channels == 1:
                    channel_base_name = scene_base_name
                else:
                    ch_label = channel_names_map.get(c_val, f"C{c_val}")
                    channel_base_name = f"{scene_base_name}_{ch_label}"

                vol_data_list = []
                is_vector = False
                px_components = 1

                # Iterate Time Steps
                for t_val in range(t_range[0], t_range[1]):
                    # Setup read arguments (only include 'scene' if it's explicitly defined)
                    sample_plane = {"C": c_val, "T": t_val, "Z": z_range[0]}
                    read_kwargs = {"plane": sample_plane}
                    if scene_idx is not None:
                        read_kwargs["scene"] = scene_idx

                    if zoom_factor != 1.0:
                        read_kwargs["zoom"] = min(zoom_factor, 1.0)

                    # Peek at the structure using our kwargs
                    sample_slice = f.read(**read_kwargs)

                    if zoom_factor > 1.0:
                        # Manual upscale
                        new_size = (int(sample_slice.shape[1] * zoom_factor), int(sample_slice.shape[0] * zoom_factor))
                        sample_slice = cv2.resize(sample_slice, new_size, interpolation=cv2.INTER_LINEAR)

                    np_dtype = sample_slice.dtype
                    px_components = sample_slice.shape[2] if len(sample_slice.shape) > 2 else 1
                    is_vector = px_components > 1

                    # The array shape is given directly by the sample slice (H, W)
                    height, width = sample_slice.shape[0], sample_slice.shape[1]
                    depth = z_range[1] - z_range[0]

                    # Allocate Numpy Volume for this specific scene
                    vol_shape = (depth, height, width, px_components) if px_components > 1 else (depth, height, width)
                    vol_data = np.zeros(vol_shape, dtype=np_dtype)

                    # Fill Z-slices
                    for z_idx_local, z_val in enumerate(range(z_range[0], z_range[1])):
                        plane_def = {"C": c_val, "T": t_val, "Z": z_val}

                        # Update kwargs for this specific Z-slice
                        read_kwargs["plane"] = plane_def
                        slice_data = f.read(**read_kwargs)

                        if zoom_factor > 1.0:
                            slice_data = cv2.resize(slice_data, new_size, interpolation=cv2.INTER_LINEAR)

                        if px_components == 1 and slice_data.ndim == 3:
                            slice_data = slice_data.squeeze(2)

                        vol_data[z_idx_local] = slice_data

                    if px_components >= 3:
                        # CZI natively uses BGR(A) format. Swap Red and Blue channels for Slicer (RGB).
                        b_channel = vol_data[..., 0].copy()
                        vol_data[..., 0] = vol_data[..., 2]
                        vol_data[..., 2] = b_channel

                    vol_data_list.append(vol_data)

                metadata = CziMetadata(
                    filename=filename,
                    spacing=spacing,
                    num_timepoints=num_timepoints,
                    num_channels=num_channels,
                    channel_names=channel_names_map,
                    scene_idx=scene_idx,
                    scene_base_name=scene_base_name,
                    channel_base_name=channel_base_name,
                    is_vector=is_vector,
                    px_components=px_components,
                )
                yield metadata, vol_data_list


def volume_from_czi(filepath, image_size=None):
    """
    Loads a CZI file into 3D Slicer.
    """
    current_scene_idx = -1
    browser_node = None

    for metadata, vol_data_list in read_czi_data(filepath, image_size=image_size):
        scene_idx = metadata.scene_idx
        scene_base_name = metadata.scene_base_name
        channel_base_name = metadata.channel_base_name
        num_timepoints = metadata.num_timepoints
        spacing = metadata.spacing
        is_vector = metadata.is_vector

        # Time Series Browser Setup (Per Scene)
        if scene_idx != current_scene_idx:
            current_scene_idx = scene_idx
            browser_node = None
            if num_timepoints > 1:
                browser_name = slicer.mrmlScene.GenerateUniqueName(f"{scene_base_name}_Browser")
                browser_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode")
                browser_node.SetName(browser_name)
                browser_node.SetPlaybackActive(False)

        channel_sequence_node = None
        if num_timepoints > 1:
            seq_name = slicer.mrmlScene.GenerateUniqueName(f"{channel_base_name}_Seq")
            channel_sequence_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode")
            channel_sequence_node.SetName(seq_name)

        proxy_node_for_channel = None

        # Iterate Time Steps
        for t_idx, vol_data in enumerate(vol_data_list):
            if num_timepoints > 1:
                node_class = "vtkMRMLVectorVolumeNode" if is_vector else "vtkMRMLScalarVolumeNode"
                volume_node = slicer.mrmlScene.CreateNodeByClass(node_class)
                volume_node.UnRegister(None)
                volume_node.SetName(f"{channel_base_name}_t{t_idx}")
            else:
                node_class = "vtkMRMLVectorVolumeNode" if is_vector else "vtkMRMLScalarVolumeNode"
                unique_vol_name = slicer.mrmlScene.GenerateUniqueName(channel_base_name)
                volume_node = slicer.mrmlScene.AddNewNodeByClass(node_class)
                volume_node.SetName(unique_vol_name)

            slicer.util.updateVolumeFromArray(volume_node, vol_data)

            # Orient correctly (Image space to Slicer RAS space)
            volume_node.SetIJKToRASDirections(-1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 1.0)

            volume_node.SetSpacing(spacing)
            volume_node.SetOrigin(0.0, 0.0, 0.0)

            if num_timepoints > 1:
                channel_sequence_node.SetDataNodeAtValue(volume_node, str(t_idx))
            else:
                proxy_node_for_channel = volume_node
                proxy_node_for_channel.CreateDefaultDisplayNodes()

        # Finalize Channel
        if num_timepoints > 1:
            browser_node.AddSynchronizedSequenceNode(channel_sequence_node)
            browser_node.SetRecording(channel_sequence_node, True)

            slicer.modules.sequences.logic().UpdateProxyNodesFromSequences(browser_node)

            proxy_node_for_channel = browser_node.GetProxyNode(channel_sequence_node)
            if proxy_node_for_channel:
                proxy_node_for_channel.SetName(slicer.mrmlScene.GenerateUniqueName(channel_base_name))
                proxy_node_for_channel.SetSpacing(spacing)
                proxy_node_for_channel.CreateDefaultDisplayNodes()

        if proxy_node_for_channel:
            yield proxy_node_for_channel


@dataclass
class CziSizeInfo:
    image_size: Tuple[int, int]
    mem_size: int


def get_czi_sizes(filepath: str) -> List[CziSizeInfo]:
    filepath = str(filepath)
    sizes = []

    with czi.open_czi(filepath) as f:
        # 1. Get Base Dimensions
        total_bbox = f.total_bounding_box

        w = max(1, total_bbox.get("X", (0, 1))[1] - total_bbox.get("X", (0, 1))[0])
        h = max(1, total_bbox.get("Y", (0, 1))[1] - total_bbox.get("Y", (0, 1))[0])
        d = max(1, total_bbox.get("Z", (0, 1))[1] - total_bbox.get("Z", (0, 1))[0])
        t = max(1, total_bbox.get("T", (0, 1))[1] - total_bbox.get("T", (0, 1))[0])

        c_start = total_bbox.get("C", (0, 1))[0]
        c_end = total_bbox.get("C", (0, 1))[1]

        # 2. Extract Pyramid Info from Metadata
        meta = f.metadata or {}
        image_info = meta.get("ImageDocument", {}).get("Metadata", {}).get("Information", {}).get("Image", {})
        dimensions = image_info.get("Dimensions", {})
        s_info = dimensions.get("S", {}).get("Scenes", {}).get("Scene", {})

        if isinstance(s_info, list):
            s_info = s_info[0]

        pyramid_info = s_info.get("PyramidInfo", {})
        layers_count = int(pyramid_info.get("PyramidLayersCount", 1))
        min_factor = float(pyramid_info.get("MinificationFactor", 2.0))

        # 3. Determine Bytes Per Pixel (Iterating over ALL channels)
        def get_pt_bytes(pt_name):
            pt_name = str(pt_name).lower()
            if "bgr24" in pt_name or "rgb24" in pt_name:
                return 3
            if "bgr48" in pt_name or "rgb48" in pt_name:
                return 6
            if "gray32" in pt_name or "float32" in pt_name:
                return 4
            if "gray16" in pt_name:
                return 2
            if "gray8" in pt_name:
                return 1
            return 1  # Fallback

        bytes_per_pixel_coord = 0

        # Loop through each channel individually to support mixed pixel types
        for c_idx in range(c_start, c_end):
            try:
                ch_pt = f.get_channel_pixel_type(c_idx)
            except Exception:
                ch_pt = "gray8"

            ch_bytes = get_pt_bytes(ch_pt)
            bytes_per_pixel_coord += ch_bytes

        # 4. Generate the ACTUAL stored layers
        for i in range(layers_count):
            zoom = 1.0 / (min_factor**i)
            level_w = max(1, int(w * zoom))
            level_h = max(1, int(h * zoom))

            # Memory = W * H * Z * T * SumOfAllChannelBytes
            mem_size = level_w * level_h * d * t * bytes_per_pixel_coord

            sizes.append(CziSizeInfo(image_size=(level_w, level_h), mem_size=mem_size))

    return sizes


def get_czi_item_count(filepath: str) -> int:
    filepath = str(filepath)
    with czi.open_czi(filepath) as f:
        total_bbox = f.total_bounding_box
        c_range = total_bbox.get("C", (0, 1))
        num_channels = c_range[1] - c_range[0]

        scene_rects = getattr(f, "scenes_bounding_rectangle", {})
        if callable(scene_rects):
            scene_rects = scene_rects()
        num_scenes = len(scene_rects) if scene_rects else 1
        return num_scenes * num_channels
