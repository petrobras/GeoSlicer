import qt

from ltrace.slicer.helpers import singleton


@singleton
class ApplicationObservables(qt.QObject):
    applicationLoadFinished = qt.Signal()
    aboutToQuit = qt.Signal()
    moduleWidgetEnter = qt.Signal(object)
    environmentChanged = qt.Signal()
