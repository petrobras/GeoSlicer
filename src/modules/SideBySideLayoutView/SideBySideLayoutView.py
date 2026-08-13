from string import Template

import qt
import slicer
import vtk

from ltrace.slicer.app.layouts import customLayout
from ltrace.slicer.side_by_side_image_layout import enable_zoom_sync, SideBySideImageManager
from ltrace.slicer_utils import LTracePlugin
from ltrace.constants import (
    SIDE_BY_SIDE_IMAGE_LAYOUT_ID,
    SIDE_BY_SIDE_SEGMENTATION_LAYOUT_ID,
    SIDE_BY_SIDE_DUMB_LAYOUT_ID,
)


class SideBySideLayoutView(LTracePlugin):
    SETTING_KEY = "SideBySideLayoutView"

    SIDE_BY_SIDE_IMAGE_GROUP = 70
    SIDE_BY_SIDE_SEGMENTATION_GROUP = 71
    SIDE_BY_SIDE_DUMB_GROUP = 72

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Side by Side"
        self.parent.categories = ["System"]
        self.parent.dependencies = []
        self.parent.hidden = True
        self.parent.contributors = []
        self.parent.helpText = ""
        self.parent.acknowledgementText = ""

        ####################################################################################
        # Custom properties
        ####################################################################################

        self.sideBySideImageManager = None
        self.sideBySideSegmentationSetupComplete = False

    @staticmethod
    def view_2D_with_group_template():
        return Template(
            """
            <item splitSize="$size">
                <view class="vtkMRMLSliceNode" singletontag="$tag">
                    <property name="orientation" action="default">$orientation</property>
                    <property name="viewlabel" action="default">$label</property>
                    <property name="viewcolor" action="default">$color</property>
                    <property name="viewgroup" action="default">$group</property>
                </view>
            </item>"""
        )

    @staticmethod
    def side_by_side_layout_template():
        return Template(
            """
            <layout type="horizontal" split="true">
                $view1
                $view2
            </layout>"""
        )

    def sideBySideImageLayout(self):
        layout_template = self.side_by_side_layout_template()
        view_2d_template_with_group = self.view_2D_with_group_template()

        layoutXML = layout_template.substitute(
            view1=view_2d_template_with_group.substitute(
                size="500",
                tag="SideBySideSlice1",
                orientation="XY",
                label="1",
                color="#EEEEEE",
                group=self.SIDE_BY_SIDE_IMAGE_GROUP,
            ),
            view2=view_2d_template_with_group.substitute(
                size="500",
                tag="SideBySideSlice2",
                orientation="XY",
                label="2",
                color="#EEEEEE",
                group=self.SIDE_BY_SIDE_IMAGE_GROUP,
            ),
        )
        customLayout(SIDE_BY_SIDE_IMAGE_LAYOUT_ID, layoutXML, "Side by side", self.resource("SideBySideImage.png"))

    def sideBySideSegmentationLayout(self):
        layout_template = self.side_by_side_layout_template()
        view_2d_template_with_group = self.view_2D_with_group_template()

        layoutXML = layout_template.substitute(
            view1=view_2d_template_with_group.substitute(
                size="500",
                tag="SideBySideImageSlice",
                orientation="XY",
                label="I",
                color="#EEEEEE",
                group=self.SIDE_BY_SIDE_SEGMENTATION_GROUP,
            ),
            view2=view_2d_template_with_group.substitute(
                size="500",
                tag="SideBySideSegmentationSlice",
                orientation="XY",
                label="S",
                color="#CCCCCC",
                group=self.SIDE_BY_SIDE_SEGMENTATION_GROUP,
            ),
        )
        customLayout(
            SIDE_BY_SIDE_SEGMENTATION_LAYOUT_ID,
            layoutXML,
            "Side by side segmentation",
            self.resource("SideBySideSegmentation.png"),
        )

        layout = slicer.app.layoutManager()

        def onLayoutChanged(id_):
            if id_ == SIDE_BY_SIDE_SEGMENTATION_LAYOUT_ID:
                self._linkViews(("SideBySideSegmentationSlice", "SideBySideImageSlice"))
                self._useSameBackgroundAs("Red", "SideBySideImageSlice")
                self._useSameForegroundAs("Red", "SideBySideImageSlice")

                if not self.sideBySideSegmentationSetupComplete:
                    enable_zoom_sync("SideBySideImageSlice", "SideBySideSegmentationSlice")
                    self.sideBySideSegmentationSetupComplete = True

                # These are necessary despite also being called inside _useSameBackgroundAs and _useSameForegroundAs
                slicer.app.processEvents(1000)
                layout.sliceWidget("SideBySideImageSlice").sliceLogic().FitSliceToAll()
                layout.sliceWidget("SideBySideSegmentationSlice").sliceLogic().FitSliceToAll()

                # Must run after processEvents: link propagation from _useSameBackgroundAs would
                # otherwise override the None background we set on the segmentation slice.
                self.updateSideBySideSegmentation()
            else:
                self.exitSideBySideSegmentation()

            if id_ == SIDE_BY_SIDE_IMAGE_LAYOUT_ID:
                self._linkViews(("SideBySideSlice1", "SideBySideSlice2"))
                self._useSameBackgroundAs("Red", "SideBySideSlice1")
                self._useSameBackgroundAs("Red", "SideBySideSlice2")

                if not self.sideBySideImageManager:
                    self.sideBySideImageManager = SideBySideImageManager()
                    enable_zoom_sync("SideBySideSlice1", "SideBySideSlice2")
                self.sideBySideImageManager.enterLayout()
            elif self.sideBySideImageManager:
                self.sideBySideImageManager.exitLayout()
                self.disableSliceVisibilityIn3DView(viewNames=["SideBySideSlice1", "SideBySideSlice2"])

        @vtk.calldata_type(vtk.VTK_OBJECT)
        def onNodeAdded(caller, event, callData):
            if (
                isinstance(callData, slicer.vtkMRMLSegmentationNode)
                and layout.layout == SIDE_BY_SIDE_SEGMENTATION_LAYOUT_ID
            ):
                self.updateSideBySideSegmentation()

        layout.layoutChanged.connect(onLayoutChanged)

        slicer.mrmlScene.AddObserver(slicer.mrmlScene.NodeAddedEvent, onNodeAdded)

    def sideBySideDumbLayout(self):
        """Same layout as side-by-side, but without any extra management logic.
        Not accessible from the UI.
        """
        layout_template = self.side_by_side_layout_template()
        view_2d_template_with_group = self.view_2D_with_group_template()

        layoutXML = layout_template.substitute(
            view1=view_2d_template_with_group.substitute(
                size="500",
                tag="SideBySideDumb1",
                orientation="XY",
                label="1",
                color="#EEEEEE",
                group=self.SIDE_BY_SIDE_DUMB_GROUP,
            ),
            view2=view_2d_template_with_group.substitute(
                size="500",
                tag="SideBySideDumb2",
                orientation="XY",
                label="2",
                color="#EEEEEE",
                group=self.SIDE_BY_SIDE_DUMB_GROUP,
            ),
        )
        layoutID = SIDE_BY_SIDE_DUMB_LAYOUT_ID
        layoutManager = slicer.app.layoutManager()
        layoutManager.layoutLogic().GetLayoutNode().AddLayoutDescription(layoutID, layoutXML)

    def updateSideBySideSegmentation(self):
        sliceWidget = slicer.app.layoutManager().sliceWidget("SideBySideSegmentationSlice")
        if not sliceWidget or slicer.mrmlScene.IsImporting():
            # Project is loading, will update later when layout is changed
            return
        segSliceLogic = sliceWidget.sliceLogic()
        segCompositeNode = segSliceLogic.GetSliceCompositeNode()

        segSliceId = segSliceLogic.GetSliceNode().GetID()
        segNodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
        for segNode in segNodes:
            # Image log has its own handling of segmentation visibility
            if not segNode.GetAttribute("ImageLogSegmentation"):
                segNode.CreateDefaultDisplayNodes()
                displayNode = segNode.GetDisplayNode()
                displayNode.SetOpacity(1)

                # Show segmentation on 'S' slice view only
                displayNode.AddViewNodeID(segSliceId)

        # Defer clearing the background to the next event loop iteration so that any
        # synchronous link-sync events triggered above (e.g. by AddViewNodeID) have
        # already settled before we apply the final None.
        qt.QTimer.singleShot(0, lambda: segCompositeNode.SetBackgroundVolumeID(None))

    def disableSliceVisibilityIn3DView(self, viewNames):
        for viewName in viewNames:
            sliceNode = slicer.util.getFirstNodeByClassByName("vtkMRMLSliceNode", viewName)
            if sliceNode:
                sliceNode.SetSliceVisible(False)

    def exitSideBySideSegmentation(self):
        segNodes = slicer.util.getNodesByClass("vtkMRMLSegmentationNode")
        for segNode in segNodes:
            # Image log has its own handling of segmentation visibility
            if not segNode.GetAttribute("ImageLogSegmentation"):
                displayNode = segNode.GetDisplayNode()
                if displayNode is None:
                    continue

                displayNode.SetOpacity(0.5)
                # Show segmentation on any view
                displayNode.RemoveAllViewNodeIDs()

        self.disableSliceVisibilityIn3DView(viewNames=["SideBySideImageSlice", "SideBySideSegmentationSlice"])

    @staticmethod
    def _linkViews(viewNames):
        for viewName in viewNames:
            slicer.app.layoutManager().sliceWidget(viewName).sliceLogic().GetSliceCompositeNode().SetLinkedControl(1)

    @staticmethod
    def _useSameBackgroundAs(fromSlice, toSlice):
        layout = slicer.app.layoutManager()
        toLogic = layout.sliceWidget(toSlice).sliceLogic()
        toComposite = toLogic.GetSliceCompositeNode()
        if toComposite.GetBackgroundVolumeID() != None:
            # This slice already has a background, don't change it
            return
        fromLogic = layout.sliceWidget(fromSlice).sliceLogic()
        fromComposite = fromLogic.GetSliceCompositeNode()

        toComposite.SetBackgroundVolumeID(fromComposite.GetBackgroundVolumeID())

        fromLogic.FitSliceToAll()
        toLogic.FitSliceToAll()

    @staticmethod
    def _useSameForegroundAs(fromSlice, toSlice):
        layout = slicer.app.layoutManager()
        toLogic = layout.sliceWidget(toSlice).sliceLogic()
        toComposite = toLogic.GetSliceCompositeNode()
        if toComposite.GetForegroundVolumeID() != None:
            # This slice already has a foreground, don't change it
            return
        fromLogic = layout.sliceWidget(fromSlice).sliceLogic()
        fromComposite = fromLogic.GetSliceCompositeNode()

        toComposite.SetForegroundVolumeID(fromComposite.GetForegroundVolumeID())
        toComposite.SetForegroundOpacity(fromComposite.GetForegroundOpacity())

        fromLogic.FitSliceToAll()
        toLogic.FitSliceToAll()
