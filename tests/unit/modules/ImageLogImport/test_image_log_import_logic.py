from commons.slicer.image_log.import_logic import get_valid_folder_volume_name
from unittest.mock import MagicMock

import pytest
import slicer


@pytest.mark.parametrize(
    "name, volume_id, expected_valid_name",
    [
        pytest.param("WELL_NAME [unit/unit]", 0, "WELL_NAME [unit_unit]"),
        pytest.param("WELL_NAME [unit/unit]", 1, None),
        pytest.param("WELL_NAME {unit/unit}", 0, "WELL_NAME {unit_unit}"),
        pytest.param("WELL_NAME <unit/unit>", 0, "WELL_NAME _unit_unit_"),
        pytest.param("WELL_NAME [unit.unit]", 0, "WELL_NAME [unit.unit]"),
        pytest.param("WELL_NAME [%]", 0, "WELL_NAME [%]"),
        pytest.param("WELL_NAME [<>:/\\|?*]", 0, "WELL_NAME [________]"),
    ],
)
def test_get_valid_folder_volume_name(name, volume_id, expected_valid_name):
    mock_subject_hierarchy_node = MagicMock()
    mock_subject_hierarchy_node.GetItemChildWithName.return_value = volume_id
    slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode.return_value = mock_subject_hierarchy_node

    valid_name_output = get_valid_folder_volume_name(name, "frame_id")
    assert valid_name_output == expected_valid_name
