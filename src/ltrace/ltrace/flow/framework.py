from abc import ABC, abstractmethod
from ltrace.slicer import helpers
import ctk
import qt
import slicer


class UnstackedWidget(qt.QFrame):
    """QStackedWidget's size is the maximum size of its children.
    This widget is a workaround to make the size of the widget the size of the current child.
    """

    def __init__(self, parent=None):
        qt.QFrame.__init__(self, parent)
        self.setLayout(qt.QVBoxLayout())
        self._widgets = []
        self._currentWidget = None

    def addWidget(self, widget):
        self.layout().addWidget(widget)
        self._widgets.append(widget)
        widget.visible = False

    def setCurrentIndex(self, index):
        if self._currentWidget:
            self._currentWidget.visible = False
        self._currentWidget = self._widgets[index]
        self._currentWidget.visible = True


class HoverEventFilter(qt.QObject):
    itemHovered = qt.Signal(int)

    def eventFilter(self, obj, event):
        if event.type() == qt.QEvent.HoverMove:
            item = obj.itemAt(event.pos())
            if item:
                self.itemHovered.emit(obj.row(item))
        if event.type() == qt.QEvent.HoverLeave:
            selected = obj.selectedItems()
            if selected:
                self.itemHovered.emit(obj.row(selected[0]))
        return False


class NavWidget(qt.QGroupBox):
    def __init__(self):
        super().__init__()
        flowLayout = qt.QHBoxLayout(self)
        self.backButton = qt.QPushButton("\u2190 Back")
        self.backButton.setFixedHeight(40)
        self.skipButton = qt.QPushButton("Skip \u21d2")
        self.skipButton.setFixedHeight(40)
        self.nextButton = qt.QPushButton("Next \u2192")
        self.nextButton.setProperty("class", "actionButtonBackground")
        self.nextButton.setFixedHeight(40)

        flowLayout.addWidget(self.backButton, 1)
        flowLayout.addStretch(1)
        flowLayout.addWidget(self.skipButton, 1)
        flowLayout.addWidget(self.nextButton, 1)


class OverviewSection(ctk.ctkCollapsibleButton):
    def __init__(self):
        super().__init__()

        self.text = "Step-by-step Overview"
        stepListLayout = qt.QHBoxLayout(self)

        self.stepList = qt.QListWidget()
        isDark = helpers.themeIsDark()
        self.stepList.setStyleSheet(
            f"""
            QListView {{
                outline: none;
            }}
            QListWidget::item {{
                padding: 4px; 
                border: 0px;
                outline: none;
            }}
            QListWidget::item:selected {{
                padding-left: 10px;
                font-weight: bold;
                background-color: {'#37403A' if isDark else '#d9ebff'};
                border-left: 6px solid #26C252;
                color: {'#ffffff' if isDark else '#000000'};
            }}
            QListWidget::item:hover {{
                background-color: {'#37403A' if isDark else '#d9ebff'};
            }}
        """
        )

        stepListLayout.addWidget(self.stepList)
        stepListLayout.setSpacing(5)

        self.helpLabel = qt.QLabel()
        self.helpLabel.setWordWrap(True)
        self.helpLabel.setAlignment(qt.Qt.AlignTop)
        self.helpLabel.setStyleSheet("margin: 10px;")
        self.helpScrollArea = qt.QScrollArea()
        self.helpScrollArea.setWidget(self.helpLabel)
        self.helpScrollArea.setWidgetResizable(True)

        stepListLayout.addWidget(self.helpScrollArea, 1)


class CurrentStepSection(ctk.ctkCollapsibleButton):
    def __init__(self):
        super().__init__()
        self.text = "Current Step"
        moduleLayout = qt.QVBoxLayout(self)

        self.stepsWidget = UnstackedWidget()
        moduleLayout.addWidget(self.stepsWidget)


