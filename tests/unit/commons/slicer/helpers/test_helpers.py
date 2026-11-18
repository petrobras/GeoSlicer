from commons.slicer import helpers
from pathlib import Path
import numpy as np
import os
import pytest
import shutil
import vtk
from vtk.util import numpy_support as numpySupport


@pytest.mark.parametrize(
    "email, expected_result",
    [
        pytest.param("test@example.com", True, id="valid_email"),
        pytest.param("invalid-email@.com", False, id="invalid_email"),
        pytest.param("user@sub.domain.co.uk", True, id="valid_email_sub_domain"),
        pytest.param("user@localhost", False, id="invalid_email_2"),
        pytest.param("", False, id="empty_string"),
    ],
)
def test_valid_email(email, expected_result):
    assert helpers.isValidEmail(email) is expected_result


def test_number_array_to_label_array_keeps_signed_labels():
    array = np.array([-9999, 1, 2, 3], dtype=np.int16)
    result = helpers.numberArrayToLabelArray(array)
    assert np.array_equal(result, np.array([0, 1, 2, 3], dtype=np.int16))


def test_number_array_to_label_array_nulls_non_positive_floats():
    array = np.array([-1.0, -9999.0, np.nan, np.inf, -np.inf, 0.2, 1.6], dtype=np.float32)
    result = helpers.numberArrayToLabelArray(array)
    assert result.dtype == np.uint16
    assert np.array_equal(result, np.array([0, 0, 0, 0, 0, 0, 2], dtype=np.uint16))


def test_number_array_to_label_array_saturates_out_of_range_floats():
    array = np.array([70000.0, 65535.0], dtype=np.float32)
    result = helpers.numberArrayToLabelArray(array)
    assert np.array_equal(result, np.array([65535, 65535], dtype=np.uint16))


def test_number_array_to_label_array_keeps_unsigned_input():
    array = np.array([0, 1, 3, 15], dtype=np.uint8)
    result = helpers.numberArrayToLabelArray(array)
    assert result.dtype == np.uint8
    assert np.array_equal(result, array)


NUMERIC_VTK_SCALAR_TYPES = [
    "VTK_UNSIGNED_CHAR",
    "VTK_CHAR",
    "VTK_SIGNED_CHAR",
    "VTK_UNSIGNED_SHORT",
    "VTK_SHORT",
    "VTK_UNSIGNED_INT",
    "VTK_INT",
    "VTK_UNSIGNED_LONG_LONG",
    "VTK_LONG_LONG",
    "VTK_UNSIGNED_LONG",
    "VTK_LONG",
    "VTK_ID_TYPE",
    "VTK_FLOAT",
    "VTK_DOUBLE",
]


@pytest.mark.parametrize("typeName", NUMERIC_VTK_SCALAR_TYPES)
def test_scalar_type_label_matches_vtk_numpy_type(typeName):
    scalarType = getattr(vtk, typeName)
    expected = np.dtype(numpySupport.get_numpy_array_type(scalarType)).name
    assert helpers.getScalarTypesAsString(scalarType) == expected


@pytest.mark.parametrize("typeName", NUMERIC_VTK_SCALAR_TYPES)
def test_scalar_type_label_matches_vtk_data_type_size(typeName):
    scalarType = getattr(vtk, typeName)
    array = vtk.vtkDataArray.CreateDataArray(scalarType)
    assert np.dtype(helpers.getScalarTypesAsString(scalarType)).itemsize == array.GetDataTypeSize()


@pytest.mark.parametrize(
    "typeName, expected",
    [
        pytest.param("VTK_UNSIGNED_INT", "uint32", id="unsigned_int"),
        pytest.param("VTK_INT", "int32", id="int"),
        pytest.param("VTK_VOID", "void", id="void"),
        pytest.param("VTK_BIT", "bit", id="bit"),
    ],
)
def test_scalar_type_label_fixed_names(typeName, expected):
    assert helpers.getScalarTypesAsString(getattr(vtk, typeName)) == expected


def test_scalar_type_label_unknown_type():
    assert helpers.getScalarTypesAsString(-1) == "undefined type"


def _set_read_only(folder: Path, read_only: bool) -> None:
    for root, _, files in os.walk(folder, topdown=not read_only):
        for file in files:
            os.chmod(Path(root) / file, 0o444 if read_only else 0o644)
        os.chmod(root, 0o555 if read_only else 0o755)


def test_copy_tree_without_permissions_from_read_only_installation(tmp_path):
    """A copy of a read-only installation's folder must be writable: the report adds files to it, an update copies
    over it, and the user must be able to delete it."""
    source = tmp_path / "installation" / "streamlit"
    (source / "pages").mkdir(parents=True)
    (source / "PNM_Report.py").write_text("report")
    (source / "pages" / "page.py").write_text("page")
    destination = tmp_path / "appdata" / "streamlit"
    _set_read_only(source, True)
    try:
        helpers.copyTreeWithoutPermissions(source, destination)
        helpers.copyTreeWithoutPermissions(source, destination)
    finally:
        _set_read_only(source, False)

    assert (destination / "pages" / "page.py").read_text() == "page"
    (destination / "pages" / "static").mkdir()
    (destination / "PNM_Report.py").write_text("edited")
    shutil.rmtree(destination)
