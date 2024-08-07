from pathlib import Path
import json


ROOT = Path(__file__).resolve().absolute().parent / "assets"
PUBLIC = ROOT / "public"
PRIVATE = ROOT / "private"


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


def get_trained_models(environment):
    models_path = Path(__file__).resolve().absolute().parent / "assets" / "models"

    extensions = [".h5", ".pth"]
    models = []
    for root_path in (PUBLIC, PRIVATE):
        models_path = root_path / environment
        models += [file for file in models_path.glob("**/*") if file.suffix in extensions]
    return models


def get_trained_models_with_metadata(environment):
    models = []
    for root_path in (PUBLIC, PRIVATE):
        models_path = root_path / environment
        if not models_path.is_dir():
            continue
        for subdir in models_path.iterdir():
            if not subdir.is_dir():
                continue
            base = subdir.name
            pth = subdir / f"model.pth"

            assert pth.exists(), f"Directory {base} exists but file {pth} does not exist"

            models.append(subdir)
    return models


def get_metadata(model_dir):
    model_dir = Path(model_dir)
    with open(model_dir / f"meta.json") as f:
        metadata = json.load(f)
    return metadata


def get_pth(model_dir):
    model_dir = Path(model_dir)
    return model_dir / f"model.pth"
