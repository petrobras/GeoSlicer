import qt
import slicer

from pathlib import Path
from ltrace.slicer.lazy import lazy as lazy_module


class DisplayOverrideSubjectHierarchyPlugin:
    """Display-override provider for the SH Data tree.

    Registered globally via qSlicerSubjectHierarchyPluginHandler::setDisplayOverrideProvider().
    The model consults this single provider on every name-column and visibility-column refresh
    in every SH tree view. Each method:

        Return an empty/null value to keep the default.
        Return a non-empty/non-null value to override.

    If a method is missing, raises, or returns the wrong type, the failure surfaces visibly:
    string overrides come back as "ERROR: ..." in the tooltip / displayed name; icon overrides
    come back as a red-X icon plus a qCritical log entry.
    """

    filePath = __file__

    def __init__(self, scriptedPlugin):
        scriptedPlugin.name = "DisplayOverride"
        self.scriptedPlugin = scriptedPlugin
        self._iconsDir = Path(slicer.app.slicerHome) / "LTrace" / "Resources" / "Icons" / "svg" / "Explorer"
        self._icons = {}  # SVG parsing on every refresh would be expensive; cache on first use

    def _icon(self, name):
        if name not in self._icons:
            self._icons[name] = qt.QIcon(str(self._iconsDir / f"{name}.svg"))
        return self._icons[name]

    def tooltipOverride(self, itemID, defaultTooltip):
        shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        if shNode is None:
            return ""
        itemName = shNode.GetItemName(itemID)
        node = shNode.GetItemDataNode(itemID)

        if node is not None:
            if node.IsA("vtkMRMLScalarVolumeNode"):  # covers LabelMapVolumeNode too
                img = node.GetImageData()
                if img is not None:
                    d = img.GetDimensions()
                    return f"{itemName}\n{d[0]}x{d[1]}x{d[2]}"

            if lazy_module.is_lazy_node(node):
                return f"{itemName}"

        return itemName

    def iconOverride(self, itemID, defaultIcon):
        shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        if shNode is None:
            return qt.QIcon()
        node = shNode.GetItemDataNode(itemID)

        # Lazy nodes are TextNodes with a specific attribute; check before the TextNode branch below.
        if lazy_module.is_lazy_node(node):
            return self._icon("Lazy")

        # Segments expose the parent segmentation node as their data node, so the IsA chain
        # would mis-match them. Check owner first.
        ownerPlugin = shNode.GetItemOwnerPluginName(itemID)
        if ownerPlugin == "Segments":
            return self._icon("Segment")

        if node is not None:
            # LabelMap before Scalar - vtkMRMLLabelMapVolumeNode IsA vtkMRMLScalarVolumeNode.
            if node.IsA("vtkMRMLLabelMapVolumeNode"):
                return self._icon("LabelMap")
            if node.IsA("vtkMRMLVectorVolumeNode"):
                return self._icon("Vector")
            if node.IsA("vtkMRMLScalarVolumeNode"):
                return self._icon("Scalar")
            if node.IsA("vtkMRMLModelNode"):
                return self._icon("Model")
            if node.IsA("vtkMRMLSegmentationNode"):
                return self._icon("Segmentation")
            if node.IsA("vtkMRMLTableNode"):
                return self._icon("Table")
            if node.IsA("vtkMRMLTextNode"):
                return self._icon("Text")

        # Folders have no data node - detect by owner plugin name.
        if ownerPlugin == "Folder":
            return self._icon("Folder")

        return qt.QIcon()

    def visibilityIconOverride(self, itemID, visible, defaultIcon):
        if visible not in (0, 1):
            return qt.QIcon()
        shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
        if shNode is None:
            return qt.QIcon()

        return self._icon("Eye") if visible == 1 else self._icon("EyeClosed")

    def displayedNameOverride(self, itemID, defaultName):
        return ""
