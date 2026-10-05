"""Registry of node backends. New node classes only need a backend here to become virtual-able."""

from typing import List, Type

from ..sources.base import SourceInfo, UnsupportedSourceError
from .base import VirtualNodeBackend, apply_geometry
from .tables import TableBackend
from .volumes import LabelMapVolumeBackend, ScalarVolumeBackend, VectorVolumeBackend, VolumeBackend

BACKENDS: List[Type[VirtualNodeBackend]] = [
    TableBackend,
    LabelMapVolumeBackend,
    VectorVolumeBackend,
    ScalarVolumeBackend,
]


def backend_for(info: SourceInfo) -> Type[VirtualNodeBackend]:
    for backend in BACKENDS:
        if backend.handles(info):
            return backend
    raise UnsupportedSourceError(f"No virtual node backend for {info.node_class}")


def backend_for_class(node_class: str) -> Type[VirtualNodeBackend]:
    for backend in BACKENDS:
        if backend.NODE_CLASS == node_class:
            return backend
    raise UnsupportedSourceError(f"No virtual node backend for {node_class}")
