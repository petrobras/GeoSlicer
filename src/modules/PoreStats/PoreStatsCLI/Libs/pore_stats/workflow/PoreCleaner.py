import os
import pickle
import time
import warnings
import cv2
import joblib
import nrrd
import numpy as np
from scipy import ndimage as ndi
from skimage import measure
from tqdm import tqdm
from skimage.segmentation import watershed
from workflow.commons import no_extra_dim_read, write


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
    # visíveis nas imagens PX/c2, enquanto os demais elementos são geralmente notáveis. Algumas imagens
    # do poço RJS-702, porém, não têm um bom alinhamento natual ou facilmente corrigível entre as imagens
    # PP e PX, dificultando essa correspondência de regiões. Esta etapa é então ignorada para essas
    # imagens, listadas no arquivo `not_use_px.csv`, o que pode resultar em sobressegmentação dos poros
    # por capturar falsos artefatos.

    # O NRRD de poros é novamente atualizado, desta vez com os poros "limpos".

    def __init__(self, pore_model, keep_spurious, keep_residues, save_unclean_resin=False):
        self.pore_model = pore_model
        self.keep_spurious = keep_spurious
        self.keep_residues = keep_residues
        self.save_unclean_resin = save_unclean_resin

    def _remove_spurious(self, image, binary_seg):
        def get_roi_from_centroid(cy, cx, image, seg, i_seg, roi_size):
            def get_ref_point(cy, cx, seg, i_seg):
                def try_getting_ref_point(y, x, seg):
                    if any(np.isnan(coord) for coord in [y, x]):
                        return False, y, x
                    y, x = int(y), int(x)
                    return seg[y, x], y, x

                cy, cx = np.clip(int(cy), 0, seg.shape[0] - 1), np.clip(int(cx), 0, seg.shape[1] - 1)

                if not seg[cy, cx]:
                    seg_y, seg_x = np.where(seg == i_seg)

                    y, x = cy, cx
                    success, y, x = try_getting_ref_point(cy, np.median(seg_x[(seg_x < cx) & (seg_y == cy)]), seg)
                    if not success:
                        success, y, x = try_getting_ref_point(cy, np.median(seg_x[(seg_x > cx) & (seg_y == cy)]), seg)
                    if not success:
                        success, y, x = try_getting_ref_point(np.median(seg_y[(seg_y < cy) & (seg_x == cx)]), cx, seg)
                    if not success:
                        success, y, x = try_getting_ref_point(np.median(seg_y[(seg_y > cy) & (seg_x == cx)]), cx, seg)

                    cy = y
                    cx = x

                return cy, cx

            offset = roi_size // 2

            # Em alguns casos, o centróide do segmento reside fora dele. Então, tenta-se obter o pixel mediano do segmento à esquerda
            # do centróide. Se não houver, tenta-se à direita. Então, acima. Em último caso, abaixo.
            cy, cx = get_ref_point(cy, cx, seg, i_seg)
            y0, x0 = max(0, cy - offset), max(0, cx - offset)
            y1, x1 = y0 + roi_size, x0 + roi_size
            if y1 > image.shape[0]:
                d = y1 - image.shape[0]
                y0, y1 = y0 - d, y1 - d
            if x1 > image.shape[1]:
                d = x1 - image.shape[1]
                x0, x1 = x0 - d, x1 - d
            assert y1 - y0 == roi_size
            assert x1 - x0 == roi_size

            return image[y0:y1, x0:x1].flatten()

        split_pores = ndi.label(binary_seg)[0]

        if split_pores.max() > 0:
            # Há um modelo RandomForest de remoção de poros espúrios para cada modelo de segmentação de poros
            with open(
                os.path.join(__file__, "..", "..", "models", "spurious_removal", f"spurious_{self.pore_model}.pkl"),
                "rb",
            ) as pkl:
                scaler_and_model = pickle.load(pkl)
                scaler = scaler_and_model["scaler"]
                model = scaler_and_model["model"]

            # Para cada segmento de poro, é obtida uma pequena região de interesse (ROI) em volta do centróide
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore")

                print("Removing spurious pore detections...")
                start_time = time.time()
                regions_props = measure.regionprops(split_pores, intensity_image=image)

                rois = []
                pred_indexes = []
                for i in tqdm(range(1, split_pores.max() + 1)):
                    region_props = regions_props[i - 1]
                    if (
                        region_props.area < 3
                    ):  # porque o Segment Inspector não inclui segmentos com menos de 3 pixeis no relatório
                        split_pores[split_pores == i] = 0
                    else:
                        cy, cx = region_props.centroid
                        roi = get_roi_from_centroid(cy, cx, image, split_pores, i, roi_size=10)
                        rois.append(roi)
                        pred_indexes.append(i)

                if len(rois) > 0:
                    # O modelo detecta os ROIs espúrios e os descarta
                    predictions = model.predict(scaler.transform(np.array(rois)))
                    valid_pred_indexes = np.array(pred_indexes)[np.nonzero(predictions)[0]]

                    split_pores = np.where(np.isin(split_pores, valid_pred_indexes), split_pores, 0)
                    n_valid = len(valid_pred_indexes)
                else:
                    n_valid = 0

                n_discarded = i - n_valid

            print(f"Done: {n_valid} detections kept, {n_discarded} discarded ({time.time() - start_time}s).")
        else:
            print("No pores found.")

        return split_pores.astype(bool)

    def _clean_resin(self, image, binary_seg, px_image, pp_rock_area, px_rock_area, decide_best_reg):
        def remove_artifacts(mask, open_kernel_size, close_kernel_size):
            if open_kernel_size is not None:
                open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_kernel_size, open_kernel_size))
                mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, open_kernel)
            if close_kernel_size is not None:
                close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_kernel_size, close_kernel_size))
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel).astype(bool)

            return mask

        def get_roi_from_blue_channel(image):
            blue_channel = image[:, :, 2]
            blue_channel = cv2.equalizeHist(blue_channel)

            # with open(os.path.join(__file__, '..', '..', 'models', 'pore_residues', 'blue_channel.pkl'), 'rb') as pkl:
            #    kmeans = pickle.load(pkl)

            # Usando joblib em vez de pickle para aproveitar a compressão do modelo (K-Means pickle fica muito grande)
            # O modelo joblib foi salvo usando a mesma versão do Python usado para executar este script (PythonSlicer). Divergência de versão causa erro.
            kmeans = joblib.load(os.path.join(__file__, "..", "..", "models", "pore_residues", "blue_channel.pkl"))

            clusters = kmeans.predict(blue_channel.flatten().reshape(-1, 1))
            blue_mask = clusters.reshape(blue_channel.shape) == kmeans.cluster_centers_.argmax()
            return remove_artifacts(blue_mask, open_kernel_size=20, close_kernel_size=None)

        def get_roi_from_hue_channel(image):
            hue_channel = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)[:, :, 0]

            hue_mask = (hue_channel >= 75) & (
                hue_channel <= 135
            )  # blue hue, which catches both the resin and the dark bubbles/residues
            for open_kernel_size, close_kernel_size in [(5, None), (None, 13), (13, None)]:
                hue_mask = remove_artifacts(
                    hue_mask, open_kernel_size=open_kernel_size, close_kernel_size=close_kernel_size
                )

            return hue_mask

        def get_roi_from_px_hsv(pp, px, pores_mask, decide_best_reg):
            def crop_rock_area(image, rock_area):
                non_zero_coords = cv2.findNonZero(rock_area.astype(np.uint8))
                x, y, w, h = cv2.boundingRect(non_zero_coords)
                crop = image[y : y + h, x : x + w]
                return crop

            def register_px_to_pp(pp, px, pp_rock_area=None, px_rock_area=None):
                reg_px = np.zeros((max(pp.shape[0], px.shape[0]), max(pp.shape[1], px.shape[1]), 3)).astype(np.uint8)
                orig_pp_shape = pp.shape

                if pp_rock_area is not None:
                    pp = crop_rock_area(pp, pp_rock_area)
                if px_rock_area is not None:
                    px = crop_rock_area(px, px_rock_area)

                px_y0 = reg_px.shape[0] // 2 - px.shape[0] // 2
                px_y1 = reg_px.shape[0] // 2 + px.shape[0] // 2 + px.shape[0] % 2
                px_x0 = reg_px.shape[1] // 2 - px.shape[1] // 2
                px_x1 = reg_px.shape[1] // 2 + px.shape[1] // 2 + px.shape[1] % 2

                reg_px[px_y0:px_y1, px_x0:px_x1] = px.copy()

                pp_y0 = reg_px.shape[0] // 2 - orig_pp_shape[0] // 2
                pp_y1 = reg_px.shape[0] // 2 + orig_pp_shape[0] // 2 + orig_pp_shape[0] % 2
                pp_x0 = reg_px.shape[1] // 2 - orig_pp_shape[1] // 2
                pp_x1 = reg_px.shape[1] // 2 + orig_pp_shape[1] // 2 + orig_pp_shape[1] % 2

                return reg_px[pp_y0:pp_y1, pp_x0:pp_x1]

            reg_px = {
                "Centralized": register_px_to_pp(pp, px),
            }
            if decide_best_reg:
                reg_px.update(
                    {
                        "Cropped and centralized": register_px_to_pp(
                            pp, px, pp_rock_area=pp_rock_area, px_rock_area=px_rock_area
                        )
                    }
                )
            px_pores_mask = None
            best_reg_quality = -1
            best_method = None
            for method, px in reg_px.items():
                px_hsv = cv2.cvtColor(cv2.GaussianBlur(px, (99, 99), 9), cv2.COLOR_RGB2HSV)

                kmeans = joblib.load(os.path.join(__file__, "..", "..", "models", "pore_residues", "px_hsv.pkl"))
                clusters = kmeans.predict(px_hsv.flatten().reshape(-1, 3))
                test_px_pores_mask = clusters.reshape(px_hsv.shape[:2]) == 3
                test_px_pores_mask = remove_artifacts(test_px_pores_mask, open_kernel_size=13, close_kernel_size=13)

                reg_area = np.count_nonzero(test_px_pores_mask & pores_mask)
                pore_area = np.count_nonzero(pores_mask)
                test_reg_quality = reg_area / pore_area if pore_area > 0 else 0
                print(method, "registration quality:", "{:.2f} %".format(100 * test_reg_quality))
                if test_reg_quality > best_reg_quality:
                    best_method = method
                    best_reg_quality = test_reg_quality
                    px_pores_mask = test_px_pores_mask

            print(best_method, "registration method chosen.")
            return px_pores_mask

        def grow_pores_through_mask(mask, pores):
            markers = pores & mask
            return watershed(~mask, markers=markers, mask=mask)

        use_px = px_image is not None

        print("Detecting air bubbles and residues in pore resin... Using PX:", {False: "No", True: "Yes"}[use_px])
        start_time = time.time()

        # O canal azul da imagem funde as bolhas brancas à resina azul
        blue_mask = get_roi_from_blue_channel(image)
        # O canal Hue da imagem funde as bolhas negras e resíduos à resina azul
        hue_mask = get_roi_from_hue_channel(image)

        if use_px:
            # A região escura do PX funde as bolhas e resíduos à região porosa
            px_pores_mask = get_roi_from_px_hsv(image, px_image, binary_seg, decide_best_reg)

            # As regiões não-escuras do PX são descartadas das regiões úteis dos canais azul e Hue
            blue_mask &= px_pores_mask
            hue_mask &= px_pores_mask

        # Os poros detectados crescem sobre a região azul, cobrindo as bolhas brancas
        bubbled_blue_mask = grow_pores_through_mask(blue_mask, binary_seg)
        # Os poros detectados crescem sobre a região Hue, cobrindo as bolhas negras e resíduos
        bubbled_hue_mask = grow_pores_through_mask(hue_mask, binary_seg)

        print(f"Done ({time.time() - start_time}s).")
        # As regiões crescidas são unidas. Os poros originais são reinclusos para o caso de terem sido
        # perdidos por um mal alinhamento entre PP e PX
        return bubbled_blue_mask | bubbled_hue_mask | binary_seg

    def run(self, frags_file_path, seg_path, px_image, pp_rock_area, px_rock_area, decide_best_reg):
        if self.keep_spurious and self.keep_residues:
            return seg_path

        image = no_extra_dim_read(frags_file_path)
        binary_data = nrrd.read(seg_path, index_order="C")
        binary_seg = binary_data[0][0].astype(bool)

        unclean_resin_path = seg_path.replace(".nrrd", "_noclean.nrrd")
        if not self.keep_spurious:
            # Remoção de poros espúrios
            binary_seg = (
                self._remove_spurious(image, binary_seg)
                if not os.path.exists(unclean_resin_path)
                else nrrd.read(unclean_resin_path, index_order="C")[0][0]
            )
        if not self.keep_residues:
            if self.save_unclean_resin:
                write(unclean_resin_path, binary_seg.astype(np.uint8), header=binary_data[1])
            # Incorporação de bolhas e resíduos na resina de poro
            binary_seg = self._clean_resin(image, binary_seg, px_image, pp_rock_area, px_rock_area, decide_best_reg)

        write(seg_path, binary_seg.astype(np.uint8), header=binary_data[1])
        return seg_path
