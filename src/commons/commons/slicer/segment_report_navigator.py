"""Frames a segment in the slice and 3D views when a row of a Segment Inspector report is clicked.

A report table is recognized by its link to the labelmap the report describes: a node reference (see
linkReportToLabelMap) or, in projects saved before those existed, its "ReferenceVolumeNode" attribute.
The clicked row's "label" value is located in that labelmap on demand, so it works for any report, with or
without centroid columns.
"""

import logging
from collections import OrderedDict

import numpy as np
import qt
import slicer
import vtk
from scipy import ndimage

from commons.slicer.application_observables import ApplicationObservables
from commons.slicer.helpers import singleton

LABEL_COLUMN = "label"

# Node reference roles linking a Segment Inspector report and its labelmap. Slicer keeps references right when node IDs
# change, e.g. when a project is imported into a scene that already has nodes with the same IDs; the ID attributes
# ("ReferenceVolumeNode" and "ResultReport", still written for the code that reads them) go stale then.
REPORT_LABELMAP_ROLE = "SegmentInspectorLabelMap"
LABELMAP_REPORT_ROLE = "SegmentInspectorReport"

# How much larger than the segment the framed views are
FRAME_MARGIN = 1.5

# Smallest framed size, in voxels, so that tiny segments still show some context
MIN_FRAME_VOXELS = 10


def label_bounding_boxes(array: np.ndarray) -> list:
    """Bounding box (tuple of slices) of each label, at index label - 1. Absent labels get None."""
    if not np.issubdtype(array.dtype, np.integer):
        array = array.astype(np.int64)
    return ndimage.find_objects(array)


def locate_label(array: np.ndarray, box: tuple, label: int, spacing) -> tuple:
    """Find a voxel of the label close to its centroid, and the corners of its bounding box.

    Works one plane at a time, so even a segment spanning the whole volume needs little memory.

    Args:
        array: 3D labelmap, in (k, j, i) order.
        box: the label's bounding box, as given by label_bounding_boxes.
        label: the label value.
        spacing: voxel size along (k, j, i).

    Returns:
        (inside, corners): the (k, j, i) index of the label's voxel nearest to its centroid (the centroid itself
        can fall outside ring- or C-shaped segments), and the 8 corners of the bounding box, at voxel edges.
    """
    spacing = np.asarray(spacing, dtype=float)
    offset = np.array([s.start for s in box])
    planes = range(box[0].start, box[0].stop)

    count = 0
    index_sum = np.zeros(3)
    for k in planes:
        mask = array[k, box[1], box[2]] == label
        rows = mask.sum(axis=1)
        columns = mask.sum(axis=0)
        plane_count = rows.sum()
        count += plane_count
        index_sum += (k * plane_count, np.dot(rows, np.arange(len(rows))), np.dot(columns, np.arange(len(columns))))

    centroid = index_sum / count
    centroid[1:] += offset[1:]

    inside = np.rint(centroid).astype(int)
    if array[tuple(inside)] != label:
        inside = None
        best_distance = np.inf
        # Visit planes from the centroid outwards, stopping when no voxel can be closer than the best one
        for k in sorted(planes, key=lambda plane: abs(plane - centroid[0])):
            plane_distance = ((k - centroid[0]) * spacing[0]) ** 2
            if plane_distance >= best_distance:
                break
            jj, ii = np.nonzero(array[k, box[1], box[2]] == label)
            if len(jj) == 0:
                continue
            jj += offset[1]
            ii += offset[2]
            distances = plane_distance + ((jj - centroid[1]) * spacing[1]) ** 2 + ((ii - centroid[2]) * spacing[2]) ** 2
            nearest = np.argmin(distances)
            if distances[nearest] < best_distance:
                best_distance = distances[nearest]
                inside = np.array((k, jj[nearest], ii[nearest]))

    edges = [(s.start - 0.5, s.stop - 0.5) for s in box]
    corners = np.array([(k, j, i) for k in edges[0] for j in edges[1] for i in edges[2]])
    return inside, corners


def index_to_ras(points: np.ndarray, ijk_to_ras: np.ndarray) -> np.ndarray:
    """Map (k, j, i) index points to RAS with a 4x4 IJK to RAS matrix."""
    ijk = np.atleast_2d(np.asarray(points, dtype=float))[:, ::-1]
    return (ijk_to_ras[:3, :3] @ ijk.T).T + ijk_to_ras[:3, 3]


