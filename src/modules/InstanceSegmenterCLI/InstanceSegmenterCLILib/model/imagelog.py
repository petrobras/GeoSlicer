from collections import namedtuple

import cv2
import numpy as np
import pandas as pd
import vtk
from scipy.ndimage import binary_fill_holes
from skimage.segmentation import expand_labels

import ltrace.algorithms.supervised.mrcnn.model as modellib
from ltrace.algorithms.measurements import instances_depths, sidewall_sample_instance_properties
from ltrace.algorithms.supervised.mrcnn.config import Config
from ltrace.slicer.cli_utils import progressUpdate
from .model import Model, processImageArray, combineImageArrays, updateLabelMapArray

ImageLogSidewallSampleModelParameters = namedtuple(
    "ImageLogSidewallSampleModelParameters",
    [
        "model",
        "ampImageNode",
        "ttImageNode",
        "minimumScore",
        "maximumDetections",
        "gpuEnabled",
    ],
)

EXTRA_COLUMNS = 30


class PetrobrasSidewallSampleConfig1(Config):
    NAME = "sample"
    GPU_COUNT = 1
    IMAGES_PER_GPU = 1
    NUM_CLASSES = 1 + 1
    RPN_ANCHOR_SCALES = (26, 28, 30, 32, 34)  # anchor side in pixels
    BACKBONE = "resnet50"
    MEAN_PIXEL = [173.58488657, 109.89597048, 0]
    DETECTION_NMS_THRESHOLD = 0.0  # no overlapping
    RPN_ANCHOR_RATIOS = [0.9, 1, 1.1]

    MAX_GT_INSTANCES = 100
    IMAGE_MIN_DIM = 256
    IMAGE_MAX_DIM = 1024
    DETECTION_MIN_CONFIDENCE = 0.96


class PetrobrasSidewallSampleConfig2(Config):
    NAME = "sample"
    GPU_COUNT = 1
    IMAGES_PER_GPU = 1
    NUM_CLASSES = 1 + 1
    RPN_ANCHOR_SCALES = (26, 28, 30, 32, 34)  # anchor side in pixels
    BACKBONE = "resnet50"
    MEAN_PIXEL = [173.58488657, 109.89597048, 0]
    DETECTION_NMS_THRESHOLD = 0.0  # no overlapping
    RPN_ANCHOR_RATIOS = [0.9, 1, 1.1]

    MAX_GT_INSTANCES = 100
    IMAGE_MIN_DIM = 256
    IMAGE_MAX_DIM = 1024
    DETECTION_MIN_CONFIDENCE = 0.96


class SyntheticSidewallSampleConfig(Config):
    NAME = "sample"
    GPU_COUNT = 1
    IMAGES_PER_GPU = 1
    NUM_CLASSES = 1 + 1
    RPN_ANCHOR_SCALES = (26, 28, 30, 32, 34)  # anchor side in pixels
    BACKBONE = "resnet50"
    MEAN_PIXEL = [173.58488657, 109.89597048, 0]
    DETECTION_NMS_THRESHOLD = 0.0  # no overlapping
    RPN_ANCHOR_RATIOS = [0.9, 1, 1.1]

    MAX_GT_INSTANCES = 100
    IMAGE_MIN_DIM = 256
    IMAGE_MAX_DIM = 1024
    DETECTION_MIN_CONFIDENCE = 0.96


