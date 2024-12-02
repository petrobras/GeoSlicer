import qt
import slicer


class CustomAction(qt.QWidgetAction):
    # Define a custom signal that can be connected to any slot
    clicked = qt.Signal(bool)

    def __init__(self, icon, text, parent=None):
        super().__init__(parent)

        # Store the icon and text for later use
        self.icon = icon
        self.text = text  # if " " in text else text + "              "

        # Create a custom widget for the action
        self.widget = qt.QWidget(parent)
        self.layout = qt.QHBoxLayout()
        self.layout.setAlignment(qt.Qt.AlignLeft)  # Align content to the left initially
        self.layout.setContentsMargins(0, 2, 0, 2)

        # Create a button that holds the icon and text
        self.button = qt.QPushButton(parent)
        self.button.setIcon(self.icon)
        self.button.setFlat(True)  # Make the button look like a label without borders
        self.label = qt.QLabel(self.text)
        self.label.visible = False

        # Connect the button's clicked signal to emit the custom clicked signal
        self.button.clicked.connect(self.clicked)

        # Set up the layout
        self.layout.addWidget(self.button)
        self.layout.addWidget(self.label)
        self.widget.setLayout(self.layout)

        # Set the custom widget as the default widget for this action
        self.setDefaultWidget(self.widget)

        self.hideName()

    def showName(self):
        """Switch to text beside icon (left-aligned)."""
        self.label.visible = True  # Show the text

    def hideName(self):
        """Switch to icon only (centered)."""
        self.label.visible = False
        # self.layout.setAlignment(qt.Qt.AlignCenter)  # Center the icon

    def toggleName(self):
        """Toggle between text beside icon and icon only."""
        if self.label.visible:
            self.hideName()
        else:
            self.showName()


class CustomToolButton(qt.QToolButton):
    def __init__(self, parent):
        super().__init__(parent)

    def showName(self):
        """Switch to text beside icon (left-aligned)."""
        self.setToolButtonStyle(qt.Qt.ToolButtonTextBesideIcon)

    def hideName(self):
        """Switch to icon only (centered)."""
        self.setToolButtonStyle(qt.Qt.ToolButtonIconOnly)

    def toggleName(self):
        """Toggle between text beside icon and icon only."""
        if self.toolButtonStyle == qt.Qt.ToolButtonTextBesideIcon:
            self.hideName()
        else:
            self.showName()


def addAction(module, toolbar, root="", parent=None):
    if not parent:
        parent = toolbar
    m = getattr(slicer.modules, module.key.lower())
    button = CustomToolButton(parent)
    action = qt.QAction(m.icon, m.title, parent)
    action.setToolTip(m.title)

    def selectModule():
        slicer.util.selectModule(module.key)

    action.triggered.connect(selectModule)
    button.setDefaultAction(action)
    toolbar.addWidget(button)
    return action


def addEntry(module, menu, parent=None):
    if not parent:
        parent = menu
    m = getattr(slicer.modules, module.key.lower())
    action = qt.QAction(m.icon, m.title, parent)
    action.triggered.connect(lambda _, name=module.key: slicer.util.selectModule(name))
    # menu.setToolButtonStyle(qt.Qt.ToolButtonTextBesideIcon)
    menu.addAction(action)


def addMenu(icon, folder, modules, parent):
    toolButton = CustomToolButton(parent)
    toolButton.setIcon(icon)
    toolButton.setText(folder)
    toolButton.setToolTip(folder)

    menu = qt.QMenu(toolButton)
    for module in modules:
        addEntry(module, menu, parent)
    toolButton.setMenu(menu)

    toolButton.setPopupMode(qt.QToolButton.MenuButtonPopup)
    toolButton.clicked.connect(lambda _: toolButton.showMenu())
    parent.addWidget(toolButton)


# Future use, similar function but different name to avoid conflict


def addEntryRaw(module, menu, parent=None):
    if not parent:
        parent = menu
    action = qt.QAction(module.icon, module.title, parent)

    def selectModule():
        slicer.util.selectModule(module.name)

    action.triggered.connect(selectModule)
    # menu.setToolButtonStyle(qt.Qt.ToolButtonTextBesideIcon)
    menu.addAction(action)


def addMenuRaw(icon, folder, modules, parent):
    toolButton = CustomToolButton(parent)
    toolButton.setIcon(icon)
    toolButton.setText(folder)
    toolButton.setToolTip(folder)

    menu = qt.QMenu(toolButton)
    for module in modules:
        addEntry(module, menu, parent)
    toolButton.setMenu(menu)

    toolButton.setPopupMode(qt.QToolButton.MenuButtonPopup)
    toolButton.clicked.connect(lambda _: toolButton.showMenu())
    parent.addWidget(toolButton)


def addActionWidget(icon, title, callback=None, parent=None):
    button = CustomToolButton(parent)
    action = qt.QAction(icon, title, parent)
    action.setToolTip(title)
    action.triggered.connect(lambda tb=parent: callback(tb))
    button.setDefaultAction(action)
    parent.addWidget(button)
    return action
