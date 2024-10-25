import slicer
import qt
import vtk
from ltrace.slicer.helpers import getCurrentEnvironment
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer.widget.save_netcdf import SaveNetcdfWidget

Env = NodeEnvironment


def _select_tab(tab_widget, label):
    for i in range(tab_widget.count):
        if tab_widget.tabText(i) == label:
            tab_widget.setCurrentIndex(i)
            return tab_widget.widget(i)


def _detect_node_env(node, current_env):
    if node is None:
        return None
    if node.IsA("vtkMRMLTableNode") or node.IsA("vtkMRMLSegmentationNode"):
        if current_env in [Env.CORE, Env.MICRO_CT, Env.IMAGE_LOG, Env.THIN_SECTION]:
            return current_env
    if node.IsA("vtkMRMLVectorVolumeNode"):
        return Env.THIN_SECTION
    if node.IsA("vtkMRMLScalarVolumeNode"):
        array = slicer.util.arrayFromVolume(node)
        if array.shape[1] == 1:
            return Env.IMAGE_LOG
        if current_env == Env.CORE:
            return Env.CORE
        return Env.MICRO_CT
    return None


def _export_node_as(selected_item_id, env):
    if env is None:
        slicer.util.warningDisplay(
            "Can't export selection. Make sure you have selected a single image, or try using the 'Data > Export' tab of your environment."
        )
        return
    select_module = slicer.util.mainWindow().moduleSelector().selectModule
    if env == Env.THIN_SECTION:
        select_module("ThinSectionEnv")
        widget = slicer.modules.ThinSectionEnvWidget

        data_widget = _select_tab(widget.mainTab, "Data")
        export_widget = _select_tab(data_widget, "Export").self()

        export_widget.subjectHierarchyTreeView.setCurrentItem(selected_item_id)
        return
    if env == Env.IMAGE_LOG:
        select_module("ImageLogEnv")
        widget = slicer.modules.ImageLogEnvWidget

        data_widget = _select_tab(widget.mainTab, "Data")
        export_widget = _select_tab(data_widget, "Export").self()
        export_widget.subjectHierarchyTreeView.setCurrentItem(selected_item_id)
        return
    if env == Env.CORE:
        select_module("CoreEnv")
        widget = slicer.modules.CoreEnvWidget

        data_widget = _select_tab(widget.mainTab, "Data")
        export_widget = _select_tab(data_widget, "Export").self()

        export_widget.subjectHierarchyTreeView.setCurrentItem(selected_item_id)
        return
    if env == Env.MICRO_CT:
        select_module("MicroCTEnv")
        widget = slicer.modules.MicroCTEnvWidget

        data_widget = _select_tab(widget.mainTab, "Data")
        export_widget = _select_tab(data_widget, "Export").self()
        return


def _export_folder_as_netcdf(folder_id):
    slicer.util.mainWindow().moduleSelector().selectModule("NetCDFExport")
    ids = vtk.vtkIdList()
    ids.SetNumberOfIds(1)
    ids.SetId(0, folder_id)
    slicer.modules.NetCDFExportWidget.subjectHierarchyTreeView.setCurrentItems(ids)


def _save_folder_as_netcdf(folder_id):
    widget = SaveNetcdfWidget()
    widget.setFolder(folder_id)
    widget.show()


def _export_selected_node():
    sh = slicer.mrmlScene.GetSubjectHierarchyNode()
    plugin_handler = slicer.qSlicerSubjectHierarchyPluginHandler().instance()
    selected_item_id = plugin_handler.currentItem()

    if sh.GetItemOwnerPluginName(selected_item_id) == "Folder":
        if sh.GetItemAttribute(selected_item_id, "netcdf_path"):
            _save_folder_as_netcdf(selected_item_id)
        else:
            _export_folder_as_netcdf(selected_item_id)
        return
    node = sh.GetItemDataNode(selected_item_id)
    detected_env = _detect_node_env(node, getCurrentEnvironment())
    _export_node_as(selected_item_id, detected_env)


def customize_export_to_file():
    plugin_handler = slicer.qSlicerSubjectHierarchyPluginHandler().instance()
    export_plugin = plugin_handler.pluginByName("Export")
    export_action = export_plugin.findChild(qt.QAction)
    export_action.triggered.disconnect()
    export_action.triggered.connect(_export_selected_node)
