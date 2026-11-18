import slicer
import numpy as np
import vtk

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events
from commons.slicer.helpers import tryGetNode


class CoreInpaintTest(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self):
        """Test case setup handler, applied before reloding the widgets"""
        self._widgets = {
            "segmentationComboBox": self.find_widget("Segmentation ComboBox"),
            "imageComboBox": self.find_widget("Image Segments ComboBox"),
            "apply": self.find_widget("Apply"),
            "outputNameLineEdit": self.find_widget("Output Name Line Edit"),
        }

        for objectName, widget in self._widgets.items():
            assert widget is not None, f"Missing widget {objectName}"

    def tear_down(self):
        pass

    def test_small_inpaint_area_should_not_raise_exception(self):
        endZ = 4
        initX = 4
        endX = 4

        imageLog = slicer.util.addVolumeFromArray(
            np.random.random((1200, 1, 360)), name="TestImageLog", nodeClassName="vtkMRMLScalarVolumeNode"
        )

        segment = np.zeros((1200, 1, 360))
        segment[:endZ, :, initX:endX] = 1

        labelmap = slicer.util.addVolumeFromArray(
            segment, name="TestLabeMap", nodeClassName="vtkMRMLLabelMapVolumeNode"
        )

        segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "TestSegmentation")
        segmentation.CreateDefaultDisplayNodes()
        segmentation.SetAttribute("ImageLogSegmentation", "True")
        segmentation.GetSegmentation().AddEmptySegment("Segment_1", "Segment_1")
        segmentation.SetReferenceImageGeometryParameterFromVolumeNode(imageLog)

        ids = vtk.vtkStringArray()
        ids.InsertNextValue("Segment_1")
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmap, segmentation, ids)

        self._widgets["segmentationComboBox"].setCurrentNode(segmentation)
        process_events()
        assert self._widgets["imageComboBox"].currentNode() is not None
        assert self._widgets["outputNameLineEdit"].text == f"{imageLog.GetName()} Inpainted", (
            f"Expected '{imageLog.GetName()} Inpainted', got '{self._widgets['outputNameLineEdit'].text}'"
        )

        try:
            self._widgets["apply"].clicked()
            process_events()
        except ZeroDivisionError:
            self.fail()

        assert tryGetNode(imageLog.GetName() + " Inpainted") is not None
