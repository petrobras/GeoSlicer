import collections
import slicer
import vtk
import numpy as np

from ltrace.slicer.node_attributes import ColorMapSelectable


COLOR_MAPS_NAME = [
    "Labels",
    "Grey",
    "InvertedGray",
    "Red",
    "Yellow",
    "ColdToHotRainbow",
    "HotToColdRainbow",
    "DivergingBlueRed",
    "Viridis",
    "Afmhot",
    "InvertedAfmhot",
]

RENAME_COLOR_MAPS = {
    "Labels": "Labels",
    "Grey": "Grey",
    "InvertedGray": "Inverted Gray",
    "Red": "Red",
    "Yellow": "Yellow",
    "ColdToHotRainbow": "Cold To Hot Rainbow",
    "HotToColdRainbow": "Hot To Cold Rainbow",
    "DivergingBlueRed": "Diverging Blue Red",
    "Viridis": "Viridis",
    "Afmhot": "AFMHot",
    "InvertedAfmhot": "Inverted AFMHot",
}


def customize_color_maps():
    add_custom_colors()
    color_map_nodes = get_original_color_map_nodes()
    rename_color_map_nodes(color_map_nodes)
    set_selectable_color_maps(color_map_nodes)


def rename_color_map_nodes(color_map_nodes):
    for node in color_map_nodes:
        if node.GetName() in RENAME_COLOR_MAPS.keys():
            node.SetName(RENAME_COLOR_MAPS[node.GetName()])


def set_selectable_color_maps(color_map_nodes):
    for node in color_map_nodes:
        node.SetAttribute(ColorMapSelectable.name(), ColorMapSelectable.TRUE.value)


def get_original_color_map_nodes():
    nodes = [slicer.mrmlScene.GetNthNode(idx) for idx in range(slicer.mrmlScene.GetNumberOfNodes())]
    color_map_nodes = []
    for node in nodes:
        if node.GetName() in COLOR_MAPS_NAME:
            color_map_nodes.append(node)

    return color_map_nodes


def add_custom_colors():
    import matplotlib.pyplot as plt

    afmhot = plt.get_cmap("afmhot")
    afmhot.name = "Afmhot"
    add_color_map(afmhot)
    afmhot_reversed = plt.get_cmap("afmhot_r")
    afmhot_reversed.name = "InvertedAfmhot"
    add_color_map(afmhot_reversed)


def add_color_map(cmap):
    ## not working for every colormap on matplotlib
    ## only for the ones with 256 colors.
    c = cmapToColormap(cmap, 256)
    n = slicer.vtkMRMLColorTableNode()
    n.SaveWithSceneOff()
    n.SetName(cmap.name)
    lut = vtk.vtkLookupTable()
    lut.SetRampToLinear()
    lut.SetTableRange(0, 255)
    lut.SetHueRange(0, 1)
    lut.SetSaturationRange(0, 1)
    lut.SetValueRange(1, 1)
    lut.SetAlphaRange(1, 1)
    lut.SetNumberOfColors(len(c))
    lut.Build()
    n.SetLookupTable(lut)
    n.SetNamesFromColors()
    slicer.mrmlScene.AddNode(n)
    for i in range(len(c)):
        ci = np.array(c[i][1]) / 255
        lut.SetTableValue(i, *ci, 1)


def cmapToColormap(cmap, nTicks=256):
    import numpy as np

    """
    Converts a Matplotlib cmap to pyqtgraphs colormaps. No dependency on matplotlib.

    Parameters:
    *cmap*: Cmap object. Imported from matplotlib.cm.*
    *nTicks*: Number of ticks to create when dict of functions is used. Otherwise unused.
    """
    # Case #1: a dictionary with 'red'/'green'/'blue' values as list of ranges (e.g. 'jet')
    # The parameter 'cmap' is a 'matplotlib.colors.LinearSegmentedColormap' instance ...
    if hasattr(cmap, "_segmentdata"):
        colordata = getattr(cmap, "_segmentdata")
        if ("red" in colordata) and isinstance(colordata["red"], collections.Sequence):
            # collect the color ranges from all channels into one dict to get unique indices
            posDict = {}
            for idx, channel in enumerate(("red", "green", "blue")):
                for colorRange in colordata[channel]:
                    posDict.setdefault(colorRange[0], [-1, -1, -1])[idx] = colorRange[2]
            indexList = list(posDict.keys())
            indexList.sort()
            # interpolate missing values (== -1)
            for channel in range(3):  # R,G,B
                startIdx = indexList[0]
                emptyIdx = []
                for curIdx in indexList:
                    if posDict[curIdx][channel] == -1:
                        emptyIdx.append(curIdx)
                    elif curIdx != indexList[0]:
                        for eIdx in emptyIdx:
                            rPos = (eIdx - startIdx) / (curIdx - startIdx)
                            vStart = posDict[startIdx][channel]
                            vRange = posDict[curIdx][channel] - posDict[startIdx][channel]
                            posDict[eIdx][channel] = rPos * vRange + vStart
                        startIdx = curIdx
                        del emptyIdx[:]
            for channel in range(3):  # R,G,B
                for curIdx in indexList:
                    posDict[curIdx][channel] *= 255
            posList = [[i, posDict[i]] for i in indexList]
            return posList
        # Case #2: a dictionary with 'red'/'green'/'blue' values as functions (e.g. 'gnuplot')
        elif ("red" in colordata) and isinstance(colordata["red"], collections.Callable):
            indices = np.linspace(0.0, 1.0, nTicks)
            luts = [
                np.clip(np.array(colordata[rgb](indices), dtype=np.float), 0, 1) * 255
                for rgb in ("red", "green", "blue")
            ]
            return list(zip(indices, list(zip(*luts))))
    # If the parameter 'cmap' is a 'matplotlib.colors.ListedColormap' instance, with the attributes 'colors' and 'N'
    elif hasattr(cmap, "colors") and hasattr(cmap, "N"):
        colordata = getattr(cmap, "colors")
        # Case #3: a list with RGB values (e.g. 'seismic')
        if len(colordata[0]) == 3:
            indices = np.linspace(0.0, 1.0, len(colordata))
            scaledRgbTuples = [(rgbTuple[0] * 255, rgbTuple[1] * 255, rgbTuple[2] * 255) for rgbTuple in colordata]
            return list(zip(indices, scaledRgbTuples))
        # Case #4: a list of tuples with positions and RGB-values (e.g. 'terrain')
        # -> this section is probably not needed anymore!?
        elif len(colordata[0]) == 2:
            scaledCmap = [(idx, (vals[0] * 255, vals[1] * 255, vals[2] * 255)) for idx, vals in colordata]
            return scaledCmap
    # Case #X: unknown format or datatype was the wrong object type
    else:
        raise ValueError("[cmapToColormap] Unknown cmap format or not a cmap!")
