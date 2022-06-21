from pathlib import Path
from typing import List


def parse_command_stdout(sim_info_output_list: List[str]):
    from collections import defaultdict

    parse = lambda item: item.strip().split(" ")

    sim_info = defaultdict(list)
    for item in sim_info_output_list:
        if "work_dir = " in item:
            sim_info["work_dir"].append(str(parse(item)[2]))
        if "job_id = " in item:
            print(item)
            print(parse(item))
            print("done ----------------")
            sim_info["job_id"].append(int(parse(item)[2]))
        if "start_time = " in item:
            sim_info["start_time"].append(" ".join(parse(item)[2:]))
        if "simulation_type = " in item:
            sim_info["simulation_type"].append(str(parse(item)[2]))
        if "simulation_output = " in item:
            sim_info["simulation_output"].append(str(parse(item)[2]))
        if "slurm_file = " in item:
            sim_info["slurm_output"].append(str(parse(item)[2]))
        if "final_results = " in item:
            sim_info["final_results"].append(str(parse(item)[2]))

    # if len(sim_info.get("final_results", [])) == 0:

    #     textout = "\n".join(sim_info_output_list)
    #     raise RuntimeError(
    #         f"{textout}\nResults location is missing from output info. KeyError: 'final results'"
    #     )

    return sim_info


def node_to_mct_format(node, name=None, direction="z", img_type="bin"):
    import xarray as xr
    import numpy as np

    import slicer

    from ltrace.algorithms.common import FlowSetter

    if name is None:
        name = node.GetName()

    basename_list = name.split("_")

    resolution = min([i for i in node.GetSpacing()])  # pegar o spacing correto para cada dimensao
    img = slicer.util.arrayFromVolume(node)

    if img_type == "bin":
        img = img.astype(
            np.uint8
        )  # inverte apenas usando o parametro e continua passando pra frente pra inverter no CLI
    elif img_type == "kabs":
        img = img.astype(np.float32)

    if direction in ("x", "y", "z"):
        fs = FlowSetter(direction=direction)
        img_t = fs.apply(img)
    else:
        img_t = img

    dimz, dimy, dimx = img_t.shape

    attrs = {}
    attrs["well"] = basename_list[0]
    attrs["sample_name"] = basename_list[1] if len(basename_list) > 1 else ""
    attrs["condition"] = basename_list[2] if len(basename_list) > 2 else ""
    attrs["sample_type"] = basename_list[3] if len(basename_list) > 3 else ""
    attrs["dimx"] = dimx
    attrs["dimy"] = dimy
    attrs["dimz"] = dimz
    attrs["resolution"] = float(resolution)  # mm

    dict_name = img_type  # if img.dtype == np.uint8 else 'microtom'

    x = np.linspace(0, attrs["resolution"] * dimx, dimx)
    y = np.linspace(0, attrs["resolution"] * dimy, dimy)
    z = np.linspace(0, attrs["resolution"] * dimz, dimz)

    ds = xr.Dataset(
        {dict_name: (("z", "y", "x"), img_t)},
        coords={"z": z, "y": y, "x": x},
        attrs=attrs,
    )

    ds.x.attrs["units"] = "mm"
    ds.y.attrs["units"] = "mm"
    ds.z.attrs["units"] = "mm"

    return ds, dict_name


def read_file(selectedPath: Path):
    import microtom

    ext = selectedPath.suffix

    if ext == ".tar":
        ds = microtom.read_tar_file(str(selectedPath))
    elif ext == ".raw":
        ds = microtom.read_raw_file(str(selectedPath))
    elif ext == ".vtk":
        ds = microtom.read_vtk_file(str(selectedPath))
    elif ext == ".nc":
        ds = microtom.read_netcdf_file(str(selectedPath))
    elif ext == ".h5" or ext == ".hdf5":
        ds = microtom.read_netcdf_file(str(selectedPath))
    else:
        raise TypeError(f"{ext} is not a valid extension.")

    return ds


def convert_z_axis(direction, volumeArray):
    direction = direction if direction in ("x", "y", "z") else "z"

    if direction == "y":
        return volumeArray.transpose((1, 2, 0))
    elif direction == "x":
        return volumeArray.transpose((2, 1, 0))

    return volumeArray


def revert_z_axis(direction, volumeArray):
    direction = direction.lower()
    direction = direction if direction in ("x", "y", "z") else "z"

    if direction == "y":
        return volumeArray.transpose((2, 0, 1))
    elif direction == "x":
        return volumeArray.transpose((2, 1, 0))

    return volumeArray
