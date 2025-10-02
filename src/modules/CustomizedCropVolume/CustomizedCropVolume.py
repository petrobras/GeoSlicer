import os
from pathlib import Path
from threading import Lock

import ctk
import qt
import slicer
import vtk

from ltrace.slicer import ui
from ltrace.slicer import helpers
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer_utils import *
from ltrace.slicer_utils import getResourcePath
from ltrace.utils.callback import Callback

try:
    from Test.CustomizedCropVolumeTest import CustomizedCropTest
except ImportError:
    CustomizedCropTest = None


class CustomizedCropVolume(LTracePlugin):
    SETTING_KEY = "CustomizedCropVolume"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Crop"
        self.parent.categories = ["Tools", "MicroCT", "Thin Section", "Core", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]

        self.setHelpUrl("Volumes/Crop/Crop.html", NodeEnvironment.MICRO_CT)
        self.setHelpUrl("ThinSection/Crop/Crop.html", NodeEnvironment.THIN_SECTION)
        self.setHelpUrl("Core/Crop.html", NodeEnvironment.CORE)

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class CustomizedCropVolumeWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.roiObserver = None

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = CustomizedCropVolumeLogic()

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        loadFormLayout = qt.QFormLayout(frame)
        loadFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        loadFormLayout.setContentsMargins(0, 0, 0, 0)

        # Input section
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.setText("Input")
        self.inputCollapsibleButton = inputCollapsibleButton
        loadFormLayout.addRow(inputCollapsibleButton)
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.volumeComboBox = slicer.qMRMLNodeComboBox()
        self.volumeComboBox.nodeTypes = [
            "vtkMRMLScalarVolumeNode",
            "vtkMRMLVectorVolumeNode",
            "vtkMRMLLabelMapVolumeNode",
        ]
        self.volumeComboBox.selectNodeUponCreation = False
        self.volumeComboBox.addEnabled = False
        self.volumeComboBox.removeEnabled = False
        self.volumeComboBox.noneEnabled = True
        self.volumeComboBox.showHidden = False
        self.volumeComboBox.showChildNodeTypes = False
        self.volumeComboBox.setMRMLScene(slicer.mrmlScene)
        self.volumeComboBox.setToolTip("Select the image to be cropped.")
        self.volumeComboBox.currentNodeChanged.connect(self.currentNodeChanged)
        inputFormLayout.addRow("Image to be cropped:", self.volumeComboBox)

        inputFormLayout.addRow(" ", None)

        # Parameters section
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.setText("Parameters")
        loadFormLayout.addRow(parametersCollapsibleButton)
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.sizeBoxes = []
        for _ in range(3):
            sizeBox = qt.QSpinBox()
            sizeBox.valueChanged.connect(self.onSizeBoxChanged)
            self.sizeBoxes.append(sizeBox)

        sizeEditLayout = qt.QHBoxLayout()
        sizeEditLayout.addWidget(self.sizeBoxes[0])
        sizeEditLayout.addWidget(qt.QLabel("×"))
        sizeEditLayout.addWidget(self.sizeBoxes[1])
        sizeEditLayout.addWidget(qt.QLabel("×"))
        sizeEditLayout.addWidget(self.sizeBoxes[2])
        sizeEditLayout.addStretch()

        self.sizeEditWidget = qt.QWidget()
        self.sizeEditWidget.setLayout(sizeEditLayout)
        self.roiSize = (0, 0, 0)

        parametersFormLayout.addRow("Crop size:", self.sizeEditWidget)

        parametersFormLayout.addRow(" ", None)

        self.applyCancelButtons = ui.ApplyCancelButtons(
            onApplyClick=self.onCropButtonClicked,
            onCancelClick=self.onCancelButtonClicked,
            applyTooltip="Crop",
            cancelTooltip="Cancel",
            applyText="Crop",
            cancelText="Cancel",
            enabled=True,
        )
        loadFormLayout.addWidget(self.applyCancelButtons)

        statusLabel = qt.QLabel("Status: ")
        self.currentStatusLabel = qt.QLabel("Idle")
        statusHBoxLayout = qt.QHBoxLayout()
        statusHBoxLayout.addStretch(1)
        statusHBoxLayout.addWidget(statusLabel)
        statusHBoxLayout.addWidget(self.currentStatusLabel)
        self.layout.addLayout(statusHBoxLayout)

        self.progressBar = qt.QProgressBar()
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)
        self.layout.addWidget(self.progressBar)
        self.progressBar.hide()

        self.progressMux = Lock()

        self.layout.addStretch()

    def sizeBoxHasFocus(self):
        # Qt does not distinguish value change coming from the user or from the program
        # so we check focus to see if the user is editing the size
        return any([sizeBox.hasFocus() for sizeBox in self.sizeBoxes])

    def currentNodeChanged(self):
        volume = self.volumeComboBox.currentNode()

        if volume and volume.GetImageData() is not None:
            dims = volume.GetImageData().GetDimensions()
            for dim, sizeBox in zip(dims, self.sizeBoxes):
                sizeBox.setRange(0, dim)
                sizeBox.setValue(dim)
            self.sizeEditWidget.setVisible(True)
        else:
            self.sizeEditWidget.setVisible(False)
        self.logic.initializeVolume(volume)

    def onCropButtonClicked(self):
        callback = Callback(
            on_update=lambda message, percent, processEvents=True: self.updateStatus(
                message,
                progress=percent,
                processEvents=processEvents,
            )
        )
        try:
            if self.volumeComboBox.currentNode() is None:
                raise CropInfo("Image to be cropped is required.")
            callback.on_update("Cropping...", 10)
            ijkSize = [sizeBox.value for sizeBox in self.sizeBoxes]
            self.logic.crop(self.volumeComboBox.currentNode(), ijkSize)
        except CropInfo as e:
            slicer.util.infoDisplay(str(e))
            return
        finally:
            callback.on_update("", 100)
        self.volumeComboBox.setCurrentNode(None)

    def onCancelButtonClicked(self):
        self.logic.roi.SetDisplayVisibility(False)
        self.volumeComboBox.setCurrentNode(None)

    def onRoiModified(self, caller, event):
        volume = self.volumeComboBox.currentNode()
        if volume is None:
            return

        size = self.logic.getCroppedSize(volume)

        if self.sizeBoxHasFocus():
            return

        for dimSize, sizeBox in zip(size, self.sizeBoxes):
            sizeBox.setValue(dimSize)

    def onSizeBoxChanged(self, value):
        if not self.sizeBoxHasFocus():
            return
        ijkSize = [sizeBox.value for sizeBox in self.sizeBoxes]
        self.logic.setRoiSizeIjk(self.volumeComboBox.currentNode(), ijkSize)

    def enter(self) -> None:
        super().enter()
        if self.roiObserver is not None:
            return
        self.volumeComboBox.setCurrentNode(None)
        self.logic.roi = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLMarkupsROINode.__name__, "Crop ROI")
        self.logic.roi.SetDisplayVisibility(False)
        self.logic.roi.GetDisplayNode().SetFillOpacity(0.5)
        self.roiObserver = self.logic.roi.AddObserver(
            slicer.vtkMRMLDisplayableNode.DisplayModifiedEvent, self.onRoiModified
        )
        # self.roiObserver = NodeObserver(node=self.logic.roi, parent=None)
        # self.roiObserver.modifiedSignal.connect(self.onRoiModified)

    def exit(self):
        if self.roiObserver:
            self.logic.roi.RemoveObserver(self.roiObserver)
        self.roiObserver = None
        slicer.mrmlScene.RemoveNode(self.logic.roi)
        self.logic.roi = None

    def updateStatus(self, message, progress=None, processEvents=True):
        self.progressBar.show()
        self.currentStatusLabel.text = message
        if progress == -1:
            self.progressBar.setRange(0, 0)
        else:
            self.progressBar.setRange(0, 100)
            self.progressBar.setValue(progress)
            if self.progressBar.value == 100:
                self.progressBar.hide()
                self.currentStatusLabel.text = "Idle"
        if not processEvents:
            return
        if self.progressMux.locked():
            return
        with self.progressMux:
            slicer.app.processEvents()

    def cleanup(self):
        super().cleanup()
        self.exit()


class CustomizedCropVolumeLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.roi = None
        self.cropVolumeNode = None

    def initializeVolume(self, volume):
        if volume is not None and self.roi is not None:
            cropVolumeParameters = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLCropVolumeParametersNode.__name__)
            cropVolumeParameters.SetIsotropicResampling(True)
            cropVolumeParameters.SetInputVolumeNodeID(volume.GetID())
            cropVolumeParameters.SetROINodeID(self.roi.GetID())
            slicer.modules.cropvolume.logic().FitROIToInputVolume(cropVolumeParameters)
            self.roi.SetDisplayVisibility(True)
            slicer.util.setSliceViewerLayers(foreground=None, background=volume, label=None, fit=True)
            self.cropVolumeNode = cropVolumeParameters
        elif self.roi is not None:
            self.roi.SetDisplayVisibility(False)

    def crop(self, volume, ijkSize):
        position_ras = [0] * 3
        if self.roi is not None:
            self.roi.GetXYZ(position_ras)

        ras_to_ijk = vtk.vtkMatrix4x4()
        volume.GetRASToIJKMatrix(ras_to_ijk)
        position_ijk = [0] * 4
        ras_to_ijk.MultiplyPoint(position_ras + [1], position_ijk)

        # IJK integers are on the center of voxels, we add 0.5 since crop ROI is usually on the edge of voxels.
        start = [round(x - size / 2 + 0.5) for x, size in zip(position_ijk[:3], ijkSize)]
        end = [st + size for st, size in zip(start, ijkSize)]

        start = [0 if st < 0 else st for st in start]

        dims = volume.GetImageData().GetDimensions()
        end = [min(d, en) for d, en in zip(dims, end)]

        ijk_to_ras = vtk.vtkMatrix4x4()
        volume.GetIJKToRASMatrix(ijk_to_ras)
        new_origin = [0] * 4
        ijk_to_ras.MultiplyPoint(start + [1], new_origin)

        name = f"{volume.GetName()} - Cropped"
        croppedVolume = slicer.mrmlScene.AddNewNodeByClass(volume.GetClassName(), name)
        croppedVolume.CopyOrientation(volume)

        for attrName in volume.GetAttributeNames():
            croppedVolume.SetAttribute(attrName, volume.GetAttribute(attrName))

        array = slicer.util.arrayFromVolume(volume)
        slices = tuple(slice(st, en) for st, en in zip(start, end))
        croppedArray = array[tuple(reversed(slices))]
        slicer.util.updateVolumeFromArray(croppedVolume, croppedArray)
        croppedVolume.SetOrigin(new_origin[:3])

        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemParent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(volume))
        subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(croppedVolume), itemParent)

        slicer.util.setSliceViewerLayers(background=croppedVolume, fit=True)
        helpers.copy_display(volume, croppedVolume)

        if self.roi is not None:
            self.roi.SetDisplayVisibility(False)
        self.lastCroppedVolume = croppedVolume

    def getCroppedSize(self, volume):
        position = [0] * 3
        radius = [0] * 3
        if self.roi is not None:
            self.roi.GetRadiusXYZ(radius)
            self.roi.GetXYZ(position)

        volumeExtents = [0] * 6
        volume.GetRASBounds(volumeExtents)

        rasExtents = []
        for i in range(3):
            rasExtents += [
                max(volumeExtents[i * 2], position[i] - radius[i]),
                min(volumeExtents[i * 2 + 1], position[i] + radius[i]),
            ]

        rasSize = helpers.bounds2size(rasExtents)
        spacing = volume.GetSpacing()
        ijkSize = tuple(round(rasDim / spacingDim) for rasDim, spacingDim in zip(rasSize, spacing))
        return ijkSize

    def setRoiSizeIjk(self, volume, ijkSize):
        spacing = volume.GetSpacing()
        rasSize = tuple(ijkDim * spacingDim / 2 for ijkDim, spacingDim in zip(ijkSize, spacing))
        if self.roi is not None:
            self.roi.SetRadiusXYZ(rasSize)


class CropInfo(RuntimeError):
    pass
