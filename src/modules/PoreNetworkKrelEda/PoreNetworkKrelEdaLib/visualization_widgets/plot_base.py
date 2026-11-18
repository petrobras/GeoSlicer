from abc import abstractmethod

from commons.slicer import widgets


class PlotBase(widgets.BaseSettingsWidget):
    def __init__(self):
        super().__init__()

    @abstractmethod
    def update(self, data_manager):
        pass

    @abstractmethod
    def clear_saved_plots(self):
        pass
