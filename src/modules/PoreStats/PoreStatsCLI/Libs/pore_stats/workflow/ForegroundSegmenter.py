import os
import sys
import nrrd
import numpy as np
from workflow.commons import get_check_cli_path, no_extra_dim_read, run_subprocess, write


class ForegroundSegmenter:

    ## ForegroundSegmenter: Isolamento da área de interesse da rocha

    # Normalmente, as imagens de seção delgada incluem grandes áreas de borda não-úteis para a análise
    # da rocha. Além disso, muitas imagens possuem grandes regiões "vazias", preenchidas por resina de poro,
    # que são detectadas pelo PoreSegmenter mas que não correspondem de fato à porosidade da rocha, mas
    # apenas à região em volta de seu(s) fragmento(s). Em alguns casos específicos, não todos mas apenas os N
    # maiores fragmentos da seção de rocha interessam.
    #
    # Este módulo permite isolar a área útil (não-borda) da rocha e, opcionalmente, separar seus fragmentos.
    # Apenas para o segundo caso a segmentação prévia da resina de poro é necessária. O processo completo
    # inclui a seguinte sequência de operações:

    # * Primeiramente, o maior fragmento, correspondente à toda área da seção, é isolado das bordas da
    # imagem;
    # * Então, no caso de separação dos fragmentos, toda porosidade detectada que toque a borda da imagem
    # é também descartada, pois é interpretada como resina de poro visível ao redor da área útil da rocha;
    # * Por fim, no caso opcional de se considerar apenas os *N* maiores fragmentos, o tamanho (em pixeis)
    # de cada fragmento da área útil restante é medido e apenas os N maiores são mantidos.

    # O NRRD dos poros detectados é atualizado descartando toda detecção não-contida na área útil da
    # rocha.

    def __init__(self, cli_path):
        self.cli_path = get_check_cli_path(cli_file_prefix="SmartForeground", cli_path=cli_path)

    def run(self, image_path, seg_path=None, n_largest_islands=None):
        rock_seg_path = image_path.replace(".nrrd", "_seg_rock.nrrd")
        extra_args = []

        if seg_path:
            binary_data = nrrd.read(seg_path, index_order="C")
            binary_seg = binary_data[0][0].astype(np.uint8)
            extra_args += ["--poreseg", seg_path]

        image_name = os.path.splitext(os.path.basename(image_path))[0]
        print(f"Getting {'PX' if image_name.endswith('c2') else ''} rock area", end="")
        if seg_path:
            if n_largest_islands is None:
                print(" and splitting fragments", end="")
            else:
                print(f", splitting fragments and filtering the {n_largest_islands} largest one(s)", end="")
        print("...")

        run_subprocess(
            [
                sys.executable,
                self.cli_path,
                "--input",
                image_path,
                "--outputrock",
                rock_seg_path,
                "--max_frags",
                str(n_largest_islands) if n_largest_islands is not None else "-1",
            ]
            + extra_args
        )

        if seg_path:
            frags_file_path = image_path.replace(".nrrd", "_frags.nrrd")

            frags_mask = nrrd.read(rock_seg_path, index_order="C")[0][0].astype(np.uint8)

            image, image_header = no_extra_dim_read(image_path, return_header=True)
            frags_image = image * np.stack(3 * [frags_mask], axis=2)

            write(frags_file_path, frags_image, header=image_header, extra_dim=image_header["dimension"] > 3)
            write(seg_path, binary_seg * frags_mask, header=binary_data[1])

            return frags_file_path, rock_seg_path

        return rock_seg_path
