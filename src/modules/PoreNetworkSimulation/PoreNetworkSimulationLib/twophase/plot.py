import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


if __name__ == "__main__":
    ax = plt.axes(projection="3d")
    df = pd.read_csv("output.txt", header=None)
    ax.plot3D(df[0], df[1], np.sqrt(df[2] ** 2 + df[3] ** 2))
    plt.show()
