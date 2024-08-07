""" Development script to automate bug inspection through 'git bisect run' function.
    Refer to 'git bisect documentation' for more information about it (https://git-scm.com/docs/git-bisect)
    Usage:

        '''
        # /bin/bash

        git bisect start
        git bisect good <good-commit>
        git bisect bad <bad-commit>
        git bisect run python ./tools/bisect_bug_inspector.py <OPTIONS>
        '''

    Please, check the available options through bisect_bug_inspector.py help:
        '''
        # /bin/bash
        python ./tools/bisect_bug_inspector.py --help
        '''
    
    As example, you could use its full potential with the following command
        '''
        # /bin/bash
        git bisect run python ./tools/bisect_bug_inspector.py --deploy "C:/GeoSlicer-1.15.0-2022-10-11-win-amd64.zip" --integration-tests TestsModuleTest MultipleImageAnalysisTest --unit-tests ./tests/unit/etc/test_dummy.py::TestDummy::test_case_2
        '''

    Add new process in-between the current written stages as you need it, but only commit if its a generic handler.
"""

from pathlib import Path
import argparse
import subprocess
import json
import sys
import time
import shutil
import logging


REPOSITORY_PATH = Path(__file__).parent.parent
RUN_MODULES_TESTS_SCRIPT_PATH = REPOSITORY_PATH / "tools" / "pipeline" / "run_modules_tests.py"
DUMMY_SCRIPT_PATH = REPOSITORY_PATH / "tools" / "pipeline" / "dummy_script.py"
DEPLOY_SCRIPT = REPOSITORY_PATH / "tools" / "deploy" / "deploy_slicer.py"
USE_SHELL = sys.platform == "win32"
PYTHON_EXECUTABLE_PATH = sys.executable

# Initialize logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(sys.stdout))


def run(args):
    if args.deploy:
        deploy_file_path = Path(args.deploy)
        extension = ".exe" if sys.platform == "win32" else ""
        GEOSLICER_EXECUTABLE_PATH = deploy_file_path.parent / deploy_file_path.stem / f"GeoSlicer{extension}"
        GEOSLICER_EXECUTABLE_DIRECTORY_PATH = GEOSLICER_EXECUTABLE_PATH.parent

        new_deploy_folder = not GEOSLICER_EXECUTABLE_DIRECTORY_PATH.exists()
        if args.no_cache and not new_deploy_folder:
            logger.info("Deleting old deployment application files...")
            shutil.rmtree(GEOSLICER_EXECUTABLE_DIRECTORY_PATH.as_posix())
            new_deploy_folder = True

        logger.info("Deploying application...")
        command = f"{PYTHON_EXECUTABLE_PATH} {DEPLOY_SCRIPT.as_posix()} {deploy_file_path.as_posix()} --dev"
        subprocess.run(command.split(" "), capture_output=True, shell=USE_SHELL, check=True)

        if new_deploy_folder:
            # Run dummy script to run first startup configuration
            command = f"{GEOSLICER_EXECUTABLE_PATH.as_posix()} --python-script {DUMMY_SCRIPT_PATH.as_posix()}"
            subprocess.run(command.split(" "), capture_output=True, shell=USE_SHELL, check=False)
            time.sleep(2)

    elif args.executable:
        GEOSLICER_EXECUTABLE_PATH = Path(args.executable)
        GEOSLICER_EXECUTABLE_DIRECTORY_PATH = GEOSLICER_EXECUTABLE_PATH.parent

    if isinstance(args.unit_tests, list):
        test_target = (
            (REPOSITORY_PATH / "tests" / "unit").as_posix() if len(args.unit_tests) == 0 else " ".join(args.unit_tests)
        )
        command = f"{PYTHON_EXECUTABLE_PATH} -m pytest {test_target}"
        logger.info("Running unit tests...")
        proc = subprocess.run(
            command.split(" "), capture_output=True, shell=USE_SHELL, check=False, cwd=REPOSITORY_PATH.as_posix()
        )
        pytest_output = proc.stdout.decode("utf-8")
        logger.info(pytest_output)
        if proc.returncode != 0:
            raise RuntimeError("Some unit tests have failed!")

    if isinstance(args.integration_tests, list):
        logger.info("Running integration tests...")
        command = f"{GEOSLICER_EXECUTABLE_PATH.as_posix()} --python-script {RUN_MODULES_TESTS_SCRIPT_PATH.as_posix()} -f {' '.join(args.integration_tests)}"
        proc = subprocess.run(command.split(" "), capture_output=True, shell=USE_SHELL, check=False)

        TEST_STATUS_FILE_PATH = GEOSLICER_EXECUTABLE_DIRECTORY_PATH / "LTrace" / "temp" / "test_status.json"

        # Opening JSON file
        with open(TEST_STATUS_FILE_PATH.as_posix()) as test_status_json_file:
            data = json.load(test_status_json_file)

        # Check results and exit process
        if data is None:
            raise RuntimeError("The integration tests broke during process. Please check the logs.")

        if data.get("Status") != 3:
            raise RuntimeError("The integration tests failed. Please check the logs.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Development script to automate bug inspection through 'git bisect' function."
    )
    parser.add_argument("-e", "--executable", help="The GeoSlicer executable", default=None)
    parser.add_argument(
        "-d",
        "--deploy",
        help="The GeoSlicer base application compressed file (.zip or .tar.gz) to deploy",
        default=None,
    )
    parser.add_argument(
        "-nc", "--no-cache", action="store_true", help="Delete previously deployed application folder", default=False
    )

    parser.add_argument(
        "-it",
        "--integration-tests",
        nargs="*",
        help="Allow integration-tests. It accepts tests suites/cases filtering Ex: '-it MultipleImageAnalysisTest:test_histogram_in_depth,test_mean_in_depth TestsModuleTest'. Default to run all discovered tests",
    )
    parser.add_argument(
        "-ut",
        "--unit-tests",
        nargs="*",
        help="Allow unit-tests. It accepts tests suites/cases filtering (pytest syxtax) Ex: '-ut ./tests/unit/Charts/HistogramInDepthPlot/test_histogram_in_depth_plot.py::TestHistogramInDepthPlotWidgetModel::test_append_data_none_type'. Default to run all discovered tests",
    )
    args_parsed = parser.parse_args()

    if args_parsed.executable is None and args_parsed.deploy is None:
        raise RuntimeError(
            "Please insert a executable path (--executable) or the GeoSlicer application base to deploy (--deploy)"
        )

    if args_parsed.executable and not Path(args_parsed.executable).is_file():
        raise RuntimeError(f"Invalid selected executable. Please select a valid GeoSlicer executable")

    if args_parsed.deploy and not Path(args_parsed.deploy).is_file():
        raise RuntimeError(
            f"Invalid selected GeoSlicer base application compressed file. Please select a valid file (.zip or .tar.gz)."
        )

    try:
        logger.info("Starting GeoSlicer bug inspection process...")
        run(args_parsed)
    except Exception as error:
        logger.info(f"Stopping process due to a failure: {error}")
        sys.exit(1)

    logger.info("NO BUGS FOUND! GeoSlicer bug inspection process finished successfully!")
    sys.exit(0)
