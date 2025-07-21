import logging
import os

import qt
import slicer
import vtk
import qSlicerSegmentationsEditorEffectsPythonQt as effects
import traceback

from ltrace import transforms
from ltrace.slicer import helpers, ui
from ltrace.slicer_utils import LTraceSegmentEditorEffectMixin
from SegmentEditorEffects import *

import scipy.ndimage as ndi
import numpy as np


class SegmentEditorEffect(AbstractScriptedSegmentEditorEffect, LTraceSegmentEditorEffectMixin):
    def __init__(self, scriptedEffect):
        AbstractScriptedSegmentEditorEffect.__init__(self, scriptedEffect)
        scriptedEffect.name = "QEMSCAN mask"
        scriptedEffect.perSegment = False
        scriptedEffect.requireSegments = True

        self.running = False

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
            <p>Segment the area overlaid by QEMSCAN.</p>
            <p>If the input image is a thin section image, select the QEMSCAN map below. The segmentation bounds will be limited by the input's bounds.</p>
            <p>Otherwise, the input itself is interpreted as the QEMSCAN map to be segmented and the selector below cannot be changed.</p>
        </html>"""

    def setupOptionsFrame(self):
        qemscanInputFrame = qt.QFrame()
        qemscanInputLayout = qt.QHBoxLayout(qemscanInputFrame)

        # QEMSCAN combobox
        self.qemscanInputLabel = qt.QLabel("QEMSCAN:")
        qemscanInputLayout.addWidget(self.qemscanInputLabel)

        self.qemscanInput = ui.hierarchyVolumeInput(
            hasNone=True,
            nodeTypes=[
                "vtkMRMLLabelMapVolumeNode",
            ],
            tooltip="Input QEMSCAN.",
            onChange=self.updateApplyButtonEnablement,
            onActivation=self.updateApplyButtonEnablement,
        )
        self.qemscanInput.objectName = "QEMSCAN Mask QEMSCAN ComboBox"
        qemscanInputLayout.addWidget(self.qemscanInput)

        self.scriptedEffect.addOptionsWidget(qemscanInputFrame)

        # Apply button
        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setMinimumHeight(25)
        self.applyButton.objectName = "QEMSCAN Mask Apply Button"
        self.applyButton.connect("clicked()", self.onApply)
        self.scriptedEffect.addOptionsWidget(self.applyButton)

        self.updateApplyButtonEnablement()

    def createCursor(self, widget):
        # Turn off effect-specific cursor for this effect
        return slicer.modules.AppContextInstance.mainWindow.cursor

    def onSourceVolumeNodeChanged(self):
        parameterSetNode = self.scriptedEffect.parameterSetNode()
        sourceVolumeNode = parameterSetNode.GetSourceVolumeNode() if parameterSetNode is not None else None

        if sourceVolumeNode is not None:
            if sourceVolumeNode.IsA(slicer.vtkMRMLLabelMapVolumeNode.__name__):
                qemscanInputEnabled = False
                self.qemscanInput.setCurrentNode(sourceVolumeNode)
            else:
                qemscanInputEnabled = True
        else:
            qemscanInputEnabled = False

        self.qemscanInput.setEnabled(qemscanInputEnabled)

    def updateApplyButtonEnablement(self):
        self.applyButton.setEnabled((not self.running) and (self.qemscanInput.currentNode() is not None))

    def cropMaskOnInputBounds(self, mask, sourceVolumeNode, qemscanNode):
        sourceVolumeRASToIJKMatrix = vtk.vtkMatrix4x4()
        sourceVolumeNode.GetRASToIJKMatrix(sourceVolumeRASToIJKMatrix)

        sourceVolumeRASBounds = np.zeros(6)
        sourceVolumeNode.GetRASBounds(sourceVolumeRASBounds)
        sourceVolumeIJKBounds = transforms.transformPoints(
            sourceVolumeRASToIJKMatrix, sourceVolumeRASBounds.reshape((3, 2)).T, returnInt=True
        )

        qemscanRASBounds = np.zeros(6)
        qemscanNode.GetRASBounds(qemscanRASBounds)
        qemscanIJKBoundsSourceRef = transforms.transformPoints(
            sourceVolumeRASToIJKMatrix, qemscanRASBounds.reshape((3, 2)).T, returnInt=True
        )  # must be reference's matrix and not QEMSCAN's matrix, or else the QEMSCAN's bounds will be reset from 0

        xMinS = sourceVolumeIJKBounds[:, 0].min()
        xMaxS = sourceVolumeIJKBounds[:, 0].max()
        yMinS = sourceVolumeIJKBounds[:, 1].min()
        yMaxS = sourceVolumeIJKBounds[:, 1].max()

        xMinQ = qemscanIJKBoundsSourceRef[:, 0].min()
        xMaxQ = qemscanIJKBoundsSourceRef[:, 0].max()
        yMinQ = qemscanIJKBoundsSourceRef[:, 1].min()
        yMaxQ = qemscanIJKBoundsSourceRef[:, 1].max()

        left_dx = slice(0, max(0, xMinS - xMinQ))
        right_dx = slice(min(xMaxQ - xMinQ, xMaxS - xMinQ), None)
        top_dy = slice(0, max(0, yMinS - yMinQ))
        bottom_dy = slice(min(yMaxQ - yMinQ, yMaxS - yMinQ), None)

        mask[:, left_dx] = 0
        mask[:, right_dx] = 0
        mask[top_dy] = 0
        mask[bottom_dy] = 0

        return mask

    def onApply(self):
        try:
            self.running = True
            self.updateApplyButtonEnablement()

            sourceVolumeNode = self.scriptedEffect.parameterSetNode().GetSourceVolumeNode()
            qemscanNode = self.qemscanInput.currentNode()

            qemscanLabels = helpers.extractLabels(qemscanNode)
            othersClassIndex = next((i for i, l in qemscanLabels.items() if l == "Outros"), -1)

            mask = slicer.util.arrayFromVolume(qemscanNode)[0] != othersClassIndex
            mask = ndi.binary_fill_holes(mask)

            if sourceVolumeNode is not qemscanNode:
                mask = self.cropMaskOnInputBounds(mask, sourceVolumeNode, qemscanNode)

            helpers.modifySelectedSegmentByMaskArray(self.scriptedEffect, mask, qemscanNode)

            self.scriptedEffect.saveStateForUndo()

            # De-select effect
            self.scriptedEffect.selectEffect("")

            self.running = False
        except Exception as error:
            logging.error(f"Error: {error}.\n{traceback.format_exc()}")
            slicer.util.errorDisplay(f"Failed to apply the effect.\nError: {error}")
            self.running = False
        finally:
            self.updateApplyButtonEnablement()
