import os
from pathlib import Path
import uuid

import ctk
import qt
import slicer

from ltrace.slicer import ui
from ltrace.slicer.helpers import (
    createLabelmapInput,
    createTemporaryNode,
    makeTemporaryNodePermanent,
    removeTemporaryNodes,
    tryGetNode,
)
from ltrace.slicer.node_attributes import Tag
from ltrace.slicer.widget.global_progress_bar import GlobalProgressBar
from ltrace.slicer_utils import LTracePlugin, LTracePluginLogic, LTracePluginWidget

import random


class SegmentationKmeans(LTracePlugin):
    SETTING_KEY = "SegmentationKmeans"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Segmentation Kmeans"
        self.parent.categories = ["Tools"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = SegmentationKmeans.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class SegmentationKmeansWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)

        # Input section
        input_section = ctk.ctkCollapsibleButton()
        input_section.collapsed = False
        input_section.text = "Input"

        self.__input_selector = ui.volumeInput(
            onChange=self.__on_input_node_changed,
            hasNone=True,
            nodeTypes=["vtkMRMLScalarVolumeNode"],
        )
        self.__input_selector.showChildNodeTypes = False
        self.__input_selector.setMRMLScene(slicer.mrmlScene)
        self.__input_selector.setToolTip("Pick a scalar volume node")

        input_layout = qt.QFormLayout(input_section)
        input_layout.addRow("Input:", self.__input_selector)

        # Parameters section
        parameters_section = ctk.ctkCollapsibleButton()
        parameters_section.text = "Parameters"
        parameters_section.collapsed = False
        parameters_section.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        self.__spacing_spin_box = qt.QLineEdit()
        self.__spacing_spin_box.setText("1, 1, 1")
        self.__radii_spin_box = qt.QLineEdit()
        self.__radii_spin_box.setText("3, 5")
        self.__classes_spin_box = qt.QSpinBox()
        self.__classes_spin_box.setValue(5)
        self.__threads_spin_box = qt.QSpinBox()
        self.__threads_spin_box.setValue(8)
        parameters_layout = qt.QFormLayout(parameters_section)
        parameters_layout.addRow("spacing:", self.__spacing_spin_box)
        parameters_layout.addRow("radii:", self.__radii_spin_box)
        parameters_layout.addRow("classes:", self.__classes_spin_box)
        parameters_layout.addRow("threads:", self.__threads_spin_box)

        # Output section
        output_section = ctk.ctkCollapsibleButton()
        output_section.text = "Output"
        output_section.collapsed = False

        self.__output_prefix_line_edit = qt.QLineEdit()
        self.__output_prefix_line_edit.objectName = "Output Prefix Line Edit"
        outputFormLayout = qt.QFormLayout(output_section)
        outputFormLayout.addRow("Output prefix:", self.__output_prefix_line_edit)

        # Apply button
        self.__apply_button = ui.ApplyButton(
            onClick=self.__on_apply_button_clicked, tooltip="Apply changes", enabled=True
        )
        self.__apply_button.objectName = "Apply Button"

        # CLI progress bar
        self.__cli_progress_bar = GlobalProgressBar.instance()

        # Update layout
        self.layout.addWidget(input_section)
        self.layout.addWidget(parameters_section)
        self.layout.addWidget(output_section)
        self.layout.addWidget(self.__apply_button)
        self.layout.addWidget(self.__cli_progress_bar)
        self.layout.addStretch(1)

    def __on_apply_button_clicked(self, state):
        if self.__output_prefix_line_edit.text.strip() == "":
            slicer.util.errorDisplay("Please type an output prefix.")
            return

        if self.__input_selector.currentNode() is None:
            slicer.util.errorDisplay("Please select an input node.")
            return

        data = {
            "input_node": self.__input_selector.currentNode(),
            "spacing": self.__spacing_spin_box.text,
            "radii": self.__radii_spin_box.text,
            "classes": self.__classes_spin_box.value,
            "threads": self.__threads_spin_box.value,
            "output_prefix": self.__output_prefix_line_edit.text,
        }

        logic = SegmentationKmeansLogic()
        logic.apply(data=data, progress_bar=self.__cli_progress_bar)

    def __on_input_node_changed(self, vtk_id):
        node = self.__input_selector.currentNode()
        if node is None:
            return

        self.__output_prefix_line_edit.text = node.GetName()


class SegmentationKmeansLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.__cli_node = None
        self.__cli_node_modified_observer = None

    def apply(self, data, progress_bar=None):
        tag = Tag(str(uuid.uuid4()))

        self.data = data

        input_volume = data["input_node"]
        output_volume = createTemporaryNode(
            cls=slicer.vtkMRMLLabelMapVolumeNode,
            name=f"{data['output_prefix']}_Output_LabelMap",
            environment=tag,
            hidden=True,
        )

        cli_config = {
            "input_volume": input_volume.GetID(),
            "spacing": data["spacing"],
            "radii": data["radii"],
            "classes": data["classes"],
            "threads": data["threads"],
            "output_volume": output_volume.GetID(),
        }

        self.__cli_node = slicer.cli.run(
            slicer.modules.segmentationkmeanscli,
            None,
            cli_config,
            wait_for_completion=False,
        )
        self.__cli_node_modified_observer = self.__cli_node.AddObserver(
            "ModifiedEvent", lambda c, ev, info=cli_config: self.__on_cli_modified_event(c, ev, info)
        )

        if progress_bar is not None:
            progress_bar.setCommandLineModuleNode(self.__cli_node)

    def __on_cli_modified_event(self, caller, event, info):
        if caller is None:
            self.__cli_node = None
            return

        if caller.IsBusy():
            return

        if caller.GetStatusString() == "Completed":
            output_volume_node = tryGetNode(info["output_volume"])
            makeTemporaryNodePermanent(output_volume_node, show=True)

            # Create segmentation from labelmap
            seg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
            slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(output_volume_node, seg)
            seg.CreateClosedSurfaceRepresentation()

            # Change segment names
            unique_name = slicer.mrmlScene.GetUniqueNameByString(f"{self.data['output_prefix']}_Segmentation")
            seg.SetName(unique_name)
            segmentation = seg.GetSegmentation()
            for i in range(0, info["classes"]):
                segment = segmentation.GetNthSegment(i)
                segment.SetName(f"Segment_{i+1}")

            slicer.mrmlScene.RemoveNode(output_volume_node)

            slicer.util.setSliceViewerLayers(background=info["input_volume"], fit=True)
        else:
            removeTemporaryNodes(environment=self.__class__.__name__)

        if self.__cli_node_modified_observer is not None:
            self.__cli_node.RemoveObserver(self.__cli_node_modified_observer)
            self.__cli_node_modified_observer = None

        del self.__cli_node
        self.__cli_node = None
