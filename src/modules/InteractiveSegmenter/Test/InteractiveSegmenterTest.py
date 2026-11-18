import qt
import slicer
import json
import re
import os
import shutil
import tempfile
import vtk
import warnings
import numpy as np
from humanize import naturalsize
from pathlib import Path

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import close_project, load_project, waitCondition, process_events
from commons.interactive.widget import (
    ApplyToOtherImagesDialog,
    InteractiveSegmenterFrame,
    LARGE_IMAGE_VOXEL_LIMIT,
    RealTimeSegLogic,
    get_annotation_node,
    is_large_3d_image,
)
from commons.interactive import (
    features,
    features_2d,
    forest,
    lazy_2d,
    reporting,
    resources,
    volume_3d,
)
from commons.interactive.ipc import (
    InterprocessPaths,
    safe_save_numpy,
    FeatureIndex,
    compute_preview_factor,
    PREVIEW_MAX_PIXELS,
)
from commons.slicer import helpers
from commons.slicer.helpers import SegmentationNodeArray
from commons.constants import SIDE_BY_SIDE_DUMB_LAYOUT_ID
from CustomizedCropVolume import CustomizedCropVolumeLogic

RESOURCES = Path(__file__).parent / "Resources"
PROJECT_FILE = RESOURCES / "InteractiveSegmenterExample" / "InteractiveSegmenterExample.mrml"


def _plane_center_ijk(slice_obj, volume_node):
    """Full-precision IJK position of the slice plane's center point."""
    node = slice_obj.node
    dims = node.GetDimensions()
    center_ras = node.GetXYToRAS().MultiplyPoint([(dims[0] - 1) / 2.0, (dims[1] - 1) / 2.0, 0, 1])
    ijk_to_ras = vtk.vtkMatrix4x4()
    volume_node.GetIJKToRASMatrix(ijk_to_ras)
    ras_to_ijk = vtk.vtkMatrix4x4()
    vtk.vtkMatrix4x4.Invert(ijk_to_ras, ras_to_ijk)
    return ras_to_ijk.MultiplyPoint(center_ras)[:3]


def _select_in_tree(tree_view, nodes):
    sh = slicer.mrmlScene.GetSubjectHierarchyNode()
    items = vtk.vtkIdList()
    for node in nodes:
        items.InsertNextId(sh.GetItemByDataNode(node))
    tree_view.setCurrentItems(items)
    process_events()


class _StubFullApplyState:
    """Enough of the segmentation state for the widget's apply bookkeeping."""

    applying_full_image = True

    def __init__(self):
        self.inference_volume_node = None

    def request_full_apply(self, node):
        self.inference_volume_node = node


