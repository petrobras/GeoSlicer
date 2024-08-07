import argparse
import git
import json
import logging
import oci
import os
import psutil
import random
import re
import shutil
import sys
import string
import subprocess
import time
import traceback

from pathlib import Path
from pyunpack import Archive
from typing import Callable, List, Union
from util import GeoSlicerBaseFileData, check_oci_configuration, download_file_from_bucket

# OCI bucket information
NAMESPACE = "grrjnyzvhu1t"
BUCKET_NAME = "General_ltrace_files"
DEVELOPMENT_TAG = "development"

# Workaround for ImportError: attempted relative import with no known parent package
sys.path.append(os.path.dirname(os.path.realpath(__file__)))

# Initialize logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(sys.stdout))

# Create directory hash suffix to avoid access problems to the temporary directory
DIR_HASH = "".join(random.choice(string.hexdigits) for i in range(4))


def get_working_directory(args) -> Path:
    if args.avoid_long_path and sys.platform == "win32":
        path = Path(Path.home().drive) / f"/gs{DIR_HASH}"
    elif os.getenv("WORKSPACE") is not None and Path(os.getenv("WORKSPACE")).exists():
        path = Path(os.getenv("WORKSPACE")) / f"gs{DIR_HASH}"
    else:
        path = Path.home() / f"gs{DIR_HASH}"

    return path


def run_tests(args: argparse.Namespace) -> None:
    geoslicer_executable_file_path = get_geoslicer_executable_file_path(args)
    geoslicer_directory = geoslicer_executable_file_path.parent
    test_status_file_path = geoslicer_directory / "LTrace" / "temp" / "test_status.json"
    test_log_file_path = geoslicer_directory / "LTrace" / "temp" / "tests.log"

    if test_status_file_path.exists():
        test_status_file_path.unlink()

    if args.no_gpu:
        logger.info("Setting environment variables to run GeoSlicer without a GPU...")
        os.environ["GALLIUM_DRIVER"] = "llvmpipe"
        os.environ["MESA_GL_VERSION_OVERRIDE"] = "3.3COMPAT"

    # Run dummy code once to apply first application setup
    logger.info("Running GeoSlicer with the dummy python code due first startup configuration...")
    dummy_script_path = (Path(args.repository_path) / "tools" / "pipeline" / "dummy_script.py").as_posix()
    command = [geoslicer_executable_file_path.as_posix(), "--python-script", dummy_script_path]
    subprocess.run(command)
    time.sleep(5)

    # Run the test runner script
    logger.info("Running GeoSlicer with the modules test runner script...")
    test_script_path = (Path(args.repository_path) / "tools" / "pipeline" / "run_modules_tests.py").as_posix()
    command = [geoslicer_executable_file_path.as_posix(), "--python-script", test_script_path]
    subprocess.run(command)

    if not test_log_file_path.exists() or not test_status_file_path.exists():
        raise RuntimeError("The test run didn't finished as expected. Please check the logs.")

    # Read test logs
    with open(test_log_file_path.as_posix(), encoding="utf-8") as test_log_file:
        for line in test_log_file:
            logger.info(line.strip())

    # Opening JSON file
    with open(test_status_file_path.as_posix()) as test_status_json_file:
        data = json.load(test_status_json_file)

    # Check results and exit process
    if data is None:
        raise RuntimeError("Something went wrong. Please check the logs.")

    if data.get("Status") != 3:
        raise RuntimeError("The tests failed. Please check the logs.")

    logger.info("The tests were successful!")


def find_geoslicer_base_files(args: argparse.Namespace, root_dir: Path) -> List[GeoSlicerBaseFileData]:
    geoslicer_zip_files = []
    for file in os.listdir(root_dir):
        try:
            geoslicer_zip_file = GeoSlicerBaseFileData(file_path=(root_dir / file).as_posix(), platform=args.platform)
        except AttributeError:
            continue

        geoslicer_zip_files.append(geoslicer_zip_file)

    return geoslicer_zip_files


