import ctk
import math
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
from humanize import naturaldelta, naturalsize
from pathlib import Path
from dataclasses import dataclass, field

from ltrace.interactive import consumer
from ltrace.interactive.features import feature_display_name
from ltrace.interactive.ipc import (
    InterprocessPaths,
    safe_save_numpy,
    safe_save_numpy_stacked,
    safe_unlink,
    safe_read_json,
    FeatureIndex,
    PRESETS,
    preset_feature_indices,
    safe_dump_json,
    compute_preview_factor,
)
from ltrace.interactive.slice_view_util import Slice, get_volume_extents_in_slice_view
from ltrace.interactive.scale_estimate import suggest_multiplier, SUPPORTED_MULTIPLIERS
from ltrace.slicer.side_by_side_image_layout import enable_zoom_sync
from ltrace.slicer.widget.global_progress_bar import CompanionProgressBar

from ltrace.slicer import ui
import numpy as np

from ltrace.slicer import helpers
from ltrace.slicer.node_observer import NodeObserver
from ltrace.slicer_utils import slicer_is_in_developer_mode
from ltrace.constants import SIDE_BY_SIDE_DUMB_LAYOUT_ID

from ltrace.flow.util import (
    createSimplifiedSegmentEditor,
    onSegmentEditorEnter,
    onSegmentEditorExit,
)

FULL_APPLY_TIMEOUT_SECONDS = 2**30

ANNOTATION_SLICE = "SideBySideDumb1"
PREVIEW_SLICE = "SideBySideDumb2"
VIEW_PLANES = ("XY", "XZ", "YZ")
ANNOTATION_REFERENCE_ROLE = "InteractiveSegmenterAnnotation"
LEGACY_ANNOTATION_ATTRIBUTE = "InteractiveSegmenterAnnotationNode"

# --- User-facing copy --------------------------------------------------------
# Every string shown to the user lives here so the copy can be reviewed and
# edited in one place. Templates use str.format placeholders.

# Input section
INPUT_SECTION_TITLE = "Input"
INPUT_IMAGE_LABEL = "Image 1:"
INPUT_IMAGE_TOOLTIP = "Select the volume to segment."
EXTRA_CHANNELS_GROUP_TITLE = "Extra channels (optional):"
EXTRA_IMAGE_LABEL = "Image {index}:"
EXTRA_IMAGE_TOOLTIP = (
    "Optional co-registered image of the same dimensions, appended as extra channels for "
    "segmentation (e.g. xpol0/xpol45 images of a thin section, or a saturated microCT scan)."
)

# Parameters section
PARAMETERS_SECTION_TITLE = "Parameters"
FEATURE_SCALE_LABEL = "Feature Scale:"
FEATURE_SCALE_AUTO = "Auto"
FEATURE_SCALE_ITEM = "{multiplier}x"
FEATURE_SCALE_TOOLTIP = (
    "Scale every feature kernel for coarser-textured images. "
    "Auto estimates the multiplier from the image's characteristic texture length."
)

# Run button
RUN_START_TEXT = "Start Annotation"
RUN_START_TOOLTIP = "Start annotating with a real-time preview of the result."
RUN_STOP_TEXT = "Cancel"
RUN_STOP_TOOLTIP = (
    "Stop the real-time segmentation preview. Your annotation will remain in project and you can resume later."
)

# Resume-annotation banner
RESUME_PROMPT_TEXT = "View layout changed. Would you like to resume annotation?"
RESUME_BUTTON_TEXT = "Resume Annotation"
RESUME_BUTTON_TOOLTIP = "Resume annotating with a real-time preview of the result."

# Annotation section
ANNOTATION_SECTION_TITLE = "Annotation"
VIEW_PLANE_LABEL = "View Plane:"
VIEW_PLANE_TOOLTIP = "Choose which plane of the volume to annotate and preview."
VIEW_PLANE_TOOLTIP_2D = "The image is 2D; only the XY plane is available."
FEATURE_SET_LABEL = "Feature Set:"
DEFAULT_FEATURE_PRESET = "Balanced"
FEATURE_SET_TOOLTIP = "Change the smoothness of the result by selecting which filters to apply before training."
FEATURE_SET_TOOLTIP_WARMING_UP = (
    "Other feature sets become selectable once feature computation finishes in the background."
)
FEATURE_LIST_TITLE = "Feature List"
FEATURE_LIST_TOOLTIP = "List of features used for segmentation. Values are in voxels."
FEATURE_LIST_AUTO_HEADER = "<i>Auto — sizes shown at 1×; the multiplier is estimated when you start.</i>"
FEATURE_LIST_SCALE_HEADER = "<i>Feature scale ×{scale}</i>"
UNCERTAINTY_TOOLTIP = (
    "Highlight in the left view the voxels the preview classifier is least certain about. "
    "These are the most useful places to add annotations."
)
UNCERTAINTY_CHECKBOX_LABEL = 'Show <a href="#" style="color:#ff6600; text-decoration:none;">uncertain</a> regions'
UNCERTAIN_SEGMENT_NAME = "Uncertain"

# Output section
OUTPUT_SECTION_TITLE = "Output"
APPLY_BUTTON_TEXT = "Apply to Full Image"
APPLY_BUTTON_TOOLTIP = "Apply the trained model to the whole of Image 1."
CANCEL_BUTTON_TEXT = "Cancel"
CANCEL_BUTTON_TOOLTIP = "Stop the current run. Your annotation will remain in project and you can resume later."
BATCH_BUTTON_TEXT = "Apply to Other Images..."
BATCH_BUTTON_TOOLTIP = "Apply the trained model to images other than Image 1."
BATCH_BUTTON_TOOLTIP_MULTIPLE_INPUTS = "Batch processing not available when using multiple inputs."

# Status line and progress
STATUS_READY = "Ready"
STATUS_PREVIEW_READY = "Preview ready."
STATUS_COMPUTING_PREVIEW = "Computing preview: {message}"
STATUS_START_ANNOTATING = "Computing preview — you can start annotating now"
STATUS_AUTO_FEATURE_SCALE = "Auto feature scale: x{scale}"
STATUS_APPLYING = "Applying segmentation..."
STATUS_APPLIED = "Segmentation applied to {image}."
# The status line carries only the action under way; the detail lives in the log.
STATUS_APPLY_STEP = "{position}{step}"
STATUS_APPLY_STEP_ETA = "{position}{step} - ETA: {eta}"

# Apply log. It is append-only: nothing written to it is ever rewritten, so a
# finished run can be read back as the whole story of what happened.
APPLY_LOG_QUEUE_PREFIX = "[{position}/{total}] "
APPLY_LOG_STARTING = "{prefix}Running full inference for image '{image}' of size {size} ({memory})"
APPLY_LOG_DONE = "Done in {elapsed}, created {result}"
APPLY_LOG_FINISHED = "Finished."
APPLY_LOG_FINISHED_BATCH = "Finished all {total} images in {elapsed}."
# The log outlives the run that wrote it, so it says which of the three states the
# run it is showing ended in rather than leaving the reader to guess from the text.
APPLY_LOG_HEADER_RUNNING = "Applying the segmentation. Live log:"
APPLY_LOG_HEADER_DONE = "Segmentation complete. Logs for the last run:"
APPLY_LOG_HEADER_STOPPED = "Segmentation stopped before finishing. Logs for the last run:"

# Large-image warning dialog
LARGE_IMAGE_VOXEL_LIMIT = 700**3
LARGE_IMAGE_TEXT = (
    "The input image is large. "
    "For better performance, it is recommended to crop the image. "
    "You can apply the segmentation to the full image later."
)
LARGE_IMAGE_INFORMATIVE_TEXT = "Would you like to crop the volume?"
LARGE_IMAGE_CROP_BUTTON = "Crop Image"
LARGE_IMAGE_CONTINUE_BUTTON = "Continue Anyways"

# Warnings and errors
ERROR_NO_SOURCE_VOLUME = "Could not find the source volume for the selected segmentation node."
ERROR_EXTRA_IMAGE_DIMENSIONS = "Extra image '{name}' must have the same dimensions as the input image."
ERROR_START_FAILED = "Failed to start segmentation process: {error}"
ERROR_BATCH_WITH_EXTRA_IMAGES = "Applying to another image is not supported when extra input images are used."
ERROR_INFERENCE_NODE_MISMATCH = (
    "'{name}' must have the same dimensionality (2D/3D) and number of channels as the input image."
)
WARNING_PROCESS_CRASHED = (
    "The segmentation process has crashed or terminated unexpectedly. "
    "Please check the logs for more details. The UI has been reset."
)
WARNING_FEATURES_NOT_READY = "Features are not ready yet. Please wait."

# "Apply to other images" dialog
BATCH_DIALOG_TITLE = "Apply to Other Images"
BATCH_DIALOG_HELP = (
    "<p>The model trained on your current annotation can segment other images too. "
    "Select the images to segment with it. Selecting a folder segments every image in it.</p>"
    "<p>The images are segmented one at a time in the background.</p>"
)
BATCH_DIALOG_CANCEL_TEXT = "Cancel"
BATCH_DIALOG_CANCEL_TOOLTIP = "Close this dialog without segmenting anything."
BATCH_DIALOG_APPLY_TEXT = "Apply"
BATCH_DIALOG_APPLY_TOOLTIP = "Segment each selected image with the trained model."
BATCH_DIALOG_NO_SELECTION = "<i>No image selected.</i>"
BATCH_DIALOG_IMAGE_COUNT_SINGULAR = "1 image"
BATCH_DIALOG_IMAGE_COUNT_PLURAL = "{count} images"
BATCH_DIALOG_SUMMARY = "Will apply a model with {segments} segments to {images}."


def is_large_3d_image(dims):
    """
    Whether a 3D image is big enough to be worth cropping before segmenting.

    ``math.prod`` (not ``np.prod``) on purpose: numpy would multiply the
    dimensions at the platform's default integer width, which is 32-bit on
    Windows, and silently wrap around past ~1300**3 -- exactly the volumes this
    is meant to catch.
    """
    return dims[2] > 1 and math.prod(dims) > LARGE_IMAGE_VOXEL_LIMIT


