import os
import numpy as np
from tensorflow import keras
from .NrrdVolume import NrrdVolume


class GeneratorNrrd(keras.utils.Sequence):
    def __init__(self, folderPath, size=32):
        self.cubeSize = size
        self.files = []

        for root, dirs, files in os.walk(folderPath):
            self.files += [os.path.join(root, file) for file in files if file.endswith(".nrrd")]

    def __len__(self):
        return len(self.files)

    def __getitem__(self, index):
        cubes = []
        depths = []

        volume = NrrdVolume(self.files[index])
        height = volume.height

        for relativeDepth in np.arange(40, height - 40, 10):
            absoluteDepth = volume.top - relativeDepth
            subcube = volume.extractCubeAtDepth(absoluteDepth, self.cubeSize)

            if subcube is None or (subcube < -0.8).sum() > 1000:
                print(f"Found hole in core {index} at depth {absoluteDepth}.")
                continue

            depths.append(absoluteDepth)
            cubes.append(np.expand_dims(subcube, 3))

        return depths, np.array(cubes)
