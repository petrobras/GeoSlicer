import numpy as np
import vtk
import vtk.util.numpy_support as vn
import slicer

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events


class ImageLogSegmentEditorTest(LTracePluginTest):
    def post_setup(self):
        slicer.modules.PeriodicLevelTracingEffectInstance.registerEditorEffect()

    def _buildRectPoly(self, x0, y0, x1, y1):
        """Return a closed rectangle vtkPolyData in (x=I_tiled, y=K, z=0) space."""
        pts = vtk.vtkPoints()
        pts.InsertNextPoint(x0, y0, 0)
        pts.InsertNextPoint(x1, y0, 0)
        pts.InsertNextPoint(x1, y1, 0)
        pts.InsertNextPoint(x0, y1, 0)

        lines = vtk.vtkCellArray()
        lines.InsertNextCell(5)
        lines.InsertCellPoint(0)
        lines.InsertCellPoint(1)
        lines.InsertCellPoint(2)
        lines.InsertCellPoint(3)
        lines.InsertCellPoint(0)

        pd = vtk.vtkPolyData()
        pd.SetPoints(pts)
        pd.SetLines(lines)
        return pd

    def _setupNodes(self, NI, NJ, NK):
        """Create a flat synthetic volume (NI×NJ×NK) and an empty segmentation."""
        volumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        imageData = vtk.vtkImageData()
        imageData.SetDimensions(NI, NJ, NK)
        imageData.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
        imageData.GetPointData().GetScalars().Fill(128)
        volumeNode.SetAndObserveImageData(imageData)

        segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        segmentationNode.GetSegmentation().AddEmptySegment("Segment_1", "Segment_1")
        return volumeNode, segmentationNode

    def _activateEffect(self, volumeNode, segmentationNode, effect):
        """Connect nodes to the editor, activate the effect, and return the effect instance."""
        widget = self._module_widget
        cse = widget.customizedSegmentEditorWidget
        cse.enter()
        cse.segmentationNodeComboBox.setCurrentNode(segmentationNode)
        cse.sourceVolumeNodeComboBox.setCurrentNode(volumeNode)
        process_events()

        assert cse.segmentationNodeComboBox.currentNode() == segmentationNode, "Segmentation node was not set correctly"
        assert cse.sourceVolumeNodeComboBox.currentNode() == volumeNode, "Source volume node was not set correctly"

        editor = widget.segmentEditorWidget
        segmentId = segmentationNode.GetSegmentation().GetNthSegmentID(0)
        editor.setCurrentSegmentID(segmentId)
        editor.setActiveEffectByName(effect)
        process_events()

        activeEffectName = cse.parameterSetNode.GetActiveEffectName()
        assert activeEffectName == effect, f"Active effect is '{activeEffectName}', expected '{effect}'"

        return editor.effectByName(effect).self()

    def _callApplyMask(self, effectInstance, tiledPD, W, j):
        """Inject a pre-built tiled contour and call applyMask."""
        sliceWidget = slicer.app.layoutManager().sliceWidget("Red")

        pipeline = effectInstance.pipelineForWidget(sliceWidget)
        pipeline._tiledPolyData = tiledPD
        pipeline._tileW = W
        pipeline._lastSeedJ = j

        modifierLabelmap = effectInstance.scriptedEffect.defaultModifierLabelmap()
        pipeline.applyMask(modifierLabelmap)

        dims = modifierLabelmap.GetDimensions()
        arr = vn.vtk_to_numpy(modifierLabelmap.GetPointData().GetScalars())
        return arr.reshape(dims[2], dims[1], dims[0])[:, j, :]

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_well_log_effects_availability(self):
        widget = self._module_widget
        widget.enter()

        widget.configureEffects()
        availableEffects = widget.segmentEditorWidget.effectNameOrder()
        expectedEffects = [
            "Threshold",
            "Paint",
            "Draw",
            "Erase",
            "Level tracing",
            "Periodic level tracing",
            "Margin",
            "Smoothing",
            "Scissors",
            "Islands",
            "Watershed",
            "Logical operators",
            "Mask Image",
            "Multiple Threshold",
            "Depth Segmenter",
            "Boundary removal",
        ]

        for expectedEffect in expectedEffects:
            assert expectedEffect in availableEffects

    def test_apply_mask_non_wrapping(self):
        """Tests the common case: a pore that lies entirely within the image, not touching
        the left or right edge."""
        NI, NJ, NK = 10, 1, 10
        W = NI
        j = 0

        volumeNode, segmentationNode = self._setupNodes(NI, NJ, NK)
        effectInstance = self._activateEffect(volumeNode, segmentationNode, "Periodic level tracing")

        tiledPD = self._buildRectPoly(W + 2, 2, W + 8, 8)
        result = self._callApplyMask(effectInstance, tiledPD, W, j)

        assert np.count_nonzero(result) > 0, "applyMask should have filled some pixels"

        # Pixels outside the rectangle (with one-pixel margin) must be empty
        assert np.all(result[:2, :] == 0), "Rows 0..1 should be empty (above the rectangle)"
        assert np.all(result[9:, :] == 0), "Row 9 should be empty (below the rectangle)"
        assert np.all(result[:, :2] == 0), "Cols 0..1 should be empty (left of the rectangle)"
        assert np.all(result[:, 9:] == 0), "Col 9 should be empty (right of the rectangle)"

    def test_apply_mask_wrapping(self):
        """Tests the periodic boundary case: a pore whose body straddles the left/right image
        edge (e.g. a pore that exits the right side and re-enters from the left)."""
        NI, NJ, NK = 10, 1, 10
        W = NI
        j = 0

        volumeNode, segmentationNode = self._setupNodes(NI, NJ, NK)
        effectInstance = self._activateEffect(volumeNode, segmentationNode, "Periodic level tracing")

        tiledPD = self._buildRectPoly(W - 2, 2, W + 2, 8)
        result = self._callApplyMask(effectInstance, tiledPD, W, j)

        assert np.count_nonzero(result) > 0, "applyMask should have filled some pixels"

        # Left and right edges (wrapping region) must be filled
        assert np.any(result[2:8, 0:2] == 1), "Left edge (cols 0..1) should be filled"
        assert np.any(result[2:8, 8:10] == 1), "Right edge (cols 8..9) should be filled"

        # The centre columns must remain empty (only the periodic boundary region is filled)
        assert np.all(result[:, 3:7] == 0), "Centre columns 3..6 should be empty"

    def test_apply_mask_fills_smaller_region(self):
        """applyMask inverts the fill when the contour encloses more than half the image area."""
        NI, NJ, NK = 10, 1, 10
        W = NI
        j = 0

        volumeNode, segmentationNode = self._setupNodes(NI, NJ, NK)
        effectInstance = self._activateEffect(volumeNode, segmentationNode, "Periodic level tracing")

        tiledPD = self._buildRectPoly(W + 1, 1, W + 9, 9)
        result = self._callApplyMask(effectInstance, tiledPD, W, j)

        assert np.count_nonzero(result) > 0, "applyMask should have filled some pixels"

        # The deep interior must be mostly empty (only the outer ring is filled).
        interior = result[2:8, 2:8]
        total_filled = np.count_nonzero(result)
        interior_filled = np.count_nonzero(interior)
        assert interior_filled < total_filled, (
            "The large interior should NOT be filled — only the smaller exterior ring should be"
        )
