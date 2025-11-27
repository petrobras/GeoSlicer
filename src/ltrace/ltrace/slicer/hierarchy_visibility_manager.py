from ltrace.slicer.node_observer import NodeObserver

import slicer


class HierarchyVisibilityManager:
    """Makes hierarchy folders above node visible when it becomes visible.
    Slicer has no visibility changed event (the modified event is triggered
    when a parent folder visibility is changed), so this class keeps track
    of the last visibility state of the node as a workaround.
    """

    def __init__(self, displayNode: slicer.vtkMRMLDisplayNode, getDisplayableNode: callable):
        # Set to false to trigger visibility change on first update
        self.__lastVisibility = False
        self.__getDisplayableNode = getDisplayableNode
        self.__nodeObserver = NodeObserver(displayNode, parent=slicer.modules.AppContextInstance.mainWindow)
        self.__nodeObserver.modifiedSignal.connect(self.__onNodeModified)
        self.__nodeObserver.removedSignal.connect(self.__onNodeRemoved)

    @staticmethod
    def __makeAllAncestorsVisible(node):
        if node is None:
            return False
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        id_ = sh.GetItemByDataNode(node)
        if id_ == 0:
            return False
        pluginHandler = slicer.qSlicerSubjectHierarchyPluginHandler().instance()
        folderPlugin = pluginHandler.pluginByName("Folder")
        sceneId = sh.GetSceneItemID()
        while (id_ := sh.GetItemParent(id_)) != sceneId:
            node = sh.GetItemDataNode(id_)
            if isinstance(node, slicer.vtkMRMLFolderDisplayNode):
                folderPlugin.setDisplayVisibility(id_, 1)
            sh.SetItemDisplayVisibility(id_, True)
        return True

    def __onNodeModified(self, nodeObserver: NodeObserver, caller: slicer.vtkMRMLNode) -> None:
        if self.__lastVisibility:
            self.__lastVisibility = caller.GetVisibility()
        elif caller.GetVisibility():
            if self.__getDisplayableNode is None:
                return

            status = self.__makeAllAncestorsVisible(self.__getDisplayableNode(caller))
            # First few calls for volume rendering are before it's set up, we
            # should skip these so the callback is triggered again later
            if status:
                self.__lastVisibility = caller.GetVisibility()

    def __onNodeRemoved(self) -> None:
        if self.__nodeObserver is not None:
            self.__nodeObserver.deleteLater()
            self.__nodeObserver = None

        del self.__getDisplayableNode
        self.__getDisplayableNode = None

        del self
