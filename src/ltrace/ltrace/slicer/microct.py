import os
from pathlib import Path
import re
import logging

import numpy as np
import slicer
import xarray as xr
from ltrace.slicer import netcdf
from ltrace.slicer_utils import *
from ltrace.slicer import loader
from ltrace.units import global_unit_registry as ureg, SLICER_LENGTH_UNIT

from collections import defaultdict
from typing import List, Tuple
from tifffile import TiffFile
from natsort import natsorted


ROOT_DATASET_DIRECTORY_NAME = "Micro CT"
MICRO_CT_LOADER_FILE_EXTENSIONS = [".tif", ".tiff", ".png", ".jpg", ".jpeg", ".nc", ".h5", ".hdf5"]
SPACING_REGEX = re.compile(r"_(\d{5})nm")


def load(
    path,
    callback=lambda message, percent, processEvents=True: None,
    imageSpacing=(1.0 * ureg.micrometer, 1.0 * ureg.micrometer, 1.0 * ureg.micrometer),
    imageOrigin=(0.0 * ureg.micrometer, 0.0 * ureg.micrometer, 0.0 * ureg.micrometer),
    centerVolume=True,
    invertDirections=[True, True, False],
    loadAsLabelmap=False,
    loadAsSequence=False,
    baseName=None,
):
    if path.suffix in (".nc", ".h5", ".hdf5"):
        nodes = netcdf.import_file(path, callback)
        # NetCDF already handles PCR
        pcrNode = None
    else:
        if path.is_file():
            singleFile = True
            pathBaseName = path.parent.name
            parentPath = path.parent
        else:
            singleFile = False
            pathBaseName = path.name
            parentPath = path

        base = baseName or slicer.mrmlScene.GetUniqueNameByString(pathBaseName)
        _, images, isVolumes = getCountsAndLoadPathsForImageFiles(path)

        nodes = [
            _loadImage(
                file,
                imageSpacing,
                imageOrigin,
                centerVolume,
                invertDirections,
                loadAsLabelmap,
                base,
                singleFile or isVolumes,
            )
            for file in images
        ]

        try:
            pcrNode = loadPCRInfoIfExist(parentPath)
        except FileNotFoundError:
            logging.debug("No PCR file found in the directory")
            pcrNode = None

    if pcrNode:
        setPCRFile(nodes, pcrNode)

    if loadAsSequence:
        return _createSequenceFromNodeList(nodes, path.name)

    return nodes


def loadPCRInfoIfExist(path):
    fpath = Path(path)
    directory = fpath if fpath.is_dir() else fpath.parent
    for file in directory.rglob(f"*.pcr"):
        return loadPCRAsTextNode(file)

    raise FileNotFoundError("No PCR file found in the directory")


def setPCRFile(nodes, pcrNode):
    if not isinstance(nodes, list):
        nodes = [nodes]

    for node in nodes:
        if pcrNode:
            node.SetAttribute("PCR", pcrNode.GetID())

    # Place PCR node in the same subject hierarchy folder as the first image node
    if nodes and pcrNode:
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        imageItemID = shNode.GetItemByDataNode(nodes[0])
        parentItemID = shNode.GetItemParent(imageItemID)
        pcrItemID = shNode.GetItemByDataNode(pcrNode)
        if parentItemID and pcrItemID:
            shNode.SetItemParent(pcrItemID, parentItemID)


def _createSequenceFromNodeList(nodeList, directoryName):
    subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    nodeTreeId = subjectHierarchyNode.GetItemByDataNode(nodeList[0])
    parentItemId = subjectHierarchyNode.GetItemParent(nodeTreeId)

    sequenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", f"{directoryName}_sequence")
    sequenceNode.SetIndexUnit("")
    sequenceNode.SetIndexName("Volume")

    browserNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", f"{directoryName}_browser")
    browserNode.SetIndexDisplayFormat("%.0f")

    for index in range(len(nodeList)):
        node = nodeList[index]
        sequenceNode.SetDataNodeAtValue(node, str(index))

    for node in nodeList:
        slicer.mrmlScene.RemoveNode(node)

    browserNode.SetAndObserveMasterSequenceNodeID(sequenceNode.GetID())

    proxyNode = browserNode.GetProxyNode(sequenceNode)
    proxyNode.SetName(f"{directoryName}_proxy")

    subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(proxyNode), parentItemId)

    return nodeList


def _loadImage(
    file, imageSpacing, imageOrigin, centerVolume, invertDirections, loadAsLabelmap, baseName, singleFile=False
):
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

    directions = [-1 if invert else 1 for invert in invertDirections]
    if singleFile:
        x = directions[0], 0, 0
        y = 0, directions[1], 0
        z = 0, 0, directions[2]
        node.SetIJKToRASDirections(*x, *y, *z)

    node.SetOrigin(*(o.m_as(SLICER_LENGTH_UNIT) * d for o, d in zip(imageOrigin, directions)))

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
    pattern = re.compile(r"^(.*?)(\d+)$")
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


def minMaxFromPcr(pcrFile):
    import configparser

    config = configparser.ConfigParser()
    try:
        if pcrFile.suffix == ".nc":
            try:
                with xr.open_dataset(pcrFile) as ds:
                    pcr_string = ds.attrs.get("pcr")
                    if not pcr_string:
                        return None
                    config.read_string(ds.attrs["pcr"])
            except Exception:
                return None
        else:
            config.read(pcrFile)
        min_ = config.getfloat("VolumeData", "Min")
        max_ = config.getfloat("VolumeData", "Max")
    except configparser.Error:
        return None
    return min_, max_


def loadPCRAsTextNode(pcrFile):
    import configparser

    try:
        config = configparser.ConfigParser()

        pcr = None

        if pcrFile.suffix in (".nc", ".h5", ".hdf5"):
            try:
                with xr.open_dataset(pcrFile) as ds:
                    pcr = ds.attrs["pcr"]
            except Exception as e:
                logging.debug(f"Failed to load PCR from NetCDF. Cause: {repr(e)}")
        else:
            pcr = pcrFile.read_text()

        if not pcr:
            return None

        try:
            config.read_string(pcr)
        except configparser.Error as e:
            logging.debug(f"Failed to parse PCR string. Cause: {repr(e)}")
            return None

        textNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTextNode", f"{pcrFile.stem}_attr_pcr")
        textNode.SetText(pcr)
        textNode.SetAttribute("IsNcAttrs", "1")
        textNode.SetAttribute("AttrKey", "pcr")

    except Exception as e:
        logging.debug(f"Failed to load PCR file. Cause: {repr(e)}")
        return None

    return textNode


# def loadPCRIntoTextNode(pcrFile):
#     import configparser
#
#     config = configparser.ConfigParser()
#     try:
#         if pcrFile.suffix in (".nc", ".h5", ".hdf5"):
#             try:
#                 with xr.open_dataset(pcrFile) as ds:
#                     pcr_string = ds.attrs.get("pcr")
#                     if not pcr_string:
#                         return None
#
#                     config.read_string(pcr_string)
#             except Exception as e:
#                 logging.debug(f"Failed to load PCR from NetCDF: {e}")
#                 raise
#         else:
#             config.read(pcrFile)
#             content = pcrFile.read_text()
#         config.
#         if not content:
#             return None
#
#         textNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTextNode", f"{pcrFile.stem}_PCR")
#         textNode.SetText(content)
#         return textNode
#
#     except configparser.Error:
#         return None
