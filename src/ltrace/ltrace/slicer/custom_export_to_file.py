import slicer
import qt
import vtk
from ltrace.slicer.helpers import getCurrentEnvironment
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer.widget.save_netcdf import SaveNetcdfWidget

Env = NodeEnvironment


def _detectNodeEnv(node, current_env):
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


def _exportNodeAs(selectedItemId, env):
    if env is None:
        slicer.util.warningDisplay(
            "Can't export selection. Make sure you have selected a single image, or try using the 'Data > Export' tab of your environment."
        )
        return
    selectModule = slicer.modules.AppContextInstance.mainWindow.moduleSelector().selectModule
    if env == Env.THIN_SECTION:
        selectModule("ThinSectionExport")
        widget = slicer.modules.ThinSectionExportWidget
        widget.subjectHierarchyTreeView.setCurrentItem(selectedItemId)
        return
    if env == Env.IMAGE_LOG:
        selectModule("ImageLogExport")
        widget = slicer.modules.ImageLogExportWidget
        widget.subjectHierarchyTreeView.setCurrentItem(selectedItemId)
        return
    if env == Env.CORE:
        selectModule("MulticoreExport")
        widget = slicer.modules.MulticoreExportWidget

        widget.subjectHierarchyTreeView.setCurrentItem(selectedItemId)
        return
    if env == Env.MICRO_CT:
        selectModule("MicroCTExport")
        return


def _export_folder_as_netcdf(folder_id):
    slicer.util.mainWindow().moduleSelector().selectModule("NetCDFExport")
    ids = vtk.vtkIdList()
    ids.SetNumberOfIds(1)
    ids.SetId(0, folder_id)
    slicer.modules.NetCDFExportWidget.subjectHierarchyTreeView.setCurrentItems(ids)


def _save_folder_as_netcdf(folder_id):
    widget = SaveNetcdfWidget()
    widget.show()
    widget.setFolder(folder_id)


def _exportSelectedNode():
    sh = slicer.mrmlScene.GetSubjectHierarchyNode()
    pluginHandler = slicer.qSlicerSubjectHierarchyPluginHandler().instance()
    selectedItemId = pluginHandler.currentItem()

    if sh.GetItemOwnerPluginName(selectedItemId) == "Folder":
        if sh.GetItemAttribute(selectedItemId, "netcdf_path"):
            _save_folder_as_netcdf(selectedItemId)
        else:
            _export_folder_as_netcdf(selectedItemId)
        return

    node = sh.GetItemDataNode(selectedItemId)
    detectedEnv = _detectNodeEnv(node, getCurrentEnvironment())
    _exportNodeAs(selectedItemId, detectedEnv)


def customizeExportToFile():
    pluginHandler = slicer.qSlicerSubjectHierarchyPluginHandler().instance()
    exportPlugin = pluginHandler.pluginByName("Export")
    exportAction = exportPlugin.findChild(qt.QAction)
    exportAction.triggered.disconnect()
    exportAction.triggered.connect(_exportSelectedNode)
