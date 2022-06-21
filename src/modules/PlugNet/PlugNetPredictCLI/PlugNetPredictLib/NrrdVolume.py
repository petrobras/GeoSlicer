from cv2 import transform
import nrrd
import numpy as np


def _transform(vector3, transform4x4):
    homogenous = np.concatenate((vector3, [1]))
    transformed = np.matmul(homogenous, transform4x4)
    return transformed[:-1]


class NrrdVolume:
    def __init__(self, filename):
        self.data, header = nrrd.read(filename)

        self.origin = header["space origin"]

        dirMatrix = header["space directions"]
        self.ijkToRasMatrix = np.concatenate((dirMatrix, self.origin[np.newaxis, :]))
        self.ijkToRasMatrix = np.concatenate((self.ijkToRasMatrix, np.array([[0.0, 0.0, 0.0, 1.0]]).T), axis=1)
        self.rasToIjkMatrix = np.linalg.inv(self.ijkToRasMatrix)

        zOrigin = self.origin[2]
        zTop = self.ijkToRas(np.array(self.data.shape) - 1)[2]

        self.top = max(zOrigin, zTop)
        self.height = abs(abs(zOrigin) - abs(zTop))

    def ijkToRas(self, ijk):
        return _transform(ijk, self.ijkToRasMatrix)

    def rasToIjk(self, ras):
        return _transform(ras, self.rasToIjkMatrix)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def extractCubeAtDepth(self, depth, size):
        i = int(self.data.shape[0] / 2)
        j = int(self.data.shape[1] / 2)
        k = int(round(self.rasToIjk([0, 0, depth])[2]))

        half = int(size / 2)
        if k + half >= self.data.shape[2]:
            return None
        if k - half < 0:
            return None
        return self.data[i - half : i + half, j - half : j + half, k - half : k + half]
