import slicer


def configureInitialNodeMetadata(root_dataset_dir_name, baseName, node):
    if isinstance(baseName, str):
        baseName = (baseName,)

    subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    rootDirID = subjectHierarchyNode.GetItemByName(root_dataset_dir_name)
    if rootDirID == 0:
        rootDirID = subjectHierarchyNode.CreateFolderItem(subjectHierarchyNode.GetSceneItemID(), root_dataset_dir_name)
    parentDirID = rootDirID

    for name in baseName:
        dirID = subjectHierarchyNode.GetItemChildWithName(parentDirID, name)
        if dirID == 0:
            dirID = subjectHierarchyNode.CreateFolderItem(parentDirID, name)
        subjectHierarchyNode.SetItemParent(
            subjectHierarchyNode.GetItemByDataNode(node),
            dirID,
        )
        parentDirID = dirID
