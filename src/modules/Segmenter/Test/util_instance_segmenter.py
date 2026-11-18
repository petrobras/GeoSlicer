from commons.slicer.tests.utils import wait_cli_to_finish, load_project, save_project

import numpy as np
import os
import slicer
import vtk
import pandas as pd
import scipy
import shutil


def vtkTableToDataFrame(tableNode):
    table = tableNode.GetTable()
    num_columns = table.GetNumberOfColumns()

    data_dict = {}
    for col_idx in range(num_columns):
        col_name = table.GetColumnName(col_idx)
        col_data = vtk.util.numpy_support.vtk_to_numpy(table.GetColumn(col_idx))
        data_dict[col_name] = col_data

    df = pd.DataFrame(data_dict)
    return df


def getNodesInRelativeFolder(shNode, relativeFolder):
    folderID = shNode.GetSceneItemID()
    for folder in relativeFolder.split("/"):
        folderID = shNode.GetItemChildWithName(folderID, folder)

    nodes = []
    children = vtk.vtkIdList()
    shNode.GetItemChildren(folderID, children)
    for i in range(children.GetNumberOfIds()):
        childID = children.GetId(i)
        node = shNode.GetItemDataNode(childID)
        nodes.append(node)

    return folderID, nodes


def get_widgets(cls):
    """Test case setup handler, applied before reloding the widgets"""

    widgets = {
        # Resources
        "resources_local_radiobutton": cls.find_widget("Local Resources RadioButton"),
        "resources_remote_radiobutton": cls.find_widget("Remote Resources RadioButton"),
        # Detector
        "model_combobox": cls.find_widget("Thin Section Instance Segmenter Model ComboBox"),
        "soi_combobox": cls.find_widget("Thin Section Instance Segmenter SOI ComboBox"),
        "input_volume_combobox": cls.find_widget("Thin Section Instance Segmenter Input Volume ComboBox"),
        # Settings
        "conf_thresh_spinbox": cls.find_widget("Confidence Threshold SpinBox"),
        "nms_thresh_spinbox": cls.find_widget("NMS Threshold SpinBox"),
        "resize_spinbox": cls.find_widget("Resize SpinBox"),
        "chunk_size_spinbox": cls.find_widget("Chunk Size SpinBox"),
        "chunk_overlap_spinbox": cls.find_widget("Chunk Overlap SpinBox"),
        "chunked_inference_checkbox": cls.find_widget("Chunked Inference CheckBox"),
        "recommended_settings_button": cls.find_widget("Recommended Settings Button"),
        # Output
        "statistics_checkbox": cls.find_widget("Statistics CheckBox"),
        "instance_output_prefix_line_edit": cls.find_widget("Thin Section Instance Segmenter Output Prefix Line Edit"),
        "instance_apply_button": cls.find_widget("Thin Section Instance Segmenter Apply Button"),
    }

    for key, widget in widgets.items():
        cls.assertIsNotNone(widget, msg=f"{key} widget not found!")

    return widgets


def pre_trained_model_selection(
    cls, pre_trained_model
):  # Not used now. Useful if ThinSectionInstanceSegmenter becomes an independent module again.
    instance_segmenter_model_combobox = cls._widgets["model_combobox"]

    # Set input settings
    cls._module_widget.enter()

    if pre_trained_model is not None:
        instance_segmenter_model_combobox.setCurrentText(pre_trained_model)
        cls.assertTrue(
            instance_segmenter_model_combobox.currentText == pre_trained_model,
            f"Expected model {pre_trained_model} but got {instance_segmenter_model_combobox.currentText}",
        )


