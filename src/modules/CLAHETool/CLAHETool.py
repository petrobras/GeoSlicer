import ctk
import os
import qt
import slicer

from ltrace.slicer import helpers
from ltrace.slicer.node_attributes import ImageLogDataSelectable
from ltrace.slicer.ui import hierarchyVolumeInput, numericInput, numberParamInt
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, getResourcePath
from ltrace.utils.recursive_progress import RecursiveProgress
from pathlib import Path
from typing import Callable

import numpy as np
import skimage

try:
    from Test.CLAHEToolTest import CLAHEToolTest
except ImportError:
    CLAHEToolTest = None  # tests not deployed to final version or closed source


class CLAHETool(LTracePlugin):
    SETTING_KEY = "CLAHETool"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "CLAHE Tool"
        self.parent.categories = ["Tools", "ImageLog", "Multiscale"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = (
            f"file:///{(getResourcePath('manual') / 'Modules/ImageLog/CLAHETool/CLAHETool.html').as_posix()}"
        )

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class CLAHEToolWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

        self.subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        self.logic = CLAHEToolLogic()

    def setup(self):
        LTracePluginWidget.setup(self)

        # Input section
        inputSection = ctk.ctkCollapsibleButton()
        inputSection.collapsed = False
        inputSection.text = "Input"

        self.inputImage = hierarchyVolumeInput(
            onChange=self.onInputNodeChange,
            nodeTypes=[
                "vtkMRMLVectorVolumeNode",
                "vtkMRMLScalarVolumeNode",
            ],
            hasNone=True,
        )
        self.inputImage.objectName = "inputImage"
        self.inputImage.setToolTip("Select the image to be corrected")

        inputFormLayout = qt.QFormLayout(inputSection)
        inputFormLayout.addRow("Image node:", self.inputImage)

        # Parameters sections
        parametersSection = ctk.ctkCollapsibleButton()
        parametersSection.text = "Parameters"
        parametersSection.collapsed = False

        parametersLayout = qt.QFormLayout(parametersSection)

        self.kernelSizeXInput = numberParamInt(vrange=(2, 2048), value=32, step=2)
        self.kernelSizeXInput.objectName = "kernelSizeX"
        self.kernelSizeXInput.valueChanged.connect(lambda value: self.onNumericIntChanged("kernelSizeX", value))
        self.kernelSizeXInput.setToolTip(
            "Defines the shape of contextual regions used in the algorithm. By default, kernel_size is 1/8 of image height by 1/8 of its width."
        )

        parametersLayout.addRow("Kernel Size X:", self.kernelSizeXInput)

        self.kernelSizeYInput = numberParamInt(vrange=(2, 2048), value=32, step=2)
        self.kernelSizeYInput.objectName = "kernelSizeY"
        self.kernelSizeYInput.valueChanged.connect(lambda value: self.onNumericIntChanged("kernelSizeY", value))
        self.kernelSizeYInput.setToolTip(
            "Defines the shape of contextual regions used in the algorithm. By default, kernel_size is 1/8 of image height by 1/8 of its width."
        )
        parametersLayout.addRow("Kernel Size Y:", self.kernelSizeYInput)

        clipLimitInput = numericInput(value=0.01, onChange=lambda value: self.onNumericChanged("clipLimit", value))
        clipLimitInput.objectName = "clipLimit"
        clipLimitInput.setToolTip("Clipping limit, normalized between 0 and 1 (higher values give more contrast).")
        parametersLayout.addRow("Clip Limit:", clipLimitInput)

        nBinsInput = numberParamInt(vrange=(2, 65536), value=256, step=2)
        nBinsInput.objectName = "nBinsInput"
        nBinsInput.valueChanged.connect(lambda value: self.onNumericIntChanged("nBins", value))
        nBinsInput.setToolTip("Number of bins for histogram ('data range').")
        parametersLayout.addRow("Number of Bins:", nBinsInput)

        # Output section
        outputSection = ctk.ctkCollapsibleButton()
        outputSection.text = "Output"
        outputSection.collapsed = False

        self.outputPrefix = qt.QLineEdit()
        self.outputPrefix.objectName = "outputPrefix"
        self.outputPrefix.setToolTip("Name of the processed image output (in float64 dtype)")
        self.outputPrefix.textChanged.connect(self.checkApplyState)
        outputFormLayout = qt.QFormLayout(outputSection)
        outputFormLayout.addRow("Output prefix:", self.outputPrefix)

        # Apply button
        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.clicked.connect(self.onApplyButtonClicked)
        self.applyButton.objectName = "applyButton"
        self.applyButton.enabled = False
        self.applyButton.setToolTip("Run the azimuth shift correcting tool")

        # Progress Bar
        self.progressBar = qt.QProgressBar()
        self.progressBar.setValue(0)
        self.progressBar.hide()
        self.progressBar.objectName = "progressBar"

        statusLabel = qt.QLabel("Status: ")
        self.currentStatusLabel = qt.QLabel("Idle")
        statusHBoxLayout = qt.QHBoxLayout()
        # statusHBoxLayout.addStretch(1)
        statusHBoxLayout.addWidget(statusLabel)
        statusHBoxLayout.addWidget(self.currentStatusLabel)
        outputFormLayout.addRow(statusHBoxLayout)

        # Update layout
        self.layout.addWidget(inputSection)
        self.layout.addWidget(parametersSection)
        self.layout.addWidget(outputSection)
        self.layout.addWidget(self.applyButton)
        self.layout.addWidget(self.progressBar)
        self.layout.addStretch(1)

    def onApplyButtonClicked(self):
        self.applyButton.enabled = False
        self.progressBar.show()

        self.currentStatusLabel.setStyleSheet("color: white;")
        self.currentStatusLabel.text = "Applying Contrast Limited Adaptive Histogram Equalization (CLAHE)..."
        try:
            self.logic.apply(
                volume_node=self.inputImage.currentNode(),
                kernel_size=(
                    self.logic.model["kernelSizeX"],
                    self.logic.model["kernelSizeY"],
                ),
                clip_limit=self.logic.model["clipLimit"],
                nbins=self.logic.model["nBins"],
                prefix=self.outputPrefix.text,
                callback=self.progress_callback,
            )
        except RuntimeError as e:
            # logging.error(e)
            self.progressBar.setValue(0)
            self.currentStatusLabel.setStyleSheet("color: red;")
            self.currentStatusLabel.text = "Export failed!"
            return

        self.progressBar.setValue(100)
        self.currentStatusLabel.setStyleSheet("color: green;")
        self.currentStatusLabel.text = f"CLAHE completed. Volume {self.outputPrefix.text} created."

        self.applyButton.enabled = True

    def progress_callback(self, progress: float):
        self.progressBar.setValue(progress)

    def onInputNodeChange(self, itemId):
        volumeNode = self.subjectHierarchyNode.GetItemDataNode(itemId)
        if volumeNode:
            self.outputPrefix.text = slicer.mrmlScene.GenerateUniqueName(
                f"{self.inputImage.currentNode().GetName()}_CLAHE"
            )
            kx = volumeNode.GetImageData().GetDimensions()[0] / 8
            if kx:
                self.kernelSizeXInput.setValue(kx)
            else:
                self.kernelSizeXInput.setValue(2)
            ky = volumeNode.GetImageData().GetDimensions()[2] / 8
            if ky:
                self.kernelSizeYInput.setValue(ky)
            else:
                self.kernelSizeYInput.setValue(2)
        else:
            self.outputPrefix.text = ""

    def onNumericChanged(self, key, value):
        self.logic.model[key] = float(value)

    def onNumericIntChanged(self, key, value):
        self.logic.model[key] = int(value)

    def checkApplyState(self):
        if self.inputImage.currentNode() is not None and self.outputPrefix.text.replace(" ", "") != "":
            self.applyButton.enabled = True
        else:
            self.applyButton.enabled = False


def CLAHEModel():
    return dict(
        inputVolume=None,
        kernelSizeX=32,
        kernelSizeY=32,
        clipLimit=0.01,
        nBins=256,
    )


class CLAHEToolLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.model = CLAHEModel()

    def apply(self, volume_node, kernel_size, clip_limit, nbins, prefix, callback: Callable[[float], None]):
        """
        Applies Contrast Limited Adaptive Histogram Equalization (CLAHE) to the given image.

        Parameters:
            acoustic_imagelog (uint16 numpy array): The input acoustic_imagelog.
            kernel_size (int or tuple, optional): Defines the shape of contextual regions used in the algorithm.
            clip_limit (float, optional): Clipping limit, normalized between 0 and 1 (higher values give more contrast).
            nbins (int, optional): Number of gray bins for histogram (“nbins”).

        Returns:
            numpy array: CLAHE applied image.
        """
        callback(0)

        volumeArray = slicer.util.arrayFromVolume(volume_node)
        volumeArray = volumeArray.squeeze()  # remove the dimension with value 1

        # Convert pixels to uint16 type (skimage.exposure.equalize_adapthist expects int type and will convert to 16 bits
        # anyway). Note also that we are in the context of image visualization - our color look up tables have 16 bits...
        image_dyn_uint16 = volumeArray.astype("uint16")

        callback(5)

        # Apply CLAHE
        img_clahe = skimage.exposure.equalize_adapthist(
            image_dyn_uint16, kernel_size=kernel_size, clip_limit=clip_limit, nbins=nbins
        )

        callback(80)

        # Add new volume to the hierarchy
        newVolume = slicer.mrmlScene.AddNewNodeByClass(volume_node.GetClassName(), prefix)
        newVolume.SetName(slicer.mrmlScene.GenerateUniqueName(newVolume.GetName()))
        newVolume.CopyOrientation(volume_node)
        newVolume.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)

        callback(85)

        # Scale the image back to the range
        image_converted = (img_clahe * (volumeArray.max() - volumeArray.min())) + volumeArray.min()

        final_image = np.zeros((volumeArray.shape[0], 1, volumeArray.shape[1]))
        final_image[:, 0, :] = image_converted
        slicer.util.updateVolumeFromArray(newVolume, final_image)

        callback(90)

        helpers.copy_display(volume_node, newVolume)

        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        parent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(volume_node))

        subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(newVolume), parent)

        callback(100)
