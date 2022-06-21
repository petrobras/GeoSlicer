from collections import defaultdict

import numpy as np

from numpy.random import RandomState

from typing import List

VALUE_1D = (1, 1, 1, 1)


def fixed_segment_sample_generator(segmentVolumeArray: np.ndarray, size: int, labels: List[int] = None, seed=12345):
    labelValueArray = np.array(labels)
    rng = RandomState(seed)

    # allocate
    sampled_indexes = np.empty(size, dtype=np.int32)
    nonZeroPoints = np.argwhere(segmentVolumeArray != 0)

    pointSets = defaultdict(list)
    for index in nonZeroPoints:
        pointSets[segmentVolumeArray[tuple(index)]].append(index)

    for labelValue in pointSets:
        points = np.array(pointSets[labelValue])
        repeats = max(size - len(points), 0)

        sorted_indexes = np.arange(len(points), dtype=np.int32)
        # sample till it fills
        if repeats > 0:
            sampled_indexes[:repeats] = rng.choice(sorted_indexes, repeats, replace=True)
        sampled_indexes[repeats:] = rng.choice(sorted_indexes, size - repeats, replace=False)

        yield from points[sampled_indexes]


def segment_walking_generator(roiVolumeArray: np.ndarray):
    points = np.argwhere(roiVolumeArray == 1)
    yield from points


class InputData:
    @staticmethod
    def _take(centroid, bounds_shape, crop_shape, step=1):
        s_im = []
        pads = np.zeros((len(crop_shape), 2), dtype=np.int32)
        for dim in range(len(crop_shape)):
            r = crop_shape[dim] // 2
            lower_im = centroid[dim] - r
            if lower_im < 0:
                pads[dim][0] = int(abs(lower_im))
                lower_im = 0

            dimv = bounds_shape[dim]
            upper_im = centroid[dim] + r + 1
            if upper_im > dimv:
                pads[dim][1] = int(upper_im - dimv)
                upper_im = dimv

            s_im.append(slice(int(lower_im), int(upper_im), step))

        return tuple(s_im), pads
        # return np.pad(self.data[tuple(s_im)], pad_width=pads, mode='reflect')

    @staticmethod
    def training(X, y, shapeX, shapeY, labels, label_sample_size, step=1):

        total = label_sample_size * len(labels)
        sampler = fixed_segment_sample_generator(y, size=label_sample_size, labels=labels)

        if X.shape[0] > y.shape[0]:
            resx = np.empty((total, shapeX[0]), dtype=X.dtype)
            resy = np.empty(total, dtype=y.dtype)

            for i, index in zip(range(total), sampler):
                resx[i, ...] = X[:, index[1], index[2]]
                resy[i] = y[tuple(index)]
        else:
            resx = np.empty((total, *shapeX), dtype=X.dtype)
            resy = np.empty(total, dtype=y.dtype)

            for i, index in zip(range(total), sampler):
                xslice_i, xpads = InputData._take(index, bounds_shape=X.shape, crop_shape=shapeX, step=step)
                resx[i, ...] = np.pad(X[xslice_i], pad_width=xpads, mode="reflect")
                yslice_i, ypads = InputData._take(
                    index, bounds_shape=y.shape, crop_shape=shapeY, step=1
                )  # TODO should this be always 1?
                resy[i] = np.pad(y[yslice_i], pad_width=ypads, mode="reflect")

        return resx, resy


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test this file.")

    parser.add_argument(
        "--test-stdg", const=True, default=False, nargs="?", help="Run test for SupervisedTrainingDataGenerator"
    )

    parser.add_argument("--test-sss", const=True, default=False, nargs="?", help="Run test for SizeableSegmentSampler")

    parser.add_argument("--timeit", const=True, default=False, nargs="?", help="Run test with timeit")

    args = parser.parse_args()

    def run_stdg():
        X = np.random.randint(0, 100, (300, 300, 300))
        Y = np.random.randint(0, 5, (300, 300, 300))

        gen = InputData.training(X, Y, shapeX=(5, 5, 5), shapeY=(3, 3, 3), label_sample_size=10)

        for x, y in gen:
            print(x, y)

    def run_sss():
        X = np.random.randint(0, 100, (300, 300, 300))
        sampling = fixed_segment_sample_generator(X, size=1000, labels=None)
        x = []
        for sample in sampling:
            i, j, k = sample
            x.append(X[i, j, k])

    test = lambda: print("Not implemented")

    if args.test_stdg:
        test = run_stdg

    if args.test_sss:
        test = run_sss

    if args.timeit:
        import timeit

        print(timeit.timeit("test()", setup="from __main__ import test", number=1))
    else:
        test()
