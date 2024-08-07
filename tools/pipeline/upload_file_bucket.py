"""Script tool to upload files to Oracle Cloud Infrastructure bucket.
   It requires the OCI Auth configuration file. In case you don't have the OCI Auth configured, follow this instruction:
   https://docs.oracle.com/pt-br/iaas/Content/API/Concepts/apisigningkey.htm#Required_Keys_and_OCIDs
"""
import argparse
import oci
import os
import logging
import sys

from pathlib import Path
from util import check_oci_configuration

# Workaround for ImportError: attempted relative import with no known parent package
sys.path.append(os.path.dirname(os.path.realpath(__file__)))

NAMESPACE = "grrjnyzvhu1t"
BUCKET_NAME = "General_ltrace_files"

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(sys.stdout))


def process(args):
    logger.info("Starting upload file to OCI bucket process.")
    config = oci.config.from_file()
    check_oci_configuration(config)

    input_file_path = Path(args.file)
    output_bucket_file_path = Path(args.bucket_output_directory) / input_file_path.name
    if not input_file_path.exists():
        raise AttributeError(f"File {input_file_path.as_posix()} doesn't exist.")

    with open(input_file_path.as_posix(), "rb") as file:
        object_storage_client = oci.object_storage.ObjectStorageClient(config)
        object_storage_client.put_object(args.namespace, args.bucket_name, output_bucket_file_path.as_posix(), file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload files to Oracle Cloud Infrastructure bucket.")
    parser.add_argument(
        "--file", help="Specify a version. Otherwise, the most recent will be downloaded.", default=None
    )
    parser.add_argument(
        "--bucket-output-directory",
        help="The output directory from bucket. Default to the root directory.",
        default=None,
    )
    parser.add_argument(
        "--bucket-name",
        help=f"The bucket name. Default to '{BUCKET_NAME}'.",
        default=BUCKET_NAME,
    )
    parser.add_argument(
        "--namespace",
        help=f"The bucket namespace. Default to '{NAMESPACE}'.",
        default=NAMESPACE,
    )

    args = parser.parse_args()
    try:
        process(args)
    except Exception as error:
        logger.info(f"Found a problem! Cancelling process...")
        logger.info(f"Error: {error}")
        sys.exit(1)

    logger.info("The file was succesfully uploaded.")
    sys.exit(0)