def _elapsed_text(seconds):
    """How long a run took, in the units someone reading the log thinks in.

    Deliberately not ``naturaldelta``: it rounds a 90-second apply to "a minute",
    and the point of these totals is comparing runs against each other. The units
    match the per-slab lines, so the parts and the whole read the same way.
    """
    # Rounded before the comparison: 59.96 s would otherwise print as "60.0 s".
    if round(seconds, 1) < 60:
        return f"{seconds:.1f} s"
    minutes, seconds = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes} min {seconds} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min"


def _copy_segment_names_and_colors(source_segmentation, target_segmentation):
    """
    Copy segment names and colors from source_segmentation to target_segmentation.
    """
    source = source_segmentation.GetSegmentation()
    target = target_segmentation.GetSegmentation()

    source_ids = source.GetSegmentIDs()
    target_ids = target.GetSegmentIDs()

    for source_id in source_ids:
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

        _, alive = psutil.wait_procs([parent] + children, timeout=timeout)
        if alive:
            for p in alive:
                p.kill()
            psutil.wait_procs(alive, timeout=timeout)
    except psutil.NoSuchProcess:
        pass


def get_annotation_node(source_node):
    node = source_node.GetNodeReference(ANNOTATION_REFERENCE_ROLE)
    if node is not None:
        return node
    # Projects saved by earlier releases carry the link as an attribute instead.
    legacy_id = source_node.GetAttribute(LEGACY_ANNOTATION_ATTRIBUTE)
    return slicer.mrmlScene.GetNodeByID(legacy_id) if legacy_id else None


def _get_annotated_voxel_values_from_array(segmentationNode):
    referenceVolumeNode = helpers.getSourceVolume(segmentationNode)

    scalarIJKToRAS_vtk = vtk.vtkMatrix4x4()
    referenceVolumeNode.GetIJKToRASMatrix(scalarIJKToRAS_vtk)

    scalarRASToIJK_vtk = vtk.vtkMatrix4x4()
    scalarRASToIJK_vtk.DeepCopy(scalarIJKToRAS_vtk)
    scalarRASToIJK_vtk.Invert()

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


_shared_segment_editor_widget = None
MERGE_EDITOR_SINGLETON_TAG = "InteractiveSegmenterMerge"


def shared_segment_editor():
    global _shared_segment_editor_widget
    if _shared_segment_editor_widget is None:
        _shared_segment_editor_widget = slicer.qMRMLSegmentEditorWidget()

    node = slicer.mrmlScene.GetSingletonNode(MERGE_EDITOR_SINGLETON_TAG, "vtkMRMLSegmentEditorNode")
    if node is None:
        node = slicer.mrmlScene.CreateNodeByClass("vtkMRMLSegmentEditorNode")
        node.UnRegister(None)
        node.SetSingletonTag(MERGE_EDITOR_SINGLETON_TAG)
        node = slicer.mrmlScene.AddNode(node)

    _shared_segment_editor_widget.setMRMLScene(slicer.mrmlScene)
    _shared_segment_editor_widget.setMRMLSegmentEditorNode(node)
    return _shared_segment_editor_widget, node


