import math

import numpy as np
import pyqtgraph as pg


class DepthOverviewAxisItem(pg.AxisItem):
    def __init__(self):
        super().__init__(orientation="left")

    def tickSpacing(self, minVal, maxVal, size):
        """Return values describing the desired spacing and offset of ticks.

        This method is called whenever the axis needs to be redrawn and is a
        good method to override in subclasses that require control over tick locations.

        The return value must be a list of tuples, one for each set of ticks::

            [
                (major tick spacing, offset),
                (minor tick spacing, offset),
                (sub-minor tick spacing, offset),
                ...
            ]
        """
        # First check for override tick spacing
        if self._tickSpacing is not None:
            return self._tickSpacing

        dif = abs(maxVal - minVal)
        if dif == 0:
            return []

        ## decide optimal minor tick spacing in pixels (this is just aesthetics)
        optimalTickCount = max(2.0, math.log(size))

        ## optimal minor tick spacing
        optimalSpacing = dif / optimalTickCount

        ## the largest power-of-10 spacing which is smaller than optimal
        p10unit = 10 ** math.floor(math.log10(optimalSpacing))

        ## Determine major/minor tick spacings which flank the optimal spacing.
        intervals = np.array([1.0, 2.0, 10.0, 20.0, 100.0]) * p10unit
        minorIndex = 0
        while intervals[minorIndex + 1] <= optimalSpacing:
            minorIndex += 1

        levels = []

        ## decide whether to include the last level of ticks
        minSpacing = min(size / 20.0, 30.0)
        maxTickCount = size / minSpacing
        if dif / intervals[minorIndex] <= maxTickCount:
            levels.append((intervals[minorIndex], 0))
        else:
            levels.append((intervals[minorIndex + 1], 0))

        return levels
