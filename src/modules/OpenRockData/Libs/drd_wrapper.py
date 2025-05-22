import drd
import numpy as np
import xarray as xr
import os
import requests
from pathlib import Path
from drd.datasets.download_utils import download_url, get_data_home
from drd.datasets.utils import load_numpy_from_raw, create_xarray_from_numpy

DATASET_METADATA = {
    "Berea": {
        "Berea_2d25um_grayscale.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "Berea_2d25um_grayscale_filtered.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "Berea_2d25um_binary.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
    },
    "Bandera Brown": {
        "BanderaBrown_2d25um_grayscale.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "BanderaBrown_2d25um_grayscale_filtered.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "BanderaBrown_2d25um_binary.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
    },
    "Bandera Gray": {
        "BanderaGray_2d25um_grayscale.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "BanderaGray_2d25um_grayscale_filtered.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "BanderaGray_2d25um_binary.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
    },
    "Bentheimer": {
        "Bentheimer_2d25um_grayscale.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "Bentheimer_2d25um_grayscale_filtered.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "Bentheimer_2d25um_binary.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
    },
    "Berea Sister Gray": {
        "BSG_2d25um_grayscale.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "BSG_2d25um_grayscale_filtered.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "BSG_2d25um_binary.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
    },
    "Berea Upper Gray": {
        "BUG_2d25um_grayscale.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "BUG_2d25um_grayscale_filtered.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "BUG_2d25um_binary.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
    },
    "Buff Berea": {
        "BB_2d25um_grayscale.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "BB_2d25um_grayscale_filtered.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "BB_2d25um_binary.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
    },
    "CastleGate": {
        "CastleGate_2d25um_grayscale.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "CastleGate_2d25um_grayscale_filtered.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "CastleGate_2d25um_binary.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
    },
    "Kirby": {
        "Kirby_2d25um_grayscale.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "Kirby_2d25um_grayscale_filtered.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "Kirby_2d25um_binary.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
    },
    "Leopard": {
        "Leopard_2d25um_grayscale.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "Leopard_2d25um_grayscale_filtered.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "Leopard_2d25um_binary.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
    },
    "Parker": {
        "Parker_2d25um_grayscale.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "Parker_2d25um_grayscale_filtered.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
        "Parker_2d25um_binary.raw": {
            "voxel_length": [2.25, 2.25, 2.25],
            "metric_voxel_length_unit": 1e-6,
            "width": 1000,
            "height": 1000,
            "number_of_slices": 1000,
            "byte_order": "little-endian",
            "image_type": np.uint8,
        },
    },
}


def load_eleven_sandstones(dataset: str, filename: str, data_home: str = None) -> xr.DataArray:
    metadata = DATASET_METADATA[dataset][filename]

    data_home = get_data_home(data_home=data_home)
    if not os.path.exists(data_home):
        os.makedirs(data_home)

    file_path = os.path.join(data_home, filename)
    url = f"https://digitalporousmedia.org/api/datafiles/tapis/download/private/drp.project.published.DRP-317/{dataset}/{filename}/{filename}/"
    print("Requesting URL at:", url)

    response = requests.get(url)
    response.raise_for_status()
    json_data = response.json()
    url = json_data.get("data")

    print("Downloading file from URL:", url)

    download_url(url, root=data_home, filename=filename)

    img = load_numpy_from_raw(
        file_path, metadata["image_type"], metadata["height"], metadata["width"], metadata["number_of_slices"]
    )
    img = create_xarray_from_numpy(
        img,
        filename,
        metadata["voxel_length"],
        metadata["metric_voxel_length_unit"],
        metadata["height"],
        metadata["width"],
        metadata["number_of_slices"],
    )

    return img


class Source:
    ELEVEN = "Eleven Sandstones"
    ICL_2009 = "ICL Sandstone Carbonates 2009"
    ICL_2015 = "ICL Sandstone Carbonates 2015"


def load(hierarchy, data_home, output_name="output.nc"):
    data_home.mkdir(parents=True, exist_ok=True)
    root = hierarchy[0]
    if root == Source.ELEVEN:
        dataset = hierarchy[1]
        filename = hierarchy[2]
        array = load_eleven_sandstones(dataset=dataset, filename=filename, data_home=data_home)
    elif root == Source.ICL_2009:
        dataset = hierarchy[1]
        array = drd.datasets.load_icl_sandstones_carbonates_2009(dataset=dataset, data_home=data_home)
    elif root == Source.ICL_2015:
        dataset = hierarchy[1]
        download_root = data_home / "downloads"
        extract_root = data_home / "extracted"
        download_root.mkdir(parents=True, exist_ok=True)
        extract_root.mkdir(parents=True, exist_ok=True)
        array = drd.datasets.load_icl_microct_sandstones_carbonates_2015(
            dataset=dataset, data_home=data_home, download_root=download_root, extract_root=extract_root
        )

    output_path = data_home / "output_nc"
    output_path.mkdir(parents=True, exist_ok=True)

    array.to_netcdf(output_path / output_name)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("hierarchy", type=str, help="Hierarchy")
    parser.add_argument("data_home", type=str, help="Data Home")
    parser.add_argument("output_name", type=str, help="Output Name")
    args = parser.parse_args()

    hierarchy = args.hierarchy.split("/")
    load(hierarchy, Path(args.data_home), args.output_name)