@dataclass
class RealTimeSegLogic:
    # Fields are grouped by responsibility. The class still owns all of them, but
    # the groups make it easier to see which fields change together and keep
    # unrelated concerns (e.g. uncertainty overlay vs. subprocess) from being
    # interleaved.

    # --- Subprocess lifecycle ---
    # The consumer process that computes features and runs train/predict.
    consumer_process: subprocess.Popen = None

    # --- IPC & task dispatch ---
    # Paths shared with the consumer, the timers driving the polling loops, and
    # the flags tracking what work is outstanding / which stage we are in.
    paths: InterprocessPaths = field(init=False)
    feature_indices: list = field(init=False)
    main_loop_timer: qt.QTimer = None
    progress_timer: qt.QTimer = None
    last_annotation_write_time: float = 0
    last_result_read_time: float = 0
    pending_training: bool = True
    pending_inference: bool = True
    pending_debug: bool = False
    applying_full_image: bool = False
    features_ready: bool = False
    # How much of the consumer's append-only apply log has already been handed to
    # the widget. The file is only ever appended to (and the base dir is wiped on
    # start_segmentation), so the offset alone says what is new.
    apply_log_offset: int = 0

    # --- Input & result MRML nodes ---
    # The user's annotation and source volumes, optional extra channels and a
    # separate inference image, plus the preview result nodes this class owns and
    # tears down (and the observer watching the annotation for edits).
    annotation_node: "vtkMRMLSegmentationNode" = None
    source_volume_node: "vtkMRMLScalarVolumeNode" = None
    inference_volume_node: "vtkMRMLScalarVolumeNode" = None
    extra_volume_nodes: list = field(default_factory=list)
    result_segmentation_node: "vtkMRMLSegmentationNode" = None
    tmp_labelmap_node: "vtkMRMLLabelMapVolumeNode" = None
    segmentation_obs: NodeObserver = None

    # --- View & layout ---
    # The annotation (left) slice view and its observer; the preview slice lives
    # on an instance attribute set in start_segmentation. previous_layout is the
    # layout to restore on cleanup; it stays None until start_segmentation has
    # switched the layout, so an early-failing start leaves nothing to restore.
    annotation_slice: Slice = None
    annotation_slice_obs: NodeObserver = None
    preview_slice_obs: NodeObserver = None
    previous_layout: int = None
    view_plane: str = "XY"

    # --- Feature configuration ---
    is_2d: bool = False
    feature_scale: int = 1

    # --- Uncertainty overlay ---
    # The faint "most uncertain voxels" overlay shown in the annotation view.
    show_uncertainty: bool = True
    uncertainty_segmentation_node: "vtkMRMLSegmentationNode" = None
    uncertainty_labelmap_node: "vtkMRMLLabelMapVolumeNode" = None

    # --- Callbacks to the widget ---
    on_full_segmentation_complete_callback: callable = None
    on_process_crashed_callback: callable = None
    on_progress_callback: callable = None
    on_apply_log_callback: callable = None
    on_model_trained_callback: callable = None
    on_features_complete_callback: callable = None
    on_debug_capture_ready_callback: callable = None
    on_view_plane_changed_callback: callable = None

    def __post_init__(self):
        temp_dir = Path(slicer.app.temporaryPath) / "InteractiveSegmenter"
        self.paths = InterprocessPaths(temp_dir)
        self.calculated_extents = []

    def set_timers(self, main_loop, progress):
        self.main_loop_timer = main_loop
        self.progress_timer = progress

    def set_feature_preset(self, feature_preset_name):
        self.feature_indices = preset_feature_indices(feature_preset_name)
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
        # ignore_errors tolerates a stale file an orphaned consumer may still
        # hold open on Windows (WinError 32); the fresh session writes over it.
        shutil.rmtree(self.paths.base_dir, ignore_errors=True)
        self.paths.base_dir.mkdir(parents=True, exist_ok=True)
        python_slicer_executable = shutil.which("PythonSlicer")

        self.annotation_node = segmentation_node
        self.source_volume_node = helpers.getSourceVolume(self.annotation_node)

        if not self.source_volume_node:
            raise ValueError(ERROR_NO_SOURCE_VOLUME)

        self.is_2d = self.source_volume_node.GetImageData().GetDimensions()[2] == 1

        layout_manager = slicer.app.layoutManager()
        self.previous_layout = layout_manager.layout
        layout_manager.setLayout(SIDE_BY_SIDE_DUMB_LAYOUT_ID)

        self.annotation_slice = Slice(ANNOTATION_SLICE)
        self.preview_slice = Slice(PREVIEW_SLICE)

        self.annotation_slice.set_bg(self.source_volume_node)
        self.preview_slice.set_bg(self.source_volume_node)
        slicer.app.processEvents(1000)

        self.annotation_slice.set_orientation(self.view_plane)
        self.preview_slice.set_orientation(self.view_plane)

        self.annotation_slice.fit()
        self.preview_slice.fit()

        self.preview_slice.link()
        self.annotation_slice.link()

        # Workaround for ctrl+scroll zoom not propagating the slice origin to linked views.
        enable_zoom_sync(ANNOTATION_SLICE, PREVIEW_SLICE)

        self._sync_preview_offset()

        for display_node in slicer.util.getNodesByClass("vtkMRMLSegmentationDisplayNode"):
            display_node.SetVisibility(False)

        self._setup_segmentation_display(segmentation_node, self.annotation_slice.node.GetID())

        source_arrays = [slicer.util.arrayFromVolume(self.source_volume_node)]
        for extra_node in self.extra_volume_nodes:
            extra_array = slicer.util.arrayFromVolume(extra_node)
            if extra_array.shape[:3] != source_arrays[0].shape[:3]:
                raise ValueError(ERROR_EXTRA_IMAGE_DIMENSIONS.format(name=extra_node.GetName()))
            source_arrays.append(extra_array)

        if len(source_arrays) == 1:
            safe_save_numpy(source_arrays[0], self.paths.source)
        else:
            # Extra co-registered images are appended as additional channels
            safe_save_numpy_stacked(source_arrays, self.paths.source)
        logging.debug(f"Source image saved to {self.paths.source}")

        si = None
        if sys.platform.startswith("win32"):
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE

        command = [
            str(python_slicer_executable),
            consumer.__file__,
            "--data-dir",
            self.paths.base_dir.resolve().as_posix(),
            "--parent-pid",
            str(os.getpid()),
            # Scale every feature kernel for coarser-textured images (1/2/4).
            "--feature-scale",
            str(self.feature_scale),
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

    def _drain_apply_log(self):
        """Hand the widget every apply-log line written since the last drain.

        Read before the progress file, so the lines describing the last slab are
        delivered even on the tick that also sees the completion marker and stops
        the timer. A trailing partial line (the consumer mid-write) is left for
        the next drain rather than parsed."""
        if not self.on_apply_log_callback or not self.paths.apply_log.exists():
            return
        try:
            # Binary, because a byte offset is not a valid text-mode seek cookie.
            with open(self.paths.apply_log, "rb") as f:
                f.seek(self.apply_log_offset)
                data = f.read()
        except OSError:
            return

        complete, newline, _ = data.rpartition(b"\n")
        if not newline:
            return
        self.apply_log_offset += len(complete) + len(newline)

        entries = []
        for line in complete.decode("utf-8", errors="replace").splitlines():
            try:
                entries.append(json.loads(line))
            except ValueError:
                logging.warning(f"Unparseable apply log line: {line}")
        if entries:
            self.on_apply_log_callback(entries)

    def _check_progress(self):
        self._drain_apply_log()

        if self.paths.progress.exists():
            try:
                with open(self.paths.progress, "r") as f:
                    progress_data = json.load(f)
                self.paths.progress.unlink()
            except (OSError, ValueError):
                progress_data = None

            if progress_data is not None:
                if self.on_progress_callback:
                    self.on_progress_callback(progress_data["progress"], progress_data["message"])

                # During a full-image apply the progress file alone signals completion.
                if self.applying_full_image and progress_data["progress"] >= 100:
                    # Last chance: the timer is about to stop, so anything the
                    # consumer logged since the drain above would never be shown.
                    self._drain_apply_log()
                    self.progress_timer.stop()
                    logging.debug("Full image task complete.")
                    self.check_and_update_result()
                    return

        if self.applying_full_image:
            return

        # Preview-ready: the active preset's features exist, so start serving previews.
        # The user may already have annotated; _start_main_loop force-trains on the
        # current annotation, so nothing painted during warmup is lost.
        if not self.features_ready and self.paths.preview_ready.exists():
            self.features_ready = True
            logging.debug("Preview features ready.")
            if self.on_progress_callback:
                self.on_progress_callback(100, STATUS_PREVIEW_READY)
            self._start_main_loop()

        # Features-complete: every feature is computed, so preset switching is safe.
        if self.paths.features_complete.exists():
            self.progress_timer.stop()
            logging.debug("All features computed.")
            if self.on_features_complete_callback:
                self.on_features_complete_callback()

    def _start_main_loop(self):
        self.segmentation_obs = NodeObserver(self.annotation_node)
        self.segmentation_obs.modifiedSignal.connect(self._on_segmentation_modified)

        self.annotation_slice_obs = NodeObserver(self.annotation_slice.node)
        self.annotation_slice_obs.modifiedSignal.connect(self._on_view_modified)

        self.preview_slice_obs = NodeObserver(self.preview_slice.node)
        self.preview_slice_obs.modifiedSignal.connect(self._on_view_modified)

        self._on_segmentation_modified()
        logging.debug("NodeObserver for segmentation node started.")

        self.main_loop_timer.setInterval(50)
        self.main_loop_timer.timeout.connect(self.update_loop)
        self.main_loop_timer.start()

    def stop_segmentation(self):
        self.progress_timer.stop()
        self.main_loop_timer.stop()
        self.progress_timer.timeout.disconnect()
        self.main_loop_timer.timeout.disconnect()

        if self.is_running():
            safe_dump_json({"action": "stop"}, self.paths.task)
            _kill_process_and_children(self.consumer_process)
        self.consumer_process = None

        self._cleanup()
        logging.debug("Real-time segmentation stopped and cleaned up.")

    def set_view_plane(self, plane):
        """Reorient both slice views to `plane` and refit, discarding the preview:
        segments computed in the old orientation show up as 1-voxel-thick lines in
        the new plane. Skipping views already on `plane` avoids re-fitting one the
        user just reoriented by hand."""
        if plane != self.view_plane:
            self._reset_preview()
        self.view_plane = plane
        for slice_obj in (self.annotation_slice, self.preview_slice):
            if slice_obj.orientation != plane:
                slice_obj.set_orientation(plane)
                slice_obj.fit()
        self._sync_preview_offset()

    def _sync_preview_offset(self):
        if self.annotation_slice.orientation != self.preview_slice.orientation:
            return
        self.annotation_slice.snap_to_ijk()
        ann_offset = self.annotation_slice.offset
        if abs(self.preview_slice.offset - ann_offset) > 1e-6:
            self.preview_slice.set_offset(ann_offset)

    def _sync_view_plane(self):
        """Adopt an orientation the user set through a slice view's own selector,
        propagating it to the other view and notifying the widget."""
        for slice_obj in (self.annotation_slice, self.preview_slice):
            plane = slice_obj.orientation
            # An oblique reformat reports "Reformat"; the module only tracks the
            # three axis-aligned planes, so ignore anything else.
            if plane != self.view_plane and plane in VIEW_PLANES:
                self.set_view_plane(plane)
                if self.on_view_plane_changed_callback:
                    self.on_view_plane_changed_callback(plane)
                return
        self._sync_preview_offset()

    def _on_view_modified(self, *args, **kwargs):
        if not self.annotation_node:
            logging.warning("Segmentation node is None in _on_view_modified; skipping update.")
            return
        self.pending_inference = True
        self._sync_view_plane()

    def _request_inference(self):
        extents = get_volume_extents_in_slice_view(self.source_volume_node, self.annotation_slice)
        if not extents:
            return
        factor = compute_preview_factor(extents) if self.is_2d else 1
        for existing_extent, existing_factor in self.calculated_extents:
            if (
                existing_factor <= factor
                and existing_extent[0] <= extents[0]
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

    def request_debug_capture(self):
        """
        Request a one-off debug preview for the current view. The consumer runs
        its normal preview path with a capture sink and writes debug_capture.npz,
        which update_loop picks up. The 2D report explains the lazy feature path
        over the whole image; the 3D report shows orthogonal central slices of the
        previewed region. Returns None on success or an explanatory message
        string on failure.
        """
        if not self.features_ready:
            return WARNING_FEATURES_NOT_READY
        is_trained = False
        if self.paths.model_status.exists():
            is_trained = safe_read_json(self.paths.model_status).get("is_trained", False)
        if not is_trained:
            return "Model is not trained yet. Annotate at least two classes first."
        extents = get_volume_extents_in_slice_view(self.source_volume_node, self.annotation_slice)
        if not extents:
            return "No visible region to capture."
        if self.paths.task.exists():
            return "The consumer is busy. Try again in a moment."
        if self.paths.debug_capture.exists():
            self.paths.debug_capture.unlink()

        # Per-image channel layout, in the same order the source channels are
        # stacked (source node first, then extras). Lets the renderer split the
        # flat channel stack back into one image (RGB or grayscale) per input.
        image_nodes = [self.source_volume_node] + list(self.extra_volume_nodes)
        image_channels = [node.GetImageData().GetNumberOfScalarComponents() for node in image_nodes]
        image_names = [node.GetName() for node in image_nodes]

        task_params = {
            "action": "predict",
            "extents": extents,
            "features": self.feature_indices,
            "debug": True,
            "image_channels": image_channels,
            "image_names": image_names,
        }
        safe_dump_json(task_params, self.paths.task)
        self.pending_debug = True
        return None

    def _check_debug_capture(self):
        if self.pending_debug and self.paths.debug_capture.exists():
            self.pending_debug = False
            if self.on_debug_capture_ready_callback:
                self.on_debug_capture_ready_callback(self.paths.debug_capture)

    def _on_segmentation_modified(self, *args, **kwargs):
        self._on_input_modified()

    def _on_input_modified(self):
        self.pending_training = True
        self._reset_preview()

    def _reset_preview(self):
        """Discard the accumulated preview segments and covered extents and schedule a fresh inference."""
        if self.result_segmentation_node:
            self.result_segmentation_node.GetSegmentation().RemoveAllSegments()
        if self.uncertainty_segmentation_node:
            self.uncertainty_segmentation_node.GetSegmentation().RemoveAllSegments()
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
            # The consumer may be mid-rewrite of model_status.json; its atomic
            # replace briefly denies readers on Windows (PermissionError). Skip
            # this cycle if so -- the next tick retries (same tolerance as the
            # result.unlink below).
            try:
                with open(self.paths.model_status, "r") as f:
                    model_status = json.load(f)
            except PermissionError:
                model_status = None
            if model_status is not None and self.on_model_trained_callback:
                self.on_model_trained_callback(model_status.get("is_trained", False))

        if self.pending_inference:
            # The consumer may still hold result.npz open while rewriting it, so
            # on Windows the delete can raise WinError 32. Skip this cycle if so;
            # the next tick retries (mirrors ipc.safe_replace's tolerance).
            try:
                self.paths.result.unlink(missing_ok=True)
            except PermissionError:
                pass
        else:
            self.check_and_update_result()
        self.check_and_update_inputs()
        self._check_debug_capture()

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

            with np.load(self.paths.result) as result_arrays:
                result_array = result_arrays.get("result", None)
                uncertainty_array = result_arrays.get("uncertainty", None)
                extents = result_arrays.get("extents", None)
                factor = int(result_arrays.get("factor", 1))

            if self.result_segmentation_node and result_array.size > 0:
                source_for_geometry = self.source_volume_node
                if self.applying_full_image and self.inference_volume_node:
                    source_for_geometry = self.inference_volume_node

                self._import_result_preview(result_array, extents, factor, source_for_geometry)

                if not self.applying_full_image and self.show_uncertainty:
                    self._update_uncertainty(uncertainty_array, extents, factor, source_for_geometry)

            self.last_result_read_time = mtime

            if self.applying_full_image:
                self._finalize_full_apply()

        except Exception as e:
            logging.exception("Failed to load or update reusult node.")

    def _import_result_preview(self, result_array, extents, factor, source_for_geometry):
        """Place `result_array` into the temporary labelmap with the right
        geometry, import it into the result segmentation, then merge the new
        segments into the ones accumulated so far (2D replaces wholesale)."""
        i_min, _, j_min, _, k_min, _ = extents

        ijkToRas = vtk.vtkMatrix4x4()
        source_for_geometry.GetIJKToRASMatrix(ijkToRas)
        origin_ras = ijkToRas.MultiplyPoint([i_min, j_min, k_min, 1])

        self.tmp_labelmap_node.SetOrigin(origin_ras[:3])
        # Downscaled previews cover `factor` source pixels per result pixel
        spacing = source_for_geometry.GetSpacing()
        self.tmp_labelmap_node.SetSpacing(spacing[0] * factor, spacing[1] * factor, spacing[2])
        slicer.util.updateVolumeFromArray(self.tmp_labelmap_node, result_array)

        if self.is_2d:
            # 2D previews always cover the whole visible region, and merging
            # mixed-resolution segments through the segment editor would
            # resample them at full resolution, which is prohibitive for
            # very large images. Replace the preview instead of merging.
            self.result_segmentation_node.GetSegmentation().RemoveAllSegments()
            self.calculated_extents.clear()

        n_existing_segments = self.result_segmentation_node.GetSegmentation().GetNumberOfSegments()
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
            self.tmp_labelmap_node, self.result_segmentation_node
        )
        n_total_segments = self.result_segmentation_node.GetSegmentation().GetNumberOfSegments()

        self._merge_result_segments(n_existing_segments, n_total_segments)

        self.calculated_extents.append((list(extents), factor))
        _copy_segment_names_and_colors(self.annotation_node, self.result_segmentation_node)

    def _merge_result_segments(self, n_existing_segments, n_total_segments):
        """Merge each freshly imported segment (indices
        [n_existing_segments, n_total_segments)) into the pre-existing segment
        with the same label value, so previews accumulated across views keep one
        segment per class rather than one per import."""
        segmentation = self.result_segmentation_node.GetSegmentation()

        result_segments_by_label = {}
        for i in range(n_existing_segments, n_total_segments):
            segment_id = segmentation.GetNthSegmentID(i)
            label_value = segmentation.GetSegment(segment_id).GetLabelValue()
            result_segments_by_label[label_value] = segment_id

        for i in range(n_existing_segments):
            source_segment_id = segmentation.GetNthSegmentID(i)
            label_value = segmentation.GetSegment(source_segment_id).GetLabelValue()
            target_segment_id = result_segments_by_label.get(label_value, None)
            if target_segment_id is not None:
                self.add_segment_to_segment(self.result_segmentation_node, source_segment_id, target_segment_id)
                segmentation.RemoveSegment(target_segment_id)
                logging.debug(f"Merged label {label_value}.")
            else:
                logging.debug(f"No result segment found for label {label_value}; skipping merge.")

    def _finalize_full_apply(self):
        """Stop the main loop and hand the completed full-image result node to the
        completion callback, releasing ownership so _cleanup won't delete it."""
        if self.main_loop_timer:
            self.main_loop_timer.stop()
        if self.on_full_segmentation_complete_callback:
            result_node = self.result_segmentation_node
            result_node.SaveWithSceneOn()

            # Don't delete later
            self.result_segmentation_node = None

            self.on_full_segmentation_complete_callback(result_node, self.inference_volume_node)

    def request_full_apply(self, inference_node):
        """Ask the consumer for a full-image prediction on `inference_node`, into a
        fresh result node. Called once per image of an apply queue."""
        self.applying_full_image = True
        self.inference_volume_node = inference_node
        if self.result_segmentation_node is None:
            self._create_result_segmentation_node()
        else:
            # The preview accumulated so far belongs to the input image. Clear it,
            # as we are now segmenting a potentially different image.
            self.result_segmentation_node.GetSegmentation().RemoveAllSegments()
        helpers.setSourceVolume(self.result_segmentation_node, inference_node)
        self.tmp_labelmap_node.CopyOrientation(inference_node)
        self.calculated_extents.clear()
        self.last_result_read_time = 0

        safe_unlink(self.paths.result)

        if inference_node is not self.source_volume_node:
            safe_save_numpy(slicer.util.arrayFromVolume(inference_node), self.paths.inference_source)
            logging.debug(f"Inference image saved to {self.paths.inference_source}")

        extents_inclusive = inference_node.GetImageData().GetExtent()
        task_params = {
            "action": "predict",
            "extents": [
                extents_inclusive[0],
                extents_inclusive[1] + 1,
                extents_inclusive[2],
                extents_inclusive[3] + 1,
                extents_inclusive[4],
                extents_inclusive[5] + 1,
            ],
            "features": self.feature_indices,
            "is_full_inference": True,
        }

        self.main_loop_timer.stop()
        self.progress_timer.start()
        safe_dump_json(task_params, self.paths.task)
        logging.debug(f"Requested full image segmentation of '{inference_node.GetName()}'. Waiting for result...")

    def _create_result_segmentation_node(self):
        self.result_segmentation_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLSegmentationNode", "SegmentationPreview"
        )
        self.result_segmentation_node.SaveWithSceneOff()
        self._setup_segmentation_display(self.result_segmentation_node, self.preview_slice.node.GetID())
        helpers.setSourceVolume(self.result_segmentation_node, self.source_volume_node)

    def _setup_result_node(self):
        self._create_result_segmentation_node()
        self.tmp_labelmap_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "TemporaryResult")
        self.tmp_labelmap_node.HideFromEditorsOn()
        self.tmp_labelmap_node.SaveWithSceneOff()
        self.tmp_labelmap_node.CopyOrientation(self.source_volume_node)

        # Overlay highlighting the classifier's most uncertain voxels, shown only
        # in the annotation (left) view alongside the user's annotation.
        self.uncertainty_segmentation_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLSegmentationNode", "UncertaintyPreview"
        )
        self.uncertainty_segmentation_node.SaveWithSceneOff()
        self._setup_segmentation_display(self.uncertainty_segmentation_node, self.annotation_slice.node.GetID())
        helpers.setSourceVolume(self.uncertainty_segmentation_node, self.source_volume_node)

        # The overlay sits on top of the user's annotation, so keep the fill faint
        # and rely on the outline to mark the uncertain regions without hiding the
        # underlying image.
        uncertainty_display = self.uncertainty_segmentation_node.GetNthDisplayNode(1)
        if uncertainty_display:
            uncertainty_display.SetOpacity2DFill(0.3)
            uncertainty_display.SetVisibility2DOutline(True)
            uncertainty_display.SetOpacity2DOutline(1.0)

        self.uncertainty_labelmap_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLLabelMapVolumeNode", "UncertaintyResult"
        )
        self.uncertainty_labelmap_node.HideFromEditorsOn()
        self.uncertainty_labelmap_node.SaveWithSceneOff()
        self.uncertainty_labelmap_node.CopyOrientation(self.source_volume_node)

        self._update_uncertainty_visibility()

        logging.debug(f"Created result node: {self.result_segmentation_node.GetName()}")

    def _update_uncertainty_visibility(self):
        if not self.uncertainty_segmentation_node:
            return
        display_node = self.uncertainty_segmentation_node.GetNthDisplayNode(1)
        if display_node:
            display_node.SetVisibility(self.show_uncertainty)

    def set_show_uncertainty(self, value):
        self.show_uncertainty = value
        self._update_uncertainty_visibility()
        if value:
            # Re-run inference so the overlay reflects the current view immediately.
            self.pending_inference = True
            self.calculated_extents.clear()
        elif self.uncertainty_segmentation_node:
            self.uncertainty_segmentation_node.GetSegmentation().RemoveAllSegments()

    def _update_uncertainty(self, uncertainty_array, extents, factor, source_for_geometry):
        if not self.uncertainty_segmentation_node:
            return

        segmentation = self.uncertainty_segmentation_node.GetSegmentation()
        # The overlay only ever reflects the current view, so replace it wholesale
        # rather than merging across extents like the result preview.
        segmentation.RemoveAllSegments()

        if uncertainty_array is None or uncertainty_array.size == 0 or not np.any(uncertainty_array):
            return

        i_min, _, j_min, _, k_min, _ = extents
        ijkToRas = vtk.vtkMatrix4x4()
        source_for_geometry.GetIJKToRASMatrix(ijkToRas)
        origin_ras = ijkToRas.MultiplyPoint([i_min, j_min, k_min, 1])

        self.uncertainty_labelmap_node.SetOrigin(origin_ras[:3])
        spacing = source_for_geometry.GetSpacing()
        self.uncertainty_labelmap_node.SetSpacing(spacing[0] * factor, spacing[1] * factor, spacing[2])
        slicer.util.updateVolumeFromArray(self.uncertainty_labelmap_node, uncertainty_array.astype(np.uint8))

        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
            self.uncertainty_labelmap_node, self.uncertainty_segmentation_node
        )

        for i in range(segmentation.GetNumberOfSegments()):
            segment = segmentation.GetSegment(segmentation.GetNthSegmentID(i))
            segment.SetName(UNCERTAIN_SEGMENT_NAME)
            segment.SetColor(1.0, 0.4, 0.0)

    def _cleanup(self):
        # Detach the shared segment editor widget from its segmentation node and
        # scene *before* removing any node. add_segment_to_segment() leaves that
        # widget observing result_segmentation_node, so removing that node while
        # the widget is still attached re-enters its segments model during
        # teardown and corrupts the sort/filter proxy mapping (crash in
        # qMRMLSegmentsModel::onSegmentRemoved). The widget itself outlives the
        # session; shared_segment_editor() reattaches it on the next merge.
        if _shared_segment_editor_widget is not None:
            _shared_segment_editor_widget.setSegmentationNode(None)
            _shared_segment_editor_widget.setMRMLScene(None)

        if self.tmp_labelmap_node and slicer.mrmlScene.IsNodePresent(self.tmp_labelmap_node):
            slicer.mrmlScene.RemoveNode(self.tmp_labelmap_node)
            self.tmp_labelmap_node = None

        if self.result_segmentation_node and slicer.mrmlScene.IsNodePresent(self.result_segmentation_node):
            slicer.mrmlScene.RemoveNode(self.result_segmentation_node)
            self.result_segmentation_node = None

        if self.uncertainty_labelmap_node and slicer.mrmlScene.IsNodePresent(self.uncertainty_labelmap_node):
            slicer.mrmlScene.RemoveNode(self.uncertainty_labelmap_node)
            self.uncertainty_labelmap_node = None

        if self.uncertainty_segmentation_node and slicer.mrmlScene.IsNodePresent(self.uncertainty_segmentation_node):
            slicer.mrmlScene.RemoveNode(self.uncertainty_segmentation_node)
            self.uncertainty_segmentation_node = None

        if self.segmentation_obs:
            self.segmentation_obs.clear()
        if self.annotation_slice_obs:
            self.annotation_slice_obs.clear()
        if self.preview_slice_obs:
            self.preview_slice_obs.clear()

        shutil.rmtree(self.paths.base_dir, ignore_errors=True)
        # Only restore the layout if start_segmentation actually changed it; an
        # early-failing start cleans up here before previous_layout was set.
        if self.previous_layout is not None:
            slicer.app.layoutManager().setLayout(self.previous_layout)

    def add_segment_to_segment(self, seg_node, segment_a, segment_b):
        modifierSegmentID = segment_b
        selectedSegmentID = segment_a
        editor_widget, editor_node = shared_segment_editor()
        editor_widget.setSegmentationNode(seg_node)
        editor_node.SetOverwriteMode(slicer.vtkMRMLSegmentEditorNode.OverwriteNone)
        editor_node.SetMaskMode(slicer.vtkMRMLSegmentationNode.EditAllowedEverywhere)
        editor_node.SetSelectedSegmentID(selectedSegmentID)
        editor_widget.setActiveEffectByName("Logical operators")
        effect = editor_widget.activeEffect()
        effect.setParameter("BypassMasking", "1")
        effect.setParameter("ModifierSegmentID", modifierSegmentID)
        effect.setParameter("Operation", "UNION")
        effect.self().onApply()


