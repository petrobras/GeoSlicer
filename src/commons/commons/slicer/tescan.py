import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Tuple
from dataclasses import dataclass


def _parse_parameter_xml(file_path):
    tree = ET.parse(file_path)
    root = tree.getroot()

    params = {}

    for param in root.findall("Parameter"):
        name_elem = param.find("Name")
        value_elem = param.find("Value")

        if name_elem is not None and value_elem is not None:
            name = name_elem.text or ""
            value = value_elem.text or ""
            params[name] = value

    return params


def _find_tescan_files(base_dir: Path):
    base_dir = Path(base_dir)

    if any(base_dir.glob("*.acq.1.xml")):
        # we're in root/
        root_dir = base_dir
        recon_dir = base_dir / "recon"
    elif any(base_dir.glob("*.rec.1.xml")):
        # we're in recon/
        recon_dir = base_dir
        root_dir = base_dir.parent
    else:
        return None

    acq_files = list(root_dir.glob("*.acq.1.xml"))
    rec_files = list(recon_dir.glob("*.rec.1.xml"))

    if not acq_files:
        return None
    if not rec_files:
        return None
    if not any(recon_dir.glob("*.tif")):
        return None

    return acq_files[0], rec_files[0], recon_dir


def _get_tescan_parameters(acq_file: Path, rec_file: Path):
    acq_params = _parse_parameter_xml(acq_file)
    rec_params = _parse_parameter_xml(rec_file)

    voxel_size = rec_params.get("VoxelSize", "1.0")
    voxel_size = float(voxel_size)

    object_to_world = acq_params["ObjectToWorld"]
    object_to_world = tuple(float(x) for x in object_to_world.split(";"))

    return voxel_size, object_to_world


@dataclass
class TescanInfo:
    origin_xyz: Tuple[float, float, float]
    spacing: float
    image_dir: Path


def get_tescan_info(base_dir: Path) -> TescanInfo:
    if not base_dir.is_dir():
        return None
    tescan_files = _find_tescan_files(base_dir)
    if tescan_files is None:
        return None

    acq_file, rec_file, recon_dir = tescan_files
    voxel_size, object_to_world = _get_tescan_parameters(acq_file, rec_file)
    return TescanInfo(origin_xyz=object_to_world, spacing=voxel_size, image_dir=recon_dir)
