import os

import cv2
import nrrd
import numpy as np

from workflow.commons import no_extra_dim_read


class ImageExporter:

    ## ImageExporter: Geração de imagem destacando as instâncias segmentadas em cada imagem original

    # Módulo responsável por salvar uma imagem em formato trandicional (PNG) exibindo os resultados
    # finais das segmentações para todos os tipos de instância (atualmente poros e oóides). A imagem
    # final é uma cópia da imagem PP original, porém colorindo aleatoriamente cada instância detectada.

    def _save_plot(self, image, image_name, output_dir):
        image_output_dir = os.path.join(output_dir, image_name)
        os.makedirs(image_output_dir, exist_ok=True)
        cv2.imwrite(os.path.join(image_output_dir, f"{image_name}.png"), cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

    def run(self, image_file_path, instance_seg_file_path, output_dir):
        image_name = os.path.splitext(os.path.basename(image_file_path))[0]

        image = no_extra_dim_read(image_file_path)

        instance_seg = nrrd.read(instance_seg_file_path, index_order="C")[0][0]

        # Essa solução é MUITO mais rápida que a atribuição direta de uma cor aleatória para cada label em um for-loop
        # Basicamente: as cores são criadas antecipadamente, então as labels do instance_seg são usadas como índices para o array de cores
        num_labels = np.max(instance_seg)
        random_colors = np.random.randint(0, 256, size=(num_labels, 3))
        image_with_instance_seg = image.copy()
        image_with_instance_seg[instance_seg > 0] = random_colors[instance_seg[instance_seg > 0] - 1]

        self._save_plot(image_with_instance_seg, image_name, output_dir)