class ApplyToOtherImagesDialog(qt.QDialog):
    def __init__(self, segment_count, parent=None):
        super().__init__(parent or slicer.util.mainWindow())
        self._segmentCount = segment_count
        self.setWindowTitle(BATCH_DIALOG_TITLE)
        self.setMinimumWidth(500)

        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        helpLabel = qt.QLabel(BATCH_DIALOG_HELP)
        helpLabel.setWordWrap(True)
        layout.addWidget(helpLabel)

        self._treeView = slicer.qMRMLSubjectHierarchyTreeView()
        self._treeView.setMRMLScene(slicer.mrmlScene)
        for column in (2, 3, 4, 5):
            self._treeView.hideColumn(column)
        self._treeView.nodeTypes = ["vtkMRMLScalarVolumeNode", "vtkMRMLVectorVolumeNode"]
        self._treeView.setMultiSelection(True)
        self._treeView.setContextMenuEnabled(False)
        self._treeView.setEditMenuActionVisible(False)
        self._treeView.setMinimumHeight(250)
        layout.addWidget(self._treeView)

        self._summaryLabel = qt.QLabel()
        self._summaryLabel.setWordWrap(True)
        layout.addWidget(self._summaryLabel)

        self._cancelButton = qt.QPushButton(BATCH_DIALOG_CANCEL_TEXT)
        self._cancelButton.toolTip = BATCH_DIALOG_CANCEL_TOOLTIP
        self._cancelButton.setFixedSize(140, 40)
        self._cancelButton.clicked.connect(lambda: self.reject())

        self._applyButton = qt.QPushButton(BATCH_DIALOG_APPLY_TEXT)
        self._applyButton.toolTip = BATCH_DIALOG_APPLY_TOOLTIP
        self._applyButton.setFixedSize(140, 40)
        self._applyButton.setProperty("class", "actionButtonBackground")
        self._applyButton.clicked.connect(lambda: self.accept())

        buttonRowLayout = qt.QHBoxLayout()
        buttonRowLayout.setSpacing(12)
        buttonRowLayout.addStretch(1)
        buttonRowLayout.addWidget(self._cancelButton)
        buttonRowLayout.addWidget(self._applyButton)
        layout.addLayout(buttonRowLayout)

        # Connected only now: populating the tree emits a selection change, and the
        # summary needs the label and the button above.
        self._treeView.currentItemsChanged.connect(lambda _: self._updateSummary())
        self._updateSummary()

    def selectedNodes(self):
        """Volume nodes selected in the tree, expanding selected folders."""
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        selectedItems = vtk.vtkIdList()
        self._treeView.currentItems(selectedItems)

        itemIds = []
        for i in range(selectedItems.GetNumberOfIds()):
            itemId = selectedItems.GetId(i)
            if itemId == sh.GetSceneItemID():
                continue
            itemIds.append(itemId)
            children = vtk.vtkIdList()
            sh.GetItemChildren(itemId, children, True)
            itemIds.extend(children.GetId(j) for j in range(children.GetNumberOfIds()))

        nodes = []
        for itemId in dict.fromkeys(itemIds):
            node = sh.GetItemDataNode(itemId)
            if isinstance(node, slicer.vtkMRMLScalarVolumeNode) and node not in nodes:
                nodes.append(node)
        return nodes

    def _updateSummary(self):
        nodes = self.selectedNodes()
        if not nodes:
            self._summaryLabel.setText(BATCH_DIALOG_NO_SELECTION)
            self._applyButton.enabled = False
            return
        images = (
            BATCH_DIALOG_IMAGE_COUNT_SINGULAR
            if len(nodes) == 1
            else BATCH_DIALOG_IMAGE_COUNT_PLURAL.format(count=len(nodes))
        )
        self._summaryLabel.setText(BATCH_DIALOG_SUMMARY.format(segments=self._segmentCount, images=images))
        self._applyButton.enabled = True


