import drd
from pathlib import Path


class Source:
    ELEVEN = "Eleven Sandstones"
    ICL_2009 = "ICL Sandstone Carbonates 2009"
    ICL_2015 = "ICL Sandstone Carbonates 2015"


def load(hierarchy, data_home):
    data_home.mkdir(parents=True, exist_ok=True)
    root = hierarchy[0]
    if root == Source.ELEVEN:
        dataset = hierarchy[1]
        filename = hierarchy[2]
        array = drd.datasets.load_eleven_sandstones(dataset=dataset, filename=filename, data_home=data_home)
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

    array.to_netcdf(output_path / "output.nc")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("hierarchy", type=str, help="Hierarchy")
    parser.add_argument("data_home", type=str, help="Data Home")
    args = parser.parse_args()

    hierarchy = args.hierarchy.split("/")
    load(hierarchy, Path(args.data_home))
