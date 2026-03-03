import logging

import numpy as np
import slicer
import qt
from CustomResampleScalarVolume import CustomResampleScalarVolumeLogic, ResampleScalarVolumeData
from ltrace.slicer import helpers
from ltrace.slicer_utils import getResourcePath
from typing import Tuple, Union


class ResampleBox(qt.QGroupBox):
    signalResampledNode = qt.Signal(object, str, object)

    def __init__(self, parent=None, title=""):
        super().__init__(f"{title} Resample", parent)
        self.objectName = f"{title} Resample Widget"
        # referenceDimesions of each axis x,y,z
        self.referenceNodeId = None
        self.sourceNodeId = None
        self.referenceDimensions = [0, 0, 0]
        self.referenceSpacing = [0, 0, 0]
        self.gridSpacing = [0, 0, 0]
        self.resampleDimensions = [0, 0, 0]
        self.lockAxis = [0, 0, 0]
        self.setupWidget()
        self.localProgressBar = None
        self.cliNode = None
        self.inputTitle = title
        self.isPreviewOn = False

    def setupWidget(self) -> None:
        resampleLayout = qt.QFormLayout(self)
        resampleLayout.setSizeConstraint(qt.QLayout.SetFixedSize)

        self.dimensionsGroup = []
        labelLayout = qt.QHBoxLayout()
        labelLayout.addWidget(qt.QLabel("Spacing"))
        labelLayout.addWidget(qt.QLabel("Size"))
        labelLayout.addWidget(qt.QLabel("Ratio"))
        resampleLayout.addRow("", labelLayout)
        for dimension in ["X", "Y", "Z"]:
            lineLayout = qt.QHBoxLayout()
            singleGroup = (qt.QDoubleSpinBox(), qt.QLabel("0 px"), qt.QDoubleSpinBox())
            for spinBox in singleGroup:
                spinBox.enabled = False
                lineLayout.addWidget(spinBox)

            self.dimensionsGroup.append(singleGroup)
            resampleLayout.addRow(f"{dimension}:", lineLayout)

        self.previewButton = qt.QPushButton("PREVIEW ")
        self.previewButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "EyeClosed.png"))
        self.previewButton.setLayoutDirection(qt.Qt.RightToLeft)
        self.previewButton.clicked.connect(self.generatePreview)
        resampleLayout.addWidget(self.previewButton)

    def changePreviewButton(self, state) -> None:
        if state:
            self.previewButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "EyeOpen.png"))
        else:
            self.previewButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "EyeClosed.png"))

    def getResampleSpacings(self) -> list:
        return [self.gridSpacing[0], self.gridSpacing[1], self.gridSpacing[2]]

    def getResampleDimensions(self) -> list:
        return [int(dim) for dim in self.resampleDimensions]

    def setLock(self, lock: list) -> None:
        self.lockAxis = lock
        self.updateBoxes()

    def setGrid(self, gridSpacing: np.ndarray) -> None:
        self.gridSpacing = gridSpacing
        self.updateBoxes()

    def calculateImagelogWrapDimensions(self) -> Tuple[np.ndarray, np.ndarray]:
        diameter = self.referenceDimensions[0] * self.referenceSpacing[0] / np.pi
        sides = diameter / self.gridSpacing[0]
        height = self.referenceDimensions[2] * self.referenceSpacing[2] / self.gridSpacing[2]
        return np.ceil(sides), np.ceil(height)

    def setReferenceNode(self, node: Union[slicer.vtkMRMLScalarVolumeNode, slicer.vtkMRMLLabelMapVolumeNode]) -> None:
        if node is not None:
            self.referenceNodeId = node.GetID()
            if isinstance(node, slicer.vtkMRMLSegmentationNode):
                node = helpers.getSourceVolume(node)
            self.referenceDimensions = node.GetImageData().GetDimensions()
            self.referenceSpacing = node.GetSpacing()
        else:
            self.referenceNodeId = None
            self.referenceDimensions = [0, 0, 0]
            self.referenceSpacing = [0, 0, 0]

        self.updateBoxes()

        if self.referenceNodeId is not None:
            self.visible = True
        else:
            self.visible = False

    def setSourceID(self, node: Union[slicer.vtkMRMLScalarVolumeNode, slicer.vtkMRMLLabelMapVolumeNode]) -> None:
        if node is not None:
            self.sourceNodeId = node.GetID()
        else:
            self.sourceNodeId = None

        self.previewButton.setEnabled(self.sourceNodeId is not None)

    def updateBoxes(self) -> None:
        # grid Dim x,y,z
        if 0 not in self.gridSpacing and 0 not in self.referenceSpacing:
            for dim in range(3):
                if self.lockAxis[dim]:
                    spacing = self.referenceSpacing[dim]
                else:
                    spacing = self.gridSpacing[dim]
                self.dimensionsGroup[dim][0].setValue(spacing)

                # Rule from CustomResampleScalarVolume.py and ResampleScalarVolume.cxx
                newDimension = (self.referenceDimensions[dim] * self.referenceSpacing[dim]) / spacing + 0.5
                self.dimensionsGroup[dim][1].text = f"{int(newDimension)} px"
                self.resampleDimensions[dim] = newDimension

                ratio = self.referenceDimensions[dim] / newDimension
                self.dimensionsGroup[dim][2].setValue(ratio)
        else:
            for dim in range(3):
                self.dimensionsGroup[dim][0].setValue(0)
                self.dimensionsGroup[dim][1].text = "0 px"
                self.dimensionsGroup[dim][2].setValue(0)

    def resampleNode(self, progressBar=None):
        node = helpers.tryGetNode(self.referenceNodeId)
        if node is not None:
            if isinstance(node, slicer.vtkMRMLSegmentationNode):
                resampleNode = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLLabelMapVolumeNode", f"{node.GetName()}_LabelMap"
                )
                slicer.modules.segmentations.logic().ExportAllSegmentsToLabelmapNode(
                    node, resampleNode, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY
                )
                helpers.makeNodeTemporary(resampleNode, hide=True, save=False)

            elif isinstance(node, slicer.vtkMRMLLabelMapVolumeNode):
                resampleNode = node
            else:
                logging.error(f"Node type {node.GetClassName()} not allowed for resample")
                return None

            resampleLogic = CustomResampleScalarVolumeLogic(progressBar=progressBar)

            spacings = self.getResampleSpacings()

            for axis in range(3):
                if self.lockAxis[axis]:
                    spacings[axis] = self.referenceSpacing[axis]

            x, y, z = spacings

            resampleData = ResampleScalarVolumeData(
                input=resampleNode,
                outputSuffix="multiscale_resample",
                x=x,
                y=y,
                z=z,
                interpolationType="Nearest Neighbor",
            )

            resampleLogic.run(resampleData)

            self.cliNode = resampleLogic.cliNode

            return resampleLogic.cliNode

    def generatePreview(self) -> None:
        if self.isPreviewOn:
            self.signalResampledNode.emit(None, "", None)
        else:
            if self.localProgressBar is not None:
                if self.sourceNodeId is None:
                    logging.error("No source volume found and preview is not able to be generated")
                    return

                cliNode = self.resampleNode(self.localProgressBar)
                cliNode.AddObserver("ModifiedEvent", self.sendResampleSignal)
            else:
                logging.error("No progress bar found. Module is not properly set up.")

    def sendResampleSignal(self, caller, event) -> None:
        if caller.GetStatusString() == "Completed":
            outputNodeName = caller.GetParameterAsString("OutputVolume")
            node = helpers.tryGetNode(outputNodeName)
            node.CreateDefaultDisplayNodes()

            helpers.makeNodeTemporary(node, hide=True, save=False)

            if node is None:
                logging.error("Node was not resampled correctly and could not be created.")
                return

            self.signalResampledNode.emit(node, self.inputTitle, self)