def slice_view_frame(inside: np.ndarray, corners: np.ndarray, slice_to_ras: np.ndarray, view_size, min_extent=0):
    """Center and field of view that fit the corners in a slice view whose plane goes through the inside point.

    Args:
        inside: RAS point the slice plane must contain.
        corners: RAS points that must fit in the view.
        slice_to_ras: the view's 4x4 SliceToRAS matrix; its first two columns are the in-plane axes.
        view_size: view width and height, in pixels.
        min_extent: smallest framed width and height, in mm.

    Returns:
        (center, (fov_x, fov_y)): the RAS point to center the view on, in the plane through the inside point, and
        the field of view in mm, with the view's aspect ratio.
    """
    axes = slice_to_ras[:3, :2]
    projection = (corners - inside) @ axes
    low = projection.min(axis=0)
    high = projection.max(axis=0)
    center = inside + axes @ ((low + high) / 2)

    extent = np.maximum(high - low, min_extent) * FRAME_MARGIN
    aspect = view_size[0] / view_size[1]
    fov_x = max(extent[0], extent[1] * aspect)
    return center, (fov_x, fov_x / aspect)


def camera_frame(corners: np.ndarray, position: np.ndarray, focal_point: np.ndarray, view_angle: float):
    """Camera that keeps its viewing direction and fits the corners.

    Args:
        corners: RAS points that must fit in the view.
        position: current camera position.
        focal_point: current camera focal point.
        view_angle: camera view angle, in degrees.

    Returns:
        (focal_point, position, parallel_scale) of the framed camera. The parallel scale is for cameras in parallel
        projection.
    """
    center = (corners.min(axis=0) + corners.max(axis=0)) / 2
    radius = np.linalg.norm(corners - center, axis=1).max() * FRAME_MARGIN

    direction = np.asarray(position, dtype=float) - np.asarray(focal_point, dtype=float)
    norm = np.linalg.norm(direction)
    direction = direction / norm if norm > 0 else np.array((0.0, 0.0, 1.0))

    distance = radius / np.sin(np.radians(view_angle) / 2)
    return center, center + direction * distance, radius


def linkReportToLabelMap(reportNode, labelMapNode, backLink=True):
    """Link a Segment Inspector report to the labelmap it describes and, with backLink, the labelmap to the report.

    Links are node references, plus the ID attributes for the code that reads those.
    """
    reportNode.SetAttribute("ReferenceVolumeNode", labelMapNode.GetID())
    reportNode.SetNodeReferenceID(REPORT_LABELMAP_ROLE, labelMapNode.GetID())
    if backLink:
        labelMapNode.SetAttribute("ResultReport", reportNode.GetID())
        labelMapNode.SetNodeReferenceID(LABELMAP_REPORT_ROLE, reportNode.GetID())


def _linkedNodeId(node, role, attribute):
    """ID of the node linked by a reference role or, in projects saved before references were used, an attribute."""
    return node.GetNodeReferenceID(role) or node.GetAttribute(attribute)


def reportLabelMap(tableNode):
    """Labelmap described by a Segment Inspector report table, or None if the table isn't one."""
    if tableNode is None or tableNode.GetColumnIndex(LABEL_COLUMN) < 0:
        return None

    labelMapId = _linkedNodeId(tableNode, REPORT_LABELMAP_ROLE, "ReferenceVolumeNode")
    labelMap = slicer.mrmlScene.GetNodeByID(labelMapId) if labelMapId else None
    if labelMap is None or not labelMap.IsA("vtkMRMLLabelMapVolumeNode") or labelMap.GetImageData() is None:
        return None

    # A labelmap only points back to its latest report
    reportId = _linkedNodeId(labelMap, LABELMAP_REPORT_ROLE, "ResultReport")
    if reportId and reportId != tableNode.GetID():
        return None

    return labelMap


def labelMapReport(labelMapNode):
    """Segment Inspector report of a labelmap, or None if it has none: the reverse of reportLabelMap."""
    reportId = _linkedNodeId(labelMapNode, LABELMAP_REPORT_ROLE, "ResultReport") if labelMapNode is not None else None
    report = slicer.mrmlScene.GetNodeByID(reportId) if reportId else None
    if report is None or not report.IsA("vtkMRMLTableNode") or reportLabelMap(report) is not labelMapNode:
        return None
    return report


