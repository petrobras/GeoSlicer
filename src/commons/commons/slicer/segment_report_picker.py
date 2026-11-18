"""Pick mode: click a segment in a slice view to see its row of the Segment Inspector report.

A checkable button in the mouse mode toolbar turns the mode on, using Slicer's "User" interaction mode so that the other
mouse modes turn it off. A click on a segment shows a summary of its report row in a tooltip; Ctrl+click shows the
report and selects the row, in the Explorer or, for reports too large to preview, in the layout's table view.
"""

import html
import logging
import math

import numpy as np
import qt
import slicer
import vtk
from vtk.util.numpy_support import vtk_to_numpy

from commons.constants import TABLE_PREVIEW_MAX_ROWS
from commons.slicer.application_observables import ApplicationObservables
from commons.slicer.helpers import singleton, svgToQIcon
from commons.slicer.segment_report_navigator import LABEL_COLUMN, SegmentReportNavigator, labelMapReport
from commons.slicer_utils import getResourcePath

# Report columns the tooltip shows, when present, in this order. The label and the size class go in its title.
SUMMARY_COLUMNS_2D = ("area", "max_feret", "min_feret", "aspect_ratio", "coordination_number")
SUMMARY_COLUMNS_3D = (
    "volume",
    "max_feret",
    "sphere_diameter_from_volume",
    "aspect_ratio",
    "elongation",
    "flatness",
    "coordination_number",
)
SIZE_CLASS_COLUMN = "pore_size_class"

# A press and release farther apart than this, in pixels, is a drag, not a click
CLICK_TOLERANCE = 4

# How long status bar messages stay, in milliseconds
MESSAGE_TIMEOUT = 5000


def split_unit(column: str) -> tuple:
    """Split a report column into its name and unit: "area (mm^2)" gives ("area", "mm²"), "label" gives ("label", "")."""
    name, _, unit = column.partition(" (")
    return name, unit.rstrip(")").replace("^2", "²").replace("^3", "³")


def format_value(text: str) -> str:
    """A cell's text with numbers shortened to 4 significant digits."""
    try:
        return f"{float(text):.4g}"
    except ValueError:
        return text


def segment_summary(label: int, row: dict) -> str:
    """Tooltip text (rich text) summarizing a report row, given as {column: cell text}."""
    columns = {split_unit(column)[0]: column for column in row}
    summary_columns = SUMMARY_COLUMNS_3D if "volume" in columns else SUMMARY_COLUMNS_2D

    title = f"<b>Segment {label}</b>"
    size_class = row.get(columns.get(SIZE_CLASS_COLUMN), "")
    if size_class:
        title += f" &middot; {html.escape(size_class)}"

    lines = []
    for name in summary_columns:
        if name not in columns:
            continue
        text = row[columns[name]]
        try:
            if math.isnan(float(text)):
                continue
        except ValueError:
            pass
        unit = split_unit(columns[name])[1]
        lines.append(
            f"<tr><td>{html.escape(name)}</td><td align='right'>&nbsp;{html.escape(format_value(text))}</td>"
            f"<td>&nbsp;{html.escape(unit)}</td></tr>"
        )

    return (
        f"{title}<table cellspacing='0' cellpadding='1'>{''.join(lines)}</table>"
        "<span style='color:gray'>Ctrl+click to show it in the report</span>"
    )


def label_at(array: np.ndarray, ras_to_ijk: np.ndarray, ras) -> int:
    """Label of the voxel containing a RAS point, given the labelmap's (k, j, i) array and 4x4 RAS to IJK matrix.

    Points outside the labelmap are background (0).
    """
    ijk = np.rint(ras_to_ijk[:3, :3] @ np.asarray(ras, dtype=float) + ras_to_ijk[:3, 3]).astype(int)
    index = tuple(ijk[::-1])
    if any(not 0 <= i < n for i, n in zip(index, array.shape)):
        return 0
    return int(array[index])


def label_rows(labels) -> dict:
    """Map each label of a report's label column to its (first) row. Values that aren't numbers are skipped."""
    rows = {}
    for row, label in enumerate(labels):
        try:
            rows.setdefault(int(float(label)), row)
        except ValueError:
            continue
    return rows


