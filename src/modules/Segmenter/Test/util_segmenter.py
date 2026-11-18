from commons.slicer.node_attributes import NodeEnvironment
from commons.slicer.tests.utils import wait_cli_to_finish, load_project, save_project, close_project
from commons.slicer.helpers import moveNodeTo, getCurrentEnvironment
import shutil

import numpy as np
import os

import qt
import slicer

from .util_instance_segmenter import (
    get_widgets as get_instance_segmenter_widgets,
    pre_trained_model_parameters_selection_and_run as instance_segmenter_configure_and_run,
    common_recommended_settings_test_process,
)

TEST_RESOURCES_DIR = os.path.join(os.path.dirname(__file__), "Resources")
TEXTURA_SINTETICO_2D_PROJECT_FILE = os.path.join(
    TEST_RESOURCES_DIR, "textura_sintetico_2d", "textura_sintetico_2d.mrml"
)
TEXTURA_SINTETICO_3D_PROJECT_FILE = os.path.join(
    TEST_RESOURCES_DIR, "textura_sintetico_3d", "textura_sintetico_3d.mrml"
)
QEMSCAN_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "QEMSCAN", "QEMSCAN.mrml")
MICROCT_BORDER_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "microct_border", "microct_border.mrml")
PORE_CLEANING_PROJECT_FILE = os.path.join(TEST_RESOURCES_DIR, "pore_cleaning", "pore_cleaning.mrml")
THIN_SECTION_INSTANCE_SEGMENTER_PROJECT_FILE = os.path.join(
    TEST_RESOURCES_DIR, "ThinSectionInstanceSegTests", "ThinSectionInstanceSegTests.mrml"
)

RANDOM_FOREST_METHOD_LABEL = "Random Forest"
BAYESIAN_INFERENCE_METHOD_LABEL = "Bayesian Inference"
PRE_TRAINED_MODEL_LABEL = "Pre-trained models"


def populate_widgets(cls):
    """Initialize dictionary with module's interface widgets reference."""

    cls._widgets = {
        "create_classifier_radio_button": cls.find_widget("Create Classifier Radio"),
        "load_classifier_radio_button": cls.find_widget("Load Classifier Radio"),
        "user_classifier_radio_button": cls.find_widget("User Classifier Radio"),
        "classifier_input_combo_box": cls.find_widget("Classifier Input ComboBox"),
        "user_classifier_input_combo_box": cls.find_widget("User Classifier Input ComboBox"),
        "pore_model_type_radio_button": cls.find_widget("Pore Models Radio Button"),
        "multiphase_model_type_radio_button": cls.find_widget("Multiphase Models Radio Button"),
        "textural_structures_model_type_radio_button": cls.find_widget("Textural Structures Models Radio Button"),
        "basins_model_type_radio_button": cls.find_widget("Basins Models Radio Button"),
        "cleaning_collapsible_button": cls.find_widget("Cleaning Collapsible Button"),
        "remove_spurious_check_box": cls.find_widget("Remove Spurious CheckBox"),
        "clean_resin_check_box": cls.find_widget("Clean Resin CheckBox"),
        "extra_cleaning_image_combo_box": cls.find_widget("PX For Cleaning ComboBox"),
        "smart_registration_check_box": cls.find_widget("Smart Registration CheckBox"),
        "single_shot_input": cls.find_widget("SingleShot Input"),
        "extra_image_1_combo_box": cls.find_widget("Volume 2 ComboBox"),
        "extra_image_2_combo_box": cls.find_widget("Volume 3 ComboBox"),
        "methods_combo_box": cls.find_widget("Methods ComboBox"),
        "features_table": cls.find_widget("Features Table"),
        "kernel_size_line_edit": cls.find_widget("Kernel Size Line Edit"),
        "kernel_type_combo_box": cls.find_widget("Kernel Type ComboBox"),
        "unsafe_memory_check_box": cls.find_widget("Unsafe Memory CheckBox"),
        "keep_features_check_box": cls.find_widget("Keep features CheckBox"),
        "output_prefix_line_edit": cls.find_widget("Output Prefix Line Edit"),
        "apply_button": cls.find_widget("Apply Button"),
    }

    for key, widget in cls._widgets.items():
        cls.assertIsNotNone(widget, msg=f"{key} widget not found!")

    cls._widgets["model_type_radio_buttons_group"] = {
        "Pore": cls._widgets.pop("pore_model_type_radio_button"),
        "Multiphase": cls._widgets.pop("multiphase_model_type_radio_button"),
        "Textural Structures": cls._widgets.pop("textural_structures_model_type_radio_button"),
        "Basins": cls._widgets.pop("basins_model_type_radio_button"),
    }

    cls._widgets.update(get_instance_segmenter_widgets(cls))


