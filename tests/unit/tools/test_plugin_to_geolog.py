from commons.slicer.helpers import make_directory_writable
from pathlib import Path
from unittest.mock import MagicMock, patch

import deploy.Geolog.plugin_to_geolog as pg
import pytest
import shutil
import tempfile


def create_processing_mmu_lines_ok():
    lines = []
    lines.append("Menu processing_menu\n")
    lines.append("{\n")
    lines.append("#if defined ( MUI_WELL )\n")
    lines.append('"Data"               +  f.menu data_menu\n')
    lines.append("#endif\n")
    lines.append("#if defined ( MUI_PROJECT )\n")
    lines.append('"Data"               +  f.menu data_menu\n')
    lines.append("#endif\n")
    lines.append("}\n")
    lines.append("\n")
    lines.append("#if defined ( MUI_WELL )\n")
    lines.append("#include <data.mmu>\n")
    lines.append("#endif\n")
    lines.append("\n")
    lines.append("#if defined ( MUI_PROJECT )\n")
    lines.append("\n")
    lines.append("Menu data_menu\n")
    lines.append("{\n")
    lines.append('  "Well Inventory"        f.exec "catalog_inventory_new"\n')
    lines.append("}\n")
    lines.append("\n")
    lines.append("#endif\n")
    lines.append("\n")
    lines.append("#include <processing+*.mmu>\n")
    return lines


# Malformed: "Menu processing_menu" is absent
def create_processing_mmu_lines_malformed1():
    lines = create_processing_mmu_lines_ok()
    lines[0] = "Menu not_the_processing_menu\n"
    return lines


# Malformed: "Menu processing_menu" braces inconsistent
def create_processing_mmu_lines_malformed2():
    lines = create_processing_mmu_lines_ok()
    lines[8] = "oops we should have a closing brace here\n"
    return lines


def write_processing_mmu_to_file(geolog_appdefaults_path: Path, lines: list[str]) -> None:
    with open(geolog_appdefaults_path / "processing.mmu", "w") as file:
        for line in lines:
            file.write(line)


@patch("deploy.Geolog.plugin_to_geolog.is_elevated", return_value=True)
@patch("deploy.Geolog.plugin_to_geolog.enable_privilege", return_value=None)
@patch("deploy.Geolog.plugin_to_geolog.add_write_permission", lambda x: None)  # Several problems within linux
class TestPluginToGeolog:
    def setup_method(self):
        self._temp_dir = Path(tempfile.TemporaryDirectory().name)
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self._geolog_path = self._temp_dir / "dummy_geolog_path"
        self._geolog_resources_path = self._geolog_path / "resources"
        self._geolog_appdefaults = self._geolog_path / "app-defaults"
        self._geoslicer_path = self._temp_dir / "dummy_geoslicer_path"

        for path in [self._geolog_path, self._geolog_resources_path, self._geolog_appdefaults, self._geoslicer_path]:
            path.mkdir(parents=True, exist_ok=True)

    def teardown_method(self):
        if self._temp_dir.exists():
            shutil.rmtree(self._temp_dir, onexc=make_directory_writable)

    def _create_test_arguments_mock(self, geolog_path: str, geoslicer_path: str) -> MagicMock:
        mock_args = MagicMock()
        mock_args.geolog_path = geolog_path
        mock_args.geoslicer_path = geoslicer_path
        return mock_args

    def test_script_normal(self, mock_is_elevated: MagicMock, mock_enable_privilege: MagicMock) -> None:
        write_processing_mmu_to_file(self._geolog_appdefaults, create_processing_mmu_lines_ok())
        mock_args = self._create_test_arguments_mock(self._geolog_path, self._geoslicer_path)
        assert pg.run(mock_args) == pg.ReturnValues.SUCCESS

    def test_script_geolog_path_not_found(self, mock_is_elevated: MagicMock, mock_enable_privilege: MagicMock) -> None:
        mock_args = self._create_test_arguments_mock("", self._geoslicer_path)
        assert pg.run(mock_args) == pg.ReturnValues.GEOLOG_NOT_FOUND

    @pytest.mark.parametrize(
        "malformed_creator, expected_return",
        [
            pytest.param(
                create_processing_mmu_lines_malformed1,
                pg.ReturnValues.PROCESSING_MENU_NOT_FOUND_IN_MMU,
                id="malformed1",
            ),
            pytest.param(
                create_processing_mmu_lines_malformed2, pg.ReturnValues.ERROR_PARSING_PROCESSING_MENU, id="malformed2"
            ),
        ],
    )
    def test_script_processing_mmu_malformed(
        self,
        mock_is_elevated: MagicMock,
        mock_enable_privilege: MagicMock,
        malformed_creator,
        expected_return,
    ) -> None:
        write_processing_mmu_to_file(self._geolog_appdefaults, malformed_creator())
        mock_args = self._create_test_arguments_mock(self._geolog_path, self._geoslicer_path)
        assert pg.run(mock_args) == expected_return