class SegmentLocator:
    """Locates labels in labelmaps, caching each labelmap's bounding boxes until its image changes."""

    MAX_CACHED_LABELMAPS = 4

    def __init__(self):
        # node ID -> (image MTime, bounding boxes, {label: (inside, corners)})
        self.__cache = OrderedDict()

    def clear(self):
        self.__cache.clear()

    def locate(self, labelMapNode, label):
        """(inside, corners) of the label in (k, j, i) index space, as in locate_label, or None if absent."""
        nodeId = labelMapNode.GetID()
        mtime = labelMapNode.GetImageData().GetMTime()
        entry = self.__cache.get(nodeId)
        array = slicer.util.arrayFromVolume(labelMapNode)

        if entry is None or entry[0] != mtime:
            with slicer.util.WaitCursor():
                entry = (mtime, label_bounding_boxes(array), {})
            self.__cache[nodeId] = entry

        self.__cache.move_to_end(nodeId)
        while len(self.__cache) > self.MAX_CACHED_LABELMAPS:
            self.__cache.popitem(last=False)

        _, boxes, located = entry
        if label not in located:
            if not 0 < label <= len(boxes) or boxes[label - 1] is None:
                return None
            with slicer.util.WaitCursor():
                located[label] = locate_label(array, boxes[label - 1], label, labelMapNode.GetSpacing()[::-1])

        return located[label]


