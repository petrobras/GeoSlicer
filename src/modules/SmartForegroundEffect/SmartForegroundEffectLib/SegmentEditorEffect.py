import json
import logging
import os

from ltrace.slicer.tests.utils import wait
import numpy as np

import vtk.util.numpy_support as vn

import qt
import slicer
import vtk
import qSlicerSegmentationsEditorEffectsPythonQt as effects
import traceback

from ltrace.slicer import helpers, ui, widgets
from ltrace.slicer_utils import LTraceSegmentEditorEffectMixin, getResourcePath
from ltrace.slicer.ui import numberParamInt
from ltrace.assets_utils import get_model_by_name, get_pth
from ltrace.slicer.helpers import LazyLoad
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.cli_queue import CliQueue
from ltrace.slicer.application_observables import ApplicationObservables
from SegmentEditorEffects import *


FILTER_GRADIENT_MAGNITUDE = "GRADIENT_MAGNITUDE"


class SegmentEditorEffect(AbstractScriptedSegmentEditorEffect, LTraceSegmentEditorEffectMixin):
    def __init__(self, scriptedEffect):
        AbstractScriptedSegmentEditorEffect.__init__(self, scriptedEffect)
        scriptedEffect.name = "Smart foreground"
        scriptedEffect.requireSegments = True

        self.inputModelPath = None
        self.__sourceIs2d = None
        self.firstActivation = True
        self.cliQueue = None

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
        commonBeginning = """<html>
            <p>Segment only the useful area of a thin section image, discarding borders and inter-fragments areas.</p>
            <p>
              <b>Operation</b>:
              <ul style="feature: 0">
                <li>Fill inside: fill the selected segment along the detected useful area;</li>
                <li>Erase outside: erase the region from the selected segment which lies outside the useful area.</li>
              </ol>
            </p>
            <p>
              <b>Fragments (<i>available for thin section images only</i>)</b>:
              <ul style="feature: 0">
                <li>Split: if not checked, only the image's borders will be considered non-useful area. Otherwise, the area between fragments will be too. <i>Use preferably with plane-polarized (PP) images.</i></li>
                <li>
                  <ul style="feature: 0">
                    <li>Keep all: every fragment will be considered useful area;</li>
                    <li>Filter the largest <i>N</i>: only the <i>N</i> fragments with the largest area will be considered useful"""

        exclusiveMiddle = ".</li>"
        if not self.inputModelPath:
            exclusiveMiddle = """;</li>
                        <li>Annotations: segmentation containing manually marked samples of both texture and resin on the input image, each on a different segment.
                        <ul style="feature: 0">
                            <li>Texture samples: segment containing samples of the rock's texture;</li>
                            <li>Resin samples: segment containing samples of the resin applied to void regions.</li>
                        </ol>
            """

        commonEnd = """
                  </ol>
                </li>
              </ol>
            </p>
            <p>Click <b>Apply</b> to start. It may take a while.</p>
        </html>"""

        return commonBeginning + exclusiveMiddle + commonEnd

    def activate(self):
        if self.firstActivation:
            self.__updateTrainedModelAvailability()
            ApplicationObservables().modelPathUpdated.connect(self.__updateTrainedModelAvailability)
            self.firstActivation = False

    def cleanup(self) -> None:
        super().cleanup()
        ApplicationObservables().modelPathUpdated.disconnect(self.__updateTrainedModelAvailability)

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

        # Fragment label (isolated for changing visibility depending on environment)
        self.fragSplitLabel = qt.QLabel("Fragments:")
        self.fragSplitLabel.objectName = "Smart Foreground Split Fragments Section Label"

        # Fragment splitting options
        self.fragSplitCheckbox = qt.QCheckBox("Split")
        self.fragSplitCheckbox.objectName = "Smart Foreground Split Checkbox"

        self.fragSplitAllButton = qt.QRadioButton("Keep all")
        self.fragSplitAllButton.objectName = "Smart Foreground Split All Button"
        self.fragSplitAllButtonLayout = qt.QHBoxLayout()
        self.fragSplitAllButtonLayout.setAlignment(qt.Qt.AlignLeft)
        self.fragSplitAllButtonLayout.addWidget(self.fragSplitAllButton)

        self.fragFilterButton = qt.QRadioButton("Filter the largest")
        self.fragFilterButton.objectName = "Smart Foreground Fragments Filter Button"
        self.fragFilterButtonLayout = qt.QHBoxLayout()
        self.fragFilterButtonLayout.setAlignment(qt.Qt.AlignLeft)
        self.fragFilterButtonLayout.addWidget(self.fragFilterButton)

        self.fragFilterInput = numberParamInt((1, 20), value=1, step=1)
        self.fragFilterInput.objectName = "Smart Foreground Fragments Filter Input"

        # Grouping
        self.fragSplitLabelAndCheckbox = qt.QHBoxLayout()
        self.fragSplitLabelAndCheckbox.setAlignment(qt.Qt.AlignLeft)
        self.fragSplitLabelAndCheckbox.addWidget(self.fragSplitLabel)
        self.fragSplitLabelAndCheckbox.addWidget(self.fragSplitCheckbox)
        self.scriptedEffect.addOptionsWidget(self.fragSplitLabelAndCheckbox)

        self.fragRadioGroup = qt.QButtonGroup()
        self.fragRadioGroup.setExclusive(True)
        self.fragRadioGroup.addButton(self.fragSplitAllButton)
        self.fragRadioGroup.addButton(self.fragFilterButton)

        fragFilterLayout = qt.QHBoxLayout()
        fragFilterLayout.addWidget(self.fragFilterButton)
        fragFilterLayout.addWidget(self.fragFilterInput)

        # Annotations inputs (non-AI mode (public) only)
        self.fragAnnotsInput = ui.hierarchyVolumeInput(
            hasNone=True,
            nodeTypes=[
                "vtkMRMLSegmentationNode",
            ],
            tooltip="Annotations of texture and resin samples whose patterns will be identified for fragment splitting.",
            onChange=self.onAnnotationsSelected,
            onActivation=self.onAnnotationsSelected,
            allowFolders=True,  # otherwise onChange will not be triggered when folders are selected
        )
        self.fragAnnotsInput.objectName = "Smart Foreground Annotations Combobox"
        self.fragAnnotsLabel = qt.QLabel("Annotations:")
        self.fragAnnotsLabel.objectName = "Smart Foreground Annotations Label"
        self.refreshFragAnnotSegmentsButton = qt.QPushButton()
        self.refreshFragAnnotSegmentsButton.objectName = "Smart Foreground Annotation Segments Refresh Button"
        self.refreshFragAnnotSegmentsButton.clicked.connect(self.onAnnotationsSelected)
        self.refreshFragAnnotSegmentsButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "Reset.png"))
        self.refreshFragAnnotSegmentsButton.setToolTip(
            "Refresh the list of available segments for the selected annotations."
        )
        fragAnnotsLayout = qt.QHBoxLayout()
        fragAnnotsLayout.addWidget(self.fragAnnotsInput)
        fragAnnotsLayout.addWidget(self.refreshFragAnnotSegmentsButton)

        self.fragTextureAnnotCombobox = qt.QComboBox()
        self.fragTextureAnnotCombobox.objectName = "Smart Foreground Texture Annotations Combobox"
        self.fragTextureAnnotLabel = qt.QLabel("Texture samples:")
        self.fragTextureAnnotLabel.objectName = "Smart Foreground Texture Annotations Label"

        self.fragResinAnnotCombobox = qt.QComboBox()
        self.fragResinAnnotCombobox.objectName = "Smart Foreground Resin Annotations Combobox"
        self.fragResinAnnotLabel = qt.QLabel("Resin samples:")
        self.fragResinAnnotLabel.objectName = "Smart Foreground Resin Annotations Label"

        # Setting initial state
        self.fragSplitCheckbox.clicked.connect(self.setVisibleFragSplitting)
        self.fragSplitAllButton.clicked.connect(self.setEnableFragLimit)
        self.fragFilterButton.clicked.connect(self.setEnableFragLimit)
        self.fragSplitAllButton.setChecked(True)
        self.fragFilterInput.setEnabled(False)
        self.fragFilterInput.setVisible(False)
        self.fragAnnotsInput.setVisible(False)
        self.refreshFragAnnotSegmentsButton.setVisible(False)
        self.fragAnnotsLabel.setVisible(False)
        self.fragTextureAnnotCombobox.setVisible(False)
        self.fragTextureAnnotLabel.setVisible(False)
        self.fragResinAnnotCombobox.setVisible(False)
        self.fragResinAnnotLabel.setVisible(False)

        # Fragment splitting options layout
        fragSplitLayout = qt.QGridLayout()
        fragSplitLayout.addWidget(self.fragSplitAllButton, 0, 0)
        fragSplitLayout.addLayout(fragFilterLayout, 0, 1)
        fragSplitLayout.addWidget(self.fragAnnotsLabel, 1, 0)
        fragSplitLayout.addLayout(fragAnnotsLayout, 1, 1)
        fragSplitLayout.addWidget(self.fragTextureAnnotLabel, 2, 0)
        fragSplitLayout.addWidget(self.fragTextureAnnotCombobox, 2, 1)
        fragSplitLayout.addWidget(self.fragResinAnnotLabel, 3, 0)
        fragSplitLayout.addWidget(self.fragResinAnnotCombobox, 3, 1)
        self.scriptedEffect.addOptionsWidget(fragSplitLayout)

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

    def sourceVolumeNodeChanged(self):
        sourceVolumeNode = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()
        if sourceVolumeNode is None:
            return

        self.__sourceIs2d = sourceVolumeNode.GetImageData().GetNumberOfScalarComponents() == 3

        self.fragSplitLabel.setVisible(self.__sourceIs2d)
        self.fragSplitCheckbox.setVisible(self.__sourceIs2d)
        self.setVisibleFragSplitting()
        self.setApplyButtonEnablement()

    def createCursor(self, widget):
        # Turn off effect-specific cursor for this effect
        return slicer.modules.AppContextInstance.mainWindow.cursor

    def reactivateIfOpen(self):
        # If the effect is open, reopen it to update the help text
        # Note: this was also thought to be used in sourceVolumeNodeChanged, for eliminating the "Fragments" section when input goes from
        # 2D to 3D, but it does not work inside sourceVolumeNodeChanged probably due to the way the callback is handled (but it works outside).
        if self.scriptedEffect.active():
            self.scriptedEffect.selectEffect("")
            self.scriptedEffect.selectEffect(self.scriptedEffect.name)

    def __updateTrainedModelAvailability(self):
        try:
            self.inputModelPath = get_pth(get_model_by_name("bayes_3px")).as_posix()
        except:
            self.inputModelPath = None
        finally:
            self.setVisibleFragSplitting()
            self.setApplyButtonEnablement()
            self.reactivateIfOpen()

    def setApplyButtonEnablement(self):
        effectIsRunning = (self.cliQueue is not None) and self.cliQueue.is_running()

        if self.__sourceIs2d:
            fragSplitChecked = self.fragSplitCheckbox.isChecked()
            AIMode = self.inputModelPath is not None
            textureAnnotSelected = self.fragTextureAnnotCombobox.currentData is not None
            resinAnnotSelected = self.fragResinAnnotCombobox.currentData is not None

            parametersReady = (not fragSplitChecked) or AIMode or (textureAnnotSelected and resinAnnotSelected)
        else:
            parametersReady = True

        self.applyButton.setEnabled((not effectIsRunning) and parametersReady)

    def onAnnotationsSelected(self):
        self.fragTextureAnnotCombobox.clear()
        self.fragResinAnnotCombobox.clear()

        annotsNode = self.fragAnnotsInput.currentNode()
        annotsSelected = annotsNode is not None
        if annotsSelected:
            annotsSegmentation = annotsNode.GetSegmentation()
            numSegments = annotsSegmentation.GetNumberOfSegments()
            for i in range(numSegments):
                segmentId = annotsSegmentation.GetNthSegmentID(i)
                segmentName = annotsSegmentation.GetNthSegment(i).GetName()
                segmentColor = widgets.ColoredIcon(*(255 * np.array(annotsSegmentation.GetNthSegment(i).GetColor())))

                self.fragTextureAnnotCombobox.addItem(segmentColor, segmentName, segmentId)
                self.fragResinAnnotCombobox.addItem(segmentColor, segmentName, segmentId)

            self.fragResinAnnotCombobox.setCurrentIndex(min(1, numSegments - 1))

        segmentsSelectionVisible = self.fragSplitCheckbox.isChecked() and annotsSelected

        self.setVisibleAnnotSampleSelectors(segmentsSelectionVisible)

        self.setApplyButtonEnablement()

    def setVisibleFragSplitting(self):
        fragSplittingVisible = self.__sourceIs2d and self.fragSplitCheckbox.isChecked()

        self.fragSplitAllButton.setVisible(fragSplittingVisible)
        self.fragFilterButton.setVisible(fragSplittingVisible)
        self.fragFilterInput.setVisible(fragSplittingVisible)

        if fragSplittingVisible and (not self.inputModelPath):
            self.fragAnnotsLabel.setVisible(fragSplittingVisible)
            self.fragAnnotsInput.setVisible(fragSplittingVisible)
            self.refreshFragAnnotSegmentsButton.setVisible(fragSplittingVisible)
            self.onAnnotationsSelected()
        else:
            self.fragAnnotsLabel.setVisible(False)
            self.fragAnnotsInput.setVisible(False)
            self.refreshFragAnnotSegmentsButton.setVisible(False)
            self.setVisibleAnnotSampleSelectors(False)

    def setEnableFragLimit(self):
        self.fragFilterInput.setEnabled(self.fragFilterButton.isChecked())

    def setVisibleAnnotSampleSelectors(self, visible):
        self.fragTextureAnnotLabel.setVisible(visible)
        self.fragTextureAnnotCombobox.setVisible(visible)
        self.fragResinAnnotLabel.setVisible(visible)
        self.fragResinAnnotCombobox.setVisible(visible)

    def onApply(self):
        def onFinish():
            self.setApplyButtonEnablement()
            for node in [tmpForegroundNode, tmpSlicedReferenceNode, tmpPoreSegNode, tmpBinaryAnnotsNode]:
                if node is not None:
                    slicer.mrmlScene.RemoveNode(node)

            del self.cliQueue
            self.cliQueue = None

        def onFailure():
            slicer.util.errorDisplay(f"Operation failed on {self.cliQueue.get_error_message()}")

        def onSuccess():
            mask = slicer.util.arrayFromVolume(tmpForegroundNode).astype(bool)

            if eraseOutside:
                segmentArray = slicer.util.arrayFromSegmentBinaryLabelmap(
                    segmentationNode, selectedSegmentID, sourceVolumeNode
                )[0].astype(bool)
                mask &= segmentArray

            helpers.modifySelectedSegmentByMaskArray(self.scriptedEffect, mask, sourceVolumeNode)
            slicer.util.setSliceViewerLayers(background=sourceVolumeNode, foreground=None, fit=True)

            self.scriptedEffect.saveStateForUndo()

            # De-select effect
            self.scriptedEffect.selectEffect("")
            self.progressBar.visible = False

        def hideTmpOutput(caller, event, params):
            if caller.GetStatus() == slicer.vtkMRMLCommandLineModuleNode.Completed:
                slicer.util.setSliceViewerLayers(label=None)

        def getTrainedResinMask(caller, event, params):
            hideTmpOutput(caller, event, params)
            if caller.GetStatus() == slicer.vtkMRMLCommandLineModuleNode.Completed:
                poreSegArray = slicer.util.arrayFromVolume(tmpPoreSegNode)
                poreSegArray -= 1
                slicer.util.arrayFromVolumeModified(tmpPoreSegNode)

        def validateAnnotSegments(selectedSegment, textureSamplesSegment, resinSamplesSegment):
            for samplesType, samplesSegment in {"Texture": textureSamplesSegment, "Resin": resinSamplesSegment}.items():
                if samplesSegment is None:
                    slicer.util.errorDisplay(
                        f"{samplesType} samples segment not found. Hit the refresh button to get an up-to-date list of the available segments."
                    )
                    return False

            if textureSamplesSegment is resinSamplesSegment:
                slicer.util.errorDisplay("The texture and resin samples cannot be the same.")
                return False

            if (textureSamplesSegment is selectedSegment) or (resinSamplesSegment is selectedSegment):
                message = (
                    f'The annotations in "{selectedSegment.GetName()}" will be overwritten. Do you wish to continue?'
                )
                return qt.QMessageBox.question(None, "Overwriting annotations", message) == qt.QMessageBox.Yes

            return True

        tmpForegroundNode = None
        tmpPoreSegNode = None
        tmpSlicedReferenceNode = None
        tmpBinaryAnnotsNode = None
        try:
            self.progressBar.visible = True
            self.cliQueue = CliQueue(update_display=False, progress_bar=self.progressBar, progress_label=self.stepLabel)
            self.cliQueue.signal_queue_successful.connect(onSuccess)
            self.cliQueue.signal_queue_failed.connect(onFailure)
            self.cliQueue.signal_queue_finished.connect(onFinish)

            sourceVolumeNode = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()

            segmentationNode = self.scriptedEffect.parameterSetNode().GetSegmentationNode()
            selectedSegmentID = self.scriptedEffect.parameterSetNode().GetSelectedSegmentID()

            tmpForegroundNode = helpers.createTemporaryVolumeNode(slicer.vtkMRMLLabelMapVolumeNode, "TMP_ROCK_AREA")

            eraseOutside = self.eraseOutsideButton.isChecked()
            splitFrags = self.fragSplitCheckbox.isChecked()

            smartForegroundParams = {
                "input": sourceVolumeNode.GetID(),
                "outputRock": tmpForegroundNode.GetID(),
            }

            if not self.__sourceIs2d:
                smartForegroundParams["is3d"] = True
            elif splitFrags:
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
                    "xargs": "null",
                    "ctypes": "rgb",
                    "outputVolume": tmpPoreSegNode.GetID(),
                }

                if self.inputModelPath:
                    poreSegParams.update({"inputModel": self.inputModelPath})
                else:
                    annotsNode = self.fragAnnotsInput.currentNode()

                    if not helpers.validateSourceVolume(
                        annotationNode=annotsNode, soiNode=None, imageNode=sourceVolumeNode
                    ):
                        return

                    tmpBinaryAnnotsNode = helpers.createTemporaryVolumeNode(
                        slicer.vtkMRMLSegmentationNode, "TMP_BINARY_ANNOTS"
                    )

                    textureSamplesSegment = annotsNode.GetSegmentation().GetSegment(
                        self.fragTextureAnnotCombobox.currentData
                    )
                    resinSamplesSegment = annotsNode.GetSegmentation().GetSegment(
                        self.fragResinAnnotCombobox.currentData
                    )
                    selectedSegment = segmentationNode.GetSegmentation().GetSegment(selectedSegmentID)

                    if not validateAnnotSegments(
                        selectedSegment=selectedSegment,
                        textureSamplesSegment=textureSamplesSegment,
                        resinSamplesSegment=resinSamplesSegment,
                    ):
                        return

                    tmpBinaryAnnotsNode.GetSegmentation().AddSegment(textureSamplesSegment)
                    tmpBinaryAnnotsNode.GetSegmentation().AddSegment(resinSamplesSegment)
                    tmpBinaryAnnotsNode.SetReferenceImageGeometryParameterFromVolumeNode(sourceVolumeNode)

                    labelsNode = Segmenter.SegmenterLogic.createLabelmapNode(
                        tmpBinaryAnnotsNode, sourceVolumeNode, soiNode=None, outputPrefix="TMP_LABELS"
                    )[0]

                    poreSegParams.update(
                        {
                            "xargs": json.dumps(
                                {
                                    "method": "bayesian-inference",
                                    "kernel": 3,
                                    "stride": 2,
                                    "kernel_type": "axes",
                                    "unsafe_memory_opt": True,
                                }
                            ),
                            "labelVolume": labelsNode.GetID(),
                        }
                    )

                self.cliQueue.create_cli_node(
                    slicer.modules.bayesianinferencecli,
                    poreSegParams,
                    progress_text=f"Detecting resin region",
                    modified_callback=hideTmpOutput if self.inputModelPath else getTrainedResinMask,
                )

                smartForegroundParams.update(
                    {
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

            self.setApplyButtonEnablement()
        except Exception as error:
            print(traceback.format_exc())
            logging.debug(f"Error: {error}.\n{traceback.format_exc()}")
            slicer.util.errorDisplay(f"Failed to apply the effect.\nError: {error}")
            onFinish()
