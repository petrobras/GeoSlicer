import os
import cv2
import nrrd
import numpy as np
from scipy import ndimage as ndi
from skimage import color, morphology
from workflow.commons import no_extra_dim_read, write


class FragmentsSplitter:

    ## FragmentsSplitter: Isolamento dos fragmentos de interesse da rocha

    # Muitas imagens possuem grandes regiões "vazias", preenchidas por resina de poro, que são
    # detectadas pelo PoreSegmenter mas que não correspondem de fato à porosidade da rocha, mas apenas à
    # região em volta de seu(s) fragmento(s). Em alguns casos específicos, não todos mas apenas os N
    # maiores fragmentos da seção de rocha interessam. Os nomes das imagens que se encaixam nessa
    # situação devem constar no arquivo `filter_images.csv`, juntamente ao valor de N. Para isolar os
    # fragmentos úteis da rocha, a seguinte sequência de operações é aplicada:

    # * Primeiramente, o maior fragmento, correspondente à toda área da seção, é isolado das bordas da
    # imagem;
    # * Então, toda porosidade detectada que toque a borda da imagem é também descartada, pois é
    # interpretada como resina de poro visível ao redor da área útil da rocha;
    # * Por fim, caso a imagem conste entre as precisem considerar apenas os *N* maiores fragmentos, o
    # tamanho (em pixeis) de cada fragmento da área útil restante é medido e apenas os N maiores são
    # mantidos.

    # O NRRD dos poros detectados é atualizado descartando toda detecção não-contida na área útil da
    # rocha.

    def _filter_largest_islands(self, seg, n_largest_islands):

        # Filtra os N maiores fragmentos.

        print("** Filtering the", n_largest_islands, "largest island(s)... ***")

        seg = cv2.erode(seg.astype(np.uint8), np.ones((23, 23), np.uint8))  # para limpar pequenos artefatos
        islands = ndi.label(seg)[0]
        islands_sizes = np.bincount(islands.ravel())
        sorted_labels = np.argsort(islands_sizes)[::-1]
        sorted_labels = sorted_labels[sorted_labels != 0]
        seg[~np.isin(islands, sorted_labels[:n_largest_islands])] = 0

        print("*** Filtered. ***")
        return seg.astype(bool)

    def get_rock_area(self, image):

        # Isola a área da rocha da borda da imagem

        def equalize_each_channel(image):
            return np.stack([cv2.equalizeHist(image[:, :, i]) for i in range(3)], axis=2)

        eq = equalize_each_channel(image)
        blur = cv2.GaussianBlur(eq, (199, 199), 255)

        lum = color.rgb2gray(blur)
        mask = morphology.remove_small_holes(morphology.remove_small_objects((lum > 0.3) & (lum < 0.7), 500), 500)

        mask = morphology.opening(mask, morphology.disk(3))
        mask = self._filter_largest_islands(
            mask, 1
        )  # para pegar a área central da rocha e eliminar artefatos deixados nas bordas
        return ndi.binary_fill_holes(mask)

    def run(self, image_path, seg_path, n_largest_islands=None):
        frags_file_path = image_path.replace(".nrrd", "_frags.nrrd")
        image, image_header = no_extra_dim_read(image_path, return_header=True)

        binary_data = nrrd.read(seg_path, index_order="C")
        binary_seg = binary_data[0][0]

        # Separa a área da rocha das bordas as imagem
        binary_seg_with_border = binary_seg.copy()
        rock_area = self.get_rock_area(image)

        if not os.path.exists(frags_file_path):
            # Funde as bordas da imagem aos poros detectados que as tocam
            binary_seg_with_border[np.where(rock_area == 0)] = 1

            # Descarta o conjunto borda + poros periféricos
            binary_frags = np.logical_not(binary_seg_with_border)
            frags_mask = ndi.binary_fill_holes(binary_frags)

            # Filtra os N maiores fragmentos se necessário
            if n_largest_islands:
                frags_mask = self._filter_largest_islands(frags_mask, n_largest_islands)

            frags_image = image * np.stack(3 * [frags_mask], axis=2)

            write(frags_file_path, frags_image, header=image_header)
            write(seg_path, binary_seg * frags_mask, header=binary_data[1])
        return frags_file_path, rock_area
