import pickle
import re
import time
from pathlib import Path
from queue import Queue
from threading import Thread

import numpy as np
import qt
import slicer
from dlisio import dlis as dlisio
from ltrace.slicer_utils import *

import DLISImportLib

try:
    from Test.DLISImportTest import DLISImportTest
except ImportError:
    DLISImportTest = None  # tests not deployed to final version or closed source


class DLISImport(LTracePlugin):

    SETTING_KEY = "DLISImport"

    def __init__(self, parent):
        super().__init__(parent)
        self.parent.title = "Image Log Loader"
        self.parent.categories = ["Image Log"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = """This module loads volumes from DLIS, LAS, CSV or PDF files into slicer as volumes."""
        self.parent.acknowledgementText = """"""


class DLISImportLogic(LTracePluginLogic):
    def add_volume(self, top_folder, folder, name, domain, image, well_diameter_mm):
        total_circumference_millimeters = np.pi * well_diameter_mm
        vertical_spacing_millimeters = (domain[0] - domain[-1]) / image.shape[0]
        horizontal_spacing_millimeters = total_circumference_millimeters / image.shape[1]

        image = image.reshape(image.shape[0], 1, image.shape[1])
        read_volume = self._add_volume_from_data(top_folder, folder, name, image)

        read_volume.SetSpacing(horizontal_spacing_millimeters, 0.48, vertical_spacing_millimeters)
        read_volume.SetOrigin(
            -total_circumference_millimeters / 2,
            0,
            -int(domain[-0]),
        )

        return read_volume

    def _add_volume_from_data(self, root_folder, folder, name, data):
        volume_node = slicer.vtkMRMLScalarVolumeNode()
        volume_node.SetName(name)
        slicer.mrmlScene.AddNode(volume_node)
        slicer.util.updateVolumeFromArray(volume_node, data)

        subject_hierarchy = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

        root_folder_id = subject_hierarchy.GetItemByName(root_folder)
        if root_folder_id == 0:
            top_level_id = subject_hierarchy.GetSceneItemID()
            root_folder_id = subject_hierarchy.CreateFolderItem(top_level_id, root_folder)

        folder_id = subject_hierarchy.GetItemByName(folder)
        if folder_id == 0:
            folder_id = subject_hierarchy.CreateFolderItem(root_folder_id, folder)

        subject_hierarchy.CreateItem(folder_id, volume_node)

        return volume_node

    def load_volumes(
        self, file_path, mnemonic_and_files, should_stop_check, progress_callback, add_volume_callback, well_diameter_mm
    ):
        def get_mnemonic_search_exact_re(mnemonic):
            return "^{}$".format(re.escape(mnemonic))

        progress_callback("Opening file", 0)

        filesystem_filename = Path(file_path).stem

        def stopped():
            will_stop = should_stop_check()
            if will_stop:
                progress_callback("Stopped", len(mnemonic_and_files) + 2)

            return will_stop

        with dlisio.load(file_path) as files:
            id_to_file = {}
            for f in files:
                id_to_file[f.fileheader.id] = f

            if stopped():
                return

            print("matching here")

            for i, (mnemonic, file) in enumerate(mnemonic_and_files):
                for c in id_to_file[file].match(get_mnemonic_search_exact_re(mnemonic)):
                    curve_name = "{} [{}]".format(mnemonic, c.units)
                    progress_name = "{} - {}".format(curve_name, file)
                    progress_callback(progress_name, i + 1)

                    image = c.curves()

                    if stopped():
                        return

                    if len(image.shape) == 1:
                        image = image.reshape(-1, 1)
                    domain_channel = c.frame.channels[0]
                    domain = domain_channel.curves()
                    domain = domain * self._conversion_factor_to_millimeters(domain_channel.units)

                    add_volume_callback(filesystem_filename, file, curve_name, domain, image, well_diameter_mm)

                    if stopped():
                        return

        progress_callback("Finished", len(mnemonic_and_files) + 2)

    def _conversion_factor_to_millimeters(self, unit):
        to_mm_factors = {
            "um": 0.001,
            "mm": 1,
            "cm": 10,
            "dm": 100,
            "m": 1000,
            "km": 1000000,
            "in": 25.4,
            "ft": 304.8,
        }

        parts = unit.strip().split(" ")

        if not (1 <= len(parts) <= 2 and parts[-1] in to_mm_factors):
            raise ValueError("Unknown unit: {}".format(unit))

        unit = parts[-1]
        fraction = 1
        if len(parts) == 2:
            fraction = float(parts[0])

        return fraction * to_mm_factors[unit]


class DLISImportWidget(LTracePluginWidget):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.logic = DLISImportLogic()

    def setup(self):
        super().setup()

        self.dlis_widget = DLISImportLib.WellLogImportWidget()
        self.dlis_widget.loadClicked = self._on_load_clicked

        frame = qt.QFrame()
        self.layout.addWidget(frame)
        loadFormLayout = qt.QFormLayout(frame)
        loadFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        loadFormLayout.setContentsMargins(0, 0, 0, 0)

        loadFormLayout.addRow(self.dlis_widget)

        if slicer_is_in_developer_mode():
            self.reload_last_button = qt.QPushButton("Reload last configuration")
            self.reload_last_button.clicked.connect(self._on_reload_last_button_clicked)

            self.reload_last_button.setEnabled(self._get_last_load_options() is not None)
            self.layout.addWidget(self.reload_last_button)

    def _on_load_clicked(self, mnemonic_and_files):
        well_diameter = float(self.dlis_widget.wellDiameter.text) * 25.4  # inches to mm
        self._set_last_load_options((self.dlis_widget.currentPath(), mnemonic_and_files, well_diameter))

        if slicer_is_in_developer_mode():
            self.reload_last_button.setEnabled(True)
            self.reload_last_button.setVisible(True)

    def _load_curves(self, filename, mnemonic_and_logic_files, well_diameter):
        if slicer_is_in_developer_mode():
            self.reload_last_button.setEnabled(True)
            self.reload_last_button.setVisible(True)

        progress_queue = Queue(maxsize=len(mnemonic_and_logic_files) + 2)
        add_volume_queue = Queue(maxsize=len(mnemonic_and_logic_files))

        def progress_callback(name, progress_index):
            progress_queue.put((name, progress_index))

        def add_volume_callback(filesystem_filename, logic_filename, name, domain, image, well_diameter_mm):
            add_volume_queue.put((filesystem_filename, logic_filename, name, domain, image, well_diameter_mm))

        progress_dialog = qt.QProgressDialog()
        progress_dialog.setWindowModality(qt.Qt.WindowModal)
        progress_dialog.setLabelText("Loading Files...")
        progress_dialog.setCancelButtonText("Stop")
        progress_dialog.setRange(0, len(mnemonic_and_logic_files) + 2)

        should_stop = False

        def should_stop_check():
            return should_stop

        def stop():
            nonlocal should_stop
            should_stop = True

        progress_dialog.canceled.connect(stop)

        progress_dialog.show()
        load_thread = Thread(
            target=self.logic.load_volumes,
            args=(
                filename,
                mnemonic_and_logic_files,
                should_stop_check,
                progress_callback,
                add_volume_callback,
                well_diameter,
            ),
        )
        load_thread.start()

        def process_queue(queue, process_function):
            while not queue.empty():
                params = queue.get()
                process_function(*params)
                qt.QApplication.instance().processEvents()

        def update_progress(progress_text, progress_index):
            progress_dialog.setLabelText(progress_text)
            progress_dialog.setValue(progress_index)

        def add_volume(*args):
            self.logic.add_volume(*args)

        while load_thread.is_alive():
            process_queue(progress_queue, update_progress)
            process_queue(add_volume_queue, add_volume)
            qt.QApplication.instance().processEvents()
            time.sleep(0.01)

        process_queue(progress_queue, update_progress)
        process_queue(add_volume_queue, add_volume)

        load_thread.join()

    def _get_last_load_options(self):
        load_options = DLISImport.get_setting("last-load")
        if load_options is not None:
            try:
                load_options = pickle.loads(load_options.data())
            except RuntimeError:
                pass

        return load_options

    def _set_last_load_options(self, load_options):
        DLISImport.set_setting("last-load", qt.QByteArray(pickle.dumps(load_options)))

    def _on_reload_last_button_clicked(self):
        last_filename, last_selection, well_diameter = self._get_last_load_options()
        self._load_curves(last_filename, last_selection, well_diameter)
