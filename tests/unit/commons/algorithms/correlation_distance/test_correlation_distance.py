import pytest

import numpy as np

from commons.algorithms.CorrelationDistance import common

subvolume_size_test_data = [
    (
        "cube",
        [2, 2, 2],
        2,
        [
            (slice(0, 4), slice(0, 4), slice(0, 4)),
            (slice(0, 4), slice(0, 4), slice(4, 10)),
            (slice(0, 4), slice(4, 10), slice(0, 4)),
            (slice(0, 4), slice(4, 10), slice(4, 10)),
            (slice(4, 10), slice(0, 4), slice(0, 4)),
            (slice(4, 10), slice(0, 4), slice(4, 10)),
            (slice(4, 10), slice(4, 10), slice(0, 4)),
            (slice(4, 10), slice(4, 10), slice(4, 10)),
        ],
    ),
    (
        "cube",
        [3, 3, 3],
        2,
        [
            (slice(0, 3), slice(0, 3), slice(0, 3)),
            (slice(0, 3), slice(0, 3), slice(3, 10)),
            (slice(0, 3), slice(3, 10), slice(0, 3)),
            (slice(0, 3), slice(3, 10), slice(3, 10)),
            (slice(3, 10), slice(0, 3), slice(0, 3)),
            (slice(3, 10), slice(0, 3), slice(3, 10)),
            (slice(3, 10), slice(3, 10), slice(0, 3)),
            (slice(3, 10), slice(3, 10), slice(3, 10)),
        ],
    ),
    (
        "cube",
        [5, 5, 5],
        2,
        [
            (slice(0, 5), slice(0, 5), slice(0, 5)),
            (slice(0, 5), slice(0, 5), slice(5, 10)),
            (slice(0, 5), slice(5, 10), slice(0, 5)),
            (slice(0, 5), slice(5, 10), slice(5, 10)),
            (slice(5, 10), slice(0, 5), slice(0, 5)),
            (slice(5, 10), slice(0, 5), slice(5, 10)),
            (slice(5, 10), slice(5, 10), slice(0, 5)),
            (slice(5, 10), slice(5, 10), slice(5, 10)),
        ],
    ),
    (
        "plane",
        [5, 5],
        2,
        [
            (slice(0, 5, None), slice(0, 5, None)),
            (slice(0, 5, None), slice(5, 10, None)),
            (slice(5, 10, None), slice(0, 5, None)),
            (slice(5, 10, None), slice(5, 10, None)),
        ],
    ),
]


@pytest.mark.parametrize("input_shape,unit,divisor,expected", subvolume_size_test_data)
class TestSubvolumeSlicing:
    def setup_method(self):
        # Create dummy cube
        size = 10
        self.plane = np.zeros((size, size))
        self.cube = np.zeros((size, size, size))
        value = 0
        for i in range(size):
            for j in range(size):
                self.plane[i, j] = value
                for k in range(size):
                    self.cube[i, j, k] = value
                    value += 1

    def test_subvolume_size(self, input_shape, unit, divisor, expected):
        if input_shape == "cube":
            data = self.cube
        elif input_shape == "plane":
            data = self.plane
        assert common.get_subvolumes_dimensions(data, unit, divisor) == expected


def test_slice_padding():
    slices = (slice(0, 4), slice(0, 4), slice(4, 10))
    expected_slices = (slice(0, 10), slice(0, 12), slice(4, 20))
    result_slices = common.add_padding_to_slices(slices, [3, 4, 5])
    assert result_slices == expected_slices


kernel_slicing_test_data = [
    (
        [5, 5, 5],
        [3, 3, 3],
        [
            (((0, 5), (0, 5), (0, 5)), (0, 0, 0)),
            (((0, 5), (0, 5), (3, 8)), (0, 0, 1)),
            (((0, 5), (0, 5), (6, 11)), (0, 0, 2)),
            (((0, 5), (3, 8), (0, 5)), (0, 1, 0)),
            (((0, 5), (3, 8), (3, 8)), (0, 1, 1)),
            (((0, 5), (3, 8), (6, 11)), (0, 1, 2)),
            (((0, 5), (6, 11), (0, 5)), (0, 2, 0)),
            (((0, 5), (6, 11), (3, 8)), (0, 2, 1)),
            (((0, 5), (6, 11), (6, 11)), (0, 2, 2)),
            (((3, 8), (0, 5), (0, 5)), (1, 0, 0)),
            (((3, 8), (0, 5), (3, 8)), (1, 0, 1)),
            (((3, 8), (0, 5), (6, 11)), (1, 0, 2)),
            (((3, 8), (3, 8), (0, 5)), (1, 1, 0)),
            (((3, 8), (3, 8), (3, 8)), (1, 1, 1)),
            (((3, 8), (3, 8), (6, 11)), (1, 1, 2)),
            (((3, 8), (6, 11), (0, 5)), (1, 2, 0)),
            (((3, 8), (6, 11), (3, 8)), (1, 2, 1)),
            (((3, 8), (6, 11), (6, 11)), (1, 2, 2)),
            (((6, 11), (0, 5), (0, 5)), (2, 0, 0)),
            (((6, 11), (0, 5), (3, 8)), (2, 0, 1)),
            (((6, 11), (0, 5), (6, 11)), (2, 0, 2)),
            (((6, 11), (3, 8), (0, 5)), (2, 1, 0)),
            (((6, 11), (3, 8), (3, 8)), (2, 1, 1)),
            (((6, 11), (3, 8), (6, 11)), (2, 1, 2)),
            (((6, 11), (6, 11), (0, 5)), (2, 2, 0)),
            (((6, 11), (6, 11), (3, 8)), (2, 2, 1)),
            (((6, 11), (6, 11), (6, 11)), (2, 2, 2)),
        ],
    ),
]


@pytest.mark.parametrize("kernel,unit,expected", kernel_slicing_test_data)
def test_kernel_slicing(kernel, unit, expected):
    result = []
    output_shape = np.array([10, 10, 10]) // np.array(unit)
    for input_indexes, output_indexes, progress in common.calculate_process_indexes(
        1, np.array(kernel), np.array(unit), tuple(output_shape)
    ):
        result.append((tuple(input_indexes), tuple(output_indexes)))
    assert result == expected


coordinate_iterator_test_data = [
    (
        [2, 2],
        [
            [0, 0],
            [0, 1],
            [1, 0],
            [1, 1],
        ],
    ),
    (
        [3, 4],
        [[0, 0], [0, 1], [0, 2], [0, 3], [1, 0], [1, 1], [1, 2], [1, 3], [2, 0], [2, 1], [2, 2], [2, 3]],
    ),
]


@pytest.mark.parametrize("shape,expected", coordinate_iterator_test_data)
def test_coordinate_iterator(shape, expected):
    result = []
    for coordinate in common.coordinate_iterator(np.array(shape)):
        result.append(list(coordinate))
    assert result == expected
