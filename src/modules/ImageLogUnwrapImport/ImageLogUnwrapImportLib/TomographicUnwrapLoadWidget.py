import os
import re
from pathlib import Path

import ctk
import cv2
import numpy as np
import pandas as pd
import qt
import slicer
import vtk

from ImageLogUnwrapImportLib.TomographicUnwrapBoundariesFile import TomographicUnwrapBoundariesFile
from ltrace.image.core_box.core_box import CoreBox
from ltrace.image.core_box.core_image import concatenate_core_boxes
from ltrace.slicer import helpers, ui


class TomographicUnwrapLoadWidget(qt.QWidget):
    REGEX_PATTERN = r"T(\d+)_CX(\d+)CX(\d+)\.(jpg|png|tif)"
    TABLE_COLUMN_WELL = "poco"
    TABLE_COLUMN_SAMPLE = "testemunho"
    TABLE_COLUMN_BOX = "caixa"
    TABLE_COLUMN_INITIAL_DEPTH = "topo_caixa_m"
    TABLE_COLUMN_FINAL_DEPTH = "base_caixa_m"

    def __init__(self, parent=None):
        super().__init__(parent)

        self.currentDirectoryPath = None

        layout = qt.QVBoxLayout(self)

        self.selectDirectoryButton = qt.QPushButton("Select directory")
        self.selectDirectoryButton.setIcon(self.style().standardIcon(qt.QStyle.SP_DirIcon))
        self.selectDirectoryButton.clicked.connect(self.onSelectDirectory)

        self.fileListWidget = qt.QListWidget()

        formLayout = qt.QFormLayout()
        self.wellDiameter = ui.floatParam("")
        helpers.reset_style_on_valid_text(self.wellDiameter)
        self.boundariesFileInput = ctk.ctkPathLineEdit()
        helpers.reset_style_on_valid_text(self.boundariesFileInput)
        formLayout.addRow("Well diameter (inches):", self.wellDiameter)
        formLayout.addRow("Boundaries file:", self.boundariesFileInput)

        self.loadButton = ui.ApplyButton(onClick=self.onLoadButtonClicked, text="Load", enabled=False)

        self.statusLabel = ui.TemporaryStatusLabel()

        layout.addWidget(self.selectDirectoryButton)
        layout.addWidget(self.fileListWidget)
        layout.addLayout(formLayout)
        layout.addWidget(self.loadButton)
        layout.addWidget(self.statusLabel)
        layout.addStretch()

    def onSelectDirectory(self):
        self.currentDirectoryPath = qt.QFileDialog.getExistingDirectory(self, None, None)
        if not self.currentDirectoryPath:
            return

        self.fileListWidget.clear()
        imageFiles = [f for f in os.listdir(self.currentDirectoryPath) if re.match(self.REGEX_PATTERN, f)]
        for imageFileName in imageFiles:
            self.fileListWidget.addItem(imageFileName)

        tableFiles = [f for f in os.listdir(self.currentDirectoryPath) if re.match(r".+\.(csv)", f)]
        if tableFiles:
            self.boundariesFileInput.setCurrentPath(str(Path(self.currentDirectoryPath) / Path(tableFiles[0])))
        self.loadButton.enabled = self.fileListWidget.count > 0

    def onLoadButtonClicked(self):
        # Checks
        if not self.__validateWellDiameterInput():
            self.statusLabel.setStatus("Missing well diameter input", "red")
            return
        else:
            wellDiameter = float(self.wellDiameter.text)
        if not self.__validateBoundariesFileInput():
            self.statusLabel.setStatus("Missing boundaries csv file", "red")
            return
        else:
            boundariesFilePath = self.boundariesFileInput.currentPath
        boundariesFile = TomographicUnwrapBoundariesFile(boundariesFilePath)
        success, message = boundariesFile.check_version()
        if not success:
            self.statusLabel.setStatus(message, "red")
            return

        # Load images
        self.statusLabel.setStatus("Loading", "blue")
        slicer.app.processEvents()
        imageFileNameList = []
        for i in range(self.fileListWidget.count):
            imageFileNameList.append(self.fileListWidget.item(i).text())
        success, message = self.loadImages(
            self.currentDirectoryPath, imageFileNameList, wellDiameter, boundariesFilePath
        )
        message_color = "green" if success else "red"
        self.statusLabel.setStatus(message, message_color)

    def loadImages(self, directory, imageFileNameList, wellDiameter, boundariesFilePath):
        testemunho_info_df = pd.read_csv(boundariesFilePath)

        regex_pattern = re.compile(self.REGEX_PATTERN)

        well_diameter_mm = wellDiameter * 25.4  # inches to mm
        total_circumference_mm = np.pi * well_diameter_mm

        testemunho_info_list = {}
        valid_files_count = 0
        for file in imageFileNameList:
            match = re.search(regex_pattern, file)
            if not match:
                continue
            match_groups = match.groups()
            testemunho = int(match_groups[0])

            if testemunho not in testemunho_info_list:
                testemunho_info_list[testemunho] = []
            testemunho_info_list[testemunho].append(
                dict(
                    file_name=file,
                    first_box_number=int(match_groups[1]),
                    last_box_number=int(match_groups[2]),
                )
            )
            valid_files_count += 1

        if not testemunho_info_list:
            return False, "There's no tomographic unwrap files to be loaded"

        for testemunho_id, testemunho_info in testemunho_info_list.items():
            testemunho_info.sort(key=lambda core_box_info: core_box_info["first_box_number"])
            core_box_list = []
            for core_box_info in testemunho_info:
                file_name = core_box_info["file_name"]
                image = cv2.imread(f"{directory}/{file_name}", cv2.IMREAD_GRAYSCALE)
                image = image[..., np.newaxis]
                initial_depth, final_depth = self.__getSampleDepths(testemunho_info_df, testemunho_id, core_box_info)
                height = final_depth - initial_depth
                core_box = CoreBox(image, 0, core_box_info["first_box_number"], "", height, initial_depth)
                core_box_list.append(core_box)

            full_array, spacing, origin = concatenate_core_boxes(core_box_list)
            full_array = full_array.squeeze()
            full_array = full_array[:, np.newaxis, :]

            new_node_name = self.__getNodeName(testemunho_info_df, testemunho_id)
            new_node = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLScalarVolumeNode.__name__)
            new_node.SetName(slicer.mrmlScene.GenerateUniqueName(new_node_name))
            transform = vtk.vtkTransform()
            transform.RotateY(180)
            new_node.SetIJKToRASMatrix(transform.GetMatrix())
            new_node.SetOrigin(total_circumference_mm / 2, 0.0, origin * -1000)  # m to mm
            horizontal_spacing_mm = total_circumference_mm / full_array.shape[2]
            new_node.SetSpacing(horizontal_spacing_mm, 0.48, spacing * 1000)
            slicer.util.updateVolumeFromArray(new_node, full_array)

            dir_name = Path(directory).name
            self.__setDirForNode(dir_name, new_node)

        return True, "Successfully loaded {} nodes from {} files".format(len(testemunho_info_list), valid_files_count)

    def __getNodeName(self, samples_info_table, sample_id):
        index = samples_info_table[self.TABLE_COLUMN_SAMPLE].eq(sample_id).idxmax()
        well_name = samples_info_table[self.TABLE_COLUMN_WELL][index]
        return f"{well_name}_{sample_id}"

    def __getSampleDepths(self, samples_info_table, sample_id, core_box_info):
        sample_series = samples_info_table[self.TABLE_COLUMN_SAMPLE] == sample_id

        first_box_series = samples_info_table[self.TABLE_COLUMN_BOX] == core_box_info["first_box_number"]
        first_box_info = samples_info_table[sample_series & first_box_series]
        initial_depth = list(first_box_info[self.TABLE_COLUMN_INITIAL_DEPTH])[0]

        last_box_series = samples_info_table[self.TABLE_COLUMN_BOX] == core_box_info["last_box_number"]
        last_box_info = samples_info_table[sample_series & last_box_series]
        final_depth = list(last_box_info[self.TABLE_COLUMN_FINAL_DEPTH])[0]

        return initial_depth, final_depth

    def __validateWellDiameterInput(self):
        try:
            float(self.wellDiameter.text)
        except Exception as e:
            helpers.highlight_error(self.wellDiameter)
            return False
        else:
            self.wellDiameter.setStyleSheet("")
            return True

    def __validateBoundariesFileInput(self):
        if Path(self.boundariesFileInput.currentPath).is_file():
            self.boundariesFileInput.setStyleSheet("")
            return True
        else:
            helpers.highlight_error(self.boundariesFileInput)
            return False

    def __setDirForNode(self, dir_name, node):
        """
        Put node into diretory with dir_name. If directory doesn't exists, create it.
        """
        subject_hierarchy = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        app_folder_id = subject_hierarchy.GetSceneItemID()
        root_folder_id = subject_hierarchy.GetItemByName(dir_name)
        if root_folder_id == 0:
            root_folder_id = subject_hierarchy.CreateFolderItem(app_folder_id, dir_name)
        volume_item_id = subject_hierarchy.CreateItem(root_folder_id, node)