def pre_trained_model_parameters_selection_and_run(cls, *args, **kwargs):
    # Take function arguments
    project_file = kwargs.get("project_file")
    soi_name = kwargs.get("soi_name")
    image_name = kwargs.get("image_name")
    conf_thresh = kwargs.get("conf_thresh")
    nms_thresh = kwargs.get("nms_thresh")
    resize = kwargs.get("resize")
    chunk_size = kwargs.get("chunk_size")
    chunk_overlap = kwargs.get("chunk_overlap")
    calculate_statistics = kwargs.get("calculate_statistics")
    template_folder = kwargs.get("template_folder")
    update_template = kwargs.get("update_template", False)
    compare_with_template = kwargs.get("compare_with_template", True)

    output_prefix = template_folder.split("/")[-1]

    # Retrieve widgets of interest
    ## Resources
    resources_local_radiobutton = cls._widgets["resources_local_radiobutton"]
    resources_remote_radiobutton = cls._widgets["resources_remote_radiobutton"]
    ## Model selection
    soi_combobox = cls._widgets["soi_combobox"]
    input_volume_combobox = cls._widgets["input_volume_combobox"]
    ## Settings
    conf_thresh_spinbox = cls._widgets["conf_thresh_spinbox"]
    nms_thresh_spinbox = cls._widgets["nms_thresh_spinbox"]
    resize_spinbox = cls._widgets["resize_spinbox"]
    chunk_size_spinbox = cls._widgets["chunk_size_spinbox"]
    chunk_overlap_spinbox = cls._widgets["chunk_overlap_spinbox"]
    chunked_inference_checkbox = cls._widgets["chunked_inference_checkbox"]
    ## Output
    statistics_checkbox = cls._widgets["statistics_checkbox"]
    output_prefix_line_edit = cls._widgets["instance_output_prefix_line_edit"]
    apply_button = cls._widgets["instance_apply_button"]

    image_node = slicer.util.getNode(image_name)
    cls.assertIsNotNone(image_node)

    if soi_name is not None:
        soi_node = slicer.util.getNode(soi_name)
        cls.assertIsNotNone(soi_node)
    else:
        soi_node = None

    resources_local_radiobutton.setChecked(True)
    cls.assertTrue(resources_local_radiobutton.checked)
    cls.assertTrue(not resources_remote_radiobutton.checked)

    input_volume_combobox.setCurrentNode(image_node)
    if soi_node is not None:
        soi_combobox.setCurrentNode(soi_node)
        cls.assertTrue(soi_combobox.currentNode() == soi_node)
    cls.assertTrue(input_volume_combobox.currentNode() == image_node)

    if conf_thresh is not None:
        conf_thresh_spinbox.setValue(conf_thresh)
        cls.assertTrue(conf_thresh_spinbox.value == conf_thresh)
    if nms_thresh is not None:
        nms_thresh_spinbox.setValue(nms_thresh)
        cls.assertTrue(nms_thresh_spinbox.value == nms_thresh)
    if resize is not None:
        resize_spinbox.setValue(resize)
        cls.assertTrue(resize_spinbox.value == resize)

    if chunk_size is not None:
        chunked_inference_checkbox.setChecked(True)
        chunk_size_spinbox.setValue(chunk_size)
        cls.assertTrue(chunk_size_spinbox.value == chunk_size)
    else:
        chunked_inference_checkbox.setChecked(False)

    if chunk_overlap is not None:
        chunk_overlap_spinbox.setValue(chunk_overlap)
        cls.assertTrue(chunk_overlap_spinbox.value == chunk_overlap)

    if calculate_statistics is not None:
        statistics_checkbox.setChecked(calculate_statistics)
        cls.assertTrue(statistics_checkbox.checked == calculate_statistics)

    output_prefix_line_edit.setText(output_prefix)

    # Run
    apply_button.clicked()

    cli_node = cls._module_widget.thinSectionInstanceSegmenterWidget.cliNode
    cls.assertIsNotNone(cli_node)

    wait_cli_to_finish(cli_node)
    assert cli_node.GetStatusString() == "Completed", (
        f"CLI node Status: '{cli_node.GetStatusString()}. Error: '{cli_node.GetErrorText()}'"
    )

    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

    ################################################################### Replace tests with a new run

    if update_template:
        template_folderId, template_nodes = getNodesInRelativeFolder(shNode, template_folder)
        TemplatesFolderID = shNode.GetItemParent(template_folderId)
        shNode.RemoveItem(template_folderId, True, True)

        results_folderId, results_nodes = getNodesInRelativeFolder(shNode, f"Inputs/{output_prefix} Results")
        shNode.SetItemName(results_folderId, template_folder.split("/")[1])

        shNode.SetItemParent(results_folderId, TemplatesFolderID)

        new_project_file = os.path.join(os.path.dirname(project_file), "..", "TMP", "TMP.mrml")
        old_dir = os.path.dirname(project_file)
        new_dir = os.path.abspath(os.path.dirname(new_project_file))
        if os.path.exists(new_dir):
            shutil.rmtree(new_dir)
        os.makedirs(os.path.dirname(new_project_file), exist_ok=True)

        save_project(new_project_file)

        if os.path.exists(old_dir):
            shutil.rmtree(old_dir)
        os.rename(new_dir, old_dir)
        os.rename(os.path.join(old_dir, os.path.basename(new_project_file)), project_file)

        return

    ################################################################### Beginning tests in results

    template_folderId, template_nodes = getNodesInRelativeFolder(shNode, template_folder)
    results_folderId, results_nodes = getNodesInRelativeFolder(shNode, f"Inputs/{output_prefix} Results")

    # Check results folder name
    results_folderName = shNode.GetItemName(results_folderId)
    cls.assertTrue(results_folderName == f"{output_prefix} Results")

    # Check labelmaps and tables classes names are the same
    template_nodes_names = [i.GetName() for i in template_nodes]
    results_nodes_names = [i.GetName() for i in results_nodes]
    if compare_with_template:
        cls.assertTrue(template_nodes_names == results_nodes_names)

    # Separate labelmaps and tables
    template_labelmaps = [node for node in template_nodes if node.__class__.__name__ == "vtkMRMLLabelMapVolumeNode"]
    results_labelmaps = [node for node in results_nodes if node.__class__.__name__ == "vtkMRMLLabelMapVolumeNode"]
    if calculate_statistics:
        template_tables = [node for node in template_nodes if node.__class__.__name__ == "vtkMRMLTableNode"]
        results_tables = [node for node in results_nodes if node.__class__.__name__ == "vtkMRMLTableNode"]

    for index in range(len(results_labelmaps)):  # For each class predicted:
        template_array = slicer.util.arrayFromVolume(template_labelmaps[index])
        results_array = slicer.util.arrayFromVolume(results_labelmaps[index])
        values_in_results_array = np.unique(results_array)[1:]

        # Check table values
        if calculate_statistics:
            template_df = vtkTableToDataFrame(template_tables[index])
            result_df = vtkTableToDataFrame(results_tables[index])

            results_label_column = result_df["label"].to_numpy()
            sequence = np.arange(1, len(results_label_column) + 1)

            # Check attributes and references of table
            class_name = results_labelmaps[index].GetName()
            reference_id = image_node.GetID()
            label_id = results_labelmaps[index].GetID()
            cls.assertTrue(results_tables[index].GetAttribute("InstanceEditor") == class_name)
            cls.assertTrue(results_tables[index].GetAttribute("ReferenceVolumeNode") == label_id)
            cls.assertTrue(results_tables[index].GetNodeReferenceID("InstanceEditorLabelMap") == label_id)
            cls.assertTrue(results_tables[index].GetNodeReferenceID("referenceNode") == reference_id)

            # Entries on tables are sequential?
            np.testing.assert_array_equal(results_label_column, sequence)

            # Are equal to the template?
            if compare_with_template:
                template_label_column = template_df["label"].to_numpy()
                np.testing.assert_array_equal(results_label_column, template_label_column)

            # They agree with the labels in labelmap?
            np.testing.assert_array_equal(results_label_column, values_in_results_array)

        # Names of the segments are right?
        node = results_labelmaps[index]
        colorNode = node.GetDisplayNode().GetColorNode()
        colorNames = np.array([colorNode.GetColorName(i) for i in range(colorNode.GetNumberOfColors())])
        defaultNames = np.array([f"Segment {i}" for i in range(colorNode.GetNumberOfColors())])
        defaultNames[0] = "Background"
        np.testing.assert_array_equal(colorNames, defaultNames)

        # Segments are at the same locations as template?
        if compare_with_template:
            accuracy = np.isclose(results_array, template_array).sum() / template_array.size
            cls.assertTrue(accuracy > 0.99)

        # Are there broken labels?
        # num_labels > len(values_in_results_array) can happen since labels could be neighbours
        label, num_labels = scipy.ndimage.label(results_array)
        cls.assertTrue(num_labels <= len(values_in_results_array))


