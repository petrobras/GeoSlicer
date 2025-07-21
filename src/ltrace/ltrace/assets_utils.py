import slicer
import json

from pathlib import Path

ROOT = Path(__file__).resolve().absolute().parent / "assets"
PUBLIC = ROOT / "public"
PRIVATE = ROOT / "private"


def get_public_asset_path():
    """Returns the public assets directory absolute path"""
    return PUBLIC.as_posix()


def get_asset(asset_name):
    """Returns the asset's absolute Path given a relative path from either public or private dir.
    Do not include 'public' or 'private' in the path.
    """
    if isinstance(asset_name, str):
        asset_name = Path(asset_name)

    private_path = PRIVATE / asset_name
    if private_path.exists():
        return private_path

    public_path = PUBLIC / asset_name
    if public_path.exists():
        return public_path

    return None


def get_model_by_name(name: str) -> Path:
    paths = slicer.app.settings().value("AISingleModelsPaths", {})
    if name in paths.keys():
        return Path(paths[name]).parent
    else:
        raise FileExistsError(f"Could not find model with name {name}")


def get_models_by_tag(tags: list[str]) -> list[str]:
    pathList = slicer.app.settings().value("AIModelsPaths", [])
    models = []

    if not pathList:
        return models

    for path in pathList:
        directories = [d for d in Path(path).rglob("*") if d.is_dir()]

        for _dir in directories:
            if _dir.parent.name not in tags:
                continue

            modelPthFile = _dir / "model.pth"
            modelH5File = _dir / "model.h5"
            metaFile = _dir / "meta.json"

            if (modelPthFile.exists() or modelH5File.exists()) and metaFile.exists():
                models.append(_dir)

    return models


def get_metadata(model_dir: str) -> dict:
    if not model_dir:
        raise ValueError("Model directory parameter is empty.")

    model_dir = Path(model_dir)
    if not model_dir.exists():
        raise FileNotFoundError(f"Model directory '{model_dir.as_posix()}' does not exist.")

    with open(model_dir / f"meta.json") as f:
        metadata = json.load(f)
    return metadata


def get_pth(model_dir: str) -> Path:
    model_dir = Path(model_dir)
    return model_dir / f"model.pth"


def get_h5(model_dir: str) -> Path:
    model_dir = Path(model_dir)
    return model_dir / f"model.h5"
