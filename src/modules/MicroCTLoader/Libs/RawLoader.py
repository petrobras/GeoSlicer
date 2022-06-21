import os
from pathlib import Path

import ctk
import qt
import slicer
import vtk
import numpy as np
from SegmentEditorEffects import *
from ltrace.slicer import helpers, ui
from ltrace.slicer.node_observer import NodeObserver
from ltrace.slicer_utils import *
from ltrace.units import global_unit_registry as ureg, SLICER_LENGTH_UNIT
from ltrace.utils.ProgressBarProc import ProgressBarProc


class RawLoaderWidget(qt.QFrame):
    def __init__(self, mctLoader):
        super().__init__(None)
        self.nodeType = None
        self.dataType = None
        self.inputFileSelector = mctLoader.pathWidget
        self.mctLoader = mctLoader
        self.setup()

    def setup(self):
        self.logic = RawLoaderLogic()

        frame = self
        formLayout = qt.QFormLayout(frame)
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        formLayout.setContentsMargins(0, 0, 0, 0)

        # Parameters section
        self.parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        self.parametersCollapsibleButton.setText("Parameters")
        parametersFormLayout = qt.QFormLayout(self.parametersCollapsibleButton)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.pixelTypeComboBox = qt.QComboBox()
        self.pixelTypeComboBox.setToolTip("Set the image pixel bit depth.")
        self.pixelTypeComboBox.addItem("8 bit unsigned")
        self.pixelTypeComboBox.addItem("8 bit signed")
        self.pixelTypeComboBox.addItem("16 bit unsigned")
        self.pixelTypeComboBox.addItem("16 bit signed")
        self.pixelTypeComboBox.addItem("32 bit unsigned")
        self.pixelTypeComboBox.addItem("32 bit signed")
        self.pixelTypeComboBox.addItem("float")
        self.pixelTypeComboBox.addItem("double")
        self.pixelTypeComboBox.addItem("24 bit RGB")
        parametersFormLayout.addRow("Pixel type:", self.pixelTypeComboBox)

        self.endiannessComboBox = qt.QComboBox()
        self.endiannessComboBox.setToolTip("Set endianness.")
        self.endiannessComboBox.addItem("Little endian")
        self.endiannessComboBox.addItem("Big endian")
        parametersFormLayout.addRow("Endianness:", self.endiannessComboBox)

        self.imageSkipSliderWidget = ctk.ctkSliderWidget()
        self.imageSkipSliderWidget.setToolTip(
            "If the file has a header, it can be skipped. Set the number of bytes to skip here."
        )
        self.imageSkipSliderWidget.setDecimals(0)
        # self.imageSkipSliderWidget.singleStep = 1
        # self.imageSkipSliderWidget.minimum = 0
        self.imageSkipSliderWidget.maximum = 1000000
        # self.imageSkipSliderWidget.value = 0
        parametersFormLayout.addRow("Header size:", self.imageSkipSliderWidget)

        self.imageSizeXSliderWidget = ui.numberParamInt((1, 99999), value=100, step=1)
        self.imageSizeXSliderWidget.setToolTip("Set the image dimensions on the X axis.")
        parametersFormLayout.addRow("X dimension:", self.imageSizeXSliderWidget)

        self.imageSizeYSliderWidget = ui.numberParamInt((1, 99999), value=100, step=1)
        self.imageSizeYSliderWidget.setToolTip("Set the image dimensions on the Y axis.")
        parametersFormLayout.addRow("Y dimension:", self.imageSizeYSliderWidget)

        self.imageSizeZSliderWidget = ui.numberParamInt((1, 99999), value=100, step=1)
        self.imageSizeZSliderWidget.setToolTip("Set the image dimensions on the Z axis.")
        parametersFormLayout.addRow("Z dimension:", self.imageSizeZSliderWidget)

        self.skipSlicesSliderWidget = ui.numberParamInt((0, 99999), value=0, step=1)
        self.skipSlicesSliderWidget.setToolTip(
            "Skip this many number of slices before adding the first slice to the ouput volume."
        )

        self.imageSpacingXSliderWidget = ui.numberParam((0.01, 99999.0), value=0.01, step=0.01, decimals=2)
        self.imageSpacingXSliderWidget.setToolTip("Size of a voxel along X axis in microns.")
        parametersFormLayout.addRow("X voxel size (μm):", self.imageSpacingXSliderWidget)

        self.imageSpacingYSliderWidget = ui.numberParam((0.01, 99999.0), value=0.01, step=0.01, decimals=2)
        self.imageSpacingYSliderWidget.setToolTip("Size of a voxel along Y axis in microns.")
        parametersFormLayout.addRow("Y voxel size (μm):", self.imageSpacingYSliderWidget)

        self.imageSpacingZSliderWidget = ui.numberParam((0.01, 99999.0), value=0.01, step=0.01, decimals=2)
        self.imageSpacingZSliderWidget.setToolTip("Size of a voxel along Z axis in microns.")
        parametersFormLayout.addRow("Z voxel size (μm):", self.imageSpacingZSliderWidget)

        parametersFormLayout.addRow(" ", None)

        # Output section
        outputCollapsibleButton = ctk.ctkCollapsibleButton()
        outputCollapsibleButton.setText("Output")
        formLayout.addRow(outputCollapsibleButton)
        outputFormLayout = qt.QFormLayout(outputCollapsibleButton)
        outputFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.fitToViewsCheckBox = qt.QCheckBox()
        self.fitToViewsCheckBox.setToolTip("Zoom and pan slice views on update to show the entire output volume.")
        self.fitToViewsCheckBox.setChecked(True)
        outputFormLayout.addRow("Fit output in views:", self.fitToViewsCheckBox)

        self.centerVolumeCheckbox = qt.QCheckBox()
        outputFormLayout.addRow("Center volume:", self.centerVolumeCheckbox)

        self.createEditableSegmentationNodeCheckBox = qt.QCheckBox()
        self.createEditableSegmentationNodeCheckBox.setToolTip(
            "Zoom and pan slice views on update to show the entire output volume."
        )
        self.createEditableSegmentationNodeLabel = qt.QLabel("Create editable segmentation:")
        outputFormLayout.addRow(self.createEditableSegmentationNodeLabel, self.createEditableSegmentationNodeCheckBox)
        self.__enableCreateEditableSegmentationNodeOption(False)
        self.createEditableSegmentationNodeCheckBox.setChecked(True)

        self.outputVolumeName = qt.QLineEdit()
        outputFormLayout.addRow("Output volume name:", self.outputVolumeName)

        outputFormLayout.addRow(" ", None)

        self.updateButton = ctk.ctkCheckablePushButton()
        self.updateButton.setText("Load")
        self.updateButton.setMinimumHeight(40)
        self.updateButton.setToolTip("Load view.")
        self.updateButton.checkState = qt.Qt.Unchecked
        self.updateButton.setEnabled(False)
        formLayout.addRow(self.updateButton)

        self.errorLabel = qt.QLabel("")
        self.errorLabel.setSizePolicy(qt.QSizePolicy.MinimumExpanding, qt.QSizePolicy.Minimum)
        self.errorLabel.setStyleSheet("color: red; font-size: 14px; font-weight: bold")
        self.errorLabel.setFixedHeight(25)
        formLayout.addRow(self.errorLabel)

        # connections
        self.endiannessComboBox.connect("currentIndexChanged(int)", self.onImageSizeChanged)
        self.imageSkipSliderWidget.connect("valueChanged(double)", self.onImageSizeChanged)
        self.imageSizeXSliderWidget.connect("valueChanged(double)", self.onImageSizeChanged)
        self.imageSizeYSliderWidget.connect("valueChanged(double)", self.onImageSizeChanged)
        self.imageSizeZSliderWidget.connect("valueChanged(double)", self.onImageSizeChanged)
        self.skipSlicesSliderWidget.connect("valueChanged(double)", self.onImageSizeChanged)
        self.imageSpacingXSliderWidget.connect("valueChanged(double)", self.onImageSizeChanged)
        self.imageSpacingYSliderWidget.connect("valueChanged(double)", self.onImageSizeChanged)
        self.imageSpacingZSliderWidget.connect("valueChanged(double)", self.onImageSizeChanged)
        self.pixelTypeComboBox.connect("currentIndexChanged(int)", self.onImageSizeChanged)
        self.fitToViewsCheckBox.connect("toggled(bool)", self.onFitToViewsCheckboxClicked)
        self.updateButton.connect("clicked()", self.onUpdateButtonClicked)
        self.updateButton.connect("checkBoxToggled(bool)", self.onUpdateCheckboxClicked)

        self.loadParametersFromSettings()

    def exit(self):
        # disable auto-update when exiting the module to prevent accidental
        # updates of other volumes (when the current output volume is deleted)
        self.updateButton.checkState = qt.Qt.Unchecked

    def onCurrentPathChanged(self, path):
        stem = Path(path).stem
        self.fillInterfaceParametersFromFileName(stem)
        if self.updateButton.checkState == qt.Qt.Checked:
            self.onUpdate()
            self.showOutputVolume()

    def __enableCreateEditableSegmentationNodeOption(self, state):
        self.createEditableSegmentationNodeCheckBox.setVisible(state)
        self.createEditableSegmentationNodeCheckBox.setChecked(state)
        self.createEditableSegmentationNodeLabel.setVisible(state)

    def __shouldCreateEditableSegmentationNode(self):
        return (
            self.createEditableSegmentationNodeCheckBox.isChecked()
            and self.nodeType is not None
            and self.nodeType == "vtkMRMLLabelMapVolumeNode"
        )

    def fillInterfaceParametersFromFileName(self, fileName):
        self.logic.currentNodeId = None
        volumeName = fileName
        self.nodeType = "vtkMRMLScalarVolumeNode"
        pixelTypeIndex, x, y, z, spacing = [None] * 5

        try:
            fileNameParts = fileName.split("_")
            if len(fileNameParts) == 9:
                volumeName = "_".join(fileNameParts[:4])
                self.dataType = fileNameParts[4]
                if any(map((lambda d: d in self.dataType), ["BIN", "BIW", "LABEL", "BASINS"])):
                    pixelTypeIndex = 0
                    self.nodeType = "vtkMRMLLabelMapVolumeNode"
                elif "MANGO" in self.dataType:  # [1.5, 101.5]
                    pixelTypeIndex = 0
                    self.nodeType = "vtkMRMLScalarVolumeNode"
                elif "CT" in self.dataType or "PSD" in self.dataType or "MICP" in self.dataType:
                    pixelTypeIndex = 2
                    self.nodeType = "vtkMRMLScalarVolumeNode"
                elif "POR" in self.dataType or "FLOAT" in self.dataType:
                    pixelTypeIndex = 6
                    self.nodeType = "vtkMRMLScalarVolumeNode"
                else:
                    raise RuntimeError("Data type not detected.")
                x, y, z, spacing = [fileNameParts[i] for i in range(5, len(fileNameParts))]
                x, y, z = int(x), int(y), int(z)
                spacing = ureg.Quantity(spacing.lstrip("0")).m_as("micrometer")
        except:
            pass  # if there is any problem resolving the filename string

        if pixelTypeIndex is not None and x is not None and y is not None and z is not None and spacing is not None:
            self.pixelTypeComboBox.setCurrentIndex(pixelTypeIndex)
            self.imageSizeXSliderWidget.value = int(x)
            self.imageSizeYSliderWidget.value = int(y)
            self.imageSizeZSliderWidget.value = int(z)
            self.imageSpacingXSliderWidget.value = spacing
            self.imageSpacingYSliderWidget.value = spacing
            self.imageSpacingZSliderWidget.value = spacing

        self.__enableCreateEditableSegmentationNodeOption(self.nodeType == "vtkMRMLLabelMapVolumeNode")
        self.mctLoader.enableProcessing(self.nodeType != "vtkMRMLLabelMapVolumeNode")
        self.outputVolumeName.setText(slicer.mrmlScene.GenerateUniqueName(volumeName))
        self.updateButton.setEnabled(True)

    def showOutputVolume(self):
        selectedVolumeNode = helpers.tryGetNode(self.logic.currentNodeId)
        if selectedVolumeNode:
            if selectedVolumeNode.IsA(slicer.vtkMRMLSegmentationNode.__name__):
                # Poking the manual segmentation combobox to update the reference volume
                segmenterWidget = slicer.modules.MicroCTEnvWidget.segmentationEnv.self().segmentEditorWidget.self()
                segmenterWidget.segmentationNodeComboBox.setMRMLScene(None)
                segmenterWidget.segmentationNodeComboBox.setMRMLScene(slicer.mrmlScene)

                # Fitting to the output segmentation and labelmap
                fit = self.fitToViewsCheckBox.checked
                referenceVolumeNodeId = selectedVolumeNode.GetAttribute("ReferenceVolumeNode")
                node = slicer.util.getNode(referenceVolumeNodeId)
                if node is not None:
                    slicer.util.setSliceViewerLayers(label=node, fit=fit)

            else:
                fit = self.fitToViewsCheckBox.checked
                slicer.util.setSliceViewerLayers(background=selectedVolumeNode, fit=fit)

    def onImageSizeChanged(self, value):
        if self.updateButton.checkState == qt.Qt.Checked:
            self.onUpdate()
            self.showOutputVolume()

    def saveParametersToSettings(self):
        settings = qt.QSettings()
        settings.setValue("RawImageGuess/pixelType", self.pixelTypeComboBox.currentText)
        settings.setValue("RawImageGuess/endianness", self.endiannessComboBox.currentText)
        settings.setValue("RawImageGuess/headerSize", self.imageSkipSliderWidget.value)
        settings.setValue("RawImageGuess/sizeX", self.imageSizeXSliderWidget.value)
        settings.setValue("RawImageGuess/sizeY", self.imageSizeYSliderWidget.value)
        settings.setValue("RawImageGuess/sizeZ", self.imageSizeZSliderWidget.value)
        settings.setValue("RawImageGuess/skipSlices", self.skipSlicesSliderWidget.value)
        settings.setValue("RawImageGuess/spacingX", self.imageSpacingXSliderWidget.value)
        settings.setValue("RawImageGuess/spacingY", self.imageSpacingYSliderWidget.value)
        settings.setValue("RawImageGuess/spacingZ", self.imageSpacingZSliderWidget.value)
        settings.setValue("RawImageGuess/centerVolume", "true" if self.centerVolumeCheckbox.checked else "false")

    def loadParametersFromSettings(self):
        settings = qt.QSettings()
        self.pixelTypeComboBox.currentText = settings.value("RawImageGuess/pixelType")
        self.endiannessComboBox.currentText = settings.value("RawImageGuess/endianness")
        self.imageSkipSliderWidget.value = int(settings.value("RawImageGuess/headerSize", 0))
        self.imageSizeXSliderWidget.value = int(settings.value("RawImageGuess/sizeX", 200))
        self.imageSizeYSliderWidget.value = int(settings.value("RawImageGuess/sizeY", 200))
        self.imageSizeZSliderWidget.value = int(settings.value("RawImageGuess/sizeZ", 1))
        self.skipSlicesSliderWidget.value = int(settings.value("RawImageGuess/skipSlices", 0))
        self.imageSpacingXSliderWidget.value = float(settings.value("RawImageGuess/spacingX", 1.0))
        self.imageSpacingYSliderWidget.value = float(settings.value("RawImageGuess/spacingY", 1.0))
        self.imageSpacingZSliderWidget.value = float(settings.value("RawImageGuess/spacingZ", 1.0))
        self.centerVolumeCheckbox.checked = settings.value("RawImageGuess/centerVolume", "true") == "true"

    def onFitToViewsCheckboxClicked(self, enable):
        self.showOutputVolume()

    def onUpdateCheckboxClicked(self, enable):
        if enable:
            self.onUpdate()
            self.showOutputVolume()

    def onUpdateButtonClicked(self):
        remap, will_crop, pcr_min, pcr_max = self.mctLoader.checkNormalization()
        if remap is None:
            return

        with ProgressBarProc() as pb:
            pb.nextStep(0, "Loading image...")
            if self.updateButton.checkState == qt.Qt.Checked:
                # If update button is untoggled then make it unchecked, too
                self.updateButton.checkState = qt.Qt.Unchecked
            self.onUpdate()
            self.showOutputVolume()

            node = helpers.tryGetNode(self.logic.currentNodeId)
            if node:
                callback = lambda msg, progress: pb.nextStep(progress, msg)
                self.mctLoader.normalize(node, remap, will_crop, pcr_min, pcr_max, callback=callback)

    def onUpdate(self):
        if not self.updateButton.enabled:
            return
        if not self.inputFileSelector.path:
            return

        if self.__shouldCreateEditableSegmentationNode():
            nodeType = "vtkMRMLSegmentationNode"
            outputName = self.outputVolumeName.text + "_seg"
        else:
            nodeType = self.nodeType
            outputName = self.outputVolumeName.text

        node = helpers.tryGetNode(self.logic.currentNodeId)
        if node is None or not node.IsA(nodeType):
            node = slicer.mrmlScene.AddNewNodeByClass(nodeType, outputName)
            self.logic.currentNodeId = node.GetID()
            self.logic.configureNodeMetadata(node)

        self.saveParametersToSettings()
        try:
            self.logic.updateImage(
                self.logic.currentNodeId,
                self.inputFileSelector.path,
                self.pixelTypeComboBox.currentText,
                self.endiannessComboBox.currentText,
                int(self.imageSizeXSliderWidget.value),
                int(self.imageSizeYSliderWidget.value),
                int(self.imageSizeZSliderWidget.value),
                int(self.imageSkipSliderWidget.value),
                int(self.skipSlicesSliderWidget.value),
                (float(self.imageSpacingXSliderWidget.value) * ureg.micrometer).m_as(SLICER_LENGTH_UNIT),
                (float(self.imageSpacingYSliderWidget.value) * ureg.micrometer).m_as(SLICER_LENGTH_UNIT),
                (float(self.imageSpacingZSliderWidget.value) * ureg.micrometer).m_as(SLICER_LENGTH_UNIT),
                self.centerVolumeCheckbox.checked,
                self.dataType,
            )
            self.errorLabel.setText("")
        except Exception as e:
            self.errorLabel.setText(str(e))