def common_successful_test_process(cls, *args, **kwargs):
    """Wrapper for different methods's successful test process

    Raises:
        RuntimeError: When using invalid input related to the current method.
    """
    pre_trained_model = kwargs.get("pre_trained_model")
    project_file = kwargs.get("project_file")
    image_name = kwargs.get("image_name")
    template_folder = kwargs.get("template_folder")

    if project_file is None or image_name is None or template_folder is None:
        raise RuntimeError("Invalid inputs")

    load_project(project_file)

    pre_trained_model_selection(cls, pre_trained_model=pre_trained_model)
    pre_trained_model_parameters_selection_and_run(cls, *args, **kwargs)


def common_recommended_settings_test_process(cls, **kwargs):
    # Take function arguments
    project_file = kwargs.get("project_file")
    image_name = kwargs.get("image_name")
    conf_thresh = kwargs.get("conf_thresh")
    nms_thresh = kwargs.get("nms_thresh")
    resize = kwargs.get("resize")
    chunk_size = kwargs.get("chunk_size")
    chunk_overlap = kwargs.get("chunk_overlap")
    expected_chunk_size = kwargs.get("expected_chunk_size")
    auto_non_chunking_expected = kwargs.get("auto_non_chunking_expected")

    if project_file is None or image_name is None:
        raise RuntimeError("Invalid inputs")

    # Retrieve widgets of interest
    ## Model selection
    input_volume_combobox = cls._widgets["input_volume_combobox"]
    ## Settings
    conf_thresh_spinbox = cls._widgets["conf_thresh_spinbox"]
    nms_thresh_spinbox = cls._widgets["nms_thresh_spinbox"]
    resize_spinbox = cls._widgets["resize_spinbox"]
    chunk_size_spinbox = cls._widgets["chunk_size_spinbox"]
    chunk_overlap_spinbox = cls._widgets["chunk_overlap_spinbox"]
    chunked_inference_checkbox = cls._widgets["chunked_inference_checkbox"]
    recommended_settings_button = cls._widgets["recommended_settings_button"]

    load_project(project_file)

    image_node = slicer.util.getNode(image_name)
    input_volume_combobox.setCurrentNode(image_node)

    chunked_inference_checkbox.setChecked(True)
    chunk_size_spinbox.setValue(chunk_size)
    chunk_overlap_spinbox.setValue(chunk_overlap)
    conf_thresh_spinbox.setValue(conf_thresh)
    nms_thresh_spinbox.setValue(nms_thresh)
    resize_spinbox.setValue(resize)

    recommended_settings_button.clicked()

    default_settings = cls._module_widget.thinSectionInstanceSegmenterWidget.default
    assert chunked_inference_checkbox.checked != auto_non_chunking_expected
    assert chunk_size_spinbox.value == expected_chunk_size
    assert chunk_overlap_spinbox.value == default_settings["chunk overlap"]
    assert conf_thresh_spinbox.value == default_settings["confidence threshold"]
    assert nms_thresh_spinbox.value == default_settings["NMS threshold"]
    assert resize_spinbox.value == default_settings["resize ratio"]
