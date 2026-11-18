"""Cores and memory this process may actually use, narrowed to what a cgroup/cpuset allows."""

import os

import psutil
from pathlib import Path


FEATURE_MEM_FRACTION = 0.25
FEATURE_MEM_MIN_BYTES = 1024 * 1024 * 1024
SLAB_THICKNESS_ENV = "GEOSLICER_SEG_SLAB_THICKNESS"
CGROUP_MEMORY_LIMIT_PATHS = (
    "/sys/fs/cgroup/memory.max",  # v2
    "/sys/fs/cgroup/memory/memory.limit_in_bytes",  # v1
)


def available_cores():
    """Cores this process may run on: its CPU affinity, capped by the physical count."""
    physical = psutil.cpu_count(logical=False) or os.cpu_count() or 2
    try:
        allowed = len(psutil.Process().cpu_affinity())
    except (AttributeError, NotImplementedError, OSError):  # macOS, restricted hosts
        allowed = physical
    return max(1, min(allowed, physical))


def max_worker_threads():
    """Workers for the interactive feature precompute, leaving a core for the OS/UI."""
    return max(1, available_cores() - 1)


def _available_memory():
    available = psutil.virtual_memory().available
    for path in CGROUP_MEMORY_LIMIT_PATHS:
        try:
            limit = Path(path).read_text().strip()
        except OSError:
            continue
        if limit.isdigit() and 0 < int(limit) < 2**62:
            return min(available, int(limit))
    return available


def feature_mem_budget():
    return max(FEATURE_MEM_MIN_BYTES, int(FEATURE_MEM_FRACTION * _available_memory()))


def slab_thickness_override():
    """Slab thickness forced through the environment, or 0 to size it from the budget."""
    return int(os.environ.get(SLAB_THICKNESS_ENV, "0") or 0)