def select_segment(widget: qt.QListWidget, segment_labels):
    """Wrapper for segment selection at the segment list widget

    Args:
        widget (qt.QListWidget): the list widget
        segment_labels (list or str): the name of the desired segments to be selected

    Returns:
        bool: True
    """
    if widget is None:
        return False

    if isinstance(segment_labels, str):
        segment_labels = [segment_labels]

    for index in range(widget.count):
        item = widget.item(index)
        if any(map(item.text().__contains__, segment_labels)):
            item.setCheckState(qt.Qt.Checked)

    return True


def common_successful_test_process(cls, *args, **kwargs):
    """Wrapper for different methods's successful test process"""
    method = kwargs.get("method")

    if method == RANDOM_FOREST_METHOD_LABEL:
        random_forest_successful_test_process(cls, *args, **kwargs)
    elif method == BAYESIAN_INFERENCE_METHOD_LABEL:
        bayesian_inference_successful_test_process(cls, *args, **kwargs)
    elif method == PRE_TRAINED_MODEL_LABEL:
        pre_trained_successful_test_process(cls, *args, **kwargs)
    else:
        raise NotImplementedError(f"The method {method} data successful test process was not implemented.")


def generate_template(project_file: str, template_prefix: str):
    """
    Set the last segmentation as the new template
    and save the project.
    """

    project_file_name = os.path.basename(project_file)
    project_folder_name = os.path.basename(os.path.dirname(project_file))

    try:
        # delete old template
        old_template = slicer.util.getNode(template_prefix)
        slicer.mrmlScene.RemoveNode(old_template)
    except slicer.util.MRMLNodeNotFoundException:
        print("Old template not found. New segmentation will be used as template.")
    except Exception as error:
        raise error

    # set segmenteation as new template
    new_template = slicer.util.getNode(f"{template_prefix}_Segmentation")
    new_template.SetName(template_prefix)

    # move new template to root
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    sceneItemID = shNode.GetSceneItemID()
    templatesFolderID = shNode.GetItemChildWithName(sceneItemID, "templates")
    moveNodeTo(templatesFolderID, new_template)

    # save project in tmp file
    os.makedirs(os.path.join(TEST_RESOURCES_DIR, "tmp"), exist_ok=True)
    save_project(os.path.join(TEST_RESOURCES_DIR, "tmp", project_folder_name, project_file_name))
    close_project()

    def move_contents(source_directory, destination_directory):
        os.makedirs(destination_directory, exist_ok=True)

        for item in os.listdir(source_directory):
            source_item_path = os.path.join(source_directory, item)
            destination_item_path = os.path.join(destination_directory, item)

            shutil.move(source_item_path, destination_item_path)

    def delete_read_only_dir(directory):
        os.chmod(directory, 0o777)
        shutil.rmtree(directory)

    # delete old project and move tmp project to main folder, replacing the old project
    delete_read_only_dir(os.path.join(TEST_RESOURCES_DIR, project_folder_name))
    move_contents(
        os.path.join(TEST_RESOURCES_DIR, "tmp", project_folder_name),
        os.path.join(TEST_RESOURCES_DIR, project_folder_name),
    )
    delete_read_only_dir(os.path.join(TEST_RESOURCES_DIR, "tmp", project_folder_name))
    delete_read_only_dir(os.path.join(TEST_RESOURCES_DIR, "tmp"))


def pre_trained_model_selection(cls, pre_trained_model_type, pre_trained_model):
    # Retrieve widgets of interest
    create_classifier_radio_button = cls._widgets["create_classifier_radio_button"]
    load_classifier_radio_button = cls._widgets["load_classifier_radio_button"]
    model_type_radio_buttons_group = cls._widgets["model_type_radio_buttons_group"]
    classifier_input_combo_box = cls._widgets["classifier_input_combo_box"]

    create_classifier_radio_button.setChecked(False)
    load_classifier_radio_button.setChecked(True)

    ###
    # This already happens in setup, but using the real current environment. Only inside the test function (here)
    # the simulated environment is used. So, ThinSection and MicroCT tests can run sucessfully regardless the
    # current real environment.
    cls._module_widget.enter()
    ###

    cls.assertTrue(pre_trained_model_type in model_type_radio_buttons_group)
    model_type_radio_buttons_group[pre_trained_model_type].toggle()

    classifier_input_combo_box.setCurrentText(pre_trained_model)
    cls.assertTrue(classifier_input_combo_box.currentText == pre_trained_model)