class FlowWidget(qt.QFrame):
    def __init__(self, steps, state):
        super().__init__()
        layout = qt.QVBoxLayout(self)

        self.overviewSection = OverviewSection()
        layout.addWidget(self.overviewSection)
        layout.addSpacing(15)

        self.currentStepSection = CurrentStepSection()
        layout.addWidget(self.currentStepSection)

        self.navWidget = NavWidget()
        layout.addWidget(self.navWidget)

        layout.addStretch(1)

        self.stepKeyToIndex = {}
        for i, step in enumerate(steps):
            self.stepKeyToIndex[step.KEY] = i
        stepList = self.overviewSection.stepList

        navHandle = NavHandle(self.navWidget, stepList)

        self.state = state
        self.steps = steps
        self.currentStepIndex = -1

        for i, step in enumerate(self.steps):
            step.initialize(self.state, navHandle)
            stepList.addItem(f"{i + 1}. {step.TITLE}")
            self.currentStepSection.stepsWidget.addWidget(step.widget)
        stepList.setMinimumHeight(stepList.sizeHintForRow(0) * (len(self.steps) + 1))
        stepList.setMaximumWidth(150)

        hoverFilter = HoverEventFilter()
        hoverFilter.setParent(self.overviewSection.stepList)
        stepList.installEventFilter(hoverFilter)
        hoverFilter.itemHovered.connect(lambda row: self.onUpdateHelp(self.steps[row].HELP))
        stepList.currentRowChanged.connect(self.onStepChange)
        stepList.setCurrentRow(0)

        self.navWidget.backButton.clicked.connect(lambda: stepList.setCurrentRow(stepList.currentRow - 1))
        self.navWidget.skipButton.clicked.connect(lambda: stepList.setCurrentRow(stepList.currentRow + 1))
        self.navWidget.nextButton.clicked.connect(lambda: self.steps[stepList.currentRow].next())

        self.__closeSceneObserverHandler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.StartCloseEvent, self.onCloseScene
        )
        self.destroyed.connect(self.__del__)

    def __del__(self):
        slicer.mrmlScene.RemoveObserver(self.__closeSceneObserverHandler)

    def updateAvailableSteps(self):
        availableSteps = self.state.availableSteps()
        indices = [self.stepKeyToIndex[key] for key in availableSteps]
        for i in range(len(self.steps)):
            item = self.overviewSection.stepList.item(i)
            if i in indices:
                item.setFlags(item.flags() | qt.Qt.ItemIsEnabled)
            else:
                item.setFlags(item.flags() & ~qt.Qt.ItemIsEnabled)

    def onUpdateHelp(self, text):
        self.overviewSection.helpLabel.setText(text)

    def onStepChange(self, nextWidgetIndex):
        self.updateAvailableSteps()
        if self.currentStepIndex >= 0:
            self.steps[self.currentStepIndex].exit()
        self.steps[nextWidgetIndex].enter()
        self.onUpdateHelp(self.steps[nextWidgetIndex].HELP)
        self.currentStepSection.stepsWidget.setCurrentIndex(nextWidgetIndex)
        self.currentStepIndex = nextWidgetIndex

    def onCloseScene(self, *args, **kwargs):
        try:
            self.state.reset()
            self.overviewSection.stepList.setCurrentRow(0)
        except Exception:
            pass  # avoid run after widget being deleted

    def enter(self):
        self.steps[self.currentStepIndex].enter()

    def exit(self):
        self.steps[self.currentStepIndex].exit()


class NavHandle:
    """Allows steps to navigate the interface in a limited way."""

    def __init__(self, navWidget, stepListWidget):
        self._navWidget = navWidget
        self._stepListWidget = stepListWidget

    def setButtonsState(self, backState, skipState, nextState):
        self._navWidget.backButton.enabled = backState[0]
        self._navWidget.skipButton.enabled = skipState[0]
        self._navWidget.nextButton.enabled = nextState[0]

        self._navWidget.backButton.setToolTip(backState[1])
        self._navWidget.skipButton.setToolTip(skipState[1])
        self._navWidget.nextButton.setToolTip(nextState[1])

    def next(self):
        self._stepListWidget.setCurrentRow((self._stepListWidget.currentRow + 1) % self._stepListWidget.count)


class FlowState(ABC):
    def __init__(self):
        self.reset()

    @abstractmethod
    def reset(self):
        pass

    @abstractmethod
    def availableSteps(self):
        pass


class FlowStep(ABC):
    HELP = None
    KEY = None
    TITLE = None

    def initialize(self, state: FlowState, navHandle: NavHandle):
        self.state = state
        self.nav = navHandle
        self.widget = self.setup()

    @abstractmethod
    def setup(self):
        pass

    @abstractmethod
    def enter(self):
        pass

    @abstractmethod
    def exit(self):
        pass

    @abstractmethod
    def next(self):
        pass
