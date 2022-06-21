from typing import Tuple

import qt
import slicer
import numpy as np

from ltrace.slicer import helpers, widgets


class LitePorosityOutputWidget(qt.QFrame):
    clicked = qt.Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = qt.QHBoxLayout(self)

        self.compute_porosity_button = widgets.ActionButton("Compute Porosity", self.clicked)
        self.compute_porosity_button.objectName = f"{parent.DISPLAY_NAME} Compute Porosity Button"
        self.total_porosity_label = qt.QLabel(" Estimated porosity: ")
        self.total_porosity_output = qt.QLabel("-*- %")
        self.total_porosity_output.objectName = f"{parent.DISPLAY_NAME} Compute Porosity Output"

        layout.addWidget(self.total_porosity_label)
        layout.addWidget(self.total_porosity_output)
        layout.addWidget(self.compute_porosity_button)

        layout.addStretch(1)

    def setRunningState(self):
        self.compute_porosity_button.setEnabled(False)
        self.total_porosity_output.setText(" Running...")

    def clearState(self, default=True):
        self.compute_porosity_button.setEnabled(default)
        self.total_porosity_output.setText("")

    def setValueState(self, value):
        self.compute_porosity_button.setEnabled(True)
        self.total_porosity_output.setText(f" {value:.2f}%")

    def getState(self):
        return self.compute_porosity_button.isEnabled(), self.total_porosity_output.text


def processSegmentation(targetNode, refNode, soiNode=None) -> Tuple[str, list]:

    labelsNode, invmap = helpers.createLabelmapInput(
        segmentationNode=targetNode,
        name="segmentationMask_",
        referenceNode=refNode,
        soiNode=soiNode,
    )

    return labelsNode, invmap


def processVolume(targetNode, soiNode=None) -> str:
    if soiNode is None:
        return targetNode

    nodeSOIName = targetNode.GetName() + "_Edition"
    clonedNode = helpers.clone_volume(targetNode, nodeSOIName, copy_names=False, as_temporary=True)
    return helpers.maskInputWithROI(clonedNode, soiNode)
