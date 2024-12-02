import logging
import os

import vtk.util.numpy_support as vn

import qt
import slicer
import vtk
import qSlicerSegmentationsEditorEffectsPythonQt as effects
import traceback

from ltrace.slicer import helpers
from ltrace.slicer_utils import LTraceSegmentEditorEffectMixin
from ltrace.slicer.ui import numberParamInt
from ltrace.assets_utils import get_asset, get_pth
from ltrace.slicer.helpers import LazyLoad
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.cli_queue import CliQueue
from SegmentEditorEffects import *


FILTER_GRADIENT_MAGNITUDE = "GRADIENT_MAGNITUDE"


class SegmentEditorEffect(AbstractScriptedSegmentEditorEffect, LTraceSegmentEditorEffectMixin):
    def __init__(self, scriptedEffect):
        AbstractScriptedSegmentEditorEffect.__init__(self, scriptedEffect)
        scriptedEffect.name = "Smart foreground"
        scriptedEffect.perSegment = False
        scriptedEffect.requireSegments = True

    def clone(self):
        clonedEffect = effects.qSlicerSegmentEditorScriptedEffect(None)
        clonedEffect.setPythonSource(__file__.replace("\\", "/"))
        return clonedEffect

    def icon(self):
        iconPath = os.path.join(os.path.dirname(__file__), "SegmentEditorEffect.png")
        if os.path.exists(iconPath):
            return qt.QIcon(iconPath)
        return qt.QIcon()

    def helpText(self):
        return """<html>
            <p>Segment only the useful area of a thin section image, discarding borders and inter-fragments areas.</p>
            <p>
              Operation:
              <ul style="feature: 0">
                <li>Fill inside: fill the selected segment along the detected useful area;</li>
                <li>Erase outside: erase the region from the selected segment which lies outside the useful area.</li>
              </ol>
            </p>
            <p>
              Fragments (<b>recommended for plane-polarized (PP) images only</b>):
              <ul style="feature: 0">
                <li>Split: if not checked, only the image's borders will be considered non-useful area. Otherwise, the area between fragments will be too.</li>
                <li>
                  <ul style="feature: 0">
                    <li>Keep all: every fragment will be considered useful area;</li>
                    <li>Filter the largest <i>N</i>: only the <i>N</i> fragments with the largest area will be considered useful.</li>
                  </ol>
                </li>
              </ol>
            </p>
            <p>Click <b>Apply</b> to start. It may take a while.</p>
        </html>"""

    def setupOptionsFrame(self):
        # Operation buttons
        self.fillInsideButton = qt.QRadioButton("Fill inside")
        self.fillInsideButton.objectName = "Smart Foreground Fill Inside Button"

        self.eraseOutsideButton = qt.QRadioButton("Erase outside")
        self.eraseOutsideButton.objectName = "Smart Foreground Erase Outside Button"

        # Grouping
        self.operationRadioGroup = qt.QButtonGroup()
        self.operationRadioGroup.setExclusive(True)
        self.operationRadioGroup.addButton(self.fillInsideButton)
        self.operationRadioGroup.addButton(self.eraseOutsideButton)

        self.fillInsideButton.setChecked(True)

        # Operation buttons layout
        operationLayout = qt.QGridLayout()
        operationLayout.addWidget(self.fillInsideButton, 0, 0)
        operationLayout.addWidget(self.eraseOutsideButton, 0, 1)
        self.scriptedEffect.addLabeledOptionsWidget("Operation:", operationLayout)

        # Fragment splitting options
        self.fragSplitCheckbox = qt.QCheckBox("Split")
        self.fragSplitCheckbox.objectName = "Smart Foreground Split Checkbox"
        self.fragSplitAllButton = qt.QRadioButton("Keep all")
        self.fragSplitAllButton.objectName = "Smart Foreground Split All Button"
        self.fragFilterButton = qt.QRadioButton("Filter the largest")
        self.fragFilterButton.objectName = "Smart Foreground Fragments Filter Button"
        self.fragFilterInput = numberParamInt((1, 20), value=1, step=1)

        # Grouping
        self.fragRadioGroup = qt.QButtonGroup()
        self.fragRadioGroup.setExclusive(True)
        self.fragRadioGroup.addButton(self.fragSplitAllButton)
        self.fragRadioGroup.addButton(self.fragFilterButton)

        self.fragSplitCheckbox.clicked.connect(self.setVisibleFragSplitting)
        self.fragSplitAllButton.setChecked(True)
        self.fragSplitAllButton.setVisible(False)
        self.fragSplitAllButton.clicked.connect(self.setVisibleFragLimit)
        self.fragFilterButton.setVisible(False)
        self.fragFilterButton.clicked.connect(self.setVisibleFragLimit)
        self.fragFilterInput.setEnabled(False)
        self.fragFilterInput.setVisible(False)

        # Fragment splitting options layout
        fragSplitLayout = qt.QGridLayout()
        fragSplitLayout.addWidget(self.fragSplitCheckbox, 0, 0)
        fragSplitLayout.addWidget(self.fragSplitAllButton, 1, 0)
        fragSplitLayout.addWidget(self.fragFilterButton, 1, 1)
        fragSplitLayout.addWidget(self.fragFilterInput, 1, 2)
        self.scriptedEffect.addLabeledOptionsWidget("Fragments:", fragSplitLayout)

        # Apply button
        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setMinimumHeight(25)
        self.scriptedEffect.addOptionsWidget(self.applyButton)
        self.applyButton.setVisible(True)
        self.applyButton.objectName = "Smart Foreground Apply Button"
        self.applyButton.connect("clicked()", self.onApply)

        # Step label (multistep CLI)
        self.stepLabel = qt.QLabel("")
        self.scriptedEffect.addOptionsWidget(self.stepLabel)

        # Progress bar
        self.progressBar = LocalProgressBar()
        self.scriptedEffect.addOptionsWidget(self.progressBar)

    def createCursor(self, widget):
        # Turn off effect-specific cursor for this effect
        return slicer.util.mainWindow().cursor

    def setVisibleFragSplitting(self):
        self.fragSplitAllButton.setVisible(self.fragSplitCheckbox.isChecked())
        self.fragFilterButton.setVisible(self.fragSplitCheckbox.isChecked())
        self.fragFilterInput.setVisible(self.fragSplitCheckbox.isChecked())

    def setVisibleFragLimit(self):
        self.fragFilterInput.setEnabled(self.fragFilterButton.isChecked())

    def onApply(self):
        def onFinish():
            self.applyButton.setEnabled(True)
            for node in [tmpForegroundNode, tmpPoreSegNode, tmpSlicedReferenceNode]:
                if node is not None:
                    slicer.mrmlScene.RemoveNode(node)

            del self.cliQueue
            self.cliQueue = None

        def onFailure():
            slicer.util.errorDisplay(f"Operation failed on {self.cliQueue.get_error_message()}")

        def onSuccess():
            mask = slicer.util.arrayFromVolume(tmpForegroundNode)[0].astype(bool)

            if eraseOutside:
                segmentArray = slicer.util.arrayFromSegmentBinaryLabelmap(
                    segmentationNode, segmentID, sourceVolumeNode
                )[0].astype(bool)
                mask &= segmentArray

            maskImage = vtk.vtkImageData()
            maskImage.SetDimensions(cols, rows, 1)
            maskImage.SetSpacing(sourceVolumeNode.GetSpacing())
            maskImage.SetOrigin(sourceVolumeNode.GetOrigin())

            maskData = vn.numpy_to_vtk(num_array=mask.ravel(), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
            maskData.SetNumberOfComponents(1)
            maskImage.GetPointData().SetScalars(maskData)

            modifierLabelmap = self.scriptedEffect.defaultModifierLabelmap()
            originalImageToWorldMatrix = vtk.vtkMatrix4x4()
            modifierLabelmap.GetImageToWorldMatrix(originalImageToWorldMatrix)
            modifierLabelmap.DeepCopy(maskImage)

            # Apply changes
            self.scriptedEffect.modifySelectedSegmentByLabelmap(
                modifierLabelmap,
                slicer.qSlicerSegmentEditorAbstractEffect.ModificationModeSet,
            )
            slicer.util.setSliceViewerLayers(background=sourceVolumeNode, foreground=None, fit=True)

            self.scriptedEffect.saveStateForUndo()

            # De-select effect
            self.scriptedEffect.selectEffect("")
            self.progressBar.visible = False

        def hideTmpOutput(caller, event, params):
            if caller.GetStatus() == slicer.vtkMRMLCommandLineModuleNode.Completed:
                slicer.util.setSliceViewerLayers(label=None)

        tmpForegroundNode = None
        tmpPoreSegNode = None
        tmpSlicedReferenceNode = None
        try:
            self.applyButton.setEnabled(False)

            self.progressBar.visible = True
            self.cliQueue = CliQueue(update_display=False, progress_bar=self.progressBar, progress_label=self.stepLabel)
            self.cliQueue.signal_queue_successful.connect(onSuccess)
            self.cliQueue.signal_queue_failed.connect(onFailure)
            self.cliQueue.signal_queue_finished.connect(onFinish)

            sourceVolumeNode = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()
            sourceImageData = sourceVolumeNode.GetImageData()
            cols, rows, _ = sourceImageData.GetDimensions()  # x, y, z

            segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
            segmentID = self.scriptedEffect.parameterSetNode().GetSelectedSegmentID()

            tmpForegroundNode = helpers.createTemporaryVolumeNode(slicer.vtkMRMLLabelMapVolumeNode, "TMP_ROCK_AREA")

            eraseOutside = self.eraseOutsideButton.isChecked()
            splitFrags = self.fragSplitCheckbox.isChecked()

            smartForegroundParams = {
                "input": sourceVolumeNode.GetID(),
                "outputRock": tmpForegroundNode.GetID(),
            }

            if splitFrags:
                limitFrags = self.fragFilterButton.isChecked()
                numberFrags = self.fragFilterInput.value

                Segmenter = LazyLoad("Segmenter")

                tmpPoreSegNode = helpers.createTemporaryVolumeNode(slicer.vtkMRMLLabelMapVolumeNode, "TMP_PORE_SEG")

                tmpSlicedReferenceNode = Segmenter.prepareTemporaryInputs(
                    [sourceVolumeNode],
                    outputPrefix="TMP_INPUT_NODE",
                    soiNode=None,
                    referenceNode=sourceVolumeNode,
                    colorsToSlices=True,
                )[0][0]
                poreSegParams = {
                    "inputVolume": tmpSlicedReferenceNode.GetID(),
                    "inputModel": get_pth(os.path.join(get_asset("ThinSectionEnv"), "bayes_3px")).as_posix(),
                    "xargs": "null",
                    "ctypes": "rgb",
                    "outputVolume": tmpPoreSegNode.GetID(),
                }
                self.cliQueue.create_cli_node(
                    slicer.modules.bayesianinferencecli,
                    poreSegParams,
                    progress_text="Detecting resin region",
                    modified_callback=hideTmpOutput,
                )

                smartForegroundParams.update(
                    {
                        "outputFrags": tmpForegroundNode.GetID(),  # here specifically, there's no need to outputRock != outputFrags
                        "poreSegmentation": tmpPoreSegNode.GetID(),
                        "nLargestFrags": numberFrags if limitFrags else -1,
                    }
                )

            self.cliQueue.create_cli_node(
                slicer.modules.smartforegroundcli,
                smartForegroundParams,
                progress_text="Removing borders",
                modified_callback=hideTmpOutput,
            )
            self.cliQueue.run()
        except Exception as error:
            print(traceback.format_exc())
            logging.debug(f"Error: {error}.\n{traceback.format_exc()}")
            slicer.util.errorDisplay(f"Failed to apply the effect.\nError: {error}")
            onFinish()
