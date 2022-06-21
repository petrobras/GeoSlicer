from collections import defaultdict


def find_objects(data_array):
    if data_array.ndim == 2:
        return find_objects_2d(data_array)
    elif data_array.ndim == 3:
        return find_objects_3d(data_array)


def find_objects_2d(data_array):
    founds: defaultdict = defaultdict(list)
    data_view: cython.int[:, :] = data_array

    row: cython.int
    for row in range(data_array.shape[0]):
        newpts: defaultdict = defaultdict(list)
        col: cython.int
        for col in range(data_array.shape[1]):
            point: tuple = (row, col)
            label: cython.int = data_view[point]

            if label != 0:
                newpts[label].append(point)

        closed: dict = {k: v for k, v in founds.items() if k not in newpts}
        if len(closed):
            yield row, closed

        founds = defaultdict(list, {k: [*founds[k], *v] for k, v in newpts.items()})

    row: cython.int = data_array.shape[0] - 1
    yield row, founds


def find_objects_3d(data_array):
    founds: defaultdict = defaultdict(list)
    data_view: cython.int[:, :, :] = data_array

    row: cython.int
    for row in range(data_array.shape[0]):
        newpts: defaultdict = defaultdict(list)
        j: cython.int
        for j in range(data_array.shape[1]):
            k: cython.int
            for k in range(data_array.shape[2]):
                point: tuple = (row, j, k)
                label: cython.int = data_view[point]

                if label != 0:
                    newpts[label].append(point)

        closed: dict = {k: v for k, v in founds.items() if k not in newpts}
        if len(closed):
            yield row, closed

        founds = defaultdict(list, {k: [*founds[k], *v] for k, v in newpts.items()})

    row: cython.int = data_array.shape[0] - 1
    yield row, founds
