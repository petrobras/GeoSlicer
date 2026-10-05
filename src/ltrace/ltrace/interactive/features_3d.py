"""Precomputing a 3D session's feature volumes into its feature memmap, slab by slab.

The full apply on a separate inference volume does not use this; it fuses filtering into
the prediction loop instead (volume_3d.predict_full_3d).
"""

import os

import dask.array as da
import numpy as np

from ltrace.interactive.ipc import FEATURE_NAMES, FeatureIndex
from ltrace.interactive.resources import feature_mem_budget, max_worker_threads, slab_thickness_override


SLAB_WORKING_COPIES = 4  # live copies of a haloed slab a worker holds at its peak


def filter_into_plane(channel_array, calc_func, halo, out_plane):
    """Filter one 3D channel in haloed slabs along its longest axis, streaming the
    result into `out_plane` (a view of the feature memmap). Bit-for-bit identical to
    filtering the whole volume at once.
    """
    channel_array = np.asarray(channel_array)
    axis = int(np.argmax(channel_array.shape))
    n = channel_array.shape[axis]
    plane_bytes = (channel_array.size // n) * 4

    cores = max_worker_threads()
    budget = feature_mem_budget()
    override = slab_thickness_override()
    if override:
        thickness = max(halo + 1, override)
    else:
        by_parallelism = -(-n // cores)
        by_memory = budget // (cores * SLAB_WORKING_COPIES) // plane_bytes - 2 * halo
        thickness = max(halo + 1, min(by_parallelism, by_memory))

    if thickness >= n:
        # Whole volume fits in one slab (or the kernel is too large to slab):
        # filter it directly and skip the dask machinery.
        out_plane[...] = np.asarray(calc_func(channel_array), dtype=np.float32)
        return

    # Explicit slab sizes along `axis`, all >= halo+1 (map_overlap requires every
    # chunk to be at least the overlap depth): fold any short final remainder back
    # into the previous slab rather than leaving an undersized chunk.
    sizes = [thickness] * (n // thickness)
    rem = n - thickness * len(sizes)
    if rem:
        if rem >= halo + 1:
            sizes.append(rem)
        else:
            sizes[-1] += rem

    haloed_bytes = (max(sizes) + 2 * halo) * plane_bytes
    workers = max(1, min(cores, len(sizes), int(budget // (haloed_bytes * SLAB_WORKING_COPIES))))
    if haloed_bytes * SLAB_WORKING_COPIES > budget:
        print(
            f"[{os.getpid()}] Slab working set {haloed_bytes * SLAB_WORKING_COPIES / 2**30:.1f} GiB "
            f"exceeds the {budget / 2**30:.1f} GiB budget (halo {halo} forces it); filtering one slab at a time",
            flush=True,
        )

    chunks = tuple(tuple(sizes) if i == axis else channel_array.shape[i] for i in range(channel_array.ndim))
    depth = {i: (halo if i == axis else 0) for i in range(channel_array.ndim)}
    darr = da.from_array(channel_array, chunks=chunks)
    # boundary="none" leaves the outer faces unpadded so the filter's own edge handling
    # applies there, instead of tying the result to dask's padding mode.
    filtered = darr.map_overlap(
        lambda block: np.asarray(calc_func(block), dtype=np.float32),
        depth=depth,
        boundary="none",
        dtype=np.float32,
    )
    da.store(filtered, out_plane, scheduler="threads", num_workers=workers)


def allocate_feature_mmap(source_array, mmap_path):
    """Allocate the session feature memmap, (n_channels, n_features, K, J, I), with a
    plane for every feature so each one lands at the fixed index [:, feature.value]."""
    n_channels = source_array.shape[3] if source_array.ndim == 4 else 1
    spatial_shape = source_array.shape[:3]
    mmap_shape = (n_channels, len(FeatureIndex)) + spatial_shape
    features_mmap = np.memmap(mmap_path, dtype=np.float32, mode="w+", shape=mmap_shape)
    print(f"[{os.getpid()}] Created memory-mapped file at {mmap_path} with shape {mmap_shape}", flush=True)
    return features_mmap, n_channels


def compute_feature_planes(source_array, features_mmap, n_channels, feature_enums, scale, progress_callback=None):
    """Compute `feature_enums` into their fixed planes of `features_mmap`."""
    total = len(feature_enums) * n_channels
    done = 0
    for feature_enum in feature_enums:
        calc_func = scale.definitions[feature_enum]
        halo = scale.halo(feature_enum)
        for channel in range(n_channels):
            channel_array = source_array[..., channel] if source_array.ndim == 4 else source_array
            filter_into_plane(channel_array, calc_func, halo, features_mmap[channel, feature_enum.value])
            done += 1
            if progress_callback:
                progress_callback(int(100 * done / total), f"{FEATURE_NAMES[feature_enum]} done")
    features_mmap.flush()
