import os
from __main__ import vtk, qt, ctk, slicer
from ltrace.slicer import helpers
from ltrace.slicer_utils import LTracePluginWidget, LTracePlugin, LTracePluginTest

#
# SurfaceLoader3D
# Fork from SlicerIGT TextureModel not merged yet
# https://github.com/fbordignon/SlicerIGT/commit/22cf9e01c5e8e6663ab4948d3fd2cf7d1f7a0b21


class SurfaceLoader3D(LTracePlugin):
    SETTING_KEY = "3DSurfaceLoader"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "3D Surface Loader"
        self.parent.categories = ["Surface Models"]
        self.parent.dependencies = []
        self.parent.contributors = ["Andras Lasso (PerkLab, Queen's)", "Amani Ibrahim (PerkLab, Queen's)"]
        self.parent.helpText = """This module applies a texture (stored in a volume node) to a model node.
It is typically used to display colored surfaces, provided by surface scanners, exported in OBJ format.
The model must contain texture coordinates. Only a single texture file per model is supported.
For more information, visit <a href='https://github.com/SlicerIGT/SlicerIGT/#user-documentation'>SlicerIGT project website</a>.
"""
        self.parent.acknowledgementText = """ """  # replace with organization, grant and thanks.


#
# SurfaceLoader3DWidget
#


