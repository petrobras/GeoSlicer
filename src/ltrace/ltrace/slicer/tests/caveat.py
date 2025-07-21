import json
import jsonschema
import jsonschema.exceptions

from pathlib import Path
from typing import List

REPOSITORY_PATH = Path(__file__).parents[5]
SOURCE_FILE_PATH = REPOSITORY_PATH / "tools" / "pipeline" / "integration_tests_caveat.json"


class Caveat(object):
    SCHEMA = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "Generated schema for Caveat integration tests",
        "type": "object",
        "properties": {"failing_tests": {"type": "object", "properties": {}, "required": []}},
        "required": ["failing_tests"],
    }

    def __init__(self, dataSource: str = SOURCE_FILE_PATH):
        self.__dataSource = dataSource
        self.__data = None
        self.__parse()

    def __parse(self):
        if self.__dataSource is None:
            return

        try:
            self.__data = json.loads(self.__dataSource)
        except Exception:
            path = Path(self.__dataSource)
            if not path.exists():
                raise ValueError(f"{self.__dataSource} is not a valid JSON or JSON file")
            with open(path, "r") as f:
                self.__data = json.load(f)

        jsonschema.validate(self.__data, self.SCHEMA)

    def failing_test_suites(self) -> List[str]:
        return list(self.failing_tests.keys())

    def failing_test_cases(self, testSuiteName: str) -> List[str]:
        return list(self.failing_tests.get(testSuiteName, []))

    @property
    def failing_tests(self):
        return self.__data.get("failing_tests", {})
