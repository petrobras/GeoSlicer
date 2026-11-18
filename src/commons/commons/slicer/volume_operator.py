import itertools
import numpy as np
import slicer
import vtk


class SegmentOperator:
    """Callable that can be serialized and passed to other processes.

    When centroidMatrix is given, the segment's centroid is appended to the operator's result. It is the mean of
    all the segment's voxels, mapped by centroidMatrix (see VolumeOperator.ijkToZyxOperator).
    """

    def __init__(self, operator, matrix, centroidMatrix=None):
        self.operator = operator
        self.matrix = matrix
        self.centroidMatrix = centroidMatrix

    def __call__(self, label, points):
        fit = (np.dot(self.matrix, np.c_[points, np.ones(len(points))].T).T)[:, :-1]
        stats = self.operator(label, fit)
        if stats is None or self.centroidMatrix is None:
            return stats

        # Uses the points as given: the operator may discard some of them (e.g. LabelStatistics2D)
        centroid = np.dot(self.centroidMatrix, np.append(np.mean(points, axis=0), 1))
        return (*stats, *centroid)


class VolumeOperator:
    def __init__(self, volumeNode, dtype=np.uint8):
        self._array = slicer.util.arrayFromVolume(volumeNode).astype(dtype)

        IJKToRASMatrix = vtk.vtkMatrix4x4()
        volumeNode.GetIJKToRASMatrix(IJKToRASMatrix)

        self._ijkToRasMatrix = IJKToRASMatrix

        transformationMatrixArray = np.zeros(16)
        IJKToRASMatrix.DeepCopy(transformationMatrixArray, IJKToRASMatrix)

        if self._array.shape[0] == 1:
            validAxis = (0, 1, 3)
        elif self._array.shape[1] == 1:
            validAxis = (0, 2, 3)
        elif self._array.shape[2] == 1:
            validAxis = (1, 2, 3)  # [(1, 1), (1, 2), (2, 1), (2, 2), (1, 3), (2, 3)]
        else:
            validAxis = (0, 1, 2, 3)

        pairs = [pair for pair in itertools.product(validAxis, validAxis)]

        ndim = int(np.sqrt(len(pairs)))
        T = transformationMatrixArray.reshape((-1, 4))
        A = np.array([T[p] for p in pairs]).reshape((ndim, ndim))
        d = len(validAxis) - 1
        C = np.empty((len(validAxis), len(validAxis)))
        C[0:d, 0:d] = np.flipud(np.fliplr(A[0:d, 0:d]))
        C[0:d, d] = np.flipud(A[0:d, d])
        self.ijkToRasOperator = C

        # Maps array index points (squeezed, as in ijkToRasOperator) plus a trailing 1 to full world (S, A, R)
        # coordinates, the (z, y, x) order of the report. Unlike ijkToRasOperator, it keeps the position along the
        # squeezed axis, so 2D images get their slice position too.
        keptAxes = [axis for axis in range(3) if self._array.shape[axis] != 1]
        ijkToSar = T[[2, 1, 0]][:, [2, 1, 0, 3]]  # rows S, A, R; columns K, J, I, translation
        self.ijkToZyxOperator = ijkToSar[:, keptAxes + [3]]

    def fit(self, points):
        return np.dot(self.ijkToRasOperator, np.array(points).T).T
