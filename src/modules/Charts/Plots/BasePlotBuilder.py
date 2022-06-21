from .BasePlotWidget import BasePlotWidget
import qt


class BasePlotBuilder:
    """Class to handle pre-configurations to the plot widget, avoiding its prior creation"""

    def __init__(self, plotWidgetClass: BasePlotWidget):
        self._plotWidgetClass = plotWidgetClass
        self.TYPE = plotWidgetClass.TYPE
        self._setupConfigurationWidget()

    def build(self, **kwargs):
        """Create and returns the widget object

        Returns:
            BasePlotWidget: the widget object
        """
        return self._plotWidgetClass(**kwargs)

    def _setupConfigurationWidget(self):
        self._configurationWidget = qt.QWidget()

    def configurationWidget(self):
        return self._configurationWidget
