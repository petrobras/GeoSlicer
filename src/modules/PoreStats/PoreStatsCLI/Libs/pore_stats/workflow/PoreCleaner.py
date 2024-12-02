import sys
import nrrd
import numpy as np

from workflow.commons import run_subprocess, write


class PoreCleaner:

    ## PoreCleaner: Remoção de poros espúrios e artefatos na resina

    # Este módulo é responsável por aplicar duas operações de "limpeza" na segmentação de poros
    # convencional, que se não realizadas podem impactar negativamente nos resultados finais.

    ### Remoção de poros espúrios

    # Os segmentadores de poro atuais do GeoSlicer tendem a gerar detecções espúrias em pequenas regiões
    # compreendidas por rocha mas que por efeitos de iluminação/resolução/afins têm coloração parecida
    # com a da resina azul de poro. O módulo executa um modelo capaz de reconhecer essas detecções e
    # diferencia-las das corretas, com base nos valores de pixel dentro de um intervalo em torno do
    # centróide de cada segmento. Todos os poros espúrios detectados são descartados.

    ### Incorporação de bolhas e resíduos na resina de poro

    # É comum que se formem na resina de poro algumas bolhas de ar e resíduos relacionados. Os
    # segmentadores não detectam esses artefatos, não interpretando-os como área de poro, o que
    # influencia no tamanho e quantidade dos poros detectados. Este módulo visa "limpar" a resina,
    # incluindo essas bolhas e resíduos ao corpo do poro correspondente. Basicamente, três critérios
    # devem ser atendidos para que uma região da imagem seja interpretada como bolha/resíduo:

    # 1. **Ter cor branca ou ter cor azul com pouca intensidade e saturação:** em geral, as bolhas são
    # brancas ou, quando cobertas de material, têm um tom de azul quase negro. Os resíduos que
    # eventualmente circundam as bolhas também tem um nível de azul pouco intenso;
    # 2. **Tocar na resina de poro:** a transição entre a resina e os artefatos é normalmente direta e
    # suave. Como o modelo de segmentação de poro detecta bem a região de resina, o artefato precisa
    # tocar nessa região. Consequentemente, o algoritmo atual não consegue detectar casos menos comuns
    # em que o artefato tome 100% da área do poro;
    # 3. **Ser pouco visível na imagem PX/c2:** alguns elementos da rocha podem ser parecidos com os
    # artefatos e também ter contato com a resina. Porém, no geral, os artefatos são pouco ou nada
    # visíveis nas imagens PX/c2, enquanto os demais elementos são geralmente notáveis. Note que essa
    # análise exige um bom registro (alinhamento espacial) entre as imagens PP/c1 e PX/c2. O algoritmo
    # tenta corrigir possíveis desalinhamentos centralizando uma imagem sobre a outra, opcionalmente
    # considerando apenas a área útil (obtida através do recurso ForegroundSegmenter) de cada uma.

    # O NRRD de poros é novamente atualizado, desta vez com a porosidade "limpa" com base no(s) recurso(s)
    # aplicado(s).

    def __init__(
        self,
        pore_model,
        keep_spurious,
        keep_residues,
        remove_spurious_cli_path,
        clean_resin_cli_path,
        save_unclean_resin=False,
    ):
        self.pore_model = pore_model
        self.keep_spurious = keep_spurious
        self.keep_residues = keep_residues
        self.remove_spurious_cli_path = remove_spurious_cli_path
        self.clean_resin_cli_path = clean_resin_cli_path
        self.save_unclean_resin = save_unclean_resin

    def run(self, frags_file_path, seg_path, px_image_path, pp_rock_area_path, px_rock_area_path, decide_best_reg):
        if self.keep_spurious and self.keep_residues:
            return seg_path

        unclean_resin_path = seg_path.replace(".nrrd", "_noclean.nrrd")
        if not self.keep_spurious:
            # Remoção de poros espúrios
            run_subprocess(
                [
                    sys.executable,
                    self.remove_spurious_cli_path,
                    "--input",
                    frags_file_path,
                    "--output",
                    seg_path,
                    "--poreseg",
                    seg_path,
                    "--poresegmodel",
                    self.pore_model,
                ]
            )

        if not self.keep_residues:
            if self.save_unclean_resin:
                binary_data = nrrd.read(seg_path, index_order="C")
                binary_seg = binary_data[0][0].astype(bool)

                write(unclean_resin_path, binary_seg.astype(np.uint8), header=binary_data[1])

            # Incorporação de bolhas e resíduos na resina de poro
            extra_args = []
            for arg, array_path in zip(
                ["--pximage", "--pprockarea", "--pxrockarea"], [px_image_path, pp_rock_area_path, px_rock_area_path]
            ):
                if array_path is not None:
                    extra_args += [arg, array_path]
            if decide_best_reg:
                extra_args.append("--smartreg")

            run_subprocess(
                [
                    sys.executable,
                    self.clean_resin_cli_path,
                    "--ppimage",
                    frags_file_path,
                    "--poreseg",
                    seg_path,
                    "--output",
                    seg_path,
                ]
                + extra_args
            )

        return seg_path
