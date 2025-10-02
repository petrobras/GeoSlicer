from ltrace.image.core_box.core_boxes_image_file import CoreBoxesImageFile
from ltrace.slicer.helpers import createTemporaryNode, tryGetNode, getTesseractCmd, save_path
from ltrace.slicer_utils import (
    LTracePlugin,
    LTracePluginLogic,
    LTracePluginWidget,
    addNodeToSubjectHierarchy,
    is_tensorflow_gpu_enabled,
)
from ltrace.slicer.cli_queue import CliQueue
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar
from ltrace.utils.callback import Callback
from pathlib import Path

import ctk
import glob
import json
import logging
import os
import qt
import slicer


class CorePhotographLoader(LTracePlugin):
    SETTING_KEY = "CorePhotographLoader"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Core Photograph Loader"  # TODO make this more human readable by adding spaces
        self.parent.categories = ["Tools", "Core"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]  # replace with "Firstname Lastname (Organization)"
        self.setHelpUrl("Core/CorePhotographLoader.html")

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class CorePhotographLoaderWidget(LTracePluginWidget):
    DIALOG_DIRECTORY = "dialogDirectory"
    DEPTH_CONTROL = "depthControl"
    INITIAL_DEPTH = "initialDepth"
    CORE_LENGTH = "coreLength"
    CORE_BOUNDARIES_FILE = "coreBoundariesFile"
    DEPTH_CONTROL_INITIAL_DEPTH = 0
    DEPTH_CONTROL_INITIAL_DEPTH_LABEL = "Initial depth and core length"
    DEPTH_CONTROL_CORE_BOUNDARIES = 1
    DEPTH_CONTROL_CORE_BOUNDARIES_LABEL = "Core boundaries CSV file"
    DEPTH_CONTROL_FROM_OCR = 2
    DEPTH_CONTROL_FROM_OCR_LABEL = "From photos (OCR)"

    def setup(self):
        LTracePluginWidget.setup(self)

        # Parameters Area
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Parameters"
        self.layout.addWidget(parametersCollapsibleButton)

        parameters_form_layout = qt.QFormLayout(parametersCollapsibleButton)

        # Directory selection widget
        self.directory_selector = ctk.ctkDirectoryButton()
        self.directory_selector.setMaximumWidth(374)
        self.directory_selector.caption = "Export directory"
        self.directory_selector.directoryChanged.connect(self.on_directory_input_changed)
        parameters_form_layout.addRow("Input folder:", self.directory_selector)

        # Depth control widgets
        self.depth_control_combo_box = qt.QComboBox()
        self.depth_control_combo_box.addItem(self.DEPTH_CONTROL_INITIAL_DEPTH_LABEL, self.DEPTH_CONTROL_INITIAL_DEPTH)
        self.depth_control_combo_box.addItem(
            self.DEPTH_CONTROL_CORE_BOUNDARIES_LABEL, self.DEPTH_CONTROL_CORE_BOUNDARIES
        )
        self.depth_control_combo_box.addItem(self.DEPTH_CONTROL_FROM_OCR_LABEL, self.DEPTH_CONTROL_FROM_OCR)
        self.depth_control_combo_box.setCurrentIndex(self.depth_control_combo_box.findData(self.get_depth_control()))
        self.depth_control_combo_box.currentIndexChanged.connect(self.__on_depth_control_combo_box_changed)
        self.depth_control_combo_box.setToolTip("Select an option to define the core depths")
        parameters_form_layout.addRow("Depth control:", self.depth_control_combo_box)

        # Core boxes depth table file input widget
        self.core_boundaries_file_input = ctk.ctkPathLineEdit()
        self.core_boundaries_file_input.setCurrentPath(self.get_core_boundaries_file())
        self.core_boundaries_file_input.filters = ctk.ctkPathLineEdit.Files
        self.core_boundaries_file_input.nameFilters = ["*.csv"]
        self.core_boundaries_file_input_label = qt.QLabel("Core depth file:")
        self.core_boundaries_file_input.settingKey = "CorePhotographLoader/CoreBoundariesFile"
        parameters_form_layout.addRow(self.core_boundaries_file_input_label, self.core_boundaries_file_input)

        self.locale = qt.QLocale(qt.QLocale.C)
        self.locale.setNumberOptions(qt.QLocale.RejectGroupSeparator)

        self.initial_depth_label = qt.QLabel("Initial depth (m):")
        self.initial_depth_line_edit = qt.QLineEdit(self.get_initial_depth())
        self.initial_depth_validator = qt.QDoubleValidator()
        self.initial_depth_validator.setLocale(self.locale)
        self.initial_depth_validator.bottom = 0
        self.initial_depth_line_edit.setValidator(self.initial_depth_validator)
        self.initial_depth_line_edit.setToolTip("Depth at the top of the first core in the batch")
        parameters_form_layout.addRow(self.initial_depth_label, self.initial_depth_line_edit)

        self.core_length_label = qt.QLabel("Core length (cm):")
        self.core_length_line_edit = qt.QLineEdit(self.get_core_length())
        self.core_length_validator = qt.QDoubleValidator()
        self.core_length_validator.setLocale(self.locale)
        self.core_length_validator.bottom = 0
        self.core_length_line_edit.setValidator(self.core_length_validator)
        self.core_length_line_edit.setToolTip("Core length in centimeters")
        parameters_form_layout.addRow(self.core_length_label, self.core_length_line_edit)

        # Apply Button
        self.apply_button = qt.QPushButton("Apply")
        self.apply_button.toolTip = "Run the algorithm."
        self.apply_button.enabled = False
        parameters_form_layout.addRow(self.apply_button)

        # connections
        self.apply_button.clicked.connect(self.on_apply_button_clicked)

        self.cli_progress_bar = LocalProgressBar()
        parameters_form_layout.addRow(self.cli_progress_bar)

        # Add vertical spacer
        self.layout.addStretch(1)
        self.logic = None

        self.__on_depth_control_combo_box_changed()
        self.update_apply_button_state()

    def update_apply_button_state(self, running_process=None):
        state = not running_process and Path(self.directory_selector.directory).is_dir()
        self.apply_button.setEnabled(state)

    def cleanup(self):
        pass

    def on_apply_button_clicked(self):
        input_depth_table_file = None
        user_defined_start_depth = None
        fixed_box_height_meter = None
        if self.depth_control_combo_box.currentData == self.DEPTH_CONTROL_CORE_BOUNDARIES:
            input_depth_table_file = self.core_boundaries_file_input.currentPath
        elif self.depth_control_combo_box.currentData == self.DEPTH_CONTROL_INITIAL_DEPTH:
            user_defined_start_depth = float(self.initial_depth_line_edit.text)
            fixed_box_height_meter = float(self.core_length_line_edit.text) / 100

        data = {
            "input_dir_list": [self.directory_selector.directory],
            "depth_control_mode": self.depth_control_combo_box.currentData,
            "input_depth_table_file": input_depth_table_file,
            "fixed_box_height_meter": fixed_box_height_meter,
            "user_defined_start_depth": user_defined_start_depth,
        }
        self.logic = CorePhotographLoaderLogic()
        self.logic.process_started.connect(lambda: self.update_apply_button_state(running_process=True))
        self.logic.process_finished.connect(lambda: self.update_apply_button_state(running_process=False))
        self.set_initial_depth(self.initial_depth_line_edit.text)
        self.set_core_boundaries_file(self.core_boundaries_file_input.currentPath)
        self.set_core_length(self.core_length_line_edit.text)
        self.set_depth_control(self.depth_control_combo_box.currentData)
        save_path(self.core_boundaries_file_input)

        try:
            self.logic.run(data, self.cli_progress_bar)
        except RuntimeError as error:
            slicer.util.errorDisplay(error)

    def __on_depth_control_combo_box_changed(self):
        if self.depth_control_combo_box.currentData == self.DEPTH_CONTROL_INITIAL_DEPTH:
            self.initial_depth_label.visible = True
            self.initial_depth_line_edit.visible = True
            self.core_length_label.visible = True
            self.core_length_line_edit.visible = True
            self.core_boundaries_file_input_label.visible = False
            self.core_boundaries_file_input.visible = False
        elif self.depth_control_combo_box.currentData == self.DEPTH_CONTROL_CORE_BOUNDARIES:
            self.initial_depth_label.visible = False
            self.initial_depth_line_edit.visible = False
            self.core_length_label.visible = False
            self.core_length_line_edit.visible = False
            self.core_boundaries_file_input_label.visible = True
            self.core_boundaries_file_input.visible = True
        else:
            self.initial_depth_label.visible = False
            self.initial_depth_line_edit.visible = False
            self.core_length_label.visible = False
            self.core_length_line_edit.visible = False
            self.core_boundaries_file_input_label.visible = False
            self.core_boundaries_file_input.visible = False

    def on_directory_input_changed(self, dir_path):
        CorePhotographLoader.set_setting(self.DIALOG_DIRECTORY, os.path.dirname(dir_path))
        self.update_apply_button_state()

    def get_dialog_directory(self):
        return CorePhotographLoader.get_setting(self.DIALOG_DIRECTORY, default=str(Path.home()))

    def get_depth_control(self):
        return CorePhotographLoader.get_setting(self.DEPTH_CONTROL, default=self.DEPTH_CONTROL_INITIAL_DEPTH)

    def set_depth_control(self, depth_control):
        CorePhotographLoader.set_setting(self.DEPTH_CONTROL, depth_control)

    def get_initial_depth(self):
        return CorePhotographLoader.get_setting(self.INITIAL_DEPTH, default="5422")

    def set_initial_depth(self, depth):
        return CorePhotographLoader.set_setting(self.INITIAL_DEPTH, depth)

    def get_core_length(self):
        return CorePhotographLoader.get_setting(self.CORE_LENGTH, default="90")

    def set_core_length(self, length):
        return CorePhotographLoader.set_setting(self.CORE_LENGTH, length)

    def get_core_boundaries_file(self):
        return CorePhotographLoader.get_setting(self.CORE_BOUNDARIES_FILE, default="")

    def set_core_boundaries_file(self, file):
        return CorePhotographLoader.set_setting(self.CORE_BOUNDARIES_FILE, file)


