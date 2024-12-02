import os
import sys
from workflow.commons import (
    dict_to_arg,
    get_check_cli_path,
    get_model_type,
    get_models_dir,
    get_models_info,
    run_subprocess,
)


class PoreSegmenter:

    ## PoreSegmenter: Segmentação binária de poros

    # O CLI de segmentação binária de poro é invocado para operar a partir do caminho para o NRRD da
    # imagem original, salvo pelo ThinSectionLoader. O resultado é salvo em um novo NRRD.

    def __init__(self, pore_model, seg_cli_path):
        self.pore_model_path = self._get_pore_model_path(pore_model)
        self.seg_cli_path, self.xargs, self.extra_args = self._get_cli_args(seg_cli_path)

    def _get_pore_model_path(self, pore_model):
        models_info = get_models_info()

        pore_model_path = None
        if pore_model in models_info.keys():
            for candidate_base_path in models_info[pore_model].candidate_base_paths:
                candidate_path = os.path.join(get_models_dir(), candidate_base_path)
                if os.path.isfile(candidate_path):
                    pore_model_path = candidate_path
        else:
            pore_model_path = pore_model

        assert pore_model_path is not None, f"No {pore_model} trained model was found in {get_models_dir()}"
        assert os.path.exists(pore_model_path), f"Trained model not found in {pore_model_path}"
        assert (
            os.path.isfile(pore_model_path) and os.path.splitext(pore_model_path)[-1] == ".pth"
        ), f"Invalid trained model: {pore_model_path}"

        return pore_model_path

    def _get_cli_args(self, cli_path):
        def get_cli_info():
            model_type = get_model_type(self.pore_model_path)
            if "bayes" in model_type:
                cli_file_prefix = "BayesianInference"
                xargs = "null"
                extra_args = []
            else:
                cli_file_prefix = "MonaiModels"
                xargs = dict_to_arg({"deterministic": False})
                extra_args = ["--ctypes", "rgb"]
            return cli_file_prefix, xargs, extra_args, model_type

        cli_file_prefix, xargs, extra_args, model_type = get_cli_info()
        cli_path = get_check_cli_path(cli_file_prefix, cli_path)
        assert ("bayes" in model_type) == (
            cli_file_prefix == "BayesianInference"
        ), f"{cli_file_prefix}CLI is not compatible with model of type {model_type}"

        return cli_path, xargs, extra_args

    def run(self, nrrd_image_file_path):
        output_file_path = nrrd_image_file_path.replace(".nrrd", "_seg.nrrd")
        if not os.path.exists(output_file_path):
            print("* Segmenting pores...")
            run_subprocess(
                [
                    sys.executable,
                    self.seg_cli_path,
                    "--master",
                    nrrd_image_file_path,
                    "--xargs",
                    self.xargs,
                    "--ctypes",
                    "rgb",
                    "--outputvolume",
                    output_file_path,
                    "--inputmodel",
                    self.pore_model_path,
                    "--returnparameterfile",
                    nrrd_image_file_path.replace(".nrrd", ".params"),
                ]
                + self.extra_args
            )

        return output_file_path
