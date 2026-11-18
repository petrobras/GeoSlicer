from __main__ import qt
from commons.slicer_utils import LTracePluginWidget, LTracePlugin
from commons.slicer_utils import LTracePluginLogic


class DummyModule(LTracePlugin):
    SETTING_KEY = "Dummy Module"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Dummy Module"
        self.parent.categories = ["MicroCT"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ""
        self.parent.acknowledgementText = ""


class DummyModuleWidget(LTracePluginWidget):
    def setup(self):
        LTracePluginWidget.setup(self)

        for i in range(10):
            self.layout.addWidget(qt.QLabel("Hello World!"))
        self.layout.addStretch(1)


class DummyModuleLogic(LTracePluginLogic):
    pass
