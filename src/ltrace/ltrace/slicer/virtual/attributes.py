"""Node attribute names shared by every deferred-data feature.

A virtual node is an ordinary MRML node (volume, label map, vector volume or table) whose data is only a
*sample* of a much larger source that stays on disk. The attributes below are what makes it recognizable
without opening the source again, so they are the contract between the creator (``virtual_node``), the
folder monitor, the 4D player and the UI that surfaces them.

``SPEC`` holds the authoritative, machine-readable description; the individual attributes duplicate the
few fields a human (or a node-attribute filter in a node selector) needs to see, as required by the task.
"""

TRUE = "True"
FALSE = "False"

# --- virtual node ------------------------------------------------------------------------------------
VIRTUAL_NODE = "VirtualNode"
"""Set to ``"True"`` on every virtual node. Node selectors can filter on it."""

SPEC = "VirtualNodeSpec"
"""JSON serialization of :class:`ltrace.slicer.virtual.virtual_node.VirtualNodeSpec`."""

URI = "VirtualNodeURI"
"""URI of the original data, e.g. ``file:///data/tomo.nc`` or ``4d:///data/LBPM?pattern=vis%5Cd%2B``."""

VARIABLE = "VirtualNodeVariable"
"""Name of the variable inside the source, when the source holds more than one."""

DOWNSAMPLING = "VirtualNodeDownsampling"
"""Sampling factor of the data currently held by the node (1 means full resolution)."""

SAMPLE_ROWS = "VirtualNodeSampleRows"
"""Number of rows held by a virtual table node."""

FULL_SHAPE = "VirtualNodeFullShape"
"""Shape of the original data as ``"z,y,x"``."""

FULL_ROWS = "VirtualNodeFullRows"
"""Row count of the original table, when known (counting rows can be expensive, so it may be absent)."""

DTYPE = "VirtualNodeDtype"
"""Numeric type of the original data."""

STALE = "VirtualNodeStale"
"""``"True"`` when the source could not be reached on the last attempt. Nodes are never auto-deleted."""

SOURCE_STAMP = "VirtualNodeSourceStamp"
"""Cheap change stamp of the source (size/mtime digest) used to detect that a refresh is needed."""

FOLDER_ROOT = "VirtualFolderRoot"
"""Root of the monitored folder that produced this node, when it came from one."""

# --- 4D proxy ----------------------------------------------------------------------------------------
FOURD_PROXY = "FourDProxy"
"""``"True"`` on the proxy node that surfaces a 4D dataset. Such nodes are also virtual nodes."""

FOURD_FRAME_COUNT = "FourDFrameCount"
FOURD_FRAME_INDEX = "FourDFrameIndex"
FOURD_FRAME_KEYS = "FourDFrameKeys"
"""JSON list of the frame labels (e.g. LBPM timesteps), in playback order."""

FOURD_RESOLUTION = "FourDResolution"
"""``"preview"`` while scrubbing, ``"full"`` once the user loads the settled frame at full resolution."""

FOURD_PREVIEW_FACTOR = "FourDPreviewFactor"
FOURD_PATTERN = "FourDPattern"
FOURD_FOLLOW = "FourDFollow"


def is_true(node, attribute: str) -> bool:
    """Whether ``attribute`` is set to ``"True"`` on ``node`` (tolerant of ``None`` nodes)."""
    return node is not None and node.GetAttribute(attribute) == TRUE


def set_bool(node, attribute: str, value: bool) -> None:
    node.SetAttribute(attribute, TRUE if value else FALSE)


def get_int(node, attribute: str, default: int = 0) -> int:
    try:
        return int(node.GetAttribute(attribute))
    except (TypeError, ValueError):
        return default
