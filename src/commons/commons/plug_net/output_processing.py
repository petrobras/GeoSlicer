import numpy as np

Y_LIMITS = np.array([[0.0, 2000.0], [0.0, 35.0], [2.2, 2.9]])


def preprocess(y):
    return (y - Y_LIMITS[:, 0]) / (Y_LIMITS[:, 1] - Y_LIMITS[:, 0])


def postprocess(y):
    return y * (Y_LIMITS[:, 1] - Y_LIMITS[:, 0]) + Y_LIMITS[:, 0]