@singleton
class SegmentReportNavigator:
    """App-wide: clicking a row of a Segment Inspector report frames its segment in the slice and 3D views.

    Watches the table views of the layout. Other table views, like the Explorer's preview, are added with watch().
    """

    WATCHED_PROPERTY = "SegmentReportNavigatorWatched"

    def __init__(self):
        self.__locator = SegmentLocator()
        self.__pendingClick = None
        self.__installed = False
        self.__selectingRow = False
        ApplicationObservables().applicationLoadFinished.connect(self.install)

    def install(self):
        if self.__installed or slicer.app.layoutManager() is None:
            return

        self.__installed = True
        slicer.app.layoutManager().layoutChanged.connect(self.__onLayoutChanged)
        slicer.mrmlScene.AddObserver(slicer.mrmlScene.EndCloseEvent, lambda *args: self.__locator.clear())
        self.__onLayoutChanged()

    def watch(self, tableView):
        """Frame the segment of the rows clicked in this qMRMLTableView."""
        if tableView is None or tableView.property(self.WATCHED_PROPERTY):
            return

        tableView.setProperty(self.WATCHED_PROPERTY, True)
        # A click on another row emits both signals, a click on the current row only pressed, and moving with the
        # keyboard only currentRowChanged. __onRowClicked merges them into one framing.
        tableView.selectionModel().currentRowChanged.connect(
            lambda current, previous, view=tableView: self.__onRowClicked(view, current)
        )
        tableView.pressed.connect(lambda index, view=tableView: self.__onRowClicked(view, index))

    def selectReportRow(self, tableView, tableRow):
        """Select and show a row of the table in the view, without framing its segment."""
        tableNode = tableView.mrmlTableNode()
        modelRow = tableRow if tableNode.GetUseColumnTitleAsColumnHeader() else tableRow + 1  # see __labelAt
        column = max(tableNode.GetColumnIndex(LABEL_COLUMN), 0)
        proxy = tableView.sortFilterProxyModel()
        source = tableView.tableModel()
        if tableView.transposed:
            index = proxy.mapFromSource(source.index(column, modelRow))
            flags = qt.QItemSelectionModel.ClearAndSelect | qt.QItemSelectionModel.Columns
        else:
            index = proxy.mapFromSource(source.index(modelRow, column))
            flags = qt.QItemSelectionModel.ClearAndSelect | qt.QItemSelectionModel.Rows

        self.__selectingRow = True
        try:
            tableView.selectionModel().setCurrentIndex(index, flags)
        finally:
            self.__selectingRow = False
        tableView.scrollTo(index, qt.QAbstractItemView.PositionAtCenter)

    def frameSegment(self, labelMapNode, label) -> bool:
        """Center and zoom the slice and 3D views on a label of the labelmap. Returns False if the label is absent."""
        location = self.__locator.locate(labelMapNode, label)
        if location is None:
            return False

        inside, corners = location
        ijkToRas = vtk.vtkMatrix4x4()
        labelMapNode.GetIJKToRASMatrix(ijkToRas)
        points = self.__toWorld(
            labelMapNode, index_to_ras(np.vstack((inside, corners)), slicer.util.arrayFromVTKMatrix(ijkToRas))
        )
        insideWorld, cornersWorld = points[0], points[1:]

        minExtent = MIN_FRAME_VOXELS * min(labelMapNode.GetSpacing())
        self.__frameSliceViews(insideWorld, cornersWorld, minExtent)
        self.__frameThreeDViews(cornersWorld)
        return True

    def __onLayoutChanged(self, *args):
        layoutManager = slicer.app.layoutManager()
        for index in range(layoutManager.tableViewCount):
            self.watch(layoutManager.tableWidget(index).tableView())

    def __onRowClicked(self, tableView, index):
        if not index.isValid() or self.__selectingRow:
            return

        alreadyScheduled = self.__pendingClick is not None
        self.__pendingClick = (tableView, index.row(), index.column())
        if not alreadyScheduled:
            qt.QTimer.singleShot(0, self.__framePendingClick)

    def __framePendingClick(self):
        tableView, row, column = self.__pendingClick
        self.__pendingClick = None

        try:
            tableNode = tableView.mrmlTableNode()
            labelMapNode = reportLabelMap(tableNode)
            if labelMapNode is None:
                return

            label = self.__labelAt(tableView, tableNode, row, column)
            if label is not None and not self.frameSegment(labelMapNode, label):
                logging.info(f"Label {label} was not found in {labelMapNode.GetName()}.")
        except Exception as error:
            logging.warning(f"Failed to frame the clicked segment: {repr(error)}")

    @staticmethod
    def __labelAt(tableView, tableNode, row, column):
        # The view may be sorted and transposed: go back to the table's own row
        sourceIndex = tableView.sortFilterProxyModel().mapToSource(tableView.model().index(row, column))
        tableRow = sourceIndex.column() if tableView.transposed else sourceIndex.row()
        if not tableNode.GetUseColumnTitleAsColumnHeader():
            tableRow -= 1  # the model shows the column titles in its first row (column, if transposed)
        if not 0 <= tableRow < tableNode.GetNumberOfRows():
            return None

        try:
            return int(float(tableNode.GetCellText(tableRow, tableNode.GetColumnIndex(LABEL_COLUMN))))
        except ValueError:
            return None

    @staticmethod
    def __toWorld(node, points):
        parentTransform = node.GetParentTransformNode()
        if parentTransform is None:
            return points

        transform = vtk.vtkGeneralTransform()
        parentTransform.GetTransformToWorld(transform)
        return np.array([transform.TransformPoint(point) for point in points])

    @staticmethod
    def __frameSliceViews(inside, corners, minExtent):
        layoutManager = slicer.app.layoutManager()
        for viewName in layoutManager.sliceViewNames():
            # Image log views have their own depth navigation
            if viewName.startswith("ImageLog"):
                continue

            sliceNode = layoutManager.sliceWidget(viewName).mrmlSliceNode()
            viewSize = sliceNode.GetDimensions()
            if not sliceNode.IsMappedInLayout() or viewSize[0] <= 0 or viewSize[1] <= 0:
                continue

            sliceToRas = slicer.util.arrayFromVTKMatrix(sliceNode.GetSliceToRAS())
            center, fov = slice_view_frame(inside, corners, sliceToRas, viewSize, minExtent)

            wasModifying = sliceNode.StartModify()
            sliceNode.SetXYZOrigin(0, 0, 0)  # remove any pan, so the view center is the slice origin
            sliceNode.JumpSliceByCentering(*center)
            sliceNode.SetFieldOfView(fov[0], fov[1], sliceNode.GetFieldOfView()[2])
            sliceNode.EndModify(wasModifying)

    @staticmethod
    def __frameThreeDViews(corners):
        layoutManager = slicer.app.layoutManager()
        camerasLogic = slicer.modules.cameras.logic()
        for index in range(layoutManager.threeDViewCount):
            viewNode = layoutManager.threeDWidget(index).mrmlViewNode()
            if not viewNode.IsMappedInLayout():
                continue

            cameraNode = camerasLogic.GetViewActiveCameraNode(viewNode)
            if cameraNode is None:
                continue

            focalPoint, position, parallelScale = camera_frame(
                corners, cameraNode.GetPosition(), cameraNode.GetFocalPoint(), cameraNode.GetViewAngle()
            )

            wasModifying = cameraNode.StartModify()
            cameraNode.SetFocalPoint(*focalPoint)
            cameraNode.SetPosition(*position)
            cameraNode.SetParallelScale(parallelScale)
            cameraNode.EndModify(wasModifying)
            cameraNode.ResetClippingRange()
