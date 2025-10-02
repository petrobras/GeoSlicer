import ctk
import os
import qt
import slicer
import logging
import subprocess
import shutil
import vtk
import time
import json
import sys
import psutil
import traceback

from vtk.util.numpy_support import vtk_to_numpy
from pathlib import Path
from dataclasses import dataclass, field

from ltrace.interactive import seg_consumer
from ltrace.interactive.seg_ipc import (
    InterprocessPaths,
    safe_save_numpy,
    FeatureIndex,
    FEATURE_NAMES,
    safe_dump_json,
)
from ltrace.interactive.slice_view_util import Slice, get_volume_extents_in_slice_view

from ltrace.slicer import ui
import numpy as np

from ltrace.slicer import helpers
from ltrace.slicer.node_observer import NodeObserver
from ltrace.constants import SIDE_BY_SIDE_DUMB_LAYOUT_ID

from ltrace.flow.util import (
    createSimplifiedSegmentEditor,
    onSegmentEditorEnter,
    onSegmentEditorExit,
)

ANNOTATION_SLICE = "SideBySideDumb1"
PREVIEW_SLICE = "SideBySideDumb2"


def _copy_segment_names_and_colors(source_segmentation, target_segmentation):
    """
    Copy segment names and colors from source_segmentation to target_segmentation.
    """
    source = source_segmentation.GetSegmentation()
    target = target_segmentation.GetSegmentation()

    source_ids = source.GetSegmentIDs()
    target_ids = target.GetSegmentIDs()

    n = min(len(source_ids), len(target_ids))

    for source_id in source_ids[:n]:
        source_segment = source.GetSegment(source_id)
        label_value = source_segment.GetLabelValue()
        for target_id in target_ids:
            target_segment = target.GetSegment(target_id)
            if target_segment.GetLabelValue() == label_value:
                logging.debug(
                    f"Segment {source_segment.GetName()} matches {target_segment.GetName()}; copying properties."
                )
                break
        else:
            continue

        target_segment.SetName(source_segment.GetName())
        target_segment.SetColor(source_segment.GetColor())


def _kill_process_and_children(proc: subprocess.Popen, timeout=5):
    try:
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)

        parent.terminate()
        for child in children:
            child.terminate()

        gone, alive = psutil.wait_procs([parent] + children, timeout=timeout)
        if alive:
            for p in alive:
                p.kill()
            psutil.wait_procs(alive, timeout=timeout)
    except psutil.NoSuchProcess:
        pass


def _get_annotated_voxel_values_from_array(segmentationNode):
    referenceVolumeNode = helpers.getSourceVolume(segmentationNode)

    # Get transform from reference volume IJK to RAS
    scalarIJKToRAS_vtk = vtk.vtkMatrix4x4()
    referenceVolumeNode.GetIJKToRASMatrix(scalarIJKToRAS_vtk)

    # Get transform from RAS to reference volume IJK
    scalarRASToIJK_vtk = vtk.vtkMatrix4x4()
    scalarRASToIJK_vtk.DeepCopy(scalarIJKToRAS_vtk)
    scalarRASToIJK_vtk.Invert()

    # Convert VTK matrix to numpy array
    scalarRASToIJK_np = np.zeros((4, 4))
    for r in range(4):
        for c in range(4):
            scalarRASToIJK_np[r, c] = scalarRASToIJK_vtk.GetElement(r, c)

    segmentation = segmentationNode.GetSegmentation()
    all_label_values = []
    all_ijk_coordinates = []

    segmentIDs = vtk.vtkStringArray()
    segmentation.GetSegmentIDs(segmentIDs)

    for i in range(segmentIDs.GetNumberOfValues()):
        segmentID = segmentIDs.GetValue(i)
        segment = segmentation.GetSegment(segmentID)

        binaryLabelmap = segment.GetRepresentation(
            slicer.vtkSegmentationConverter.GetBinaryLabelmapRepresentationName()
        )
        if not binaryLabelmap:
            continue

        # Get segment's labelmap as numpy array
        dims = binaryLabelmap.GetDimensions()
        shape = tuple(reversed(dims))
        vtk_scalars = binaryLabelmap.GetPointData().GetScalars()
        if vtk_scalars is not None:
            labelmapArray = vtk_to_numpy(vtk_scalars).reshape(shape)
        else:
            continue

        mask = labelmapArray > 0
        if not np.any(mask):
            continue

        # Get the segment's extent to find the coordinate offset
        extent = binaryLabelmap.GetExtent()
        i_min, j_min, k_min = extent[0], extent[2], extent[4]

        # Get voxel coordinates in the segment's LOCAL (NumPy) IJK space
        k_indices, j_indices, i_indices = np.where(mask)

        # Convert LOCAL indices to the segment's ABSOLUTE IJK coordinates by adding the offset
        i_indices_abs = i_indices + i_min
        j_indices_abs = j_indices + j_min
        k_indices_abs = k_indices + k_min

        # Get transform from segment's ABSOLUTE IJK to RAS
        segmentIJKToRAS_vtk = vtk.vtkMatrix4x4()
        binaryLabelmap.GetImageToWorldMatrix(segmentIJKToRAS_vtk)

        # Convert VTK matrix to numpy array
        segmentIJKToRAS_np = np.zeros((4, 4))
        for r in range(4):
            for c in range(4):
                segmentIJKToRAS_np[r, c] = segmentIJKToRAS_vtk.GetElement(r, c)

        # Create homogeneous coordinates for the segment's voxels using the CORRECTED absolute coordinates
        points_in_segment_ijk = np.vstack([i_indices_abs, j_indices_abs, k_indices_abs, np.ones(len(i_indices_abs))])

        # Transform points: Segment IJK -> RAS -> Reference Volume IJK
        points_in_ras = segmentIJKToRAS_np @ points_in_segment_ijk
        points_in_scalar_ijk_homogeneous = scalarRASToIJK_np @ points_in_ras

        # Convert back from homogeneous, transpose, and store
        final_points = np.round(points_in_scalar_ijk_homogeneous[:3, :].T).astype(np.uint32)

        all_label_values.append(labelmapArray[mask])
        all_ijk_coordinates.append(final_points)

    if not all_label_values:
        return np.empty((4, 0), dtype=np.uint32)

    final_labels = np.concatenate(all_label_values)
    final_ijk = np.concatenate(all_ijk_coordinates)

    # Stack labels with IJK coordinates (Label, I, J, K)
    return np.vstack((final_labels, final_ijk[:, 0], final_ijk[:, 1], final_ijk[:, 2]))


