import pickle
import re
import time
import numpy as np
import qt
import slicer

from pathlib import Path
from queue import Queue
from threading import Thread
from dlisio import dlis as dlisio
from ltrace.slicer_utils import *
from ltrace.slicer.image_log.import_widget import WellLogImportWidget

try:
    from Test.ImageLogImportTest import ImageLogImportTest
except ImportError:
    ImageLogImportTest = None  # tests not deployed to final version or closed source


class ImageLogImport(LTracePlugin):

    SETTING_KEY = "ImageLogImport"

    def __init__(self, parent):
        super().__init__(parent)
        self.parent.title = "Image Log Import"
        self.parent.categories = ["ImageLog", "Data Importer", "Multiscale"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.acknowledgementText = """"""
        self.set_manual_path("Data_loading/load_well_log.html")


class ImageLogImportWidget(LTracePluginWidget):
    def __init__(self, parent) -> None:
        super().__init__(parent)

    def setup(self):
        super().setup()

        self.widget = WellLogImportWidget()

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        loadFormLayout = qt.QFormLayout(frame)
        loadFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        loadFormLayout.setContentsMargins(0, 0, 0, 0)

        loadFormLayout.addRow(self.widget)

        if slicer_is_in_developer_mode():
            self.reload_last_button = qt.QPushButton("Reload last configuration")
            self.reload_last_button.clicked.connect(self._on_reload_last_button_clicked)

            self.reload_last_button.setEnabled(self._get_last_load_options() is not None)
            self.layout.addWidget(self.reload_last_button)

    def _get_last_load_options(self):
        load_options = ImageLogImport.get_setting("last-load")
        if load_options is not None:
            try:
                load_options = pickle.loads(load_options.data())
            except RuntimeError:
                pass

        return load_options

    def _set_last_load_options(self, load_options):
        ImageLogImport.set_setting("last-load", qt.QByteArray(pickle.dumps(load_options)))

    def _on_reload_last_button_clicked(self):
        last_filename, last_selection, well_diameter = self._get_last_load_options()
        self._load_curves(last_filename, last_selection, well_diameter)
