import json
import os

import cv2
import nrrd
import numpy as np
from csbdeep.utils import normalize
from stardist.models import Config2D, StarDist2D

from workflow.commons import no_extra_dim_read, write


class OoidSegmenter:

    ## OoidSegmenter: Segmentação de oóides

    # Um modelo neural treinado para detecção de oóides também é aplicado e tem seu resultado salvo em
    # NRRD. Diferentemente da natureza binária do segmentador de poros, este já separa as diferentes
    # instâncias do elemento.

    # Na prática, este modelo é dividido em dois: uma parada detecção de instâncias grandes e outros
    # para pequenas. As grandes são detectadas primeiro, então as pequenas são detectadas apenas na
    # região não compreendida pelas grandes. Eles foram treinados e são aplicados em versões de escala
    # reduzida das imagens.

    def __init__(self, resized_input=False):
        self.scale = 1 / 4 if not resized_input else 2.5

        basedir = os.path.join(__file__, "..", "..", "models", "ooids")
        self.model_small = self._load_model(basedir=basedir, logdir="small")
        self.model_big = self._load_model(basedir=basedir, logdir="big")

    def _load_model(self, basedir, logdir):
        with open(os.path.join(basedir, logdir, "config.json"), "r") as file:
            config = json.load(file)
        config = Config2D(**config)
        model = StarDist2D(config, name=logdir, basedir=basedir)
        model.load_weights("ooids.h5")

        return model

    def _predict(self, image):
        print("Detecting ooids...")

        preds = []
        label_offset = 0

        for model in [self.model_big, self.model_small]:
            print(f"\tGetting {os.path.basename(model.logdir)} ones...")
            pred, _ = model.predict_instances(image, n_tiles=model._guess_n_tiles(image), show_tile_progress=True)

            pred[pred > 0] += label_offset
            label_offset = pred.max()
            preds.append(pred)

        final_pred = np.zeros(image.shape[:2]).astype(np.uint16)
        for pred in preds:
            overlapping_instances = np.unique(pred[np.where((final_pred > 0) & (pred > 0))])
            pred[np.isin(pred, overlapping_instances)] = 0
            final_pred[final_pred == 0] = pred[final_pred == 0]

        print("Done.")
        return final_pred

    def run(self, nrrd_frags_file_path, pore_instance_seg_file_path):
        pore_instance_data = nrrd.read(pore_instance_seg_file_path, index_order="C")
        pore_instance_seg = pore_instance_data[0][0]
        image = no_extra_dim_read(nrrd_frags_file_path)
        frags_mask = np.any(image != 0, axis=2)
        image = cv2.resize(image, (0, 0), fx=self.scale, fy=self.scale)
        image = normalize(image, 1, 99.8, axis=(0, 1))

        ooids = self._predict(image)

        ooids = cv2.resize(ooids, pore_instance_seg.shape[1::-1], interpolation=cv2.INTER_NEAREST)
        ooids[(frags_mask == 0) | (pore_instance_seg != 0)] = 0

        ooids_file_path = nrrd_frags_file_path.replace("frags.nrrd", "ooids.nrrd")
        write(ooids_file_path, ooids.astype(np.uint8), header=pore_instance_data[1])

        return ooids_file_path
