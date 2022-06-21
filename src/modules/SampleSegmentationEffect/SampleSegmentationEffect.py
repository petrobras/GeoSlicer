import os
import slicer
import qSlicerSegmentationsEditorEffectsPythonQt as qSlicerSegmentationsEditorEffects

from ltrace.slicer_utils import LTracePlugin


class SampleSegmentationEffect(LTracePlugin):

    SETTING_KEY = "SampleSegmentationEffect"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Sample segmentation effect"
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = ["Segmentations"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.hidden = True
        self.parent.helpText = "This hidden module registers the segment editor effect"
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = ""

    def registerEditorEffect(self):
        instance = qSlicerSegmentationsEditorEffects.qSlicerSegmentEditorScriptedEffect(None)
        effectFilename = os.path.join(os.path.dirname(__file__), self.__class__.__name__ + "Lib/SegmentEditorEffect.py")
        instance.setPythonSource(effectFilename.replace("\\", "/"))
        instance.self().register()