class ImageLogSidewallSampleModel(Model):
    def __init__(self):
        super().__init__()

    def segment(self, p):
        import tensorflow as tf

        if p.model == "side_1":
            self.inferenceConfig = PetrobrasSidewallSampleConfig1()
        elif p.model == "side_2":
            self.inferenceConfig = PetrobrasSidewallSampleConfig2()
        elif p.model == "synth_side":
            self.inferenceConfig = SyntheticSidewallSampleConfig()
        else:
            raise RuntimeError(f"Model {p.model} isn't implemented.")

        # Hide GPU from visible devices
        if not p.gpuEnabled:
            tf.config.set_visible_devices([], "GPU")

        ampImageArray = processImageArray(
            p.ampImageNode, self.inferenceConfig.IMAGE_MIN_DIM, cloneColumns=EXTRA_COLUMNS
        )
        ttImageArray = processImageArray(p.ttImageNode, self.inferenceConfig.IMAGE_MIN_DIM, cloneColumns=EXTRA_COLUMNS)
        combinedImageArray, ampImageArray, ttImageArray, _ = combineImageArrays(ampImageArray, ttImageArray, None)

        # For debugging purposes, please don't delete
        # cv2.imwrite("D:/redImageArray.tif", ampImageArray)
        # cv2.imwrite("D:/greenImageArray.tif", ttImageArray)
        # cv2.imwrite("D:/combinedImageArray.tif", cv2.cvtColor(combinedImageArray, cv2.COLOR_RGB2BGR))

        inferenceModel = modellib.MaskRCNN(mode="inference", config=self.inferenceConfig, model_dir="")
        tf.keras.Model.load_weights(inferenceModel.keras_model, str(self.getModelPath(p.model)), by_name=True)

        shape = combinedImageArray.shape
        labelMapArray = np.full((shape[0], 1, shape[1]), 0)

        propertiesList = []
        labelValue = 1
        end = min(shape[0], self.inferenceConfig.IMAGE_MAX_DIM)
        progress = 0.1
        progressIncrement = 0.9 / (len(combinedImageArray) // self.inferenceConfig.IMAGE_MAX_DIM)
        while end < len(combinedImageArray):
            start = end - self.inferenceConfig.IMAGE_MAX_DIM
            imageSection = combinedImageArray[start:end]
            ampImageSection = ampImageArray[start:end]
            result = inferenceModel.detect([imageSection], verbose=0)[0]

            # reversed because we want the highest score mask to take over the others
            for i in reversed(range(len(result["scores"]))):
                mask = np.rollaxis(result["masks"], 2)[i]
                mask = self.improveSidewallSampleMask(ampImageSection, mask, i)
                if 1 not in mask:
                    continue
                markMaskIndexes = np.where(mask == True)
                # if there isn't a label in the same location, proceed to add a label
                if not np.any(labelMapArray[start:end, 0, :][markMaskIndexes]):
                    properties = sidewall_sample_instance_properties(mask, p.ampImageNode.GetSpacing())

                    # Correcting azimuth for no extra columns
                    maskNoExtraColumns = mask[:, EXTRA_COLUMNS : self.inferenceConfig.IMAGE_MIN_DIM + EXTRA_COLUMNS]
                    propertiesNoExtraColumns = sidewall_sample_instance_properties(
                        maskNoExtraColumns, p.ampImageNode.GetSpacing()
                    )
                    properties["azimuth (°)"] = propertiesNoExtraColumns["azimuth (°)"]

                    if self.isValidSidewallSampleMark(properties):
                        properties["label"] = labelValue
                        propertiesList.append(properties)
                        labelMapArray[start:end, 0, :][markMaskIndexes] = labelValue
                        labelValue += 1

            end += self.inferenceConfig.IMAGE_MAX_DIM
            remainder = len(combinedImageArray) - end
            if remainder < self.inferenceConfig.IMAGE_MAX_DIM:
                end += remainder

            progress += progressIncrement
            progressUpdate(value=progress)

        # removing extra detections by lower score
        if p.maximumDetections < len(propertiesList):
            propertiesList = sorted(propertiesList, key=lambda x: x[1])[::-1]
            extraResults = propertiesList[p.maximumDetections :]
            propertiesList = propertiesList[: p.maximumDetections]
            for extraResult in extraResults:
                labelMapArray[labelMapArray == extraResult[0]] = 0

        propertiesDataFrame = pd.DataFrame(
            propertiesList, columns=["diam (cm)", "circularity", "solidity", "azimuth (°)", "label"]
        )

        # Abort early if nothing is detected
        if len(propertiesDataFrame.index) == 0:
            return labelMapArray, propertiesDataFrame

        # Removing cloned columns
        labelMapArray = labelMapArray[:, :, EXTRA_COLUMNS : self.inferenceConfig.IMAGE_MIN_DIM + EXTRA_COLUMNS]

        labelMapArray = updateLabelMapArray(labelMapArray, p.ttImageNode)

        ijkToRASMatrix = vtk.vtkMatrix4x4()
        p.ampImageNode.GetIJKToRASMatrix(ijkToRASMatrix)
        labels = propertiesDataFrame["label"].to_list()
        depths, problematicLabels = instances_depths(labelMapArray, labels, ijkToRASMatrix)
        problematicIndexes = propertiesDataFrame[propertiesDataFrame["label"].isin(problematicLabels)].index
        propertiesDataFrame.drop(problematicIndexes, inplace=True)
        propertiesDataFrame["depth (m)"] = depths
        propertiesDataFrame.sort_values(by=["depth (m)"], ascending=True, inplace=True)

        propertiesDataFrame = propertiesDataFrame[
            ["depth (m)", "diam (cm)", "circularity", "solidity", "azimuth (°)", "label"]
        ]

        labelMapArray, propertiesDataFrame = self.removeSidewallSampleMarkDuplicate(labelMapArray, propertiesDataFrame)

        return labelMapArray, propertiesDataFrame

    def removeSidewallSampleMarkDuplicate(self, labelMapArray, propertiesDataFrame):
        df = propertiesDataFrame.copy()
        depthDelta = 0.05
        df["duplicates"] = (
            df["depth (m)"]
            .apply(
                lambda depth: df.index[
                    (depth - depthDelta <= df["depth (m)"]) & (depth + depthDelta >= df["depth (m)"])
                ]
            )
            .apply(lambda value: tuple(sorted(list(value))))
        )

        df = df[df["duplicates"].apply(len) == 2]

        df = df[(df["azimuth (°)"] < 20) | (df["azimuth (°)"] > 340)]

        df = df[["label", "duplicates", "azimuth (°)"]]

        df = df.groupby(["duplicates"]).aggregate(list)

        removedLabels = []
        for index, row in df.iterrows():
            labels = row["label"]
            azimuths = row["azimuth (°)"]
            if len(labels) == 2:
                if abs(azimuths[0] - 180) <= abs(azimuths[1] - 180):
                    removedLabels.append(labels[1])
                else:
                    removedLabels.append(labels[0])

        propertiesDataFrame = propertiesDataFrame[~propertiesDataFrame["label"].isin(removedLabels)]

        for removedLabel in removedLabels:
            labelMapArray[labelMapArray == removedLabel] = 0

        return labelMapArray, propertiesDataFrame

    def isValidSidewallSampleMark(self, properties):
        """
        Filtering extreme results.
        """
        # If the expanded mark is very big
        if properties["diam (cm)"] > 9:
            return False

        # If the expanded mark is very small
        if properties["diam (cm)"] < 3.5:
            return False

        # If a mark is very irregular
        if properties["circularity"] < 0.65:
            return False

        # If a mark is very irregular
        if properties["solidity"] < 0.8:
            return False

        return True

    def improveSidewallSampleMask(self, ampImage, mask, index):
        def keepLargestComponent(mask):
            newMask = np.zeros_like(mask)
            labels, statistics = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 4)[1:3]
            largestLabel = 1 + np.argmax(statistics[1:, cv2.CC_STAT_AREA])
            newMask[labels == largestLabel] = 1
            return newMask

        try:
            new_mask = expand_labels(mask, distance=14)  # expand to ensure getting all the mark
            # threshold to get just the mark
            new_mask = np.where(
                # Getting the limits of the mark, where is very dark
                np.logical_and(new_mask == 1, ampImage < 0.3 * np.mean(ampImage)),
                1,
                0,
            )
            new_mask = expand_labels(new_mask, distance=1)
            new_mask = binary_fill_holes(new_mask)
            # # sometimes the threshold will get some other background and will exclude them
            new_mask = keepLargestComponent(new_mask)
        except:
            print("Sidewall sample mark improvement failed on " + str(index))
        return new_mask
