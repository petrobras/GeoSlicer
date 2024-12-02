import slicer
import qt

from ltrace.slicer.helpers import themeIsDark


def customize_3d_view():
    """ "
    modified by: Gabriel Muller
    commit 4dee811d6ef94128a37e85d5747a50f0bf5f5acb
    * PL-1170 3D view settings
    """
    viewWidget = slicer.app.layoutManager().threeDWidget(0)
    viewNode = viewWidget.mrmlViewNode()
    if themeIsDark():
        viewNode.SetBackgroundColor(0, 0, 0)
        viewNode.SetBackgroundColor2(0, 0, 0)
    # Hiding the purple 3D boundary box
    viewNode.SetBoxVisible(False)

    viewNode.SetAxisLabelsVisible(False)
    viewNode.SetOrientationMarkerType(slicer.vtkMRMLViewNode.OrientationMarkerTypeAxes)

    orientationMenu = viewWidget.findChild(qt.QMenu, "orientationMarkerMenu")
    for action in orientationMenu.actions():
        if action.text in ["Cube", "Human"]:
            orientationMenu.removeAction(action)
