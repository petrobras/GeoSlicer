import lasio
import os
import numpy as np
import shutil
import time
import xarray

from pathlib import Path
from commons.slicer.tests.utils import check_for_message_box, wait, process_events


RESOURCES = Path(__file__).parent / "Resources"

DATASETS = RESOURCES / "datasets"
SINGLE_WELL_DATASET_PATH = DATASETS / "single_well_dataset"
NO_PX_DATASET_PATH = DATASETS / "no_px_dataset"
MULTIWELL_DATASET_PATH = DATASETS / "multiwell_dataset"
NO_IMAGE_DATASET_PATH = DATASETS / "no_image_dataset"
INVALID_IMAGE_NAME_DATASET_PATH = DATASETS / "invalid_image_name_dataset"
NON_EXISTENT_DATASET_PATH = DATASETS / "non_existent_dataset"
TWO_TS_DATASET_PATH = DATASETS / "two_ts_dataset"
MANY_SPURIOUS_DATASET_PATH = DATASETS / "many_spurious_dataset"

TEMPLATES = RESOURCES / "templates"
SHEETS_TEMPLATE_PATH = TEMPLATES / "sheets_template"
LAS_TEMPLATE_PATH = TEMPLATES / "las_template"
NO_SPURIOUS_TEMPLATE_PATH = TEMPLATES / "no_spurious_template"
CLEAN_RESIN_PX_TEMPLATE_PATH = TEMPLATES / "clean_resin_px_template"
CLEAN_RESIN_PX_SMART_REG_TEMPLATE_PATH = TEMPLATES / "clean_resin_px_smart_reg_template"
CLEAN_RESIN_DO_NOT_USE_PX_TEMPLATE_PATH = TEMPLATES / "clean_resin_do_not_use_px_template"
CLEAN_RESIN_NO_PX_TEMPLATE_PATH = TEMPLATES / "clean_resin_no_px_template"
SINGLE_FRAG_TEMPLATE_PATH = TEMPLATES / "single_frag_template"
WATERSHED_TEMPLATE_PATH = TEMPLATES / "watershed_template"


def sort_df(df):
    df = df.reindex(sorted(df.columns), axis=1)
    return df


def _init_and_get_widget(cls):
    widget = cls._module_widget
    widget.enter()
    return widget


def delete_dir_if_exists(dir):
    if os.path.exists(dir):
        shutil.rmtree(dir)


def _wait_output_path(output_path: Path, timeout_sec: float = 10.0, raiseOnFail=False):
    if isinstance(output_path, str):
        output_path = Path(output_path)

    start = time.perf_counter()
    failed = False
    while not output_path.exists():
        wait(0.2)
        if time.perf_counter() - start >= timeout_sec:
            failed = True
            break

    if raiseOnFail and failed:
        raise RuntimeError(f"{output_path.as_posix()} doesn't exist")


def _set_checkboxes(
    widget,
    export_images=False,
    export_sheets=False,
    export_las=False,
    remove_spurious=False,
    clean_resin=False,
    use_px=False,
    reg_method=False,
    limit_frags=False,
):
    widget.exportImagesCheckbox.setChecked(export_images)
    widget.exportSheetsCheckbox.setChecked(export_sheets)
    widget.exportLASCheckbox.setChecked(export_las)
    widget.removeSpuriousCheckbox.setChecked(remove_spurious)
    widget.cleanResinCheckbox.setChecked(clean_resin)
    widget.usePXCheckbox.setChecked(use_px)
    widget.regMethodCheckbox.setChecked(reg_method)
    widget.limitFragsCheckbox.setChecked(limit_frags)

    return widget


