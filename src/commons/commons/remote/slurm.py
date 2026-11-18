import math

import numpy as np

MAX_WORKERS = 39


def calculate_slurm_parameters(
    volume_shape: tuple, itemsize: int, divs: int, cpus_per_node: int = 40, max_memory_per_node_gb: int = 350
) -> dict:
    """
    Estimates the required SLURM resources based on volume dimensions and hardware constraints.

    :param volume_shape: Tuple representing the shape of the volume array (Z, Y, X).
    :param itemsize: Number of bytes per item/voxel (e.g., array.itemsize).
    :param divs: Number of divisions.
    :param cpus_per_node: Total number of CPUs available per node.
    :param max_memory_per_node_gb: Maximum memory available per node in GB.
    :return: Dictionary containing calculated slurm jobs, cores, memory, and chunk size.
    """
    JOBS_PER_NODE = 2
    BORDER_CHUNK_FRACTION = 0.25  # Fraction of the chunk shape that is estimated to be added as border
    BASE_MEMORY_USAGE_FACTOR = 400
    MEMORY_PER_CPU_USAGE_FACTOR = 20

    number_of_chunks = divs**3

    # Estimate required resources
    chunk_shape = np.ceil(np.array(volume_shape) / divs)
    chunk_shape += chunk_shape * BORDER_CHUNK_FRACTION  # Add estimation of overlap border
    bytes_per_chunk = itemsize * (chunk_shape[0] * chunk_shape[1] * chunk_shape[2])

    slurm_jobs = None
    slurm_cores = None
    slurm_memory_gb = max_memory_per_node_gb + 1
    i = 0

    while slurm_memory_gb > max_memory_per_node_gb:
        slurm_jobs = JOBS_PER_NODE * math.ceil(number_of_chunks / cpus_per_node) + i
        slurm_cores = math.ceil(number_of_chunks / slurm_jobs)

        slurm_memory_bytes = (bytes_per_chunk * BASE_MEMORY_USAGE_FACTOR) + slurm_cores * (
            bytes_per_chunk * MEMORY_PER_CPU_USAGE_FACTOR
        )
        slurm_memory_gb = math.ceil(slurm_memory_bytes / 10**9)  # Convert bytes to GB
        i += 1

        if slurm_cores == 1 or i >= 20:
            break

    return {
        "bytes_per_chunk": bytes_per_chunk,
        "slurm_jobs": slurm_jobs,
        "slurm_cores": slurm_cores,
        "slurm_memory_gb": slurm_memory_gb,
    }