def get_specified_base_file_path(args: argparse.Namespace) -> Path:
    root_dir = args.local_files_directory

    # Check if the specified base exists in the local directory
    base_path = root_dir / args.base
    if base_path.exists():
        logger.info(f"Specified base {args.base} found in the local directory. Path: {base_path.as_posix()}")
        return base_path

    # Download specified base from the bucket
    logger.info(f"Specified base {args.base} doesn't exist in the local directory. Starting download process...")

    download_geoslicer_base_from_bucket(root_dir, None, base=args.base)
    if base_path.exists():
        logger.info(f"Specified base {args.base} downloaded successfully. Path: {base_path.as_posix()}")
        return base_path
    raise RuntimeError(
        f"Something went wrong during attempt to download the specified base {args.base} from the bucket."
    )


def get_latest_geoslicer_base_file_path(args: argparse.Namespace) -> Path:
    root_dir = args.local_files_directory

    logger.info(f"Looking for a GeoSlicer base zip file in {root_dir.as_posix()}...")
    geoslicer_zip_files = find_geoslicer_base_files(args, root_dir)
    if len(geoslicer_zip_files) <= 0:
        logger.info(f"Missing GeoSlicer base zip file in directory {root_dir.as_posix()}. Starting download process.. ")
        current_geoslicer_zip_file = None
    else:
        logger.info(
            f"Found! GeoSlicer base zip file: {geoslicer_zip_files[0].file_path}. Checking for available newer"
            " version..."
        )
        geoslicer_zip_files = sorted(geoslicer_zip_files, reverse=True)
        current_geoslicer_zip_file = geoslicer_zip_files[0]

    # Download/check newer version at bucket
    download_geoslicer_base_from_bucket(root_dir, current_geoslicer_zip_file)
    geoslicer_zip_files = find_geoslicer_base_files(args, root_dir)
    if len(geoslicer_zip_files) <= 0:
        raise RuntimeError("Something went wrong during attempt to download/check a newer version from the bucket.")

    geoslicer_zip_files = sorted(geoslicer_zip_files, reverse=True)
    return geoslicer_zip_files[0].file_path


def get_geoslicer_base_file_path(args: argparse.Namespace) -> Path:
    if args.base == "latest":
        return get_latest_geoslicer_base_file_path(args)
    else:
        return get_specified_base_file_path(args)


def download_geoslicer_base_from_bucket(
    root_dir: Path, current_geoslicer_zip_file_data: GeoSlicerBaseFileData, base=None
):
    download_geoslicer_base_script_path = Path(__file__).parent / "download_geoslicer_base.py"
    command = ["python", download_geoslicer_base_script_path.as_posix(), "--output-dir", root_dir.as_posix()]
    if current_geoslicer_zip_file_data is not None:
        command.extend(["--current-version", current_geoslicer_zip_file_data.file_path])
    if base is not None:
        command.extend(["--base", base])

    run_subprocess(command)


def generate_application(
    args: argparse.Namespace, geoslicer_base_zip_file_path: Path, production: bool = False
) -> None:
    repository_path = args.repository_path
    deploy_script_path = (Path(repository_path) / "tools" / "deploy" / "deploy_slicer.py").as_posix()
    command = [
        "python",
        deploy_script_path,
        geoslicer_base_zip_file_path,
        "--with-porespy",
    ]

    if production:
        command.append("--geoslicer-version"),
        command.append(args.version),
    else:
        # Development deploy is required to copy tests
        command.append("--dev")

    if args.sfx:
        command.append("--sfx")

    if args.generate_public_version:
        command.append("--generate-public-version")

    if args.no_public_commit:
        command.append("--no-public-commit")

    logger.info("Running GeoSlicer deploy script...")
    run_subprocess(command)


def get_geoslicer_executable_file_path(args: argparse.Namespace) -> Path:
    working_dir = get_working_directory(args)
    geoslicer_dir = [gd for gd in working_dir.glob("GeoSlicer*") if gd.is_dir()]
    if len(geoslicer_dir) <= 0:
        raise RuntimeError(
            "Deployed GeoSlicer directory wasn't found. Available files in current directory:"
            f" {os.listdir(working_dir.as_posix())}"
        )
    ext = ".exe" if args.platform == "win32" else ""
    geoslicer_executable_file_path = working_dir / geoslicer_dir[0] / ("GeoSlicer" + ext)
    if not geoslicer_executable_file_path.exists():
        raise RuntimeError(
            "GeoSlicer executable not found. Available files in deployed GeoSlicer directory:"
            f" {os.listdir(geoslicer_dir[0])}"
        )

    return geoslicer_executable_file_path