def test_message_box(
    cls,
    input_path,
    output_path,
    result_messages,
    alternative_messages=None,
    message_timeouts_sec=2,
    buttons_texts_to_click=None,
    model_name="Bayesian small kernel",
    partit_method="Islands",
    should_apply=True,
    **checkbox_kwargs,
):
    def as_iterable(var):
        if not isinstance(var, (list, tuple)):
            return [var]
        return var

    widget = _init_and_get_widget(cls)
    widget = _set_checkboxes(widget, **checkbox_kwargs)
    widget.classifierInput.setCurrentText(model_name)
    widget.inputDirectoryLineEdit.setCurrentPath(input_path)
    widget.imageSpacingLineEdit.setText("0.1")
    widget.methodSelector.selector.setCurrentText(partit_method)
    widget.outputDirectoryLineEdit.setCurrentPath(output_path)
    process_events()

    result_messages = as_iterable(result_messages)
    message_timeouts_sec = as_iterable(message_timeouts_sec)
    buttons_texts_to_click = as_iterable(buttons_texts_to_click)
    should_apply = as_iterable(should_apply)

    message_sets = [result_messages]
    if alternative_messages is not None:
        message_sets += [as_iterable(alternative_messages)]

    for message_set in message_sets:
        try:
            for result_message, message_timeout_sec, button_text_to_click, apply in zip(
                message_set, message_timeouts_sec, buttons_texts_to_click, should_apply
            ):
                with check_for_message_box(
                    result_message, timeout_sec=message_timeout_sec, buttonTextToClick=button_text_to_click
                ):
                    if apply:
                        widget.applyButton.clicked()
                        wait(0.2)
            break
        except Exception as error:
            delete_dir_if_exists(output_path)
            raise error


def test_and_delete_results(
    cls,
    input_path,
    output_path,
    result_messages,
    alternative_messages=None,
    message_timeouts_sec=20,
    buttons_texts_to_click=None,
    model_name="Bayesian small kernel",
    partit_method="Islands",
    result_simul_callback=None,
    checks_callback=None,
    should_apply=True,
    **checkbox_kwargs,
):
    delete_dir_if_exists(output_path)

    if result_simul_callback is not None:
        result_simul_callback()

    try:
        test_message_box(
            cls,
            input_path,
            output_path,
            result_messages,
            alternative_messages,
            message_timeouts_sec,
            buttons_texts_to_click,
            model_name,
            partit_method,
            should_apply,
            **checkbox_kwargs,
        )

        if checks_callback:
            _wait_output_path(output_path=output_path)
            checks_callback()
    except Exception as error:
        delete_dir_if_exists(output_path)
        raise error
    else:
        delete_dir_if_exists(output_path)


def test_netcdf(image_name, template_results_path, output_path):
    template_file_path = Path(template_results_path) / "netCDFs" / (image_name + ".nc")
    _wait_output_path(template_file_path)
    template_nc = xarray.open_dataset(template_file_path, engine="h5netcdf")
    template_pores_mask = template_nc["Pores"]  # compare in mask level since the colors are random

    output_file_path = Path(Path(output_path) / "netCDFs" / (image_name + ".nc"))
    _wait_output_path(output_file_path)
    result_nc = xarray.open_dataset(output_file_path, engine="h5netcdf")
    result_pores_mask = result_nc["Pores"]

    np.testing.assert_array_equal(template_pores_mask, result_pores_mask)
    assert result_nc["x"][1] - result_nc["x"][0] == 0.1  # spacing


# from WorkflowTest.py which is only in release/2.4.0
def test_las_files_are_equal(las1_path, las2_path):
    def must_be_different(key, item):
        return key == "Well" and item.mnemonic == "DATE"

    las1 = lasio.read(las1_path)
    las2 = lasio.read(las2_path)
    assert las1.header.keys() == las2.header.keys()
    for key in las1.header.keys():
        las1_header = las1.header[key]
        las2_header = las2.header[key]
        assert type(las1_header) is type(las2_header)
        if isinstance(las1.header[key], list):
            assert len(las1_header) == len(las2_header)
            for las1_item, las2_item in zip(las1_header, las2_header):
                assert type(las1_item) is type(las2_item)
                assert las1_item.mnemonic == las2_item.mnemonic
                assert las1_item.unit == las2_item.unit
                assert las1_item.descr == las2_item.descr
                # VALUE COMPARISON:
                # - equals (==) will work for all types of values (including absent);
                # - np.isclose() will handle floating values that are essentially equal but diverge by precision issues;
                # - must_be_different() refers to Well.DATE, which will be different on every run
                assert (
                    las1_item.value == las2_item.value
                    or must_be_different(key, las1_item)
                    or np.isclose(las1_item.value, las2_item.value)
                )
                if isinstance(las1_item, lasio.las_items.CurveItem):
                    # Results are slightly variable for watershed, so let's verify if each of them differ by less than 1% with the template
                    epsilon = 1e-10  # for handling zero division
                    curve1 = las1_item.data + epsilon
                    curve2 = las2_item.data + epsilon
                    ratio = curve1 / curve2
                    assert np.all((ratio > 0.99) & (ratio < 1.01))
        else:
            assert las1_header == las2_header
