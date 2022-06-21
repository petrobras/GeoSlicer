from abc import abstractclassmethod
import qt
import slicer
from dataclasses import dataclass


FILE_NOT_FOUND = "FILE NOT FOUND"


@dataclass
class AnalysisReport:
    name: str
    data: object
    config: dict


class AnalysisWidgetBase(qt.QWidget):
    output_name_changed = qt.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup()

    @abstractclassmethod
    def setup(self):
        pass


class AnalysisBase:
    def __init__(self, name: str, config_widget: AnalysisWidgetBase):
        self._name = name
        self._config_widget = config_widget
        self._reports = list()

    @property
    def name(self):
        return self._name

    @property
    def config_widget(self):
        return self._config_widget

    @abstractclassmethod
    def run(self):
        pass

    @abstractclassmethod
    def get_suggested_output_name(self):
        pass

    @abstractclassmethod
    def refresh_input_report_files(self, folder):
        pass
