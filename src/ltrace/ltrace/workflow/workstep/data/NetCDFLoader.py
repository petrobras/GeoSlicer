from pathlib import Path
import re

import ctk
import qt
import slicer
import xarray as xr
from ltrace.workflow.workstep import Workstep, WorkstepWidget
from ltrace.slicer.netcdf import import_dataset

ROOT_DATASET_DIRECTORY_NAME = "NetCDF"


class NetCDFLoader(Workstep):
    NAME = "Data: NetCDF Loader"

    INPUT_TYPES = (type(None),)
    OUTPUT_TYPES = {
        "Segmentation": slicer.vtkMRMLSegmentationNode,
        "Label map": slicer.vtkMRMLLabelMapVolumeNode,
        "RGB image": slicer.vtkMRMLVectorVolumeNode,
        "Grayscale image": slicer.vtkMRMLScalarVolumeNode,
    }

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.input_directory = ""
        self.output_type_name = "Segmentation"
        self.name_filter = ""
        self.file_filter = ""

    def run(self, nodes):
        for dataset, name, images in self.datasets_to_load():
            try:
                folderTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
                scene_id = folderTree.GetSceneItemID()
                current_dir = folderTree.CreateFolderItem(scene_id, name)
                for (node, _) in import_dataset(dataset, images):
                    _ = folderTree.CreateItem(current_dir, node)
                    # Don't yield reference images
                    if type(node) == self.output_type():
                        yield node
            except Exception as e:
                print(f"Failed to import {name}: {e}")
                continue

    def expected_length(self, input_length):
        return sum(len(images) for _, _, images in self.datasets_to_load())

    def output_type(self):
        return self.OUTPUT_TYPES[self.output_type_name]

    def datasets_to_load(self):
        datasets = []

        if not self.input_directory:
            return datasets

        for path in Path(self.input_directory).glob("*.nc"):
            dataset = xr.open_dataset(str(path))
            images_to_load = []
            if not re.search(self.file_filter, str(path.name)):
                continue
            for array in dataset.values():
                if self.name_filter not in array.name:
                    continue
                type_ = None
                if "c" in array.dims:
                    type_ = slicer.vtkMRMLVectorVolumeNode
                elif "labels" in array.attrs:
                    type_ = (
                        slicer.vtkMRMLLabelMapVolumeNode
                        if array.attrs["type"] == "labelmap"
                        else slicer.vtkMRMLSegmentationNode
                    )
                else:
                    type_ = slicer.vtkMRMLScalarVolumeNode
                if type_ == self.output_type():
                    images_to_load.append(array.name)
                    if "reference" in array.attrs and self.name_filter in array.attrs["reference"]:
                        images_to_load.append(array.attrs["reference"])
            datasets.append((dataset, path.stem, images_to_load))
        return datasets

    def widget(self):
        return NetCDFLoaderWidget(self)

    def validate(self):
        if not self.datasets_to_load():
            return "No NetCDF files found in input directory."
        if self.output_type() == Workstep.MIXED_TYPE:
            return "Images in directory are of different types. Make sure they are all of the same type (grayscale, RGB or segmentation)."
        return True


class NetCDFLoaderWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)

        self.form_layout = qt.QFormLayout()
        self.form_layout.setLabelAlignment(qt.Qt.AlignRight)
        self.layout().addLayout(self.form_layout)

        self.input_directory_button = ctk.ctkDirectoryButton()
        self.input_directory_button.setMaximumWidth(374)
        self.input_directory_button.setToolTip("Load all images from all NetCDF files in this directory.")

        self.form_layout.addRow("Input directory:", self.input_directory_button)

        self.type_combobox = qt.QComboBox()
        self.type_combobox.addItems(list(NetCDFLoader.OUTPUT_TYPES))
        self.type_combobox.setToolTip("Only images of the selected type and their reference images will be loaded.")
        self.form_layout.addRow("Output type:", self.type_combobox)

        self.name_filter_label = qt.QLineEdit()
        self.name_filter_label.setToolTip("Only images that contain this string in their name will be loaded.")
        self.form_layout.addRow("Filter image by name:", self.name_filter_label)

        self.file_filter_label = qt.QLineEdit()
        self.file_filter_label.setToolTip(
            "Only files that contain this string in their name will be loaded"
            ". String is interpreted as a Regular Expression"
        )
        self.form_layout.addRow("Filter file by substring:", self.file_filter_label)

    def save(self):
        self.workstep.input_directory = self.input_directory_button.directory
        self.workstep.output_type_name = self.type_combobox.currentText
        self.workstep.name_filter = self.name_filter_label.text
        self.workstep.file_filter = self.file_filter_label.text

    def load(self):
        self.input_directory_button.directory = self.workstep.input_directory
        self.type_combobox.setCurrentText(self.workstep.output_type_name)
        self.name_filter_label.setText(self.workstep.name_filter)
        self.file_filter_label.setText(self.workstep.file_filter)
