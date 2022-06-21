from pathlib import Path
import json


def get_asset(asset_name):
    """Returns the asset's absolute Path given a relative path from this dir."""
    if isinstance(asset_name, str):
        asset_name = Path(asset_name)

    absolute_path = Path(__file__).resolve().absolute().parent / "assets" / asset_name
    if not absolute_path.exists():
        raise RuntimeError("Invalid asset: {}".format(absolute_path))

    return absolute_path


def get_trained_model(model_name):
    return get_asset(Path("trained_models") / Path(model_name))


def get_trained_models(environment=None):
    models_path = Path(__file__).resolve().absolute().parent / "assets" / "trained_models"

    if environment:
        models_path = models_path / environment

    extensions = [".h5", ".pth"]
    models = [file for file in models_path.glob("**/*") if file.suffix in extensions]
    return models


def get_trained_models_with_metadata(environment):
    models_path = Path(__file__).resolve().absolute().parent / "assets" / "trained_models"
    models_path = models_path / environment

    models = []
    for subdir in models_path.iterdir():
        if not subdir.is_dir():
            continue
        base = subdir.name
        pth = subdir / f"{base}.pth"

        assert pth.exists(), f"Directory {base} exists but file {pth} does not exist"

        models.append(subdir)
    return models


def get_metadata(model_dir):
    model_dir = Path(model_dir)
    with open(model_dir / f"{model_dir.name}.json") as f:
        metadata = json.load(f)
    return metadata


def get_pth(model_dir):
    model_dir = Path(model_dir)
    return model_dir / f"{model_dir.name}.pth"
