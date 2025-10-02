import qt
import slicer
from ltrace.slicer.helpers import getSourceVolume

from ltrace.slicer_utils import getResourcePath


class Workstep:
    NAME = None
    CHECK_ICON_PATH = getResourcePath("Icons") / "png" / "GreenCheckCircle.png"
    ERROR_ICON_PATH = getResourcePath("Icons") / "png" / "RedBangCircle.png"

    INPUT_TYPES = None
    OUTPUT_TYPE = None

    # If the output type of a workstep is MATCH_INPUT_TYPE,
    # the computed output type is the same as the input type.
    MATCH_INPUT_TYPE = 1

    # The output type is MIXED_TYPE if there are nodes of different types in the input.
    # No workstep should allow this type as input or output.
    MIXED_TYPE = 2

    def __init__(self):
        if self.NAME is None:
            raise NotImplementedError
        self.defaultValues()

    def widget(self):
        raise NotImplementedError

    def defaultValues(self):
        raise NotImplementedError

    def run(self):
        raise NotImplementedError

    def expected_length(self, input_length):
        """Expected number of output nodes before execution. Can be used to update run progress."""
        return input_length

    def input_types(self):
        return self.INPUT_TYPES

    def output_type(self):
        return self.OUTPUT_TYPE

    def dump(self):
        return {"workstepName": self.NAME, **self.__dict__}

    def load(self, data):
        self.__dict__.update(data)

    def discard_input(self, input_node):
        if self.delete_inputs:
            master = getSourceVolume(input_node)
            slicer.mrmlScene.RemoveNode(input_node)
            if master:
                slicer.mrmlScene.RemoveNode(master)

    def makeSegmentsVisible(self, segmentationNode):
        displayNode = segmentationNode.GetDisplayNode()
        if displayNode is None:
            segmentationNode.CreateDefaultDisplayNodes()
            displayNode = segmentationNode.GetDisplayNode()
        displayNode.SetVisibility(True)
        for i in range(segmentationNode.GetSegmentation().GetNumberOfSegments()):
            displayNode.SetSegmentVisibility(segmentationNode.GetSegmentation().GetNthSegmentID(i), True)

    def validate(self):
        return True


class WorkstepWidget(qt.QWidget):
    def __init__(self, workstep, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.workstep = workstep
        self.setup()

    def setup(self):
        self.setLayout(qt.QVBoxLayout())

    def reset(self):
        self.workstep.defaultValues()
        self.load()

    def setComboBoxIndexByData(self, comboBox, data):
        for i in range(comboBox.count):
            comboBox.setCurrentIndex(i)
            if comboBox.currentData == data:
                return

    def load(self):
        raise NotImplementedError

    def save(self):
        raise NotImplementedError
