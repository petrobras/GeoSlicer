import slicer
from commons import constants
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest


class SideBySideLayoutViewTest(LTracePluginTest):
    def _test_disable_slice_visibility_in_3D_view_when_leaving_layout(self, layoutId, viewName):
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)

        slicer.app.layoutManager().setLayout(layoutId)
        sliceNode = slicer.util.getFirstNodeByClassByName("vtkMRMLSliceNode", viewName)
        assert sliceNode is not None
        sliceNode.SetSliceVisible(True)
        assert sliceNode.GetSliceVisible() == 1

        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)
        slicer.app.layoutManager().setLayout(layoutId)
        assert sliceNode.GetSliceVisible() == 0

    def test_slice1_invisible_in_3D_view_when_leaving_side_by_side_image(self):
        self._test_disable_slice_visibility_in_3D_view_when_leaving_layout(
            layoutId=constants.SIDE_BY_SIDE_IMAGE_LAYOUT_ID, viewName="SideBySideSlice1"
        )

    def test_slice2_invisible_in_3D_view_when_leaving_side_by_side_image(self):
        self._test_disable_slice_visibility_in_3D_view_when_leaving_layout(
            layoutId=constants.SIDE_BY_SIDE_IMAGE_LAYOUT_ID, viewName="SideBySideSlice2"
        )

    def test_image_slice_invisible_in_3D_view_when_leaving_side_by_side_segmentation(self):
        self._test_disable_slice_visibility_in_3D_view_when_leaving_layout(
            layoutId=constants.SIDE_BY_SIDE_SEGMENTATION_LAYOUT_ID, viewName="SideBySideImageSlice"
        )

    def test_segmentation_slice_invisible_in_3D_view_when_leaving_side_by_side_segmentation(self):
        self._test_disable_slice_visibility_in_3D_view_when_leaving_layout(
            layoutId=constants.SIDE_BY_SIDE_SEGMENTATION_LAYOUT_ID, viewName="SideBySideSegmentationSlice"
        )