def pre_trained_model_parameters_selection_and_run(cls, *args, **kwargs):
    pre_trained_model_type = kwargs.get("pre_trained_model_type")
    project_file = kwargs.get("project_file")
    image_name = kwargs.get("image_name")
    soi_name = kwargs.get("soi_name")
    extra_image1_name = kwargs.get("extra_image1_name")
    extra_image2_name = kwargs.get("extra_image2_name")
    template_prefix = kwargs.get("template_prefix")
    update_template = kwargs.get("update_template")
    remove_spurious = kwargs.get("remove_spurious")
    clean_resin = kwargs.get("clean_resin")
    extra_cleaning_image_name = kwargs.get("extra_cleaning_image_name")
    smart_registration = kwargs.get("smart_registration")

    image_node = slicer.util.getNode(image_name)
    cls.assertIsNotNone(image_node)

    if soi_name is not None:
        soi_node = slicer.util.getNode(soi_name)
        cls.assertIsNotNone(soi_node)
    else:
        soi_node = None

    if extra_image1_name is not None:
        extra_image1_node = slicer.util.getNode(extra_image1_name)
        cls.assertIsNotNone(extra_image1_node)
    else:
        extra_image1_node = None

    if extra_image2_name is not None:
        extra_image2_node = slicer.util.getNode(extra_image2_name)
        cls.assertIsNotNone(extra_image2_node)
    else:
        extra_image2_node = None

    # Retrieve widgets of interest
    single_shot_input = cls._widgets["single_shot_input"]
    extra_image_1_combo_box = cls._widgets["extra_image_1_combo_box"]
    extra_image_2_combo_box = cls._widgets["extra_image_2_combo_box"]
    cleaning_collapsible_button = cls._widgets["cleaning_collapsible_button"]
    remove_spurious_check_box = cls._widgets["remove_spurious_check_box"]
    clean_resin_check_box = cls._widgets["clean_resin_check_box"]
    extra_cleaning_image_combo_box = cls._widgets["extra_cleaning_image_combo_box"]
    smart_registration_check_box = cls._widgets["smart_registration_check_box"]
    output_prefix_line_edit = cls._widgets["output_prefix_line_edit"]
    apply_button = cls._widgets["apply_button"]

    single_shot_input.referenceInput.setCurrentNode(image_node)

    if soi_node is not None:
        single_shot_input.soiInput.setCurrentNode(soi_node)
        cls.assertTrue(single_shot_input.soiInput.currentNode() == soi_node)

    if extra_image1_node is not None:
        extra_image_1_combo_box.setCurrentNode(extra_image1_node)
        cls.assertTrue(extra_image_1_combo_box.currentNode() == extra_image1_node)

    if extra_image2_node is not None:
        extra_image_2_combo_box.setCurrentNode(extra_image2_node)
        cls.assertTrue(extra_image_2_combo_box.currentNode() == extra_image2_node)

    cls.assertTrue(single_shot_input.referenceInput.currentNode() == image_node)

    output_prefix_line_edit.setText(template_prefix)

    cls._module_widget.deterministicPreTrainedModels = True

    # Pore Cleaning
    current_env = getCurrentEnvironment()
    cls.assertTrue(
        cleaning_collapsible_button.isVisible()
        == (
            (current_env is not None)
            and (current_env.value == NodeEnvironment.THIN_SECTION.value)
            and (pre_trained_model_type == "Pore")
        )
    )
    if cleaning_collapsible_button.isVisible():
        remove_spurious = (remove_spurious is not None) and remove_spurious
        clean_resin = (clean_resin is not None) and clean_resin
        smart_registration = (smart_registration is not None) and smart_registration

        remove_spurious_check_box.setChecked(remove_spurious)
        clean_resin_check_box.setChecked(clean_resin)

        cls.assertTrue(extra_cleaning_image_combo_box.isVisible() == clean_resin)

        if clean_resin:
            cls.assertTrue(extra_cleaning_image_combo_box.isEnabled() != extra_image_1_combo_box.isVisible())

            if extra_cleaning_image_combo_box.isEnabled():
                if extra_cleaning_image_name is not None:
                    extra_cleaning_image_node = slicer.util.getNode(extra_cleaning_image_name)
                    cls.assertIsNotNone(extra_cleaning_image_node)
                else:
                    extra_cleaning_image_node = None

                extra_cleaning_image_combo_box.setCurrentNode(extra_cleaning_image_node)
                cls.assertTrue(extra_cleaning_image_combo_box.currentNode() == extra_cleaning_image_node)
            else:
                extra_cleaning_image_node = extra_cleaning_image_combo_box.currentNode()
                cls.assertTrue(extra_cleaning_image_node == extra_image1_node)

            cls.assertTrue(smart_registration_check_box.isVisible() == (extra_cleaning_image_node is not None))
            if smart_registration_check_box.isVisible():
                smart_registration_check_box.setChecked(smart_registration)
        else:
            cls.assertFalse(smart_registration_check_box.isVisible())

    # Run
    apply_button.clicked()

    cli_queue = cls._module_widget.cliQueue
    cls.assertIsNotNone(cli_queue)
    wait_cli_to_finish(cli_queue)

    assert cli_queue.get_error_message() is None, f"CLI error: '{cli_queue.get_error_message()}'"

    if update_template is True:
        generate_template(project_file, template_prefix)
        return

    # Check of the results
    output_segmentation_node = slicer.util.getNode(f"{template_prefix}_Segmentation")
    cls.assertIsNotNone(output_segmentation_node)
    output = output_segmentation_node.GetSegmentation()

    template_segmentation_node = slicer.util.getNode(template_prefix)
    cls.assertIsNotNone(template_segmentation_node)
    template = template_segmentation_node.GetSegmentation()

    ## Number of segments is equal?
    cls.assertTrue(output.GetNumberOfSegments() == template.GetNumberOfSegments())

    output_segmentation_names = [output.GetNthSegment(j).GetName() for j in range(output.GetNumberOfSegments())]
    template_segmentation_names = [template.GetNthSegment(j).GetName() for j in range(template.GetNumberOfSegments())]

    ## Names of the segments are equal?
    np.testing.assert_array_equal(output_segmentation_names, template_segmentation_names)

    ## Segments are at the same locations?
    output_labelmap_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
    slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(
        output_segmentation_node, output_labelmap_node, image_node
    )
    output_array = slicer.util.arrayFromVolume(output_labelmap_node)

    template_labelmap_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
    slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(
        template_segmentation_node, template_labelmap_node, image_node
    )
    template_array = slicer.util.arrayFromVolume(template_labelmap_node)

    accuracy = np.isclose(output_array, template_array).sum() / template_array.size
    assert accuracy >= 0.97, f"Expected accuracy >= 0.97, but got {accuracy}"


