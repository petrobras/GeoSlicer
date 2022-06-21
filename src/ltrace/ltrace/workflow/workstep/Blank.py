import qt
from ltrace.workflow.workstep import Workstep, WorkstepWidget


class Blank(Workstep):
    NAME = "Blank"

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        pass

    def widget(self):
        return BlankWidget(self)


class BlankWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)

        formLayout = qt.QFormLayout()
        formLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.layout().addLayout(formLayout)

        textEdit = qt.QPlainTextEdit()
        textEdit.viewport().setAutoFillBackground(False)
        textEdit.setFrameStyle(qt.QFrame.NoFrame)
        textEdit.setReadOnly(True)
        textEdit.setPlainText("There are no worksteps.")

        formLayout.addRow(textEdit)

    def save(self):
        pass

    def load(self):
        pass