class SurfaceLoader3DWidget(LTracePluginWidget):
    def setup(self):
        LTracePluginWidget.setup(self)

        # Instantiate and connect widgets ...

        #
        # Multi Texture Section
        #

        multiTextureParametersCollapsibleButton = ctk.ctkCollapsibleButton()
        multiTextureParametersCollapsibleButton.text = "Import Multi Texture OBJ"
        self.layout.addWidget(multiTextureParametersCollapsibleButton)
        multiTextureParametersCollapsibleButton.collapsed = False

        # Layout within the dummy collapsible button
        multiTextureparametersFormLayout = qt.QFormLayout(multiTextureParametersCollapsibleButton)

        # Input OBJ file path
        self.baseMeshSelector = ctk.ctkPathLineEdit()
        self.baseMeshSelector.nameFilters = ["*.obj"]
        self.baseMeshSelector.settingKey = "SurfaceLoader3D/BaseMesh"
        multiTextureparametersFormLayout.addRow("Model file (obj): ", self.baseMeshSelector)

        # Input MTL file path
        self.materialFileSelector = ctk.ctkPathLineEdit()
        self.materialFileSelector.nameFilters = ["*.mtl"]
        self.materialFileSelector.settingKey = "SurfaceLoader3D/MaterialFile"
        multiTextureparametersFormLayout.addRow("Material file (mtl): ", self.materialFileSelector)

        # Input texture image directory path
        self.textureDirectory = ctk.ctkPathLineEdit()
        self.textureDirectory.filters = ctk.ctkPathLineEdit.Dirs
        self.textureDirectory.setToolTip("Select directory containing texture images")
        self.textureDirectory.settingKey = "SurfaceLoader3D/TextureDirectory"
        multiTextureparametersFormLayout.addRow("Texture directory: ", self.textureDirectory)

        self.multiTextureAddColorAsPointAttributeComboBox = qt.QComboBox()
        self.multiTextureAddColorAsPointAttributeComboBox.addItem("disabled")
        self.multiTextureAddColorAsPointAttributeComboBox.addItem("separate scalars")
        self.multiTextureAddColorAsPointAttributeComboBox.addItem("single vector")
        self.multiTextureAddColorAsPointAttributeComboBox.setCurrentIndex(0)
        self.multiTextureAddColorAsPointAttributeComboBox.setToolTip(
            "It is useful if further color-based filtering will be performed on the model."
        )
        multiTextureparametersFormLayout.addRow(
            "Save color information as point data: ", self.multiTextureAddColorAsPointAttributeComboBox
        )

        #
        # Apply Button
        #
        self.multiTextureApplyButton = qt.QPushButton("Import")
        self.multiTextureApplyButton.toolTip = "Import model with multiple texture images to scene."
        self.multiTextureApplyButton.enabled = False
        multiTextureparametersFormLayout.addRow(self.multiTextureApplyButton)

        # connections
        self.multiTextureApplyButton.connect("clicked(bool)", self.onMultiTextureApplyButton)
        self.baseMeshSelector.connect("validInputChanged(bool)", self.onMultiTextureSelect)
        self.materialFileSelector.connect("validInputChanged(bool)", self.onMultiTextureSelect)
        self.textureDirectory.connect("validInputChanged(bool)", self.onMultiTextureSelect)

        #
        # Parameters Area
        #
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Parameters"
        self.layout.addWidget(parametersCollapsibleButton)
        parametersCollapsibleButton.collapsed = True
        parametersCollapsibleButton.visible = False

        # Layout within the dummy collapsible button
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

        #
        # input volume selector
        #
        self.inputModelSelector = slicer.qMRMLNodeComboBox()
        self.inputModelSelector.nodeTypes = ["vtkMRMLModelNode"]
        self.inputModelSelector.addEnabled = False
        self.inputModelSelector.removeEnabled = True
        self.inputModelSelector.renameEnabled = True
        self.inputModelSelector.noneEnabled = False
        self.inputModelSelector.showHidden = False
        self.inputModelSelector.showChildNodeTypes = False
        self.inputModelSelector.setMRMLScene(slicer.mrmlScene)
        self.inputModelSelector.setToolTip("Model node containing geometry and texture coordinates.")
        parametersFormLayout.addRow("Model: ", self.inputModelSelector)

        # input texture selector
        self.inputTextureSelector = slicer.qMRMLNodeComboBox()
        self.inputTextureSelector.nodeTypes = ["vtkMRMLVectorVolumeNode"]
        self.inputTextureSelector.addEnabled = False
        self.inputTextureSelector.removeEnabled = True
        self.inputTextureSelector.renameEnabled = True
        self.inputTextureSelector.noneEnabled = False
        self.inputTextureSelector.showHidden = False
        self.inputTextureSelector.showChildNodeTypes = False
        self.inputTextureSelector.setMRMLScene(slicer.mrmlScene)
        self.inputTextureSelector.setToolTip("Color image containing texture image.")
        parametersFormLayout.addRow("Texture: ", self.inputTextureSelector)

        self.addColorAsPointAttributeComboBox = qt.QComboBox()
        self.addColorAsPointAttributeComboBox.addItem("disabled")
        self.addColorAsPointAttributeComboBox.addItem("separate scalars")
        self.addColorAsPointAttributeComboBox.addItem("single vector")
        self.addColorAsPointAttributeComboBox.setCurrentIndex(0)
        self.addColorAsPointAttributeComboBox.setToolTip(
            "It is useful if further color-based filtering will be performed on the model."
        )
        parametersFormLayout.addRow("Save color information as point data: ", self.addColorAsPointAttributeComboBox)

        #
        # Apply Button
        #
        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.toolTip = "Apply texture to selected model."
        self.applyButton.enabled = False
        parametersFormLayout.addRow(self.applyButton)

        # connections
        self.applyButton.connect("clicked(bool)", self.onApplyButton)
        self.inputModelSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onSelect)
        self.inputTextureSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onSelect)

        # Add vertical spacer
        self.layout.addStretch(1)

        # Refresh Apply button state
        self.onSelect()
        self.onMultiTextureSelect()

    def onSelect(self):
        self.applyButton.enabled = self.inputTextureSelector.currentNode() and self.inputModelSelector.currentNode()

    def onMultiTextureSelect(self):
        self.multiTextureApplyButton.enabled = (
            self.baseMeshSelector.currentPath
            and self.materialFileSelector.currentPath
            and self.textureDirectory.currentPath
        )
        import re

        obj = re.compile(re.escape("obj"), re.IGNORECASE)
        if os.path.exists(obj.sub("mtl", self.baseMeshSelector.currentPath)):
            self.materialFileSelector.currentPath = obj.sub("mtl", self.baseMeshSelector.currentPath)
        elif os.path.exists(obj.sub("MTL", self.baseMeshSelector.currentPath)):
            self.materialFileSelector.currentPath = obj.sub("MTL", self.baseMeshSelector.currentPath)

        self.textureDirectory.currentPath = os.path.dirname(self.baseMeshSelector.currentPath)

    def onApplyButton(self):
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        logic = SurfaceLoader3DLogic()
        logic.applyTexture(
            self.inputModelSelector.currentNode(),
            self.inputTextureSelector.currentNode(),
            self.addColorAsPointAttributeComboBox.currentIndex > 0,
            self.addColorAsPointAttributeComboBox.currentIndex > 1,
        )
        qt.QApplication.restoreOverrideCursor()

    def onMultiTextureApplyButton(self):
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        logic = SurfaceLoader3DLogic()
        logic.applyMultiTexture(
            self.baseMeshSelector.currentPath,
            self.materialFileSelector.currentPath,
            self.textureDirectory.currentPath,
            self.multiTextureAddColorAsPointAttributeComboBox.currentIndex > 0,
            self.multiTextureAddColorAsPointAttributeComboBox.currentIndex > 1,
        )
        helpers.save_path(self.baseMeshSelector)
        helpers.save_path(self.materialFileSelector)
        helpers.save_path(self.textureDirectory)
        qt.QApplication.restoreOverrideCursor()


