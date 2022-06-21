import os
import string
from pathlib import Path

import qt

from ltrace.assets_utils import get_trained_models
from ltrace.slicer_utils import (
    LTracePlugin,
    LTracePluginWidget,
    LTracePluginLogic,
)

try:
    from Test.ImageLogInstanceSegmenterTest import ImageLogInstanceSegmenterTest
except ImportError:
    ImageLogInstanceSegmenterTest = None  # tests not deployed to final version or closed source


MODEL_IMAGE_LOG_STOPS = "ImageLogStops"
MODEL_IMAGE_LOG_ISLANDS = "ImageLogIslands"
MODEL_IMAGE_LOG_SNOW = "ImageLogSnow"


class ImageLogInstanceSegmenter(LTracePlugin):
    SETTING_KEY = "ImageLogInstanceSegmenter"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Image Log Instance segmenter"
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ImageLogInstanceSegmenter.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ImageLogInstanceSegmenterWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        from Models.SidewallSample import SidewallSampleWidget
        from Models.Stops import StopsWidget
        from Models.Islands import IslandsWidget
        from Models.Snow import SnowWidget

        LTracePluginWidget.setup(self)
        self.logic = InstanceSegmenterLogic()

        form = qt.QFormLayout()
        form.setLabelAlignment(qt.Qt.AlignRight)
        self.layout.addLayout(form)

        models = get_trained_models("ImageLogEnv")

        self.modelComboBox = qt.QComboBox()
        self.modelComboBox.setObjectName("modelComboBox")

        for model in models:
            modelFile = model.stem
            modelName = string.capwords(modelFile.replace("_", " "))
            self.modelComboBox.addItem("Image Log: " + modelName, modelFile)
        self.modelComboBox.addItem("Image Log: Batentes", MODEL_IMAGE_LOG_STOPS)
        self.modelComboBox.addItem("Image Log: Generic (Island)", MODEL_IMAGE_LOG_ISLANDS)
        self.modelComboBox.addItem("Image Log: Generic (Watershed)", MODEL_IMAGE_LOG_SNOW)
        self.modelComboBox.setToolTip("Model to be used.")
        form.addRow("Model:", self.modelComboBox)
        form.addRow(" ", None)
        self.modelComboBox.currentTextChanged.connect(lambda _: self.updateFormFromModel())

        self.sidewallSampleV1ModelWidget = SidewallSampleWidget(ImageLogInstanceSegmenter, self, "V1")
        self.sidewallSampleV2ModelWidget = SidewallSampleWidget(ImageLogInstanceSegmenter, self, "V2")
        self.sidewallSampleSyntheticModelWidget = SidewallSampleWidget(ImageLogInstanceSegmenter, self, "Synthetic")
        self.stopsModelWidget = StopsWidget()
        self.islandsModelWidget = IslandsWidget(ImageLogInstanceSegmenter, self)
        self.snowModelWidget = SnowWidget(ImageLogInstanceSegmenter, self)

        self.stackedWidgets = qt.QStackedWidget()
        self.stackedWidgets.addWidget(self.sidewallSampleV1ModelWidget)
        self.stackedWidgets.addWidget(self.sidewallSampleV2ModelWidget)
        self.stackedWidgets.addWidget(self.sidewallSampleSyntheticModelWidget)
        self.stackedWidgets.addWidget(self.stopsModelWidget)
        self.stackedWidgets.addWidget(self.islandsModelWidget)
        self.stackedWidgets.addWidget(self.snowModelWidget)

        self.layout.addWidget(self.stackedWidgets)
        self.layout.addStretch(1)
        self.updateFormFromModel()

    def updateFormFromModel(self):
        self.stackedWidgets.setCurrentIndex(self.modelComboBox.currentIndex)


class InstanceSegmenterLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