def remove_working_directory(args: argparse.Namespace) -> None:
    temp_dir = get_working_directory(args)
    if not temp_dir.exists():
        return
    logger.info("Removing temporary folder...")
    shutil.rmtree(temp_dir, onerror=make_directory_writable)


def get_mesa_driver_file_path(args) -> Path:
    logger.info("Searching for MESA 3D driver local file...")
    mesa_zip_file_path_list = [
        Path(args.local_files_directory) / f
        for f in os.listdir(args.local_files_directory)
        if re.match(r"(^mesa3d)(\S+)(\.7z$)", f)
    ]
    if len(mesa_zip_file_path_list) <= 0:
        logger.info("MESA 3D driver local file doesn't exist. Downloading it from the bucket...")
        config = oci.config.from_file()
        check_oci_configuration(config, logger=logger)
        object_storage_client = oci.object_storage.ObjectStorageClient(config)
        mesa_zip_file = get_working_directory(args) / "mesa3d-23.1.3-release-msvc.7z"
        download_file_from_bucket(
            object_storage_client=object_storage_client,
            namespace=NAMESPACE,
            bucket_name=BUCKET_NAME,
            file_path_from_bucket="GeoSlicer/mesa3d-23.1.3-release-msvc.7z",
            output_file_path=mesa_zip_file,
            logger=logger,
        )
    else:
        mesa_zip_file = mesa_zip_file_path_list[0]
        logger.info(f"Found {mesa_zip_file.as_posix()}!")

    return mesa_zip_file


def run_no_gpu_process(args: argparse.Namespace) -> None:
    logger.info("Adapting GeoSlicer to use it without GPU...")
    mesa_zip_file = get_mesa_driver_file_path(args)

    if not mesa_zip_file.exists():
        raise RuntimeError("MESA3D file was not found.")

    geoslicer_executable_file_path = get_geoslicer_executable_file_path(args)
    geoslicer_folder = geoslicer_executable_file_path.parent
    if not geoslicer_folder.exists():
        raise RuntimeError("Deployed GeoSlicer application directory doesn't exist!")

    logger.info("Extracting MESA3D dll files...")
    mesa_folder = get_working_directory(args) / "mesa"
    if mesa_folder.exists():
        shutil.rmtree(mesa_folder, onerror=make_directory_writable)

    mesa_folder.mkdir()
    Archive(mesa_zip_file).extractall(mesa_folder)

    current_arch = "x64" if args.arch == "x64" else "x86"
    logger.info(f"Moving {current_arch} MESA 3D dll files to GeoSlicer folder...")
    mesa_arch_folder = mesa_folder / current_arch
    if not mesa_arch_folder.exists():
        raise RuntimeError(f"The MESA 3D dll folder {mesa_arch_folder.as_posix()} doesn't exist!")
    geoslicer_bin_folder = geoslicer_folder / "bin"

    shutil.copytree(mesa_arch_folder, geoslicer_bin_folder, dirs_exist_ok=True)


def get_geoslicer_application_compressed_file_path(args: argparse.Namespace) -> Path:
    extension = ""
    public_suffix = "_public" if args.generate_public_version else ""

    if args.sfx:
        extension = ".exe" if args.platform == "win32" else ".sfx"
    else:
        extension = ".zip" if args.platform == "win32" else ".tar.gz"

    working_directory_path = get_working_directory(args)
    if args.production:
        file_path = working_directory_path / f"GeoSlicer-{args.version}{public_suffix}{extension}"
        if not file_path.exists():
            raise RuntimeError(f"GeoSlicer Application compressed file doesn't exist at {file_path.as_posix()}.")
    else:
        pattern = f"GeoSlicer*_{DEVELOPMENT_TAG}{public_suffix}{extension}"
        file_paths = [file for file in working_directory_path.glob(pattern)]
        if len(file_paths) <= 0:
            raise RuntimeError(
                f"GeoSlicer Application compressed file doesn't exist at {working_directory_path.as_posix()}. Expected the filename pattern: {pattern}"
            )
        file_path = file_paths[0]

    return file_path


