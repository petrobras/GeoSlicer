import unittest
from .NeighbourPixelCount import NeighbourPixelCount
import numpy as np
import pandas as pd

"""
Test Array:

1 2 3
2 3 5
4 1 2
1 5 5
"""
testData = np.asarray([[1, 2, 3], [2, 3, 5], [4, 1, 2], [1, 5, 5]])
testDataResultWithSelfInteration = {
    1: {1: 1, 2: 4, 3: 2, 4: 2, 5: 4},
    2: {1: 4, 2: 1, 3: 4, 4: 1, 5: 4},
    3: {1: 2, 2: 4, 3: 1, 4: 1, 5: 2},
    4: {1: 2, 2: 1, 3: 1, 4: 0, 5: 1},
    5: {
        1: 4,
        2: 4,
        3: 2,
        4: 1,
        5: 1,
    },
}

testDataResultWithoutSelfInteration = {
    1: {1: 0, 2: 4, 3: 2, 4: 2, 5: 4},
    2: {1: 4, 2: 0, 3: 4, 4: 1, 5: 4},
    3: {1: 2, 2: 4, 3: 0, 4: 1, 5: 2},
    4: {1: 2, 2: 1, 3: 1, 4: 0, 5: 1},
    5: {
        1: 4,
        2: 4,
        3: 2,
        4: 1,
        5: 0,
    },
}


class TestNeighbourPixelCount(unittest.TestCase):
    def test_DataWithoutSelfInteration(self):
        resultDataWithoutSelfInteration = NeighbourPixelCount(matrix=testData).result()
        self.assertTrue(
            assertResult(
                currentResult=resultDataWithoutSelfInteration, expectedResult=testDataResultWithoutSelfInteration
            )
        )

    def test_DataWithSelfInteration(self):
        resultDataWithSelfInteration = NeighbourPixelCount(matrix=testData, allowSelfCount=True).result()
        self.assertTrue(
            assertResult(currentResult=resultDataWithSelfInteration, expectedResult=testDataResultWithSelfInteration)
        )

    def test_DataWithoutSelfInterationAsDataFrame(self):
        df = NeighbourPixelCount(matrix=testData).toDataFrame()
        expectedDataFrame = pd.DataFrame.from_dict(testDataResultWithoutSelfInteration)
        self.assertTrue(df.equals(expectedDataFrame))

    def test_DataWithoutSelfInterationAsPercentDataFrame(self):
        df = NeighbourPixelCount(matrix=testData).toDataFrame(asPercent=True)

        expectedDataFrame = pd.DataFrame.from_dict(testDataResultWithoutSelfInteration, dtype=int)
        expectedDataFrame = expectedDataFrame * 100 / expectedDataFrame.sum(axis=0).values

        self.assertTrue(df.equals(expectedDataFrame))

    def test_DataWithoutSelfInterationAsPercentDataFrameWithLabels(self):
        labels = {
            0: "Zero",
            1: "One",
            2: "Two",
            3: "Three",
            4: "Four",
            5: "Five",
            6: "Six",
        }

        df = NeighbourPixelCount(matrix=testData).toDataFrame(pixelLabels=labels)
        labelsList = ["One", "Two", "Three", "Four", "Five"]
        self.assertTrue(list(df.index) == labelsList)
        self.assertTrue(list(df.columns) == labelsList)

    def test_DataWithoutSelfInterationAsPercentDataFrameWithNonExistentLabels(self):
        labels = {6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten"}

        df = NeighbourPixelCount(matrix=testData).toDataFrame(pixelLabels=labels)
        labelsList = [1, 2, 3, 4, 5]
        self.assertTrue(list(df.index) == labelsList)
        self.assertTrue(list(df.columns) == labelsList)

    def test_DataWithoutSelfInterationAsPercentDataFrameWithBlackListLabels(self):
        labelsList = [1, 2, 3, 4, 5]
        labelsBlackList = [3, 4]

        labelListResult = [label for label in labelsList if not label in labelsBlackList]

        df = NeighbourPixelCount(matrix=testData).toDataFrame(labelBlackList=labelsBlackList)
        self.assertTrue(list(df.index) == labelListResult)
        self.assertTrue(list(df.columns) == labelListResult)

    def test_DataWithoutSelfInterationAsPercentDataFrameWithNonExistentBlackListLabels(self):
        labelsList = [1, 2, 3, 4, 5]
        labelsBlackList = [3, 4, 8, 9]

        labelListResult = [label for label in labelsList if not label in labelsBlackList]

        df = NeighbourPixelCount(matrix=testData).toDataFrame(labelBlackList=labelsBlackList)
        self.assertTrue(list(df.index) == labelListResult)
        self.assertTrue(list(df.columns) == labelListResult)


def assertResult(currentResult, expectedResult, allowPrint=False):
    for key, val in currentResult.items():
        values = val.keys()
        if allowPrint:
            print("Count for key: {}".format(key))
        for value in values:
            currentValue = currentResult[key][value]
            expectedValue = 0
            try:
                expectedValue = expectedResult[key][value]
            except:
                if allowPrint:
                    print("TestData doesn have values for this input: key {} value {}".format(key, value))
                return False

            if allowPrint:
                print("\t{} counts: \t Current: {} - Expected: {}".format(value, currentValue, expectedValue))

            if currentValue != expectedValue:
                if allowPrint:
                    print("ERROR! Current value is different from the expected!")
                return False

    return True


if __name__ == "__main__":
    unittest.main()