@dataclass
class RealTimeSegLogic:
    paths: InterprocessPaths = field(init=False)
    consumer_process: subprocess.Popen = None
    annotation_node: "vtkMRMLSegmentationNode" = None
    source_volume_node: "vtkMRMLScalarVolumeNode" = None
    inference_volume_node: "vtkMRMLScalarVolumeNode" = None
    result_segmentation_node: "vtkMRMLSegmentationNode" = None
    segmentation_obs: NodeObserver = None
    annotation_slice: Slice = None
    tmp_labelmap_node: "vtkMRMLLabelMapVolumeNode" = None
    annotation_slice_obs: NodeObserver = None
    last_annotation_write_time: float = 0
    last_result_read_time: float = 0
    main_loop_timer: qt.QTimer = None
    feature_indices: list = field(init=False)
    pending_training: bool = True
    pending_inference: bool = True
    applying_full_image: bool = False
    on_full_segmentation_complete_callback: callable = None
    on_process_crashed_callback: callable = None
    on_progress_callback: callable = None
    on_model_trained_callback: callable = None
    features_ready: bool = False
    progress_timer: qt.QTimer = None

    def __post_init__(self):
        temp_dir = Path(slicer.app.temporaryPath) / "InteractiveSegmenter"
        self.paths = InterprocessPaths(temp_dir)
        self.calculated_extents = []

        self.segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
        self.segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
        self.segmentEditorNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentEditorNode")
        self.segmentEditorWidget.setMRMLSegmentEditorNode(self.segmentEditorNode)

    def set_timers(self, main_loop, progress):
        self.main_loop_timer = main_loop
        self.progress_timer = progress

    def set_feature_preset(self, feature_preset_name):
        FI = FeatureIndex
        if feature_preset_name == "Sharp":
            fi = [FI.SOURCE, FI.GAUSSIAN_A, FI.GAUSSIAN_B, FI.WINVAR_A]
        elif feature_preset_name == "Balanced":
            fi = [FI.SOURCE, FI.GAUSSIAN_A, FI.GAUSSIAN_B, FI.GAUSSIAN_C, FI.WINVAR_A, FI.WINVAR_B]
        elif feature_preset_name == "Smooth":
            fi = [FI.GAUSSIAN_A, FI.GAUSSIAN_B, FI.GAUSSIAN_C, FI.GAUSSIAN_D, FI.WINVAR_A, FI.WINVAR_B]
        elif feature_preset_name == "Extra Smooth":
            fi = [FI.GAUSSIAN_B, FI.GAUSSIAN_C, FI.GAUSSIAN_D, FI.WINVAR_A, FI.WINVAR_B]
        elif feature_preset_name == "Complete":
            fi = [FI(i) for i in range(len(FI))]
        else:
            raise ValueError(f"Unknown feature set: {feature_preset_name}")

        self.feature_indices = [i.value for i in fi]
        self._on_input_modified()
        logging.debug(f"Feature set set to: {self.feature_indices}")

    def _setup_segmentation_display(self, segmentation_node, view_node_id):
        """Configures a segmentation node to be visible only in a specific view."""
        if not segmentation_node.GetDisplayNode():
            segmentation_node.CreateDefaultDisplayNodes()

        default_display_node = segmentation_node.GetDisplayNode()
        if default_display_node:
            default_display_node.SetVisibility(False)

        custom_display_node = segmentation_node.GetNthDisplayNode(1)
        if not custom_display_node:
            custom_display_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationDisplayNode")
            segmentation_node.AddAndObserveDisplayNodeID(custom_display_node.GetID())

        custom_display_node.SetDisplayableOnlyInView(view_node_id)
        custom_display_node.SetVisibility(True)

    def is_running(self):
        return self.consumer_process is not None and self.consumer_process.poll() is None

    def start_segmentation(self, segmentation_node):
        if self.is_running():
            logging.warning("Process is already running.")
            return

        self.features_ready = False
        if self.paths.base_dir.exists():
            shutil.rmtree(self.paths.base_dir)
        self.paths.base_dir.mkdir(parents=True)
        python_slicer_executable = shutil.which("PythonSlicer")

        self.annotation_node = segmentation_node
        self.source_volume_node = helpers.getSourceVolume(self.annotation_node)

        if not self.source_volume_node:
            raise ValueError("Could not find the source volume for the selected segmentation node.")

        layout_manager = slicer.app.layoutManager()
        self.previous_layout = layout_manager.layout
        layout_manager.setLayout(SIDE_BY_SIDE_DUMB_LAYOUT_ID)

        self.annotation_slice = Slice(ANNOTATION_SLICE)
        self.preview_slice = Slice(PREVIEW_SLICE)

        self.annotation_slice.set_bg(self.source_volume_node)
        self.annotation_slice.fit()
        self.preview_slice.set_bg(self.source_volume_node)
        self.preview_slice.fit()

        self.preview_slice.link()
        self.annotation_slice.link()

        for display_node in slicer.util.getNodesByClass("vtkMRMLSegmentationDisplayNode"):
            display_node.SetVisibility(False)

        self._setup_segmentation_display(segmentation_node, self.annotation_slice.node.GetID())

        source_array = slicer.util.arrayFromVolume(self.source_volume_node)
        safe_save_numpy(source_array, self.paths.source)
        logging.debug(f"Source image saved to {self.paths.source}")

        si = None
        if sys.platform.startswith("win32"):
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE

        command = [
            str(python_slicer_executable),
            seg_consumer.__file__,
            "--data-dir",
            self.paths.base_dir.resolve().as_posix(),
        ]

        logging.debug(f"Starting consumer process with command: {' '.join(command)}")
        self.consumer_process = subprocess.Popen(command, startupinfo=si)
        logging.debug(f"Consumer process started with PID: {self.consumer_process.pid}")

        self._setup_result_node()
        self.last_annotation_write_time = 0
        self.last_result_read_time = 0

        self.progress_timer.setInterval(100)
        self.progress_timer.timeout.connect(self._check_progress)
        self.progress_timer.start()

    def _check_progress(self):
        if not self.paths.progress.exists():
            return

        with open(self.paths.progress, "r") as f:
            progress_data = json.load(f)

        self.paths.progress.unlink()

        if self.on_progress_callback:
            self.on_progress_callback(progress_data["progress"], progress_data["message"])

        if progress_data["progress"] >= 100:
            self.progress_timer.stop()
            logging.debug("Task complete.")

            if self.applying_full_image:
                self.check_and_update_result()
            else:
                self.features_ready = True
                if self.on_progress_callback:
                    self.on_progress_callback(100, "Features ready.")
                self._start_main_loop()

    def _start_main_loop(self):
        self.segmentation_obs = NodeObserver(self.annotation_node)
        self.segmentation_obs.modifiedSignal.connect(self._on_segmentation_modified)

        self.annotation_slice_obs = NodeObserver(self.annotation_slice.node)
        self.annotation_slice_obs.modifiedSignal.connect(self._on_view_modified)

        self._on_segmentation_modified()
        logging.debug("NodeObserver for segmentation node started.")

        self.main_loop_timer.setInterval(50)
        self.main_loop_timer.timeout.connect(self.update_loop)
        self.main_loop_timer.start()

    def stop_segmentation(self):
        self.progress_timer.stop()
        self.main_loop_timer.stop()
        try:
            self.progress_timer.timeout.disconnect()
        except (TypeError, RuntimeError):
            logging.error("Failed to disconnect progress timer; it may not have been connected.")
        try:
            self.main_loop_timer.timeout.disconnect()
        except (TypeError, RuntimeError):
            logging.error("Failed to disconnect main loop timer; it may not have been connected.")

        if self.is_running():
            safe_dump_json({"action": "stop"}, self.paths.task)
            _kill_process_and_children(self.consumer_process)
        self.consumer_process = None

        self._cleanup()
        logging.debug("Real-time segmentation stopped and cleaned up.")

    def _on_view_modified(self, *args, **kwargs):
        if not self.annotation_node:
            logging.warning("Segmentation node is None in _on_view_modified; skipping update.")
            return
        self.pending_inference = True

    def _request_inference(self):
        extents = get_volume_extents_in_slice_view(self.source_volume_node, self.annotation_slice)
        if not extents:
            return
        for existing_extent in self.calculated_extents:
            if (
                existing_extent[0] <= extents[0]
                and existing_extent[1] >= extents[1]
                and existing_extent[2] <= extents[2]
                and existing_extent[3] >= extents[3]
                and existing_extent[4] <= extents[4]
                and existing_extent[5] >= extents[5]
            ):
                logging.debug("View has not changed significantly; skipping inference.")
                return

        if self.paths.task.exists():
            return

        task_params = {
            "action": "predict",
            "extents": extents,
            "features": self.feature_indices,
        }
        safe_dump_json(task_params, self.paths.task)

    def _on_segmentation_modified(self, *args, **kwargs):
        self._on_input_modified()

    def _on_input_modified(self):
        if self.result_segmentation_node:
            self.result_segmentation_node.GetSegmentation().RemoveAllSegments()
        self.pending_training = True
        self.pending_inference = True
        self.calculated_extents.clear()

    def _request_training_and_inference(self):
        try:
            start_time = time.perf_counter()
            # annotated_voxels is an array of shape (4, N), where N is the number of annotated voxels.
            # The first row contains the label values, and the next three rows contain the I, J, K coordinates.
            annotated_voxels = _get_annotated_voxel_values_from_array(self.annotation_node)
            end_time = time.perf_counter()
            logging.debug(f"Annotation extraction took: {end_time - start_time:.4f} seconds")

            labels = annotated_voxels[0, :]
            if annotated_voxels.shape[1] < 10 or len(np.unique(labels)) < 2:
                safe_dump_json({"action": "write_empty"}, self.paths.task)
                return

            safe_save_numpy(annotated_voxels, self.paths.annotation)

            extents = get_volume_extents_in_slice_view(self.source_volume_node, self.annotation_slice)
            safe_dump_json({"action": "train", "extents": extents, "features": self.feature_indices}, self.paths.task)

            logging.debug("Annotation file updated after segmentation modification.")
        except Exception as e:
            logging.error(f"Failed to get/save annotation labelmap: {e}")
            raise e

    def update_loop(self):
        if not self.is_running() and not self.applying_full_image:
            if self.on_process_crashed_callback:
                self.on_process_crashed_callback()
            return

        if self.applying_full_image:
            self._check_progress()
            self.check_and_update_result()
            return

        if not self.features_ready:
            return

        if self.paths.model_status.exists():
            with open(self.paths.model_status, "r") as f:
                model_status = json.load(f)
            if self.on_model_trained_callback:
                self.on_model_trained_callback(model_status.get("is_trained", False))

        if self.pending_inference:
            if self.paths.result.exists():
                self.paths.result.unlink()
        else:
            self.check_and_update_result()
        self.check_and_update_inputs()

    def check_and_update_inputs(self):
        if self.pending_training:
            self._request_training_and_inference()
            self.pending_training = False
            self.pending_inference = False
        elif self.pending_inference:
            self._request_inference()
            self.pending_inference = False

    def check_and_update_result(self):
        if not self.paths.result.exists():
            return

        try:
            mtime = self.paths.result.stat().st_mtime
            if mtime <= self.last_result_read_time:
                return

            result_arrays = np.load(self.paths.result)
            result_array = result_arrays.get("result", None)

            if self.result_segmentation_node:
                if result_array.size > 0:
                    extents = result_arrays.get("extents", None)
                    i_min, _, j_min, _, k_min, _ = extents

                    ijkToRas = vtk.vtkMatrix4x4()
                    source_for_geometry = self.source_volume_node
                    if self.applying_full_image and self.inference_volume_node:
                        source_for_geometry = self.inference_volume_node
                    source_for_geometry.GetIJKToRASMatrix(ijkToRas)

                    origin_ijk = [i_min, j_min, k_min, 1]
                    origin_ras = ijkToRas.MultiplyPoint(origin_ijk)

                    self.tmp_labelmap_node.SetOrigin(origin_ras[:3])
                    slicer.util.updateVolumeFromArray(self.tmp_labelmap_node, result_array)

                    n_existing_segments = self.result_segmentation_node.GetSegmentation().GetNumberOfSegments()
                    slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                        self.tmp_labelmap_node, self.result_segmentation_node
                    )
                    n_total_segments = self.result_segmentation_node.GetSegmentation().GetNumberOfSegments()

                    segmentation = self.result_segmentation_node.GetSegmentation()
                    to_remove = []
                    for i in range(n_existing_segments):
                        j = i + n_existing_segments
                        if j > n_total_segments - 1:
                            break

                        segment_a = segmentation.GetNthSegmentID(i)
                        segment_b = segmentation.GetNthSegmentID(j)
                        self.add_segment_to_segment(self.result_segmentation_node, segment_a, segment_b)
                        to_remove.append(segment_b)
                    for segment_id in to_remove:
                        segmentation.RemoveSegment(segment_id)

                    self.calculated_extents.append(extents)
                    _copy_segment_names_and_colors(self.annotation_node, self.result_segmentation_node)

            self.last_result_read_time = mtime

            if self.applying_full_image:
                if self.main_loop_timer:
                    self.main_loop_timer.stop()
                if self.on_full_segmentation_complete_callback:
                    self.on_full_segmentation_complete_callback(self.result_segmentation_node)
                return

        except Exception as e:
            logging.error(f"Failed to load or update result node: {e}")
            traceback.print_exc()

    def _setup_result_node(self):
        self.result_segmentation_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLSegmentationNode", "SegmentationResult"
        )
        self._setup_segmentation_display(self.result_segmentation_node, self.preview_slice.node.GetID())

        helpers.setSourceVolume(self.result_segmentation_node, self.source_volume_node)
        self.tmp_labelmap_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "TemporaryResult")

        colors = [
            (1.0, 0.0, 0.0),  # Red
            (0.0, 1.0, 1.0),  # Cyan
            (0.0, 0.0, 1.0),  # Blue
            (1.0, 1.0, 0.0),  # Yellow
        ]
        color_table = helpers.create_color_table("Preview_Color_Table", colors, add_background=True)
        self.tmp_labelmap_node.CreateDefaultDisplayNodes()
        self.tmp_labelmap_node.GetDisplayNode().SetAndObserveColorNodeID(color_table.GetID())
        self.tmp_labelmap_node.CopyOrientation(self.source_volume_node)

        logging.debug(f"Created/updated result node: {self.result_segmentation_node.GetName()}")

    def _cleanup(self):
        if self.tmp_labelmap_node and slicer.mrmlScene.IsNodePresent(self.tmp_labelmap_node):
            slicer.mrmlScene.RemoveNode(self.tmp_labelmap_node)
            self.tmp_labelmap_node = None

        if self.segmentEditorNode and slicer.mrmlScene.IsNodePresent(self.segmentEditorNode):
            slicer.mrmlScene.RemoveNode(self.segmentEditorNode)
            self.segmentEditorNode = None

        if self.segmentEditorWidget:
            self.segmentEditorWidget.setMRMLScene(None)
            self.segmentEditorWidget = None

        if self.segmentation_obs:
            self.segmentation_obs.clear()
        if self.annotation_slice_obs:
            self.annotation_slice_obs.clear()

        shutil.rmtree(self.paths.base_dir, ignore_errors=True)
        slicer.app.layoutManager().setLayout(self.previous_layout)

    def add_segment_to_segment(self, seg_node, segment_a, segment_b):
        modifierSegmentID = segment_b
        selectedSegmentID = segment_a
        self.segmentEditorWidget.setSegmentationNode(seg_node)
        self.segmentEditorNode.SetOverwriteMode(slicer.vtkMRMLSegmentEditorNode.OverwriteNone)
        self.segmentEditorNode.SetMaskMode(slicer.vtkMRMLSegmentationNode.EditAllowedEverywhere)
        self.segmentEditorNode.SetSelectedSegmentID(selectedSegmentID)
        self.segmentEditorWidget.setActiveEffectByName("Logical operators")
        effect = self.segmentEditorWidget.activeEffect()
        effect.setParameter("BypassMasking", "1")
        effect.setParameter("ModifierSegmentID", modifierSegmentID)
        effect.setParameter("Operation", "UNION")
        effect.self().onApply()


