import ctk
import vtk
import os
import qt
import slicer
import xarray as xr
import numpy as np
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget
from ltrace.slicer.helpers import save_path
from ltrace.slicer.netcdf import import_file

from importlib import reload
from pathlib import Path


class NetCDFLoader(LTracePlugin):
    SETTING_KEY = "NetCDFLoader"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "NetCDF Loader"
        self.parent.categories = ["Tools", "MicroCT"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = NetCDFLoader.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class NetCDFLoaderWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)

        self.file_selector = ctk.ctkPathLineEdit()
        self.file_selector.nameFilters = ["NetCDF / HDF5 files (*.nc *.h5 *.hdf5)"]
        self.file_selector.settingKey = "NetCDFLoader/LoadPath"

        self.apply_button = qt.QPushButton("Load")
        self.apply_button.setFixedHeight(40)

        self.progress_bar = qt.QProgressBar()
        self.progress_bar.visible = False
        self.status_label = qt.QLabel()
        self.status_label.visible = False
        self.status_label.setAlignment(qt.Qt.AlignRight)

        self.file_selector.validInputChanged.connect(self.apply_button.setEnabled)
        self.apply_button.setEnabled(False)
        path = self.file_selector.currentPath
        self.file_selector.setCurrentPath("not_a_path")
        self.file_selector.setCurrentPath(path)

        self.apply_button.clicked.connect(self.on_apply)

        form_layout = qt.QFormLayout()
        form_layout.addRow("NetCDF file:", self.file_selector)

        self.layout.addLayout(form_layout)
        self.layout.addWidget(self.progress_bar)
        self.layout.addWidget(self.status_label)
        self.layout.addWidget(self.apply_button)
        self.layout.addStretch(1)

    def on_apply(self):
        self.apply_button.setEnabled(False)
        try:
            self.on_progress("Importing…", 0)
            dataset_path = Path(self.file_selector.currentPath)
            save_path(self.file_selector)
            import_file(dataset_path, self.on_progress)

            self.on_progress("Import complete", 1)

        except Exception as e:
            message = f"Import failed: {e}"
            slicer.util.errorDisplay(message)
            self.status_label.setText(message)
            raise e
        finally:
            self.apply_button.setEnabled(True)

    def on_progress(self, message, progress):
        self.progress_bar.visible = True
        self.status_label.visible = True
        self.status_label.setText(message)
        self.progress_bar.setValue(progress * 100)
        slicer.app.processEvents()
