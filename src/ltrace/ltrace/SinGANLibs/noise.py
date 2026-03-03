import torch
import torch.nn.functional as F
import numpy as np
import math
from ltrace.SinGANLibs.partition_manager import PartitionManager
from abc import ABC, abstractmethod
from typing import Dict


class Noise(ABC):
    @abstractmethod
    def get_scale_noise(self, index):
        pass

    @abstractmethod
    def get_noise_patch(self, no_pad_slice, index):
        pass

    @abstractmethod
    def reset_cache(self):
        pass

    @abstractmethod
    def force_dynamic_base_size(self):
        pass

    @abstractmethod
    def suspend_dynamic_base_size(self):
        pass


class NoiseReconstruction(Noise):
    def __init__(self, noises, pad):
        assert isinstance(noises, list)
        self.noises = noises
        self.no_pad_noises = [noise[:, :, pad:-pad, pad:-pad, pad:-pad] for noise in noises]

    def get_scale_noise(self, index):
        return self.noises[index]

    def get_noise_patch(self, no_pad_slice, index):
        return self.no_pad_noises[index][no_pad_slice]

    def reset_cache(self):
        pass

    def force_dynamic_base_size(self):
        pass

    def suspend_dynamic_base_size(self):
        pass

    def get_no_pad_noises_shapes(self):
        shapes = []
        for z_scale in self.no_pad_noises:
            shapes.append(z_scale.shape)
        return shapes


class NoiseSavedInDisk(Noise):
    def __init__(self, noise_folder, model_shapes, pad):
        assert isinstance(noise_folder, str)
        self.model_shapes = model_shapes
        self.noise_folder = noise_folder
        self.pad = pad
        self.noises = self.set_noise()

    def set_noise(self):
        noises = []
        for k, shape in enumerate(self.model_shapes):
            noise = torch.load(f"{self.noise_folder}/z_{k}.pth", weights_only=True, mmap=True)
            assert shape == noise.shape
            noises.append(noise)
        return noises

    def get_scale_noise(self, index):
        return F.pad(self.noises[index], [self.pad] * 6, value=0)

    def get_noise_patch(self, no_pad_slice, index):
        return self.noises[index][no_pad_slice]

    def reset_cache(self):
        pass

    def force_dynamic_base_size(self):
        pass

    def suspend_dynamic_base_size(self):
        pass


class DynamicNoise(Noise, PartitionManager):
    def __init__(
        self,
        model_shapes,
        base_volume,
        pad,
        seed=None,
        img_num_channel=1,
        use_cache=False,
    ):
        super().__init__(model_shapes, img_num_channel)
        self.base_volume = base_volume
        self.pad = pad
        self.seed_range = [0, 10_000_000]
        self.main_seed = (
            seed if seed is not None else np.random.randint(low=self.seed_range[0], high=self.seed_range[1])
        )
        self.dynamic_base_size = False
        self.scale_factors = self.set_scale_factors()
        self.all_scale_patch_dim = self.set_all_scale_patch_dim()
        self.all_scale_partition = self.set_all_scale_partition()
        self.scale_seeds = self.set_scale_seeds()
        self.use_cache = use_cache
        if self.use_cache:
            self.cache = {k: {} for k in range(len(self.model_shapes))}

    def set_scale_factors(self):
        if self.dynamic_base_size:
            scale_factors = {
                index: [self.model_shapes[index][k] / self.model_shapes[-1][k] for k in range(2, 5)]
                for index in range(len(self.model_shapes))
            }
        else:
            scale_factors = {index: [1.0, 1.0, 1.0] for index in range(len(self.model_shapes))}
        return scale_factors

    def get_patch_dim(self, index: int):
        max_size = max([self.base_volume * self.scale_factors[index][i] for i in range(3)])
        patch_dim = math.ceil(
            max_size + 3 * self.pad
        )  # 3 * self.padd ensures partition_base_size larger than the patch
        return patch_dim

    def set_all_scale_patch_dim(self) -> Dict:
        patch_dims = {k: self.get_patch_dim(k) for k in range(len(self.model_shapes))}
        return patch_dims

    def get_scale_patch_dim(self, index):
        return self.all_scale_patch_dim[index]

    def get_scale_partition(self, index):
        return self.all_scale_partition[index]

    def set_scale_seeds(self):
        scale_seeds = {}
        np.random.seed(self.main_seed)
        for index in range(len(self.model_shapes)):
            scale_seeds[index] = np.random.choice(
                np.arange(self.seed_range[0], self.seed_range[1], 1),
                size=len(self.get_scale_partition(index)),
                replace=False,
            )
        return scale_seeds

    def get_random_tensor(self, size, seed):
        torch.manual_seed(seed)
        return torch.randn(1, self.img_num_channel, *size, device=torch.device("cpu"))

    def get_base_elements(self, base_indices, index):
        base_elements = {}
        unique_base_indices = set(base_indices)

        for base_index in unique_base_indices:
            limits = self.get_scale_partition(index)[base_index]
            base_elements[base_index] = self.get_random_tensor(
                size=[limits[1] - limits[0], limits[3] - limits[2], limits[5] - limits[4]],
                seed=self.scale_seeds[index][base_index],
            )
        return base_elements

    def get_base_elements_with_caching(self, base_indices, index):
        unique_base_indices = set(base_indices)
        cached_indices = set(self.cache[index].keys())
        indices_to_generate = unique_base_indices.difference(cached_indices)
        cached_indices_to_delete = cached_indices.difference(unique_base_indices)

        for index_to_delete in cached_indices_to_delete:
            del self.cache[index][index_to_delete]

        for base_index in indices_to_generate:
            limits = self.get_scale_partition(index)[base_index]
            self.cache[index][base_index] = self.get_random_tensor(
                size=[limits[1] - limits[0], limits[3] - limits[2], limits[5] - limits[4]],
                seed=self.scale_seeds[index][base_index],
            )

        return {k: self.cache[index][k] for k in base_indices}

    def get_noise_patch(self, no_pad_slice, index):
        base_indices = self.get_base_indices(no_pad_slice, index)
        base_elements_limits = [self.get_scale_partition(index)[k] for k in base_indices]

        if not self.use_cache:
            base_elements = self.get_base_elements(base_indices, index)
        else:
            base_elements = self.get_base_elements_with_caching(base_indices, index)

        merged_patch = self.get_merged_patch(no_pad_slice, base_elements_limits, base_elements, base_indices)
        merged_patch = torch.from_numpy(merged_patch)
        return merged_patch

    def get_scale_noise(self, index):
        scale_noise = torch.empty(self.model_shapes[index])
        partition_slices = self.get_scale_partition_slices(index)
        base_elements = self.get_base_elements(partition_slices.keys(), index)

        for k, slice_ in partition_slices.items():
            scale_noise[slice_] = base_elements[k]

        return F.pad(scale_noise, [self.pad] * 6, value=0)

    def force_dynamic_base_size(self):
        self.dynamic_base_size = True
        self.scale_factors = self.set_scale_factors()
        self.all_scale_patch_dim = self.set_all_scale_patch_dim()
        self.all_scale_partition = self.set_all_scale_partition()
        self.scale_seeds = self.set_scale_seeds()

    def suspend_dynamic_base_size(self):
        self.dynamic_base_size = False
        self.scale_factors = self.set_scale_factors()
        self.all_scale_patch_dim = self.set_all_scale_patch_dim()
        self.all_scale_partition = self.set_all_scale_partition()
        self.scale_seeds = self.set_scale_seeds()

    def reset_cache(self):
        self.cache = {k: {} for k in range(len(self.model_shapes))}
