import slicer, slicer.util, mrml
import numpy as np
import os

from .generate_image import GenerateImage
from ltrace.slicer.cli_utils import progressUpdate, readFrom, writeDataInto
from pathlib import Path
from tqdm import tqdm


class SequentialMPS:
    def __init__(self, opt):
        self.sim_grid_cell_size = [1, 1, 1]  # Should be opt["grid_cell_size"], but does not matter in inpainting
        self.nreal = 1  # Looped outside of mpslib
        self.ncond = opt["ncond"]
        self.n_max_ite = opt["iterations"]
        self.rseed = opt["rseed"]
        self.n_patches = opt["patches"]
        self.neighbor_size = opt["neighbor_size"]
        self.hard_data_res = [1, 1, 1]  # Does not matter in inpainting
        self.root_path = opt["root_path"]
        self.fname = opt["fname"]
        self.ti = opt["ti"]
        self.hd = opt["hd"]
        self.colocate_dimensions = opt["colocateDimensions"]
        self.max_search_radius = opt["maxSearchRadius"]
        self.distance_max = opt["distanceMax"]
        self.distance_power = opt["distancePower"]
        self.distance_measure = opt["distanceMeasure"]

    def get_img(self, id):
        referenceVolumeNode = readFrom(id, mrml.vtkMRMLScalarVolumeNode)
        volumeArray = slicer.util.arrayFromVolume(referenceVolumeNode)

        return volumeArray

    def get_partition(self, shape, n_patches, ns):
        # edges = np.linspace(0, shape[-2], num=n_patches + 1, dtype=int)
        edges = np.linspace(0, shape[0], num=n_patches + 1, dtype=int)
        slices = []

        for k in range(len(edges) - 1):
            # slice_ = np.s_[:, max(0, edges[k] - ns) : min(edges[k + 1], shape[-2])]
            slice_ = np.s_[max(0, edges[k] - ns) : min(edges[k + 1], shape[0]), :]
            slices.append(slice_)
        return slices

    def delete_aux_files(self):
        for file in ["ti.dat", "mps.txt", "hard.dat"]:
            if os.path.exists(file):
                os.remove(file)

    def get_hard_data(self, patch):
        i_s, j_s, k_s = np.where(patch >= 0)
        values = patch[i_s, j_s, k_s]
        hd = np.concatenate([i_s[:, np.newaxis], j_s[:, np.newaxis], k_s[:, np.newaxis], values[:, np.newaxis]], axis=1)
        sorted_indices = np.lexsort((hd[:, 0].astype(int), hd[:, 1].astype(int), hd[:, 2].astype(int)))
        hd = hd[sorted_indices]
        return hd

    def preprocess_img(self, img):
        img = np.where(img <= -9999, np.NAN, img)
        return img

    def run_3d(self, realization):
        hd_img = self.get_img(self.hd)
        ti_img = self.get_img(self.ti)

        slices = self.get_partition(hd_img.shape, self.n_patches, self.neighbor_size)

        total_time = 0

        for k, out_img_slice in enumerate(tqdm(slices), start=1):
            self.delete_aux_files()
            ti_patch = self.preprocess_img(ti_img[out_img_slice])
            hd_patch = self.preprocess_img(hd_img[out_img_slice])

            hard_data = self.get_hard_data(hd_patch)

            self.generate_image = GenerateImage()
            self.generate_image.create_TI_file(ti_patch)
            self.generate_image.configure_MPS_method(
                hard_data,
                hd_patch.shape,
                self.sim_grid_cell_size,
                self.ncond,
                self.nreal,
                self.hard_data_res,
                self.n_max_ite,
                self.rseed,
                self.colocate_dimensions,
                self.max_search_radius,
                self.distance_max,
                self.distance_power,
                self.distance_measure,
            )
            out, partial_time = self.generate_image.run()
            hd_img[out_img_slice] = out[0]
            ti_img[out_img_slice] = out[0]

            total_time += partial_time

        self.delete_aux_files()
        np.save(Path(self.root_path).parent.joinpath(f"sim_data_{realization}.npy"), hd_img)

        return total_time
