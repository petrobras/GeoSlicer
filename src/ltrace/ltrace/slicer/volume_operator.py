import itertools
import numpy as np
import slicer
import vtk


class SegmentOperator:
    """Callable that can be serialized and passed to other processes."""

    def __init__(self, operator, matrix):
        self.operator = operator
        self.matrix = matrix

    def __call__(self, label, points):
        fit = (np.dot(self.matrix, np.c_[points, np.ones(len(points))].T).T)[:, :-1]
        return self.operator(label, fit)


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

    def fit(self, points):
        return np.dot(self.ijkToRasOperator, np.array(points).T).T
