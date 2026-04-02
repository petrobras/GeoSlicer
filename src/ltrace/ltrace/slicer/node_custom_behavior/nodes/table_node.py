import slicer
import qt
from pathlib import Path

from ltrace.slicer.node_custom_behavior.node_custom_behavior_base import (
    NodeCustomBehaviorBase,
    CustomBehaviorRequirements,
)
from ltrace.slicer.node_custom_behavior.defs import TriggerEvent
from ltrace.slicer.helpers import autoDetectColumnType


class TableNodeCustomBehavior(NodeCustomBehaviorBase):
    """Custom behavior for vtkMRMLTableNode.
    This change forces the related storable node to signalize that it was modified when the node itself is modified."""

    REQUIREMENTS = CustomBehaviorRequirements(nodeTypes=[slicer.vtkMRMLTableNode], attributes={})

    def __init__(self, node: slicer.vtkMRMLNode, event: TriggerEvent) -> None:
        super().__init__(node=node, event=event)

    def _onNodeAdded(self, node: slicer.vtkMRMLNode) -> None:
        if node.GetName() == "Default mineral colors":
            return

        node.AddObserver("ModifiedEvent", self.__onNodeModified)

        qt.QTimer.singleShot(0, lambda: self.__processTableNodeOnAdded(node))

    def __processTableNodeOnAdded(self, tableNode):
        """
        Process a table node after a short delay to ensure the storageNode is linked.
        This is called via singleShot(0) from _onNodeAdded for vtkMRMLTableNode.
        """
        if tableNode.GetScene() is None:
            return

        storageNode = tableNode.GetStorageNode()

        # This line is important for the Slicer shows the type property on tooltip when hover
        tableNode.SetDefaultColumnType("double")

        if storageNode:
            schemaFilePath = None
            for i in range(storageNode.GetNumberOfFileNames()):
                fileName = storageNode.GetNthFileName(i)
                if fileName and fileName.endswith(".schema.tsv"):
                    schemaFilePath = Path(fileName)
                    if not schemaFilePath.is_absolute():
                        rootDir = slicer.mrmlScene.GetRootDirectory()
                        if rootDir:
                            schemaFilePath = Path(rootDir) / schemaFilePath
                    break

            if not schemaFilePath or not schemaFilePath.exists():
                autoDetectColumnType(tableNode)
        else:
            autoDetectColumnType(tableNode)

    def _onNodeRemoved(self, node: slicer.vtkMRMLNode) -> None:
        pass

    def _onNodeAboutToBeRemoved(self, node: slicer.vtkMRMLNode) -> None:
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return

        for i in range(layoutManager.tableViewCount):
            tableWidget = layoutManager.tableWidget(i)
            if tableWidget and tableWidget.tableView():
                tableView = tableWidget.tableView()
                currentTableNode = tableView.mrmlTableNode()
                if currentTableNode and currentTableNode.GetID() == node.GetID():
                    viewNode = tableView.mrmlTableViewNode()
                    if viewNode:
                        viewNode.SetTableNodeID(None)

    def __onNodeModified(self, node: slicer.vtkMRMLNode, event) -> None:
        node.StorableModified()

    def _beforeSave(self) -> None:
        storageNode = self._node.GetStorageNode()
        if not storageNode:
            return

        fileName = storageNode.GetFileName()
        if not fileName:
            return

        filePath = Path(fileName)
        schemaPath = filePath.with_suffix(".schema" + filePath.suffix)

        if schemaPath.exists():
            rootDir = slicer.mrmlScene.GetRootDirectory()

            absoluteSchemaPath = schemaPath
            if rootDir and not schemaPath.is_absolute():
                absoluteSchemaPath = Path(rootDir) / schemaPath

            # Check if the schema is already in the list
            found = False
            for i in range(storageNode.GetNumberOfFileNames()):
                nthPath = Path(storageNode.GetNthFileName(i))
                absoluteNthPath = nthPath
                if rootDir and not nthPath.is_absolute():
                    absoluteNthPath = Path(rootDir) / nthPath

                if absoluteNthPath == absoluteSchemaPath:
                    found = True
                    break
            if not found:
                storageNode.AddFileName(str(schemaPath))
