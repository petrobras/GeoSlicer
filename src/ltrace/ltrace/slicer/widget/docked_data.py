import logging

import slicer
import qt

from ltrace.constants import ImageLogConst


class DockedData(qt.QDockWidget):
    def __init__(self):
        super().__init__("Explorer")

        try:
            self.default_data = slicer.modules.customizeddata.createNewWidgetRepresentation()
            self.image_log_data = slicer.modules.imagelogdata.createNewWidgetRepresentation()
        except AttributeError:
            logging.warn("CustomizedData and ImageLogData modules are not available yet.")
            self.default_data = None
            self.image_log_data = None

        slicer.app.layoutManager().layoutChanged.connect(self.on_layout_changed)
        self.on_layout_changed()

        self.setAllowedAreas(qt.Qt.AllDockWidgetAreas)
        main_window = slicer.util.mainWindow()
        main_window.addDockWidget(qt.Qt.RightDockWidgetArea, self)

    def on_layout_changed(self):
        current_layout = slicer.app.layoutManager().layout
        if current_layout >= ImageLogConst.DEFAULT_LAYOUT_ID_START_VALUE:
            data_widget = self.image_log_data
        else:
            data_widget = self.default_data

        if data_widget is not None:
            self.setWidget(data_widget)