def pre_trained_successful_test_process(cls, *args, **kwargs):
    """Handle common interface configurations for pre-trained model usage.

    Raises:
        RuntimeError: When using invalid method or input.
    """
    method = kwargs.get("method")

    if method != PRE_TRAINED_MODEL_LABEL:
        raise RuntimeError(f"Unable to execute test process for method {method} using the pre-trained model handler.")

    pre_trained_model_type = kwargs.get("pre_trained_model_type")
    pre_trained_model = kwargs.get("pre_trained_model")
    project_file = kwargs.get("project_file")
    image_name = kwargs.get("image_name")
    template_prefix = kwargs.get("template_prefix")
    template_folder = kwargs.get("template_folder")

    if project_file is None or image_name is None or (template_prefix is None and template_folder is None):
        raise RuntimeError("Invalid inputs")

    load_project(project_file)

    pre_trained_model_selection(cls, pre_trained_model_type=pre_trained_model_type, pre_trained_model=pre_trained_model)
    if pre_trained_model_type != "Textural Structures":
        pre_trained_model_parameters_selection_and_run(cls, *args, **kwargs)
    else:
        instance_segmenter_configure_and_run(cls, *args, **kwargs)


def cleaning_visibility_test_on_pre_trained(cls, shoud_be_visible_decider):
    create_classifier_radio_button = cls._widgets["create_classifier_radio_button"]
    load_classifier_radio_button = cls._widgets["load_classifier_radio_button"]
    user_classifier_radio_button = cls._widgets["user_classifier_radio_button"]
    classifier_input_combo_box = cls._widgets["classifier_input_combo_box"]
    model_type_radio_buttons_group = cls._widgets["model_type_radio_buttons_group"]

    cleaning_collapsible_button = cls._widgets["cleaning_collapsible_button"]

    apply_button = cls._widgets["apply_button"]

    cls._module_widget.enter()

    create_classifier_radio_button.setChecked(False)
    user_classifier_radio_button.setChecked(False)
    load_classifier_radio_button.setChecked(True)

    for model_type, button in model_type_radio_buttons_group.items():
        if not button.visible:
            continue

        button.toggle()

        for i in range(classifier_input_combo_box.count):
            pre_trained_model = classifier_input_combo_box.itemText(i)
            classifier_input_combo_box.setCurrentText(pre_trained_model)
            cls.assertTrue(classifier_input_combo_box.currentText == pre_trained_model)
            cls.assertTrue(apply_button.enabled is False)
            cls.assertTrue(cleaning_collapsible_button.visible is shoud_be_visible_decider(model_type))


