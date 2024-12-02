import slicer
import qt


def customLayout(layoutID, layoutXML, name, iconPath):
    layoutManager = slicer.app.layoutManager()
    layoutManager.layoutLogic().GetLayoutNode().AddLayoutDescription(layoutID, layoutXML)

    # Add button to layout selector toolbar for this custom layout
    viewToolBar = slicer.modules.AppContextInstance.mainWindow.findChild("QToolBar", "ViewToolBar")
    layoutMenu = viewToolBar.widgetForAction(viewToolBar.actions()[0]).menu()
    layoutSwitchActionParent = layoutMenu
    layoutSwitchAction = layoutSwitchActionParent.addAction(name)  # add inside layout list
    layoutSwitchAction.setData(layoutID)
    layoutSwitchAction.setIcon(qt.QIcon(str(iconPath)))
    layoutSwitchAction.connect(
        "triggered()",
        lambda layoutId=layoutID: slicer.app.layoutManager().setLayout(layoutId),
    )
