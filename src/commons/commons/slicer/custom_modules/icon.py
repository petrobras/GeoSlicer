"""Placeholder icon for custom modules that don't ship one."""

import qt

from commons.slicer.helpers import svgToQIcon
from commons.slicer_utils import getResourcePath

# What Slicer shows for a scripted module without Resources/Icons/<ModuleName>.svg or .png
SLICER_DEFAULT_MODULE_ICON = ":/Icons/Extension.png"


def hasDefaultIcon(icon) -> bool:
    if icon is None or icon.isNull():
        return True
    size = qt.QSize(64, 64)
    return icon.pixmap(size).toImage() == qt.QIcon(SLICER_DEFAULT_MODULE_ICON).pixmap(size).toImage()


def usePlaceholderIconIfMissing(slicerModule) -> bool:
    """Give a loaded module the puzzle icon if it has none of its own. Returns whether it did."""
    if not hasDefaultIcon(slicerModule.icon):
        return False
    slicerModule.icon = svgToQIcon(getResourcePath("Icons") / "svg" / "Puzzle.svg")
    return True
