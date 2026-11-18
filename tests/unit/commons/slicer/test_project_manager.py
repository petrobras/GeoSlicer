from commons.slicer.project_manager import getAvailableFilename
import pytest
import tempfile
from pathlib import Path


@pytest.mark.parametrize(
    "input_file_name, files_in_directory, expected_file_name",
    [
        pytest.param("TestNode.nrrd", [], "TestNode.nrrd", id="file_name_doesnt_exist"),
        pytest.param("TestNode.nrrd", ["TestNode.nrrd"], "TestNode (1).nrrd", id="one_file_name_exists"),
        pytest.param(
            "TestNode.nrrd", ["TestNode.nrrd", "TestNode (1).nrrd"], "TestNode (2).nrrd", id="two_file_name_exists"
        ),
        pytest.param(
            "TestNode.nrrd",
            ["TestNode.nrrd", "TestNode (1).nrrd", "TestNode (2).nrrd", "TestNode (3).nrrd"],
            "TestNode (4).nrrd",
            id="four_file_name_exists",
        ),
        pytest.param("TestNode (1).nrrd", ["TestNode.nrrd"], "TestNode (1).nrrd", id="copy_file_name_doesnt_exists"),
        pytest.param(
            "TestNode (1).nrrd", ["TestNode.nrrd", "TestNode (1).nrrd"], "TestNode (2).nrrd", id="copy_file_name_exists"
        ),
        pytest.param("table.tsv", ["table.schema.tsv"], "table.tsv", id="default_table_case"),
    ],
)
def test_get_available_filename(input_file_name, files_in_directory, expected_file_name):

    with tempfile.TemporaryDirectory() as dir:
        dir_path = Path(dir)

        for file in files_in_directory:
            file_path = dir_path / file
            file_path.touch()

        unique_file_name = getAvailableFilename(input_file_name, dir_path)
        assert unique_file_name == expected_file_name, f"Expected: '{expected_file_name}', got: '{unique_file_name}'"
