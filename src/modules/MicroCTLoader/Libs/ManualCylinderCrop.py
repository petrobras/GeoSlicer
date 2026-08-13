import qt
import slicer
import ctk
import vtk

from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer.widget.status_panel import StatusPanel
import ltrace.algorithms.detect_cups as cups
from ltrace.slicer.helpers import (
    copy_display,
    setVolumeNullValue,
    copy_attributes,
    copy_hierarchy_attributes,
)
from ltrace.slicer import metadata
import json
from ltrace.utils.ProgressBarProc import ProgressBarProc


def create_cylinder_crop(volume, cylinder):
    array = slicer.util.arrayFromVolume(volume)
    rock, null_value = cups.crop_cylinder(array, cylinder)
    rockNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
    setVolumeNullValue(rockNode, null_value)
    rockNode.CreateDefaultDisplayNodes()
    slicer.util.updateVolumeFromArray(rockNode, rock)

    rockNode.SetIJKToRASDirections(-1, 0, 0, 0, -1, 0, 0, 0, 1)
    spacing = volume.GetSpacing()
    rockNode.SetSpacing(*spacing)
    size = rockNode.GetImageData().GetDimensions()
    origin = [size[0] * spacing[0] / 2, size[1] * spacing[1] / 2, size[2] * -spacing[2] / 2]
    rockNode.SetOrigin(*origin)
    slicer.util.setSliceViewerLayers(background=rockNode, fit=True)
    copy_display(volume, rockNode)

    sh = slicer.mrmlScene.GetSubjectHierarchyNode()
    node_id = sh.GetItemByDataNode(volume)
    parent = sh.GetItemParent(node_id)
    rock_id = sh.GetItemByDataNode(rockNode)
    sh.SetItemParent(rock_id, parent)

    float_cylinder = [float(x) for x in cylinder]
    volume.SetAttribute("RockCylinder", json.dumps(float_cylinder))

    """ Should we copy all attributes and references by default? MUSA-150. 
    copy_attributes(volume, rockNode)
    copy_hierarchy_attributes(volume, rockNode)
    metadata.set_node_metadata(volume, "RockCylinder", json.dumps(float_cylinder))
    metadata.copy_metadata(volume, rockNode)
    # (Note that if spacing is changed, keeping the geometryReference may be problematic)
    rockNode.CopyReferences(volume) """
    return rockNode


class ManualCylinderCropWidget(qt.QWidget):
    DEFAULT_INSTRUCTION = "Select a volume to manually crop the rock cylinder."
    CROPPING_INSTRUCTION = "Drag the handles on the view until the box tightly fits the rock cylinder."
    SUCCESS_INSTRUCTION = "Make sure the box tightly fits the rock cylinder, adjust if necessary."
    ERROR_INSTRUCTION = CROPPING_INSTRUCTION

    DEFAULT_CROP_BUTTON_TEXT = "Start adjusting crop"
    CROPPING_CROP_BUTTON_TEXT = "Apply crop"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setUp()

    def setUp(self) -> None:
        self.section = ctk.ctkCollapsibleButton()
        self.section.text = "Manual cylinder crop"
        self.section.collapsed = True
        self.section.flat = True

        formLayout = qt.QFormLayout(self.section)
        formLayout.setVerticalSpacing(10)

        self.instructionLabel = StatusPanel("", defaultStatus=self.DEFAULT_INSTRUCTION)
        self.instructionLabel.statusLabel.setWordWrap(True)
        formLayout.addRow(self.instructionLabel)

        self.volumeInput = hierarchyVolumeInput(
            tooltip="Select the volume to crop", onChange=self.onVolumeChanged, hasNone=True
        )
        formLayout.addRow("Volume to crop:", self.volumeInput)

        self.adjustButton = qt.QPushButton(self.DEFAULT_CROP_BUTTON_TEXT)
        self.adjustButton.setFixedHeight(40)

        self.cancelButton = qt.QPushButton("Cancel crop")
        self.cancelButton.setFixedHeight(40)
        self.cancelButton.visible = False

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.addWidget(self.adjustButton)
        buttonsLayout.addWidget(self.cancelButton)
        buttonsLayout.setSpacing(10)
        formLayout.addRow(buttonsLayout)

        layout = qt.QVBoxLayout()
        layout.addWidget(self.section)
        self.setLayout(layout)

        self.onVolumeChanged(None)
        self.cylinderRoi = None

        self.adjustButton.clicked.connect(self.onAdjustButtonClicked)
        self.cancelButton.clicked.connect(self.onCancelButtonClicked)

    def onVolumeChanged(self, volume):
        self.adjustButton.setEnabled(bool(volume))

    def finishCrop(self):
        slicer.mrmlScene.RemoveNode(self.cylinderRoi)
        self.cylinderRoi = None
        self.cancelButton.visible = False
        self.instructionLabel.unset_instruction()
        self.adjustButton.text = self.DEFAULT_CROP_BUTTON_TEXT
        self.volumeInput.enabled = True

    def onCancelButtonClicked(self):
        self.finishCrop()

    def onAdjustButtonClicked(self):
        volume = self.volumeInput.currentNode()

        if self.cylinderRoi:
            ManualCylinderCropModel.finishCropping(volume, self.cylinderRoi)
            self.finishCrop()
            self.instructionLabel.unset_instruction()
            self.section.collapsed = True
            return

        self.cylinderRoi = ManualCylinderCropModel.startCropping(volume)
        self.instructionLabel.set_instruction(self.CROPPING_INSTRUCTION)
        self.adjustButton.text = self.CROPPING_CROP_BUTTON_TEXT
        self.cancelButton.visible = True
        self.volumeInput.enabled = False


