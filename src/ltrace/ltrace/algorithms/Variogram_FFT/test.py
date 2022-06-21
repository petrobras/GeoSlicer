import numpy as np
import matplotlib.pyplot as plt

from variogram import *

data = np.loadtxt("simulation_5_10_10.csv", dtype=int)
data = data.reshape(200, 200, 200)

data = data[:, :, :]

spacing = 0.01
# spacing = [0.1, 0.1, 0.1]

variogram_axes, axes = compute_axes_variogram_FFT(data, spacing)


# plt.imshow(corr_func[:,:,100])
plt.plot(axes[0], variogram_axes[0])
plt.plot(axes[1], variogram_axes[1])
plt.plot(axes[2], variogram_axes[2])
plt.show()
