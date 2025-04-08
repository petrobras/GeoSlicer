import slicer
import qt

from ltrace.constants import ImageLogConst
from ltrace.slicer.application_observables import ApplicationObservables
from typing import Union


def tryGetWidget(moduleName: str, copyWidget: bool = True) -> Union["LTracePluginWidget", None]:
    module = getattr(slicer.modules, moduleName, None)

    if not module:
        return None

    if copyWidget:
        oldModuleWidget = module.widgetRepresentation()
        newModuleWidget = module.createNewWidgetRepresentation()
        setattr(slicer.modules, f"{oldModuleWidget.self().moduleName}Widget", oldModuleWidget.self())
        setattr(slicer.modules, f"{oldModuleWidget.self().moduleName}DockedWidget", newModuleWidget.self())
        return newModuleWidget

    return module.widgetRepresentation()


class DockedData(qt.QDockWidget):
    def __init__(self):
        super().__init__("")
        self.objectName = "Docked Data"
        self.tabs = None

        self.setAllowedAreas(qt.Qt.AllDockWidgetAreas)
        ApplicationObservables().applicationLoadFinished.connect(self.__onApplicationLoadFinished)

    def __onApplicationLoadFinished(self):
        ApplicationObservables().applicationLoadFinished.disconnect(self.__onApplicationLoadFinished)
        self.setupUI()

    def __createImageLogDataWidget(self):
        self.imageLogData = self._createScrollableWidget("imagelogdata")
        if self.imageLogData is not None:
            self.stackedWidget.addWidget(self.imageLogData)

    def setupUI(self):
        self.defaultData = self._createScrollableWidget("customizeddata")
        self.jobMonitorWidget = self._createScrollableWidget("jobmonitor", copyWidget=False)
        self.stackedWidget = qt.QStackedWidget()
        self.stackedWidget.addWidget(self.defaultData)
        self.__createImageLogDataWidget()
        self.stackedWidget.setCurrentWidget(self.defaultData)
        self.tabs = qt.QTabWidget()
        self.tabs.addTab(self.stackedWidget, "Explorer")
        self.tabs.addTab(self.jobMonitorWidget, "Remote Jobs")

        mainWindow = slicer.modules.AppContextInstance.mainWindow
        mainWindow.addDockWidget(qt.Qt.RightDockWidgetArea, self)

        self.setWidget(self.tabs)
        slicer.app.layoutManager().layoutChanged.connect(self.onLayoutChanged)
        self.onLayoutChanged(slicer.app.layoutManager().layout)

    def _createScrollableWidget(self, pluginWidgetName: str, copyWidget: bool = True) -> qt.QScrollArea:
        """Method to wrap the plugin's widget to a scroll area

        Args:
            pluginWidget (LTracePluginWidget): the plugin's widget object.

        Returns:
            qt.QScrollArea: the scroll area widget object.
        """
        newWidgetRepresentation = tryGetWidget(pluginWidgetName, copyWidget)
        if not newWidgetRepresentation:
            return None

        scroll = qt.QScrollArea()
        scroll.setVerticalScrollBarPolicy(qt.Qt.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAsNeeded)
        scroll.setWidgetResizable(True)
        scroll.setWidget(newWidgetRepresentation)

        return scroll

    def setCurrentWidget(self, index: int):
        if self.tabs is None:
            return

        self.tabs.setCurrentIndex(index)

    def onLayoutChanged(self, currentLayout):
        explorerWidget = self.defaultData
        if currentLayout >= ImageLogConst.DEFAULT_LAYOUT_ID_START_VALUE:
            if self.imageLogData is None:
                self.__createImageLogDataWidget()

            explorerWidget = self.imageLogData

        if explorerWidget is not None:
            self.stackedWidget.setCurrentWidget(explorerWidget)
