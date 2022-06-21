import os
import vtk, qt, ctk, slicer


from ltrace.slicer_utils import LTracePlugin


class CustomizedSmoothingEffect(LTracePlugin):

    SETTING_KEY = "CustomizedSmoothingEffect"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Customized Smoothing Effect"
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = ["Segmentations"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.hidden = True
        self.parent.helpText = "This hidden module registers the segment editor effect"
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = ""

    def registerEditorEffect(self):
        import qSlicerSegmentationsEditorEffectsPythonQt as qSlicerSegmentationsEditorEffects

        instance = qSlicerSegmentationsEditorEffects.qSlicerSegmentEditorScriptedPaintEffect(None)
        effectFilename = os.path.join(
            os.path.dirname(__file__), self.__class__.__name__ + "Lib/SegmentEditorSmoothingEffect.py"
        )
        instance.setPythonSource(effectFilename.replace("\\", "/"))
        instance.self().register()
