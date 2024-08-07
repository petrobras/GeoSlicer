""" Script to run GeoSlicer test modules automatically using the --python-script flag.
    The test result is saved at 'test_result.json' on GeoSlicer temp folder.
    
    Ex: C:/GeoSlicer/GeoSlicer.exe --python-script "./tools/pipeline/run_modules_tests.py"
"""


import argparse
import json
import logging
import os
import slicer
import sys
import time

from ltrace.slicer.tests.ltrace_tests_model import LTraceTestsModel, TestsSource
from ltrace.slicer.tests.utils import create_logger, log
from pathlib import Path


TEST_STATUS_FILE_PATH = Path(slicer.app.temporaryPath) / "test_status.json"


class ConsoleHandler(logging.StreamHandler):
    """Custom logging handler for showing log in console."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        formatter = logging.Formatter("%(message)s%(end)s")
        self.terminator = ""
        self.setFormatter(formatter)


logger = create_logger()
logger.addHandler(ConsoleHandler())


def create_test_status_file(state, file_path=TEST_STATUS_FILE_PATH):
    data = {"Status": state.value}

    if os.path.exists(file_path):
        os.remove(file_path)

    with open(file_path, "x") as f:
        json.dump(data, f, indent=4)


def filter_tests(args, model):
    if len(args.filter) <= 0:  # Enable all tests
        for test_suite in model.test_suite_list:
            test_suite.enabled = True
    else:
        test_list = args.filter
        for test_label in test_list:
            if ":" in test_label:
                filtered_test_suite = test_label.split(":")[0]
                filtered_test_cases = test_label.split(":")[1]
            else:
                filtered_test_suite = test_label
                filtered_test_cases = None

            # Check if filtered test suite exists
            test_suite_name_list = [test_suite_data.name for test_suite_data in model.test_suite_list]
            if filtered_test_suite not in test_suite_name_list:
                raise RuntimeError(f"The desired test suite {filtered_test_suite} doesn't exist.")

            # Iterate
            for test_suite_data in model.test_suite_list:
                if test_suite_data.name != filtered_test_suite:
                    continue

                if filtered_test_cases is None:  # All test cases enabled
                    test_suite_data.enabled = True
                else:
                    test_case_name_list = [
                        test_case_data.name for test_case_data in test_suite_data.test_case_data_list
                    ]
                    for filtered_test_case in filtered_test_cases.split(","):
                        # Check if filtered test case exists
                        if filtered_test_case not in test_case_name_list:
                            raise RuntimeError(
                                f"The desired test case {filtered_test_suite}:{filtered_test_case} doesn't exist."
                            )

                        # Iterate
                        for test_case_data in test_suite_data.test_case_data_list:
                            if test_case_data.name != filtered_test_case:
                                continue

                            test_case_data.enabled = True


def process(args):
    model = LTraceTestsModel(test_source=TestsSource.GEOSLICER)

    filter_tests(args, model)

    # Run tests (blocking function)
    try:
        model.run_tests(suite_list=model.test_suite_list, shuffle=True, break_on_failure=False)
    except Exception as e:
        log(f"Error on running tests: {e}")
        return

    # Failure overview
    for test_suite_data in model.test_suite_list:
        if warning_text := test_suite_data.warning_log_text:
            log(warning_text)
        if failure_text := test_suite_data.failure_log_text:
            log(failure_text)

    create_test_status_file(state=model.result())
    slicer.app.processEvents()
    time.sleep(5)


def processEvents():
    slicer.app.processEvents()


def run(args):
    log("Starting modules test runner!")
    try:
        process(args)
    except Exception as error:
        log(error)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run modules test from GeoSlicer using command line.")
    parser.add_argument(
        "-f",
        "--filter",
        nargs="+",
        default=[],
        help="Filter the test suites/cases to run. Ex: '--filter MultipleImageAnalysisTest:test_histogram_in_depth,test_mean_in_depth TestsModuleTest'. Default to run all test suites",
    )
    args_parsed = parser.parse_args()

    run(args_parsed)