def export_application(args: argparse.Namespace) -> None:
    logger.info("Exporting GeoSlicer application compressed file to the bucket...")
    geoslicer_compressed_file = get_geoslicer_application_compressed_file_path(args)
    download_geoslicer_base_script_path = Path(__file__).parent / "upload_file_bucket.py"
    platform = "windows" if sys.platform == "win32" else "linux"
    bucket_output_directory = f"GeoSlicer/builds/{platform}"
    command = [
        "python",
        download_geoslicer_base_script_path.as_posix(),
        "--file",
        geoslicer_compressed_file.as_posix(),
        "--bucket-output-directory",
        bucket_output_directory,
        "--bucket-name",
        "General_ltrace_files",
        "--namespace",
        "grrjnyzvhu1t",
    ]

    run_subprocess(command)
    logger.info(f"GeoSlicer application compressed file upload successfully. File path: {bucket_output_directory}")


def clone_sikulix_repository(args: argparse.Namespace) -> Path:
    logger.info(f"Cloning sikulix repository...")
    repo_url = "git@bitbucket.org:ltrace/geoslicer_sikuli.git"
    working_dir = get_working_directory(args)
    repo_dir = os.path.join(working_dir, "geoslicer_sikuli")
    branch_to_clone = args.sikulix_branch

    repo = git.Repo.clone_from(repo_url, repo_dir, branch=branch_to_clone)
    logger.info("Git clone completed successfully.")
    try:
        repo.git.execute(["git-lfs", "pull"])
        logger.info("Git LFS pull completed successfully.")
    except git.GitCommandError as e:
        logger.info(f"Error running 'git-lfs pull': {e}")

    logger.info(f"Repository cloned to {repo_dir}")

    if not Path(repo_dir).exists():
        raise RuntimeError(f"Sikulix repository cloning fail.")

    return repo_dir


def extract_critical_stream_lines_from_geoslicer_logs(folder_path, log_path):
    all_files = os.listdir(folder_path)
    text_files = [file for file in all_files if file.endswith(".log")]

    newest_file = max(text_files, key=lambda f: os.path.getmtime(os.path.join(folder_path, f)))
    newest_file_path = os.path.join(folder_path, newest_file)
    # write logs
    with open(log_path, "a", encoding="utf8") as log:
        log.write("GEOSLICER TRACEBACK LOGS\n")

    with open(newest_file_path, "r", encoding="utf8") as file:
        for line in file:
            if line.startswith("[CRITICAL][Stream]"):
                logger.info(line)
                with open(log_path, "a", encoding="utf8") as log:
                    log.write(line + "\n")


def kill_geoslicer_process():
    logger.info("Closing GeoSlicer...")
    try:
        for process in psutil.process_iter(["name"]):
            if process.info["name"] == "GeoSlicerApp-real.exe" or process.info["name"] == "GeoSlicer.exe":
                process.kill()
                process.wait()
    except psutil.Error as e:
        logger.error("Error occurred while terminating processes: %s", e)
    except Exception as e:
        logger.error("Unexpected error occurred: %s", e)


