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

from Models.SidewallSample import SidewallSampleWidget
from Models.Stops import StopsWidget
from Models.Islands import IslandsWidget
from Models.Snow import SnowWidget

try:
    from Test.ImageLogInstanceSegmenterTest import ImageLogInstanceSegmenterTest
except ImportError:
    ImageLogInstanceSegmenterTest = None  # tests not deployed to final version or closed source


MODEL_IMAGE_LOG_STOPS = "ImageLogStops"
MODEL_IMAGE_LOG_ISLANDS = "ImageLogIslands"
MODEL_IMAGE_LOG_SNOW = "ImageLogSnow"

MODEL_TITLES = {
    "synth_side": "Sidewall Sample Mask RCNN (trained on synthetic data)",
    "side_1": "Petrobras Sidewall Sample Mask RCNN 1",
    "side_2": "Petrobras Sidewall Sample Mask RCNN 2",
}

MODEL_IDENTIFIER = {
    "synth_side": "Synthetic",
    "side_1": "V1",
    "side_2": "V2",
}


class ImageLogInstanceSegmenter(LTracePlugin):
    SETTING_KEY = "ImageLogInstanceSegmenter"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Instance Segmenter"
        self.parent.categories = ["Segmentation", "ImageLog", "Multiscale"]
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

        LTracePluginWidget.setup(self)
        self.logic = InstanceSegmenterLogic(self.parent)

        form = qt.QFormLayout()
        form.setLabelAlignment(qt.Qt.AlignRight)
        self.layout.addLayout(form)

        models = get_trained_models("ImageLogEnv")

        self.modelComboBox = qt.QComboBox()
        self.modelComboBox.setObjectName("modelComboBox")

        # Add to stackedWidgets at the same time as adding to modelComboBox to guarantee the match
        # TODO Figure out a way for users to add custom models
        self.stackedWidgets = qt.QStackedWidget()
        for model in models:
            modelFile = model.stem
            modelName = MODEL_TITLES.get(modelFile, None)
            if modelName:
                widget = SidewallSampleWidget(ImageLogInstanceSegmenter, self, MODEL_IDENTIFIER[modelFile])
                self.stackedWidgets.addWidget(widget)
                self.modelComboBox.addItem("Image Log: " + modelName, modelFile)

        self.stopsModelWidget = StopsWidget()
        self.stackedWidgets.addWidget(self.stopsModelWidget)
        self.modelComboBox.addItem("Image Log: Batentes", MODEL_IMAGE_LOG_STOPS)

        self.islandsModelWidget = IslandsWidget(ImageLogInstanceSegmenter, self)
        self.stackedWidgets.addWidget(self.islandsModelWidget)
        self.modelComboBox.addItem("Image Log: Generic (Island)", MODEL_IMAGE_LOG_ISLANDS)

        self.snowModelWidget = SnowWidget(ImageLogInstanceSegmenter, self)
        self.stackedWidgets.addWidget(self.snowModelWidget)
        self.modelComboBox.addItem("Image Log: Generic (Watershed)", MODEL_IMAGE_LOG_SNOW)

        self.modelComboBox.setToolTip("Model to be used.")
        form.addRow("Model:", self.modelComboBox)
        form.addRow(" ", None)
        self.modelComboBox.currentTextChanged.connect(lambda _: self.updateFormFromModel())

        self.layout.addWidget(self.stackedWidgets)
        self.layout.addStretch(1)
        self.updateFormFromModel()

    def updateFormFromModel(self):
        self.stackedWidgets.setCurrentIndex(self.modelComboBox.currentIndex)

    def cleanup(self) -> None:
        LTracePluginWidget.cleanup(self)
        for idx in range(self.stackedWidgets.count):
            widget = self.stackedWidgets.widget(idx)
            widget.cleanup()


class InstanceSegmenterLogic(LTracePluginLogic):
    def __init__(self, parent):
        LTracePluginLogic.__init__(self, parent)
