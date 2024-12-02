import os
from pathlib import Path

import numpy as np
import qt
import slicer
from ltrace.slicer_utils import *
from ltrace.units import global_unit_registry as ureg, SLICER_LENGTH_UNIT


class MulticoreTransforms(LTracePlugin):
    SETTING_KEY = "MulticoreTransforms"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Multicore Transforms"
        self.parent.categories = ["Core"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = MulticoreTransforms.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class MulticoreTransformsWidget(LTracePluginWidget):
    def __init__(self, widgetName):
        super(MulticoreTransformsWidget, self).__init__(widgetName)

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = MulticoreTransformsLogic()

        transformWidget = slicer.modules.transforms.createNewWidgetRepresentation()

        self.transformNodeSelector = transformWidget.findChild(qt.QObject, "TransformNodeSelector")

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        depthAndOrientationFormLayout = qt.QFormLayout(frame)
        depthAndOrientationFormLayout.setContentsMargins(0, 0, 0, 0)

        hBoxLayout = qt.QHBoxLayout()
        depthAndOrientationFormLayout.addRow(hBoxLayout)

        vBoxLayout = qt.QVBoxLayout()
        self.transformableTreeView = transformWidget.findChild(qt.QObject, "TransformableTreeView")
        self.transformableTreeView.nodeTypes = [slicer.vtkMRMLVolumeNode.__name__]
        vBoxLayout.addWidget(qt.QLabel("Available volumes:"))
        vBoxLayout.addWidget(self.transformableTreeView)
        hBoxLayout.addLayout(vBoxLayout)

        vBoxLayout = qt.QVBoxLayout()
        self.transformToolButton = transformWidget.findChild(qt.QObject, "TransformToolButton")
        vBoxLayout.addWidget(self.transformToolButton)
        self.untransformToolButton = transformWidget.findChild(qt.QObject, "UntransformToolButton")
        vBoxLayout.addWidget(self.untransformToolButton)
        hBoxLayout.addLayout(vBoxLayout)

        vBoxLayout = qt.QVBoxLayout()
        self.transformedTreeView = transformWidget.findChild(qt.QObject, "TransformedTreeView")
        self.transformedTreeView.nodeTypes = [slicer.vtkMRMLVolumeNode.__name__]
        vBoxLayout.addWidget(qt.QLabel("Selected volumes:"))
        vBoxLayout.addWidget(self.transformedTreeView)
        hBoxLayout.addLayout(vBoxLayout)

        spinBoxWidth = 100

        translationSliders = transformWidget.findChild(qt.QObject, "TranslationSliders")
        depthAndOrientationFormLayout.addRow(qt.QLabel("Depth adjustment (negative value is deeper):"))
        # The MinMaxWidget has a bug if you keep changing the min and max values, which causes a translation on the XY
        # plane (should occur only on the Z axis). Then we are hiding them
        minMaxWidget = transformWidget.findChild(qt.QObject, "MinMaxWidget")
        minValueSpinBox = minMaxWidget.findChild(qt.QObject, "MinValueSpinBox")
        minValueSpinBox.setValue(-1000)
        maxValueSpinBox = minMaxWidget.findChild(qt.QObject, "MaxValueSpinBox")
        maxValueSpinBox.setValue(1000)
        minMaxWidget.setVisible(False)
        iSSLider = translationSliders.findChild(qt.QObject, "ISSlider")
        iSSLider.setObjectName("Translation ISSlider")
        self.depthSpinBox = iSSLider.children()[-1]
        self.depthSpinBox.setMinimumWidth(spinBoxWidth)
        depthAndOrientationFormLayout.addRow(iSSLider)
        depthAndOrientationFormLayout.addRow(transformWidget.findChild(qt.QObject, "MinMaxWidget"))

        rotationSliders = transformWidget.findChild(qt.QObject, "RotationSliders")
        depthAndOrientationFormLayout.addRow(
            qt.QLabel("Orientation adjustment (from above, positive value is counterclockwise):")
        )
        iSSLider = rotationSliders.findChild(qt.QObject, "ISSlider")
        iSSLider.setObjectName("Rotation ISSlider")
        self.orientationSpinBox = iSSLider.children()[-1]
        self.orientationSpinBox.setMinimumWidth(spinBoxWidth)
        depthAndOrientationFormLayout.addRow(iSSLider)

        depthAndOrientationFormLayout.addRow(" ", None)

        self.applyTransformButton = qt.QPushButton("Apply")
        self.applyTransformButton.setFixedHeight(40)
        self.cancelTransformButton = qt.QPushButton("Cancel")
        self.cancelTransformButton.setFixedHeight(40)
        hBoxLayout = qt.QHBoxLayout()
        hBoxLayout.addWidget(self.applyTransformButton)
        hBoxLayout.addWidget(self.cancelTransformButton)
        depthAndOrientationFormLayout.addRow(hBoxLayout)

        self.applyTransformButton.connect("clicked(bool)", self.onApplyTransformButton)
        self.cancelTransformButton.connect("clicked(bool)", self.onCancelTransformButton)

    def onApplyTransformButton(self):
        selectedVolumeNodeNames = []
        self.transformedTreeView.selectAll()
        for index in self.transformedTreeView.selectedIndexes():
            selectedVolumeNodeNames.append(index.data())
        transformNode = self.transformNodeSelector.currentNode()
        # If the transform is not Identity matrix, apply
        if not np.array_equal(slicer.util.arrayFromTransformMatrix(transformNode), np.eye(4)):
            transformedNodes = self.logic.applyTransform(
                selectedVolumeNodeNames, self.depthSpinBox.value * ureg.millimeter, self.orientationSpinBox.value
            )
            self.renewHiddenTransformNode()
            for node in transformedNodes:
                self.transformableTreeView.setCurrentNode(node)
                self.transformToolButton.click()

    def onCancelTransformButton(self):
        self.transformedTreeView.selectAll()
        self.untransformToolButton.click()
        self.renewHiddenTransformNode()

    def renewHiddenTransformNode(self):
        slicer.mrmlScene.RemoveNode(self.transformNodeSelector.currentNode())
        self.transformNodeSelector.addNode()

    def enter(self) -> None:
        super().enter()
        self.renewHiddenTransformNode()

    def exit(self):
        slicer.mrmlScene.RemoveNode(self.transformNodeSelector.currentNode())


class MulticoreTransformsLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.multicoreLogic = slicer.util.getModuleLogic("Multicore")

    def applyTransform(self, volumeNodeNames, depthIncrement, orientationIncrement):
        """
        Applies the transforms to the core volumes.
        These transforms turn the core unwraps and well unwrap outdated.
        Outdated unwraps are automatically replaced when 'Unwrap all" button is clicked, on the Multicore module.
        """
        wellUnwrapVolumeOutdated = False
        transformedNodes = []
        for volumeNodeName in volumeNodeNames:
            volumeNode = slicer.util.getNode(volumeNodeName)
            # Only apply changes in the core volumes (original volumes and unwraps will follow)
            # TODO Only show core volumes in this interface
            if volumeNode.GetAttribute(self.multicoreLogic.NODE_TYPE) == self.multicoreLogic.NODE_TYPE_CORE_VOLUME:
                transformedNodes.append(volumeNode)
                volumeNode.HardenTransform()
                self.multicoreLogic.setDepth(volumeNode, self.multicoreLogic.getDepth(volumeNode) - depthIncrement)
                self.multicoreLogic.setOrientationAngle(volumeNode)

                # Adjusting the depth for the original volume it exists
                originalVolume = self.multicoreLogic.getNodesByBaseNameAndNodeType(
                    volumeNode.GetAttribute(self.multicoreLogic.BASE_NAME),
                    self.multicoreLogic.NODE_TYPE_ORIGINAL_VOLUME,
                )
                if len(originalVolume) == 1:
                    self.multicoreLogic.configureVolumeDepth(
                        originalVolume[0], self.multicoreLogic.getDepth(volumeNode)
                    )

                # Adjusting the depth of the ROI if it exists
                if depthIncrement != 0:
                    try:
                        roi = slicer.util.getNode(volumeNode.GetName() + " ROI")
                        xyz = np.zeros(3)
                        roi.GetXYZ(xyz)
                        xyz[2] += depthIncrement.m_as(SLICER_LENGTH_UNIT)
                        roi.SetXYZ(xyz)
                    except slicer.util.MRMLNodeNotFoundException:
                        pass

                unwrapVolume = self.multicoreLogic.getUnwrapVolume(volumeNode)
                if len(unwrapVolume) == 1:
                    if orientationIncrement != 0:
                        self.multicoreLogic.updateCoreUnwrapVolume(volumeNode)
                    if depthIncrement != 0:
                        self.multicoreLogic.configureVolumeDepth(
                            unwrapVolume[0], self.multicoreLogic.getDepth(volumeNode)
                        )

                wellUnwrapVolumeOutdated = True

        wellUnwrapVolume = self.multicoreLogic.getWellUnwrapVolume()
        if len(wellUnwrapVolume) == 1 and wellUnwrapVolumeOutdated:
            self.multicoreLogic.flagVolumeOutdated(wellUnwrapVolume[0])

        return transformedNodes
