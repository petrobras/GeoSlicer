import ctk
import qt
import slicer


class GlobalProgressBar(qt.QWidget):
    _instance = None

    @staticmethod
    def instance():
        if GlobalProgressBar._instance:
            return GlobalProgressBar._instance
        else:
            return GlobalProgressBar()

    def __init__(self):
        if GlobalProgressBar._instance:
            raise Exception("Instance already created!")
        else:
            super().__init__()

            self.currentCliNode = None

            layout = qt.QHBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)

            self.progressBar = slicer.qSlicerCLIProgressBar()
            self.progressBar.findChild(ctk.ctkExpandButton).setVisible(False)
            self.progressBar.setStatusVisibility(False)
            self.progressBar.setNameVisibility(False)
            self.progressBar.setMaximumHeight(25)
            self.progressBar.setMinimumHeight(25)
            self.progressBar.setMaximumWidth(400)
            self.progressBar.setMinimumWidth(400)
            newFont = self.progressBar.font
            newFont.setPixelSize(7)
            self.progressBar.setFont(newFont)

            self.toolButton = qt.QToolButton()
            self.toolButton.setToolTip("Return to the last CLI started.")
            self.toolButton.setEnabled(False)
            icon = (
                slicer.util.mainWindow().moduleSelector().findChildren(qt.QToolButton)[-2].icon
            )  # Next module tool button
            self.toolButton.setObjectName("GoBackButton")
            self.toolButton.setPopupMode(qt.QToolButton.MenuButtonPopup)
            self.toolButton.setIcon(icon)

            self.lastCLILabel = qt.QLabel()
            self.lastCLILabel.setObjectName("lastCLILabel")

            layout.addWidget(self.lastCLILabel)
            layout.addWidget(self.toolButton)
            layout.addWidget(self.progressBar)

            self.setLayout(layout)

            GlobalProgressBar._instance = self

    def setCommandLineModuleNode(self, cliNode, localProgressBar):
        GlobalProgressBar._instance.currentCliNode = cliNode
        GlobalProgressBar._instance.progressBar.setCommandLineModuleNode(cliNode)

        GlobalProgressBar._instance.toolButton.setEnabled(True)
        GlobalProgressBar._instance.toolButton.clicked.disconnect()
        GlobalProgressBar._instance.toolButton.clicked.connect(localProgressBar.returnToCLIWidget)

        GlobalProgressBar._instance.lastCLILabel.setText(
            f"Last scheduled job from: {localProgressBar.getCLIWidgetName()}"
        )

    def actionCreated(self, action):
        GlobalProgressBar._instance.toolButton.addAction(action)


class LocalProgressBar(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = qt.QFormLayout()
        self.progressBar = slicer.qSlicerCLIProgressBar()
        layout.addWidget(self.progressBar)
        self.setLayout(layout)

        self.module = None
        self.tabIndex = None
        self.subtabIndex = None

        self.scheduled = set()
        self.completed = 0
        self.running = False
        self.goBackAction = None

    def setCommandLineModuleNode(self, cliNode):

        self.module = slicer.util.mainWindow().moduleSelector().selectedModule
        self.moduleWidget = eval(f"slicer.modules.{self.module}Widget")

        try:
            self.tabIndex = self.moduleWidget.mainTab.currentIndex
            currentTab = self.moduleWidget.mainTab.widget(self.tabIndex)
            if isinstance(currentTab, qt.QTabWidget):
                self.subtabIndex = currentTab.currentIndex
            else:
                self.subtabIndex = None
        except AttributeError:  # no attribute 'mainTab'
            self.tabIndex = None
            self.subtabIndex = None

        self.scheduled.add(cliNode)
        cliNode.AddObserver("ModifiedEvent", self._onCLIModified)

        self.progressBar.setCommandLineModuleNode(cliNode)
        GlobalProgressBar.instance().setCommandLineModuleNode(cliNode, self)

        self.changeAction()

    def changeAction(self):
        widgetName = self.getCLIWidgetName()
        completedText = f" {self.completed} completed;" if self.completed else ""
        scheduledText = f" {len(self.scheduled)} scheduled;" if self.scheduled else ""
        runningText = f" 1 running;" if self.running else ""
        actionText = f"{widgetName}:{completedText}{scheduledText}{runningText}"

        if not self.goBackAction:
            self.goBackAction = qt.QAction(actionText)
            actionName = f"{self.module}{self.tabIndex}{self.subtabIndex}"
            self.goBackAction.setObjectName(actionName)
            self.goBackAction.triggered.connect(self.returnToCLIWidget)

            GlobalProgressBar.instance().actionCreated(self.goBackAction)
        else:
            self.goBackAction.setText(actionText)

        if not self.running and not self.completed and not self.scheduled:
            self.goBackAction.setVisible(False)
        else:
            self.goBackAction.setVisible(True)

    def _onCLIModified(self, cliNode, event):
        if cliNode is None:
            return

        if cliNode.GetStatusString() == "Completed" and self.running:
            self.completed += 1
            self.running = False
        elif cliNode.GetStatusString() == "Running" and cliNode in self.scheduled:
            self.scheduled.remove(cliNode)
            self.running = True

        self.changeAction()

    def getCLIWidgetName(self):
        currentModule = eval(f"slicer.modules.{self.module}Instance")
        name = currentModule.parent.title
        try:
            name += f" → {self.moduleWidget.mainTab.tabText(self.tabIndex)}"
            if self.subtabIndex != None:
                currentTab = self.moduleWidget.mainTab.widget(self.tabIndex)
                name += f" → {currentTab.tabText(self.subtabIndex)}"
        except AttributeError as e:  # no attribute 'mainTab'
            pass
        return name

    def returnToCLIWidget(self):
        moduleSelectorToolBar = slicer.util.mainWindow().findChild(slicer.qSlicerModuleSelectorToolBar)
        moduleSelectorToolBar.selectModule(self.module)
        self.completed = 0
        self.changeAction()
