import ctk
import numpy as np
import os
import qt
import slicer
import vtk
import xarray as xr
import logging
import traceback

from dataclasses import dataclass
from humanize import naturalsize
from ltrace.slicer import netcdf
from ltrace.slicer.lazy import lazy
from ltrace.slicer.helpers import BlockSignals
from ltrace.slicer.ui import hierarchyVolumeInput
from ltrace.slicer.widget.labels_table_widget import LabelsTableWidget
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.utils.ProgressBarProc import ProgressBarProc
from pathlib import Path
from time import perf_counter
from vtk.util.numpy_support import numpy_to_vtk

# Checks if closed source code is available
try:
    from Test.BigImageTest import BigImageTest
except ImportError:
    BigImageTest = None


class BigImage(LTracePlugin):
    SETTING_KEY = "BigImage"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Large Image Loader (beta)"
        self.parent.categories = ["Tools", "MicroCT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.set_manual_path("Data_loading/load_bigimage.html")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class BigImageWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = BigImageLogic()

    def setup(self):
        LTracePluginWidget.setup(self)

        self.loadMfDatasetSection = ctk.ctkCollapsibleButton()
        self.loadMfDatasetSection.text = "Load Multi-file NetCDF Image"

        loadMfDatasetLayout = qt.QFormLayout(self.loadMfDatasetSection)

        self.inputDirSelector = ctk.ctkDirectoryButton()
        self.inputDirSelector.setMaximumWidth(374)
        self.inputDirSelector.setToolTip("Select the directory containing the NetCDF files")
        savedDirectory = BigImage.get_setting("InputDir", None)
        if savedDirectory is not None:
            self.inputDirSelector.directory = savedDirectory
        loadMfDatasetLayout.addRow("Input directory:", self.inputDirSelector)

        self.loadDatasetButton = qt.QPushButton("Load dataset")
        self.loadDatasetButton.setToolTip(
            "Create a dask array from which individual slices can be loaded from disk. This operation is fast."
        )
        self.loadDatasetButton.clicked.connect(self.onLoadDatasetClicked)
        self.loadDatasetButton.enabled = False
        self.loadDatasetButton.setFixedHeight(30)

        self.inputDirSelector.directoryChanged.connect(self.onInputDirSelected)
        self.onInputDirSelected(self.inputDirSelector.directory)
        loadMfDatasetLayout.addRow(self.loadDatasetButton)

        self.layout.addWidget(self.loadMfDatasetSection)

        self.datasetSection = ctk.ctkCollapsibleButton()
        self.datasetSection.text = "Data"
        datasetLayout = qt.QFormLayout(self.datasetSection)

        self.layout.addWidget(self.datasetSection)

        self.volumeSelector = hierarchyVolumeInput(
            onChange=self.onVolumeSelected,
            nodeTypes=["vtkMRMLTextNode"],
            tooltip="Select the image within the NetCDF dataset to preview.",
        )
        self.volumeSelector.selectorWidget.addNodeAttributeFilter("LazyNode", "1")
        self.volumeSelector.objectName = "Volume Selector"
        datasetLayout.addRow("Image:", self.volumeSelector)

        self.shapeLabel = qt.QLabel("")
        datasetLayout.addRow("Shape (XYZ):", self.shapeLabel)

        self.dtypeLabel = qt.QLabel("")
        datasetLayout.addRow("Data type:", self.dtypeLabel)

        self.networkStatusLabel = qt.QLabel("")
        self.networkStatusLabel.setStyleSheet("QLabel { color: #ff6060; }")
        datasetLayout.addRow(self.networkStatusLabel)

        self.labelsWidget = LabelsTableWidget()
        self.labelsWidget.visible = False
        datasetLayout.addRow(self.labelsWidget)

        self.previewButton = qt.QPushButton("Preview image")
        self.previewButton.setToolTip("Preview slices of the currently selected image.")
        self.previewButton.clicked.connect(self.onPreviewVolume)
        self.previewButton.setFixedHeight(30)
        self.previewButton.enabled = False
        self.previewButton.objectName = "Preview Button"
        datasetLayout.addRow(self.previewButton)

        self.stopPreviewButton = qt.QPushButton("Stop preview")
        self.stopPreviewButton.setToolTip("Stop previewing slices of the currently selected image.")
        self.stopPreviewButton.clicked.connect(self.onStopPreviewVolume)
        self.stopPreviewButton.objectName = "Stop Preview Button"
        datasetLayout.addRow(self.stopPreviewButton)

        self.previewSection = ctk.ctkCollapsibleButton()
        self.previewSection.text = "Slice Preview"
        previewLayout = qt.QFormLayout(self.previewSection)

        self.sliceSliders = []
        for axisName in "ZYX":
            sliceSlider = ctk.ctkSliderWidget()
            sliceSlider.tracking = False
            sliceSlider.singleStep = 1
            sliceSlider.minimum = 0
            sliceSlider.maximum = 0

            sliceSlider.setToolTip(f"Specify {axisName} position in which the slice will be viewed.")
            sliceSlider.decimals = 0

            self.sliceSliders.append(sliceSlider)

        previewLayout.addRow(f"Z:", self.sliceSliders[0])

        yxSection = ctk.ctkCollapsibleButton()
        yxSection.text = "Y and X axes"
        yxSection.setToolTip(
            "View slices on the XZ and YZ planes. This may be slower than the XY plane depending on how the data is stored."
        )
        yxSection.flat = True
        yxSection.collapsed = True

        yxLayout = qt.QFormLayout(yxSection)
        yxLayout.addRow("Y:", self.sliceSliders[1])
        yxLayout.addRow("X:", self.sliceSliders[2])

        previewLayout.addRow(yxSection)

        self.layout.addWidget(self.previewSection)

        self.reduceSection = ctk.ctkCollapsibleButton()
        self.reduceSection.text = "Reduce Image"
        self.reduceSection.setToolTip("Load a reduced version of the image.")

        reduceLayout = qt.QFormLayout(self.reduceSection)

        cropBox = qt.QGroupBox("Crop")
        cropLayout = qt.QFormLayout(cropBox)

        originLayout = qt.QHBoxLayout()
        sizeLayout = qt.QHBoxLayout()
        self.cropOriginSpinBoxes = []
        self.cropSizeSpinBoxes = []
        for axisName in "XYZ":
            originBox = qt.QSpinBox()
            originBox.setToolTip(f"Start coordinate of the crop in the {axisName} axis.")
            originBox.valueChanged.connect(self.onCropSpinBoxChanged)
            self.cropOriginSpinBoxes.append(originBox)

            sizeBox = qt.QSpinBox()
            sizeBox.setToolTip(f"Size of the crop in the {axisName} axis.")
            sizeBox.valueChanged.connect(self.onCropSpinBoxChanged)
            self.cropSizeSpinBoxes.append(sizeBox)

        originLayout.addWidget(self.cropOriginSpinBoxes[0], 1)
        originLayout.addWidget(qt.QLabel("×"))
        originLayout.addWidget(self.cropOriginSpinBoxes[1], 1)
        originLayout.addWidget(qt.QLabel("×"))
        originLayout.addWidget(self.cropOriginSpinBoxes[2], 1)
        originLayout.addStretch(2)

        sizeLayout.addWidget(self.cropSizeSpinBoxes[0], 1)
        sizeLayout.addWidget(qt.QLabel("×"))
        sizeLayout.addWidget(self.cropSizeSpinBoxes[1], 1)
        sizeLayout.addWidget(qt.QLabel("×"))
        sizeLayout.addWidget(self.cropSizeSpinBoxes[2], 1)
        sizeLayout.addStretch(2)

        resetCropButton = qt.QPushButton("Reset crop region")
        resetCropButton.setToolTip("Reset the region of interest to the full image.")
        resetCropButton.clicked.connect(self.onResetCrop)

        cropLayout.addRow("Crop origin:", originLayout)
        cropLayout.addRow("Crop size:", sizeLayout)
        cropLayout.addRow(resetCropButton)

        reduceLayout.addRow(cropBox)
        reduceLayout.addRow(qt.QLabel(""))

        self.downsampleBox = qt.QSpinBox()
        self.downsampleBox.setToolTip("Downsample the image by this factor for each axis (nearest neighbor).")
        self.downsampleBox.minimum = 1
        self.downsampleBox.value = 1
        self.downsampleBox.setFixedWidth(100)
        self.downsampleBox.valueChanged.connect(lambda _: self.updateOutputSizeLabel())

        downsampleBox = qt.QGroupBox("Downsample")
        downsampleLayout = qt.QFormLayout(downsampleBox)

        downsampleLayout.addRow("Downsample factor:", self.downsampleBox)

        reduceLayout.addRow(downsampleBox)
        reduceLayout.addRow(qt.QLabel(""))

        self.typeBox = qt.QGroupBox("Numeric type conversion")
        typeLayout = qt.QFormLayout(self.typeBox)

        self.originalTypeLabel = qt.QLabel("")
        self.originalTypeLabel.setToolTip("Original numeric type of the image.")
        typeLayout.addRow("Original type:", self.originalTypeLabel)

        self.convertedTypeComboBox = qt.QComboBox()
        for typeName in ("uint8", "int8", "uint16", "int16", "uint32", "int32", "float32", "float64"):
            self.convertedTypeComboBox.addItem(typeName)
        self.convertedTypeComboBox.setToolTip("Convert the image to this numeric type.")
        self.convertedTypeComboBox.currentIndexChanged.connect(lambda _: self.updateOutputSizeLabel())
        typeLayout.addRow("Convert to type:", self.convertedTypeComboBox)
        self.remapRangeCheckBox = qt.QCheckBox("Map min and max values to min and max of new type")
        self.remapRangeCheckBox.setToolTip(
            "When enabled, the remapping of values will occur when converting to a new integer type, preserving the dynamic range of the original values. "
            "When disabled, values outside the range of the new type will be clipped, while values within the range will remain unchanged."
        )
        self.remapRangeCheckBox.checked = True

        typeLayout.addRow(self.remapRangeCheckBox)

        reduceLayout.addRow(self.typeBox)
        reduceLayout.addRow(qt.QLabel(""))

        self.layout.addWidget(self.reduceSection)

        self.outputSection = ctk.ctkCollapsibleButton()
        self.outputSection.text = "Output"
        self.outputSection.setToolTip("Output options")
        outputLayout = qt.QFormLayout(self.outputSection)

        self.outputNameEdit = qt.QLineEdit()
        self.outputNameEdit.setToolTip("Name of the reduced image")

        self.outputSizeLabel = qt.QLabel("")
        self.outputSizeLabel.setToolTip("Estimated size the reduced image will take.")
        outputLayout.addRow("Output size:", self.outputSizeLabel)

        loadButton = qt.QPushButton("Load reduced image")
        loadButton.setFixedHeight(40)
        loadButton.clicked.connect(self.onLoadClicked)

        outputLayout.addRow("Output name:", self.outputNameEdit)
        outputLayout.addRow(loadButton)

        self.layout.addWidget(self.outputSection)
        self.layout.addStretch(1)

        self.logic.cropChanged.connect(self.onCropRoiChanged)
        self.restoreWidgets()

        self.stopPreviewObserver = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.StartCloseEvent, lambda *args: self.onStopPreviewVolume()
        )

    def startPreview(self, node):
        self.stopPreview()  # To eliminate artifacts from the previous views
        self.volumeSelector.setCurrentNode(node)
        self.logic.setCurrentLazyNode(node)
        self.updateWidgetsForVolume()

    def stopPreview(self):
        self.logic.clearCurrentVolume()
        self.volumeSelector.enabled = True
        self.restoreWidgets()
        self.onVolumeSelected()

    def onResetCrop(self):
        info = self.logic.getVolumeInfo()
        for originBox, sizeBox, size in zip(self.cropOriginSpinBoxes, self.cropSizeSpinBoxes, info.shape_xyz):
            originBox.maximum = size - 1
            originBox.value = 0
            sizeBox.maximum = size
            sizeBox.value = size

    def restoreWidgets(self):
        self.volumeSelector.enabled = True
        self.volumeSelector.setToolTip("Select the image within the NetCDF dataset to preview.")
        self.dtypeLabel.text = ""
        self.shapeLabel.text = ""
        self.previewButton.visible = True
        self.stopPreviewButton.visible = False

        self.previewSection.visible = False
        self.reduceSection.visible = False
        self.outputSection.visible = False
        self.loadMfDatasetSection.collapsed = False
        for slider in self.sliceSliders:
            slider.valueChanged.disconnect()
        for sliceWidgetName in ("Red", "Green", "Yellow"):
            sliceWidget = slicer.app.layoutManager().sliceWidget(sliceWidgetName)
            sliceController = sliceWidget.sliceController()
            sliceController.setSliceVisible(False)

    def onInputDirSelected(self, directoryPath):
        directoryPath = Path(directoryPath)
        self.loadDatasetButton.enabled = directoryPath.is_dir() and list(Path(directoryPath).glob("*.nc"))

    def onLoadDatasetClicked(self):
        self.logic.loadDatasetFromPath(self.inputDirSelector.directory)

    def onVolumeSelected(self, _=0):
        lazyNode = self.volumeSelector.currentNode()
        networkProblem = False
        exceptionError = ""
        if lazyNode:
            try:
                volumeInfo = self.logic.getVolumeInfo(lazyNode)
                self.networkStatusLabel.setText("")
            except Exception as error:
                networkProblem = True
                exceptionError = error
        if lazyNode is None or networkProblem:
            self.previewButton.enabled = False
            self.shapeLabel.text = ""
            self.dtypeLabel.text = ""
            self.labelsWidget.visible = False
            if networkProblem:
                logging.info(f"{exceptionError}.\n{traceback.format_exc()}")
                self.networkStatusLabel.setText("Please configure a BIAEP account to preview this image.")
                slicer.modules.RemoteServiceInstance.cli.initiateConnectionDialog(keepDialogOpen=True)
            return
        self.previewButton.enabled = True
        self.shapeLabel.text = "×".join(map(str, volumeInfo.shape_xyz))
        self.dtypeLabel.text = str(volumeInfo.dtype)
        if volumeInfo.colorNode:
            self.labelsWidget.visible = True
            self.labelsWidget.set_color_node(volumeInfo.colorNode)
        else:
            self.labelsWidget.visible = False

    def onPreviewVolume(self):
        # This will trigger self.startPreview(node) from the event
        node = self.volumeSelector.currentNode()
        lazy.set_visibility(node, True)

    def onStopPreviewVolume(self):
        # This will trigger self.stopPreview() from the event
        node = self.volumeSelector.currentNode()
        if node:
            lazy.set_visibility(self.volumeSelector.currentNode(), False)
        else:
            # Node has been deleted, so we need to stop the preview manually
            self.stopPreview()

    def updateWidgetsForVolume(self):
        self.onResetCrop()
        info = self.logic.getVolumeInfo()
        for axis, (slider, size) in enumerate(zip(self.sliceSliders, info.shape_zyx)):
            slider.maximum = size - 1
            slider.value = size // 2
            slider.valueChanged.connect(lambda value, axis=axis: self.onSliderValueChanged(axis, value))

        self.previewButton.visible = False
        self.stopPreviewButton.visible = True

        self.previewSection.visible = True
        self.reduceSection.visible = True
        self.outputSection.visible = True
        self.originalTypeLabel.setText(str(info.dtype))
        self.convertedTypeComboBox.setCurrentText(str(info.dtype))
        self.typeBox.visible = info.colorNode is None
        self.outputNameEdit.text = f"{info.name}_reduced"

        self.sliceSliders[0].valueChanged.emit(self.sliceSliders[0].value)
        self.cropOriginSpinBoxes[0].valueChanged.emit(self.cropOriginSpinBoxes[0].value)
        self.volumeSelector.enabled = False
        red_and_3d_layout_id = 100
        slicer.app.layoutManager().setLayout(red_and_3d_layout_id)
        BigImage.set_setting("InputDir", self.inputDirSelector.directory)

    def onLoadClicked(self):
        origin = [int(spinBox.value) for spinBox in self.cropOriginSpinBoxes]
        size = [int(spinBox.value) for spinBox in self.cropSizeSpinBoxes]
        stride = int(self.downsampleBox.value)
        type_ = np.dtype(self.convertedTypeComboBox.currentText)
        remap = self.remapRangeCheckBox.checked

        with ProgressBarProc() as pb:
            pb.setTitle("Loading image to memory")

            # Size will be read by h5pyd
            pb.setMessage(f"Loading image, please wait...")
            pb.sharedDict["total_size"] = self.getOutputSize(afterTypeConversion=False)
            pb._updateSharedMem()
            reducedVolume = self.logic.loadReducedVolume(origin, size, stride, type_, remap)
        reducedVolume.SetName(self.outputNameEdit.text)

    def onSliderValueChanged(self, axis, value):
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            self.logic.updatePreviewVolume(axis, value)
        finally:
            qt.QApplication.restoreOverrideCursor()

    def getOutputSize(self, afterTypeConversion=True):
        if not self.logic.currentLazyNode:
            return 0
        origin = [spinBox.value for spinBox in self.cropOriginSpinBoxes]
        size = [spinBox.value for spinBox in self.cropSizeSpinBoxes]
        volumeInfo = self.logic.getVolumeInfo()
        shape = volumeInfo.shape_xyz
        end = [min(o + s, ss) for o, s, ss in zip(origin, size, shape)]
        realSize = [int(e - o) for o, e in zip(origin, end)]
        if afterTypeConversion:
            outputDtype = np.dtype(self.convertedTypeComboBox.currentText)
        else:
            outputDtype = volumeInfo.dtype
        nVoxels = realSize[0] * realSize[1] * realSize[2] // self.downsampleBox.value**3
        byteSize = outputDtype.itemsize * nVoxels
        return byteSize

    def updateOutputSizeLabel(self):
        self.outputSizeLabel.setText(naturalsize(self.getOutputSize()))

    def onCropSpinBoxChanged(self):
        origin = [spinBox.value for spinBox in self.cropOriginSpinBoxes]
        size = [spinBox.value for spinBox in self.cropSizeSpinBoxes]
        self.logic.updateCropRoi(origin, size)
        self.updateOutputSizeLabel()

    def onCropRoiChanged(self, origin, size):
        for spinBox, o, s in zip(self.cropOriginSpinBoxes, origin, size):
            spinBox.value = o
        for spinBox, s in zip(self.cropSizeSpinBoxes, size):
            spinBox.value = s
        self.updateOutputSizeLabel()

    def cleanup(self):
        super().cleanup()
        slicer.mrmlScene.RemoveObserver(self.stopPreviewObserver)
        self.logic.cropChanged.disconnect()