class InteractiveSegmenterFrame(qt.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = None
        # Images still waiting for a full-image apply; the head of it is running.
        self._applyQueue = []
        self._applyTotal = 0
        self._applyProgress = 0
        # Slab bookkeeping for the running image, feeding the ETA: the slab last
        # reported, how many there are, and when the first one started.
        self._applySlab = 0
        self._applySlabTotal = 0
        self._applyFirstSlabTime = None
        # When the whole queue started, and when the image now running started.
        self._applyStartTime = None
        self._applyImageStartTime = None

        layout = qt.QVBoxLayout(self)

        self._resumeSegFrame = qt.QGroupBox()
        resumeSegLayout = qt.QVBoxLayout(self._resumeSegFrame)
        resumeSegLayout.addSpacing(20)
        self._resumeSegLabel = qt.QLabel(RESUME_PROMPT_TEXT)
        self._resumeSegLabel.setAlignment(qt.Qt.AlignCenter)
        resumeSegLayout.addWidget(self._resumeSegLabel)
        resumeSegLayout.addSpacing(10)
        self._resumeSegButton = qt.QPushButton(RESUME_BUTTON_TEXT)
        self._resumeSegButton.setFixedHeight(40)
        self._resumeSegButton.toolTip = RESUME_BUTTON_TOOLTIP
        self._resumeSegButton.setProperty("class", "actionButtonBackground")
        resumeSegLayout.addWidget(self._resumeSegButton)
        resumeSegLayout.addSpacing(20)

        self._resumeSegButton.clicked.connect(self._onResumeSegButtonClicked)
        self._resumeSegFrame.visible = False

        layout.addWidget(self._resumeSegFrame)

        self._inputSection = ctk.ctkCollapsibleButton()
        self._inputSection.collapsed = False
        self._inputSection.text = INPUT_SECTION_TITLE
        layout.addWidget(self._inputSection)
        inputLayout = qt.QFormLayout(self._inputSection)

        self._inputSelector = ui.hierarchyVolumeInput(
            onChange=self._onInputNodeChanged,
            hasNone=True,
            nodeTypes=["vtkMRMLScalarVolumeNode", "vtkMRMLVectorVolumeNode"],
        )
        self._inputSelector.setMRMLScene(slicer.mrmlScene)
        self._inputSelector.setToolTip(INPUT_IMAGE_TOOLTIP)
        inputLayout.addRow(" ", None)
        inputLayout.addRow(INPUT_IMAGE_LABEL, self._inputSelector)
        inputLayout.addRow(" ", None)

        self._extraImageSelectors = []
        extraImageGroupBox = qt.QGroupBox(EXTRA_CHANNELS_GROUP_TITLE)
        extraImageLayout = qt.QFormLayout(extraImageGroupBox)
        inputLayout.addRow(extraImageGroupBox)
        for index in (2, 3):
            extraSelector = ui.hierarchyVolumeInput(
                hasNone=True,
                nodeTypes=["vtkMRMLScalarVolumeNode", "vtkMRMLVectorVolumeNode"],
            )
            extraSelector.setMRMLScene(slicer.mrmlScene)
            extraSelector.setToolTip(EXTRA_IMAGE_TOOLTIP)
            extraImageLayout.addRow(EXTRA_IMAGE_LABEL.format(index=index), extraSelector)
            self._extraImageSelectors.append(extraSelector)

        self._paramSection = ctk.ctkCollapsibleButton()
        self._paramSection.collapsed = False
        self._paramSection.text = PARAMETERS_SECTION_TITLE
        inputLayout.addRow(self._paramSection)
        paramLayout = qt.QFormLayout(self._paramSection)

        self._featureScaleComboBox = qt.QComboBox()
        self._featureScaleComboBox.addItems(
            [FEATURE_SCALE_AUTO] + [FEATURE_SCALE_ITEM.format(multiplier=m) for m in SUPPORTED_MULTIPLIERS]
        )
        self._featureScaleComboBox.setToolTip(FEATURE_SCALE_TOOLTIP)
        self._featureScaleComboBox.currentTextChanged.connect(self._onFeatureScaleChanged)
        paramLayout.addRow(FEATURE_SCALE_LABEL, self._featureScaleComboBox)

        self._runButton = qt.QPushButton()
        self._runButton.setFixedHeight(40)
        self._runButton.objectName = "Run Button"

        inputLayout.addRow(" ", None)
        inputLayout.addRow(self._runButton)

        self._annotationSection = ctk.ctkCollapsibleButton()
        self._annotationSection.visible = False
        self._annotationSection.text = ANNOTATION_SECTION_TITLE
        layout.addWidget(self._annotationSection)
        annotationLayout = qt.QFormLayout(self._annotationSection)

        self._viewPlaneComboBox = qt.QComboBox()
        self._viewPlaneComboBox.addItems(list(VIEW_PLANES))
        self._viewPlaneTooltip = VIEW_PLANE_TOOLTIP
        self._viewPlaneComboBox.setToolTip(self._viewPlaneTooltip)
        self._viewPlaneComboBox.currentTextChanged.connect(self._onViewPlaneChanged)
        annotationLayout.addRow(VIEW_PLANE_LABEL, self._viewPlaneComboBox)

        self._featurePresetComboBox = qt.QComboBox()
        self._featurePresetComboBox.addItems(list(PRESETS.keys()))
        self._featurePresetComboBox.setCurrentText(DEFAULT_FEATURE_PRESET)
        self._featurePresetTooltip = FEATURE_SET_TOOLTIP
        self._featurePresetComboBox.setToolTip(self._featurePresetTooltip)
        self._featurePresetComboBox.currentTextChanged.connect(self._onFeaturePresetChanged)
        annotationLayout.addRow(FEATURE_SET_LABEL, self._featurePresetComboBox)

        self._featureListGroupBox = ctk.ctkCollapsibleButton()
        self._featureListGroupBox.text = FEATURE_LIST_TITLE
        self._featureListGroupBox.flat = True
        self._featureListGroupBox.collapsed = True
        featureToolTip = FEATURE_LIST_TOOLTIP
        self._featureListGroupBox.setToolTip(featureToolTip)
        featureListLayout = qt.QVBoxLayout(self._featureListGroupBox)
        self._featureListLabel = qt.QLabel()
        self._featureListLabel.setWordWrap(True)
        self._featureListLabel.setToolTip(featureToolTip)
        featureListLayout.addWidget(self._featureListLabel)
        annotationLayout.addRow(self._featureListGroupBox)

        uncertaintyToolTip = UNCERTAINTY_TOOLTIP
        self._showUncertaintyCheckBox = qt.QCheckBox()
        self._showUncertaintyCheckBox.setChecked(True)
        self._showUncertaintyCheckBox.setToolTip(uncertaintyToolTip)
        self._showUncertaintyCheckBox.toggled.connect(self._onShowUncertaintyToggled)

        # QCheckBox text is plain-text only, so the word is rendered in a sibling
        # rich-text label colored to match the uncertainty overlay (rgb 255,102,0).
        uncertaintyLabel = qt.QLabel(UNCERTAINTY_CHECKBOX_LABEL)
        uncertaintyLabel.setToolTip(uncertaintyToolTip)
        uncertaintyLabel.linkActivated.connect(lambda _: self._showUncertaintyCheckBox.toggle())

        uncertaintyRow = qt.QWidget()
        uncertaintyRowLayout = qt.QHBoxLayout(uncertaintyRow)
        uncertaintyRowLayout.setContentsMargins(0, 0, 0, 0)
        uncertaintyRowLayout.addWidget(self._showUncertaintyCheckBox)
        uncertaintyRowLayout.addWidget(uncertaintyLabel)
        uncertaintyRowLayout.addStretch(1)
        annotationLayout.addRow(uncertaintyRow)

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
            "Level tracing",
        ]
        self._segmentEditor.setEffectNameOrder(effects)
        self._segmentEditor.unorderedEffectsVisible = False
        self._segmentEditor.findChild(qt.QPushButton, "AddSegmentButton").visible = True
        self._segmentEditor.findChild(qt.QPushButton, "RemoveSegmentButton").visible = True
        annotationLayout.addRow(self._segmentEditor)

        self.outputSection = ctk.ctkCollapsibleButton()
        self.outputSection.text = OUTPUT_SECTION_TITLE
        self.outputSection.visible = False

        outputLayout = qt.QFormLayout(self.outputSection)

        self._applyButton = qt.QPushButton(APPLY_BUTTON_TEXT)
        self._applyButton.toolTip = APPLY_BUTTON_TOOLTIP
        self._applyButton.setFixedHeight(40)
        self._applyButton.setProperty("class", "actionButtonBackground")
        self._applyButton.clicked.connect(self._onApplyButtonClicked)
        self._applyButton.enabled = False

        self._cancelButton = qt.QPushButton(CANCEL_BUTTON_TEXT)
        self._cancelButton.toolTip = CANCEL_BUTTON_TOOLTIP
        self._cancelButton.setFixedHeight(40)
        self._cancelButton.clicked.connect(self._onRunButtonClicked)

        applyRow = qt.QWidget()
        applyRowLayout = qt.QHBoxLayout(applyRow)
        applyRowLayout.setContentsMargins(0, 0, 0, 0)
        applyRowLayout.addWidget(self._applyButton, 3)
        applyRowLayout.addWidget(self._cancelButton, 1)

        inputLayout.addRow(" ", None)
        outputLayout.addRow(applyRow)

        self._batchButton = qt.QPushButton(BATCH_BUTTON_TEXT)
        self._batchTooltip = BATCH_BUTTON_TOOLTIP
        self._batchButton.setToolTip(self._batchTooltip)
        self._batchButton.setFixedHeight(40)
        self._batchButton.clicked.connect(self._onBatchButtonClicked)
        self._batchButton.enabled = False
        outputLayout.addRow(self._batchButton)

        # Developer aid: dump and render a montage explaining how the current
        # preview was computed (features, computed region, training samples,
        # result for 2D; orthogonal feature/result slices for 3D).
        self._debugPreviewButton = qt.QPushButton("Debug Preview")
        self._debugPreviewButton.toolTip = "Render a montage explaining how the current preview is computed."
        self._debugPreviewButton.clicked.connect(self._onDebugPreviewClicked)
        self._debugPreviewButton.visible = slicer_is_in_developer_mode()
        outputLayout.addRow(self._debugPreviewButton)

        self._progressBar = qt.QProgressBar()
        self._progressBar.setRange(0, 100)
        outputLayout.addRow(self._progressBar)
        self._statusLabel = qt.QLabel(STATUS_READY)
        self._statusLabel.setAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)
        outputLayout.addRow(self._statusLabel)

        layout.addWidget(self.outputSection)

        # What the user reads to follow an apply run, and to read back afterwards
        # what it did. It sits in the panel's own layout rather than in the Output
        # section because a finished apply closes the session that produced it: from
        # inside the section, the record would disappear at the exact moment the user
        # turns to it. Once shown it stays, and its header says which run it belongs to.
        self._applyLogFrame = qt.QWidget()
        applyLogLayout = qt.QVBoxLayout(self._applyLogFrame)
        applyLogLayout.setContentsMargins(0, 0, 0, 0)
        self._applyLogHeaderLabel = qt.QLabel()
        self._applyLogHeaderLabel.setWordWrap(True)
        applyLogLayout.addWidget(self._applyLogHeaderLabel)
        self._applyLogTextEdit = qt.QPlainTextEdit()
        self._applyLogTextEdit.setReadOnly(True)
        applyLogLayout.addWidget(self._applyLogTextEdit)
        self._applyLogFrame.visible = False
        layout.addWidget(self._applyLogFrame)

        self._runButton.clicked.connect(self._onRunButtonClicked)

        layout.addSpacing(300)

        self._onInputNodeChanged(None)
        self._onStatusUpdate(STATUS_READY, show_progress=False)
        self._setRunButtonState(True)
        self._onFeaturePresetChanged(self._featurePresetComboBox.currentText)

        # Timers are Qt objects, so they should have the same lifetime as the widget.
        self._mainLoopTimer = qt.QTimer(self)
        self._progressTimer = qt.QTimer(self)

        self._sceneCloseObserver = slicer.mrmlScene.AddObserver(slicer.mrmlScene.StartCloseEvent, self._onCloseEvent)
        self.destroyed.connect(lambda *_: self._releaseGlobalCallbacks())

        # Reports full-image apply progress on the application status bar.
        self._cliProgressBar = CompanionProgressBar()

    def _releaseGlobalCallbacks(self):
        """The scene and the layout manager outlive this widget and hold references to
        its bound methods, so they go on calling a destroyed widget unless dropped."""
        if self._sceneCloseObserver is None:
            return
        slicer.mrmlScene.RemoveObserver(self._sceneCloseObserver)
        self._sceneCloseObserver = None
        slicer.app.layoutManager().layoutChanged.disconnect(self._onLayoutChanged)

    def _onCloseEvent(self, *args, **kwargs):
        self._stopSegmentation()

    def exit(self):
        if self._state and self._state.applying_full_image:
            logging.debug("Module exit: full image apply continues in the background.")
            onSegmentEditorExit(self._segmentEditor)
            return
        if self._state:
            self._stopSegmentation()

    def cleanup(self):
        if self._state:
            logging.debug("Module cleanup: Stopping segmentation process.")
            self._stopSegmentation()
        self._releaseGlobalCallbacks()

    def _onInputNodeChanged(self, vtkId):
        is_running = self._state and self._state.is_running()
        if is_running:
            self._runButton.enabled = True
        else:
            self._runButton.enabled = self._inputSelector.currentNode() is not None

    def _setStatusText(self, status_message):
        """Say what is being done right now, leaving the progress bar as it is.

        The status line holds one line: the action under way. Everything worth
        keeping goes to the apply log, which is never rewritten."""
        if self._statusLabel:
            self._statusLabel.setText(status_message)

    def _onStatusUpdate(self, status_message, show_progress=False):
        self._setStatusText(status_message)
        if self._statusLabel:
            self._progressBar.setVisible(show_progress)
            self._progressBar.setRange(0, 0) if show_progress else self._progressBar.setRange(0, 100)

    def _startGlobalProgress(self):
        self._cliProgressBar.processStopped()
        self._cliProgressBar.start(f"interactive_segmenter_{time.time_ns()}", FULL_APPLY_TIMEOUT_SECONDS)

    def _updateGlobalProgress(self, value):
        if self._cliProgressBar.isRunning():
            self._cliProgressBar.update(value)

    def _onFeatureProgressUpdate(self, progress, message):
        if self._state and self._state.applying_full_image:
            # The bar covers the whole queue; the consumer only knows the current
            # image. This channel's text is not shown during an apply: the log and
            # the status line are driven by the apply log instead, which -- unlike
            # this one -- cannot drop a step another step quickly follows.
            self._setApplyProgress(self._queueProgress(progress))
            return

        # Annotation is already enabled (see _startSegmentation); this only reports
        # how close the preview is while the user annotates.
        self._progressBar.setRange(0, 100)
        self._progressBar.setVisible(True)
        self._progressBar.setValue(progress)
        if progress >= 100:
            self._onStatusUpdate(STATUS_READY, show_progress=False)
        else:
            self._setStatusText(STATUS_COMPUTING_PREVIEW.format(message=message))

    def _onFeaturesComplete(self):
        # Every feature is now cached, so switching presets no longer risks reading
        # not-yet-computed features.
        self._featurePresetComboBox.enabled = True
        self._featurePresetComboBox.setToolTip(self._featurePresetTooltip)

    def _onModelTrained(self, status):
        if self._state:
            self._applyButton.enabled = status
            self._batchButton.enabled = status and not self._state.extra_volume_nodes

    def _onResumeSegButtonClicked(self):
        layoutManager = slicer.app.layoutManager()
        layoutManager.setLayout(SIDE_BY_SIDE_DUMB_LAYOUT_ID)

    def _onLayoutChanged(self, layout):
        if layout != SIDE_BY_SIDE_DUMB_LAYOUT_ID and self._state and not self._state.applying_full_image:
            self._resumeSegFrame.visible = True
        else:
            self._resumeSegFrame.visible = False

    def _stopSegmentation(self):
        logging.debug("Stopping real-time segmentation process.")
        self._updateGlobalProgress(1.0)
        self._applyQueue.clear()
        if self._state:
            self._state.stop_segmentation()
            self._state = None

        self._setRunButtonState(True)
        self._inputSection.enabled = True
        self._inputSelector.enabled = True
        self._featureScaleComboBox.enabled = True
        self._featurePresetComboBox.enabled = True
        self._featurePresetComboBox.setToolTip(self._featurePresetTooltip)
        self._viewPlaneComboBox.enabled = True
        self._viewPlaneComboBox.setToolTip(self._viewPlaneTooltip)
        for extraSelector in self._extraImageSelectors:
            extraSelector.enabled = True
        self._updateFeatureList()  # state is gone; revert to the combobox selection
        onSegmentEditorExit(self._segmentEditor)

        self._annotationSection.visible = False
        self.outputSection.visible = False
        self._inputSection.collapsed = False
        # The log itself stays: it is the record of the run, and this is where a
        # completed apply lands. Only the header, which still promises a running
        # apply, has to be corrected -- a finished run has already replaced it.
        if self._applyLogHeaderLabel.text == APPLY_LOG_HEADER_RUNNING:
            self._applyLogHeaderLabel.text = APPLY_LOG_HEADER_STOPPED

        self._applyButton.enabled = False
        self._batchButton.enabled = False
        self._resumeSegFrame.visible = False
        self._onStatusUpdate(STATUS_READY, show_progress=False)
        slicer.app.layoutManager().layoutChanged.disconnect(self._onLayoutChanged)

    def _startSegmentation(self):
        source_node = self._inputSelector.currentNode()

        dims = source_node.GetImageData().GetDimensions()
        if is_large_3d_image(dims):
            msgBox = qt.QMessageBox(slicer.util.mainWindow())
            msgBox.setText(LARGE_IMAGE_TEXT)
            msgBox.setInformativeText(LARGE_IMAGE_INFORMATIVE_TEXT)
            cropButton = msgBox.addButton(LARGE_IMAGE_CROP_BUTTON, qt.QMessageBox.YesRole)
            continueButton = msgBox.addButton(LARGE_IMAGE_CONTINUE_BUTTON, qt.QMessageBox.NoRole)
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
            annotation_node = get_annotation_node(source_node)
            # vtkMRMLNode.Copy does carry references over, so verify ownership too.
            if annotation_node and helpers.getSourceVolume(annotation_node) is not source_node:
                annotation_node = None
            annotation_node = annotation_node or slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLSegmentationNode", f"{source_node.GetName()}_Annotation"
            )
            source_node.SetNodeReferenceID(ANNOTATION_REFERENCE_ROLE, annotation_node.GetID())
            source_node.RemoveAttribute(LEGACY_ANNOTATION_ATTRIBUTE)
            helpers.setSourceVolume(annotation_node, source_node)

            logging.debug("Starting real-time segmentation process.")
            self._onStatusUpdate(STATUS_START_ANNOTATING, show_progress=True)
            # Let the user annotate immediately while features warm up; the preview
            # appears once they are ready. Preset switching stays disabled until all
            # features are computed (3D), so a switch can't reference missing features.
            self._annotationSection.enabled = True
            self._featurePresetComboBox.enabled = False
            self._featurePresetComboBox.setToolTip(FEATURE_SET_TOOLTIP_WARMING_UP)
            self._applyButton.enabled = False

            self._state = RealTimeSegLogic()
            self._state.on_full_segmentation_complete_callback = self._onFullSegmentationComplete
            self._state.on_process_crashed_callback = self._onProcessCrashed
            self._state.on_progress_callback = self._onFeatureProgressUpdate
            self._state.on_apply_log_callback = self._onApplyLog
            self._state.on_model_trained_callback = self._onModelTrained
            self._state.on_features_complete_callback = self._onFeaturesComplete
            self._state.on_debug_capture_ready_callback = self._onDebugCaptureReady
            self._state.on_view_plane_changed_callback = self._onViewPlaneChangedInView
            self._state.set_timers(self._mainLoopTimer, self._progressTimer)
            self._state.set_feature_preset(self._featurePresetComboBox.currentText)
            self._state.extra_volume_nodes = [
                selector.currentNode()
                for selector in self._extraImageSelectors
                if selector.currentNode() and selector.currentNode() is not source_node
            ]
            self._batchButton.setToolTip(
                BATCH_BUTTON_TOOLTIP_MULTIPLE_INPUTS if self._state.extra_volume_nodes else self._batchTooltip
            )
            self._state.show_uncertainty = self._showUncertaintyCheckBox.isChecked()
            self._state.feature_scale = self._resolveFeatureScale(source_node)
            self._updateFeatureList()  # reflect the resolved (possibly Auto) scale

            default_plane = self._defaultViewPlane(source_node)
            self._viewPlaneComboBox.blockSignals(True)
            self._viewPlaneComboBox.setCurrentText(default_plane)
            self._viewPlaneComboBox.blockSignals(False)
            is_2d = dims[2] == 1
            self._viewPlaneComboBox.enabled = not is_2d
            self._viewPlaneComboBox.setToolTip(VIEW_PLANE_TOOLTIP_2D if is_2d else self._viewPlaneTooltip)
            self._state.view_plane = default_plane

            self._state.start_segmentation(annotation_node)

            self._setRunButtonState(False)
            self._featureScaleComboBox.enabled = False
            self._inputSelector.enabled = False
            for extraSelector in self._extraImageSelectors:
                extraSelector.enabled = False
            onSegmentEditorEnter(self._segmentEditor, "InteractiveSegmenter")
            self._segmentationComboBox.setCurrentNode(annotation_node)
            self._sourceVolumeComboBox.setCurrentNode(source_node)

            self._annotationSection.visible = True
            self.outputSection.visible = True
            # Keep the panel on the work at hand; the input is read-only during a session.
            self._inputSection.collapsed = True
            slicer.app.layoutManager().layoutChanged.connect(self._onLayoutChanged)
        except Exception as e:
            slicer.util.errorDisplay(ERROR_START_FAILED.format(error=e))
            self._stopSegmentation()
            raise e

    def _setRunButtonState(self, is_start):
        if is_start:
            self._runButton.text = RUN_START_TEXT
            self._runButton.toolTip = RUN_START_TOOLTIP
            self._runButton.setProperty("class", "actionButtonBackground")
        else:
            self._runButton.text = RUN_STOP_TEXT
            self._runButton.toolTip = RUN_STOP_TOOLTIP
            self._runButton.setProperty("class", "regularButton")

        # Force style update
        self._runButton.style().unpolish(self._runButton)
        self._runButton.style().polish(self._runButton)
        self._runButton.update()

    def _onRunButtonClicked(self):
        is_running = self._state and (self._state.is_running() or self._state.progress_timer.isActive())
        if is_running:
            self._stopSegmentation()
        else:
            self._startSegmentation()

    def _resolveFeatureScale(self, source_node):
        """Resolve the Feature Scale combobox to an integer multiplier, estimating
        it from the image's characteristic texture length when set to Auto."""
        text = self._featureScaleComboBox.currentText
        if text != FEATURE_SCALE_AUTO:
            return int(text.rstrip("x"))
        try:
            array = slicer.util.arrayFromVolume(source_node)
            scale = suggest_multiplier(array)
            logging.info(f"Auto feature scale: estimated x{scale} for '{source_node.GetName()}'.")
            self._onStatusUpdate(STATUS_AUTO_FEATURE_SCALE.format(scale=scale), show_progress=True)
            return scale
        except Exception as e:
            logging.warning(f"Auto feature scale estimation failed ({e}); falling back to x1.")
            return 1

    @staticmethod
    def _defaultViewPlane(source_node):
        """Show XY by default, the usual way to view microCT cylinders. For very
        anisotropic volumes (e.g. well cores) show the largest slice instead."""
        dims = source_node.GetImageData().GetDimensions()
        if max(dims) <= 2 * min(dims):
            return "XY"
        areas = {
            "XY": dims[0] * dims[1],
            "XZ": dims[0] * dims[2],
            "YZ": dims[1] * dims[2],
        }
        return max(areas, key=areas.get)

    def _onViewPlaneChanged(self, plane):
        if self._state and self._state.annotation_slice:
            self._state.set_view_plane(plane)

    def _onViewPlaneChangedInView(self, plane):
        self._viewPlaneComboBox.blockSignals(True)
        self._viewPlaneComboBox.setCurrentText(plane)
        self._viewPlaneComboBox.blockSignals(False)

    def _onShowUncertaintyToggled(self, checked):
        if self._state:
            self._state.set_show_uncertainty(checked)

    def _onFeaturePresetChanged(self, feature_preset_name):
        if self._state:
            self._state.set_feature_preset(feature_preset_name)

        self._currentFeatureIndices = preset_feature_indices(feature_preset_name)
        self._updateFeatureList()

    def _currentDisplayScale(self):
        """(scale, is_auto) to show in the feature list: the running session's
        resolved multiplier, else the combobox selection (Auto shown at 1x)."""
        if self._state is not None:
            return self._state.feature_scale, False
        text = self._featureScaleComboBox.currentText
        if text == FEATURE_SCALE_AUTO:
            return 1, True
        return int(text.rstrip("x")), False

    def _updateFeatureList(self):
        scale, is_auto = self._currentDisplayScale()
        items = "".join(
            f"<li>{feature_display_name(FeatureIndex(i), scale)}</li>"
            for i in getattr(self, "_currentFeatureIndices", [])
        )
        if is_auto:
            header = FEATURE_LIST_AUTO_HEADER
        elif scale != 1:
            header = FEATURE_LIST_SCALE_HEADER.format(scale=scale)
        else:
            header = ""
        self._featureListLabel.setText(header + "<ul>" + items + "</ul>")

    def _onFeatureScaleChanged(self, _text):
        self._updateFeatureList()

    def _onProcessCrashed(self):
        slicer.util.warningDisplay(WARNING_PROCESS_CRASHED)
        self._stopSegmentation()

    def _onDebugPreviewClicked(self):
        if not self._state:
            return
        message = self._state.request_debug_capture()
        if message:
            slicer.util.warningDisplay(message)
            return
        self._onStatusUpdate("Computing debug preview...", show_progress=False)

    def _onDebugCaptureReady(self, npz_path):
        try:
            from ltrace.interactive.debug_render import render_capture

            pdf_path = render_capture(npz_path)
            qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(str(pdf_path)))
            self._onStatusUpdate(f"Debug preview saved to {pdf_path}", show_progress=False)
        except Exception as exc:
            logging.error(f"Failed to render debug preview: {exc}\n{traceback.format_exc()}")
            slicer.util.warningDisplay(f"Failed to render debug preview: {exc}")

    def _inferenceNodeError(self, node):
        """Why `node` can't be segmented with the current model, or None if it can."""
        source_node = self._state.source_volume_node
        if node is source_node:
            return None
        if self._state.extra_volume_nodes:
            return ERROR_BATCH_WITH_EXTRA_IMAGES
        source_image = source_node.GetImageData()
        image = node.GetImageData()
        if (source_image.GetDimensions()[2] == 1) != (image.GetDimensions()[2] == 1) or (
            source_image.GetNumberOfScalarComponents() != image.GetNumberOfScalarComponents()
        ):
            return ERROR_INFERENCE_NODE_MISMATCH.format(name=node.GetName())
        return None

    def _onApplyButtonClicked(self):
        self._startApply([self._state.source_volume_node] if self._state else [])

    def _onBatchButtonClicked(self):
        segments = self._state.annotation_node.GetSegmentation().GetNumberOfSegments()
        dialog = ApplyToOtherImagesDialog(segments, self)
        nodes = dialog.selectedNodes() if dialog.exec_() == qt.QDialog.Accepted else []
        dialog.deleteLater()
        if nodes:
            self._startApply(nodes)

    def _startApply(self, nodes):
        if not self._state or not self._state.features_ready:
            slicer.util.warningDisplay(WARNING_FEATURES_NOT_READY)
            return
        for node in nodes:
            error = self._inferenceNodeError(node)
            if error:
                slicer.util.warningDisplay(error)
                return

        self._applyQueue = list(nodes)
        self._applyTotal = len(nodes)
        self._applyProgress = 0
        self._applyStartTime = time.time()
        self._applyLogTextEdit.clear()
        self._applyLogHeaderLabel.text = APPLY_LOG_HEADER_RUNNING
        self._applyLogFrame.visible = True
        self._applyButton.enabled = False
        self._batchButton.enabled = False
        self._inputSection.enabled = False
        self._annotationSection.enabled = False
        self._startGlobalProgress()
        self._onStatusUpdate(STATUS_APPLYING, show_progress=True)
        self._setApplyProgress(0)
        self._applyNextInQueue()

    def _applyLogPrefix(self):
        """The running image's place in the queue, or nothing when it is the only one."""
        if self._applyTotal <= 1:
            return ""
        return APPLY_LOG_QUEUE_PREFIX.format(position=self._applyTotal - len(self._applyQueue), total=self._applyTotal)

    @staticmethod
    def _imageSizeText(node):
        """The image's size as the user thinks of it (IxJxK), and what it occupies."""
        image = node.GetImageData()
        dimensions = image.GetDimensions()
        voxel_bytes = image.GetScalarSize() * image.GetNumberOfScalarComponents()
        # Deliberately not np.prod: that returns a platform int, which overflows on
        # Windows past ~1300^3 -- exactly the sizes worth logging.
        voxels = dimensions[0] * dimensions[1] * dimensions[2]
        return "x".join(str(d) for d in dimensions), naturalsize(voxels * voxel_bytes, binary=True)

    def _onApplyLog(self, entries):
        """Show everything the consumer reported since the last poll, in order."""
        for entry in entries:
            message = entry.get("message", "")
            self._logApply(message)
            self._updateApplyStatus(entry, message)

    def _updateApplyStatus(self, entry, message):
        """Put the step under way on the status line, with an ETA once one can be had.

        The estimate extrapolates the average time a finished slab took over the
        slabs left, so it only exists from the second slab on: before that there is
        nothing measured to extrapolate from, and a guess would be worse than silence.
        """
        if entry.get("slabs"):
            self._applySlabTotal = entry["slabs"]
        slab = entry.get("slab")
        if not slab:
            return
        if slab != self._applySlab:
            if self._applyFirstSlabTime is None:
                self._applyFirstSlabTime = time.time()
            self._applySlab = slab

        finished = self._applySlab - 1
        position = self._applyLogPrefix()
        if finished < 1 or self._applyFirstSlabTime is None:
            self._setStatusText(STATUS_APPLY_STEP.format(position=position, step=message))
            return

        average = (time.time() - self._applyFirstSlabTime) / finished
        remaining = average * max(0, self._applySlabTotal - finished)
        self._setStatusText(STATUS_APPLY_STEP_ETA.format(position=position, step=message, eta=naturaldelta(remaining)))

    def _queueProgress(self, progress):
        """How far the whole apply queue is, given `progress` on the running image."""
        finished = self._applyTotal - len(self._applyQueue) - 1
        return round((finished + progress / 100) / self._applyTotal * 100)

    def _setApplyProgress(self, progress):
        """Show the queue's progress on both bars, never going backwards."""
        self._applyProgress = max(self._applyProgress, progress)
        self._progressBar.setRange(0, 100)
        self._progressBar.setVisible(True)
        self._progressBar.setValue(self._applyProgress)
        self._updateGlobalProgress(self._applyProgress / 100)

    def _logApply(self, message):
        """Append one line to the apply log.

        Nothing here is ever rewritten: a run's log is the whole story of what it
        did, in order, which is what makes it worth reading after the fact. Every
        line also goes to the application log, which outlives this widget.

        The view follows the tail only while the user is already at the tail, so
        scrolling back to read something is not undone by the next line.
        """
        logging.info(f"Interactive segmenter: {message}")
        scrollBar = self._applyLogTextEdit.verticalScrollBar()
        wasAtEnd = scrollBar.value >= scrollBar.maximum - 4
        self._applyLogTextEdit.appendPlainText(message)
        if wasAtEnd:
            scrollBar.setValue(scrollBar.maximum)

    def _applyNextInQueue(self):
        node = self._applyQueue.pop(0)
        self._state.request_full_apply(node)
        # The slab timings of the image just finished say nothing about this one.
        self._applySlab = 0
        self._applySlabTotal = 0
        self._applyFirstSlabTime = None
        self._applyImageStartTime = time.time()
        size, memory = self._imageSizeText(node)
        self._logApply(
            APPLY_LOG_STARTING.format(prefix=self._applyLogPrefix(), image=node.GetName(), size=size, memory=memory)
        )

    def _onFullSegmentationComplete(self, final_result_node, input_node):
        final_result_node.SetName(slicer.mrmlScene.GenerateUniqueName(f"{input_node.GetName()}_Segmented"))
        elapsed = _elapsed_text(time.time() - self._applyImageStartTime)
        self._logApply(APPLY_LOG_DONE.format(elapsed=elapsed, result=final_result_node.GetName()))

        # Only the last result is shown: overlapping results from a batch run would
        # otherwise all be drawn on top of each other.
        self._revealResultNode(final_result_node, visible=not self._applyQueue)

        if self._applyQueue:
            self._applyNextInQueue()
            return

        # A single image already reported its own time on the line above; only a
        # batch has a total that is not just a repeat of it.
        if self._applyTotal > 1:
            batch_elapsed = _elapsed_text(time.time() - self._applyStartTime)
            self._logApply(APPLY_LOG_FINISHED_BATCH.format(total=self._applyTotal, elapsed=batch_elapsed))
        else:
            self._logApply(APPLY_LOG_FINISHED)
        self._applyLogHeaderLabel.text = APPLY_LOG_HEADER_DONE
        self._stopSegmentation()
        slicer.util.setSliceViewerLayers(background=input_node, fit=True)
        self._onStatusUpdate(STATUS_APPLIED.format(image=input_node.GetName()), show_progress=False)

    @staticmethod
    def _revealResultNode(final_result_node, visible):
        """Take the finished result out of the preview-only view it was computed in."""
        displayNode = final_result_node.GetDisplayNode()
        if displayNode:
            displayNode.SetVisibility(visible)
            displayNode.SetDisplayableOnlyInView(None)

        previewDisplayNode = final_result_node.GetNthDisplayNode(1)
        if previewDisplayNode:
            final_result_node.RemoveNthDisplayNodeID(1)
            # Can't remove node, otherwise a crash occurs later in vtkMRMLSegmentationsDisplayableManager3D::ProcessMRMLNodesEvents
            # slicer.mrmlScene.RemoveNode(previewDisplayNode)

    def _switchToCropModule(self):
        slicer.util.selectModule("CustomizedCropVolume")
        slicer.app.processEvents(1000)
        volume = self._inputSelector.currentNode()
        cropWidget = slicer.modules.CustomizedCropVolumeWidget
        cropWidget.volumeComboBox.setCurrentNode(volume)
        slicer.app.processEvents(1000)
        cropWidget.logic.setRoiSizeIjk(volume, (500, 500, 500))
        self._inputSelector.setCurrentNode(None)
