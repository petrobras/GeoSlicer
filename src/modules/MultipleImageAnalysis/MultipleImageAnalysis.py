from pathlib import Path
from AnalysisTypes.analysis_base import AnalysisReport, FILE_NOT_FOUND
from AnalysisTypes.basic_petrophysics_analysis import BasicPetrophysicsAnalysis
from AnalysisTypes.histogram_in_depth_analysis import HistogramInDepthAnalysis
from AnalysisTypes.mean_in_depth_analysis import MeanInDepthAnalysis
from ltrace.slicer import helpers
from ltrace.slicer.node_attributes import TableDataOrientation
from ltrace.slicer_utils import (
    LTracePlugin,
    LTracePluginWidget,
    LTracePluginLogic,
    LTracePluginTest,
    dataFrameToTableNode,
)

import os
import vtk, qt, ctk, slicer
import logging
import pandas as pd

# Checks if closed source code is available
try:
    from Test.MultipleImageAnalysisTest import MultipleImageAnalysisTest
except ImportError:
    MultipleImageAnalysisTest = None  # tests not deployed to final version or closed source


class MultipleImageAnalysis(LTracePlugin):
    SETTING_KEY = "MultipleImageAnalysis"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Multiple Image Analysis"
        self.parent.categories = ["LTrace Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]  # replace with "Firstname Lastname (Organization)"
        self.parent.helpText = MultipleImageAnalysis.help()
        self.parent.helpText += self.getDefaultModuleDocumentationLink()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class MultipleImageAnalysisWidget(LTracePluginWidget):
    """Plugin responsible to generate custom reports based on the analysis' type selected.
    To add a new type of analysis, create a custom class that inherits AnalysisBase class, and then append its instance to
    'analysis_types' list object.
    """

    def setup(self):
        LTracePluginWidget.setup(self)

        self.analysis_types = [HistogramInDepthAnalysis(), MeanInDepthAnalysis(), BasicPetrophysicsAnalysis()]

        parameters_collapsible_button = ctk.ctkCollapsibleButton()
        parameters_collapsible_button.text = "Multiple Image Analysis"
        self.layout.addWidget(parameters_collapsible_button)

        form_layout = qt.QFormLayout(parameters_collapsible_button)

        # Analysis type combo box
        self.analysis_type_combo_box = qt.QComboBox()
        analysys_type_name_list = [analysis_cls.name for analysis_cls in self.analysis_types]
        default_analysis_type = HistogramInDepthAnalysis.name
        self.analysis_type_combo_box.addItems(analysys_type_name_list)
        self.analysis_type_combo_box.setCurrentText(default_analysis_type)
        form_layout.addRow("Analysis: ", self.analysis_type_combo_box)

        # Directory selection widget
        self.directory_input_path_line_edit = ctk.ctkPathLineEdit()
        self.directory_input_path_line_edit.filters = ctk.ctkPathLineEdit.Dirs
        self.directory_input_path_line_edit.settingKey = "ioDirInputSegInspector"
        self.directory_input_path_line_edit.setToolTip(
            "Directory with several GeoSlicer projects/folders, one for each Thin section image at a given depth. The name of the projects must finish with the depth info, such as “Well_5000,00”."
        )
        self.directory_input_path_line_edit.setCurrentPath("")
        form_layout.addRow("Projects folder: ", self.directory_input_path_line_edit)

        # Table widget that shows directory important information
        self.loaded_files_table = self._create_loaded_files_table_widget()
        form_layout.addRow(self.loaded_files_table)

        # Populate configuration widget for analysis types
        self.analysis_type_config_widgets = qt.QStackedWidget()
        form_layout.addRow(self.analysis_type_config_widgets)
        self.null_type_widget = qt.QWidget()
        self.analysis_type_config_widgets.addWidget(self.null_type_widget)
        for type in self.analysis_types:
            widget = type.config_widget
            self.analysis_type_config_widgets.addWidget(widget)
            widget.output_name_changed.connect(lambda model=type: self._on_output_name_changed(model))

        self.output_name = qt.QLineEdit()
        form_layout.addRow("Output name: ", self.output_name)

        self.generate_button = qt.QPushButton("Generate")
        self.generate_button.toolTip = "Generate report."
        self.generate_button.enabled = False
        self.generate_button.setFixedHeight(40)
        form_layout.addRow(self.generate_button)

        # connections
        self.generate_button.clicked.connect(self.on_generate_button_clicked)
        self.directory_input_path_line_edit.currentPathChanged.connect(self._on_directory_input_changed)
        self.analysis_type_combo_box.currentTextChanged.connect(self._on_analysis_type_changed)

        self._on_analysis_type_changed(self.analysis_type_combo_box.currentText)
        # Add vertical spacer
        self.layout.addStretch(1)

    def _on_output_name_changed(self, model):
        path = self.directory_input_path_line_edit.currentPath
        self.output_name.text = model.get_suggested_output_name(path)

    def _on_analysis_type_changed(self, type):
        """Handle analysis type' combobox change event.

        Args:
            type (str): the name of the analysis type.
        """
        analysis_model = self.get_analysis_model(type)
        if analysis_model is None:
            self.analysis_type_config_widgets.setCurrentWidget(self.null_type_widget)
            return

        self.analysis_type_config_widgets.setCurrentWidget(analysis_model.config_widget)

        if self.directory_input_path_line_edit.currentPath:
            self._refresh_input_report_files(self.directory_input_path_line_edit.currentPath)

    def get_analysis_model(self, desired_analysis_name):
        """Get Analysis model object based on the name

        Args:
            desired_analysis_name (str): The analysis' name

        Returns:
            AnalysisBase: The Analysis model object.
        """
        model = None
        for analysis_model in self.analysis_types:
            if analysis_model.name == desired_analysis_name:
                model = analysis_model
                break

        return model

    def on_generate_button_clicked(self):
        """Handles click event on the 'Generate' button."""
        selected_analysis_type = self.analysis_type_combo_box.currentText
        analysis_model = self.get_analysis_model(selected_analysis_type)
        if analysis_model is None:
            return

        path = self.directory_input_path_line_edit.currentPath
        name = self.output_name.text or analysis_model.get_suggested_output_name(path)
        report = analysis_model.run(path, name)
        helpers.save_path(self.directory_input_path_line_edit)

        node = self._export_report_table_node(report)

        # Show node in image log view
        slicer.modules.ImageLogDataWidget.logic.changeToLayout()
        nodeId = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemByDataNode(node)
        slicer.modules.ImageLogDataWidget.logic.addView(nodeId)

    def _create_loaded_files_table_widget(self):
        """Initialize information's table widget.

        Returns:
            qt.QTableWidget: the Table Widget object.
        """
        table_widget = qt.QTableWidget()
        table_widget.verticalHeader().setVisible(False)
        table_widget.horizontalHeader().setStretchLastSection(True)
        table_widget.setShowGrid(True)
        table_widget.setAlternatingRowColors(True)
        table_widget.setSelectionMode(table_widget.NoSelection)

        return table_widget

    def _on_directory_input_changed(self, folder):
        """Handles directory change event

        Args:
            folder (str): the directory string.
        """
        self._clear_table()

        if folder == "" or not os.path.isdir(folder):
            message = "The selected path is invalid. Please select a directory."
            logging.warning(message)
            qt.QMessageBox.information(slicer.util.mainWindow(), "Error", message)
            return

        self._refresh_input_report_files(folder)

    def _refresh_input_report_files(self, folder):
        selected_analysis_type = self.analysis_type_combo_box.currentText
        analysis_model = self.get_analysis_model(selected_analysis_type)
        if analysis_model is None:
            message = "The selected analysis' type is invalid. Please, contact the technical support."
            logging.warning(message)
            qt.QMessageBox.information(slicer.util.mainWindow(), "Error", message)
            return

        try:
            table_data = analysis_model.refresh_input_report_files(folder)
            self._on_output_name_changed(analysis_model)
        except RuntimeError as error:
            logging.warning(error)
            qt.QMessageBox.information(slicer.util.mainWindow(), "Error", error)
        else:
            self._update_table(table_data)

    def _clear_table(self):
        self.loaded_files_table.clearContents()
        self.loaded_files_table.setRowCount(0)
        self.loaded_files_table.setColumnCount(0)
        self.loaded_files_table.setHorizontalHeaderLabels([])

    def _update_table(self, table_data: pd.DataFrame):
        """Handles table's information update.

        Args:
            table_data (pd.DataFrame): The data to be populated at the table widget.
        """
        total_rows = table_data.shape[0]
        columns = list(table_data.columns)

        self._clear_table()
        self.loaded_files_table.rowCount = total_rows
        self.loaded_files_table.setColumnCount(len(columns))
        self.loaded_files_table.setHorizontalHeaderLabels(columns)

        success = True
        for idx, column in enumerate(columns):
            array = table_data[column]
            result = self._add_column_to_table(idx, array)
            success = success and result

        self.generate_button.enabled = total_rows > 0 and success

    def _add_column_to_table(self, column_index, data):
        """Wrapper for populating table's column.

        Args:
            column_index (integer): the column's index
            data (list, array): the column's data
        """

        def create_text_table_item(text):
            item = qt.QTableWidgetItem(text)
            flags = ~qt.Qt.ItemIsEditable
            original_flags = item.flags()
            item.setFlags(qt.Qt.ItemFlag(original_flags and flags))
            return item

        success = True
        for row, element in enumerate(data):
            item = create_text_table_item(str(element))
            if element == FILE_NOT_FOUND:
                item.setForeground(qt.QBrush(qt.QColor(255, 0, 0)))
                success = False
            self.loaded_files_table.setItem(row, column_index, item)
        return success

    def _export_report_table_node(self, report):
        """Handle report export to a table node.

        Args:
            report (AnalysisReport): the AnalysisReport object
        """
        default_orientation = TableDataOrientation.ROW.value
        if isinstance(report.config, dict):
            orientation = report.config.get(TableDataOrientation.name(), default_orientation)
        else:
            orientation = default_orientation

        table_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", f"{report.name}")
        if orientation == TableDataOrientation.ROW.value:
            table_node.SetUseColumnNameAsColumnHeader(True)
            table_node.SetUseFirstColumnAsRowHeader(True)

            df = pd.DataFrame.from_dict(report.data, orient="index")
            df.sort_index(ascending=True, inplace=True)

            # Workaround to create a row header
            table_was_modified = table_node.StartModify()
            header_array = vtk.vtkStringArray()
            for header in list(df.index):
                header_array.InsertNextValue(header)
            table_node.AddColumn(header_array)
            table_node.Modified()
            table_node.EndModify(table_was_modified)

            dataFrameToTableNode(dataFrame=df, tableNode=table_node)
            # Rename first table's cell random name
            table_node.RenameColumn(0, "")
        else:
            df = pd.DataFrame.from_dict(report.data)
            df.sort_values(by=df.columns[0], ascending=True, inplace=True)
            dataFrameToTableNode(dataFrame=df, tableNode=table_node)

        for key, values in report.config.items():
            table_node.SetAttribute(str(key), str(values))
        return table_node