class InteractiveSegmenterTest(LTracePluginTest):
    def test_full_segmentation(self):
        """
        Run a full segmentation using an existing annotation and compare
        it with the expected result segmentation.
        """
        load_project(PROJECT_FILE)

        source_volume = slicer.util.getNode("Input_volume")
        self.assertIsNotNone(source_volume)

        expected_segmentation = slicer.util.getNode("ExpectedResult")
        self.assertIsNotNone(expected_segmentation)

        widget = self._module_widget.interactive_segmenter_frame
        self.assertIsNotNone(widget)

        # Set the input node in the widget
        widget._inputSelector.setCurrentNode(source_volume)
        process_events()

        # Start the segmentation process
        widget._runButton.click()
        process_events()

        # Wait for the segmentation process to start and features to be calculated
        waitCondition(lambda: widget._applyButton.enabled, timeoutSec=60)

        # Trigger the full image segmentation
        widget._applyButton.click()
        process_events()

        # Wait for the full segmentation to complete
        waitCondition(lambda: slicer.mrmlScene.GetFirstNodeByName("Input_volume_Segmented") is not None, timeoutSec=60)

        result_segmentation = slicer.util.getNode("Input_volume_Segmented")

        # Compare the result with the expected segmentation
        with (
            SegmentationNodeArray(expected_segmentation) as array1,
            SegmentationNodeArray(result_segmentation) as array2,
        ):
            np.testing.assert_array_equal(array1, array2)

    def test_full_apply_survives_module_exit(self):
        """Leaving the module during a full-image apply must not cancel it."""
        load_project(PROJECT_FILE)

        source_volume = slicer.util.getNode("Input_volume")
        widget = self._module_widget.interactive_segmenter_frame

        widget._inputSelector.setCurrentNode(source_volume)
        process_events()

        widget._runButton.click()
        process_events()
        waitCondition(lambda: widget._applyButton.enabled, timeoutSec=60)

        widget._applyButton.click()
        process_events()

        self._module_widget.exit()
        process_events()
        self.assertIsNotNone(widget._state)
        self.assertTrue(widget._state.is_running())

        waitCondition(lambda: slicer.mrmlScene.GetFirstNodeByName("Input_volume_Segmented") is not None, timeoutSec=60)
        self.assertIsNotNone(slicer.mrmlScene.GetFirstNodeByName("Input_volume_Segmented"))
        self.assertIsNone(widget._state)

    def _make_two_tone_image(self, name, shape, spacing=None):
        """Noisy image of `shape` (K, J, I) whose left half is dark and right half bright."""
        rng = np.random.default_rng(0)
        array = np.zeros(shape, dtype=np.int16)
        array[..., : shape[-1] // 2] = 60
        array[..., shape[-1] // 2 :] = 200
        array = np.clip(array + rng.integers(-10, 10, array.shape), 0, 255).astype(np.uint8)
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", name)
        slicer.util.updateVolumeFromArray(node, array)
        if spacing:
            node.SetSpacing(*spacing)
        return node

    def test_apply_to_multiple_images(self):
        """One trained model applied in sequence to several images of different sizes."""
        source_volume = self._make_two_tone_image("Batch_source", (1, 200, 300))
        volumes = [
            source_volume,
            self._make_two_tone_image("Batch_other1", (1, 150, 260)),
            self._make_two_tone_image("Batch_other2", (1, 220, 180)),
        ]

        widget = self._module_widget.interactive_segmenter_frame
        widget._inputSelector.setCurrentNode(source_volume)
        process_events()

        widget._runButton.click()
        process_events()
        waitCondition(lambda: widget._state and widget._state.features_ready, timeoutSec=60)

        strokes = np.zeros((1, 200, 300), dtype=np.uint8)
        strokes[0, 90:110, 40:80] = 1
        strokes[0, 90:110, 220:260] = 2
        strokes_labelmap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(strokes_labelmap, strokes)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
            strokes_labelmap, get_annotation_node(source_volume)
        )
        slicer.mrmlScene.RemoveNode(strokes_labelmap)
        process_events()

        waitCondition(lambda: widget._applyButton.enabled, timeoutSec=60)
        self.assertTrue(widget._batchButton.enabled)

        # The dialog is modal, so it is driven directly instead of through the button
        # that opens it.
        dialog = ApplyToOtherImagesDialog(widget._state.annotation_node.GetSegmentation().GetNumberOfSegments())
        _select_in_tree(dialog._treeView, volumes)
        self.assertEqual(
            {node.GetID() for node in dialog.selectedNodes()},
            {volume.GetID() for volume in volumes},
        )
        self.assertEqual(dialog._summaryLabel.text, "Will apply a model with 2 segments to 3 images.")

        selected = dialog.selectedNodes()
        dialog.deleteLater()
        widget._startApply(selected)
        process_events()
        self.assertTrue(widget._applyLogTextEdit.visible)
        # The tree hands over its selection in its own order; the log must follow it.
        queued = [widget._state.inference_volume_node] + list(widget._applyQueue)

        for volume in volumes:
            waitCondition(
                lambda name=f"{volume.GetName()}_Segmented": slicer.mrmlScene.GetFirstNodeByName(name) is not None,
                timeoutSec=120,
            )
        waitCondition(lambda: widget._state is None, timeoutSec=30)
        self.assertIsNone(widget._state)

        # The log tells which images ran, in which order, and what each one produced.
        # It is append-only, so the per-step lines the consumer reported sit between
        # these; only the lines that open and close an image are asserted on here.
        def opening_line(index, volume):
            image = volume.GetImageData()
            dimensions = image.GetDimensions()
            occupied = np.prod(dimensions, dtype=np.int64) * image.GetScalarSize() * image.GetNumberOfScalarComponents()
            return (
                f"[{index}/3] Running full inference for image '{volume.GetName()}' "
                f"of size {'x'.join(str(d) for d in dimensions)} ({naturalsize(occupied, binary=True)})"
            )

        log_lines = widget._applyLogTextEdit.toPlainText().splitlines()

        # The elapsed times are real measurements, so they are blanked before the
        # comparison; that each line carries one is what the assertion checks.
        def without_times(line):
            line = re.sub(r"^Done in .+?, created ", "Done in <time>, created ", line)
            return re.sub(r"^(Finished all \d+ images in ).+\.$", r"\g<1><time>.", line)

        self.assertEqual(
            [without_times(line) for line in log_lines if line.startswith(("[", "Done", "Finished"))],
            [
                line
                for index, volume in enumerate(queued, start=1)
                for line in (opening_line(index, volume), f"Done in <time>, created {volume.GetName()}_Segmented")
            ]
            + ["Finished all 3 images in <time>."],
        )
        # Nothing is ever overwritten, so every step the consumer reported is still there.
        self.assertTrue([line for line in log_lines if "calculating prediction" in line], log_lines)

        # The log is the record of the run, so it survives the session ending with it.
        self.assertTrue(widget._applyLogTextEdit.visible)
        self.assertEqual(widget._applyLogHeaderLabel.text, "Segmentation complete. Logs for the last run:")

        # Only the last result is shown, so overlapping results don't pile up in the views.
        for index, volume in enumerate(queued):
            result = slicer.util.getNode(f"{volume.GetName()}_Segmented")
            is_last = index == len(queued) - 1
            self.assertEqual(bool(result.GetDisplayNode().GetVisibility()), is_last)

        # Each result must follow the geometry of its own image, not the input's.
        for volume in volumes:
            result = slicer.util.getNode(f"{volume.GetName()}_Segmented")
            labelmap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
            slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(result, labelmap, volume)
            array = slicer.util.arrayFromVolume(labelmap)
            self.assertEqual(array.shape, slicer.util.arrayFromVolume(volume).shape)

            width = array.shape[2]
            left_label = np.bincount(array[0, :, : width // 2].ravel()).argmax()
            right_label = np.bincount(array[0, :, width // 2 :].ravel()).argmax()
            self.assertNotEqual(left_label, 0)
            self.assertNotEqual(right_label, 0)
            self.assertNotEqual(left_label, right_label)
            slicer.mrmlScene.RemoveNode(labelmap)

    def test_apply_to_image_of_another_geometry_ignores_the_preview(self):
        """The accumulated 3D preview belongs to the input image. Merging the applied
        result into it resamples onto the input's grid over the union of both images,
        which for a much finer input spacing is a labelmap of tens of GB."""
        source_volume = self._make_two_tone_image("Fine3D", (24, 32, 32), (0.25, 0.25, 0.25))
        other_volume = self._make_two_tone_image("Coarse3D", (20, 20, 20), (1.0, 1.0, 1.0))

        widget = self._module_widget.interactive_segmenter_frame
        widget._inputSelector.setCurrentNode(source_volume)
        process_events()

        widget._runButton.click()
        process_events()
        waitCondition(lambda: widget._state and widget._state.features_ready, timeoutSec=120)

        strokes = np.zeros((24, 32, 32), dtype=np.uint8)
        strokes[8:16, 12:20, 4:12] = 1
        strokes[8:16, 12:20, 20:28] = 2
        strokes_labelmap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(strokes_labelmap, strokes)
        strokes_labelmap.CopyOrientation(source_volume)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
            strokes_labelmap, get_annotation_node(source_volume)
        )
        slicer.mrmlScene.RemoveNode(strokes_labelmap)
        process_events()

        waitCondition(lambda: widget._applyButton.enabled, timeoutSec=120)
        self.assertTrue(widget._applyButton.enabled)
        # Without an accumulated preview there is nothing for the result to be merged into.
        waitCondition(
            lambda: widget._state.result_segmentation_node.GetSegmentation().GetNumberOfSegments() > 0,
            timeoutSec=120,
        )
        self.assertGreater(widget._state.result_segmentation_node.GetSegmentation().GetNumberOfSegments(), 0)

        widget._startApply([other_volume])
        process_events()
        waitCondition(lambda: slicer.mrmlScene.GetFirstNodeByName("Coarse3D_Segmented") is not None, timeoutSec=120)

        segmentation = slicer.util.getNode("Coarse3D_Segmented").GetSegmentation()
        self.assertGreater(segmentation.GetNumberOfSegments(), 0)
        for index in range(segmentation.GetNumberOfSegments()):
            labelmap = segmentation.GetNthSegment(index).GetRepresentation(
                slicer.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName()
            )
            self.assertEqual(labelmap.GetSpacing(), other_volume.GetSpacing())
            i_min, i_max, j_min, j_max, k_min, k_max = labelmap.GetExtent()
            voxels = (i_max - i_min + 1) * (j_max - j_min + 1) * (k_max - k_min + 1)
            self.assertLessEqual(voxels, 20 * 20 * 20)

    def test_apply_log_keeps_every_step(self):
        """The log is append-only: a step is never rewritten by the one after it, and the
        status line -- not the log -- is what carries the single current action."""
        widget = self._module_widget.interactive_segmenter_frame
        widget._applyTotal = 1
        widget._applyQueue = []
        widget._applySlab = 0
        widget._applySlabTotal = 0
        widget._applyFirstSlabTime = None
        widget._applyLogTextEdit.clear()

        entries = [
            {"message": "Divided in 3 slabs, each with size 16x16x4 (12.0 KiB of features)", "slabs": 3},
            {"message": "Slab 1/3 - calculating features", "slab": 1, "slabs": 3},
            {"message": "Slab 1/3 - calculating prediction", "slab": 1, "slabs": 3},
        ]
        widget._onApplyLog(entries)

        self.assertEqual(widget._applyLogTextEdit.toPlainText().splitlines(), [entry["message"] for entry in entries])
        self.assertEqual(widget._statusLabel.text, "Slab 1/3 - calculating prediction")

    def test_apply_status_shows_eta_once_a_slab_has_finished(self):
        """The ETA extrapolates from slabs that actually finished, so it appears on the
        second slab and not before -- there is nothing to extrapolate from until then."""
        widget = self._module_widget.interactive_segmenter_frame
        widget._applyTotal = 1
        widget._applyQueue = []
        widget._applySlab = 0
        widget._applySlabTotal = 0
        widget._applyFirstSlabTime = None
        widget._applyLogTextEdit.clear()

        widget._onApplyLog([{"message": "Slab 1/4 - calculating features", "slab": 1, "slabs": 4}])
        self.assertNotIn("ETA", widget._statusLabel.text)

        # A slab that took a minute leaves three to go, so about three minutes.
        widget._applyFirstSlabTime -= 60
        widget._onApplyLog([{"message": "Slab 2/4 - calculating prediction", "slab": 2, "slabs": 4}])
        self.assertEqual(widget._statusLabel.text, "Slab 2/4 - calculating prediction - ETA: 3 minutes")

    def test_full_apply_filters_the_next_slab_while_it_predicts(self):
        """The two phases are pipelined, and the log is the only place that shows it:
        the next slab's features must start before the current slab is done, or the
        filter threads are idling through every prediction (measured 1.47x slower).
        """
        temp_dir = Path(slicer.app.temporaryPath) / "InteractiveSegmenterPipelineTest"
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True)
        paths = InterprocessPaths(temp_dir)

        rng = np.random.default_rng(0)
        X_train = rng.random((2000, 2)).astype(np.float32)
        y_train = np.digitize(X_train[:, 0], [0.5]).astype(np.uint8) + 1
        model = forest.make_model(1).fit(X_train, y_train)
        source = rng.integers(0, 4096, (24, 16, 16), dtype=np.uint16)

        # A fixture this small fits in one slab, and one slab has nothing to overlap;
        # the override is the same knob the memory budget would turn on a real volume.
        os.environ[resources.SLAB_THICKNESS_ENV] = "6"
        try:
            volume_3d.predict_full_3d(model, source, [0, 1], features.FeatureScale.from_multiplier(1), paths)
            messages = [json.loads(line)["message"] for line in paths.apply_log.read_text().splitlines()]
        finally:
            os.environ.pop(resources.SLAB_THICKNESS_ENV, None)
            shutil.rmtree(temp_dir, ignore_errors=True)

        slabs = sum(1 for message in messages if " - calculating prediction" in message)
        self.assertGreater(slabs, 1, "the fixture is meant to need several slabs")
        next_features = messages.index(f"Slab 2/{slabs} - calculating features")
        first_done = next(i for i, message in enumerate(messages) if message.startswith(f"Slab 1/{slabs} - done"))
        self.assertLess(next_features, first_done)

    def test_slab_plan_leaves_room_for_both_slabs_in_flight(self):
        """Pipelining keeps two design matrices alive at the handover, so a plan that
        budgeted for one would overshoot the memory it promised to stay inside."""
        plane_bytes, margin, n_columns, budget = 16 * 16 * 4, 3, 6, 64 * 1024 * 1024
        thickness, workers = volume_3d.fused_slab_plan(4096, plane_bytes, margin, n_columns, 1, budget, 12)
        haloed = volume_3d.PREDICT_FILTER_COPIES * workers + 1
        peak = plane_bytes * (
            volume_3d.PREDICT_SLAB_BUFFERS * n_columns * thickness + haloed * (thickness + 2 * margin)
        )
        self.assertLessEqual(peak, budget)
        self.assertGreaterEqual(volume_3d.PREDICT_SLAB_BUFFERS, 2)

    def test_apply_log_keeps_lines_written_between_two_polls(self):
        """The consumer writes its log far faster than the widget polls, so the channel
        has to be append-only on disk too: a burst between two polls must arrive whole."""
        temp_dir = Path(slicer.app.temporaryPath) / "InteractiveSegmenterLogTest"
        shutil.rmtree(temp_dir, ignore_errors=True)
        paths = InterprocessPaths(temp_dir)

        drained = []
        state = RealTimeSegLogic.__new__(RealTimeSegLogic)
        state.paths = paths
        state.apply_log_offset = 0
        state.on_apply_log_callback = drained.extend

        state._drain_apply_log()  # nothing written yet
        for slab in (1, 2):
            reporting.log_apply(paths.apply_log, f"Slab {slab}/2 - calculating features", slab=slab, slabs=2)
            reporting.log_apply(paths.apply_log, f"Slab {slab}/2 - calculating prediction", slab=slab, slabs=2)
        state._drain_apply_log()
        state._drain_apply_log()  # a second drain must not repeat what it already handed over

        self.assertEqual(
            [entry["message"] for entry in drained],
            [
                "Slab 1/2 - calculating features",
                "Slab 1/2 - calculating prediction",
                "Slab 2/2 - calculating features",
                "Slab 2/2 - calculating prediction",
            ],
        )
        self.assertEqual(drained[-1], {"message": "Slab 2/2 - calculating prediction", "slab": 2, "slabs": 2})
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_batched_predict_matches_sklearn(self):
        """The full apply sums the trees' leaf probabilities itself instead of calling
        RandomForestClassifier.predict, which spends most of its time on float64
        bookkeeping. It has to be the same argmax over the same sums, not merely a
        close one: a voxel that flips is a voxel the user sees change colour.
        """
        rng = np.random.default_rng(0)
        X_train = rng.random((4000, 5)).astype(np.float32)
        # Overlapping, noisy classes, so the leaves are impure and soft voting
        # genuinely differs from a majority vote over the trees.
        y_train = np.digitize(X_train @ rng.random(5) + rng.normal(0, 0.4, 4000), [0.9, 1.4]).astype(np.uint8)
        model = forest.make_model(1).fit(X_train, y_train)
        self.assertGreater(
            sum((e.tree_.value[e.tree_.children_left == -1, 0, :].max(axis=1) < 1.0).sum() for e in model.estimators_),
            0,
            "the fixture is meant to have impure leaves",
        )

        # Feature-major then transposed, exactly as the fused apply builds it.
        X = rng.random((5, 300_000)).astype(np.float32).T
        for n_jobs in (1, 4):
            model.n_jobs = n_jobs
            np.testing.assert_array_equal(forest.predict_in_batches(model, X), model.predict(X))

        # More rows than one batch holds, so the batch seam itself is covered.
        self.assertGreater(X.shape[0], forest.PREDICT_ACCUMULATOR_BYTES // (int(model.n_classes_) * 4))
        # And the shapes the guard clauses cover still go somewhere sensible.
        self.assertEqual(forest.predict_in_batches(model, X[:0]).shape, (0,))
        np.testing.assert_array_equal(
            forest.predict_in_batches(model, X[:10].astype(np.float64)), model.predict(X[:10])
        )

    def test_apply_progress_covers_the_whole_queue(self):
        """The progress bar tracks the whole run; the consumer only reports on the image
        it is working on."""
        widget = self._module_widget.interactive_segmenter_frame
        widget._applyTotal = 3

        widget._applyQueue = [None, None]  # the first of three images is running
        self.assertEqual(widget._queueProgress(0), 0)
        self.assertEqual(widget._queueProgress(100), 33)

        widget._applyQueue = []  # the last one is
        self.assertEqual(widget._queueProgress(50), 83)
        self.assertEqual(widget._queueProgress(100), 100)

        widget._applyTotal = 1
        self.assertEqual(widget._queueProgress(42), 42)

    def test_apply_progress_never_goes_backwards(self):
        """RED: `_applyNextInQueue` puts the bar back into the indeterminate range at
        every image boundary, so the fill drops to zero between images."""
        widget = self._module_widget.interactive_segmenter_frame
        # Real (if tiny) images: the log line opening each one states its size.
        nodes = [self._make_two_tone_image(f"Monotonic{index}", (1, 8, 8)) for index in range(3)]
        widget._state = _StubFullApplyState()
        widget._applyQueue = list(nodes)
        widget._applyTotal = len(nodes)
        widget._applyLogTextEdit.clear()
        widget._applyProgress = 0

        samples = []
        for _ in nodes:
            widget._applyNextInQueue()
            samples.append((widget._progressBar.maximum, widget._progressBar.value))
            # 40 after 60: the bar tracks the queue, so a report that dips on the running
            # image must not move it back either.
            for progress in (0, 60, 40, 100):
                widget._onFeatureProgressUpdate(progress, "phase")
                samples.append((widget._progressBar.maximum, widget._progressBar.value))
        widget._state = None

        self.assertTrue(all(maximum == 100 for maximum, _ in samples), samples)
        values = [value for _, value in samples]
        self.assertEqual(values, sorted(values), values)
        self.assertEqual(values[-1], 100)

    def test_batch_tree_populated_at_construction_does_not_crash(self):
        """
        RED: the dialog tree's ``currentItemsChanged`` is connected before the summary
        label it updates exists, so the selection change the tree emits while being
        populated -- which happens whenever the scene already holds a volume -- raises
        ``AttributeError: ApplyToOtherImagesDialog has no attribute named
        '_summaryLabel'``. PythonQt swallows the exception, which the test framework's
        excepthook turns into a failure.
        """
        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "BatchTreeProbe")
        slicer.util.updateVolumeFromArray(volume, np.zeros((8, 8, 8), dtype=np.uint8))
        process_events()

        dialog = ApplyToOtherImagesDialog(2)
        process_events()
        self.assertEqual([node.GetID() for node in dialog.selectedNodes()], [])
        dialog.deleteLater()

    def test_dialog_buttons_close_the_dialog(self):
        """
        RED: ``clicked`` carries a ``checked`` bool that PythonQt forwards to the slot,
        so connecting it straight to ``accept``/``reject`` raises ``ValueError: Called
        accept() -> void with wrong number of arguments: (False,)`` and the dialog never
        closes.
        """
        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "DialogButtonProbe")
        slicer.util.updateVolumeFromArray(volume, np.zeros((8, 8, 8), dtype=np.uint8))
        process_events()

        for button_name, expected in (("_cancelButton", qt.QDialog.Rejected), ("_applyButton", qt.QDialog.Accepted)):
            dialog = ApplyToOtherImagesDialog(2)
            _select_in_tree(dialog._treeView, [volume])
            getattr(dialog, button_name).click()
            process_events()
            self.assertEqual(dialog.result(), expected, button_name)
            dialog.deleteLater()

    def test_dialog_is_parented(self):
        """
        RED: a parentless dialog belongs to PythonQt, so the ``deleteLater()`` these
        tests post races Python's collection of it and GeoSlicer dies with an access
        violation in ``QWidget::~QWidget`` once the event loop resumes - after the whole
        suite has already reported OK.
        """
        dialog = ApplyToOtherImagesDialog(2)
        self.assertIsNotNone(dialog.parent())
        dialog.deleteLater()

    def test_cancel_segmentation(self):
        """
        Test that cancelling the segmentation cleans up temporary nodes.
        """
        load_project(PROJECT_FILE)

        source_volume = slicer.util.getNode("Input_volume")
        self.assertIsNotNone(source_volume)

        widget = self._module_widget.interactive_segmenter_frame
        self.assertIsNotNone(widget)

        # Set the input node in the widget
        widget._inputSelector.setCurrentNode(source_volume)
        process_events()

        # Store the number of nodes before starting
        editor_nodes_before = slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLSegmentEditorNode")

        # Start the segmentation process
        widget._runButton.click()
        process_events()

        # Wait for the segmentation process to start
        waitCondition(lambda: widget._state and widget._state.is_running(), timeoutSec=60)

        # Check that temporary nodes are created. The merge segment editor is shared
        # across sessions, so a session adds no segment editor node of its own.
        self.assertIsNotNone(slicer.mrmlScene.GetFirstNodeByName("SegmentationPreview"))
        self.assertIsNotNone(slicer.mrmlScene.GetFirstNodeByName("TemporaryResult"))
        self.assertEqual(
            slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLSegmentEditorNode"),
            editor_nodes_before,
        )

        # Cancel the segmentation process
        widget._runButton.click()
        process_events()

        # Wait for the segmentation process to stop
        waitCondition(lambda: widget._state is None, timeoutSec=60)

        # Check that temporary nodes are removed
        self.assertIsNone(slicer.mrmlScene.GetFirstNodeByName("SegmentationPreview"))
        self.assertIsNone(slicer.mrmlScene.GetFirstNodeByName("TemporaryResult"))
        self.assertEqual(
            slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLSegmentEditorNode"),
            editor_nodes_before,
        )

    def test_cancel_during_full_apply_reenables_input(self):
        """Cancelling a running full-image apply must leave the Input section usable."""
        source_volume = self._make_two_tone_image("Cancel_apply_source", (1, 200, 300))

        widget = self._module_widget.interactive_segmenter_frame
        widget._inputSelector.setCurrentNode(source_volume)
        process_events()

        widget._runButton.click()
        process_events()
        waitCondition(lambda: widget._state and widget._state.features_ready, timeoutSec=60)

        strokes = np.zeros((1, 200, 300), dtype=np.uint8)
        strokes[0, 90:110, 40:80] = 1
        strokes[0, 90:110, 220:260] = 2
        strokes_labelmap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(strokes_labelmap, strokes)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
            strokes_labelmap, get_annotation_node(source_volume)
        )
        slicer.mrmlScene.RemoveNode(strokes_labelmap)
        process_events()

        waitCondition(lambda: widget._applyButton.enabled, timeoutSec=60)

        widget._applyButton.click()
        process_events()
        self.assertTrue(widget._state.applying_full_image)

        widget._runButton.click()
        process_events()
        waitCondition(lambda: widget._state is None, timeoutSec=60)

        self.assertTrue(widget._inputSection.enabled)

    def test_output_section_cancel_button(self):
        """The Output section's Cancel stops the session, and the Input section (which
        holds Parameters and the run button) stays collapsed while it runs."""
        source_volume = self._make_two_tone_image("Cancel_button_source", (1, 64, 64))

        widget = self._module_widget.interactive_segmenter_frame
        widget._inputSelector.setCurrentNode(source_volume)
        process_events()

        widget._runButton.click()
        process_events()
        waitCondition(lambda: widget._state and widget._state.is_running(), timeoutSec=60)

        self.assertTrue(widget._inputSection.collapsed)
        self.assertTrue(widget._paramSection.isHidden())
        self.assertTrue(widget._runButton.isHidden())

        widget._cancelButton.click()
        process_events()
        waitCondition(lambda: widget._state is None, timeoutSec=60)

        self.assertFalse(widget._inputSection.collapsed)
        self.assertFalse(widget._paramSection.isHidden())
        self.assertFalse(widget._runButton.isHidden())

    def test_2d_rgb_segmentation(self):
        """
        Segment a synthetic 2D RGB image end to end: annotate two color regions,
        wait for the model, apply to the full image and check the result.
        """
        height, width = 300, 400
        rgb = np.zeros((1, height, width, 3), dtype=np.uint8)
        rgb[0, :, : width // 2] = (200, 60, 60)
        rgb[0, :, width // 2 :] = (60, 60, 200)
        rng = np.random.default_rng(0)
        rgb = np.clip(rgb.astype(np.int16) + rng.integers(-20, 20, rgb.shape), 0, 255).astype(np.uint8)

        source_volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode", "Rgb2D")
        slicer.util.updateVolumeFromArray(source_volume, rgb)

        widget = self._module_widget.interactive_segmenter_frame
        self.assertIsNotNone(widget)

        widget._inputSelector.setCurrentNode(source_volume)
        process_events()

        widget._runButton.click()
        process_events()

        # 2D mode skips feature precalculation, so the annotation section enables quickly
        waitCondition(lambda: widget._state and widget._state.features_ready, timeoutSec=60)

        # A 2D image only has an XY plane, so the view plane selector is locked
        self.assertFalse(widget._viewPlaneComboBox.enabled)
        self.assertEqual(widget._viewPlaneComboBox.currentText, "XY")

        # Annotate a stroke on each color region
        annotation_node = get_annotation_node(source_volume)
        self.assertIsNotNone(annotation_node)

        strokes = np.zeros((1, height, width), dtype=np.uint8)
        strokes[0, 140:160, 40:80] = 1
        strokes[0, 140:160, width - 80 : width - 40] = 2

        strokes_labelmap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(strokes_labelmap, strokes)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(strokes_labelmap, annotation_node)
        slicer.mrmlScene.RemoveNode(strokes_labelmap)
        process_events()

        # Wait for the model to be trained on the annotation
        waitCondition(lambda: widget._applyButton.enabled, timeoutSec=60)

        widget._applyButton.click()
        process_events()

        waitCondition(lambda: slicer.mrmlScene.GetFirstNodeByName("Rgb2D_Segmented") is not None, timeoutSec=60)
        result_segmentation = slicer.util.getNode("Rgb2D_Segmented")

        result_labelmap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(
            result_segmentation, result_labelmap, source_volume
        )
        result_array = slicer.util.arrayFromVolume(result_labelmap)
        self.assertEqual(result_array.shape, strokes.shape)

        # Each half should be covered almost entirely by its own distinct label
        left = result_array[0, :, : width // 2]
        right = result_array[0, :, width // 2 :]
        left_label = np.bincount(left.ravel()).argmax()
        right_label = np.bincount(right.ravel()).argmax()
        self.assertNotEqual(left_label, 0)
        self.assertNotEqual(right_label, 0)
        self.assertNotEqual(left_label, right_label)
        self.assertGreater(np.mean(left == left_label), 0.95)
        self.assertGreater(np.mean(right == right_label), 0.95)

        slicer.mrmlScene.RemoveNode(result_labelmap)

    def test_2d_multi_input(self):
        """
        Segment using extra co-registered images as additional channels: the main
        image is uniform noise and only the extra images separate the classes.
        """
        height, width = 300, 400
        rng = np.random.default_rng(0)
        bright = rng.integers(100, 140, (1, height, width, 3)).astype(np.uint8)

        xpol = np.zeros((1, height, width, 3), dtype=np.uint8)
        xpol[0, :, : width // 2] = (40, 90, 30)
        xpol[0, :, width // 2 :] = (90, 40, 30)
        xpol = np.clip(xpol.astype(np.int16) + rng.integers(-15, 15, xpol.shape), 0, 255).astype(np.uint8)

        source_volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode", "Bright2D")
        slicer.util.updateVolumeFromArray(source_volume, bright)
        extra_volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode", "Xpol2D")
        slicer.util.updateVolumeFromArray(extra_volume, xpol)

        widget = self._module_widget.interactive_segmenter_frame
        widget._inputSelector.setCurrentNode(source_volume)
        widget._extraImageSelectors[0].setCurrentNode(extra_volume)
        process_events()

        widget._runButton.click()
        process_events()
        waitCondition(lambda: widget._state and widget._state.features_ready, timeoutSec=60)
        self.assertEqual(widget._state.extra_volume_nodes, [extra_volume])

        annotation_node = get_annotation_node(source_volume)
        strokes = np.zeros((1, height, width), dtype=np.uint8)
        strokes[0, 140:160, 40:80] = 1
        strokes[0, 140:160, width - 80 : width - 40] = 2
        strokes_labelmap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(strokes_labelmap, strokes)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(strokes_labelmap, annotation_node)
        slicer.mrmlScene.RemoveNode(strokes_labelmap)
        process_events()

        waitCondition(lambda: widget._applyButton.enabled, timeoutSec=60)
        # A batch target is a single node; it cannot name the extra channels it needs.
        self.assertFalse(widget._batchButton.enabled)
        self.assertIn("multiple inputs", widget._batchButton.toolTip)

        widget._applyButton.click()
        process_events()
        waitCondition(lambda: slicer.mrmlScene.GetFirstNodeByName("Bright2D_Segmented") is not None, timeoutSec=60)

        result_labelmap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(
            slicer.util.getNode("Bright2D_Segmented"), result_labelmap, source_volume
        )
        result_array = slicer.util.arrayFromVolume(result_labelmap)

        # The main image is uninformative, so success proves the extra channels are used
        left = result_array[0, :, : width // 2]
        right = result_array[0, :, width // 2 :]
        left_label = np.bincount(left.ravel()).argmax()
        right_label = np.bincount(right.ravel()).argmax()
        self.assertNotEqual(left_label, 0)
        self.assertNotEqual(right_label, 0)
        self.assertNotEqual(left_label, right_label)
        self.assertGreater(np.mean(left == left_label), 0.95)
        self.assertGreater(np.mean(right == right_label), 0.95)

        slicer.mrmlScene.RemoveNode(result_labelmap)

    def test_3d_two_channel(self):
        """
        Segment a 3D volume using a second co-registered scalar volume as an
        extra channel; only the extra volume separates the classes.
        """
        shape = (48, 64, 80)  # (K, J, I)
        rng = np.random.default_rng(0)
        dry = rng.normal(128, 20, shape).astype(np.float32)

        saturated = np.where(np.arange(shape[2])[np.newaxis, np.newaxis, :] < shape[2] // 2, 80.0, 180.0)
        saturated = np.broadcast_to(saturated, shape) + rng.normal(0, 10, shape)
        saturated = saturated.astype(np.float32)

        source_volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Dry3D")
        slicer.util.updateVolumeFromArray(source_volume, dry)
        extra_volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Saturated3D")
        slicer.util.updateVolumeFromArray(extra_volume, saturated)

        widget = self._module_widget.interactive_segmenter_frame
        widget._inputSelector.setCurrentNode(source_volume)
        widget._extraImageSelectors[1].setCurrentNode(extra_volume)
        process_events()

        widget._runButton.click()
        process_events()
        waitCondition(lambda: widget._state and widget._state.features_ready, timeoutSec=120)

        annotation_node = get_annotation_node(source_volume)
        strokes = np.zeros(shape, dtype=np.uint8)
        strokes[20:28, 28:36, 10:30] = 1
        strokes[20:28, 28:36, 50:70] = 2
        strokes_labelmap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(strokes_labelmap, strokes)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(strokes_labelmap, annotation_node)
        slicer.mrmlScene.RemoveNode(strokes_labelmap)
        process_events()

        waitCondition(lambda: widget._applyButton.enabled, timeoutSec=120)
        widget._applyButton.click()
        process_events()
        waitCondition(lambda: slicer.mrmlScene.GetFirstNodeByName("Dry3D_Segmented") is not None, timeoutSec=120)

        result_labelmap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(
            slicer.util.getNode("Dry3D_Segmented"), result_labelmap, source_volume
        )
        result_array = slicer.util.arrayFromVolume(result_labelmap)
        self.assertEqual(result_array.shape, shape)

        left = result_array[:, :, : shape[2] // 2 - 2]
        right = result_array[:, :, shape[2] // 2 + 2 :]
        left_label = np.bincount(left.ravel()).argmax()
        right_label = np.bincount(right.ravel()).argmax()
        self.assertNotEqual(left_label, 0)
        self.assertNotEqual(right_label, 0)
        self.assertNotEqual(left_label, right_label)
        self.assertGreater(np.mean(left == left_label), 0.95)
        self.assertGreater(np.mean(right == right_label), 0.95)

        slicer.mrmlScene.RemoveNode(result_labelmap)

    def test_resume_feature(self):
        """
        Test the resume feature when the layout is changed during segmentation.
        """
        load_project(PROJECT_FILE)

        source_volume = slicer.util.getNode("Input_volume")
        self.assertIsNotNone(source_volume)

        widget = self._module_widget.interactive_segmenter_frame
        self.assertIsNotNone(widget)

        # Set the input node in the widget
        widget._inputSelector.setCurrentNode(source_volume)
        process_events()

        # Resume widget should be invisible initially
        self.assertFalse(widget._resumeSegFrame.visible)

        # Start the segmentation process
        widget._runButton.click()
        process_events()

        # Wait for the segmentation process to start
        waitCondition(lambda: widget._state and widget._state.is_running(), timeoutSec=60)

        # Resume widget should still be invisible
        self.assertFalse(widget._resumeSegFrame.visible)

        # Change the layout
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)
        process_events()

        # Resume widget should now be visible
        self.assertTrue(widget._resumeSegFrame.visible)

        # Click the resume button
        widget._resumeSegButton.click()
        process_events()

        # Check that the layout is restored
        self.assertEqual(slicer.app.layoutManager().layout, SIDE_BY_SIDE_DUMB_LAYOUT_ID)

        # Resume widget should be invisible again
        self.assertFalse(widget._resumeSegFrame.visible)

    def test_default_view_plane(self):
        """
        The default view plane is XY unless the volume is strongly anisotropic
        (largest dimension more than twice the smallest), in which case it is
        the axis-aligned plane with the largest area. Numpy shape (K, J, I)
        maps to image dimensions (I, J, K) via updateVolumeFromArray.
        """
        cases = [
            ((64, 64, 64), "XY"),  # isotropic
            ((20, 300, 400), "XY"),  # anisotropic, XY still the largest plane
            ((400, 300, 20), "YZ"),
            ((400, 20, 300), "XZ"),
        ]
        for shape, expected in cases:
            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
            slicer.util.updateVolumeFromArray(node, np.zeros(shape, dtype=np.uint8))
            self.assertEqual(
                InteractiveSegmenterFrame._defaultViewPlane(node),
                expected,
                f"wrong default plane for shape {shape}",
            )
            slicer.mrmlScene.RemoveNode(node)

    def test_view_plane_switching(self):
        """
        Switching the view plane through the combobox synchronously discards the
        accumulated preview (segments computed in another orientation are stale)
        and reorients both slice views; the preview then regenerates in the new
        plane. Changing the orientation through a slice view itself propagates
        back to the other view and the combobox.
        """
        shape = (48, 64, 80)  # (K, J, I)
        rng = np.random.default_rng(0)
        volume = np.where(np.arange(shape[2])[np.newaxis, np.newaxis, :] < shape[2] // 2, 50.0, 200.0)
        volume = (np.broadcast_to(volume, shape) + rng.normal(0, 10, shape)).astype(np.float32)

        source_volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Planes3D")
        slicer.util.updateVolumeFromArray(source_volume, volume)

        widget = self._module_widget.interactive_segmenter_frame
        widget._inputSelector.setCurrentNode(source_volume)
        process_events()

        widget._runButton.click()
        process_events()
        waitCondition(lambda: widget._state and widget._state.features_ready, timeoutSec=120)
        self.assertTrue(widget._state.features_ready)

        # Annotate one stroke on each half so a preview gets computed
        annotation_node = get_annotation_node(source_volume)
        strokes = np.zeros(shape, dtype=np.uint8)
        strokes[20:28, 28:36, 10:30] = 1
        strokes[20:28, 28:36, 50:70] = 2
        strokes_labelmap = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.util.updateVolumeFromArray(strokes_labelmap, strokes)
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(strokes_labelmap, annotation_node)
        slicer.mrmlScene.RemoveNode(strokes_labelmap)
        process_events()

        waitCondition(lambda: widget._applyButton.enabled, timeoutSec=120)

        # Wait for the first preview to arrive in the initial plane
        preview_segmentation = widget._state.result_segmentation_node.GetSegmentation()
        waitCondition(lambda: preview_segmentation.GetNumberOfSegments() > 0, timeoutSec=120)
        self.assertGreater(preview_segmentation.GetNumberOfSegments(), 0)

        initial = widget._viewPlaneComboBox.currentText
        self.assertEqual(widget._state.annotation_slice.orientation, initial)
        self.assertEqual(widget._state.preview_slice.orientation, initial)
        self.assertTrue(widget._viewPlaneComboBox.enabled)

        # Switching the plane wipes the preview synchronously and reorients both views
        target = "YZ" if initial != "YZ" else "XZ"
        widget._viewPlaneComboBox.setCurrentText(target)
        self.assertEqual(widget._state.annotation_slice.orientation, target)
        self.assertEqual(widget._state.preview_slice.orientation, target)
        self.assertEqual(widget._state.view_plane, target)
        self.assertEqual(preview_segmentation.GetNumberOfSegments(), 0)
        self.assertEqual(widget._state.calculated_extents, [])

        # The preview regenerates in the new plane: every covered extent must be
        # collapsed (width 1) along the new plane's normal axis. Extents are
        # (i_min, i_max, j_min, j_max, k_min, k_max), half-open on max.
        min_index, max_index = {"XY": (4, 5), "XZ": (2, 3), "YZ": (0, 1)}[target]

        def preview_regenerated_in_plane():
            extents_list = widget._state.calculated_extents
            if not extents_list:
                return False
            if not all(extents[max_index] - extents[min_index] == 1 for extents, _ in extents_list):
                return False
            return preview_segmentation.GetNumberOfSegments() > 0

        process_events()
        waitCondition(preview_regenerated_in_plane, timeoutSec=120)
        self.assertTrue(preview_regenerated_in_plane())

        # Changing the orientation through a slice view itself syncs back (via a
        # debounced NodeObserver) to the other view and the combobox
        widget._state.preview_slice.set_orientation(initial)
        process_events()
        waitCondition(
            lambda: (
                widget._viewPlaneComboBox.currentText == initial
                and widget._state.annotation_slice.orientation == initial
                and widget._state.view_plane == initial
            ),
            timeoutSec=30,
        )
        self.assertEqual(widget._viewPlaneComboBox.currentText, initial)
        self.assertEqual(widget._state.annotation_slice.orientation, initial)
        self.assertEqual(widget._state.view_plane, initial)

        # The preview view must display the same slice plane as the annotation
        # view: predictions cover the annotation view's one-voxel slab, so a
        # diverged preview offset renders nothing (the imported result lies on
        # a neighboring slice). Reorienting a view through its own selector
        # preserves each node's old translation and desyncs the offsets for
        # real; the module must snap them back together.
        state = widget._state
        spacing = max(state.source_volume_node.GetSpacing())
        state.preview_slice.set_offset(state.annotation_slice.offset + spacing)
        process_events()
        waitCondition(
            lambda: abs(state.preview_slice.offset - state.annotation_slice.offset) < 1e-6,
            timeoutSec=30,
        )
        self.assertLess(abs(state.preview_slice.offset - state.annotation_slice.offset), 1e-6)

        # The plane must also sit on a voxel CENTER: fit() centers the plane on
        # the volume, which for an even-dimension axis is a voxel BOUNDARY
        # (IJK X.5), and scrolling preserves the fractional part. A plane lying
        # exactly on the preview slab's edge renders the one-voxel-thick result
        # only on floating-point luck (about half the slice indices show
        # nothing). Push the plane onto a boundary and check the module snaps
        # it back.
        normal_axis = {"YZ": 0, "XZ": 1, "XY": 2}[state.view_plane]
        normal_spacing = state.source_volume_node.GetSpacing()[normal_axis]
        state.annotation_slice.set_offset(state.annotation_slice.offset + 0.5 * normal_spacing)
        process_events()

        def plane_on_voxel_center():
            coord = _plane_center_ijk(state.annotation_slice, state.source_volume_node)[normal_axis]
            return abs(coord - round(coord)) < 1e-3

        waitCondition(plane_on_voxel_center, timeoutSec=30)
        self.assertTrue(plane_on_voxel_center())

    # ------------------------------------------------------------------
    # Regression tests for crashes found by the standalone fuzzer
    # (tools/fuzz_interactive_segmenter.py), which drives the widget like a user until
    # a traceback appears. Each test below reproduces one such traceback and is
    # written RED (failing against the current code) so the fix can be verified.
    # ------------------------------------------------------------------

    def test_cleanup_before_layout_saved_does_not_crash(self):
        """
        RED: ``RealTimeSegLogic._cleanup`` restores the layout via
        ``self.previous_layout``, but that attribute is only set partway through
        ``start_segmentation`` (after the temp-dir reset and the source-volume
        lookup). If the start fails before that point -- e.g. the temp dir holds
        a file still locked by a previous consumer, or the segmentation has no
        source volume -- the widget's error path runs ``_stopSegmentation`` ->
        ``stop_segmentation`` -> ``_cleanup``, which raises ``AttributeError:
        'RealTimeSegLogic' object has no attribute 'previous_layout'`` and masks
        the original error.

        Expected after fix: cleanup leaves the layout alone when it never changed
        it, instead of raising.
        """
        from commons.interactive.widget import RealTimeSegLogic

        state = RealTimeSegLogic()
        try:
            state._cleanup()
        except AttributeError as exc:
            self.fail(f"_cleanup crashed before previous_layout was set: {exc}")

    def test_sessions_share_one_merge_segment_editor(self):
        """
        RED: every session used to build its own hidden ``qMRMLSegmentEditorWidget``
        just to run the "Logical operators" merge. Each one clones every registered
        segment editor effect -- ~0.3 s and ~8 MiB per Run -- and the clones outlive
        the widget, so orphaned effects keep observing the slice views. One of those
        orphans firing after a scene close is the ``'SegmentEditorEffect' object has
        no attribute 'previewedSegmentationDisplayNode'`` traceback the fuzzer hit.

        Expected after fix: the editor is built once per application run and every
        session reuses it, so counting the live effect objects across sessions shows
        no growth.
        """
        import gc

        from commons.interactive.widget import RealTimeSegLogic, shared_segment_editor

        def effect_objects():
            count = 0
            for obj in gc.get_objects():
                mro = getattr(type(obj), "__mro__", ())
                if any(getattr(cls, "__name__", "") == "AbstractScriptedSegmentEditorEffect" for cls in mro):
                    count += 1
            return count

        shared_segment_editor()  # first use pays for the clones; later sessions must not
        gc.collect()
        before = effect_objects()

        widgets = set()
        for _ in range(3):
            state = RealTimeSegLogic()
            widget, _ = shared_segment_editor()
            widgets.add(id(widget))
            state._cleanup()
        gc.collect()

        self.assertEqual(len(widgets), 1, "sessions built more than one merge segment editor")
        self.assertEqual(effect_objects(), before, "sessions leaked segment editor effect clones")

    def test_update_loop_tolerates_locked_result_file(self):
        """
        RED: ``update_loop`` clears the stale preview with a bare
        ``self.paths.result.unlink()`` whenever a new inference is pending. On
        Windows the consumer subprocess may still hold ``result.npz`` open while
        it rewrites it, so the unlink raises ``PermissionError: [WinError 32]``.
        The call runs inside a QTimer slot, so PythonQt swallows the traceback
        and the preview silently stalls. (``ipc.safe_replace`` already retries
        on this exact error; the delete does not.)

        A held file handle here stands in for the consumer's lock. Expected after
        fix: the delete tolerates the lock (skipped this cycle, retried next tick)
        instead of raising.
        """
        import shutil

        from commons.interactive.widget import RealTimeSegLogic

        class _FakeProcess:
            returncode = None

            def poll(self):
                return None

        state = RealTimeSegLogic()
        state.consumer_process = _FakeProcess()
        state.features_ready = True
        state.pending_inference = True
        state.pending_training = False
        # Isolate the delete: stop update_loop before it requests new work, which
        # would otherwise need a full live session (source volume, slice view).
        state.check_and_update_inputs = lambda: None

        state.paths.base_dir.mkdir(parents=True, exist_ok=True)
        np.savez(str(state.paths.result), result=np.zeros((1, 4, 4), dtype=np.uint8))
        handle = open(str(state.paths.result), "rb")
        try:
            try:
                state.update_loop()
            except PermissionError as exc:
                self.fail(f"update_loop did not tolerate a locked result file: {exc}")
        finally:
            handle.close()
            shutil.rmtree(state.paths.base_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Consumer-level tests
    #
    # These exercise consumer's task handlers and helpers directly, in
    # process, without launching the subprocess or the side-by-side GUI. The
    # subprocess swallows tracebacks into its stdout, so a crash in the task
    # handlers is invisible to the end-to-end widget tests above; calling the
    # handlers here surfaces those failures and runs in milliseconds, which makes
    # them useful guard rails for the upcoming bug fixes and refactor.
    # ------------------------------------------------------------------

    @staticmethod
    def _consumer_paths():
        """A fresh InterprocessPaths rooted at a throwaway temp directory."""
        return InterprocessPaths(Path(tempfile.mkdtemp(prefix="interactive_seg_test_")))

    @staticmethod
    def _two_region_2d(height=64, width=64):
        """A 2D source (1, H, W) split into two flat-valued halves."""
        image = np.zeros((1, height, width), dtype=np.uint8)
        image[0, :, : width // 2] = 50
        image[0, :, width // 2 :] = 200
        return image

    @staticmethod
    def _annotation_2d(height=64, width=64):
        """Annotation array (label, i, j, k) painting class 1 on the left half
        and class 2 on the right half, in the format the consumer expects."""
        points = [(1, x, height // 2, 0) for x in range(5, 25)]
        points += [(2, x, height // 2, 0) for x in range(width - 24, width - 4)]
        return np.array(points, dtype=np.int64).T

    @staticmethod
    def _is_trained(paths):
        return json.loads(paths.model_status.read_text())["is_trained"]

    def test_2d_write_empty_does_not_crash(self):
        """
        RED (reproduces a bug): the widget sends a ``write_empty`` task with no
        ``features`` key whenever the annotation has fewer than 10 voxels or only
        one class -- i.e. right after the first stroke of every 2D session.
        ``_handle_task_2d`` sorts ``task_params.get("features")`` (which is None)
        BEFORE the ``write_empty`` branch, so it raises
        ``TypeError: 'NoneType' object is not iterable``. The 3D handler already
        handles this correctly (see test_3d_write_empty_resets_model).

        Expected behavior once fixed: the task resets the session, writes an empty
        result and reports the model as untrained.
        """
        paths = self._consumer_paths()
        state = lazy_2d.Lazy2DState(self._two_region_2d(), paths)
        # Pretend a model had already been trained, so we can assert it is reset.
        state.annotation = np.zeros((4, 5), dtype=np.int64)
        state.models[(0,)] = "stale-model"

        lazy_2d.handle_task_2d({"action": "write_empty"}, paths, state)

        self.assertIsNone(state.annotation)
        self.assertEqual(state.models, {})
        with np.load(paths.result) as result:
            self.assertEqual(result["result"].size, 0)
        self.assertFalse(self._is_trained(paths))

    def test_3d_write_empty_resets_model(self):
        """
        GREEN counterpart to test_2d_write_empty_does_not_crash: the 3D handler
        tolerates a ``write_empty`` task with no features, writes a zeroed result
        of the original shape and reports the model as untrained. This pins the
        behavior the 2D handler should match.
        """
        paths = self._consumer_paths()
        shape = (2, 4, 4)
        model = volume_3d.handle_task(
            {"action": "write_empty"},
            paths,
            model=None,
            features=None,
            original_shape=shape,
            scale=features.FeatureScale.from_multiplier(1),
        )
        self.assertIsNone(model)
        with np.load(paths.result) as result:
            self.assertEqual(result["result"].shape, shape)
            self.assertEqual(int(result["result"].sum()), 0)
        self.assertFalse(self._is_trained(paths))

    def test_2d_lazy_train_and_predict(self):
        """
        Drive the 2D lazy pipeline (train then a cached predict) through the task
        handler without the subprocess, asserting a full-size labelmap is produced
        and the model is reported as trained. Covers the core consumer path the
        refactor will touch.
        """
        paths = self._consumer_paths()
        height, width = 64, 64
        state = lazy_2d.Lazy2DState(self._two_region_2d(height, width), paths)
        state.build_pyramid()
        safe_save_numpy(self._annotation_2d(height, width), paths.annotation)
        features = [FeatureIndex.SOURCE.value, FeatureIndex.GAUSSIAN_A.value, FeatureIndex.WINVAR_A.value]
        extents = [0, width, 0, height, 0, 1]

        lazy_2d.handle_task_2d({"action": "train", "extents": extents, "features": features}, paths, state)

        with np.load(paths.result) as result:
            self.assertEqual(result["result"].shape, (1, height, width))
        self.assertTrue(self._is_trained(paths))

        # A subsequent predict reuses the cached model and produces a result too.
        paths.result.unlink()
        lazy_2d.handle_task_2d({"action": "predict", "extents": extents, "features": features}, paths, state)
        with np.load(paths.result) as result:
            self.assertEqual(result["result"].shape, (1, height, width))

    def test_compute_preview_factor(self):
        """The preview downscale factor is a power of two that brings the visible
        region within the preview pixel budget (both processes rely on this)."""
        self.assertEqual(compute_preview_factor([0, 100, 0, 100, 0, 1]), 1)
        factor = compute_preview_factor([0, 4000, 0, 4000, 0, 1])
        self.assertGreaterEqual(factor, 2)
        self.assertEqual(factor & (factor - 1), 0, "factor must be a power of two")
        self.assertLessEqual((4000 * 4000) // (factor * factor), PREVIEW_MAX_PIXELS)

    def test_feature_scale(self):
        """FeatureScale scales the kernels linearly and the displayed names track
        the scaled sizes; scale 1 reproduces the base sizes. Two scales coexist as
        independent value objects (no shared module state to reset)."""
        scale1 = features.FeatureScale.from_multiplier(1)
        self.assertEqual(scale1.gaussian_sigmas[FeatureIndex.GAUSSIAN_A], 1)
        self.assertEqual(scale1.winvar_sizes[FeatureIndex.WINVAR_A], 5)

        scale2 = features.FeatureScale.from_multiplier(2)
        self.assertEqual(scale2.gaussian_sigmas[FeatureIndex.GAUSSIAN_A], 2)
        self.assertIn("sigma=2", features.feature_display_name(FeatureIndex.GAUSSIAN_A, 2))
        self.assertEqual(features.feature_display_name(FeatureIndex.SOURCE, 4), "Raw Image")

    def test_compute_features_2d_plane_counts(self):
        """Multi-channel inputs yield one plane per (feature, channel), laid out
        feature-major / channel-minor, and SOURCE planes pass the input through."""
        scale = features.FeatureScale.from_multiplier(1)
        rgb = np.zeros((20, 20, 3), dtype=np.float32)
        rgb[..., 0], rgb[..., 1], rgb[..., 2] = 10, 20, 30
        feature_indices = [FeatureIndex.SOURCE.value, FeatureIndex.GAUSSIAN_A.value]

        planes = features_2d.compute_features_2d(rgb, feature_indices, scale)

        self.assertEqual(planes.shape, (len(feature_indices) * 3, 20, 20))
        self.assertTrue(np.allclose(planes[0], 10))
        self.assertTrue(np.allclose(planes[1], 20))
        self.assertTrue(np.allclose(planes[2], 30))

    def test_large_3d_image_predicate(self):
        """The crop suggestion triggers on big 3D volumes only, and keeps
        triggering past 2**31 voxels -- ``np.prod`` overflows numpy's 32-bit
        default integer on Windows and made the check silently pass (as a
        negative product) for exactly the volumes that need it most."""
        self.assertFalse(is_large_3d_image((700, 700, 700)))
        self.assertTrue(is_large_3d_image((701, 700, 700)))
        self.assertFalse(is_large_3d_image((20000, 20000, 1)), "2D images are never too large")

        huge = (1600, 1600, 3000)
        self.assertGreater(np.prod(huge, dtype=np.int64), 2**31, "test case must overflow int32")
        self.assertTrue(is_large_3d_image(huge))

        self.assertEqual(LARGE_IMAGE_VOXEL_LIMIT, 700**3)

    def test_suggest_multiplier(self):
        """The auto feature-scale estimator returns a supported multiplier: 1 for
        fine white-noise texture, and 1 (not a crash) for a zero-variance image."""
        from commons.interactive.scale_estimate import suggest_multiplier, SUPPORTED_MULTIPLIERS

        rng = np.random.default_rng(0)
        fine = rng.integers(0, 256, (600, 600)).astype(np.uint8)
        multiplier = suggest_multiplier(fine)
        self.assertIn(multiplier, SUPPORTED_MULTIPLIERS)
        self.assertEqual(multiplier, 1)

        flat = np.full((600, 600), 100, dtype=np.uint8)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)  # all-NaN spectrum
            self.assertEqual(suggest_multiplier(flat), 1)

    def test_destroyed_frame_stops_observing_the_scene(self):
        """
        RED: the scene close observer is dropped only in ``cleanup()``, and the scene
        keeps a reference to the bound method, so a frame destroyed without it goes on
        reacting to scene closes: ``AttributeError: Trying to set property 'text' on a
        destroyed QPushButton object``. The framework's excepthook then fails whichever
        test happens to be running when the next project is loaded.
        """
        frame = InteractiveSegmenterFrame()
        process_events()
        frame.delete()
        process_events()

        close_project()

    def test_long_input_name_does_not_squeeze_form_label(self):
        """Selecting a long-named node must not raise the input section's minimum
        width, which would leave no room for the "Image 1:" label in the module panel."""
        widget = self._module_widget.interactive_segmenter_frame
        inputLayout = widget._inputSection.layout()
        minimumWidth = inputLayout.minimumSize().width()

        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "n" * 120)
        widget._inputSelector.setCurrentNode(volume)
        process_events()
        # Re-entering the module re-polishes the selector, dropping its cached size hints.
        qt.QApplication.sendEvent(widget._inputSelector.selectorWidget, qt.QEvent(qt.QEvent.StyleChange))
        inputLayout.activate()
        process_events()

        self.assertEqual(inputLayout.minimumSize().width(), minimumWidth)

    def test_cropped_volume_gets_its_own_annotation(self):
        """A cropped volume must get its own annotation instead of inheriting the one
        belonging to the volume it was cropped from."""
        widget = self._module_widget.interactive_segmenter_frame

        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "CropSource")
        slicer.util.updateVolumeFromArray(volume, np.zeros((40, 40, 40), dtype=np.uint8))

        widget._inputSelector.setCurrentNode(volume)
        process_events()
        widget._runButton.click()
        process_events()
        original_annotation = widget._state.annotation_node
        widget._stopSegmentation()
        process_events()

        CustomizedCropVolumeLogic().crop(volume, (20, 20, 20))
        cropped = slicer.util.getFirstNodeByName("CropSource - Cropped", "vtkMRMLScalarVolumeNode")
        self.assertIsNotNone(cropped)
        self.assertIsNone(get_annotation_node(cropped))

        widget._inputSelector.setCurrentNode(cropped)
        process_events()
        widget._runButton.click()
        process_events()
        self.assertIsNot(widget._state.annotation_node, original_annotation)
        self.assertIs(helpers.getSourceVolume(widget._state.annotation_node), cropped)

    def tear_down(self):
        widget: InteractiveSegmenterFrame = self._module_widget.interactive_segmenter_frame
        if widget and widget._state and widget._state.is_running():
            widget._stopSegmentation()
        super().tear_down()
