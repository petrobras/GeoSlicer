import slicer
import logging
import tomli
import tomli_w
import numpy as np

from ltrace.slicer import helpers

METADATA_KEY = "MetadataNode"


def _convert_numpy(obj):
    if isinstance(obj, dict):
        return {k: _convert_numpy(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_numpy(i) for i in obj]
    elif isinstance(obj, (np.integer, np.floating, np.ndarray)):
        return obj.tolist()
    else:
        return obj


def _create_metadata_node(name: str, attrs: dict) -> slicer.vtkMRMLTextNode:
    text_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTextNode", name)
    text_node.SetText(tomli_w.dumps(_convert_numpy(attrs), multiline_strings=True))
    text_node.HideFromEditorsOn()
    helpers.triggerNodeModified(text_node)
    return text_node


def _metadata_from_node_id(metadata_node_id) -> dict:
    if not metadata_node_id:
        return {}

    metadata_node = slicer.mrmlScene.GetNodeByID(metadata_node_id)
    text = metadata_node.GetText()
    if not text:
        return {}

    try:
        return tomli.loads(text)
    except tomli.TOMLDecodeError as e:
        logging.warning(f"Failed to parse TOML from metadata node {metadata_node.GetName()}: {e}")
        return {}


def get_node_metadata(node: slicer.vtkMRMLNode) -> dict:
    metadata_node_id = node.GetAttribute(METADATA_KEY)
    return _metadata_from_node_id(metadata_node_id)


def get_item_metadata(item_id: int) -> dict:
    sh_node = slicer.mrmlScene.GetSubjectHierarchyNode()
    metadata_node_id = sh_node.GetItemAttribute(item_id, "MetadataNode")
    return _metadata_from_node_id(metadata_node_id)


def set_node_metadata(node: slicer.vtkMRMLNode, metadata: dict):
    metadata_node = None
    metadata_node_id = node.GetAttribute(METADATA_KEY)
    if metadata_node_id:
        metadata_node = slicer.mrmlScene.GetNodeByID(metadata_node_id)

    if metadata_node is None:
        metadata_node = _create_metadata_node(f"{node.GetID()}_Metadata", metadata)
        node.SetAttribute(METADATA_KEY, metadata_node.GetID())

    metadata_node.SetText(tomli_w.dumps(_convert_numpy(metadata), multiline_strings=True))


def set_item_metadata(item_id: int, metadata: dict):
    sh_node = slicer.mrmlScene.GetSubjectHierarchyNode()
    metadata_node_id = sh_node.GetItemAttribute(item_id, "MetadataNode")
    metadata_node = None
    if metadata_node_id:
        metadata_node = slicer.mrmlScene.GetNodeByID(metadata_node_id)

    if metadata_node is None:
        item_name = sh_node.GetItemName(item_id)
        metadata_node = _create_metadata_node(f"{item_name}_Metadata", metadata)
        sh_node.SetItemAttribute(item_id, "MetadataNode", metadata_node.GetID())

    metadata_node.SetText(tomli_w.dumps(_convert_numpy(metadata), multiline_strings=True))


def copy_metadata(source_node: slicer.vtkMRMLNode, target_node: slicer.vtkMRMLNode):
    metadata = get_node_metadata(source_node)
    set_node_metadata(target_node, metadata)


class Metadata:
    """
    A wrapper for GeoSlicer node metadata providing a convenient, dict-like interface.

    This class supports two modes of operation:

    1. Direct, single-shot operations (convenient for one-off changes):
       >>> Metadata(node)["my_key"] = "my_value"  # Reads, modifies, and writes metadata

    2. Context manager for multiple, atomic changes:
       >>> with Metadata(node) as meta:
       ...     meta["foo"] = 123
       ...     meta["date"] = "2025-11-05"

       Metadata is only written back to the node upon successful exit.
       If an exception occurs, changes are discarded.
    """

    def __init__(self, node: slicer.vtkMRMLNode):
        if not isinstance(node, slicer.vtkMRMLNode):
            raise TypeError("A valid slicer.vtkMRMLNode must be provided.")
        self._node = node
        self._metadata_cache = None

    def __getitem__(self, key):
        """Reads the full metadata and returns the value for the given key."""
        return get_node_metadata(self._node)[key]

    def __setitem__(self, key, value):
        """
        Performs a full read-modify-write cycle to set a single key.
        Convenient but inefficient for multiple updates.
        """
        metadata = get_node_metadata(self._node)
        metadata[key] = value
        set_node_metadata(self._node, metadata)

    def __delitem__(self, key):
        """Performs a full read-modify-write cycle to delete a single key."""
        metadata = get_node_metadata(self._node)
        del metadata[key]
        set_node_metadata(self._node, metadata)

    def __contains__(self, key):
        """Checks if a key exists in the metadata."""
        return key in get_node_metadata(self._node)

    def get(self, key, default=None):
        """Gets a key's value, returning a default if the key does not exist."""
        return get_node_metadata(self._node).get(key, default)

    def to_dict(self) -> dict:
        """Returns a copy of the entire metadata dictionary."""
        return get_node_metadata(self._node)

    def update(self, other_dict: dict):
        """Efficiently updates metadata with keys from another dictionary."""
        with self as meta:
            meta.update(other_dict)

    def clear(self):
        """Removes all metadata from the node."""
        set_node_metadata(self._node, {})

    def __enter__(self):
        """
        Called when entering a 'with' block.
        Loads the metadata into a temporary cache.
        """
        self._metadata_cache = get_node_metadata(self._node)
        return self._metadata_cache

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Called when exiting a 'with' block.

        If no exception occurred (exc_type is None), the cached metadata
        is written back to the node.

        If an exception occurred, the changes are discarded, ensuring the
        original metadata remains untouched (atomic operation).
        """
        if exc_type is None and self._metadata_cache is not None:
            # Success! No exception, so we commit the changes.
            set_node_metadata(self._node, self._metadata_cache)

        # Always clear the cache, and re-raise the exception if there was one.
        self._metadata_cache = None
        return False  # Returning False re-raises the exception
