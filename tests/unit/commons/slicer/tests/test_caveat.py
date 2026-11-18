from pathlib import Path
from commons.slicer.tests.caveat import Caveat

import pytest
import tempfile
import json


class TestCaveatTest:
    @pytest.mark.parametrize(
        "dataSource, success",
        [
            pytest.param("not a json", False, id="wrong_input"),
            pytest.param("", False, id="empty"),
            pytest.param("{}", False, id="empty_json"),
            pytest.param("{'teste': 1}", False, id="json_wrong_schema"),
            pytest.param(
                '{"failing_tests": {"suite1": ["test_case_1", "test_case_2"], "suite2": ["test_case_3", "test_case_4"]}}',
                True,
                id="valid",
            ),
        ],
    )
    def test_loading_json_format(self, dataSource, success):
        succeed = False
        try:
            Caveat(dataSource)
            succeed = True
        except Exception:
            succeed = False

        assert succeed is success, (
            f"TestCaveat loading result wasn't the expected. Expected to load? {success}. But it loaded? {succeed}"
        )

    @pytest.mark.parametrize(
        "data_source, success",
        [
            pytest.param({}, False, id="empty_json"),
            pytest.param({"teste": 1}, False, id="json_wrong_schema"),
            pytest.param(
                {"failing_tests": {"suite1": ["test_case_1", "test_case_2"], "suite2": ["test_case_3", "test_case_4"]}},
                True,
                id="valid",
            ),
        ],
    )
    def test_loading_json_file(self, data_source, success):
        with tempfile.TemporaryDirectory() as dir:
            caveat_file_path = Path(dir) / "caveat.json"
            with open(caveat_file_path, "w") as file:
                json.dump(data_source, file)

            succeed = False
            try:
                Caveat(caveat_file_path)
                succeed = True
            except Exception:
                succeed = False

            assert succeed is success, (
                f"TestCaveat loading result wasn't the expected. Expected to load? {success}. But it loaded? {succeed}"
            )

    @pytest.mark.parametrize(
        "caveat_json, expected_failing_test_suites",
        [
            pytest.param(
                '{"failing_tests": {"suite1": ["test_case_1"], "suite2": ["test_case_3", "test_case_4"]}}',
                ["suite1", "suite2"],
                id="valid",
            ),
            pytest.param('{"failing_tests": {}}', [], id="empty_values_json"),
        ],
    )
    def test_failing_test_suites(self, caveat_json, expected_failing_test_suites):
        testCaveat = Caveat(caveat_json)
        assert testCaveat.failing_test_suites() == expected_failing_test_suites

    @pytest.mark.parametrize(
        "caveat_json, test_suite_name, expected_failing_test_cases",
        [
            pytest.param(
                '{"failing_tests": {"suite1": ["test_case_1"], "suite2": ["test_case_3", "test_case_4"]}}',
                "suite1",
                ["test_case_1"],
                id="valid",
            ),
            pytest.param(
                '{"failing_tests": {"suite1": ["test_case_1"], "suite2": ["test_case_3", "test_case_4"]}}',
                "suite2",
                ["test_case_3", "test_case_4"],
                id="valid_2",
            ),
            pytest.param('{"failing_tests": {}}', "suite1", [], id="empty_values_json"),
        ],
    )
    def test_failing_test_cases(self, caveat_json, test_suite_name, expected_failing_test_cases):
        testCaveat = Caveat(caveat_json)
        assert testCaveat.failing_test_cases(test_suite_name) == expected_failing_test_cases