class RawLoaderLogic:
    def __init__(self):
        self.reader = vtk.vtkImageReader2()
        self._currentNodeId = None
        self._currentNodeObserver = None
        self.ROOT_DATASET_DIRECTORY_NAME = "Micro CT"

        # The first LabelMapVolumeNode always has a displayNode with old Slicer names for the segments
        # This serves to circumvent that and make newly created LabelMapVolumeNodes work as intended
        labelMapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.mrmlScene.RemoveNode(labelMapVolumeNode)

    def newImage(self):
        # If a new image is selected then we create an independent reader
        # (to prevent overwriting previous volumes with updateImage).
        # We do not create a new reader on each updateImage to improve performance
        # (avoid reallocation of the image).
        self.reader = vtk.vtkImageReader2()

    def updateImage(
        self,
        outputVolumeNodeId,
        imageFilePath,
        pixelTypeString,
        endiannessString,
        sizeX,
        sizeY,
        sizeZ,
        headerSize,
        skipSlices,
        spacingX,
        spacingY,
        spacingZ,
        centerVolume,
        dataType=None,
    ):
        """
        Reads image into output volume
        """
        outputVolumeNode = helpers.tryGetNode(outputVolumeNodeId)
        scalarType, numberOfComponents = RawLoaderLogic.scalarTypeComponentFromString(pixelTypeString)

        if endiannessString == "Little endian":
            scalarType = "<" + scalarType
        else:
            scalarType = ">" + scalarType

        if numberOfComponents == 1:
            arrayShape = (sizeZ, sizeY, sizeX)
        else:
            arrayShape = (sizeZ, sizeY, sizeX, numberOfComponents)

        count = sizeX * sizeY * sizeZ * numberOfComponents
        message = ""
        fsize = 0
        try:
            fsize = os.path.getsize(imageFilePath)
        except:
            raise RuntimeError("File not accessible")

        try:
            if outputVolumeNode.IsA(slicer.vtkMRMLLabelMapVolumeNode.__name__):
                self.__updateLabelMapVolumeNodeImage(
                    outputVolumeNode,
                    imageFilePath,
                    scalarType,
                    headerSize,
                    count,
                    arrayShape,
                    spacingX,
                    spacingY,
                    spacingZ,
                    centerVolume,
                    dataType,
                )
            elif outputVolumeNode.IsA(slicer.vtkMRMLSegmentationNode.__name__):
                self.__updateSegmentationNodeImage(
                    outputVolumeNode,
                    imageFilePath,
                    scalarType,
                    headerSize,
                    count,
                    arrayShape,
                    spacingX,
                    spacingY,
                    spacingZ,
                    centerVolume,
                    dataType,
                )
            elif outputVolumeNode.IsA(slicer.vtkMRMLScalarVolumeNode.__name__):
                self.__updateScalarVolumeNodeImage(
                    outputVolumeNode,
                    imageFilePath,
                    scalarType,
                    headerSize,
                    count,
                    arrayShape,
                    spacingX,
                    spacingY,
                    spacingZ,
                    centerVolume,
                )
            else:
                raise NotImplementedError(f"Unable to update image: unexpected node type {type(outputVolumeNode)}")

        except ValueError:
            raise RuntimeError("Wrong array size. Please try another set of dimensions.")
        if fsize > count * RawLoaderLogic.scalarBytesFromString(pixelTypeString):
            raise RuntimeError("File size bigger than the selected dimensions. There is still data on disk to be read")

    @staticmethod
    def __centerVolume(node):
        transformAdded = node.AddCenteringTransform()
        if transformAdded:
            node.HardenTransform()
            slicer.mrmlScene.RemoveNode(slicer.util.getNode(node.GetName() + " centering transform"))

    def __updateLabelMapVolumeNodeImage(
        self,
        outputVolumeNode,
        imageFilePath,
        scalarType,
        headerSize,
        count,
        arrayShape,
        spacingX,
        spacingY,
        spacingZ,
        centerVolume,
        dataType,
    ):
        array = np.fromfile(imageFilePath, dtype=scalarType, offset=headerSize, count=count)
        array = array.reshape(arrayShape)

        array = helpers.numberArrayToLabelArray(array)
        slicer.util.updateVolumeFromArray(outputVolumeNode, array)
        ijkToRas = vtk.vtkMatrix4x4()

        # Default Slicer orientation flips X and Y axes
        ijkToRas.SetElement(0, 0, -spacingX)
        ijkToRas.SetElement(1, 1, -spacingY)
        ijkToRas.SetElement(2, 2, spacingZ)
        outputVolumeNode.SetIJKToRASMatrix(ijkToRas)
        outputVolumeNode.Modified()

        # To force recalculation of auto window level
        displayNode = outputVolumeNode.GetDisplayNode()
        if displayNode is None:
            outputVolumeNode.CreateDefaultDisplayNodes()
            displayNode = outputVolumeNode.GetDisplayNode()

            type_indices = helpers.getTerminologyIndices(dataType)
            if type_indices is None:
                n_labels = array.max()
                colorMapNode = helpers.labelArrayToColorNode(n_labels, outputVolumeNode.GetName())
            else:
                colorMapNode = helpers.getColorMapFromTerminology(outputVolumeNode.GetName(), 2, type_indices)
            displayNode.SetAndObserveColorNodeID(colorMapNode.GetID())

        if centerVolume:
            self.__centerVolume(outputVolumeNode)

    def __updateScalarVolumeNodeImage(
        self,
        outputVolumeNode,
        imageFilePath,
        scalarType,
        headerSize,
        count,
        arrayShape,
        spacingX,
        spacingY,
        spacingZ,
        centerVolume,
    ):
        array = np.fromfile(imageFilePath, dtype=scalarType, offset=headerSize, count=count)
        array = array.reshape(arrayShape)

        slicer.util.updateVolumeFromArray(outputVolumeNode, array)
        ijkToRas = vtk.vtkMatrix4x4()

        # Default Slicer orientation flips X and Y axes
        ijkToRas.SetElement(0, 0, -spacingX)
        ijkToRas.SetElement(1, 1, -spacingY)
        ijkToRas.SetElement(2, 2, spacingZ)
        outputVolumeNode.SetIJKToRASMatrix(ijkToRas)
        outputVolumeNode.Modified()

        # To force recalculation of auto window level
        displayNode = outputVolumeNode.GetDisplayNode()
        if displayNode is None:
            outputVolumeNode.CreateDefaultDisplayNodes()
            displayNode = outputVolumeNode.GetDisplayNode()

        elif isinstance(displayNode, slicer.vtkMRMLScalarVolumeDisplayNode):
            displayNode.AutoWindowLevelOff()
            displayNode.AutoWindowLevelOn()

        if centerVolume:
            self.__centerVolume(outputVolumeNode)

    def __updateSegmentationNodeImage(
        self,
        outputVolumeNode,
        imageFilePath,
        scalarType,
        headerSize,
        count,
        arrayShape,
        spacingX,
        spacingY,
        spacingZ,
        centerVolume,
        dataType,
    ):
        # Avoid repeated segment creation if it segmentation was loaded before
        outputVolumeNode.GetSegmentation().RemoveAllSegments()

        # Remove old reference volume node if exists
        referenceVolumeNodeId = outputVolumeNode.GetAttribute("ReferenceVolumeNode")
        if referenceVolumeNodeId is not None:
            outputVolumeNode.RemoveAttribute("ReferenceVolumeNode")
            node = slicer.util.getNode(referenceVolumeNodeId)
            slicer.mrmlScene.RemoveNode(node)
            del node

        labelMapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        self.__updateLabelMapVolumeNodeImage(
            labelMapVolumeNode,
            imageFilePath,
            scalarType,
            headerSize,
            count,
            arrayShape,
            spacingX,
            spacingY,
            spacingZ,
            centerVolume,
            dataType,
        )
        self.configureNodeMetadata(labelMapVolumeNode)
        helpers.updateSegmentationFromLabelMap(outputVolumeNode, labelMapVolumeNode, includeEmptySegments=True)
        outputVolumeNode.SetReferenceImageGeometryParameterFromVolumeNode(labelMapVolumeNode)
        labelMapVolumeNode.SetName(outputVolumeNode.GetName()[:-4])  # Removes "_seg"
        outputVolumeNode.SetAttribute("ReferenceVolumeNode", labelMapVolumeNode.GetID())

        segmentation = outputVolumeNode.GetSegmentation()
        for i in range(segmentation.GetNumberOfSegments()):
            segment = segmentation.GetNthSegment(i)
            color = segment.GetColor()
            newColor = tuple(min(1, x + 0.5) for x in color)
            segment.SetColor(newColor)

    def generateImageHeader(
        self,
        outputVolumeNode,
        imageFilePath,
        pixelTypeString,
        endiannessString,
        sizeX,
        sizeY,
        sizeZ,
        headerSize,
        skipSlices,
        spacingX,
        spacingY,
        spacingZ,
        numberOfVolumes=1,
    ):
        """
        Reads image into output volume
        """

        # Trim sizeZ and numberOfVolumes to maximum available data size (the reader would refuse loading completely
        # if there is not enough voxel data)
        (scalarType, numberOfComponents) = RawLoaderLogic.scalarTypeComponentFromString(pixelTypeString)
        sliceSize = sizeX * sizeY * vtk.vtkDataArray.GetDataTypeSize(scalarType) * numberOfComponents
        totalHeaderSize = headerSize + skipSlices * sliceSize
        import os

        totalFilesize = os.path.getsize(imageFilePath)
        voxelDataSize = totalFilesize - totalHeaderSize
        maxNumberOfSlices = int(voxelDataSize / sliceSize)
        finalSizeZ = min(sizeZ, maxNumberOfSlices)
        maxNumberOfVolumes = int(voxelDataSize / sliceSize / finalSizeZ)
        finalNumberOfVolumes = min(numberOfVolumes, maxNumberOfVolumes)

        import os

        filename, file_extension = os.path.splitext(imageFilePath)
        if finalNumberOfVolumes > 1:
            nhdrFilename = filename + ".seq.nhdr"
        else:
            nhdrFilename = filename + ".nhdr"

        with open(nhdrFilename, "w") as headerFile:
            headerFile.write("NRRD0004\n")
            headerFile.write("# Complete NRRD file format specification at:\n")
            headerFile.write("# http://teem.sourceforge.net/nrrd/format.html\n")

            if scalarType == vtk.VTK_UNSIGNED_CHAR:
                typeStr = "uchar"
            elif scalarType == vtk.VTK_SIGNED_CHAR:
                typeStr = "signed char"
            elif scalarType == vtk.VTK_UNSIGNED_SHORT:
                typeStr = "ushort"
            elif scalarType == vtk.VTK_SHORT:
                typeStr = "short"
            elif scalarType == vtk.VTK_UNSIGNED_INT:
                typeStr = "uint"
            elif scalarType == vtk.VTK_INT:
                typeStr = "int"
            elif scalarType == vtk.VTK_FLOAT:
                typeStr = "float"
            elif scalarType == vtk.VTK_DOUBLE:
                typeStr = "double"
            else:
                raise ValueError("Unknown scalar type")
            headerFile.write("type: {0}\n".format(typeStr))

            # Determine dimension, sizes, and kinds (dependent of number of components and volumes)
            dimension = 3
            sizesStr = "{0} {1} {2}".format(sizeX, sizeY, finalSizeZ)
            spaceDirectionsStr = "({0}, 0.0, 0.0) (0.0, {1}, 0.0) (0.0, 0.0, {2})".format(spacingX, spacingY, spacingZ)
            kindsStr = "domain domain domain"
            if numberOfComponents > 1:
                dimension += 1
                sizesStr = "{0} ".format(numberOfComponents) + sizesStr
                spaceDirectionsStr = "none " + spaceDirectionsStr
                kindsStr = "vector " + kindsStr
            if finalNumberOfVolumes > 1:
                dimension += 1
                sizesStr = sizesStr + " {0}".format(finalNumberOfVolumes)
                spaceDirectionsStr = spaceDirectionsStr + " none"
                kindsStr = kindsStr + " list"

            headerFile.write("dimension: {0}\n".format(dimension))
            headerFile.write("space: left-posterior-superior\n")
            headerFile.write("sizes: {0}\n".format(sizesStr))
            headerFile.write("space directions: {0}\n".format(spaceDirectionsStr))
            headerFile.write("kinds: {0}\n".format(kindsStr))

            if endiannessString == "Little endian":
                headerFile.write("endian: little\n")
            else:
                headerFile.write("endian: big\n")

            headerFile.write("encoding: raw\n")
            headerFile.write("space origin: (0.0, 0.0, 0.0)\n")

            if totalHeaderSize > 0:
                headerFile.write("byte skip: {0}\n".format(totalHeaderSize))
            headerFile.write("data file: {0}\n".format(os.path.basename(imageFilePath)))

        return nhdrFilename

    @staticmethod
    def scalarTypeComponentFromString(scalarTypeStr):
        if scalarTypeStr == "8 bit unsigned":
            return "u1", 1
        elif scalarTypeStr == "8 bit signed":
            return "i1", 1
        elif scalarTypeStr == "16 bit unsigned":
            return "u2", 1
        elif scalarTypeStr == "16 bit signed":
            return "i2", 1
        elif scalarTypeStr == "32 bit unsigned":
            return "u4", 1
        elif scalarTypeStr == "32 bit signed":
            return "i4", 1
        elif scalarTypeStr == "float":
            return "f4", 1
        elif scalarTypeStr == "double":
            return "f8", 1
        elif scalarTypeStr == "24 bit RGB":
            return "B", 3

    @staticmethod
    def scalarBytesFromString(scalarTypeStr):
        if scalarTypeStr == "8 bit unsigned":
            return 1
        elif scalarTypeStr == "8 bit signed":
            return 1
        elif scalarTypeStr == "16 bit unsigned":
            return 2
        elif scalarTypeStr == "16 bit signed":
            return 2
        elif scalarTypeStr == "32 bit unsigned":
            return 4
        elif scalarTypeStr == "32 bit signed":
            return 4
        elif scalarTypeStr == "float":
            return 4
        elif scalarTypeStr == "double":
            return 8
        elif scalarTypeStr == "24 bit RGB":
            return 1

    def configureNodeMetadata(self, node):
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        rootDirID = subjectHierarchyNode.GetItemByName(self.ROOT_DATASET_DIRECTORY_NAME)

        if rootDirID == 0:
            rootDirID = subjectHierarchyNode.CreateFolderItem(
                subjectHierarchyNode.GetSceneItemID(), self.ROOT_DATASET_DIRECTORY_NAME
            )

        subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(node), rootDirID)

    @property
    def currentNode(self):
        return helpers.tryGetNode(self._currentNodeId)

    @currentNode.setter
    def currentNode(self, node):
        self._currentNodeId = node.GetID() if node is not None else None

        if node is None:
            return

        if self._currentNodeObserver is not None:
            self._currentNodeObserver.clear()
            del self._currentNodeObserver

        self._currentNodeObserver = NodeObserver(node, parent=self)
        self._currentNodeObserver.removedSignal.connect(self.onCurrentNodeRemoved)

    def onCurrentNodeRemoved(self):
        self._currentNodeId = None
        self._currentNodeObserver.clear()
        del self._currentNodeObserver
        self._currentNodeObserver = None
