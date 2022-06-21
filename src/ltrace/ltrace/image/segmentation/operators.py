import os

import tensorflow as tf

# Remember to not import slicer qt functions inside a cli
# from ltrace.slicer_utils import is_tensorflow_gpu_enabled

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import numpy as np
from ltrace.transforms import tf_pad_dims
from pathlib import Path


def roll(arr, shape, astep=None):
    if astep is None:
        astep = (1, 1)

    offset = shape[0] - astep[0], shape[1] - astep[1]

    xlen, ylen, _ = arr.shape
    for i in range(0, xlen - offset[0], astep[0]):
        xmin = i
        xmax = i + shape[0]
        for j in range(0, ylen - offset[1], astep[1]):
            ymin = j
            ymax = j + shape[1]
            yield arr[xmin:xmax, ymin:ymax, :]


class TF_RGBImageArrayBinarySegmenter(object):
    def __init__(self, model, gpuEnabled=True):
        if gpuEnabled:
            physical_devices = tf.config.experimental.list_physical_devices("GPU")
            if physical_devices:
                tf.config.experimental.set_memory_growth(physical_devices[0], True)
        else:
            tf.config.set_visible_devices([], "GPU")

        if isinstance(model, str):
            model = Path(model)

        if isinstance(model, Path):
            self.model = tf.keras.models.load_model(str(model), compile=False)
        else:
            self.model = model

        self.tf_model_input_shape = (128, 128)
        self.offset = (64, 64)
        self.buffer_size = (
            self.tf_model_input_shape[0] + self.offset[0],
            self.tf_model_input_shape[1] + self.offset[1],
        )

    def _reshape(self, result, padded_shape: tuple):
        segmented = np.zeros((padded_shape[0], padded_shape[1], 1))
        normalizer = np.zeros((padded_shape[0], padded_shape[1], 1))

        for res, out, norm in zip(
            result,
            roll(segmented, shape=self.tf_model_input_shape, astep=self.offset),
            roll(normalizer, shape=self.tf_model_input_shape, astep=self.offset),
        ):
            out += res
            norm += 1.0
        return segmented / normalizer

    def _postprocessing(self, data):
        # import cv2 as cv
        # from skimage.filters import threshold_otsu

        # background is black and foreground is white
        data[data >= 0] = 1
        data[data < 0] = 0

        # t = threshold_otsu(data)
        # mask = np.array(data > t, dtype=np.uint8)

        # kernel = np.ones((48,48),np.uint8)
        # mask = cv.morphologyEx(mask, cv.MORPH_CLOSE, kernel)

        # kernel = np.ones((15,15),np.uint8)
        # mask = cv.morphologyEx(mask, cv.MORPH_OPEN, kernel)

        return data

    def predict(self, image8bit: np.ndarray):
        image = image8bit * (1.0 / 255)

        xpad = tf_pad_dims(image.shape[0], self.offset[0], self.tf_model_input_shape[0])
        ypad = tf_pad_dims(image.shape[1], self.offset[1], self.tf_model_input_shape[1])
        tf_image = tf.constant(image[np.newaxis], dtype=tf.float32, name="data")
        tf_images = tf.image.extract_patches(
            images=tf_image,
            sizes=[1, *self.tf_model_input_shape, 1],
            strides=[1, *self.offset, 1],
            rates=[1, 1, 1, 1],
            padding="SAME",
        )
        tf_images = tf.reshape(
            tf_images, [tf_images.shape[1] * tf_images.shape[2], *self.tf_model_input_shape, image.shape[2]]
        )

        result = self.model.predict(tf_images)

        segmented = self._reshape(result, [xpad[0] + xpad[1] + image.shape[0], ypad[0] + ypad[1] + image.shape[1], 1])

        mask = self._postprocessing(segmented[xpad[0] : -xpad[1], ypad[0] : -ypad[1], :])

        return mask


if __name__ == "__main__":

    import imageio as io
    import matplotlib.pyplot as plt
    import datetime

    image = io.imread("G:/projetoPetro/Sepia/fotografias_sep1/conjunto/01cx01-04_60.jpg")

    model = TF_RGBImageArrayBinarySegmenter("ltrace/ltrace/assets/trained_models/unet-binary-segop.h5")
    a = datetime.datetime.now()

    mask = model.predict(image)
    b = datetime.datetime.now()
    c = b - a
    # visualization
    f, axarr = plt.subplots(1, 2)
    print(c.total_seconds())
    axarr[0].imshow(image)
    axarr[1].imshow(mask.squeeze(), cmap="Greys")

    plt.show()
