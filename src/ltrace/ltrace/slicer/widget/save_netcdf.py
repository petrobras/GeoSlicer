import qt
import ctk
import vtk
import slicer

from ltrace.slicer import ui
from ltrace.slicer import export, netcdf
from pathlib import Path


EXPORTABLE_TYPES = (
    slicer.vtkMRMLLabelMapVolumeNode,
    slicer.vtkMRMLSegmentationNode,
    slicer.vtkMRMLVectorVolumeNode,
    slicer.vtkMRMLScalarVolumeNode,
)


def getNodesFromFolder(folderId):
    ids = vtk.vtkIdList()
    ids.SetNumberOfIds(1)
    ids.SetId(0, folderId)
    return export.getDataNodes(ids, EXPORTABLE_TYPES)


class SaveNetcdfWidget(qt.QFrame):
    def __init__(self, *args):
        super().__init__(*args)

        self.windowIcon = slicer.modules.AppContextInstance.mainWindow.windowIcon
        self.setWindowTitle("Save")

        self.setMinimumWidth(500)

        layout = qt.QFormLayout(self)

        helpLabel = qt.QLabel(
            """
<p>Save images that are in the selected folder to the original file the folder was imported from.</p>
"""
        )
        helpLabel.setWordWrap(True)
        layout.addRow(helpLabel)

        detailsGroup = ctk.ctkCollapsibleGroupBox()
        detailsGroup.setTitle("More information...")
        detailsGroup.collapsed = True
        detailsLayout = qt.QVBoxLayout(detailsGroup)
        detailsLabel = qt.QLabel(
            """
<h3>How to use</h3>
<ul>
<li>1. Import a NetCDF file. This will create a project folder with all imported images inside it.
<li>2. Using <b>Explorer</b>, drag new images to the project folder.
<li>3. Right-click the folder and choose 'Export to file...'
<li>4. Click <b>Save</b>.
</ul>
<p>If you prefer to export images to a new file instead, use the <b>NetCDF Export</b> module.</p>

<h3>Behavior</h3>
<ul>
<li>Images and attributes that were already in the file will remain (no overwrite or delete).</li>
<li>New images will be added to the file, sampled along the coordinates that were already present in the file.</li>
<li>This operation will <b>modify the file</b>. You may want to make a copy before saving.</li>
</ul>
"""
        )
        detailsLayout.addWidget(detailsLabel)
        layout.addRow(detailsGroup)

        self.folderSelector = ui.hierarchyVolumeInput(
            nodeTypes=EXPORTABLE_TYPES,
            tooltip="All images in this folder that are not yet in the file will be added.",
            allowFolders=True,
        )
        layout.addRow("Folder:", self.folderSelector)

        self.fileLabel = qt.QLabel()
        self.fileLabel.setToolTip(
            "The selected folder was previously imported from this file. New images will be saved to the file. "
            "Existing images and attributes will remain in the file."
        )
        layout.addRow("Save as:", self.fileLabel)

        self.saveButton = qt.QPushButton("Save")
        self.saveButton.setFixedHeight(40)
        self.saveButton.enabled = False
        layout.addRow(" ", None)
        layout.addRow(self.saveButton)

        self.folderSelector.currentItemChanged.connect(self.onItemChanged)
        self.saveButton.clicked.connect(self.onSave)

    def onItemChanged(self, itemId):
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        netcdfPath = sh.GetItemAttribute(itemId, "netcdf_path")
        enabled = netcdfPath != ""
        self.saveButton.enabled = enabled
        self.saveButton.setToolTip(
            "Save folder contents to file" if enabled else "Selected item must be a folder imported from NetCDF file"
        )

        self.fileLabel.text = netcdfPath

    def setFolder(self, folderId):
        self.folderSelector.setCurrentItem(folderId)

    def onSave(self):
        path = Path(self.fileLabel.text)
        folderId = self.folderSelector.currentItem()
        nodes = getNodesFromFolder(folderId)
        netcdf.exportNetcdf(path, nodes, single_coords=True, save_in_place=True)
        self.close()