def run_ui_test(args: argparse.Namespace) -> None:
    geoslicer_executable_file_path = get_geoslicer_executable_file_path(args)
    geoslicer_directory = geoslicer_executable_file_path.parent
    repo_dir = clone_sikulix_repository(args)

    # Run UI test
    workspace_dir = get_working_directory(args)
    test_sikulix_file_path = Path(workspace_dir) / "ui_test_sikulix.txt"
    sikulix_exe = (Path(repo_dir) / "sikulixide-2.0.5-win.jar").as_posix()
    sikulix_run_all = (Path(repo_dir) / "_run_all.sikuli").as_posix()
    temp_file_path = geoslicer_directory / "LTrace" / "temp"

    # Run dummy code once to apply first application setup
    logger.info("Running GeoSlicer with the dummy python code due first startup configuration...")
    dummy_script_path = (Path(args.repository_path) / "tools" / "pipeline" / "dummy_script.py").as_posix()
    command = [geoslicer_executable_file_path.as_posix(), "--python-script", dummy_script_path]
    subprocess.run(command)
    time.sleep(15)

    logger.info("Running GeoSlicer...")
    geoslicer = geoslicer_executable_file_path.as_posix()
    subprocess.Popen(geoslicer)
    time.sleep(90)

    logger.info("Running Sikulix...")
    sikulix_log = open(test_sikulix_file_path, "w", encoding="utf8")
    sikulix_command = [
        "java",
        "-jar",
        sikulix_exe,
        "-r",
        sikulix_run_all,
    ]
    # Open the log file for writing
    with open(test_sikulix_file_path, "w", encoding="utf8") as sikulix_log:
        try:
            sikulix_process = subprocess.Popen(sikulix_command, stdout=sikulix_log, stderr=subprocess.STDOUT)
            sikulix_process.wait()
        finally:
            sikulix_log.close()
            sikulix_process.kill()
            sikulix_process.wait()
    time.sleep(20)
    if not test_sikulix_file_path.exists() or not temp_file_path.exists():
        raise RuntimeError("The test run didn't finished as expected. Please check the logs.")

    # Read test logs
    logger.info("Read test logs")
    try:
        with open(test_sikulix_file_path.as_posix(), encoding="utf-8") as test_log_file:
            error_detected = False

            for line in test_log_file:
                logger.info(line)
                if line.startswith("[error]") or line.startswith("error"):
                    error_detected = True

            if error_detected:
                raise RuntimeError("The UI tests Fail.")
            else:
                logger.info("The UI tests were successful!")
    except Exception as e:
        logger.info(f"An error occurred: {str(e)}")
        raise

    finally:
        logger.info("Read geoslicer logs")
        extract_critical_stream_lines_from_geoslicer_logs(
            folder_path=temp_file_path, log_path=test_sikulix_file_path.as_posix()
        )
        # Kill the GeoSlicer process
        kill_geoslicer_process()
        time.sleep(5)
        git.rmtree(repo_dir)


def run_process(args: argparse.Namespace) -> None:
    if args.no_deploy:
        logger.info("Skipping the application generation step...")
        return

    # Remove old generated application data
    remove_working_directory(args)

    # Get geoslicer base zip file
    geoslicer_base_zip_file_path = get_geoslicer_base_file_path(args)

    # Move geoslicer base zip file to temp file
    working_dir = get_working_directory(args)
    if not working_dir.exists():
        working_dir.mkdir()

    temp_geoslicer_base_zip_file_path = working_dir / Path(geoslicer_base_zip_file_path).name
    if not temp_geoslicer_base_zip_file_path.exists():
        logger.info(f"Moving GeoSlicer base file to the working folder... ({working_dir.as_posix()})")
        shutil.copy(geoslicer_base_zip_file_path, temp_geoslicer_base_zip_file_path)

    # Run deploy script in development mode to run test, otherwise deploy in production mode
    deploy_as_prod_mode = args.no_test and args.production
    generate_application(args, temp_geoslicer_base_zip_file_path.as_posix(), production=deploy_as_prod_mode)

    if args.no_gpu:
        run_no_gpu_process(args)
    if args.test_ui:
        logger.info("Run UI test")
        run_ui_test(args)

    if args.no_test:
        logger.info("Skipping the testing step...")
    else:
        run_tests(args)

    if args.no_export:
        logger.info("Skipping the exporting step...")
    else:
        if not deploy_as_prod_mode and args.production:
            generate_application(args, temp_geoslicer_base_zip_file_path.as_posix(), production=True)
        elif not args.production:
            make_generated_application_archive(args, DEVELOPMENT_TAG)

        export_application(args)


def make_directory_writable(func: Callable, path: Union[Path, str]) -> None:
    """
    Error handler for ``shutil.rmtree``.

    If the error is due to an access error (read only file)
    it attempts to add write permission and then retries.

    If the error is for another reason it re-raises the error.

    Usage : ``shutil.rmtree(path, onerror=make_directory_writable)``
    """
    import stat

    # Is the error an access error?
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        raise


