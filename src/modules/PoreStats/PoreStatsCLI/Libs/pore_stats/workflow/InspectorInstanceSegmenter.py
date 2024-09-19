import os
import sys
import nrrd
from scipy import ndimage as ndi
from workflow.commons import run_subprocess, write, get_cli_modules_dir, dict_to_arg


class InspectorInstanceSegmenter:

    ## InspectorInstanceSegmenter: Separação de instâncias e cálculo de propriedades geológicas

    # Este módulo aproveita uma aplicação CLI do GeoSlicer para separar as instâncias da segmentação de
    # entrada em NRRD, calcular suas propriedades geológicas e gerar um relatório de saída. A primeira
    # etapa é aplicada apenas aos poros, visto que os oóides já são naturalmente detectados de forma
    # separada.

    # O algoritmo de separação das instâncias depende da especificação do usuário, podendo alternar
    # entre islands, que os separa por conectividade simples de pixeis, ou watershed, que aplica o
    # algoritmo de mesmo nome.

    def __init__(self, algorithm, min_size, sigma, min_distance, pixel_size, inspector_cli_path, no_cli=False):
        self.algorithm = algorithm
        self.min_size = min_size
        self.sigma = sigma
        self.min_distance = min_distance
        self.pixel_size = pixel_size
        self.inspector_cli_path = self._get_cli_path(inspector_cli_path)
        self.no_cli = no_cli

    def _get_cli_path(self, cli_path):
        if cli_path is None:
            cli_path = os.path.join(get_cli_modules_dir(), "SegmentInspectorCLI", "SegmentInspectorCLI.py")

        assert os.path.exists(cli_path), f"CLI {cli_path} not found."
        return cli_path

    def _get_params(self):
        if self.algorithm == "islands":
            params = {
                "method": "islands",
            }
        else:
            params = {
                "method": "snow",
                "sigma": self.sigma,
                "d_min_filter": self.min_distance,
                "generate_throat_analysis": False,
                "voxel_size": self.pixel_size,
            }

        params["size_min_threshold"] = self.min_size
        params["direction"] = []
        return params

    def run(self, nrrd_seg_file_path, generate_partitions):
        if generate_partitions:
            instance_seg_file_path = nrrd_seg_file_path.replace(".nrrd", "_instance.nrrd")
            products = "partitions,report"
        else:
            print("Calculating properties...")
            instance_seg_file_path = nrrd_seg_file_path[:]
            products = "report"
        params_file_path = instance_seg_file_path.replace(".nrrd", ".params")
        report_file_path = instance_seg_file_path.replace(".nrrd", ".pkl")

        if self.no_cli:
            instance_seg_file_path = instance_seg_file_path.replace(".nrrd", "_noinspector.nrrd")
            binary_seg_array, header = nrrd.read(nrrd_seg_file_path, index_order="C")
            write(instance_seg_file_path, ndi.label(binary_seg_array[0])[0], header=header)
        else:
            params = self._get_params()

            run_subprocess(
                [
                    sys.executable,
                    self.inspector_cli_path,
                    "--labels",
                    nrrd_seg_file_path,
                    "--params",
                    dict_to_arg(params),
                    "--products",
                    products,
                    "--output",
                    instance_seg_file_path,
                    "--report",
                    report_file_path,
                    "--returnparameterfile",
                    params_file_path,
                ]
            )

            os.remove(params_file_path)
        return instance_seg_file_path, report_file_path
