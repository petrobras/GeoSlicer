import os
from pathlib import Path
import math
import ctk
import qt
import slicer
import numpy as np
import vtk

from ltrace.slicer import ui
from ltrace.slicer.helpers import clone_volume, copy_display, highlight_error, remove_highlight
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic

try:
    from Test.ImageLogCropVolumeTest import ImageLogCropVolumeTest
except ImportError:
    ImageLogCropVolumeTest = None  # tests not deployed to final version or closed source


class ImageLogCropVolume(LTracePlugin):
    SETTING_KEY = "ImageLogCropVolume"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Image Log Crop"
        self.parent.categories = ["ImageLog", "Multiscale"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.setHelpUrl("ImageLog/Crop.html", NodeEnvironment.IMAGE_LOG)
        self.setHelpUrl("Multiscale/VolumesPreProcessing/Crop.html", NodeEnvironment.MULTISCALE)

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ImageLogCropVolumeWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

        self.origins = np.zeros(3)
        self.spacing = np.zeros(3)
        self.dimensions = np.zeros(3)
        self.zdirection = -1
        self.mmToDepthM = 1000

        self.roiObserver = None

    def setup(self):
        LTracePluginWidget.setup(self)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.collapsed = False
        inputSection.text = "Input"

        self.inputSelector = ui.hierarchyVolumeInput(
            onChange=self.onInputNodeChange,
            hasNone=True,
            nodeTypes=[
                "vtkMRMLScalarVolumeNode",
                "vtkMRMLVectorVolumeNode",
                "vtkMRMLLabelMapVolumeNode",
            ],
            tooltip="Pick a volume node to be cropped",
        )
        self.inputSelector.objectName = "Input combobox"

        self.volumeResolution = qt.QLabel("")
        self.volumeResolution.hide()
        self.volumeResolution.objectName = "Input resolution label"
        self.volumeResolutionLabel = qt.QLabel("Dimensions:")
        self.volumeResolutionLabel.hide()

        inputLayout = qt.QFormLayout(inputSection)
        inputLayout.addRow("Input:", self.inputSelector)
        inputLayout.addRow(self.volumeResolutionLabel, self.volumeResolution)

        # Parameters section
        parametersSection = ctk.ctkCollapsibleButton()
        parametersSection.text = "Parameters"
        parametersSection.collapsed = False
        parametersSection.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        ######
        parametersLayout = qt.QFormLayout(parametersSection)

        self.roiSize = (0, 0, 0)

        self.depthSlider = ctk.ctkRangeWidget()
        # self.depthSlider.prefix = "Depth"
        self.depthSlider.setWindowTitle("Depth range")
        self.depthSlider.objectName = "Depth range"
        self.depthSlider.setRange(0, 0)
        self.depthSlider.setValues(0, 0)
        self.depthSlider.valuesChanged.connect(self.onDepthChange)

        self.indexSlider = ctk.ctkRangeWidget()
        # self.indexSlider.prefix = "Index"
        self.indexSlider.setWindowTitle("Index range")
        self.indexSlider.objectName = "Index range"
        self.indexSlider.setRange(0, 0)
        self.indexSlider.setValues(0, 0)
        self.indexSlider.setDecimals(0)
        self.indexSlider.valuesChanged.connect(self.onIndexChange)

        parametersLayout.addRow("Depth crop range (m):", self.depthSlider)
        parametersLayout.addRow("Index crop range:", self.indexSlider)

        # Output section
        outputSection = ctk.ctkCollapsibleButton()
        outputSection.text = "Output"
        outputSection.collapsed = False

        self.outputPrefix = qt.QLineEdit()
        self.outputPrefix.objectName = "Output Prefix Line Edit"
        self.outputPrefix.textChanged.connect(self.checkApplyButtonState)
        outputFormLayout = qt.QFormLayout(outputSection)
        outputFormLayout.addRow("Output prefix:", self.outputPrefix)

        # Apply button
        self.applyButton = ui.ApplyButton(
            onClick=self.onApplyButtonClicked, tooltip="Crop image using the indexes", enabled=False
        )
        self.applyButton.objectName = "Apply Button"

        # Update layout
        self.layout.addWidget(inputSection)
        self.layout.addWidget(parametersSection)
        self.layout.addWidget(outputSection)
        self.layout.addWidget(self.applyButton)
        self.layout.addStretch(1)

    def onApplyButtonClicked(self, state):
        dims = self.logic.volume.GetImageData().GetDimensions()
        # The +1 below because we interpret the indexSlider as a _closed_ interval
        ijkSize = [dims[0], 1, (self.indexSlider.maximumValue - self.indexSlider.minimumValue) + 1]
        self.logic.apply(
            self.logic.volume,
            ijkSize,
            self.indexSlider.minimumValue,
            self.indexSlider.maximumValue,
            self.depthSlider.minimumValue * self.zdirection * self.mmToDepthM,
            self.depthSlider.maximumValue * self.zdirection * self.mmToDepthM,
            self.outputPrefix.text,
        )

    def checkApplyButtonState(self):
        self.applyButton.enabled = False
        if self.inputSelector.currentNode() is not None and self.outputPrefix.text.replace(" ", "") != "":
            self.applyButton.enabled = True

    def onInputNodeChange(self, itemId):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        self.logic.volume = subjectHierarchyNode.GetItemDataNode(itemId)
        if self.logic.volume:
            # first, refreshing the log view. Otherwise, the volume selected won't show up in the view
            ImageLogDataWidget = slicer.modules.ImageLogDataWidget
            ImageLogDataWidget.logic.refreshViews()

            self.origins = np.array(self.logic.volume.GetOrigin())
            self.spacing = np.array(self.logic.volume.GetSpacing())
            self.dimensions = np.array(self.logic.volume.GetImageData().GetDimensions())
            directions = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
            self.logic.volume.GetIJKToRASDirections(directions)
            self.zdirection = np.sign(np.dot(directions[2], [0, 0, 1]))

            self.volumeResolution.setText(f"{self.dimensions[0]} x {self.dimensions[1]} x {self.dimensions[2]}")
            self.volumeResolution.show()
            self.volumeResolutionLabel.show()

            self.initializeROIFromVolume()

            self.depthSlider.blockSignals(True)
            self.indexSlider.blockSignals(True)
            self.indexSlider.setRange(0, self.dimensions[2] - 1)
            self.indexSlider.setValues(0, self.dimensions[2] - 1)

            self.depthSlider.setRange(
                self.__calculateDepthFromIndex(0) / (self.zdirection * self.mmToDepthM),
                self.__calculateDepthFromIndex(self.dimensions[2] - 1) / (self.zdirection * self.mmToDepthM),
            )
            self.depthSlider.setValues(
                self.__calculateDepthFromIndex(0) / (self.zdirection * self.mmToDepthM),
                self.__calculateDepthFromIndex(self.dimensions[2] - 1) / (self.zdirection * self.mmToDepthM),
            )

            self.outputPrefix.text = f"{self.logic.volume.GetName()}_cropped"

            self.roiObserver = self.logic.roi.AddObserver(
                slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.onRoiModified
            )
            self.depthSlider.blockSignals(False)
            self.indexSlider.blockSignals(False)

            self.logic.roi.SetDisplayVisibility(1)
        else:
            self.depthSlider.setRange(0, 0)
            self.depthSlider.setValues(0, 0)
            self.indexSlider.setRange(0, 0)
            self.indexSlider.setValues(0, 0)

            self.volumeResolution.hide()
            self.volumeResolutionLabel.hide()
            self.outputPrefix.text = ""

            self.logic.roi.SetDisplayVisibility(0)

    def onRoiModified(self, caller, event):
        if self.logic.volume is None:
            return

        if self.roiObserver:
            self.logic.roi.RemoveObserver(self.roiObserver)
            self.roiObserver = None
        else:  # shouldn't be needed, but it seems onRoiModified is being called despite the RemoveObserver call
            return

        depth_bounds = self.logic.getCroppedDepth(self.logic.volume)

        self.depthSlider.setValues(
            depth_bounds[0] / (self.zdirection * self.mmToDepthM), depth_bounds[1] / (self.zdirection * self.mmToDepthM)
        )
        idx_top = self.__calculateIndexFromDepth(depth_bounds[0], True)
        idx_bottom = self.__calculateIndexFromDepth(depth_bounds[1], True)
        self.indexSlider.setValues(idx_top, idx_bottom)

        self.roiObserver = self.logic.roi.AddObserver(slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.onRoiModified)

    def enter(self) -> None:
        super().enter()

        self.inputSelector.setCurrentNode(None)
        self.logic = ImageLogCropVolumeLogic()
        self.logic.roi = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLMarkupsROINode.__name__, "Crop ROI")

        if self.roiObserver is not None:
            return
        #
        # Adusting the appearance of our ROI:
        self.logic.roi.GetDisplayNode().SetFillOpacity(0.5)
        self.logic.roi.GetDisplayNode().PropertiesLabelVisibilityOff()  # hides the name of the ROI from the view
        self.logic.roi.GetDisplayNode().SetRotationHandleVisibility(False)
        self.logic.roi.GetDisplayNode().SetTranslationHandleVisibility(
            False
        )  # The translation handle is too big. We'll keep only the upper and lower scaling handles
        scaleHandleAxes = [False, False, True, False]  # x, y, z, plane
        self.logic.roi.GetDisplayNode().SetScaleHandleVisibility(True)
        self.logic.roi.GetDisplayNode().SetScaleHandleComponentVisibility(scaleHandleAxes)
        self.logic.roi.GetDisplayNode().SetInteractionHandleScale(1)  # 1%
        self.logic.roi.SetDisplayVisibility(0)

    def initializeROIFromVolume(self):
        if self.logic.volume is not None and self.logic.roi is not None:
            volumeExtents = [0] * 6
            self.logic.volume.GetRASBounds(volumeExtents)
            self.logic.roi.SetSize(0, 1, volumeExtents[(2 * 2) + 1] - volumeExtents[2 * 2])  # + 1
            self.logic.roi.SetXYZ(0, 0, (volumeExtents[2 * 2] + volumeExtents[(2 * 2) + 1]) / 2.0)  # + 1)

            self.roiObserver = self.logic.roi.AddObserver(
                slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.onRoiModified
            )

            slicer.util.setSliceViewerLayers(foreground=None, background=self.logic.volume, label=None, fit=True)

    def exit(self):
        if self.roiObserver:
            self.logic.roi.RemoveObserver(self.roiObserver)
        self.roiObserver = None
        slicer.mrmlScene.RemoveNode(self.logic.roi)
        self.logic.roi = None

    def __calculateDepthFromIndex(self, index):
        return self.origins[2] + (self.zdirection * self.spacing[2] * index)

    def __calculateIndexFromDepth(self, depth, isFloor):
        if isFloor:
            return math.floor((depth - self.origins[2]) / (self.zdirection * self.spacing[2]))
        else:
            return math.ceil((depth - self.origins[2]) / (self.zdirection * self.spacing[2]))

    # Updates also the ROI; If focused, updates the depthSlider too; Extends the view range if needed
    def onDepthChange(self, depth_top_M, depth_bottom_M):
        self.depthSlider.blockSignals(True)

        idx_top = self.__calculateIndexFromDepth(depth_top_M * (self.zdirection * self.mmToDepthM), True)
        idx_bottom = self.__calculateIndexFromDepth(depth_bottom_M * (self.zdirection * self.mmToDepthM), True)

        # self.depthSlider.hasFocus() is always False... But checking in the children works it around
        if any(child.hasFocus() for child in self.depthSlider.findChildren(qt.QWidget)):
            self.logic.updateRoi(
                self.inputSelector.currentNode(),
                depth_bottom_M * (self.zdirection * self.mmToDepthM),
                depth_top_M * (self.zdirection * self.mmToDepthM),
            )
            self.indexSlider.setValues(idx_top, idx_bottom)

        # We set again to correct eventual roundings by onRoiModified
        self.depthSlider.setValues(depth_top_M, depth_bottom_M)

        self.depthSlider.blockSignals(False)

        if slicer.modules.ImageLogDataWidget.logic.currentRange:
            cur_range_bottom_top = slicer.modules.ImageLogDataWidget.logic.currentRange

            # Note that we don't apply self.zdirection alongside with self.mmToDepthM, as the range on
            # the ImageLogDataWidget is expressed in positive meters
            if cur_range_bottom_top[0] < depth_bottom_M * self.mmToDepthM:
                slicer.modules.ImageLogDataWidget.logic.onGraphicViewRangeChange(
                    [depth_bottom_M * self.mmToDepthM, cur_range_bottom_top[1]]
                )
            if cur_range_bottom_top[1] > depth_top_M * self.mmToDepthM:
                slicer.modules.ImageLogDataWidget.logic.onGraphicViewRangeChange(
                    [cur_range_bottom_top[0], depth_top_M * self.mmToDepthM]
                )

        self.previousTopBottom_depths = [depth_top_M, depth_bottom_M]

    # Updates also the ROI. And if focused, updates the depthSlider too
    def onIndexChange(self, idx_top, idx_bottom):
        self.indexSlider.blockSignals(True)

        depth_top = self.__calculateDepthFromIndex(idx_top)
        depth_bottom = self.__calculateDepthFromIndex(idx_bottom)

        # self.indexSlider.hasFocus() is always False... But checking in the children works it around
        if any(child.hasFocus() for child in self.indexSlider.findChildren(qt.QWidget)):
            self.depthSlider.setValues(depth_top, depth_bottom)
            self.logic.updateRoi(self.inputSelector.currentNode(), depth_bottom, depth_top)

        # We set again to correct eventual roundings by onRoiModified
        self.indexSlider.setValues(idx_top, idx_bottom)

        self.indexSlider.blockSignals(False)


class ImageLogCropVolumeLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.roi = None

    def apply(
        self,
        volumeNode,
        ijkSize,
        topIndex,
        bottomIndex,
        topDepth,
        bottomDepth,
        name,
    ):
        origins = volumeNode.GetOrigin()
        spacing = volumeNode.GetSpacing()

        nodeArray = slicer.util.arrayFromVolume(volumeNode)
        newNode = clone_volume(volumeNode, name, as_temporary=False)
        slicer.util.updateVolumeFromArray(newNode, nodeArray[int(topIndex) : int(bottomIndex) + 1, :, :])
        newNode.SetOrigin(origins[0], origins[1], topDepth)
        newNode.SetSpacing(spacing)

        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemParent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(volumeNode))
        subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(newNode), itemParent)

        copy_display(volumeNode, newNode)

    def getCroppedDepth(self, volume):
        position = [0] * 3
        radius = [0] * 3
        if self.roi is not None:
            self.roi.GetRadiusXYZ(radius)
            self.roi.GetXYZ(position)

        volumeExtents = [0] * 6
        volume.GetRASBounds(volumeExtents)

        return [
            max(volumeExtents[2 * 2], position[2] - radius[2]),
            min(volumeExtents[(2 * 2) + 1], position[2] + radius[2]),
        ]

    def updateRoi(self, volume, depth_bottom, depth_top):
        if self.roi is not None:
            r = [0, 0, 0]
            self.roi.GetRadiusXYZ(r)
            self.roi.SetRadiusXYZ(r[0], r[1], math.fabs(depth_bottom - depth_top) / 2.0)
            self.roi.SetXYZ(0, 0, (depth_bottom + depth_top) / 2.0)
