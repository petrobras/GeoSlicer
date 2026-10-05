"""The proxy node: the single MRML node through which a 4D dataset is seen.

One node is reused for every frame, repainted as the user scrubs. That keeps the scene (and the subject
hierarchy, and any module holding a reference to it) stable while the content changes, and it is what makes
the memory cost of a 4D dataset independent of its frame count — unlike ``vtkMRMLSequenceNode``, which
holds every frame at once.

The node carries enough attributes to be rebuilt from a saved project without the dataset being open.
"""

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import slicer

from .. import attributes as attrs
from ..nodes import backend_for
from ..sources.base import KIND_VOLUME
from ..virtual_node import VirtualNodeSpec, write_spec

RESOLUTION_PREVIEW = "preview"
RESOLUTION_FULL = "full"


def is_proxy(node) -> bool:
    return attrs.is_true(node, attrs.FOURD_PROXY)


def create(dataset, name: str = None, parent_item: int = None, preview_factor: int = None):
    """Create the proxy node for ``dataset`` (without painting a frame yet)."""
    info = dataset.describe()
    backend = backend_for(info)

    # Only an explicitly requested variable earns a place in the name: falling back to the reference
    # frame's own name produces things like "recon_amp_small recon_0 (4D)".
    label = name or f"{Path(dataset.root).name} {dataset.variable or ''} (4D)".replace("  ", " ")
    node = backend.create(slicer.mrmlScene.GenerateUniqueName(label.strip()), info)

    factor = int(preview_factor or dataset.preview_factor())
    write_spec(
        node,
        VirtualNodeSpec(
            uri=dataset.uri,
            node_class=info.node_class,
            kind=info.kind,
            variable=dataset.variable or info.variable,
            factor=factor,
            full_shape=info.shape_zyx,
            dtype=info.dtype,
        ),
    )

    attrs.set_bool(node, attrs.FOURD_PROXY, True)
    node.SetAttribute(attrs.FOURD_PATTERN, dataset.pattern or "")
    node.SetAttribute(attrs.FOURD_PREVIEW_FACTOR, str(factor))
    node.SetAttribute(attrs.FOURD_RESOLUTION, RESOLUTION_PREVIEW)
    update_frames(node, dataset, index=0)

    if parent_item:
        folder_tree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        item = folder_tree.GetItemByDataNode(node)
        if item:
            folder_tree.SetItemParent(item, parent_item)

    return node


def update_frames(node, dataset, index: int = None) -> None:
    """Refresh the frame bookkeeping attributes after a rescan."""
    node.SetAttribute(attrs.FOURD_FRAME_COUNT, str(dataset.frame_count))
    node.SetAttribute(attrs.FOURD_FRAME_KEYS, json.dumps(dataset.labels()))
    if index is not None:
        node.SetAttribute(attrs.FOURD_FRAME_INDEX, str(int(index)))


def paint(node, dataset, array: np.ndarray, factor: int, index: int, resolution: str = RESOLUTION_PREVIEW) -> None:
    """Write one frame into the proxy node.

    Spacing is scaled by the sampling factor, so a preview frame and a full-resolution frame of the same
    dataset occupy exactly the same physical bounds: promoting a frame changes the detail, never the
    position or the size of what the user is looking at.
    """
    info = dataset.describe()
    backend = backend_for(info)

    if info.kind != KIND_VOLUME:
        raise TypeError("4D playback is only defined for volume datasets")

    backend.write_array(node, array, info, factor=factor)

    node.SetAttribute(attrs.FOURD_RESOLUTION, resolution)
    node.SetAttribute(attrs.FOURD_FRAME_INDEX, str(int(index)))
    node.SetAttribute(attrs.DOWNSAMPLING, str(int(factor)))

    frame = dataset.frame(index)
    node.SetAttribute("FourDFrameLabel", frame.label)


def frame_index(node) -> int:
    return attrs.get_int(node, attrs.FOURD_FRAME_INDEX, 0)


def frame_labels(node) -> list:
    try:
        return json.loads(node.GetAttribute(attrs.FOURD_FRAME_KEYS) or "[]")
    except ValueError:
        return []


def resolution(node) -> str:
    return node.GetAttribute(attrs.FOURD_RESOLUTION) or RESOLUTION_PREVIEW


def follow(node) -> bool:
    return attrs.is_true(node, attrs.FOURD_FOLLOW)


def set_follow(node, value: bool) -> None:
    attrs.set_bool(node, attrs.FOURD_FOLLOW, value)


def dataset_uri(node) -> Optional[str]:
    return node.GetAttribute(attrs.URI)


def show(node) -> None:
    """Make the proxy node the visible layer, fitting the views once."""
    try:
        if node.IsA("vtkMRMLLabelMapVolumeNode"):
            slicer.util.setSliceViewerLayers(label=node, fit=True)
        else:
            slicer.util.setSliceViewerLayers(background=node, fit=True)
    except Exception as error:
        logging.debug(f"Unable to show the 4D proxy node: {error}")
