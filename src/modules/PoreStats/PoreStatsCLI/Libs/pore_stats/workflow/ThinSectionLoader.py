import os
from PIL import Image, ImageFile
import cv2
import numpy as np

from workflow.commons import write

Image.MAX_IMAGE_PIXELS = None
ImageFile.LOAD_TRUNCATED_IMAGES = True


class ThinSectionLoader:

    ## ThinSectionLoader: Carregamento das imagens

    # A imagem PP/c1 é carregada e salva em formato NRRD compatível com as aplicações em CLI executadas nas etapas
    # posteriores. O cabeçalho do arquivo é diferente de acordo com o modelo de segmentação de poro escolhido
    # (Bayesiano ou neural), visto que são administrados por diferentes CLI's. Opcionalmente, a versão PP/c2 também
    # pode ser carregada para uso posterior, mais especificamente para incorporação de bolhas e resíduos na resina
    # de poro através do módulo PoreCleaner.

    THIN_SECTION_LOADER_FILE_EXTENSIONS = [".tif", ".tiff", ".png", ".jpg", ".jpeg"]

    def __init__(self, pixel_size, using_bayesian=False, do_resize=False):
        self.pixel_size = pixel_size
        self.using_bayesian = using_bayesian
        self.do_resize = do_resize

    def _get_spacing(self):
        if self.using_bayesian:
            spacing = np.zeros((3, 3))
            spacing[0, 0] = self.pixel_size
            spacing[1, 1] = self.pixel_size
            spacing[2, 2] = self.pixel_size

        else:
            spacing = np.zeros((4, 3))
            spacing[1, 0] = self.pixel_size
            spacing[2, 1] = self.pixel_size
            spacing[3, 2] = self.pixel_size

        return spacing

    def run(self, image_path, tmp_nrrd_dir=None):
        image = np.array(Image.open(image_path))[:, :, :3]
        if self.do_resize:
            image = cv2.resize(image, (0, 0), fx=0.1, fy=0.1)

        # Fornecer o caminho do diretório temporário faz com que o NRRD seja salvo. Caso contrário, a imagem é carregada apenas em memória.
        if tmp_nrrd_dir is not None:
            image_name = os.path.splitext(os.path.basename(image_path))[0]
            output_file_path = os.path.join(tmp_nrrd_dir, f"{image_name}.nrrd")

            # Os modelos bayesianos e o modelo neural têm diferentes CLI, com padrão diferente para o cabeçalho
            if self.using_bayesian:
                header = {
                    "dimension": 3,
                    "space directions": self._get_spacing(),
                    "space": "left-posterior-superior",
                    "kinds": 3 * ["domain"],
                    "encoding": "raw",
                }
            else:
                header = {
                    "space directions": self._get_spacing(),
                    "space": "left-posterior-superior",
                    "kinds": ["RGB-color"] + 3 * ["domain"],
                    "encoding": "raw",
                }
            # Note que apenas o padrão neural usa 4 dimensões
            write(output_file_path, image, header, extra_dim=not self.using_bayesian)
            return output_file_path
        else:
            return image