class InteractiveSegmenterFrame(qt.QFrame):
    START_TEXT = "Start Annotation"
    START_TIP = "Start annotating with a real-time preview of the result."
    STOP_TEXT = "Cancel"
    STOP_TIP = (
        "Stop the real-time segmentation preview. Your annotation will remain in project and you can resume later."
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = None

        layout = qt.QVBoxLayout(self)

        self._inputSection = ctk.ctkCollapsibleButton()
        self._inputSection.collapsed = False
        self._inputSection.text = "Input"
        layout.addWidget(self._inputSection)
        inputLayout = qt.QFormLayout(self._inputSection)

        self._inputSelector = ui.hierarchyVolumeInput(
            onChange=self._onInputNodeChanged,
            hasNone=True,
            nodeTypes=["vtkMRMLScalarVolumeNode"],
        )
        self._inputSelector.setMRMLScene(slicer.mrmlScene)
        self._inputSelector.setToolTip("Select the volume to segment.")
        inputLayout.addRow("Input Image:", self._inputSelector)

        self._runButton = qt.QPushButton()
        self._runButton.setFixedHeight(40)
        self._runButton.objectName = "Run Button"
        inputLayout.addRow(" ", None)
        inputLayout.addRow(self._runButton)
        inputLayout.addRow(" ", None)

        self._annotationSection = ctk.ctkCollapsibleButton()
        self._annotationSection.visible = False
        self._annotationSection.text = "Annotation"
        layout.addWidget(self._annotationSection)
        annotationLayout = qt.QFormLayout(self._annotationSection)

        self._featurePresetComboBox = qt.QComboBox()
        self._featurePresetComboBox.addItems(["Sharp", "Balanced", "Smooth", "Extra Smooth", "Complete"])
        self._featurePresetComboBox.setCurrentText("Balanced")
        self._featurePresetComboBox.setToolTip(
            "Change the smoothness of the result by selecting which filters to apply before training."
        )
        self._featurePresetComboBox.currentTextChanged.connect(self._onFeaturePresetChanged)
        annotationLayout.addRow("Feature Set:", self._featurePresetComboBox)

        self._featureListGroupBox = ctk.ctkCollapsibleButton()
        self._featureListGroupBox.text = "Feature List"
        self._featureListGroupBox.flat = True
        self._featureListGroupBox.collapsed = True
        featureToolTip = "List of features used for segmentation. Values are in voxels."
        self._featureListGroupBox.setToolTip(featureToolTip)
        featureListLayout = qt.QVBoxLayout(self._featureListGroupBox)
        self._featureListLabel = qt.QLabel()
        self._featureListLabel.setWordWrap(True)
        self._featureListLabel.setToolTip(featureToolTip)
        featureListLayout.addWidget(self._featureListLabel)
        annotationLayout.addRow(self._featureListGroupBox)

        (
            self._segmentEditor,
            _,
            self._sourceVolumeComboBox,
            self._segmentationComboBox,
        ) = createSimplifiedSegmentEditor()

        maskingWidget = self._segmentEditor.findChild(qt.QGroupBox, "MaskingGroupBox")
        maskingWidget.visible = False
        maskingWidget.setFixedHeight(0)

        effects = [
            "Paint",
            "Draw",
            "Erase",
        ]
        self._segmentEditor.setEffectNameOrder(effects)
        self._segmentEditor.unorderedEffectsVisible = False
        self._segmentEditor.findChild(qt.QPushButton, "AddSegmentButton").visible = True
        self._segmentEditor.findChild(qt.QPushButton, "RemoveSegmentButton").visible = True
        annotationLayout.addRow(self._segmentEditor)

        self.outputSection = ctk.ctkCollapsibleButton()
        self.outputSection.text = "Output"
        self.outputSection.visible = False

        outputLayout = qt.QFormLayout(self.outputSection)

        self._inferenceImageSelector = ui.hierarchyVolumeInput(
            onChange=self._onInferenceNodeChanged,
            hasNone=True,
            nodeTypes=["vtkMRMLScalarVolumeNode"],
        )
        self._inferenceImageSelector.setMRMLScene(slicer.mrmlScene)
        self._inferenceImageSelector.setToolTip(
            "Select an image to apply the segmentation to. If None, the input image is used."
        )
        outputLayout.addRow("Inference Image:", self._inferenceImageSelector)

        self._applyButton = qt.QPushButton("Apply to Full Image")
        self._applyButton.toolTip = "Apply the current segmentation to the full image."
        self._applyButton.setFixedHeight(40)
        self._applyButton.setProperty("class", "actionButtonBackground")
        self._applyButton.clicked.connect(self._onApplyButtonClicked)
        self._applyButton.enabled = False
        inputLayout.addRow(" ", None)
        outputLayout.addRow(self._applyButton)

        self._progressBar = qt.QProgressBar()
        self._progressBar.setRange(0, 100)
        outputLayout.addRow(self._progressBar)
        self._statusLabel = qt.QLabel("Ready")
        self._statusLabel.setAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)
        outputLayout.addRow(self._statusLabel)

        layout.addWidget(self.outputSection)

        self._runButton.clicked.connect(self._onRunButtonClicked)

        layout.addSpacing(300)

        self._onInputNodeChanged(None)
        self._onStatusUpdate("Ready", show_progress=False)
        self._setRunButtonState(True)
        self._onFeaturePresetChanged(self._featurePresetComboBox.currentText)

        # Timers are Qt objects, so they should have the same lifetime as the widget.
        self._mainLoopTimer = qt.QTimer(self)
        self._progressTimer = qt.QTimer(self)

        self._scene_close_observer = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.StartCloseEvent, lambda *args: self._stopSegmentation()
        )

    def cleanup(self):
        if self._state and self._state.is_running():
            logging.debug("Module cleanup: Stopping segmentation process.")
            self._stopSegmentation()
        slicer.mrmlScene.RemoveObserver(self._scene_close_observer)

    def _onInputNodeChanged(self, vtkId):
        is_running = self._state and self._state.is_running()
        if is_running:
            self._runButton.enabled = True
        else:
            self._runButton.enabled = self._inputSelector.currentNode() is not None
        self._inferenceImageSelector.setCurrentNode(self._inputSelector.currentNode())

    def _onStatusUpdate(self, status_message, show_progress=False):
        if self._statusLabel:
            self._statusLabel.setText(status_message)
            self._progressBar.setVisible(show_progress)
            self._progressBar.setRange(0, 0) if show_progress else self._progressBar.setRange(0, 100)

    def _onFeatureProgressUpdate(self, progress, message):
        self._statusLabel.setText(f"Calculating features: {message}")
        self._progressBar.setRange(0, 100)
        self._progressBar.setValue(progress)
        self._progressBar.setVisible(True)

        if progress >= 100:
            self._onStatusUpdate("Ready", show_progress=False)
            self._annotationSection.enabled = True

    def _onModelTrained(self, status):
        if self._state:
            self._applyButton.enabled = status

    def _stopSegmentation(self):
        logging.debug("Stopping real-time segmentation process.")
        if self._state:
            self._state.stop_segmentation()
            self._state = None

        self._setRunButtonState(True)
        self._inputSelector.enabled = True
        onSegmentEditorExit(self._segmentEditor)

        self._annotationSection.visible = False
        self.outputSection.visible = False

        self._applyButton.enabled = False
        self._onStatusUpdate("Ready", show_progress=False)

    def _startSegmentation(self):
        source_node = self._inputSelector.currentNode()

        dims = source_node.GetImageData().GetDimensions()
        if np.prod(dims) > 700**3:
            msgBox = qt.QMessageBox(slicer.util.mainWindow())
            msgBox.setText(
                "The input image is large. For better performance, it is recommended to crop the image. You can apply the segmentation to the full image later."
            )
            msgBox.setInformativeText("Would you like to crop the volume?")
            cropButton = msgBox.addButton("Crop Image", qt.QMessageBox.YesRole)
            continueButton = msgBox.addButton("Continue Anyways", qt.QMessageBox.NoRole)
            cancelButton = msgBox.addButton(qt.QMessageBox.Cancel)
            msgBox.setDefaultButton(cancelButton)
            msgBox.exec_()

            if msgBox.clickedButton() == cropButton:
                self._switchToCropModule()
                return
            elif msgBox.clickedButton() == cancelButton:
                logging.debug("Segmentation process cancelled by user.")
                return

        annotation_node = None
        try:
            annotation_node = source_node.GetAttribute("InteractiveSegmenterAnnotationNode")
            if annotation_node is not None:
                annotation_node = slicer.mrmlScene.GetNodeByID(annotation_node)
            annotation_node = annotation_node or slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLSegmentationNode", f"{source_node.GetName()}_Annotation"
            )
            source_node.SetAttribute("InteractiveSegmenterAnnotationNode", annotation_node.GetID())
            helpers.setSourceVolume(annotation_node, source_node)

            logging.debug("Starting real-time segmentation process.")
            self._onStatusUpdate("Calculating features...", show_progress=True)
            self._annotationSection.enabled = False
            self._applyButton.enabled = False

            self._state = RealTimeSegLogic()
            self._state.on_full_segmentation_complete_callback = self._onFullSegmentationComplete
            self._state.on_process_crashed_callback = self._onProcessCrashed
            self._state.on_progress_callback = self._onFeatureProgressUpdate
            self._state.on_model_trained_callback = self._onModelTrained
            self._state.set_timers(self._mainLoopTimer, self._progressTimer)
            self._state.set_feature_preset(self._featurePresetComboBox.currentText)
            self._state.inference_volume_node = self._inferenceImageSelector.currentNode()
            self._state.start_segmentation(annotation_node)

            self._setRunButtonState(False)
            self._inputSelector.enabled = False
            onSegmentEditorEnter(self._segmentEditor, "InteractiveSegmenter")
            self._segmentationComboBox.setCurrentNode(annotation_node)
            self._sourceVolumeComboBox.setCurrentNode(source_node)

            self._annotationSection.visible = True
            self.outputSection.visible = True
        except Exception as e:
            slicer.util.errorDisplay(f"Failed to start segmentation process: {e}")
            self._stopSegmentation()
            raise e

    def _setRunButtonState(self, is_start):
        if is_start:
            self._runButton.text = self.START_TEXT
            self._runButton.toolTip = self.START_TIP
            self._runButton.setProperty("class", "actionButtonBackground")
        else:
            self._runButton.text = self.STOP_TEXT
            self._runButton.toolTip = self.STOP_TIP
            self._runButton.setProperty("class", "regularButton")

        # Force style update
        self._runButton.style().unpolish(self._runButton)
        self._runButton.style().polish(self._runButton)
        self._runButton.update()

    def _onInferenceNodeChanged(self, vtkId):
        if self._state:
            node = self._inferenceImageSelector.currentNode()
            self._state.inference_volume_node = node

    def _onRunButtonClicked(self):
        is_running = self._state and (self._state.is_running() or self._state.progress_timer.isActive())
        if is_running:
            self._stopSegmentation()
        else:
            self._startSegmentation()

    def _onFeaturePresetChanged(self, feature_preset_name):
        if self._state:
            self._state.set_feature_preset(feature_preset_name)

        FI = FeatureIndex
        if feature_preset_name == "Sharp":
            fi = [FI.SOURCE, FI.GAUSSIAN_A, FI.GAUSSIAN_B, FI.WINVAR_A]
        elif feature_preset_name == "Balanced":
            fi = [FI.SOURCE, FI.GAUSSIAN_A, FI.GAUSSIAN_B, FI.GAUSSIAN_C, FI.WINVAR_A, FI.WINVAR_B]
        elif feature_preset_name == "Smooth":
            fi = [FI.GAUSSIAN_A, FI.GAUSSIAN_B, FI.GAUSSIAN_C, FI.GAUSSIAN_D, FI.WINVAR_A, FI.WINVAR_B]
        elif feature_preset_name == "Extra Smooth":
            fi = [FI.GAUSSIAN_B, FI.GAUSSIAN_C, FI.GAUSSIAN_D, FI.WINVAR_A, FI.WINVAR_B]
        elif feature_preset_name == "Complete":
            fi = [FI(i) for i in range(len(FI))]
        else:
            fi = []
        feature_indices = [i.value for i in fi]

        self._featureListLabel.setText(
            "<ul>" + "".join([f"<li>{FEATURE_NAMES[FeatureIndex(i)]}</li>" for i in feature_indices]) + "</ul>"
        )

    def _onProcessCrashed(self):
        slicer.util.warningDisplay(
            "The segmentation process has crashed or terminated unexpectedly. "
            "Please check the logs for more details. The UI has been reset."
        )
        self._stopSegmentation()

    def _onApplyButtonClicked(self):
        if not self._state or not self._state.features_ready:
            slicer.util.warningDisplay("Features are not ready yet. Please wait.")
            return

        self._applyButton.enabled = False
        self._inputSection.enabled = False
        self._annotationSection.enabled = False

        self._state.applying_full_image = True

        if self._state.inference_volume_node:
            helpers.setSourceVolume(self._state.result_segmentation_node, self._state.inference_volume_node)
            self._state.tmp_labelmap_node.CopyOrientation(self._state.inference_volume_node)

        if self._state.paths.result.exists():
            self._state.paths.result.unlink()

        inference_node = self._state.inference_volume_node or self._state.source_volume_node
        if (
            self._state.inference_volume_node
            and self._state.inference_volume_node is not self._state.source_volume_node
        ):
            inference_array = slicer.util.arrayFromVolume(self._state.inference_volume_node)
            safe_save_numpy(inference_array, self._state.paths.inference_source)
            logging.debug(f"Inference image saved to {self._state.paths.inference_source}")

        extents_inclusive = inference_node.GetImageData().GetExtent()
        full_extents = [
            extents_inclusive[0],
            extents_inclusive[1] + 1,
            extents_inclusive[2],
            extents_inclusive[3] + 1,
            extents_inclusive[4],
            extents_inclusive[5] + 1,
        ]
        task_params = {
            "action": "predict",
            "extents": full_extents,
            "features": self._state.feature_indices,
            "is_full_inference": True,
        }

        self._state.main_loop_timer.stop()
        self._state.progress_timer.start()
        self._applyButton.enabled = False

        safe_dump_json(task_params, self._state.paths.task)

        logging.debug("Requested full image segmentation. Waiting for result...")
        self._onStatusUpdate("Applying segmentation to full image...", show_progress=True)

    def _onFullSegmentationComplete(self, final_result_node):
        input_node = self._state.inference_volume_node if self._state else None
        if not input_node:
            input_node = self._inputSelector.currentNode()

        input_name = input_node.GetName()
        output_name = slicer.mrmlScene.GenerateUniqueName(f"{input_name}_Segmented")
        final_result_node.SetName(output_name)

        self._stopSegmentation()

        displayNode = final_result_node.GetDisplayNode()
        if displayNode:
            displayNode.SetVisibility(True)
            displayNode.SetDisplayableOnlyInView(None)

        previewDisplayNode = final_result_node.GetNthDisplayNode(1)
        if previewDisplayNode:
            final_result_node.RemoveNthDisplayNodeID(1)
            slicer.mrmlScene.RemoveNode(previewDisplayNode)
        slicer.util.setSliceViewerLayers(background=input_node, fit=True)
        self._inputSection.enabled = True
        self._onStatusUpdate("Segmentation applied to full image.", show_progress=False)

    def _switchToCropModule(self):
        slicer.util.selectModule("CustomizedCropVolume")
        slicer.app.processEvents(1000)
        volume = self._inputSelector.currentNode()
        cropWidget = slicer.modules.CustomizedCropVolumeWidget
        cropWidget.volumeComboBox.setCurrentNode(volume)
        slicer.app.processEvents(1000)
        cropWidget.logic.setRoiSizeIjk(volume, (500, 500, 500))
        self._inputSelector.setCurrentNode(None)
