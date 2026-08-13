from functools import partial
import qt
import slicer
from ltrace.slicer.widgets import SingleShotInputWidget


class SideBySideImageManager:
    def __init__(self):
        self.segmentationNodes = {}
        for i in (1, 2):
            self.segmentationNodes[i] = None
            sliceWidget = slicer.app.layoutManager().sliceWidget(f"SideBySideSlice{i}")
            for widgetName in (
                "SegmentationIconLabel",
                "SegmentationVisibilityButton",
                "SegmentationOpacitySlider",
                "SegmentationOutlineButton",
                "SegmentSelectorWidget",
            ):
                sliceWidget.findChild(qt.QWidget, widgetName).setFixedSize(qt.QSize(0, 0))

            qMRMLSliceControllerWidget = sliceWidget.findChild(qt.QWidget, "qMRMLSliceControllerWidget")
            layout = qMRMLSliceControllerWidget.layout()
            layout.setSizeConstraint(qt.QLayout.SetFixedSize)
            customSegmentSelector = SingleShotInputWidget(
                hideImage=True,
                hideSoi=True,
                hideCalcProp=True,
                requireSourceVolume=False,
                allowedInputNodes=["vtkMRMLSegmentationNode"],
            )
            customSegmentSelector.setObjectName("CustomSegmentSelector")
            customSegmentSelector.onMainSelectedSignal.connect(partial(self.onSegmentationChanged, i))

            customSegmentSelector.segmentSelectionChanged.connect(
                lambda segments, i=i: self.onSegmentSelectionChanged(i, segments)
            )
            customSegmentSelector.hide()
            layout.addWidget(customSegmentSelector, 1, 0, 1, 5)
            layout.setRowStretch(1, 1)

            moreButton = sliceWidget.findChild(qt.QWidget, "MoreButton")
            moreButton.toggled.connect(
                lambda toggled, sliceWidget=sliceWidget: self.formatWidgets(toggled, sliceWidget)
            )

            # Undoes the effects FixedSize size constraint has on the width of the controller
            paddingWidget = qt.QWidget()
            paddingWidget.setObjectName("PaddingWidget")
            paddingWidget.setAttribute(qt.Qt.WA_TransparentForMouseEvents, True)
            layout.addWidget(paddingWidget, 0, 4, 1, 1)
            paddingWidget.setFixedWidth(sliceWidget.sliceView().width)
            paddingWidget.setVisible(True)
            sliceWidget.sliceView().resized.connect(
                lambda size, paddingWidget=paddingWidget, isChecked=moreButton.isChecked: self._onViewResized(
                    size, paddingWidget, isChecked
                )
            )

    def _onViewResized(self, newSize, paddingWidget, isChecked):
        PADDING_OFFSET = 152  # Measured manually but shouldn't change
        paddingWidget.setFixedWidth(newSize.width() - (isChecked() * PADDING_OFFSET))

    def formatWidgets(self, toggled, sliceWidget):
        QWIDGETSIZE_MAX = (1 << 24) - 1  # constant not available in pyqt, just qt
        PADDING_OFFSET = 152  # Measured manually but shouldn't change

        qMRMLSliceControllerWidget = sliceWidget.findChild(qt.QWidget, "qMRMLSliceControllerWidget")

        customSegmentSelector = qMRMLSliceControllerWidget.findChild(SingleShotInputWidget, "CustomSegmentSelector")
        customSegmentSelector.setVisible(toggled)

        paddingWidget = qMRMLSliceControllerWidget.findChild(qt.QWidget, "PaddingWidget")
        paddingWidget.setFixedWidth(sliceWidget.sliceView().width - (toggled * PADDING_OFFSET))

        if toggled:
            # Undoing the fixed height
            qMRMLSliceControllerWidget.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
            qMRMLSliceControllerWidget.setMinimumSize(0, 0)
        else:
            qMRMLSliceControllerWidget.setFixedHeight(31)

    @staticmethod
    def enterLayout():
        segNodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
        for segNode in segNodes:
            # Image log has its own handling of segmentation visibility
            if not segNode.GetAttribute("ImageLogSegmentation"):
                segNode.CreateDefaultDisplayNodes()
                displayNode = segNode.GetDisplayNode()
                if displayNode.GetVisibility():
                    displayNode.SetAllSegmentsVisibility(False)

    def exitLayout(self):
        for i in (1, 2):
            if not slicer.mrmlScene.IsNodePresent(self.segmentationNodes[i]):
                self.segmentationNodes[i] = None

    @staticmethod
    def getViewId(index):
        sliceWidget = slicer.app.layoutManager().sliceWidget(f"SideBySideSlice{index}")
        return sliceWidget.sliceLogic().GetSliceNode().GetID()

    def onSegmentationChanged(self, sliceIndex, segmentationNode):
        viewId = self.getViewId(sliceIndex)

        if self.segmentationNodes[sliceIndex]:
            displayNode = self.segmentationNodes[sliceIndex].GetNthDisplayNode(sliceIndex)
            if displayNode:
                displayNode.SetAllSegmentsVisibility(False)

        if segmentationNode:
            # Hide default display node (0)
            displayNode = segmentationNode.GetDisplayNode()
            if displayNode:
                displayNode.SetAllSegmentsVisibility(False)

            # Create custom display nodes (1 and 2) if necessary
            for i in (1, 2):
                if not segmentationNode.GetNthDisplayNode(i):
                    displayNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationDisplayNode")
                    segmentationNode.AddAndObserveDisplayNodeID(displayNode.GetID())

                    # Initialize visibility
                    displayNode.SetDisplayableOnlyInView(self.getViewId(i))
                    displayNode.SetAllSegmentsVisibility(False)

            # Set custom display node visibility (1 or 2)
            displayNode = segmentationNode.GetNthDisplayNode(sliceIndex)

        self.segmentationNodes[sliceIndex] = segmentationNode

    def onSegmentSelectionChanged(self, sliceIndex, selectedSegments):
        segmentationNode = self.segmentationNodes[sliceIndex]
        if not segmentationNode:
            return
        displayNode = segmentationNode.GetNthDisplayNode(sliceIndex)
        displayNode.SetAllSegmentsVisibility(False)

        for segmentId in selectedSegments:
            displayNode.SetSegmentVisibility(segmentId, True)


