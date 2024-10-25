import os
from pathlib import Path
import re
import logging

import numpy as np
import slicer
import xarray as xr
from ltrace.slicer.netcdf import import_dataset
from ltrace.slicer_utils import *
from ltrace.slicer import loader
from ltrace.units import global_unit_registry as ureg, SLICER_LENGTH_UNIT

from collections import defaultdict
from typing import List, Tuple
from tifffile import TiffFile
from natsort import natsorted


ROOT_DATASET_DIRECTORY_NAME = "Micro CT"
MICRO_CT_LOADER_FILE_EXTENSIONS = [".tif", ".tiff", ".png", ".jpg", ".jpeg", ".nc"]
SPACING_REGEX = re.compile(r"_(\d{5})nm")


def load(
    path,
    callback=lambda message, percent, processEvents=True: None,
    imageSpacing=(1.0 * ureg.micrometer, 1.0 * ureg.micrometer, 1.0 * ureg.micrometer),
    centerVolume=True,
    invertDirections=[True, True, False],
    loadAsLabelmap=False,
    baseName=None,
):
    if path.suffix == ".nc":
        return _loadNetCDF(path, callback)
    if path.is_file():
        singleFile = True
        pathBaseName = path.parent.name
    else:
        singleFile = False
        pathBaseName = path.name
    base = baseName or slicer.mrmlScene.GetUniqueNameByString(pathBaseName)
    _, images, isVolumes = getCountsAndLoadPathsForImageFiles(path)

    nodes = [
        _loadImage(file, imageSpacing, centerVolume, invertDirections, loadAsLabelmap, base, singleFile or isVolumes)
        for file in images
    ]
    return nodes


def _loadNetCDF(path, callback):
    dataset = xr.open_dataset(path)
    dataset_name = path.with_suffix("").name

    folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    scene_id = folderTree.GetSceneItemID()
    current_dir = folderTree.CreateFolderItem(scene_id, dataset_name)
    folderTree.SetItemAttribute(current_dir, "netcdf_path", path.as_posix())

    nodes = []
    for node, progress in zip(import_dataset(dataset), np.arange(10, 100, 90 / len(dataset))):
        callback("Loading...", progress, True)
        _ = folderTree.CreateItem(current_dir, node)
        nodes.append(node)
    return nodes


def _loadImage(file, imageSpacing, centerVolume, invertDirections, loadAsLabelmap, baseName, singleFile=False):
    loadAsLabelmap = loadAsLabelmap and singleFile
    node = slicer.util.loadVolume(str(file), properties={"singleFile": singleFile, "labelmap": loadAsLabelmap})

    spacing = [
        imageSpacing[0].m_as(SLICER_LENGTH_UNIT),
        imageSpacing[1].m_as(SLICER_LENGTH_UNIT),
        imageSpacing[2].m_as(SLICER_LENGTH_UNIT),
    ]
    node.SetSpacing(spacing)

    if centerVolume:
        transformAdded = node.AddCenteringTransform()
        if transformAdded:
            node.HardenTransform()
            slicer.mrmlScene.RemoveNode(slicer.util.getNode(node.GetName() + " centering transform"))

    if singleFile:
        node.SetIJKToRASDirections(
            -1 if invertDirections[0] else 1,
            0,
            0,
            0,
            -1 if invertDirections[1] else 1,
            0,
            0,
            0,
            -1 if invertDirections[2] else 1,
        )

    storageNode = node.GetStorageNode()
    storageNode.SetFileName(str(Path(storageNode.GetFileName()).with_suffix(".nrrd")))
    loader.configureInitialNodeMetadata(ROOT_DATASET_DIRECTORY_NAME, baseName, node)
    slicer.util.resetSliceViews()
    return node


def _getImageList(path: Path) -> List[str]:
    paths = []
    for filename in os.listdir(path):
        filepath = path / filename
        if filepath.suffix.lower() in MICRO_CT_LOADER_FILE_EXTENSIONS:
            paths.append(filepath)

    file_groups = defaultdict(dict)
    pattern = re.compile(r"(.*nm)(\d+)$")
    for path in paths:
        match_ = pattern.match(path.stem)
        if match_:
            name = match_.group(1)
            index = int(match_.group(2))
            file_groups[name][index] = path

    filtered_groups = []
    for group in file_groups.values():
        index = min(group.keys())
        count = 0
        new_group = []
        while count + index in group:
            new_group.append(group[count + index])
            count += 1
        filtered_groups.append(new_group)

    largest_group = []
    for group in filtered_groups:
        if len(group) > len(largest_group):
            largest_group = group

    ret_paths = largest_group if largest_group else paths

    return natsorted(ret_paths, key=lambda x: str(x))


def detectSpacing(path):
    if path.is_file():
        pathList = [path, path.parent]
    elif path.exists():
        pathList = [path] + _getImageList(path)
    else:
        return None
    for path in pathList:
        name = Path(path).name

        autoSpacing = SPACING_REGEX.search(name)
        if not autoSpacing:
            continue
        sp = int(autoSpacing.group(1)) * ureg.nanometer
        spacing = [sp] * 3
        return spacing
    return None


def getCountsAndLoadPathsForImageFiles(path: Path) -> Tuple[int, List[Path], bool]:  # -> (count, paths, is3dBatch)
    if not path.exists():
        return 0, [], False

    try:
        if path.is_file():
            if path.suffix.lower() not in MICRO_CT_LOADER_FILE_EXTENSIONS:
                return 0, [], False
            if path.suffix.lower().startswith(".tif"):
                with TiffFile(path) as tiff:
                    num_pages = len(tiff.pages)
                    return (
                        max(num_pages, 1),
                        [path],
                        False,
                    )
            return 1, [path], False

        elif path.is_dir():
            images = _getImageList(path)
            if not images:
                return 0, [], False

            if len(images) > 0 and images[0].suffix.lower().startswith(".tif"):
                with TiffFile(images[0]) as tiff:
                    if len(tiff.pages) > 1:
                        return len(images), images, True  # is3dBatch = True

            return len(images), [images[0]], False
    except Exception as e:
        logging.debug(repr(e))
        return 0, [], False