def buttons_visibility_test_on_pre_trained(cls, shoud_be_visible_decider):
    create_classifier_radio_button = cls._widgets["create_classifier_radio_button"]
    load_classifier_radio_button = cls._widgets["load_classifier_radio_button"]
    user_classifier_radio_button = cls._widgets["user_classifier_radio_button"]

    model_type_radio_buttons_group = cls._widgets["model_type_radio_buttons_group"]

    cls._module_widget.enter()

    create_classifier_radio_button.setChecked(False)
    user_classifier_radio_button.setChecked(False)
    load_classifier_radio_button.setChecked(True)

    for model_type, button in model_type_radio_buttons_group.items():
        assert button.visible == shoud_be_visible_decider(model_type)


def instance_segmenter_recommended_settings_test_process(cls, **kwargs):
    common_recommended_settings_test_process(cls, **kwargs)


def random_forest_successful_test_process(cls, *args, **kwargs):
    """Handle common interface configurations for Random Forest usage.

    Raises:
        RuntimeError: When using invalid input related to the current method.
    """
    method = kwargs.get("method")

    if method != RANDOM_FOREST_METHOD_LABEL:
        raise Exception("Unable to execute test process for method {method} using the Random Forest method handler.")

    project_file = kwargs.get("project_file")
    segmentation_name = kwargs.get("segmentation_name")
    classifier_input = kwargs.get("classifier_input")
    image_name = kwargs.get("image_name")
    soi_name = kwargs.get("soi_name")
    extra_image1_name = kwargs.get("extra_image1_name")
    extra_image2_name = kwargs.get("extra_image2_name")
    template_prefix = kwargs.get("template_prefix")
    features = kwargs.get("features")
    output_prefix_line_edit = cls._widgets["output_prefix_line_edit"]
    random_seed = kwargs.get("random_seed")
    keep_features = kwargs.get("keep_features")
    update_template = kwargs.get("update_template")
    features_names = kwargs.get("features_names")

    if classifier_input is None:
        if (
            project_file is None
            or segmentation_name is None
            or image_name is None
            or template_prefix is None
            or method is None
        ):
            raise RuntimeError("Invalid inputs")
    else:
        if project_file is None or image_name is None or template_prefix is None:
            raise RuntimeError("Invalid inputs")

    load_project(project_file)

    if segmentation_name is not None:
        segmentation_node = slicer.util.getNode(segmentation_name)
        cls.assertIsNotNone(segmentation_node)
    else:
        segmentation_node = None

    if classifier_input is not None:
        classifier_node = slicer.util.getNode(classifier_input)
        cls.assertIsNotNone(classifier_node)
    else:
        classifier_node = None

    image_node = slicer.util.getNode(image_name)
    cls.assertIsNotNone(image_node)

    if soi_name is not None:
        soi_node = slicer.util.getNode(soi_name)
        cls.assertIsNotNone(soi_node)
    else:
        soi_node = None

    if extra_image1_name is not None:
        extra_image1_node = slicer.util.getNode(extra_image1_name)
        cls.assertIsNotNone(extra_image1_node)
    else:
        extra_image1_node = None

    if extra_image2_name is not None:
        extra_image2_node = slicer.util.getNode(extra_image2_name)
        cls.assertIsNotNone(extra_image2_node)
    else:
        extra_image2_node = None

    # Retrieve widgets of interest
    create_classifier_radio_button = cls._widgets["create_classifier_radio_button"]
    user_classifier_radio_button = cls._widgets["user_classifier_radio_button"]
    user_classifier_input_combo_box = cls._widgets["user_classifier_input_combo_box"]
    single_shot_input = cls._widgets["single_shot_input"]
    extra_image_1_combo_box = cls._widgets["extra_image_1_combo_box"]
    extra_image_2_combo_box = cls._widgets["extra_image_2_combo_box"]
    methods_combo_box = cls._widgets["methods_combo_box"]
    features_table = cls._widgets["features_table"]
    cleaning_collapsible_button = cls._widgets["cleaning_collapsible_button"]
    apply_button = cls._widgets["apply_button"]
    keep_features_check_box = cls._widgets["keep_features_check_box"]

    if classifier_input is None:
        create_classifier_radio_button.setChecked(True)
        single_shot_input.mainInput.setCurrentNode(segmentation_node)
        cls.assertTrue(single_shot_input.mainInput.currentNode() == segmentation_node)
    else:
        user_classifier_radio_button.setChecked(True)
        user_classifier_input_combo_box.setCurrentNode(classifier_node)
        cls.assertTrue(user_classifier_input_combo_box.currentNode() == classifier_node)

    single_shot_input.referenceInput.setCurrentNode(image_node)

    if soi_node is not None:
        single_shot_input.soiInput.setCurrentNode(soi_node)
        cls.assertTrue(single_shot_input.soiInput.currentNode() == soi_node)

    if extra_image1_node is not None:
        extra_image_1_combo_box.setCurrentNode(extra_image1_node)
        cls.assertTrue(extra_image_1_combo_box.currentNode() == extra_image1_node)

    if extra_image2_node is not None:
        extra_image_2_combo_box.setCurrentNode(extra_image2_node)
        cls.assertTrue(extra_image_2_combo_box.currentNode() == extra_image2_node)

    if classifier_input is None:
        methods_combo_box.setCurrentText(method)

        # TODO (PL-1732): Testar as janelas de seleção de parametros e tabela
        cls.assertTrue(features_table.rowCount == 0)

        for filter_func in features.keys():
            item = qt.QTableWidgetItem(filter_func)
            row = features_table.rowCount
            features_table.insertRow(row)
            features_table.setColumnCount(2)
            features_table.setItem(row, 0, item)

            string = []
            if isinstance(features[filter_func], dict):
                for key in features[filter_func].keys():
                    string.append(f"{key}={features[filter_func][key]}")
                string = ",".join(string)
            else:
                string = ""

            options = qt.QTableWidgetItem(string)
            features_table.setItem(row, 1, options)

        cls.assertTrue(features_table.rowCount > 0)

        cls._module_widget.methodSelector.widget(0).seed_rng = random_seed
        cls._module_widget.methodSelector.widget(0).customFilters = features

        if features_table.rowCount > 0:
            apply_button.enabled = True

        cls.assertTrue(single_shot_input.mainInput.currentNode() == segmentation_node)
        cls.assertTrue(methods_combo_box.currentText == method)

    cls.assertTrue(single_shot_input.referenceInput.currentNode() == image_node)
    cls.assertTrue(apply_button.enabled)

    if keep_features is not None:
        keep_features_check_box.setChecked(keep_features)
        cls.assertTrue(keep_features_check_box.isChecked() == keep_features)
    else:
        keep_features_check_box.setChecked(False)

    output_prefix_line_edit.setText(template_prefix)

    cls.assertFalse(cleaning_collapsible_button.isVisible())

    # Run
    apply_button.clicked()

    cli_queue = cls._module_widget.cliQueue
    cls.assertIsNotNone(cli_queue)
    wait_cli_to_finish(cli_queue)

    assert cli_queue.get_error_message() is None, f"CLI error: '{cli_queue.get_error_message()}'"

    if update_template:
        generate_template(project_file, template_prefix)
        return

    # Check features
    if keep_features_check_box.isChecked():
        for feature_name in features_names:
            feature_node = slicer.util.getNode(feature_name)
            feature_template_node = slicer.util.getNode(f"{feature_name}_Template")

            cls.assertIsNotNone(feature_node)
            cls.assertIsNotNone(feature_template_node)

            feature_array = slicer.util.arrayFromVolume(feature_node)
            feature_template_array = slicer.util.arrayFromVolume(feature_template_node)

            np.testing.assert_array_equal(feature_array, feature_template_array)

    # Check of the results
    output_segmentation_node = slicer.util.getNode(f"{template_prefix}_Segmentation")
    cls.assertIsNotNone(output_segmentation_node)
    output = output_segmentation_node.GetSegmentation()

    template_segmentation_node = slicer.util.getNode(template_prefix)
    cls.assertIsNotNone(template_segmentation_node)
    template = template_segmentation_node.GetSegmentation()

    ## Number of segments is equal?
    cls.assertTrue(output.GetNumberOfSegments() == template.GetNumberOfSegments())

    output_segmentation_names = [output.GetNthSegment(j).GetName() for j in range(output.GetNumberOfSegments())]
    template_segmentation_names = [template.GetNthSegment(j).GetName() for j in range(template.GetNumberOfSegments())]

    ## Names of the segments are equal?
    np.testing.assert_array_equal(output_segmentation_names, template_segmentation_names)

    ## Segments are at the same locations?
    output_labelmap_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
    slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(
        output_segmentation_node, output_labelmap_node, image_node
    )
    output_array = slicer.util.arrayFromVolume(output_labelmap_node)

    template_labelmap_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
    slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(
        template_segmentation_node, template_labelmap_node, image_node
    )
    template_array = slicer.util.arrayFromVolume(template_labelmap_node)

    accuracy = np.isclose(output_array, template_array).sum() / template_array.size
    if random_seed is not None:
        cls.assertTrue(accuracy > 0.8)
    else:
        cls.assertTrue(accuracy > 0.8)

    ## if without classifier, check also the names of segments with the annotation used
    if classifier_input is None:
        annotation = segmentation_node.GetSegmentation()
        annotation_segmentation_names = [
            annotation.GetNthSegment(j).GetName() for j in range(annotation.GetNumberOfSegments())
        ]
        np.testing.assert_array_equal(output_segmentation_names, annotation_segmentation_names)


