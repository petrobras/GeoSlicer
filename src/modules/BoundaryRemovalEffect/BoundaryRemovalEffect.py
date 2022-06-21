import os

import slicer
from ltrace.slicer_utils import LTracePlugin


class BoundaryRemovalEffect(LTracePlugin):

    SETTING_KEY = "BoundaryRemovalEffect"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Boundary removal effect"
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = ["Segmentations"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.hidden = True
        self.parent.helpText = "This hidden module registers the segment editor effect"
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = ""

    def registerEditorEffect(self):
        import qSlicerSegmentationsEditorEffectsPythonQt as qSlicerSegmentationsEditorEffects

        instance = qSlicerSegmentationsEditorEffects.qSlicerSegmentEditorScriptedEffect(None)
        effectFilename = os.path.join(os.path.dirname(__file__), self.__class__.__name__ + "Lib/SegmentEditorEffect.py")
        instance.setPythonSource(effectFilename.replace("\\", "/"))
        instance.self().register()