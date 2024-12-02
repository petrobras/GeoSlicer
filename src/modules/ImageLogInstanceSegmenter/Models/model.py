import qt


class ModelWidget(qt.QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def cleanup(self):
        pass


class ModelLogic(qt.QObject):
    processFinished = qt.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
