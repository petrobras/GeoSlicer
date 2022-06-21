import itertools

import numpy as np
import matplotlib.pyplot as plt
import cv2
from numba import njit, prange


@njit
def gaussian(x, desv_pad):
    return np.exp(-np.power(x, 2.0) / (2 * np.power(desv_pad, 2.0)))


@njit
def get_equidistant_angles(target_n):
    """See https://www.cmu.edu/biolphys/deserno/pdf/sphere_equi.pdf"""
    angles = []
    a = 4 * np.pi / target_n
    d = np.sqrt(a)
    Mt = np.uint16(np.round(np.pi / d))
    dt = np.pi / Mt
    dr = a / dt
    for m in range(Mt):
        theta = np.pi * (m + 0.5) / Mt
        Mr = np.uint16(np.round(2 * np.pi * np.sin(theta) / dr))
        for n in range(Mr):
            # We use pi instead of 2pi because the gabor kernel is symmetric over 180 degrees
            rho = np.pi * n / Mr
            angles.append((theta, rho))
    return angles[:target_n]


@njit
def create_gabor_kernel(alpha, beta, wave_length, standard_deviation, size):
    center_x = (size[0] + 1) / 2
    center_y = (size[1] + 1) / 2
    center_z = (size[2] + 1) / 2

    axis = np.array([np.sin(alpha) * np.cos(beta), np.sin(alpha) * np.sin(beta), np.cos(alpha)])

    kernel = np.zeros(size, dtype=np.float32)
    for i in prange(size[0]):
        for j in range(size[1]):
            for k in range(size[2]):
                pos = np.array([i - center_x, j - center_y, k - center_z])
                distance = np.linalg.norm(pos)
                displacement = np.dot(pos, axis)
                kernel[i, j, k] = gaussian(distance, standard_deviation) * np.cos(
                    2 * np.pi * displacement / wave_length
                )
    return kernel


def get_gabor_kernels_3d(wave_length, rotations, standard_deviation=None, size=None):

    if standard_deviation == None:
        standard_deviation = wave_length * np.pi

    if size == None:
        size = (int(np.floor(standard_deviation * 3)),) * 3
    elif type(size) == int:
        size = (size,) * 3

    angles = get_equidistant_angles(rotations)
    kernels = [create_gabor_kernel(alpha, beta, wave_length, standard_deviation, size) for alpha, beta in angles]
    return kernels


def get_gabor_kernels_2d(sigma, lambd, n_rotations, size):
    params = {
        "sigma": sigma,
        "lambd": lambd,
        "gamma": 1.0,
        "psi": 0.0,
        "ktype": cv2.CV_32F,
        "ksize": (size,) * 2,
    }

    kernels = []
    for i in range(n_rotations):
        params["theta"] = np.pi * i / float(n_rotations)
        kernels.append(cv2.getGaborKernel(**params))
    return kernels


def get_gabor_kernels(sigma, lambd, n_rotations, size, is_2d):
    if is_2d:
        return get_gabor_kernels_2d(sigma, lambd, n_rotations, size)
    return get_gabor_kernels_3d(lambd, n_rotations, sigma, (size,) * 3)
