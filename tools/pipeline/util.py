import oci
import logging
import re
import sys

from datetime import datetime
from packaging.version import parse
from pathlib import Path


PLATFORMS_FILE_DATA = {"win32": ("win", "zip"), "linux": ("linux", "tar.gz")}


class GeoSlicerBaseFileData:
    def __init__(self, file_path: str, platform=sys.platform):
        platform = "linux" if platform.startswith("linux") else platform
        os_tag, extension = PLATFORMS_FILE_DATA[platform]
        if match := re.search(rf"GeoSlicer-(.+?)-(\d{{4}}-\d{{2}}-\d{{2}})-{os_tag}\S+{extension}", file_path):
            version = parse(match.group(1))
            date = datetime.strptime(match.group(2), "%Y-%m-%d")
            self.file_path = file_path
            self.version = version
            self.date = date
        else:
            raise AttributeError(f"The file {file_path} doesn't match the GeoSlicer base compressed file pattern.")

    def __eq__(self, other) -> bool:
        return self.version == other.version and self.date == other.date

    def __lt__(self, other) -> bool:
        return self.version <= other.version and self.date < other.date

    def __le__(self, other) -> bool:
        return self.version <= other.version and self.date <= other.date

    def __ne__(self, other) -> bool:
        return not self.__eq__(other)

    def __gt__(self, other) -> bool:
        return self.version >= other.version and self.date > other.date

    def __ge__(self, other) -> bool:
        return self.version >= other.version and self.date >= other.date


def check_oci_configuration(config, logger=logging):
    logger.info("Checking OCI credentials...")
    try:
        oci.config.validate_config(config)
    except (ValueError, oci.config.InvalidConfig):
        raise RuntimeError("OCI Configuration file is invalid. Please check it.")

    logger.info("OCI credentials are okay!")


def download_file_from_bucket(
    object_storage_client,
    namespace: str,
    bucket_name: str,
    file_path_from_bucket: str,
    output_file_path: Path,
    logger=logging,
):
    if output_file_path.is_dir():
        file_base_name = Path(file_path_from_bucket).name
        output_file_path = output_file_path / file_base_name

    logger.info("Retrieving file from bucket...")
    get_obj = object_storage_client.get_object(namespace, bucket_name, file_path_from_bucket)
    with open(output_file_path.as_posix(), "wb") as f:
        for chunk in get_obj.data.raw.stream(1024 * 1024, decode_content=False):
            f.write(chunk)

    if output_file_path.exists():
        logger.info(f"Downloaded completed! File location: {output_file_path.as_posix()}")
    else:
        raise RuntimeError(f"Downloaded finished with errors... Please check the logs.")
