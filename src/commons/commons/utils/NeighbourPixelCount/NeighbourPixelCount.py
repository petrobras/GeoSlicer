from numba import jit, types, prange
from numba.typed import List, Dict
import numpy as np
import pandas as pd


class NeighbourPixelCount:
    """Class to count surround pixels values in a matrix. Current supporting 2D matrix only."""

    def __init__(self, matrix: np.ndarray, allowSelfCount=False):
        self.__result = self.count(matrix, allowSelfCount)

    @staticmethod
    @jit(nopython=True)
    def __countNeighboursProcess(matrixData, totalCountDict):
        rows, columns = matrixData.shape
        for i in prange(rows):
            for j in prange(columns):
                centerValue = matrixData[i, j].item()
                values = List()
                for row in prange(i - 1, i + 2, 1):
                    for column in prange(j - 1, j + 2, 1):
                        if column < 0 or column >= columns or row < 0 or row >= rows:
                            continue

                        if row == i and column == j:
                            continue

                        values.append(matrixData[row, column].item())

                for value in values:
                    totalCountDict[centerValue][value] += 1

    def __count2DMatrix(self, matrix: np.ndarray, allowSelfCount=False):
        uniquesMatrixDataValues = np.unique(matrix)

        inner_dict_type = types.DictType(types.int64, types.int64)
        totalCountDict = Dict.empty(key_type=types.int64, value_type=inner_dict_type)

        # Initialize numba.Dict with zeros
        uniquesMatrixDataValuesList = list(uniquesMatrixDataValues)
        for i in range(len(uniquesMatrixDataValuesList)):
            initialCountForValuesDict = Dict.empty(key_type=types.int64, value_type=types.int64)
            for j in range(len(uniquesMatrixDataValuesList)):
                initialCountForValuesDict[uniquesMatrixDataValuesList[j]] = 0

            totalCountDict[uniquesMatrixDataValuesList[i]] = initialCountForValuesDict

        # Do the count
        self.__countNeighboursProcess(matrix, totalCountDict)

        # Adjust self-counting iteraction
        for key in totalCountDict:
            value = totalCountDict[key].get(key, None)
            if value is None:
                totalCountDict[key][key] = 0
            else:
                selfCountingValue = value / 2 if allowSelfCount is True else 0
                totalCountDict[key][key] = int(selfCountingValue)

        return totalCountDict

    def count(self, matrix: np.ndarray, allowSelfCount=False):
        if matrix.ndim == 2:
            return self.__count2DMatrix(matrix, allowSelfCount)
        else:
            raise (RuntimeError("Not implemented."))

    def result(self):
        return self.__result

    def toDataFrame(self, pixelLabels=None, asPercent=False, allowNaN=False, labelBlackList=None):
        dataLabels = set(self.__result.keys())
        if labelBlackList:
            for elem in labelBlackList:
                try:
                    dataLabels.remove(elem)
                except KeyError:
                    pass  # already out

        if pixelLabels is None:
            pixelLabels = {label: label for label in dataLabels}

        result = {key: self.__result[key] for key in dataLabels}

        indexes = sorted(list(result.keys()))
        df = pd.DataFrame.from_dict(result, orient="index").reindex(columns=indexes, index=indexes)
        df = df.rename(columns=pixelLabels, index=pixelLabels)

        if not allowNaN:
            df = df.fillna(0)

        if asPercent:
            sums = df.sum(axis=0)
            df = df * 100 / sums.values

        return df
