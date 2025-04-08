import numpy as np
from numba import njit


@njit
def wqupc_find(p, parent_array):
    while p != parent_array[p]:
        parent_array[p] = parent_array[parent_array[p]]
        p = parent_array[p]
    return p


@njit
def wqupc_union(p, q, parent_array, size_array):
    root_p = wqupc_find(p, parent_array)
    root_q = wqupc_find(q, parent_array)

    if root_p != root_q:
        if size_array[root_p] < size_array[root_q]:
            parent_array[root_p] = root_q
            size_array[root_q] += size_array[root_p]
        else:
            parent_array[root_q] = root_p
            size_array[root_p] += size_array[root_q]


@njit
def compute_index(x, y, z, shape):
    return x + y * shape[0] + z * shape[0] * shape[1]


@njit
def normalize_watershed(array):
    shape = array.shape
    n = array.size

    parent_array = np.arange(n, dtype=np.uint32)
    size_array = np.ones(n, dtype=np.uint32)

    neighbor_offsets = [
        (1, 0, 0),
        (0, 1, 0),
        (0, 0, 1),
    ]

    # union forward
    for x in range(shape[0]):
        for y in range(shape[1]):
            for z in range(shape[2]):
                if array[x, y, z] == 0:
                    continue
                p = compute_index(x, y, z, shape)
                for dx, dy, dz in neighbor_offsets:
                    nx, ny, nz = x + dx, y + dy, z + dz
                    if (
                        0 <= nx < shape[0]
                        and 0 <= ny < shape[1]
                        and 0 <= nz < shape[2]
                        and array[nx, ny, nz] != 0
                        and array[x, y, z] == array[nx, ny, nz]
                    ):
                        q = compute_index(nx, ny, nz, shape)
                        wqupc_union(p, q, parent_array, size_array)

    # union backwards
    for x in range(shape[0] - 1, -1, -1):
        for y in range(shape[1] - 1, -1, -1):
            for z in range(shape[2] - 1, -1, -1):
                if array[x, y, z] == 0:
                    continue
                p = compute_index(x, y, z, shape)
                for dx, dy, dz in neighbor_offsets:
                    nx, ny, nz = x - dx, y - dy, z - dz
                    if (
                        0 <= nx < shape[0]
                        and 0 <= ny < shape[1]
                        and 0 <= nz < shape[2]
                        and array[nx, ny, nz] != 0
                        and array[x, y, z] == array[nx, ny, nz]
                    ):
                        q = compute_index(nx, ny, nz, shape)
                        wqupc_union(p, q, parent_array, size_array)

    # creating output
    output = np.zeros_like(array, dtype=np.uint32)
    labels = set()
    for x in range(shape[0]):
        for y in range(shape[1]):
            for z in range(shape[2]):
                if array[x, y, z] != 0:
                    p = compute_index(x, y, z, shape)
                    label = wqupc_find(p, parent_array) + 1
                    output[x, y, z] = label
                    labels.add(label)

    # remapping labels
    labels_list = sorted(labels)
    label_mapping = {label: i + 1 for i, label in enumerate(labels_list)}
    for x in range(shape[0]):
        for y in range(shape[1]):
            for z in range(shape[2]):
                if output[x, y, z] != 0:
                    output[x, y, z] = label_mapping[output[x, y, z]]

    return output
