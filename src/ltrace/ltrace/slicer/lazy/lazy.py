from dataclasses import dataclass, asdict
from ltrace.slicer.lazy.protocols.factory import ProtocolFactory
from ltrace.slicer.netcdf import nc_labels_to_color_node
from pathlib import Path
from typing import List
from vtk import VTK_ENCODING_UTF_8

import json
import numpy as np
import os
import slicer
import xarray as xr


_eye_observer_tag = None
_previous_module_name = None  # New variable to track the previous module


def _current_lazy_node_changed(caller, event):
    global _previous_module_name

    sh = slicer.mrmlScene.GetSubjectHierarchyNode()
    node_id = sh.GetAttribute("CurrentLazyNode")
    big_image_widget = slicer.modules.bigimage.widgetRepresentation().self()

    if node_id:
        node = sh.GetItemDataNode(int(node_id))
        loadMfDatasetSection = slicer.modules.BigImageWidget.loadMfDatasetSection

        if node.GetAttribute("pnmremoteworkflow") == "True":
            loadMfDatasetSection.hide()
        else:
            loadMfDatasetSection.show()

        # Capture the current module before switching to Big Image
        current_module = slicer.util.moduleSelector().selectedModule
        if current_module != big_image_widget.moduleName:
            _previous_module_name = current_module

        slicer.util.selectModule(big_image_widget.moduleName)
        big_image_widget.startPreview(node)
    else:
        slicer.modules.BigImageWidget.loadMfDatasetSection.show()
        big_image_widget.stopPreview()

        # Revert back to the previous module if it exists
        if _previous_module_name is not None:
            slicer.util.selectModule(_previous_module_name)
            _previous_module_name = None


def register_eye_event():
    global _eye_observer_tag

    sh_node = slicer.mrmlScene.GetSubjectHierarchyNode()

    # 1. Clean up the previous observer if it exists
    if _eye_observer_tag is not None:
        sh_node.RemoveObserver(_eye_observer_tag)
        _eye_observer_tag = None

    # 2. Add the new observer and save the new tag
    _eye_observer_tag = sh_node.AddObserver("CurrentLazyNodeChanged", _current_lazy_node_changed)


def set_visibility(node, visible):
    sh = slicer.mrmlScene.GetSubjectHierarchyNode()
    lp = slicer.qSlicerSubjectHierarchyPluginHandler().instance().pluginByName("Lazy")
    if lp is None:
        raise RuntimeError("This feature is unavailable in the current version. Please update your GeoSlicer version.")

    node_id = sh.GetItemByDataNode(node)
    lp.setDisplayVisibility(node_id, visible)


@dataclass
class LazyNodeData:
    url: str
    var: str

    def to_data_array(self, *args, **kwargs):
        dataset = load_dataset(self.url, *args, **kwargs)
        return dataset[self.var]

    def to_node(self):
        node = slicer.mrmlScene.CreateNodeByClass("vtkMRMLTextNode")
        node.UnRegister(None)  # to prevent memory leaks
        node.SetName(self.var)
        node.SetEncoding(VTK_ENCODING_UTF_8)
        node.SetText(json.dumps(asdict(self), indent=4))
        node.SetAttribute("LazyNode", "1")
        node.SetForceCreateStorageNode(True)
        slicer.mrmlScene.AddNode(node)

        data_array = self.to_data_array()
        if "labels" in data_array.attrs:
            color_node = nc_labels_to_color_node(data_array.labels, self.var)
            node.SetAttribute("ColorNodeID", color_node.GetID())

        return node

    def get_protocol(self):
        return ProtocolFactory.build(url=self.url)


def data(node):
    return LazyNodeData(**json.loads(node.GetText()))


def load_dataset(url: str, *args, **kwargs) -> xr.Dataset:
    protocolCls = ProtocolFactory.build(url=url)
    return protocolCls.load(*args, **kwargs)


def create_nodes(dataset_name: str, dataset_url: str, *args, **kwargs) -> List[slicer.vtkMRMLTextNode]:
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    folder = shNode.CreateFolderItem(shNode.GetSceneItemID(), dataset_name)

    nodes = []
    dataset = load_dataset(dataset_url, *args, **kwargs)
    for key in dataset.keys():
        data = LazyNodeData(url=dataset_url, var=key)
        node = data.to_node()
        node.SetName(key)
        shNode.CreateItem(folder, node)
        nodes.append(node)

    shNode.SetItemExpanded(folder, False)
    shNode.SetItemExpanded(folder, True)

    return nodes


def get_color_node(node: slicer.vtkMRMLTextNode) -> slicer.vtkMRMLColorTableNode:
    color_node_id = node.GetAttribute("ColorNodeID")
    if color_node_id:
        return slicer.mrmlScene.GetNodeByID(color_node_id)
    return None


def is_lazy_node(node: slicer.vtkMRMLNode) -> bool:
    return node and node.IsA(slicer.vtkMRMLTextNode.__name__) and node.GetAttribute("LazyNode") == "1"


def getParentLazyNode(node: slicer.vtkMRMLNode) -> slicer.vtkMRMLNode:
    if node is None:
        return None

    parentLazyNodeId = node.GetAttribute("ParentLazyNode")
    if not parentLazyNodeId:
        return None

    return slicer.mrmlScene.GetNodeByID(parentLazyNodeId)