POSITION_FLAG = slicer.vtkMRMLSliceNode.SliceToRASFlag
ZOOM_FLAG = slicer.vtkMRMLSliceNode.FieldOfViewFlag
FIT_VOLUME_FLAG = slicer.vtkMRMLSliceNode.ResetFieldOfViewFlag
SLICE_OFFSET_FLAG = slicer.vtkMRMLSliceNode.XYZOriginFlag

# Interactions that need a forced re-broadcast. Only zoom (and fit) qualify:
# ScaleZoom changes the slice origin but only flags FieldOfView, so the origin
# would otherwise not propagate. Pan (XYZOrigin) and slice offset (SliceToRAS)
# are intentionally excluded -- they flag exactly what they change, so they
# already propagate natively (continuously under hot link). Triggering on them
# would force-stop the interaction mid-drag (see _sync) and freeze the gesture.
FLAG_LIST = [ZOOM_FLAG, FIT_VOLUME_FLAG]
ALL_FLAGS = POSITION_FLAG | ZOOM_FLAG | SLICE_OFFSET_FLAG


def _sync(sliceNode):
    """Force-broadcast position, zoom and slice offset to the other linked views.

    Restores the original interaction state instead of clearing it, so this can
    run mid-drag (hot-linked zoom) without interrupting the ongoing gesture's own
    continuous broadcasts.
    """
    was_interacting = sliceNode.GetInteracting()
    previous_flags = sliceNode.GetInteractionFlags()
    sliceNode.SetInteracting(1)
    sliceNode.SetInteractionFlags(ALL_FLAGS)
    sliceNode.Modified()
    sliceNode.SetInteractionFlags(previous_flags)
    sliceNode.SetInteracting(was_interacting)


# ctrl+scroll zoom fires discrete events; the propagation/render of the final
# tick to the (indirectly updated) linked views is intermittently dropped by the
# render throttle and the broadcast re-entrancy guard, leaving the linked view a
# step behind / pixelated until the next interaction. After a scroll burst
# settles, re-broadcast the final geometry and force a re-render to catch up.
_zoom_finalize_timer = None
ZOOM_FINALIZE_DELAY_MS = 80


