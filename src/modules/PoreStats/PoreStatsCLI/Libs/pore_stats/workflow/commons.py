import glob
import os
import subprocess
import sys

import nrrd
import torch


class ModelInfo:
    def __init__(self, kind, kernel_size, candidate_base_paths):
        self.kind = kind
        self.kernel_size = kernel_size
        self.candidate_base_paths = candidate_base_paths


DESCRIPTIVE_STATISTICS = {
    "mean": "Mean",
    "median": "Median",
    "std": "Standard deviation",
    "max": "Maximum",
    "min": "Minimum",
}


def dict_to_arg(dict):
    return str(dict).lower().replace("'", '"')


def delete_tmp_nrrds(tmp_dir):
    nrrd_paths = glob.glob(os.path.join(tmp_dir, "*.nrrd"))
    for nrrd_path in nrrd_paths:
        os.remove(nrrd_path)


def write(path, array, header, extra_dim=True):
    if extra_dim:
        array = array.reshape(1, *array.shape)
    nrrd.write(path, array, header, index_order="C")


def no_extra_dim_read(image_file_path, return_header=False):
    image, header = nrrd.read(image_file_path, index_order="C")
    if image.ndim == 4:
        image = image[0]
    if not return_header:
        return image
    return image, header


def get_cli_modules_dir():
    geoslicer_path = sys.executable.split(os.path.join(os.sep, "bin"))[0]
    base_dirs = glob.glob(os.path.join(geoslicer_path, "lib", "GeoSlicer-5.*"))
    assert len(base_dirs) == 1, f"{len(base_dirs)} candidates to base directory found: {base_dirs}"
    cli_modules_dir = os.path.join(base_dirs[0], "cli-modules")
    if os.path.exists(cli_modules_dir):
        return cli_modules_dir
    else:
        raise FileNotFoundError(f"CLI modules directory {cli_modules_dir} not found.")


def get_models_dir():
    candidate_dirs = []
    geoslicer_path = sys.executable.split(os.path.join(os.sep, "bin"))[0]
    for envs_dir in ["trained_models", "private"]:
        models_dir = os.path.join(
            geoslicer_path, "lib", "Python", "Lib", "site-packages", "ltrace", "assets", envs_dir, "ThinSectionEnv"
        )
        candidate_dirs.append(models_dir)
        if os.path.exists(models_dir):
            return models_dir
    raise FileNotFoundError(f"No candidate models directory path found: {candidate_dirs}")


def get_models_info():
    return {
        "unet": ModelInfo(
            kind="torch",
            kernel_size=None,
            candidate_base_paths=[
                "petrobras_carbonate_pore_u_net.pth",
                os.path.join("petrobras_carbonate_pore_u_net", "petrobras_carbonate_pore_u_net.pth"),
                os.path.join("carb_pore", "model.pth"),
            ],
        ),
        "sbayes": ModelInfo(
            kind="bayesian",
            kernel_size=3,
            candidate_base_paths=[
                "petrobras_pores_bayesian_3px.pth",
                os.path.join("petrobras_pores_bayesian_3px", "petrobras_pores_bayesian_3px.pth"),
                os.path.join("bayes_3px", "model.pth"),
            ],
        ),
        "bbayes": ModelInfo(
            kind="bayesian",
            kernel_size=7,
            candidate_base_paths=[
                "petrobras_pores_bayesian_7px.pth",
                os.path.join("petrobras_pores_bayesian_7px", "petrobras_pores_bayesian_7px.pth"),
                os.path.join("bayes_7px", "model.pth"),
            ],
        ),
    }


def get_model_type(model_type_or_path):
    models_info = get_models_info()
    if model_type_or_path in models_info.keys():
        return model_type_or_path

    config = torch.load(model_type_or_path)["config"]
    model_kind = config["meta"]["kind"]
    model_params = config["model"]["params"]
    model_kernel_size = model_params["kernel_size"] if "kernel_size" in model_params else None

    for type, info in models_info.items():
        if model_kind == info.kind and model_kernel_size == info.kernel_size:
            return type
    raise ValueError(f"Unrecognized model kind {model_kind} in {model_type_or_path}")


def run_subprocess(args):
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _, error = process.communicate()
    if process.returncode != 0:
        raise RuntimeError(error)


# from SegmentInspectorCLI.py
def addUnitsToDataFrameParameters(df):
    def appendUnit(data, parameter, unit_str):
        if parameter not in data.columns:
            return data

        data = data.rename(columns={parameter: f"{parameter} ({unit_str})"})
        return data

    df = appendUnit(df, "voxelCount ", "voxels")
    df = appendUnit(df, "area", "mm^2")
    df = appendUnit(df, "volume", "mm^3")
    df = appendUnit(df, "angle_ref_to_max_feret", "deg")
    df = appendUnit(df, "angle_ref_to_min_feret", "deg")
    df = appendUnit(df, "angle", "deg")
    df = appendUnit(df, "min_feret", "mm")
    df = appendUnit(df, "max_feret", "mm")
    df = appendUnit(df, "mean_feret", "mm")
    df = appendUnit(df, "ellipse_perimeter", "mm")
    df = appendUnit(df, "ellipse_area", "mm^2")
    df = appendUnit(df, "ellipse_perimeter_over_ellipse_area", "1/mm")
    df = appendUnit(df, "perimeter", "mm")
    df = appendUnit(df, "perimeter_over_area", "1/mm")
    df = appendUnit(df, "angle", "mm^2")
    df = appendUnit(df, "ellipsoid_area", "mm^2")
    df = appendUnit(df, "ellipsoid_volume", "mm^3")
    df = appendUnit(df, "ellipsoid_area_over_ellipsoid_volume", "1/mm")
    df = appendUnit(df, "sphere_diameter_from_volume", "mm")

    return df