#
# SurfaceLoader3DLogic
#
class SurfaceLoader3DLogic(LTracePlugin):
    def applyTexture(self, modelNode, textureImageNode, addColorAsPointAttribute=False, colorAsVector=False):
        """
        Apply texture to model node
        """
        self.showTextureOnModel(modelNode, textureImageNode)
        if addColorAsPointAttribute:
            self.convertTextureToPointAttribute(modelNode, textureImageNode, colorAsVector)

    # Show texture
    def showTextureOnModel(self, modelNode, textureImageNode):
        modelDisplayNode = modelNode.GetDisplayNode()
        modelDisplayNode.SetBackfaceCulling(0)
        textureImageFlipVert = vtk.vtkImageFlip()
        textureImageFlipVert.SetFilteredAxis(1)
        textureImageFlipVert.SetInputConnection(textureImageNode.GetImageDataConnection())
        modelDisplayNode.SetTextureImageDataConnection(textureImageFlipVert.GetOutputPort())

    # Add texture data to scalars
    def convertTextureToPointAttribute(self, modelNode, textureImageNode, colorAsVector):
        polyData = modelNode.GetPolyData()
        textureImageFlipVert = vtk.vtkImageFlip()
        textureImageFlipVert.SetFilteredAxis(1)
        textureImageFlipVert.SetInputConnection(textureImageNode.GetImageDataConnection())
        textureImageFlipVert.Update()
        textureImageData = textureImageFlipVert.GetOutput()
        pointData = polyData.GetPointData()
        tcoords = pointData.GetTCoords()
        numOfPoints = pointData.GetNumberOfTuples()
        assert (
            numOfPoints == tcoords.GetNumberOfTuples()
        ), "Number of texture coordinates does not equal number of points"
        textureSamplingPointsUv = vtk.vtkPoints()
        textureSamplingPointsUv.SetNumberOfPoints(numOfPoints)
        for pointIndex in range(numOfPoints):
            uv = tcoords.GetTuple2(pointIndex)
            textureSamplingPointsUv.SetPoint(pointIndex, uv[0], uv[1], 0)

        textureSamplingPointDataUv = vtk.vtkPolyData()
        uvToXyz = vtk.vtkTransform()
        textureImageDataSpacingSpacing = textureImageData.GetSpacing()
        textureImageDataSpacingOrigin = textureImageData.GetOrigin()
        textureImageDataSpacingDimensions = textureImageData.GetDimensions()
        uvToXyz.Scale(
            textureImageDataSpacingDimensions[0] / textureImageDataSpacingSpacing[0],
            textureImageDataSpacingDimensions[1] / textureImageDataSpacingSpacing[1],
            1,
        )
        uvToXyz.Translate(textureImageDataSpacingOrigin)
        textureSamplingPointDataUv.SetPoints(textureSamplingPointsUv)
        transformPolyDataToXyz = vtk.vtkTransformPolyDataFilter()
        transformPolyDataToXyz.SetInputData(textureSamplingPointDataUv)
        transformPolyDataToXyz.SetTransform(uvToXyz)
        probeFilter = vtk.vtkProbeFilter()
        probeFilter.SetInputConnection(transformPolyDataToXyz.GetOutputPort())
        probeFilter.SetSourceData(textureImageData)
        probeFilter.Update()
        rgbPoints = probeFilter.GetOutput().GetPointData().GetArray("ImageScalars")

        if colorAsVector:
            colorArray = vtk.vtkDoubleArray()
            colorArray.SetName("Color")
            colorArray.SetNumberOfComponents(3)
            colorArray.SetNumberOfTuples(numOfPoints)
            for pointIndex in range(numOfPoints):
                rgb = rgbPoints.GetTuple3(pointIndex)
                colorArray.SetTuple3(pointIndex, rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)
            colorArray.Modified()
            pointData.AddArray(colorArray)
        else:
            colorArrayRed = vtk.vtkDoubleArray()
            colorArrayRed.SetName("ColorRed")
            colorArrayRed.SetNumberOfTuples(numOfPoints)
            colorArrayGreen = vtk.vtkDoubleArray()
            colorArrayGreen.SetName("ColorGreen")
            colorArrayGreen.SetNumberOfTuples(numOfPoints)
            colorArrayBlue = vtk.vtkDoubleArray()
            colorArrayBlue.SetName("ColorBlue")
            colorArrayBlue.SetNumberOfTuples(numOfPoints)
            for pointIndex in range(numOfPoints):
                rgb = rgbPoints.GetTuple3(pointIndex)
                colorArrayRed.SetValue(pointIndex, rgb[0])
                colorArrayGreen.SetValue(pointIndex, rgb[1])
                colorArrayBlue.SetValue(pointIndex, rgb[2])
            colorArrayRed.Modified()
            colorArrayGreen.Modified()
            colorArrayBlue.Modified()
            pointData.AddArray(colorArrayRed)
            pointData.AddArray(colorArrayGreen)
            pointData.AddArray(colorArrayBlue)

        pointData.Modified()
        polyData.Modified()

    def applyMultiTexture(self, objPath, mtlPath, texPath, addColorAsPointAttribute=False, colorAsVector=False):
        modelNode, textureImageNode = self.OBJtoVTP(objPath, mtlPath, texPath)
        self.applyTexture(modelNode, textureImageNode, addColorAsPointAttribute, colorAsVector)

    def OBJtoVTP(self, objPath, mtlPath, texPath):
        importer = vtk.vtkOBJImporter()
        importer.SetFileName(objPath)
        importer.SetFileNameMTL(mtlPath)
        importer.SetTexturePath(texPath)
        importer.Update()

        exporter = vtk.vtkSingleVTPExporter()
        exporter.SetRenderWindow(importer.GetRenderWindow())
        exporter.SetFilePrefix(slicer.app.temporaryPath + os.path.splitext(os.path.basename(objPath))[0])
        exporter.Write()

        modelNode = slicer.util.loadModel(
            slicer.app.temporaryPath + os.path.splitext(os.path.basename(objPath))[0] + ".vtp"
        )
        textureImageNode = slicer.util.loadVolume(
            slicer.app.temporaryPath + os.path.splitext(os.path.basename(objPath))[0] + ".png", {"singleFile": True}
        )
        return modelNode, textureImageNode
