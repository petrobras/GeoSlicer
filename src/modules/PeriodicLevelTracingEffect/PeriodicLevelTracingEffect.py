import os

from ltrace.slicer_utils import LTracePlugin


class PeriodicLevelTracingEffect(LTracePlugin):
    SETTING_KEY = "PeriodicLevelTracingEffect"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Periodic Level Tracing Effect"
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = ["Segmentations"]
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.hidden = True
        self.parent.helpText = "This hidden module registers the periodic level tracing segment editor effect"
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = ""

    def registerEditorEffect(self):
        import qSlicerSegmentationsEditorEffectsPythonQt as effects

        instance = effects.qSlicerSegmentEditorScriptedEffect(None)
        effectFilename = os.path.join(os.path.dirname(__file__), self.__class__.__name__ + "Lib/SegmentEditorEffect.py")
        instance.setPythonSource(effectFilename.replace("\\", "/"))
        instance.self().register()
