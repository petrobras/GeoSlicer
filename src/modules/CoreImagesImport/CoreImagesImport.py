import cv2
import numpy as np
import pickle
import qt
import slicer
import vtk
import shutil
from pathlib import Path

from ltrace.slicer_utils import *
from ltrace.units import convert_to_global_registry, global_unit_registry as ureg
from ltrace.cli_progress import RunCLIWithProgressBar


class CoreImagesImport(LTracePlugin):

    SETTING_KEY = "CoreImagesImport"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Core Images Import"
        self.parent.categories = ["Upscaling"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = """"""
        self.parent.acknowledgementText = (
            """This module finds the plug holes in core images and load them into Slicer as fiducials."""
        )
        self.final_depth = 0 * ureg.meter
        self.cores = []

    def setup(self):
        pass

    def add_core(self, name, initial_depth, plug_depths):
        self.cores.append([name, initial_depth, sorted(plug_depths)])

    def remove_core(self, index):
        del self.cores[index]

    @staticmethod
    def get_instance():
        return slicer.modules.CoreImagesImportInstance


class CoreImagesImportWidget(LTracePluginWidget):
    def __init__(self, *args, **kwargs):
        LTracePluginWidget.__init__(self, *args, **kwargs)

        initial_depth_frame = qt.QWidget()
        initial_depth_frame.setLayout(qt.QFormLayout())
        self.depth_sp_meters = qt.QDoubleSpinBox()
        self.depth_sp_meters.setRange(0, 99999)
        self.depth_sp_meters.setDecimals(2)
        self.depth_sp_meters.setSingleStep(0.01)
        instance = CoreImagesImport.get_instance()
        self.depth_sp_meters.setValue(instance.final_depth.m_as(ureg.meter))

        self.volume_selection_cb = slicer.qMRMLNodeComboBox()
        self.volume_selection_cb.nodeTypes = ["vtkMRMLScalarVolumeNode", "vtkMRMLVectorVolumeNode"]
        self.volume_selection_cb.selectNodeUponCreation = False
        self.volume_selection_cb.addEnabled = False
        self.volume_selection_cb.removeEnabled = False
        self.volume_selection_cb.noneEnabled = False
        self.volume_selection_cb.showHidden = False
        self.volume_selection_cb.showChildNodeTypes = False
        self.volume_selection_cb.setMRMLScene(slicer.mrmlScene)
        self.volume_selection_cb.setToolTip("Pick volume to place fiducials.")
        self.volume_selection_cb.currentNodeChanged.connect(self._on_volume_selected)

        self.output_selector = slicer.qMRMLNodeComboBox()
        self.output_selector.nodeTypes = ["vtkMRMLTableNode"]
        self.output_selector.selectNodeUponCreation = True
        self.output_selector.addEnabled = True
        self.output_selector.removeEnabled = True
        self.output_selector.noneEnabled = False
        self.output_selector.showHidden = False
        self.output_selector.showChildNodeTypes = False
        self.output_selector.setMRMLScene(slicer.mrmlScene)
        self.output_selector.setToolTip("Pick the output table to store the result")

        initial_depth_frame.layout().addRow("Initial Depth: ", self.depth_sp_meters)
        initial_depth_frame.layout().addRow("Volume: ", self.volume_selection_cb)
        initial_depth_frame.layout().addRow("Output Table: ", self.output_selector)

        initial_depth_frame.layout().setLabelAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)
        initial_depth_frame.layout().setFormAlignment(qt.Qt.AlignLeft | qt.Qt.AlignBottom)

        self.tableWidget = qt.QTableWidget()
        self.tableWidget.setColumnCount(3)
        self.tableWidget.setHorizontalHeaderLabels(["Core", "Depth", "Plug Holes"])
        self.tableWidget.horizontalHeader().setStretchLastSection(True)
        self.tableWidget.setShowGrid(False)
        self.tableWidget.setAlternatingRowColors(True)
        self.tableWidget.setSelectionBehavior(self.tableWidget.SelectRows)
        self.tableWidget.setSelectionMode(self.tableWidget.ExtendedSelection)
        self.tableWidget.selectionModel().selectionChanged.connect(self._on_table_selection_changed)

        self.tableWidget.cellChanged.connect(self._on_cell_changed)

        table_edit_frame = qt.QWidget()
        table_edit_frame.setLayout(qt.QHBoxLayout())
        self.add_button = qt.QPushButton("+")
        self.remove_button = qt.QPushButton("-")

        self.add_button.clicked.connect(self._on_add_clicked)
        self.remove_button.clicked.connect(self._on_remove_clicked)
        self.remove_button.setEnabled(False)

        table_edit_frame.layout().addWidget(self.add_button)
        table_edit_frame.layout().addStretch()
        table_edit_frame.layout().addWidget(self.remove_button)

        self.load_button = qt.QPushButton("Load")
        self.load_button.clicked.connect(self._on_load_clicked)
        self._on_volume_selected()

        self.layout.addWidget(initial_depth_frame)
        self.layout.addWidget(self.tableWidget)
        self.layout.addWidget(table_edit_frame)
        self.layout.addWidget(self.load_button)

        self._ignore_cell_changed = False

    def setup(self):
        LTracePluginWidget.setup(self)

    def cleanup(self):
        pass

    def _on_add_clicked(self):
        last_path = slicer.app.settings().value("CoreImagesImport/last-load-path")
        if last_path is None:
            last_path = str(Path.home())

        selected_folder = qt.QFileDialog.getExistingDirectory(None, "Load core images", last_path)

        if selected_folder:
            CoreImagesImport.set_setting("last-load-path", selected_folder)
        else:
            return

        temp_dir = Path(slicer.util.tempDirectory(key="__import_core_images__"))
        output_file = temp_dir / "plug_holes"

        success, message = RunCLIWithProgressBar(
            slicer.modules.importcoreimagescli,
            parameters={
                "core_images_folder": selected_folder,
                "output_file": str(output_file),
            },
            title="Processing files",
        )

        if not success:
            e = qt.QErrorMessage(self.parent)
            e.showMessage(message)
            shutil.rmtree(temp_dir)
            return

        current_depth = self.depth_sp_meters.value * ureg.meter
        cores = []
        with open(str(output_file), "rb") as f:
            result = pickle.loads(f.read())

            for file, plugs in result:
                filename = file.stem
                core_start = 0 * ureg.centimeter

                for i, ((start, end), holes) in enumerate(plugs):
                    start = convert_to_global_registry(start)
                    end = convert_to_global_registry(end)
                    holes.sort()

                    cores.append(
                        [
                            "{}_{}".format(filename, i + 1),
                            current_depth,
                            [convert_to_global_registry(h) - start for h in holes],
                        ]
                    )

                    current_depth += end - start

            instance = CoreImagesImport.get_instance()
            instance.cores.extend(cores)
            instance.final_depth = current_depth
            self._update_cores_list()

        shutil.rmtree(temp_dir)

        CoreImagesImport.set_setting("last-load-path", str(Path(selected_folder).absolute()))

    def _on_remove_clicked(self):
        selected_rows = sorted(self.tableWidget.selectionModel().selectedRows(), reverse=True)

        instance = CoreImagesImport.get_instance()
        for selected_row in selected_rows:
            instance.remove_core(selected_row.row())

        self._update_cores_list()

    def _on_table_selection_changed(self, *args):
        selected_rows = self.tableWidget.selectionModel().selectedRows()
        self.remove_button.setEnabled(len(selected_rows) > 0)

    def _on_volume_selected(self):
        selected_node = self.volume_selection_cb.currentNode()
        is_selected = selected_node is not None
        self.load_button.setEnabled(is_selected)

        selected_rows = self.tableWidget.selectionModel().selectedRows()
        if is_selected and len(selected_rows) == 0:
            r, a, s = selected_node.GetOrigin()
            s = s * ureg.millimeter

            self.depth_sp_meters.setValue(-s.m_as(ureg.m))

    def _on_load_clicked(self):
        markupsNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode")
        markupsNode.CreateDefaultDisplayNodes()
        markupsDisplayNode = markupsNode.GetDisplayNode()
        markupsDisplayNode.SetGlyphScale(3)
        markupsDisplayNode.SetTextScale(3)
        markupsDisplayNode.SliceProjectionOn()
        markupsDisplayNode.SliceProjectionUseFiducialColorOff()
        markupsDisplayNode.SetColor(1.0, 1.0, 1.0)
        markupsDisplayNode.SetSelectedColor(1.0, 1.0, 1.0)
        markupsDisplayNode.SetSliceProjectionColor(1.0, 1.0, 1.0)

        instance = CoreImagesImport.get_instance()
        subject_hierarchy = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        parent_item_id = subject_hierarchy.GetItemByDataNode(self.volume_selection_cb.currentNode())

        for name, depth, plug_holes in instance.cores:
            for i, hole in enumerate(plug_holes):
                hole_depth_mm = (depth + hole).m_as(ureg.millimeter)
                added_index = markupsNode.AddFiducial(0, 0, -hole_depth_mm)
                markupsNode.SetNthFiducialLabel(added_index, "{}_plug_hole_{}".format(name, i))
                markupsNode.SetNthMarkupLocked(added_index, True)
                subject_hierarchy.CreateItem(parent_item_id, markupsNode)

        self._write_table()

    def _write_table(self):
        instance = CoreImagesImport.get_instance()

        cores_array = vtk.vtkDoubleArray()
        cores_array.SetName("core")
        plugs_array = vtk.vtkDoubleArray()
        plugs_array.SetName("plug")

        for name, depth, plug_holes in instance.cores:
            for hole in plug_holes:
                cores_array.InsertNextValue(depth.m_as(ureg.meter))
                plugs_array.InsertNextValue((depth + hole).m_as(ureg.meter))

        table_node = self.output_selector.currentNode()
        table_modified_flag = table_node.StartModify()
        table_node.RemoveAllColumns()  # Reset
        table = table_node.GetTable()

        table.AddColumn(cores_array)
        table.AddColumn(plugs_array)

        table_node.Modified()
        table_node.EndModify(table_modified_flag)

    def _update_cores_list(self):
        instance = CoreImagesImport.get_instance()

        self.tableWidget.clearContents()
        self.tableWidget.setRowCount(len(instance.cores))
        for i, (name, depth, plug_holes) in enumerate(instance.cores):
            self.tableWidget.setItem(i, 0, qt.QTableWidgetItem(name))
            self.tableWidget.setItem(i, 1, qt.QTableWidgetItem(self._format_depth(depth)))
            self.tableWidget.setItem(i, 2, qt.QTableWidgetItem(self._format_plug_holes(depth, plug_holes)))

        self.depth_sp_meters.setValue(instance.final_depth.m_as(ureg.meter))
        self._resize_table_widget()

    def _format_plug_holes(self, initial_depth, holes):
        return ", ".join([self._format_depth(initial_depth + hole_depth) for hole_depth in holes])

    def _format_depth(self, depth):
        return "{:.2f}m".format(depth.m_as(ureg.meter))

    def _on_cell_changed(self, row, column):
        if self._ignore_cell_changed:
            return

        self._ignore_cell_changed = True

        if self._update_row(row, column):
            self._update_cores_list()

        self._ignore_cell_changed = False

    def _update_row(self, row, column):
        instance = CoreImagesImport.get_instance()

        if column == 0:
            name_item = self.tableWidget.item(row, column)
            instance.cores[row][0] = name_item.text()

        elif column == 1:
            depth = self.tableWidget.item(row, column)
            depth_text = depth.text()
            changed_depth = self._get_depth(depth_text)
            if changed_depth is None:
                return False

            instance.cores[row][1] = changed_depth

        elif column == 2:
            holes_item = self.tableWidget.item(row, column)
            holes_txt = holes_item.text().strip()
            holes = holes_txt.split(",")

            if not holes_txt:
                return False

            initial_depth = instance.cores[row][1]

            changed_holes = []
            for hole in holes:
                hole_value = self._get_depth(hole) - initial_depth
                if hole is None:
                    changed_holes = None
                    break
                else:
                    changed_holes.append(hole_value)

            if changed_holes is None:
                return False

            instance.cores[row][2] = changed_holes

        return True

    def _get_float(self, str):
        try:
            return float(str)
        except ValueError:
            return None

    def _get_depth(self, str):
        str = str.strip()

        if not str:
            return None

        if str[-1] == "m":
            return self._get_float(str[:-1]) * ureg.meter
        else:
            return self._get_float(str) * ureg.meter

    def _resize_table_widget(self):
        self.tableWidget.resizeColumnToContents(0)
        self.tableWidget.resizeColumnToContents(1)
        self.tableWidget.horizontalHeader().setStretchLastSection(True)


class CoreImagesImportLogic(LTracePluginLogic):

    pass


class CoreImagesImportFileWriter(object):
    def __init__(self, parent):
        pass