class ManualCylinderCropModel:
    @staticmethod
    def startCropping(volume):
        rasSpacing = volume.GetSpacing()
        cylinderRoi = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsROINode", "Cylinder bounds")
        cylinderRoi.HideFromEditorsOn()
        cylinderRoi.SaveWithSceneOff()
        slicer.util.setSliceViewerLayers(background=volume, fit=True)
        storedCylinder = volume.GetAttribute("RockCylinder")
        if not storedCylinder:
            # Set initial cylinder to the whole volume
            rasBounds = [0, 0, 0, 0, 0, 0]
            volume.GetRASBounds(rasBounds)
            center = [(a + b) / 2 for a, b in zip(rasBounds[::2], rasBounds[1::2])]
            cylinderRoi.SetXYZ(center)
            radius = [(b - a) / 2 for a, b in zip(rasBounds[::2], rasBounds[1::2])]
            cylinderRoi.SetRadiusXYZ(radius)
        else:
            x, y, r, z_min, z_max = json.loads(storedCylinder)

            ijkToRas = vtk.vtkMatrix4x4()
            volume.GetIJKToRASMatrix(ijkToRas)

            # z_max is an exclusive upper bound; center is at the midpoint of the inclusive range
            z_center_k = (z_min + z_max) / 2 - 0.5
            center_ras = [0.0, 0.0, 0.0, 1.0]
            ijkToRas.MultiplyPoint([x - 0.5, y - 0.5, z_center_k, 1.0], center_ras)

            r_ras = r * rasSpacing[0]
            z_half_ras = (z_max - z_min) / 2 * rasSpacing[2]

            center = [center_ras[0], center_ras[1], center_ras[2]]
            radius = [r_ras, r_ras, z_half_ras]
            cylinderRoi.SetXYZ(center)
            cylinderRoi.SetRadiusXYZ(radius)

        return cylinderRoi

    @staticmethod
    def finishCropping(volume: slicer.vtkMRMLNode, cylinderRoi: slicer.vtkMRMLMarkupsROINode) -> None:
        rasSpacing = volume.GetSpacing()

        rasCenter = [0, 0, 0]
        cylinderRoi.GetXYZ(rasCenter)
        rasRadius = [0, 0, 0]
        cylinderRoi.GetRadiusXYZ(rasRadius)

        ijkToRas = vtk.vtkMatrix4x4()
        volume.GetIJKToRASMatrix(ijkToRas)
        rasToIjk = vtk.vtkMatrix4x4()
        vtk.vtkMatrix4x4.Invert(ijkToRas, rasToIjk)

        ijk_center = [0.0, 0.0, 0.0, 1.0]
        rasToIjk.MultiplyPoint([rasCenter[0], rasCenter[1], rasCenter[2], 1.0], ijk_center)
        x = ijk_center[0] + 0.5
        y = ijk_center[1] + 0.5
        z_center_k = ijk_center[2]

        r = rasRadius[0] / rasSpacing[0]
        z_half_k = rasRadius[2] / rasSpacing[2]
        # z_max is an exclusive upper bound; recover by adding 0.5 to account for the
        # center being placed at the midpoint of the inclusive voxel range [z_min, z_max-1]
        z_min = z_center_k - z_half_k + 0.5
        z_max = z_center_k + z_half_k + 0.5

        cylinder = x, y, r, z_min, z_max
        with ProgressBarProc() as pb:
            pb.setMessage("Cropping cylinder...")
            cropped = create_cylinder_crop(volume, cylinder)
        cropped.SetName(volume.GetName() + " - Cylinder")