class VolumeInfo:
    def __init__(self, name, shape, origin, spacing, dtype, colorNode=None):
        self.name = name
        self._shape = np.array(shape)
        self._origin = np.array(origin)
        self._spacing = np.array(spacing)
        self.dtype = dtype
        self.colorNode = colorNode

    @property
    def shape_xyz(self):
        return self._shape[::-1].copy()

    @property
    def shape_zyx(self):
        return self._shape.copy()

    @property
    def spacing_xyz(self):
        return self._spacing[::-1].copy()

    @property
    def spacing_zyx(self):
        return self._spacing.copy()

    @property
    def origin_xyz(self):
        return self._origin[::-1].copy()

    @property
    def origin_zyx(self):
        return self._origin.copy()


INVERT = np.array([-1, -1, 1])


class BigImageLogic(LTracePluginLogic):
    cropChanged = qt.Signal(tuple, tuple)

    def __init__(self):
        LTracePluginLogic.__init__(self)
        self._clearCurrentVolumeAttrs()

    def _clearCurrentVolumeAttrs(self):
        self.currentLazyNode = None
        self.previewArrays = [None] * 3
        self.previewNodes = [None] * 3
        self.roiNode = None
        self.cropRoiNode = None
        self._volumeInfo = None

    def getVolumeInfo(self, lazyNode=None):
        if self._volumeInfo and lazyNode is None:
            return self._volumeInfo
        if lazyNode is None:
            lazyNode = self.currentLazyNode
        lazyData = lazy.data(lazyNode)
        dataArray = lazyData.to_data_array()
        name = lazyData.var
        shape = dataArray.shape
        dtype = dataArray.dtype
        color = lazy.get_color_node(lazyNode)
        origin = netcdf.get_origin(dataArray)[::-1]
        spacing = netcdf.get_spacing(dataArray)[::-1]
        volumeInfo = VolumeInfo(name, shape, origin, spacing, dtype, color)

        if lazyNode is self.currentLazyNode:
            self._volumeInfo = volumeInfo

        return volumeInfo

    def clearCurrentVolume(self):
        for node in self.previewNodes:
            if node:
                slicer.mrmlScene.RemoveNode(node)
        if self.roiNode:
            slicer.mrmlScene.RemoveNode(self.roiNode)
        if self.cropRoiNode:
            slicer.mrmlScene.RemoveNode(self.cropRoiNode)
        self._clearCurrentVolumeAttrs()

        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        sh.SetAttribute("CurrentLazyNode", "")

    @staticmethod
    def loadDatasetFromPath(directoryPath):
        start = perf_counter()
        lazy.create_nodes(Path(directoryPath).stem, f"file://{directoryPath}")
        logging.debug(f"Loaded dataset in {perf_counter() - start:.2f} seconds")

    def setCurrentLazyNode(self, lazyNode):
        if self.currentLazyNode and lazyNode.GetID() == self.currentLazyNode.GetID():
            return
        self.clearCurrentVolume()
        self.currentLazyNode = lazyNode
        self._createRois()
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        nodeId = sh.GetItemByDataNode(lazyNode)
        sh.SetAttribute("CurrentLazyNode", str(nodeId))

    def loadReducedVolume(self, origin_ijk, size_ijk, stride, type_, remap):
        start = perf_counter()
        currentLazyData = lazy.data(self.currentLazyNode)
        dataArray = currentLazyData.to_data_array()
        croppedArray = dataArray[
            tuple(slice(o, o + s, stride) for o, s in zip(reversed(origin_ijk), reversed(size_ijk)))
        ]
        colorNode = lazy.get_color_node(self.currentLazyNode)

        if colorNode:
            type_ = dataArray.dtype

        if type_ != dataArray.dtype:
            typeIsInt = np.issubdtype(type_, np.integer)
            if typeIsInt:
                typeMin = np.iinfo(type_).min
                typeMax = np.iinfo(type_).max
                if remap:
                    typeRange = typeMax - typeMin
                    arrayMin = croppedArray.min()
                    arrayMax = croppedArray.max()
                    arrayRange = arrayMax - arrayMin
                    croppedArray = croppedArray.astype(np.float64)
                    croppedArray -= arrayMin
                    croppedArray /= arrayRange
                    croppedArray = np.clip(croppedArray, 0, 1)
                    croppedArray *= typeRange
                    croppedArray += typeMin
                else:
                    croppedArray = np.clip(croppedArray, typeMin, typeMax)
            croppedArray = croppedArray.astype(type_)

        if type_ == np.int8:
            # Set type explicitly to avoid VTK_CHAR, which is platform dependent
            # and not supported by the GPU ray caster
            arrayType = vtk.VTK_SIGNED_CHAR
        else:
            # Auto detect type (get_vtk_array_type)
            arrayType = None

        vtkArray = numpy_to_vtk(croppedArray.values.ravel(), deep=True, array_type=arrayType)

        img = vtk.vtkImageData()
        img.GetPointData().SetScalars(vtkArray)
        img.SetDimensions(*(tuple(reversed(croppedArray.shape))))

        class_ = "vtkMRMLLabelMapVolumeNode" if colorNode else "vtkMRMLScalarVolumeNode"
        croppedNode = slicer.mrmlScene.AddNewNodeByClass(class_)
        croppedNode.CreateDefaultDisplayNodes()
        croppedNode.SetAndObserveImageData(img)

        volumeInfo = self.getVolumeInfo()

        origin_ras = np.array(origin_ijk) * volumeInfo.spacing_xyz * INVERT + volumeInfo.origin_xyz
        spacing_ras = volumeInfo.spacing_xyz * stride

        croppedNode.SetOrigin(origin_ras)
        croppedNode.SetSpacing(spacing_ras)
        croppedNode.SetIJKToRASDirections(-1, 0, 0, 0, -1, 0, 0, 0, 1)

        if colorNode:
            croppedNode.GetDisplayNode().SetAndObserveColorNodeID(colorNode.GetID())
        slicer.util.setSliceViewerLayers(foreground=None, background=croppedNode, label=None, fit=True)

        conventionalLayoutId = 2
        slicer.app.layoutManager().setLayout(conventionalLayoutId)

        for node in self.previewNodes:
            if node:
                slicer.mrmlScene.RemoveNode(node)
        self.previewNodes = [None] * 3
        croppedNode.SetAttribute("ParentLazyNode", self.currentLazyNode.GetID())
        logging.debug(f"Loaded reduced volume in {perf_counter() - start:.2f} seconds")
        return croppedNode

    def _createRois(self):
        volumeInfo = self.getVolumeInfo()

        roiNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsROINode", "Big Image Extent ROI")
        self.roiNode = roiNode

        offset = volumeInfo.spacing_xyz * -0.5
        size = volumeInfo.spacing_xyz * volumeInfo.shape_xyz
        center = volumeInfo.origin_xyz + (offset + size / 2) * INVERT

        roiNode.SetXYZ(center)
        roiNode.SetRadiusXYZ(size / 2)
        roiNode.SetDisplayVisibility(True)
        roiNode.GetDisplayNode().SetFillOpacity(0)
        roiNode.GetDisplayNode().SetOpacity(0.5)
        roiNode.GetDisplayNode().SetScaleHandleComponentVisibility(False, False, False, False)
        roiNode.GetDisplayNode().SetTranslationHandleComponentVisibility(False, False, False, False)
        roiNode.GetDisplayNode().SetTextScale(0)
        roiNode.SetLocked(True)
        roiNode.HideFromEditorsOn()
        roiNode.SaveWithSceneOff()

        cropRoiNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsROINode", "Big Image Crop ROI")
        self.cropRoiNode = cropRoiNode
        cropRoiNode.SetDisplayVisibility(True)
        cropRoiNode.GetDisplayNode().SetFillOpacity(0)
        cropRoiNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self._onCropRoiModified)
        cropRoiNode.HideFromEditorsOn()
        cropRoiNode.SaveWithSceneOff()

    def _onCropRoiModified(self, caller, event):
        center = [0] * 3
        self.cropRoiNode.GetXYZ(center)
        radius = [0] * 3
        self.cropRoiNode.GetRadiusXYZ(radius)
        center = np.array(center)
        radius = np.array(radius)

        origin = center - radius * INVERT
        size = radius * 2

        volumeInfo = self.getVolumeInfo()
        origin = np.round(((origin - volumeInfo.origin_xyz) / volumeInfo.spacing_xyz - 0.5) * INVERT).astype(int)
        size = np.round(size / volumeInfo.spacing_xyz).astype(int)

        self.cropChanged.emit(origin, size)

    def updateCropRoi(self, origin, size):
        volumeInfo = self.getVolumeInfo()
        origin = np.array(origin)
        size = np.array(size)
        spacing = volumeInfo.spacing_xyz
        origin_ras = (origin - 0.5) * spacing * INVERT + volumeInfo.origin_xyz
        size_ras = size * spacing
        radius_ras = size_ras / 2
        center_ras = origin_ras + radius_ras * INVERT
        with BlockSignals(self):
            self.cropRoiNode.SetXYZ(center_ras)
            self.cropRoiNode.SetRadiusXYZ(radius_ras)

    def _createPreviewVolume(self, axis):
        volumeInfo = self.getVolumeInfo()

        sliceShape = volumeInfo.shape_zyx
        sliceShape[axis] = 1
        sliceShape = tuple(reversed(sliceShape))

        previewArray = np.empty(sliceShape, dtype=volumeInfo.dtype, order="F")
        vtkArray = numpy_to_vtk(previewArray.ravel())

        img = vtk.vtkImageData()
        img.GetPointData().SetScalars(vtkArray)
        img.SetDimensions(*sliceShape)

        colorNode = lazy.get_color_node(self.currentLazyNode)
        class_ = "vtkMRMLLabelMapVolumeNode" if colorNode else "vtkMRMLScalarVolumeNode"
        previewNode = slicer.mrmlScene.AddNewNodeByClass(class_, f"{volumeInfo.name} {'ZYX'[axis]} Slice Preview")
        previewNode.SetAttribute("AutoSliceVisibleOff", "true")
        previewNode.SetAndObserveImageData(img)
        previewNode.CreateDefaultDisplayNodes()
        previewNode.SaveWithSceneOff()
        previewNode.HideFromEditorsOn()

        previewArray = slicer.util.arrayFromVolume(previewNode)

        if colorNode:
            previewNode.GetDisplayNode().SetAndObserveColorNodeID(colorNode.GetID())
        else:
            previewNode.GetDisplayNode().SetAutoWindowLevel(False)

        self.previewArrays[axis] = previewArray
        self.previewNodes[axis] = previewNode

    def updatePreviewVolume(self, axis, sliceIndex):
        start = perf_counter()
        previewNode = self.previewNodes[axis]
        nodeIsInScene = previewNode and slicer.mrmlScene.GetNodeByID(previewNode.GetID()) is previewNode
        if not nodeIsInScene:
            self._createPreviewVolume(axis)
            firstUpdate = True
            previewNode = self.previewNodes[axis]
        else:
            firstUpdate = False

        sliceIndex = int(sliceIndex)
        fromSlices = [slice(None)] * 3
        toSlices = [slice(None)] * 3
        fromSlices[axis] = sliceIndex
        toSlices[axis] = 0
        fromSlices = tuple(fromSlices)
        toSlices = tuple(toSlices)

        previewArray = self.previewArrays[axis]

        volumeInfo = self.getVolumeInfo()
        spacing = volumeInfo.spacing_xyz
        origin = volumeInfo.origin_xyz
        axis_xyz = 2 - axis
        invert = INVERT[axis_xyz]
        origin[axis_xyz] += sliceIndex * spacing[axis_xyz] * invert
        previewNode.SetOrigin(origin)
        previewNode.SetSpacing(spacing)
        previewNode.SetIJKToRASDirections(-1, 0, 0, 0, -1, 0, 0, 0, 1)

        dataArray = lazy.data(self.currentLazyNode).to_data_array()
        previewArray[toSlices] = dataArray[fromSlices]

        sliceWidgetName = ("Red", "Green", "Yellow")[axis]
        sliceWidget = slicer.app.layoutManager().sliceWidget(sliceWidgetName)
        sliceLogic = sliceWidget.sliceLogic()
        sliceController = sliceWidget.sliceController()
        sliceController.setSliceVisible(True)

        if firstUpdate:
            logging.debug(f"First update for axis {axis}")

            sliceComposite = sliceLogic.GetSliceCompositeNode()
            sliceComposite.SetBackgroundVolumeID(None)
            sliceComposite.SetBackgroundOpacity(1)
            sliceComposite.SetForegroundVolumeID(previewNode.GetID())
            sliceComposite.SetForegroundOpacity(1)

            slicer.util.arrayFromVolumeModified(previewNode)
            if not isinstance(previewNode, slicer.vtkMRMLLabelMapVolumeNode):
                previewNode.GetDisplayNode().SetWindowLevelMinMax(previewArray.min(), previewArray.max())
        else:
            previewNode.SetAttribute("AutoFrameOff", "true")
        sliceLogic.FitSliceToAll()

        logging.debug(f"Updated preview volume in {perf_counter() - start:.2f} seconds on axis {axis}")