def bayesian_inference_successful_test_process(cls, *args, **kwargs):
    """Handle common interface configurations for bayesian inference usage.

    Raises:
        RuntimeError: When using invalid input related to the current method.
    """
    method = kwargs.get("method")

    if method != BAYESIAN_INFERENCE_METHOD_LABEL:
        raise Exception(
            "Unable to execute test process for method {method} using the Bayesian Inference method handler."
        )

    project_file = kwargs.get("project_file")
    segmentation_name = kwargs.get("segmentation_name")
    image_name = kwargs.get("image_name")
    soi_name = kwargs.get("soi_name")
    extra_image1_name = kwargs.get("extra_image1_name")
    extra_image2_name = kwargs.get("extra_image2_name")
    template_prefix = kwargs.get("template_prefix")
    kernel_size = kwargs.get("kernel_size")
    kernel_type = kwargs.get("kernel_type")
    unsafe_memory_check = kwargs.get("unsafe_memory_check")
    update_template = kwargs.get("update_template")
    output_prefix_line_edit = cls._widgets["output_prefix_line_edit"]

    if (
        project_file is None
        or segmentation_name is None
        or image_name is None
        or template_prefix is None
        or method is None
    ):
        raise RuntimeError("Invalid inputs")

    load_project(project_file)

    segmentation_node = slicer.util.getNode(segmentation_name)
    cls.assertIsNotNone(segmentation_node)

    image_node = slicer.util.getNode(image_name)
    cls.assertIsNotNone(image_node)

    if soi_name is not None:
        soi_node = slicer.util.getNode(soi_name)
        cls.assertIsNotNone(soi_node)
    else:
        soi_node = None

    if extra_image1_name is not None:
        extra_image1_node = slicer.util.getNode(extra_image1_name)
        cls.assertIsNotNone(extra_image1_node)
    else:
        extra_image1_node = None

    if extra_image2_name is not None:
        extra_image2_node = slicer.util.getNode(extra_image2_name)
        cls.assertIsNotNone(extra_image2_node)
    else:
        extra_image2_node = None

    # Retrieve widgets of interest
    create_classifier_radio_button = cls._widgets["create_classifier_radio_button"]
    load_classifier_radio_button = cls._widgets["load_classifier_radio_button"]
    single_shot_input = cls._widgets["single_shot_input"]
    extra_image_1_combo_box = cls._widgets["extra_image_1_combo_box"]
    extra_image_2_combo_box = cls._widgets["extra_image_2_combo_box"]
    methods_combo_box = cls._widgets["methods_combo_box"]
    kernel_size_line_edit = cls._widgets["kernel_size_line_edit"]
    kernel_type_combo_box = cls._widgets["kernel_type_combo_box"]
    unsafe_memory_check_box = cls._widgets["unsafe_memory_check_box"]
    cleaning_collapsible_button = cls._widgets["cleaning_collapsible_button"]
    apply_button = cls._widgets["apply_button"]

    create_classifier_radio_button.setChecked(True)
    load_classifier_radio_button.setChecked(False)

    single_shot_input.mainInput.setCurrentNode(segmentation_node)
    cls.assertTrue(single_shot_input.mainInput.currentNode() == segmentation_node)

    single_shot_input.referenceInput.setCurrentNode(image_node)

    if soi_node is not None:
        single_shot_input.soiInput.setCurrentNode(soi_node)
        cls.assertTrue(single_shot_input.soiInput.currentNode() == soi_node)

    if extra_image1_node is not None:
        extra_image_1_combo_box.setCurrentNode(extra_image1_node)
        cls.assertTrue(extra_image_1_combo_box.currentNode() == extra_image1_node)

    if extra_image2_node is not None:
        extra_image_2_combo_box.setCurrentNode(extra_image2_node)
        cls.assertTrue(extra_image_2_combo_box.currentNode() == extra_image2_node)

    methods_combo_box.setCurrentText(method)

    kernel_size_line_edit.setText(kernel_size)
    cls.assertTrue(kernel_size_line_edit.text == kernel_size)

    kernel_type_combo_box.setCurrentText(kernel_type)
    cls.assertTrue(kernel_type_combo_box.currentText == kernel_type)

    unsafe_memory_check_box.setChecked(unsafe_memory_check)
    cls.assertTrue(unsafe_memory_check_box.isChecked() == unsafe_memory_check)

    cls.assertTrue(single_shot_input.referenceInput.currentNode() == image_node)

    output_prefix_line_edit.setText(template_prefix)

    cls.assertFalse(cleaning_collapsible_button.isVisible())

    # Run
    apply_button.clicked()

    cli_queue = cls._module_widget.cliQueue
    cls.assertIsNotNone(cli_queue)
    wait_cli_to_finish(cli_queue)

    assert cli_queue.get_error_message() is None, f"CLI error: '{cli_queue.get_error_message()}'"

    if update_template:
        generate_template(project_file, template_prefix)
        return

    # Check of the results
    output_segmentation_node = slicer.util.getNode(f"{template_prefix}_Segmentation")
    cls.assertIsNotNone(output_segmentation_node)
    output = output_segmentation_node.GetSegmentation()

    template_segmentation_node = slicer.util.getNode(template_prefix)
    cls.assertIsNotNone(template_segmentation_node)
    template = template_segmentation_node.GetSegmentation()

    ## Number of segments is equal?
    cls.assertTrue(output.GetNumberOfSegments() == template.GetNumberOfSegments())

    ## Names of the segments are equal?
    output_segmentation_names = [output.GetNthSegment(j).GetName() for j in range(output.GetNumberOfSegments())]
    template_segmentation_names = [template.GetNthSegment(j).GetName() for j in range(template.GetNumberOfSegments())]
    np.testing.assert_array_equal(output_segmentation_names, template_segmentation_names)

    ## check the names of segments with the annotation used
    annotation = segmentation_node.GetSegmentation()
    annotation_segmentation_names = [
        annotation.GetNthSegment(j).GetName() for j in range(annotation.GetNumberOfSegments())
    ]
    np.testing.assert_array_equal(output_segmentation_names, annotation_segmentation_names)

    ## Segments are at the same locations?
    output_labelmap_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
    slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(
        output_segmentation_node, output_labelmap_node, image_node
    )
    output_array = slicer.util.arrayFromVolume(output_labelmap_node)

    template_labelmap_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
    slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(
        template_segmentation_node, template_labelmap_node, image_node
    )
    template_array = slicer.util.arrayFromVolume(template_labelmap_node)

    accuracy = np.isclose(output_array, template_array).sum() / template_array.size
    cls.assertTrue(accuracy > 0.9)