def run_subprocess(command: Union[List, str], assert_exit_code: bool = True) -> None:
    """Wrapper for running subprocess and reading its output"""
    with subprocess.Popen(command, stdout=subprocess.PIPE, bufsize=1, universal_newlines=True) as proc:
        for line in proc.stdout:
            print(f"\t{line}", end="")

    if assert_exit_code and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, proc.args)


def make_generated_application_archive(args: argparse.Namespace, tag: str) -> Path:
    logger.info("Creating application archive...")
    source_dir = get_geoslicer_executable_file_path(args).parent
    target_file_without_extension = f"{source_dir.name}_{tag}" if tag else source_dir.name
    if args.sfx:
        ext = ".exe" if sys.platform == "win32" else ".sfx"
        packager = "7zG" if sys.platform == "win32" else "7z"
        target = source_dir.parent / f"{target_file_without_extension}{ext}"
        command = [packager, "a", target.as_posix(), "-mx5", "-sfx", source_dir.as_posix()]
        run_subprocess(command)

    else:
        archive_format = "zip" if sys.platform == "win32" else "gztar"
        result = shutil.make_archive(
            target_file_without_extension,
            archive_format,
            root_dir=source_dir.parent,
            base_dir=source_dir.name,
        )

        result = Path(result)
        target = (source_dir.parent / target_file_without_extension).with_name(result.name)
        shutil.move(result, target)

    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Configures a clean Slicer download for deploy or development.")
    parser.add_argument("--version", help="Version number to use for GeoSlicer. Examples: 1, 1.2, 1.2.3", default=None)
    parser.add_argument("--repository-path", help="The repository directory path", default=Path(__file__).parents[2])
    parser.add_argument("--no-gpu", action="store_true", help="Add flags to work without GPU", default=False)
    parser.add_argument("--arch", help="The system architeture (x64 or x86)", default="x64")
    parser.add_argument("--no-deploy", action="store_true", help="Skip application deployment step", default=False)
    parser.add_argument("--no-test", action="store_true", help="Skip application testing step", default=False)
    parser.add_argument("--no-export", action="store_true", help="Skip application exporting step", default=False)
    parser.add_argument("--test-ui", action="store_true", help="Run application testing UI step", default=False)
    parser.add_argument("--sikulix-branch", help="Sikulix branch", default="develop")
    parser.add_argument(
        "--sfx",
        action="store_true",
        help="Create Self-extracting file instead of the zip/tar compressed file",
        default=False,
    )
    parser.add_argument(
        "--platform",
        help="The OS platform string (sys based) GeoSlicer related file. Default to the current platform in use.",
        default=sys.platform,
    )
    parser.add_argument(
        "--avoid-long-path",
        action="store_true",
        help="Attempt to handle long path issue using the main drive path as working directory",
        default=False,
    )
    parser.add_argument(
        "--local-files-directory",
        help="The local directory path where required files might be stored (GeoSlicer base, MESA3D, CUDNN compressed files)",
        default=Path.home(),
    )
    parser.add_argument(
        "--base",
        help="Filename of base archive in the bucket's release base directory",
    )
    parser.add_argument(
        "--production", action="store_true", help="Generate application in production mode to export.", default=False
    )
    parser.add_argument(
        "--keep-files",
        action="store_true",
        help="Avoid file removal after succesfully finishing the process.",
        default=False,
    )
    parser.add_argument(
        "--generate-public-version",
        action="store_true",
        help="Deploy the application's public version. When in deploying production version, it also git commit to the opensource code's repository.",
        default=False,
    )
    parser.add_argument(
        "--no-public-commit",
        action="store_true",
        help="Avoid commiting to the opensource code repository.",
        default=True,
    )

    p_args = parser.parse_args()

    if not p_args.version:
        raise AttributeError("Invalid version input.")

    if p_args.version.startswith("v"):
        p_args.version = p_args.version[1:]

    try:
        run_process(p_args)
    except Exception as error:
        logger.info(f"Found a problem! Cancelling process...")
        logger.info(f"Error: {error}\n{traceback.format_exc()}")
        remove_working_directory(p_args)
        sys.exit(1)

    if not p_args.keep_files:
        remove_working_directory(p_args)
    sys.exit(0)