def _finalize_zoom(sliceNode):
    if not sliceNode or not slicer.mrmlScene.IsNodePresent(sliceNode):
        return
    # Re-broadcast the settled geometry, in case the last tick's broadcast was
    # swallowed by the re-entrancy guard.
    _sync(sliceNode)
    # Force every linked view in the group to re-render and recompute its slice
    # resolution, in case the final frame was throttled out (state correct but
    # frame/resolution stale). Modifying the node alone triggers both.
    viewGroup = sliceNode.GetViewGroup()
    for node in slicer.util.getNodesByClass("vtkMRMLSliceNode"):
        if node.GetViewGroup() == viewGroup:
            node.Modified()


def _schedule_zoom_finalize(sliceNode):
    global _zoom_finalize_timer
    if _zoom_finalize_timer is None:
        _zoom_finalize_timer = qt.QTimer()
        _zoom_finalize_timer.setSingleShot(True)
        _zoom_finalize_timer.setInterval(ZOOM_FINALIZE_DELAY_MS)
    try:
        _zoom_finalize_timer.timeout.disconnect()
    except (RuntimeError, TypeError):
        pass
    _zoom_finalize_timer.timeout.connect(lambda: _finalize_zoom(sliceNode))
    _zoom_finalize_timer.start()


def _onSliceNodeModified(caller, event):
    interaction = caller.GetInteractionFlags()
    if interaction in FLAG_LIST and caller.GetInteracting():
        _sync(caller)
        if interaction == ZOOM_FLAG:
            _schedule_zoom_finalize(caller)


def _onCompositeNodeModified(sliceNode, caller, event):
    if caller.GetInteracting():
        return
    if caller.GetInteractionFlags():
        return
    if not caller.GetLinkedControl():
        return
    _sync(sliceNode)


# Node IDs that already have zoom-sync observers, so enable_zoom_sync can be
# called repeatedly (e.g. on every segmentation start) without stacking
# duplicate observers on the persistent view nodes.
_zoom_sync_observed_nodes = set()
# Whether we have registered the scene-close hook that resets the set above.
_zoom_sync_close_hooked = False


def _reset_zoom_sync_observers(*args):
    """Forget the tracked node IDs when the scene closes.

    The observers live on slice/composite nodes that are destroyed on scene
    close, taking the observers with them. Slicer reuses node IDs across a
    close, so without this reset a recreated node could match a stale ID and
    enable_zoom_sync would skip re-attaching its observer, silently breaking
    zoom sync after a scene reload. Clearing the set also bounds its growth.
    """
    _zoom_sync_observed_nodes.clear()


def enable_zoom_sync(viewName1, viewName2):
    """Keep two linked slice views in sync when zooming with ctrl+scroll.

    Slicer's ScaleZoom (ctrl+scroll) changes both the field of view and the
    slice origin, but only flags the field of view for linked-view broadcast,
    so the origin never propagates and the views drift apart. RMB-drag zoom is
    unaffected because it only changes the field of view. We work around it by
    re-broadcasting all view-geometry flags whenever an interacting slice node
    is modified.

    Idempotent: safe to call more than once for the same views.
    """
    global _zoom_sync_close_hooked
    if not _zoom_sync_close_hooked:
        slicer.mrmlScene.AddObserver(slicer.vtkMRMLScene.EndCloseEvent, _reset_zoom_sync_observers)
        _zoom_sync_close_hooked = True

    layoutManager = slicer.app.layoutManager()
    sliceWidget1 = layoutManager.sliceWidget(viewName1)
    sliceWidget2 = layoutManager.sliceWidget(viewName2)
    sliceNode1 = sliceWidget1.sliceLogic().GetSliceNode()
    sliceNode2 = sliceWidget2.sliceLogic().GetSliceNode()

    for sliceNode in (sliceNode1, sliceNode2):
        if sliceNode.GetID() not in _zoom_sync_observed_nodes:
            sliceNode.AddObserver("ModifiedEvent", _onSliceNodeModified)
            _zoom_sync_observed_nodes.add(sliceNode.GetID())

    composite1 = sliceWidget1.sliceLogic().GetSliceCompositeNode()
    composite2 = sliceWidget2.sliceLogic().GetSliceCompositeNode()

    composite1.SetInteractionFlagsModifier(0)
    composite2.SetInteractionFlagsModifier(0)

    if composite1.GetID() not in _zoom_sync_observed_nodes:
        composite1.AddObserver(
            "ModifiedEvent", lambda caller, event: _onCompositeNodeModified(sliceNode1, caller, event)
        )
        _zoom_sync_observed_nodes.add(composite1.GetID())
