import vtk, qt, ctk, slicer
import logging
from AbstractScriptedSubjectHierarchyPlugin import *
import numpy as np
from ltrace.utils.ProgressBarProc import ProgressBarProc
from ltrace.vtk_utils.well_model.well_model import create_well_model_from_node


class CenterSubjectHierarchyPlugin(AbstractScriptedSubjectHierarchyPlugin):
    """Scripted subject hierarchy plugin for the Segment Editor module.

    This is also an example for scripted plugins, so includes all possible methods.
    The methods that are not needed (i.e. the default implementation in
    qSlicerSubjectHierarchyAbstractPlugin is satisfactory) can simply be
    omitted in plugins created based on this one.

    needs to be installed on folder Slicer 4.11.0-2020-01-20\lib\Slicer-4.11\qt-scripted-modules\SubjectHierarchyPlugins
    """

    # Necessary static member to be able to set python source to scripted subject hierarchy plugin
    filePath = __file__

    def __init__(self, scriptedPlugin):
        scriptedPlugin.name = "CenterVolumeModule"
        AbstractScriptedSubjectHierarchyPlugin.__init__(self, scriptedPlugin)

        self.centerVolumeAction = qt.QAction("Center to this Volume", scriptedPlugin)
        self.centerVolumeAction.connect("triggered()", self.centerToThisVolume)
        self.chartShortcutAction = qt.QAction("Go to Charts", scriptedPlugin)
        self.chartShortcutAction.triggered.connect(self.__onChartsShortcutClicked)
        self.centerSegmentAction = qt.QAction("Center to this segment", scriptedPlugin)
        self.centerSegmentAction.connect("triggered()", self.centerToThisSegment)
        self.folderToSequenceAction = qt.QAction("Create sequence", scriptedPlugin)
        self.folderToSequenceAction.triggered.connect(self.create_sequence_from_folder)
        self.sequenceToFolderAction = qt.QAction("Unpack sequence", scriptedPlugin)
        self.sequenceToFolderAction.triggered.connect(self.extract_volumes_from_sequence)
        self.createWellModelAction = qt.QAction("Create well Model", scriptedPlugin)
        self.createWellModelAction.triggered.connect(self.create_well_model_node)

    def canAddNodeToSubjectHierarchy(self, node, parentItemID):
        # This plugin cannot own any items (it's not a role but a function plugin),
        # but the it can be decided the following way:
        # if node is not None and node.IsA("vtkMRMLMyNode"):
        #   return 1.0
        return 0.0

    def canOwnSubjectHierarchyItem(self, itemID):
        # This plugin cannot own any items (it's not a role but a function plugin),
        # but the it can be decided the following way:
        # pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
        # shNode = pluginHandlerSingleton.subjectHierarchyNode()
        # associatedNode = shNode.GetItemDataNode(itemID)
        # if associatedNode is not None and associatedNode.IsA("vtkMRMLMyNode"):
        #   return 1.0
        return 0.0

    def roleForPlugin(self):
        # As this plugin cannot own any items, it doesn't have a role either
        return "N/A"

    def helpText(self):
        # return ("<p style=\" margin-top:4px; margin-bottom:1px; margin-left:0px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\">"
        # "<span style=\" font-family:'sans-serif'; font-size:9pt; font-weight:600; color:#000000;\">"
        # "SegmentEditor module subject hierarchy help text"
        # "</span>"
        # "</p>"
        # "<p style=\" margin-top:0px; margin-bottom:11px; margin-left:26px; margin-right:0px; -qt-block-indent:0; text-indent:0px;\">"
        # "<span style=\" font-family:'sans-serif'; font-size:9pt; color:#000000;\">"
        # "This is how you can add help text to the subject hierarchy module help box via a python scripted plugin."
        # "</span>"
        # "</p>\n")
        return ""

    def icon(self, itemID):
        # As this plugin cannot own any items, it doesn't have an icon either
        # import os
        # iconPath = os.path.join(os.path.dirname(__file__), 'Resources/Icons/MyIcon.png')
        # if self.canOwnSubjectHierarchyItem(itemID) > 0.0 and os.path.exists(iconPath):
        # return qt.QIcon(iconPath)
        # Item unknown by plugin
        return qt.QIcon()

    def visibilityIcon(self, visible):
        pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
        return pluginHandlerSingleton.pluginByName("Default").visibilityIcon(visible)

    def editProperties(self, itemID):
        pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
        pluginHandlerSingleton.pluginByName("Default").editProperties(itemID)

    def itemContextMenuActions(self):
        actions = [
            self.chartShortcutAction,
            self.centerSegmentAction,
            self.folderToSequenceAction,
            self.sequenceToFolderAction,
        ]
        if slicer.util.selectedModule() != "ImageLogEnv":
            actions.append(self.centerVolumeAction)
            actions.append(self.createWellModelAction)
        return actions

    def centerToThisVolume(self, volume=None):
        if volume is None:
            pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
            currentItemID = pluginHandlerSingleton.currentItem()
            if not currentItemID:
                logging.error("Invalid current item")

            subjectHierarchyNode = pluginHandlerSingleton.subjectHierarchyNode()
            volume = subjectHierarchyNode.GetItemDataNode(currentItemID)

        # Get volume center
        bounds = np.zeros(6)
        volume.GetRASBounds(bounds)
        volumeCenter = [(bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2, (bounds[4] + bounds[5]) / 2]

        # Shift camera to look at the new focal point
        threeDView = slicer.app.layoutManager().threeDWidget(0).threeDView()
        camera = threeDView.renderWindow().GetRenderers().GetFirstRenderer().GetActiveCamera()
        shift = ((bounds[5] - bounds[4]) / 2) / np.tan(camera.GetViewAngle() / 2 / 180 * np.pi) * 1.1

        camera.SetFocalPoint(volumeCenter)
        camera.SetPosition(volumeCenter[0], volumeCenter[1] + shift, volumeCenter[2])
        camera.SetRoll(180)

        volumeRenderingLogic = slicer.modules.volumerendering.logic()
        displayNode = volumeRenderingLogic.CreateDefaultVolumeRenderingNodes(volume)
        displayNode.SetVisibility(True)

        slicer.app.layoutManager().threeDWidget(0).threeDView().zoomOut()

    def centerToThisSegment(self):
        pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
        subjectHierarchyNode = pluginHandlerSingleton.subjectHierarchyNode()
        currentItemID = pluginHandlerSingleton.currentItem()

        segmentationNode = subjectHierarchyNode.GetItemDataNode(subjectHierarchyNode.GetItemParent(currentItemID))

        segmentID = subjectHierarchyNode.GetItemAttribute(currentItemID, "segmentID")
        markupsLogic = slicer.modules.markups.logic()

        segmentCenterRAS = segmentationNode.GetSegmentCenterRAS(segmentID)
        if slicer.util.selectedModule() != "ImageLogEnv":
            markupsLogic.JumpSlicesToLocation(*segmentCenterRAS, True)
        else:
            markupsLogic.JumpSlicesToLocation(0, 0, segmentCenterRAS[2], True)

    def sceneContextMenuActions(self):
        return []

    def showContextMenuActionsForItem(self, itemID):
        # Scene
        if not itemID:
            # No scene context menu actions in this plugin
            return

        pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
        subjectHierarchyNode = pluginHandlerSingleton.subjectHierarchyNode()
        currentItemID = pluginHandlerSingleton.currentItem()

        if not currentItemID:
            logging.error("Invalid current item")
            return

        item = subjectHierarchyNode.GetItemDataNode(currentItemID)

        self.centerVolumeAction.visible = type(item) is slicer.vtkMRMLScalarVolumeNode
        self.chartShortcutAction.visible = type(item) is slicer.vtkMRMLTableNode
        self.centerSegmentAction.visible = subjectHierarchyNode.GetItemOwnerPluginName(currentItemID) == "Segments"
        self.folderToSequenceAction.visible = (
            type(item) is slicer.vtkMRMLFolderDisplayNode
            or subjectHierarchyNode.GetItemOwnerPluginName(currentItemID) == "Folder"
        )
        is_proxy = (
            item is not None and slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(item) is not None
        )
        self.sequenceToFolderAction.visible = is_proxy
        self.createWellModelAction.visible = (
            type(item)
            in [
                slicer.vtkMRMLScalarVolumeNode,
                slicer.vtkMRMLLabelMapVolumeNode,
            ]
            and item.GetImageData().GetDimensions()[1] == 1
        )

    def tooltip(self, itemID):
        # As this plugin cannot own any items, it doesn't provide tooltip either
        return ""

    def setDisplayVisibility(self, itemID, visible):
        pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
        pluginHandlerSingleton.pluginByName("Default").setDisplayVisibility(itemID, visible)

    def getDisplayVisibility(self, itemID):
        pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
        return pluginHandlerSingleton.pluginByName("Default").getDisplayVisibility(itemID)

    def __onChartsShortcutClicked(self):
        pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
        currentItemID = pluginHandlerSingleton.currentItem()
        if not currentItemID:
            logging.error("Invalid current item")
            return

        # Find the node related to the current item ID
        subjectHierarchyNode = pluginHandlerSingleton.subjectHierarchyNode()
        node = subjectHierarchyNode.GetItemDataNode(currentItemID)

        module = "Charts"

        # Get module's widget
        widget = slicer.util.getModuleWidget(module)

        # Apply node selection in the module's widget
        widget.setSelectedNode(node)

        # Change module
        slicer.util.selectModule(module)

    def extract_volumes_from_sequence(self, node=None):
        pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
        subjectHierarchyNode = pluginHandlerSingleton.subjectHierarchyNode()
        if not node:
            itemID = pluginHandlerSingleton.currentItem()
            node = subjectHierarchyNode.GetItemDataNode(itemID)
        browser_node = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(node)
        sequence_node = browser_node.GetSequenceNode(node)

        name = slicer.mrmlScene.GenerateUniqueName(node.GetName())
        folder_dir = subjectHierarchyNode.CreateFolderItem(subjectHierarchyNode.GetSceneItemID(), name)

        if isinstance(node, slicer.vtkMRMLLabelMapVolumeNode):
            color_node = slicer.mrmlScene.CopyNode(node.GetDisplayNode().GetColorNode())

        for item in range(sequence_node.GetNumberOfDataNodes()):
            if isinstance(node, slicer.vtkMRMLLabelMapVolumeNode):
                new_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
                slicer.vtkSlicerVolumesLogic().CreateLabelVolumeFromVolume(
                    slicer.mrmlScene, new_node, sequence_node.GetNthDataNode(item)
                )
                new_node.CreateDefaultDisplayNodes()
                new_node.GetDisplayNode().SetAndObserveColorNodeID(color_node.GetID())
            else:
                new_node = slicer.mrmlScene.CopyNode(sequence_node.GetNthDataNode(item))
            new_node.SetName(f"{name}_r{item}")
            subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(new_node), folder_dir)

    def create_sequence_from_folder(self, folderID=None):
        pluginHandlerSingleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
        subjectHierarchyNode = pluginHandlerSingleton.subjectHierarchyNode()
        if not folderID:
            folderID = pluginHandlerSingleton.currentItem()

        vtk_list = vtk.vtkIdList()
        subjectHierarchyNode.GetItemChildren(folderID, vtk_list)

        sequence_node_list = {}
        enabled_sequence = [
            "vtkMRMLScalarVolumeNode",
            "vtkMRMLLabelMapVolumeNode",
            "vtkMRMLTableNode",
            "vtkMRMLSegmentationNode",
        ]

        for id in (vtk_list.GetId(i) for i in range(vtk_list.GetNumberOfIds())):
            current_node = subjectHierarchyNode.GetItemDataNode(id)
            if current_node is not None and current_node.GetClassName() in enabled_sequence:
                if current_node.GetClassName() in sequence_node_list:
                    sequence_node = sequence_node_list[current_node.GetClassName()]["sequence"]
                else:
                    class_name = current_node.GetClassName().replace("vtkMRML", "").replace("Node", "")
                    sequence_name = slicer.mrmlScene.GenerateUniqueName(
                        f"{subjectHierarchyNode.GetItemName(folderID)}_{class_name}_sequence"
                    )
                    sequence_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceNode", sequence_name)
                    sequence_node.SetIndexUnit("")
                    sequence_node.SetIndexName("Realization")
                    sequence_node_list[current_node.GetClassName()] = {}
                    sequence_node_list[current_node.GetClassName()]["sequence"] = sequence_node

                    browser_name = slicer.mrmlScene.GenerateUniqueName(
                        f"{subjectHierarchyNode.GetItemName(folderID)}_{class_name}_browser"
                    )
                    browser_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSequenceBrowserNode", browser_name)
                    browser_node.SetIndexDisplayFormat("%.0f")
                    sequence_node_list[current_node.GetClassName()]["browser"] = browser_node

                    volume_node = slicer.mrmlScene.CopyNode(current_node)
                    volume_name = slicer.mrmlScene.GenerateUniqueName(
                        f"{subjectHierarchyNode.GetItemName(folderID)}_{class_name}_proxy"
                    )
                    volume_node.SetName(volume_name)
                    if isinstance(current_node, slicer.vtkMRMLLabelMapVolumeNode):
                        new_color_node = slicer.mrmlScene.CopyNode(current_node.GetDisplayNode().GetColorNode())
                        volume_node.RemoveAllDisplayNodeIDs()
                        volume_node.CreateDefaultDisplayNodes()
                        volume_node.GetDisplayNode().SetAndObserveColorNodeID(new_color_node.GetID())
                    sequence_node_list[current_node.GetClassName()]["volume"] = volume_node

                index = sequence_node.GetNumberOfDataNodes()
                sequence_node.SetDataNodeAtValue(current_node, str(index))

        for node_type in sequence_node_list:
            sequence_node_list[node_type]["browser"].AddProxyNode(
                sequence_node_list[node_type]["volume"], sequence_node_list[node_type]["sequence"], False
            )
            sequence_node_list[node_type]["browser"].SetAndObserveMasterSequenceNodeID(
                sequence_node_list[node_type]["sequence"].GetID()
            )

    def delete_sequence_nodes(self, node=None):
        plugin_handler_singleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
        subject_hierarchy_node = plugin_handler_singleton.subjectHierarchyNode()
        if not node:
            itemID = plugin_handler_singleton.currentItem()
            node = subject_hierarchy_node.GetItemDataNode(itemID)
        browser_node = slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(node)
        if browser_node:
            sequence_node = browser_node.GetSequenceNode(node)
            slicer.mrmlScene.RemoveNode(sequence_node)
            slicer.mrmlScene.RemoveNode(browser_node)
            if isinstance(node, slicer.vtkMRMLLabelMapVolumeNode):
                slicer.mrmlScene.RemoveNode(node.GetDisplayNode().GetColorNode())
            slicer.mrmlScene.RemoveNode(node)

    def find_and_remove_sequence_nodes(self, items_list):
        subject_hierarchy = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        for item in range(items_list.GetNumberOfIds()):
            node = subject_hierarchy.GetItemDataNode(items_list.GetId(item))
            if (
                type(node) is slicer.vtkMRMLFolderDisplayNode
                or subject_hierarchy.GetItemOwnerPluginName(items_list.GetId(item)) == "Folder"
            ):
                children_list = vtk.vtkIdList()
                subject_hierarchy.GetItemChildren(items_list.GetId(item), children_list)
                self.find_and_remove_sequence_nodes(children_list)
            elif slicer.modules.sequences.logic().GetFirstBrowserNodeForProxyNode(node):
                self.delete_sequence_nodes(node)

    def create_well_model_node(self, node=None):
        plugin_handler_singleton = slicer.qSlicerSubjectHierarchyPluginHandler.instance()
        subject_hierarchy_node = plugin_handler_singleton.subjectHierarchyNode()
        if not node:
            itemID = plugin_handler_singleton.currentItem()
            node = subject_hierarchy_node.GetItemDataNode(itemID)

        with ProgressBarProc() as progressBar:
            progressBar.setMessage("Creating well model")
            create_well_model_from_node(node)
