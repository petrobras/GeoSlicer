import numpy as np
from tensorflow import keras
from random import randint


class Generator3D(keras.utils.Sequence):
    """Picks a random 3D sample from X and generates a random subcube of
    subcubeSizeensions (subcubeSize x subcubeSize x subcubeSize).
    """

    def __init__(
        self,
        X,
        Y,
        batchSize=32,
        subcubeSize=32,
        nChannels=1,
        nOutputs=3,
        nSamplesPerCase=500,
    ):
        self.X = X
        self.Y = Y
        self.batchSize = batchSize
        self.subcubeSize = subcubeSize
        self.nChannels = nChannels
        self.nOutputs = nOutputs
        self.nSamplesPerCase = nSamplesPerCase

        self.on_epoch_end()

    def __len__(self):
        """Denotes the number of batches per epoch."""
        return int(self.X.shape[0] * self.nSamplesPerCase / self.batchSize)

    def __getitem__(self, index):
        """Generates one batch of data."""
        dims = (self.subcubeSize,) * 3
        x = np.empty((self.batchSize, *dims, self.nChannels))
        y = np.empty((self.batchSize, self.nOutputs))

        for i in range(self.batchSize):
            di = self.subcubeSize
            end = self.X.shape[1] - di - 1
            ii = randint(0, end)
            ij = randint(0, end)
            ik = randint(0, end)
            iCube = randint(0, self.X.shape[0] - 1)

            # Subcube
            x[i, :, :, :, 0] = self.X[iCube, ii : ii + di, ij : ij + di, ik : ik + di]

            # Plug properties
            y[i, :] = self.Y[iCube, :]
        return x, y
