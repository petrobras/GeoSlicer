import os
import re
from pathlib import Path

import vtk, qt, ctk, slicer
from slicer import util
import logging
from scipy import ndimage
import numpy as np
from skimage.segmentation import watershed
from skimage.morphology import disk
import cv2
import pandas as pd
import pyedt

from porespy.filters import reduce_peaks, find_peaks, trim_saddle_points, trim_nearby_peaks
from ltrace.algorithms.common import get_two_highest_peaks, points_are_below_line
from ltrace.algorithms.partition import runPartitioning
from ltrace.slicer import helpers
from ltrace.slicer import ui
from ltrace.slicer.helpers import (
    generateName,
    clone_volume,
    get_subject_hierarchy_siblings,
    getCountForLabels,
    createOutput,
    createTemporaryNode,
    in_image_log_environment,
    make_labelmap_sequential,
    removeTemporaryNodes,
    makeTemporaryNodePermanent,
    isTemporaryNode,
    tryGetNode,
    create_color_table,
    autoDetectColumnType,
    rand_cmap,
    getOverlappingSlices,
)
from ltrace.slicer.throat_analysis.throat_analysis_generator import ThroatAnalysisGenerator
from ltrace.slicer_utils import (
    dataFrameToTableNode,
    LTracePlugin,
    slicer_is_in_developer_mode,
    LTracePluginWidget,
    LTracePluginLogic,
)
from ltrace.slicer.undo import manager
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.slicer.widget.status_panel import StatusPanel
from ltrace.utils.Markup import MarkupFiducial, MarkupLine

# -*- extra imports -*-


#
# LabelMapEditor
#


