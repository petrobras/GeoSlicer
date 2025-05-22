import slicer


class HierarchyVisibilityManager:
    """Makes hierarchy folders above node visible when it becomes visible.
    Slicer has no visibility changed event (the modified event is triggered
    when a parent folder visibility is changed), so this class keeps track
    of the last visibility state of the node as a workaround.
    """

    def __init__(self, display_node: slicer.vtkMRMLDisplayNode, get_displayable_node: callable):
        # Set to false to trigger visibility change on first update
        self.__last_visibility = False
        self.__get_displayable_node = get_displayable_node
        display_node.AddObserver("ModifiedEvent", self.__on_node_modified)

    @staticmethod
    def __make_all_ancestors_visible(node):
        if node is None:
            return False
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        id_ = sh.GetItemByDataNode(node)
        if id_ == 0:
            return False
        plugin_handler = slicer.qSlicerSubjectHierarchyPluginHandler().instance()
        folder_plugin = plugin_handler.pluginByName("Folder")
        scene_id = sh.GetSceneItemID()
        while (id_ := sh.GetItemParent(id_)) != scene_id:
            node = sh.GetItemDataNode(id_)
            if isinstance(node, slicer.vtkMRMLFolderDisplayNode):
                folder_plugin.setDisplayVisibility(id_, 1)
            sh.SetItemDisplayVisibility(id_, True)
        return True

    def __on_node_modified(self, caller, event):
        if self.__last_visibility:
            self.__last_visibility = caller.GetVisibility()
        elif caller.GetVisibility():
            status = self.__make_all_ancestors_visible(self.__get_displayable_node(caller))
            # First few calls for volume rendering are before it's set up, we
            # should skip these so the callback is triggered again later
            if status:
                self.__last_visibility = caller.GetVisibility()
