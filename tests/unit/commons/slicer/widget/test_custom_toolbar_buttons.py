from commons.slicer.widget.custom_toolbar_buttons import setToolbarNamesVisible, toolbarNamesVisible


class NamedItem:
    def __init__(self):
        self.nameVisible = None

    def showName(self):
        self.nameVisible = True

    def hideName(self):
        self.nameVisible = False


class PlainItem:
    pass


class FakeToolbar:
    """Maps each action to the widget the toolbar created for it, like QToolBar.widgetForAction."""

    def __init__(self, items):
        self.items = items
        self.properties = {}

    def actions(self):
        return [action for action, _ in self.items]

    def widgetForAction(self, action):
        return dict(self.items)[action]

    def setProperty(self, name, value):
        self.properties[name] = value

    def property(self, name):
        return self.properties.get(name)


def test_names_hidden_by_default():
    assert toolbarNamesVisible(FakeToolbar([])) is False


def test_set_names_visible_updates_widgets_and_actions():
    button = NamedItem()  # e.g. CustomToolButton, section header
    widgetAction = NamedItem()  # e.g. CustomAction, whose default widget has no name methods
    separator = PlainItem()
    toolbar = FakeToolbar([(PlainItem(), button), (widgetAction, PlainItem()), (PlainItem(), separator)])

    setToolbarNamesVisible(toolbar, True)
    assert button.nameVisible is True
    assert widgetAction.nameVisible is True
    assert toolbarNamesVisible(toolbar) is True

    setToolbarNamesVisible(toolbar, False)
    assert button.nameVisible is False
    assert widgetAction.nameVisible is False
    assert toolbarNamesVisible(toolbar) is False


def test_state_does_not_depend_on_the_last_item():
    button = NamedItem()
    toolbar = FakeToolbar([(PlainItem(), button), (PlainItem(), PlainItem())])

    setToolbarNamesVisible(toolbar, True)

    assert toolbarNamesVisible(toolbar) is True