class LabelMapEditor(LTracePlugin):
    SETTING_KEY = "LabelMapEditor"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        super().__init__(parent)
        self.parent.title = "Label Map Editor"
        self.parent.categories = ["Segmentation", "MicroCT", "Thin Section", "ImageLog", "Core"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = LabelMapEditor.help()
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = """
    Developed by LTrace Geophysics Solutions
"""

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


#
# LabelMapEditorWidget
#
class LabelMapEditorWidget(LTracePluginWidget):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.cliNode = None
        self.markup = None
        self.edition_labelmap = None
        self.labelmapGenerated = lambda labelmapId: None
        self.__throat_analysis_generator = None
        self.__in_debug_mode = False

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = LabelMapEditorLogic()

        #
        # Input volume selector
        #
        input_collapsible = ctk.ctkCollapsibleButton()
        input_collapsible.collapsed = False
        input_collapsible.text = "Input"
        input_layout = qt.QFormLayout(input_collapsible)
        self.input_collapsible = input_collapsible

        self.input_selector = ui.hierarchyVolumeInput(
            onChange=self.on_input_node_changed,
            hasNone=True,
            nodeTypes=["vtkMRMLLabelMapVolumeNode"],
        )
        self.input_selector.setMRMLScene(slicer.mrmlScene)
        self.input_selector.setToolTip("Pick a labeled volume node")

        input_layout.addRow(qt.QLabel("Labelmap"), self.input_selector)
        self.previous_input_node = None
        self.layout.addWidget(input_collapsible)

        #
        # Parameters
        #
        parameters_collapsible = ctk.ctkCollapsibleButton()
        parameters_collapsible.collapsed = False
        parameters_collapsible.text = "Parameters"
        parameters_layout = qt.QVBoxLayout(parameters_collapsible)

        # Status display
        self.status_panel = StatusPanel("Instruction")
        parameters_layout.addWidget(self.status_panel)

        # Tool buttons
        tools_group = qt.QGroupBox("Label tools")
        tools_frame = qt.QFrame()
        tools_grid = qt.QGridLayout(tools_frame)
        self.hold_tool_checkbox = qt.QCheckBox("Hold operation for next edition")
        self.hold_tool_checkbox.setChecked(False)
        self.merge_button = qt.QPushButton("Merge")
        self.auto_split_button = qt.QPushButton("Auto Split")
        self.slice_button = qt.QPushButton("Slice")
        self.point_cut_button = qt.QPushButton("Point cut")
        self.cancel_button = qt.QPushButton("Cancel")
        tools_grid.addWidget(self.hold_tool_checkbox, 0, 0, 1, 4)
        tools_grid.addWidget(self.merge_button, 1, 0)
        tools_grid.addWidget(self.auto_split_button, 1, 1)
        tools_grid.addWidget(self.slice_button, 1, 2)
        tools_grid.addWidget(self.point_cut_button, 1, 3)
        tools_grid.addWidget(self.cancel_button, 2, 0, 1, 4)
        tools_group.setLayout(tools_grid)
        parameters_layout.addWidget(tools_group)

        # Undo/redo
        action_group = qt.QGroupBox("Action")
        action_frame = qt.QFrame()
        action_grid = qt.QHBoxLayout(action_frame)
        self.undo_button = qt.QPushButton("Undo")
        self.redo_button = qt.QPushButton("Redo")
        action_grid.addWidget(self.undo_button)
        action_grid.addWidget(self.redo_button)
        action_group.setLayout(action_grid)
        parameters_layout.addWidget(action_group)

        self.merge_button.connect("clicked()", self.on_merge_button_clicked)
        self.auto_split_button.connect("clicked()", self.on_auto_split_button_clicked)
        self.slice_button.connect("clicked()", self.on_slice_button_clicked)
        self.point_cut_button.connect("clicked()", self.on_point_cut_button_clicked)
        self.cancel_button.connect("clicked()", self.on_cancel_button_clicked)
        self.undo_button.connect("clicked()", self.on_undo_button_clicked)
        self.redo_button.connect("clicked()", self.on_redo_button_clicked)

        self.layout.addWidget(parameters_collapsible)

        #
        # Saving
        #
        output_collapsible = ctk.ctkCollapsibleButton()
        output_collapsible.collapsed = False
        output_collapsible.text = "Output"
        self.output_collapsible = output_collapsible
        output_layout = qt.QFormLayout(output_collapsible)

        # Saving group box
        self.throat_analysis_checkbox = qt.QCheckBox("Perform throat analysis")
        self.throat_analysis_checkbox.setChecked(True)
        self.output_prefix_selector = qt.QLineEdit("Edited")
        self.output_prefix_selector.setText("")
        self.output_prefix_selector.enabled = False

        output_layout.addRow(self.throat_analysis_checkbox)
        output_layout.addRow("Output prefix: ", self.output_prefix_selector)

        self.tool_buttons = [
            self.merge_button,
            self.auto_split_button,
            self.slice_button,
            self.point_cut_button,
            self.undo_button,
            self.redo_button,
        ]

        self.layout.addWidget(output_collapsible)

        self.applyCancelButtons = ui.ApplyCancelButtons(
            onApplyClick=self.on_save_button_clicked,
            onCancelClick=self.on_cancel_saving_button_clicked,
            applyTooltip="Save",
            cancelTooltip="Cancel",
            applyText="Save",
            cancelText="Cancel",
            enabled=True,
            applyObjectName="saveLabelMapButton",
            cancelObjectName=None,
        )

        # Progress bar
        self.progress_bar = LocalProgressBar()
        self.progress_update = lambda value: None

        self.layout.addWidget(self.applyCancelButtons)
        self.layout.addWidget(self.progress_bar)

        # Add vertical spacer
        self.layout.addStretch(1)

        # Defining shortcuts
        self.shortcuts = {
            qt.QShortcut(qt.QKeySequence(qt.Qt.Key_M), util.mainWindow()): self.on_merge_button_clicked,
            qt.QShortcut(qt.QKeySequence(qt.Qt.Key_A), util.mainWindow()): self.on_auto_split_button_clicked,
            qt.QShortcut(qt.QKeySequence(qt.Qt.Key_S), util.mainWindow()): self.on_slice_button_clicked,
            qt.QShortcut(qt.QKeySequence(qt.Qt.Key_C), util.mainWindow()): self.on_point_cut_button_clicked,
            qt.QShortcut(qt.QKeySequence(qt.Qt.Key_Z), util.mainWindow()): self.on_undo_button_clicked,
            qt.QShortcut(qt.QKeySequence(qt.Qt.Key_X), util.mainWindow()): self.on_redo_button_clicked,
        }
        self._set_shortcuts_connected(True)
        self._enable_shortcuts(False)
        self.interaction_in_progress = False
        slicer.mrmlScene.SetUndoOn()

    def _enable_controls(self, enable):
        self._enable_tool_buttons(enable)
        self._enable_shortcuts(enable)

    def _enable_tool_buttons(self, enable):
        for button in self.tool_buttons:
            button.setEnabled(enable)

    def _set_shortcuts_connected(self, connect):
        if connect:
            for key, callback in self.shortcuts.items():
                key.connect("activated()", callback)
        else:
            for key, callback in self.shortcuts.items():
                key.activated.disconnect()

    def _enable_shortcuts(self, enable):
        for key, callback in self.shortcuts.items():
            key.setEnabled(enable)

    def enter(self) -> None:
        super().enter()
        self._unset_markup()
        self._enable_controls(True)

    def exit(self):
        self.on_cancel_button_clicked()
        self._unset_markup()
        self._enable_controls(False)

    def reload(self):
        self.connect_shortcuts(False)
        super().reload()

    def reload(self):
        self._set_shortcuts_connected(False)
        super().reload()

    def _unset_markup(self):
        if self.markup is not None:
            del self.markup
            self.markup = None

    def on_save_button_clicked(self):
        try:
            input_node = self.input_selector.currentNode()
            edited_labelmap_node = self.edition_labelmap
            output_prefix = self.output_prefix_selector.text

            if not input_node:
                slicer.util.errorDisplay("No input node selected", windowTitle="Parameter error")
                return

            if len(output_prefix) == 0:
                slicer.util.errorDisplay("No output suffix given", windowTitle="Parameter error")
                return

            edited_labelmap_node.SetName(output_prefix)
            make_labelmap_sequential(edited_labelmap_node)

            self.input_selector.setCurrentNode(None)
            util.setSliceViewerLayers(background=None, foreground=None, label=edited_labelmap_node, fit=True)

            tree_node = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
            item_id_in_tree = tree_node.GetItemByDataNode(edited_labelmap_node)
            parent_item_id = tree_node.GetItemParent(item_id_in_tree)

            label_indices = np.unique(util.arrayFromVolume(edited_labelmap_node))
            labels = dict(zip(label_indices, label_indices))  # labels must be in dict format

            params = {
                "method": None,
                "generate_throat_analysis": self.throat_analysis_checkbox.isChecked(),
            }

            if params.get("generate_throat_analysis", False) == True:
                self.__throat_analysis_generator = ThroatAnalysisGenerator(
                    input_node_id=None,
                    base_name=output_prefix + "_{type}",
                    hierarchy_folder=parent_item_id,
                    direction=params.get("direction", None),
                )
                self.__throat_analysis_generator.create_output_nodes()

                params["throatOutputReport"] = self.__throat_analysis_generator.throat_table_output_path
                params["throatOutputLabelVolume"] = self.__throat_analysis_generator.throat_label_map_node_id

            self.cliNode, resultInfo = runPartitioning(
                labelMapNode=edited_labelmap_node,
                labels=labels,
                outputPrefix=output_prefix + "_{type}",
                params=params,
                currentDir=parent_item_id,
                create_output=True,
                saveTo=params.get("saveTo", None),
                inputNode=input_node,
                checkPercent=False,
            )
            # Avoid multiple clicks at the Save button
            self.applyCancelButtons.applyBtn.setEnabled(False)
            self.progress_bar.setCommandLineModuleNode(self.cliNode)

            self.cliNode.AddObserver("ModifiedEvent", lambda c, ev, p=resultInfo: self.eventHandler(c, ev, p))

            edited_labelmap_node.SetHideFromEditors(False)
        except RuntimeError as e:
            print(f"An error occurred: {e}")

    def on_cancel_saving_button_clicked(self):
        if self.cliNode is None:
            return  # nothing running, nothing to do
        self.cliNode.Cancel()

    def format_markups(self, *args, **kwargs):
        if hasattr(self, "markup"):
            if self.markup is not None:
                self.markup.format_markups(*args, **kwargs)

    def get_markup_kji_indices(self, markups, volume_node):
        ijkPoints = markups.get_selected_ijk_points(volume_node)
        # return tuple(ijkPoints.T[::-1])
        return tuple(map(tuple, ijkPoints.T[::-1]))

    def get_markup_kji_index(self, markups, volume_node, point=0):
        ijkPoints = markups.get_selected_ijk_points(volume_node)
        ijkPoint = ijkPoints[point]
        return tuple(ijkPoint[::-1])

    def get_all_view_node_ids(self):
        view_node_ids = []
        layout_manager = slicer.app.layoutManager()
        # 3D views
        for threed_view_index in range(layout_manager.threeDViewCount):
            view_widget = layout_manager.threeDWidget(threed_view_index)
            view = view_widget.threeDView()
            view_node_ids.append(view.mrmlViewNode().GetID())
        # slice views
        for view_name in layout_manager.sliceViewNames():
            view_widget = layout_manager.sliceWidget(view_name)
            view = view_widget.sliceView()
            view_node_ids.append(view.mrmlSliceNode().GetID())
        return view_node_ids

    def get_views(self, including_volume=None):
        view_node_ids = []
        if including_volume:
            view_node_ids += [*including_volume.GetDisplayNode().GetViewNodeIDs()]
        if len(view_node_ids) == 0:
            # then volume is visible in all views and get all all views anyway
            view_node_ids += self.get_all_view_node_ids()

        layout_manager = slicer.app.layoutManager()
        volume_views = []
        for view_node_id in view_node_ids:
            view_node = slicer.util.getNode(view_node_id)
            if isinstance(view_node, slicer.vtkMRMLViewNode):  # 3D views
                view_widget = layout_manager.viewWidget(view_node)
                view = view_widget.threeDView()
                volume_views.append(view)
            elif isinstance(view_node, slicer.vtkMRMLSliceNode):  # slice views
                view_name = view_node.GetLayoutName()
                view_widget = layout_manager.sliceWidget(view_name)
                view = view_widget.sliceView()
                volume_views.append(view)
        return volume_views

    def set_cursor_for_views(self, views, cursor):
        for view in views:
            view.setCursor(cursor)

    def unset_cursor_for_views(self, views):
        for view in views:
            view.unsetCursor()

    def on_slice_button_clicked(self):
        self._unset_markup()

        if not self.__check_volume_selected():
            return

        edited_node = self.edition_labelmap
        self.required_control_points = 2

        def update_instruction(caller_markup, point_index=None):
            self.status_panel.set_instruction(f"Click on two points to draw the cutting line")

        def pick_criterion(caller_markup, point_index=None):
            return True

        def finish_criterion(caller_markup, point_index=None):
            return caller_markup.get_number_of_selected_points() >= self.required_control_points

        def finish_callback(caller_markup, point_index=None):
            self.status_panel.unset_instruction()

            coords_ijk = self.markup.get_selected_ijk_points(as_int=False)

            if np.allclose(np.round(coords_ijk[0]), np.round(coords_ijk[1])):
                self.status_panel.set_instruction(f"Line extremes must differ", important=True)
                return

            qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
            try:
                array = slicer.util.arrayFromVolume(edited_node)
                coords_kji = coords_ijk[:, ::-1]

                # determining label to be cut
                middle = np.round(np.mean(coords_kji, axis=0)).astype(int)
                difference = np.diff(coords_kji, axis=0)
                max_dist = np.ceil(np.sqrt(np.sum(np.square(difference))))

                search_rect = np.empty((2, 3), dtype=int)

                search_start, search_end = search_rect
                search_start[...] = middle - max_dist // 2
                search_end[...] = search_start + max_dist

                search_rect[:, 0] = np.clip(search_rect[:, 0], 0, array.shape[0])
                search_rect[:, 1] = np.clip(search_rect[:, 1], 0, array.shape[1])
                search_rect[:, 2] = np.clip(search_rect[:, 2], 0, array.shape[2])

                search_bbox = np.s_[
                    search_rect[0, 0] : search_rect[1, 0],
                    search_rect[0, 1] : search_rect[1, 1],
                    search_rect[0, 2] : search_rect[1, 2],
                ]

                search_array = array[search_bbox]
                search_middle = middle - search_rect[0]

                search_indices = np.c_[search_array.nonzero()]
                if search_indices.size == 0:
                    self.status_panel.set_instruction(f"Could not cut label", important=True)
                else:
                    middle_distances = np.sqrt(np.sum(np.square(search_indices - search_middle), axis=-1))
                    idx_min_distance = np.argmin(middle_distances)

                    # nearest label
                    label = search_array[tuple(search_indices[idx_min_distance])]

                    # splitting label
                    modified_bbox = ndimage.find_objects(array == label)[0]
                    modified_array = array[modified_bbox].copy()

                    idx_label = np.c_[(modified_array == label).nonzero()]

                    bbox_start = np.asarray([idx.start for idx in modified_bbox])[None, :]
                    coords_kji_in_bbox = coords_kji - bbox_start

                    is_below_line = points_are_below_line(coords_kji_in_bbox[:, 1:], idx_label[:, 1:])
                    idx_below_line = tuple(idx_label[is_below_line].T)

                    if 0 < sum(is_below_line) < len(is_below_line):
                        second_label = self.get_unused_label(edited_node)
                        modified_array[idx_below_line] = second_label
                        manager.modify_and_save(edited_node, modified_array, bbox_slices=modified_bbox)
                    else:
                        self.status_panel.set_instruction(f"Could not cut label", important=True)
            except Exception as e:
                logging.warning(e)
            qt.QApplication.restoreOverrideCursor()

        def cancel_callback():
            self.status_panel.unset_instruction()
            self._enable_controls(True)

        def after_finish_callback():
            if self.hold_tool_checkbox.checked:
                self._set_timer(self.on_slice_button_clicked)
            self._enable_controls(True)

        self.markup = MarkupLine(
            finish_callback,
            finish_criterion=finish_criterion,
            pick_criterion=pick_criterion,
            update_instruction=update_instruction,
            cancel_callback=cancel_callback,
            after_finish_callback=after_finish_callback,
            parent=self.parent,
        )
        self.format_markups(disable_text=True)
        self.markup.start_picking()
        self._enable_controls(False)

    def _set_timer(self, callback, delay=20):
        qt.QTimer.singleShot(delay, callback)

    def on_merge_button_clicked(self):
        self._unset_markup()

        if not self.__check_volume_selected():
            return

        edited_node = self.edition_labelmap
        self.required_control_points = 2

        def update_instruction(caller_markup, point_index=None):
            current_control_points = caller_markup.get_number_of_selected_points()
            points_left_to_pick = self.required_control_points - current_control_points
            if points_left_to_pick > 1:
                self.status_panel.set_instruction(f"Click on two labels to merge them")
            else:
                self.status_panel.set_instruction(f"Click on a second label to merge")
            if current_control_points == 0:
                self.format_markups("First label")
            else:
                self.format_markups("Last label")

        def pick_criterion(caller_markup, point_index=None):
            ijk_point = caller_markup.get_ijk_point_position(point_index)
            label = int(edited_node.GetImageData().GetScalarComponentAsDouble(*ijk_point, 0))
            return label != 0

        def finish_criterion(caller_markup, point_index=None):
            return caller_markup.get_number_of_selected_points() >= self.required_control_points

        def finish_callback(caller_markup, point_index=None):
            self.status_panel.unset_instruction()

            markup_indices = self.get_markup_kji_indices(caller_markup, edited_node)
            array = slicer.util.arrayFromVolume(edited_node)
            labels = array[markup_indices]

            if np.any(labels == 0):  # no background label joins
                return

            qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
            try:
                modifiedArray = np.where(array == labels[0], labels[1], array)
                modifiedSlice = ndimage.find_objects((array == labels[0]) | (array == labels[0]))[0]
                manager.modify_and_save(edited_node, modifiedArray[modifiedSlice], bbox_slices=modifiedSlice)
            except Exception as e:
                logging.warning(e)
            qt.QApplication.restoreOverrideCursor()

        def after_finish_callback():
            if self.hold_tool_checkbox.checked:
                self._set_timer(self.on_merge_button_clicked)
            self._enable_controls(True)

        def cancel_callback():
            self.status_panel.unset_instruction()
            self._enable_controls(True)

        self.markup = MarkupFiducial(
            finish_callback,
            finish_criterion=finish_criterion,
            pick_criterion=pick_criterion,
            update_instruction=update_instruction,
            cancel_callback=cancel_callback,
            after_finish_callback=after_finish_callback,
            parent=self.parent,
        )

        self.markup.start_picking()
        self._enable_controls(False)

    def on_auto_split_button_clicked(self):
        self._unset_markup()

        if not self.__check_volume_selected():
            return

        edited_node = self.edition_labelmap
        self.required_control_points = 1

        def update_instruction(caller_markup, point_index=None):
            self.status_panel.set_instruction("Click on a label to split it")
            self.format_markups("Label to split")

        def pick_criterion(caller_markup, point_index=None):
            ijk_point = caller_markup.get_ijk_point_position(point_index)
            label = int(edited_node.GetImageData().GetScalarComponentAsDouble(*ijk_point, 0))
            return label != 0

        def finish_criterion(caller_markup, point_index=None):
            return caller_markup.get_number_of_selected_points() >= self.required_control_points

        def finish_callback(caller_markup, point_index):
            self.status_panel.unset_instruction()

            markup_index = self.get_markup_kji_index(caller_markup, edited_node)
            array = slicer.util.arrayFromVolume(edited_node)
            label = array[markup_index]

            if label == 0:  # no background label
                return

            qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
            try:
                modified = self.inplace_watershed(edited_node, label)
                if not modified:
                    self.status_panel.set_instruction("Label could not be split", important=True)
            except Exception as e:
                logging.warning(e)
            qt.QApplication.restoreOverrideCursor()

        def cancel_callback():
            self.status_panel.unset_instruction()
            self._enable_controls(True)

        def after_finish_callback():
            if self.hold_tool_checkbox.checked:
                self._set_timer(self.on_auto_split_button_clicked)
            self._enable_controls(True)

        self.markup = MarkupFiducial(
            finish_callback,
            finish_criterion=finish_criterion,
            pick_criterion=pick_criterion,
            update_instruction=update_instruction,
            cancel_callback=cancel_callback,
            after_finish_callback=after_finish_callback,
        )
        self.markup.start_picking()
        self._enable_controls(False)

    def inplace_watershed(self, volume_node, label):
        array = slicer.util.arrayFromVolume(volume_node)
        bbox = ndimage.find_objects(array)[label - 1]
        label_array = array[bbox] == label
        dt = pyedt.edt(label_array[0, :, :], force_method="cpu", closed_border=True)
        peaks = find_peaks(dt=dt)
        peaks = reduce_peaks(peaks)
        peaks = trim_saddle_points(peaks=peaks, dt=dt)
        peaks = trim_nearby_peaks(peaks=peaks, dt=dt, f=2)
        first_peak, second_peak = get_two_highest_peaks((peaks * dt).astype(np.uint16))
        peaks = np.zeros(peaks.shape, dtype=np.uint8)
        peaks[first_peak[1], first_peak[2]] = 1
        peaks[second_peak[1], second_peak[2]] = 2
        regions = watershed(image=-dt, markers=peaks, mask=dt > 0)[np.newaxis, ...]
        second_label = self.get_unused_label(volume_node)
        modified_array = np.where(regions == 1, label, array[bbox])
        modified_array = np.where(regions == 2, second_label, array[bbox])
        modified = np.any(array[bbox] != modified_array)
        if modified:
            manager.modify_and_save(volume_node, modified_array, bbox_slices=bbox)
        return modified

    def on_point_cut_button_clicked(self):
        self._unset_markup()

        if not self.__check_volume_selected():
            return
        edited_node = self.edition_labelmap
        self.required_control_points = 1

        def update_instruction(caller_markup, point_index=None):
            self.status_panel.set_instruction("Click on a specific point to split the label")
            self.format_markups("Split point")

        def pick_criterion(caller_markup, point_index=None):
            ijk_point = caller_markup.get_ijk_point_position(point_index)
            label = int(edited_node.GetImageData().GetScalarComponentAsDouble(*ijk_point, 0))
            return label != 0

        def finish_criterion(caller_markup, point_index=None):
            return caller_markup.get_number_of_selected_points() >= self.required_control_points

        def finish_callback(caller_markup, point_index):
            self.status_panel.unset_instruction()

            markup_index = self.get_markup_kji_index(caller_markup, edited_node)
            array = slicer.util.arrayFromVolume(edited_node)
            label = array[markup_index]

            if label == 0:
                return

            qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
            try:
                bbox = ndimage.find_objects(array)[label - 1]
                cut_array = np.where(array[bbox] == label, 1, 0)
                x = markup_index[2] - bbox[2].start
                y = markup_index[1] - bbox[1].start
                cut_array = self.split_at_point(cut_array, (x, y))
                second_label = self.get_unused_label(edited_node)
                modified_array = np.where(cut_array == 1, label, array[bbox])
                modified_array = np.where(cut_array == 2, second_label, modified_array)

                modified = np.any(array[bbox] != modified_array)
                if modified:
                    manager.modify_and_save(edited_node, modified_array, bbox_slices=bbox)
                if not modified:
                    self.status_panel.set_instruction("Label could not be cut", important=True)
            except Exception as e:
                logging.warning(e)
            qt.QApplication.restoreOverrideCursor()

        def cancel_callback():
            self.status_panel.unset_instruction()
            self._enable_controls(True)

        def after_finish_callback():
            if self.hold_tool_checkbox.checked:
                self._set_timer(self.on_point_cut_button_clicked)
            self._enable_controls(True)

        self.markup = MarkupFiducial(
            finish_callback,
            finish_criterion=finish_criterion,
            pick_criterion=pick_criterion,
            update_instruction=update_instruction,
            cancel_callback=cancel_callback,
            after_finish_callback=after_finish_callback,
        )
        self.markup.start_picking()
        self._enable_controls(False)

    def on_undo_button_clicked(self):
        edited_node = self.edition_labelmap
        manager.undo(edited_node)

    def on_redo_button_clicked(self):
        edited_node = self.edition_labelmap
        manager.redo(edited_node)

    def on_cancel_button_clicked(self):
        if self.markup:
            self.markup.cancel_picking()

    def eventHandler(self, caller, event, params):
        if caller is None:
            return

        try:
            if caller.GetStatusString() == "Completed":
                self.cliNode.RemoveAllObservers()
                self.cliNode = None

                self.progress_update(0)

                folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

                outputDir = folderTree.CreateFolderItem(params.currentDir, generateName(folderTree, "Label Editor"))

                if params.outputReport:
                    reportNode = params.reportNode
                    if reportNode:
                        makeTemporaryNodePermanent(reportNode, show=True)
                        helpers.moveNodeTo(outputDir, reportNode, dirTree=folderTree)
                        reportNode.SetAttribute("ReferenceVolumeNode", params.outputVolume)
                        autoDetectColumnType(reportNode)

                        if params.params.get("generate_throat_analysis") == True:
                            self.__throat_analysis_generator.handle_process_completed()

                            throatTableNode = tryGetNode(self.__throat_analysis_generator.throat_table_node_id)
                            throatLabelMapNode = tryGetNode(self.__throat_analysis_generator.throat_label_map_node_id)

                            helpers.moveNodeTo(outputDir, throatTableNode, dirTree=folderTree)
                            helpers.moveNodeTo(
                                outputDir,
                                throatLabelMapNode,
                                dirTree=folderTree,
                            )

                            del self.__throat_analysis_generator
                            self.__throat_analysis_generator = None

                        dpath = Path(params.outputReport)
                        if dpath.exists():
                            df = pd.read_pickle(str(params.outputReport))
                            dataFrameToTableNode(df, tableNode=reportNode)
                            dpath.unlink(missing_ok=True)

                self.progress_update(0.5)

                if params.outputVolume:
                    resultNode = tryGetNode(params.outputVolume)
                    if resultNode:
                        helpers.moveNodeTo(outputDir, resultNode, dirTree=folderTree)
                        makeTemporaryNodePermanent(resultNode, show=True)
                        nsegments = int(caller.GetParameterAsString("number_of_partitions"))

                        colors = rand_cmap(nsegments)
                        color_names = [str(i) for i in range(1, nsegments + 1)]
                        colorTableNode = create_color_table(
                            f"{resultNode.GetName()}_ColorMap",
                            colors=colors,
                            color_names=color_names,
                            add_background=True,
                        )

                        resultNode.GetDisplayNode().SetAndObserveColorNodeID(colorTableNode.GetID())
                        self.labelmapGenerated(resultNode.GetID())

                self.progress_update(0.9)

                self._createRunStats(
                    params.sourceLabelMapNode,
                    params.targetLabels,
                    params.params,
                    roiNode=None,
                    where=outputDir,
                    prefix=params.outputPrefix,
                )
                if in_image_log_environment():
                    image_log_env = slicer.modules.imagelogenv.widgetRepresentation()
                    if image_log_env.visible:
                        image_log_env.self().imageLogDataWidget.self().logic.refreshViews()

        except Exception as e:
            logging.warning(repr(e))
        finally:
            if not caller.IsBusy():
                removeTemporaryNodes()
                self.progress_update(1.0)
                self.applyCancelButtons.applyBtn.setEnabled(True)

    def _createRunStats(self, inputNode, labels, params, roiNode=None, prefix="", where=None):
        """
        Creates a TableNode with run information
        """
        inputVoxelArray = util.arrayFromVolume(inputNode)
        shape = inputVoxelArray.shape
        spacing = np.array(inputNode.GetSpacing())[np.where(shape != 1)]
        vixel_dim_tag = "Volume (mm^3)" if len(spacing) > 2 else "Area (mm^2)"
        voxel_size = np.prod(spacing)

        segmentmap = getCountForLabels(inputNode, roiNode)

        totalVoxelCount = segmentmap["total"]
        del segmentmap["total"]
        segmentVoxelCount = sum([segmentmap[k]["count"] for k in segmentmap])

        data = {
            f"Pixel {vixel_dim_tag}": voxel_size,
            "ROI Voxel Count (#px)": totalVoxelCount,
            "Segment Voxel Count (#px)": segmentVoxelCount,
        }

        for idx in segmentmap:
            count = segmentmap[idx]["count"]
            if count == 0:
                continue
            data[f"{labels[idx]} [{idx}] (#px) "] = count
            data[f"{labels[idx]} [{idx}] (%) "] = np.round(count * 100 / totalVoxelCount, decimals=5)
            if int(totalVoxelCount) != int(segmentVoxelCount):
                data[f"{labels[idx]} [{idx}] (% within segmentation) "] = np.round(
                    count * 100 / segmentVoxelCount, decimals=5
                )

        data["Method:"] = params["method"]
        data.update({f"parameter.{key}": params[key] for key in params if key != "method"})

        variables_node = createOutput(
            prefix=prefix,
            ntype="Variables",
            where=where,
            builder=lambda n, hidden=True: createTemporaryNode(slicer.vtkMRMLTableNode, n, hidden=False),
        )

        df = pd.DataFrame(
            data={"Properties": [key for key in data], "Values": [repr(val) for val in data.values()]}, dtype=str
        )

        dataFrameToTableNode(df, tableNode=variables_node)
        makeTemporaryNodePermanent(variables_node, show=True)

    def get_edition_labelmaps(self, edition_name):
        pattern = re.compile("^" + edition_name + "_?\\d*$")
        nodes = slicer.util.getNodes()
        return [node for i, node in nodes.items() if pattern.match(node.GetName())]

    def on_input_node_changed(self, node_id):
        self.edition_labelmap = None

        input_node = self.input_selector.currentNode()

        if input_node is None:
            self.previous_input_node = None
            self.output_prefix_selector.setText("")
            self.output_prefix_selector.enabled = False
            return

        final_labelmap_name = input_node.GetName() + "_Edited"
        self.output_prefix_selector.setText(final_labelmap_name)
        self.output_prefix_selector.enabled = True

        # TODO é preciso rever essa logica de busca (ou vem um ou vem varios - overuse do loop), pelo menos um break ali depois que encontrar
        edition_labelmap_name = input_node.GetName() + "_Edition"
        edition_labelmaps = self.get_edition_labelmaps(edition_labelmap_name)
        for edition_labelmap in edition_labelmaps:
            if isTemporaryNode(edition_labelmap):
                self.edition_labelmap = edition_labelmap

        if not self.edition_labelmap:
            logging.info(f"No temporary node found, creating and using {edition_labelmap_name}")
            self.edition_labelmap = clone_volume(input_node, edition_labelmap_name, copy_names=False)
            self.input_selector.selectorWidget.sortFilterProxyModel().invalidateFilter()

        self.edition_labelmap.SetHideFromEditors(True)

        try:
            manager.start_managing(self.edition_labelmap, verify=False)
        except ValueError as e:
            logging.info(e)
        util.setSliceViewerLayers(background=None, foreground=None, label=self.edition_labelmap, fit=True)

        self.previous_input_node = input_node

        # enabling throat analysis by context
        sibling_nodes = get_subject_hierarchy_siblings(input_node)
        make_throat_analysis = any(n.GetName().endswith("Throat_Report") for n in sibling_nodes)
        current_selection = self.throat_analysis_checkbox.isChecked()
        self.throat_analysis_checkbox.setChecked(current_selection | make_throat_analysis)

    def split_at_point(self, array, point):
        array_copy = array.copy()
        i = 2
        while True:
            footprint = (1 - disk(i))[np.newaxis, ...]
            slice_one, slice_two = getOverlappingSlices(
                array_copy.shape, footprint.shape, (0, point[1] - i, point[0] - i)
            )
            array_copy[slice_one] *= footprint[slice_two]
            N = ndimage.label(array_copy, structure=np.ones((3, 3, 3), dtype=np.uint8), output=array_copy)
            if N == 0:
                logging.warning("Failed to split at location")
                root = os.getcwd()
                if slicer_is_in_developer_mode() and self.__in_debug_mode:
                    cv2.imwrite(os.path.join(root, "array_copy.png"), array_copy.transpose())
                return None
            elif N >= 2:
                if N > 2:
                    array_copy = np.where(array_copy > 2, 2, array_copy)
                root = os.getcwd()
                dt = array.copy()
                if slicer_is_in_developer_mode() and self.__in_debug_mode:
                    cv2.imwrite(os.path.join(root, "dt_1.png"), dt.transpose())
                dt[0, point[1], point[0]] = 0

                if slicer_is_in_developer_mode() and self.__in_debug_mode:
                    cv2.imwrite(os.path.join(root, "dt_2.png"), dt.transpose())
                dt = pyedt.edt(dt, force_method="cpu", closed_border=True)
                if slicer_is_in_developer_mode() and self.__in_debug_mode:
                    cv2.imwrite(os.path.join(root, "dt_3.png"), dt.transpose())
                dt[0, point[1], point[0]] = 1
                regions = watershed(image=dt, markers=array_copy, mask=dt > 0)
                if slicer_is_in_developer_mode() and self.__in_debug_mode:
                    cv2.imwrite(os.path.join(root, "array_copy.png"), array_copy.transpose())
                    cv2.imwrite(os.path.join(root, "dt.png"), dt.transpose())
                    cv2.imwrite(os.path.join(root, "regions.png"), regions.transpose())
                return regions
            i *= 2

    def get_unused_label(self, labelmap_node, create=True):
        color_node = labelmap_node.GetDisplayNode().GetColorNode()
        number_of_colors = color_node.GetNumberOfColors()
        new_label = number_of_colors
        if create:
            color = rand_cmap(1)[0]
            color_node.SetNumberOfColors(number_of_colors + 1)  # allocate next color
            color_node.SetColor(new_label, *color)
        return new_label

    def cleanup(self):
        pass

    def delete_node(self, node):
        node.UndoEnabledOff()
        slicer.mrmlScene.ClearUndoStack()
        slicer.mrmlScene.RemoveNode(node)
        slicer.mrmlScene.ClearRedoStack()

    def __check_volume_selected(self):
        if not self.edition_labelmap:
            self.status_panel.set_instruction(f"Please, select an input label map", True)
            return False
        return True


#
# LabelMapEditorLogic
#


class LabelMapEditorLogic(LTracePluginLogic):
    def run(self):
        pass