class CorePhotographLoaderLogic(LTracePluginLogic):
    process_started = qt.Signal()
    process_finished = qt.Signal()
    ROOT_DATASET_DIRECTORY_NAME = "Core"

    DEPTH_CONTROL_INITIAL_DEPTH = 0
    DEPTH_CONTROL_CORE_BOUNDARIES = 1
    DEPTH_CONTROL_FROM_OCR = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.__cli_queue = None

    def run(self, data: dict, cli_progress_bar):
        """Start process to extract the core image from the photographies.

        Args:
            data (dict): the logic configuration data
            cli_progress_bar (LocalProgressBar): The progress bar widget's object.
        """
        self.cli_progress_bar = cli_progress_bar
        self.__cli_queue = CliQueue(progress_bar=self.cli_progress_bar)

        input_dir_list = data.get("input_dir_list", [])
        depth_control_mode = data.get("depth_control_mode", self.DEPTH_CONTROL_INITIAL_DEPTH)
        input_depth_table_file = data.get("input_depth_table_file", "")
        fixed_box_height_meter = data.get("fixed_box_height_meter")
        user_defined_start_depth = data.get("user_defined_start_depth")

        if len(input_dir_list) <= 0:
            raise RuntimeError("Invalid directory input.")

        if depth_control_mode == self.DEPTH_CONTROL_INITIAL_DEPTH:
            if fixed_box_height_meter is None:
                raise RuntimeError("Please, insert a value for fixed depth for each box.")
            if user_defined_start_depth is None:
                raise RuntimeError("Please, insert a value for initial depth.")
        elif depth_control_mode == self.DEPTH_CONTROL_CORE_BOUNDARIES:
            if not input_depth_table_file:
                raise RuntimeError("Please, select a core depth file.")

        image_files_path = list()
        for input_dir in input_dir_list:
            image_files_path = self.__filter_image_files(input_dir)

            if len(image_files_path) <= 0:
                logging.warning("No image file was found at the directory {}.".format(input_dir))
                continue

            core_boxes_list = []
            for image_file in image_files_path:
                try:
                    core_boxes = CoreBoxesImageFile(image_file, gpuEnabled=is_tensorflow_gpu_enabled())
                except RuntimeError as error:
                    logging.warning(error)
                    continue

                core_boxes_list.append(core_boxes)

            if len(core_boxes_list) <= 0:
                logging.warning("No core box was found at the directory {}.".format(input_dir))
                continue

            # classify boxes category
            classified_cores_boxes = dict()
            for core_boxes in core_boxes_list:
                category = core_boxes.category.name
                classified_category = classified_cores_boxes.setdefault(category, dict())
                id = core_boxes.core_id

                core_boxes_from_id = classified_category.setdefault(id, list())
                core_boxes_from_id.append(core_boxes)
                classified_cores_boxes[category][id] = core_boxes_from_id

            if len(classified_cores_boxes.keys()) <= 0:
                logging.warning("No core was identified at the directory {}.".format(input_dir))
                continue

            core_boxes_files_dict = dict()

            categories = classified_cores_boxes.keys()
            for category in categories:
                name = slicer.mrmlScene.GenerateUniqueName(f"Core {category}")
                node = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLVectorVolumeNode.__name__, name)
                table_node = createTemporaryNode(slicer.vtkMRMLTableNode, "_TMP_TABLE_NODE")
                for core_id, core_boxes_list in classified_cores_boxes[category].items():
                    core_boxes_file_path = [core_boxes.file_path for core_boxes in core_boxes_list]
                    core_boxes_files_dict[core_id] = core_boxes_file_path

                cli_data = {
                    "core_boxes_files_dict": core_boxes_files_dict,
                    "fixed_box_height_meter": fixed_box_height_meter,
                    "input_depth_table_file": input_depth_table_file,
                    "user_defined_start_depth": user_defined_start_depth,
                    "tesseract_bin_path": getTesseractCmd(),
                }

                subject_hierarchy_path_node = [
                    self.ROOT_DATASET_DIRECTORY_NAME,
                    os.path.basename(os.path.dirname(core_boxes_file_path[0])),
                ]
                addNodeToSubjectHierarchy(node=node, dirPaths=subject_hierarchy_path_node)

                cli_config = dict(
                    data=json.dumps(cli_data),
                    outputVolume=node.GetID(),
                    outputReport=table_node.GetID(),
                    gpuEnabled=is_tensorflow_gpu_enabled(),
                )
                modified_callback = lambda caller, event, config=cli_config: self._cli_node_event_handler(
                    caller, event, config
                )
                self.__cli_queue.create_cli_node(slicer.modules.corephotographloadercli, cli_config, modified_callback)

        self.__cli_queue.signal_queue_finished.connect(self._on__process_finished)
        self.__cli_queue.run()
        self.process_started.emit()

    def _on_process_finished(self):
        self.process_finished.emit()

    def _cli_node_event_handler(self, caller, event, config):
        if caller is None:
            return

        if caller.GetStatus() == slicer.vtkMRMLCommandLineModuleNode.Completed:
            report_table_node = tryGetNode(config["outputReport"])
            output_node = tryGetNode(config["outputVolume"])
            slicer.app.processEvents()
            if report_table_node is None or output_node is None:
                message = "Internal error at process output."
                logging.warning(message)
                return

            report_df = slicer.util.dataframeFromTable(report_table_node)

            try:
                x_spacing = float(report_df["x_spacing"][0])
                y_spacing = float(report_df["y_spacing"][0])
                origin = float(report_df["origin"][0])
                output_node.SetSpacing(x_spacing, 1, y_spacing)
                output_node.SetOrigin(0, 0, origin)
                output_node.SetIJKToRASDirections(-1, 0, 0, 0, -1, 0, 0, 0, -1)
                slicer.mrmlScene.RemoveNode(report_table_node)
            except Exception as error:
                message = f"Error during process report generation: {error}"
                logging.warning(message)
                slicer.util.errorDisplay(message)
                slicer.mrmlScene.RemoveNode(output_node)
                slicer.mrmlScene.RemoveNode(report_table_node)

        elif caller.GetStatus() == slicer.vtkMRMLCommandLineModuleNode.CompletedWithErrors:
            error_msg = caller.GetErrorText() or "unknown"
            message = f"The process completed with an error: {error_msg}"
            logging.warning(message)
            slicer.util.errorDisplay(message)

    def __filter_image_files(self, dir):
        """Search for image files inside input's directory path

        Args:
            dir (str): directory path

        Returns:
            list: a image file's list
        """
        extensions = ["png", "jpg", "jpeg", "gif"]

        files = []

        for ext in extensions:
            files.extend(glob.glob(os.path.join(dir, "*." + ext)))

        return files