@singleton
class SegmentPicker:
    """The pick mode's button, click handling, tooltip and report display."""

    ACTION_NAME = "SegmentPickAction"

    def __init__(self):
        self.__action = None
        self.__observations = []  # (interactor, observer tag) of the watched slice views
        self.__interactionObservation = None  # (interaction node, observer tag) while the mode is on
        self.__press = None  # (view name, position) of the last left button press
        self.__labelRows = {}  # report ID -> (table MTime, {label: row})
        ApplicationObservables().applicationLoadFinished.connect(self.install)

    @property
    def action(self):
        return self.__action

    def install(self):
        """Add the mode's button to the mouse mode toolbar, after the mouse modes."""
        mainWindow = slicer.util.mainWindow()
        toolbar = mainWindow.findChild("QToolBar", "MouseModeToolBar") if mainWindow else None
        if self.__action is not None or toolbar is None:
            return

        iconPath = getResourcePath("Icons") / "svg" / "SegmentPick.svg"
        action = qt.QAction(svgToQIcon(iconPath) if iconPath.exists() else qt.QIcon(), "Pick segment", toolbar)
        action.setObjectName(self.ACTION_NAME)
        action.setCheckable(True)
        action.setToolTip(
            "Pick segment: click a segment of a Segment Inspector labelmap to see its data from the report. "
            "Ctrl+click to show its row in the report."
        )
        anchor = next((existing for existing in toolbar.actions() if not existing.checkable), None)
        if anchor is None:
            toolbar.addAction(action)
        else:
            toolbar.insertAction(anchor, action)

        action.toggled.connect(self.__onToggled)
        slicer.app.layoutManager().layoutChanged.connect(self.__observeSliceViews)
        slicer.mrmlScene.AddObserver(slicer.mrmlScene.EndCloseEvent, lambda *args: self.__labelRows.clear())
        self.__action = action

    def pick(self, viewName, position, showInReport=False):
        """Show the report data of the segment at a position of a slice view, in VTK display coordinates.

        Returns (report, label, row) when a segment of a labelmap with a report was found, None otherwise.
        """
        sliceWidget = slicer.app.layoutManager().sliceWidget(viewName)
        ras = sliceWidget.mrmlSliceNode().GetXYToRAS().MultiplyPoint((position[0], position[1], 0, 1))[:3]

        labelMapNode, report = self.__reportedLabelMap(sliceWidget)
        if report is None:
            self.__showMessage(
                "This view shows no labelmap from Segment Inspector."
                if labelMapNode is None
                else f"{labelMapNode.GetName()} has no Segment Inspector report."
            )
            return None

        label = self.__labelAt(labelMapNode, ras)
        if label == 0:
            self.__showMessage("No segment here.")
            return None

        row = self.__rowOfLabel(report, label)
        if row is None:
            self.__showMessage(f"Segment {label} is not in {report.GetName()}.")
            return None

        if showInReport:
            qt.QToolTip.hideText()
            self.__showReportRow(report, row)
        else:
            self.__showSummary(sliceWidget.sliceView(), position, report, row, label)
        return report, label, row

    def __onToggled(self, checked):
        interactionNode = slicer.app.applicationLogic().GetInteractionNode()
        if checked:
            interactionNode.SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.User)
            tag = interactionNode.AddObserver(vtk.vtkCommand.ModifiedEvent, self.__onInteractionModeChanged)
            self.__interactionObservation = (interactionNode, tag)
        else:
            if self.__interactionObservation is not None:
                node, tag = self.__interactionObservation
                node.RemoveObserver(tag)
                self.__interactionObservation = None
            if interactionNode.GetCurrentInteractionMode() == slicer.vtkMRMLInteractionNode.User:
                interactionNode.SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.ViewTransform)
            qt.QToolTip.hideText()
        self.__observeSliceViews()

    def __onInteractionModeChanged(self, interactionNode, event):
        # Another mouse mode was chosen
        if interactionNode.GetCurrentInteractionMode() != slicer.vtkMRMLInteractionNode.User:
            self.__action.setChecked(False)

    def __observeSliceViews(self, *args):
        for interactor, tag in self.__observations:
            interactor.RemoveObserver(tag)
        self.__observations = []
        self.__press = None
        if self.__action is None or not self.__action.checked:
            return

        layoutManager = slicer.app.layoutManager()
        for viewName in layoutManager.sliceViewNames():
            # Image log views have their own data display
            if viewName.startswith("ImageLog"):
                continue
            interactor = layoutManager.sliceWidget(viewName).sliceView().interactor()
            for event in (vtk.vtkCommand.LeftButtonPressEvent, vtk.vtkCommand.LeftButtonReleaseEvent):
                tag = interactor.AddObserver(
                    event, lambda caller, eventName, name=viewName: self.__onLeftButton(name, caller, eventName), 1.0
                )
                self.__observations.append((interactor, tag))

    def __onLeftButton(self, viewName, interactor, eventName):
        position = interactor.GetEventPosition()
        if eventName == "LeftButtonPressEvent":
            self.__press = (viewName, position)
            return

        press, self.__press = self.__press, None
        if press is None or press[0] != viewName:
            return
        if max(abs(a - b) for a, b in zip(press[1], position)) > CLICK_TOLERANCE:
            return  # a drag

        # Pick once the mouse event is over: Qt hides tooltips on mouse releases, including the one being handled,
        # which goes on to the slice view after VTK is done with it
        showInReport = bool(interactor.GetControlKey())
        qt.QTimer.singleShot(0, lambda: self.__pickSafely(viewName, position, showInReport))

    def __pickSafely(self, viewName, position, showInReport):
        try:
            self.pick(viewName, position, showInReport=showInReport)
        except Exception as error:
            logging.warning(f"Failed to pick the segment: {repr(error)}")

    @staticmethod
    def __reportedLabelMap(sliceWidget):
        """The view's labelmap that has a report, and the report. Without one: the view's first labelmap and None."""
        composite = sliceWidget.mrmlSliceCompositeNode()
        firstLabelMap = None
        for volumeId in (
            composite.GetLabelVolumeID(),
            composite.GetForegroundVolumeID(),
            composite.GetBackgroundVolumeID(),
        ):
            node = slicer.mrmlScene.GetNodeByID(volumeId) if volumeId else None
            if node is None or not node.IsA("vtkMRMLLabelMapVolumeNode"):
                continue
            report = labelMapReport(node)
            if report is not None:
                return node, report
            firstLabelMap = firstLabelMap or node
        return firstLabelMap, None

    @staticmethod
    def __labelAt(labelMapNode, ras):
        parentTransform = labelMapNode.GetParentTransformNode()
        if parentTransform is not None:
            transform = vtk.vtkGeneralTransform()
            parentTransform.GetTransformFromWorld(transform)
            ras = transform.TransformPoint(ras)

        rasToIjk = vtk.vtkMatrix4x4()
        labelMapNode.GetRASToIJKMatrix(rasToIjk)
        return label_at(slicer.util.arrayFromVolume(labelMapNode), slicer.util.arrayFromVTKMatrix(rasToIjk), ras)

    def __rowOfLabel(self, report, label):
        table = report.GetTable()
        mtime = max(report.GetMTime(), table.GetMTime())
        cached = self.__labelRows.get(report.GetID())
        if cached is None or cached[0] != mtime:
            column = table.GetColumnByName(LABEL_COLUMN)
            if column.IsA("vtkDataArray"):
                labels = vtk_to_numpy(column)
            else:
                labels = [column.GetValue(index) for index in range(column.GetNumberOfValues())]
            cached = (mtime, label_rows(labels))
            self.__labelRows[report.GetID()] = cached
        return cached[1].get(label)

    @staticmethod
    def __showSummary(view, position, report, row, label):
        values = {
            report.GetColumnName(column): report.GetCellText(row, column)
            for column in range(report.GetNumberOfColumns())
        }

        # VTK positions are in device pixels, from the bottom left; Qt's are in logical pixels, from the top left
        ratio = view.devicePixelRatioF()
        point = qt.QPoint(int(position[0] / ratio), int(view.height - position[1] / ratio))
        keepArea = qt.QRect(point.x() - 8, point.y() - 8, 16, 16)
        qt.QToolTip.showText(view.mapToGlobal(point), segment_summary(label, values), view, keepArea)

    def __showReportRow(self, report, row):
        tableView = None
        if report.GetNumberOfRows() <= TABLE_PREVIEW_MAX_ROWS:
            tableView = self.__showInExplorer(report)
        if tableView is None:
            tableView = self.__showInLayout(report)
        SegmentReportNavigator().selectReportRow(tableView, row)

    @staticmethod
    def __showInExplorer(report):
        """Select the report in the Explorer, which previews it; returns the preview's table view, or None."""
        appContext = getattr(slicer.modules, "AppContextInstance", None)
        explorer = getattr(slicer.modules, "CustomizedDataDockedWidget", None)
        if appContext is None or explorer is None:
            return None

        appContext.rightDrawer.show(0)
        explorer.subjectHierarchyTreeView.setCurrentNode(report)
        slicer.app.processEvents()

        tableView = explorer.tableWidget.tableView
        shown = tableView.mrmlTableNode()
        return tableView if shown is not None and shown.GetID() == report.GetID() else None

    @staticmethod
    def __showInLayout(report):
        """Show the report in the layout's table view, switching to a layout with one if needed."""
        layoutManager = slicer.app.layoutManager()
        index = next(
            (
                index
                for index in range(layoutManager.tableViewCount)
                if layoutManager.tableWidget(index).tableView().mrmlTableViewNode().IsMappedInLayout()
            ),
            None,
        )
        if index is None:
            layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpTableView)
            index = 0

        applicationLogic = slicer.app.applicationLogic()
        applicationLogic.GetSelectionNode().SetActiveTableID(report.GetID())
        applicationLogic.PropagateTableSelection()
        slicer.app.processEvents()
        return layoutManager.tableWidget(index).tableView()

    @staticmethod
    def __showMessage(message):
        qt.QToolTip.hideText()
        slicer.util.mainWindow().statusBar().showMessage(message, MESSAGE_TIMEOUT)
