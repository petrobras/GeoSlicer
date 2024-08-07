"""Script tool to download GeoSlicer base compressed file from Oracle Cloud Infrastructure bucket.
   It requires the OCI Auth configuration file. In case you don't have the OCI Auth configured, follow this instruction:
   https://docs.oracle.com/pt-br/iaas/Content/API/Concepts/apisigningkey.htm#Required_Keys_and_OCIDs
"""
import argparse
import oci
import os
import logging
import sys
from packaging.version import parse, InvalidVersion
from pathlib import Path
from util import GeoSlicerBaseFileData, check_oci_configuration, download_file_from_bucket


# Workaround for ImportError: attempted relative import with no known parent package
sys.path.append(os.path.dirname(os.path.realpath(__file__)))

NAMESPACE = "grrjnyzvhu1t"
BUCKET_NAME = "General_ltrace_files"

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(sys.stdout))


def __create_file_version_data_from_file_name(file_path, platform):
    try:
        geoslicer_file_data = GeoSlicerBaseFileData(file_path, platform=platform)
    except Exception:
        return None

    return geoslicer_file_data


def __select_most_recent_version_file_path(args, geoslicer_base_file_data_list):
    if len(geoslicer_base_file_data_list) <= 0:
        raise RuntimeError("Unexpected attempt to iterate over an empty list of GeoSlicer base files.")

    if args.base is not None:
        # Checking for specific version, if required
        try:
            version = parse(args.base)
            is_version = True
        except InvalidVersion:
            is_version = False

        for file_data in geoslicer_base_file_data_list:
            if is_version and file_data.version == version:
                logger.info(f"Found a base file that matches version {args.base}! ({file_data.file_path})")
                return file_data.file_path
            if Path(file_data.file_path).name == args.base:
                logger.info(f"Found the requested base archive! ({args.base})")
                return file_data.file_path

        raise RuntimeError(f"The specified version wasn't found ({args.base}). Aborting.")

    # Order list by version descending
    geoslicer_base_file_data_list = sorted(geoslicer_base_file_data_list, reverse=True)
    logger.debug(
        f"GeoSlicer base files found and ordered: {[file.file_path for file in geoslicer_base_file_data_list]}"
    )

    return geoslicer_base_file_data_list[0].file_path


def select_geoslicer_base_from_bucket(args, object_storage_client):
    logger.info("Listing files from bucket...")
    prefix = "GeoSlicer/base/"
    object_list = object_storage_client.list_objects(NAMESPACE, BUCKET_NAME, prefix=prefix, fields="name,timeCreated")
    file_path_list = [file_path_object.name for file_path_object in object_list.data.objects]

    logger.debug(f"Files found from bucket with prefix {prefix}:\n{file_path_list}")
    valid_file_options_objects = []
    for file_path in file_path_list:
        geoslicer_base_file_data = __create_file_version_data_from_file_name(
            file_path=file_path, platform=args.platform
        )
        if geoslicer_base_file_data is None:
            continue

        valid_file_options_objects.append(geoslicer_base_file_data)

    if len(valid_file_options_objects) <= 0:
        raise RuntimeError(
            f"Unable to found a GeoSlicer base file at the bucket file system. List of files found: {file_path_list}"
        )

    return __select_most_recent_version_file_path(args, valid_file_options_objects)


def should_download_version_from_bucket(args, file_path_from_bucket):
    if args.current_version is None:
        raise RuntimeError("Invalid attempt to compare a current version without specifying one.")

    current_file_version_data = __create_file_version_data_from_file_name(
        file_path=args.current_version, platform=args.platform
    )
    bucket_file_version_data = __create_file_version_data_from_file_name(
        file_path=file_path_from_bucket, platform=args.platform
    )

    if current_file_version_data > bucket_file_version_data:
        logger.info(
            "Current GeoSlicer file is a newer version than the file in the bucket. Stopping the download process..."
        )
        return False
    elif current_file_version_data == bucket_file_version_data:
        logger.info(
            "Current GeoSlicer file is the same version as the file in the bucket. Stopping the download process..."
        )
        return False

    logger.info(
        "The GeoSlicer file in the bucket is the most recent version than the current file. Continuing the download process..."
    )
    return True


def process(args):
    logger.info("Starting GeoSlicer compressed base file download process.")
    config = oci.config.from_file()
    check_oci_configuration(config, logger=logger)

    object_storage_client = oci.object_storage.ObjectStorageClient(config)

    file_path_from_bucket = select_geoslicer_base_from_bucket(args, object_storage_client)

    if args.current_version is not None:
        if not should_download_version_from_bucket(args, file_path_from_bucket):
            # Stop process from here as successful
            return

    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if output_path.is_file():
        output_path.unlink()

    # download file from bucket
    download_file_from_bucket(
        object_storage_client=object_storage_client,
        namespace=NAMESPACE,
        bucket_name=BUCKET_NAME,
        file_path_from_bucket=file_path_from_bucket,
        output_file_path=Path(args.output_dir),
        logger=logger,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download GeoSlicer base compressed file from Oracle Cloud Infrastructure bucket."
    )
    parser.add_argument(
        "--base",
        help="Specify a base filename or version. Otherwise, the most recent will be downloaded.",
        default=None,
    )
    parser.add_argument(
        "--output-dir",
        help="The output directory. Default to the current script directory.",
        default=Path(__file__).parent.as_posix(),
    )
    parser.add_argument(
        "--platform",
        help="The OS platform string (sys based) GeoSlicer related file. Default to the current platform in use.",
        default=sys.platform,
    )
    parser.add_argument(
        "--current-version",
        help="Compare the versions between the selected version from bucket to the passed file version. If the bucket one is newer, then the newest version will be downloaded.",
        default=None,
    )

    args = parser.parse_args()
    try:
        process(args)
    except Exception as error:
        logger.info(f"Found a problem! Cancelling process...")
        logger.info(f"Error: {error}")
        sys.exit(1)

    logger.info("The GeoSlicer compressed base file newest version download process was successful.")
    sys.exit(0)
