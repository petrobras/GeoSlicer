import os
import csv
import slicer
import numpy as np

from ltrace.slicer.helpers import hex2Rgb
from pathlib import Path
from tqdm import tqdm


def get_brightness_factor_sequence(max_value):
    seq = np.array([0])
    exp = 0
    while len(seq) < max_value:
        asc_num = np.array(range(1, 2**exp + 1, 2))
        num = asc_num.copy()
        num[0::2] = asc_num[: len(num[::2])]
        num[1::2] = asc_num[len(asc_num) - 1 : len(num[1::2]) - 1 : -1]
        dem = np.array([2**exp] * len(num))
        seq = np.concatenate((seq, num / dem))
        exp += 1

    seq = seq[:max_value]

    return seq


def import_colors_from_csv(path):
    with open(path, mode="r", encoding="utf8") as f:
        reader = csv.reader(f)
        color_dict = {}
        for rows in reader:
            k = rows[1]
            v = rows[0]
            color_dict[k] = hex2Rgb(v)
    return color_dict


def saveColorTable(colorTable, exportFilePath):
    with open(exportFilePath, "w") as file:
        file.write(f"# Color Table file {exportFilePath}\n")
        file.write(f"# {colorTable.GetNumberOfColors()} values\n")
        rgba = np.zeros(4, dtype=np.float64)
        for i in range(colorTable.GetNumberOfColors()):
            name = colorTable.GetColorName(i)
            colorTable.GetColor(i, rgba)
            rgba = rgba * 255.0
            file.write(f"{i} {name} {int(rgba[0])} {int(rgba[1])} {int(rgba[2])} {int(rgba[3])}\n")


max_value = 1000

brightness_factors = get_brightness_factor_sequence(max_value)
color_dict = import_colors_from_csv(Path(os.path.dirname(os.path.realpath(__file__))) / "colors.csv")
classes = color_dict.keys()
for idx, cls in tqdm(enumerate(classes)):
    colorNode = slicer.vtkMRMLColorTableNode()
    colorNode.SetTypeToUser()
    colorNode.SetNumberOfColors(max_value + 1)
    colorNode.SetName(f"{cls}_ColorTable")
    colorNode.SetColorName(0, "Background")
    colorNode.SetColor(0, 0.0, 0.0, 0.0, 0.0)
    colorNode.SetColorName(0, "Background")
    colorNode.SetColor(0, 0.0, 0.0, 0.0, 0.0)
    class_color = color_dict[cls]
    for j in range(1, max_value + 1):
        colorNode.SetColorName(j, f"Segment_{j}")
        brightness_factor = brightness_factors[j - 1] - 0.5
        color = [max(0, min(1.0, ch - 0.5 * ch * brightness_factor)) for ch in class_color]
        colorNode.SetColor(j, *color, 1.0)
        saveColorTable(colorNode, f"{cls}.ctbl")
