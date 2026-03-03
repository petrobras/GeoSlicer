import torch
import numpy as np
from math import ceil
from typing import Dict, List
from ltrace.SinGANLibs.partition_manager import PartitionManager
from pathlib import Path
import json
import netCDF4 as nc
import os


class InterpolationManager(PartitionManager):

    # OBS.: scale_patch_dim must be > base_volume + 2 * pad

    def __init__(self, model_shapes, partition_spec, img_num_channel=1):
        super().__init__(model_shapes, img_num_channel)
        self.partition_spec = partition_spec
        self.all_scale_patch_dim = self.set_all_scale_patch_dim()
        self.all_scale_partition = self.set_all_scale_partition()

    def get_patch_dim(self, shape: List, partition_spec: List) -> List:
        if len(shape) == 3:
            shape = [1, 1, *shape]
        if len(shape) != 5:
            raise Exception("Expected shape format DHW or BCDHW")
        patch_dim = [
            ceil(shape[2] / partition_spec[0]),
            ceil(shape[3] / partition_spec[1]),
            ceil(shape[4] / partition_spec[2]),
        ]
        return patch_dim

    def set_all_scale_patch_dim(self) -> Dict:
        patch_dims = {}
        for index, scale_shape in enumerate(self.model_shapes):
            patch_dims[index] = self.get_patch_dim(scale_shape, self.partition_spec)
        return patch_dims

    def get_scale_patch_dim(self, index):
        return self.all_scale_patch_dim[index]

    def get_scale_partition(self, index):
        return self.all_scale_partition[index]

    def get_partition_slices(self, shape):
        patch_dim = self.get_patch_dim(shape, self.partition_spec)
        partition = self.get_partition(shape, patch_dim)

        slices = {}
        for i, element in enumerate(partition):
            slices[i] = np.s_[
                :,
                :,
                element[0] : element[1],
                element[2] : element[3],
                element[4] : element[5],
            ]
        return slices

    def partition_to_patch(
        self,
        no_pad_slice: slice,
        index: int,
        chunk_paths: Dict = None,
    ):

        base_indices = self.get_base_indices(no_pad_slice, index)
        base_elements_limits = [self.get_scale_partition(index)[k] for k in base_indices]
        base_elements = {k: np.load(chunk_paths[k], mmap_mode="r+") for k in set(base_indices)}

        merged_patch = self.get_merged_patch(no_pad_slice, base_elements_limits, base_elements, base_indices)

        merged_patch = torch.from_numpy(merged_patch)
        return merged_patch

    def patch_to_partition(
        self,
        patch: np.array,
        no_pad_slice: slice,
        index: int,
        chunk_paths: Dict = None,
    ):
        base_indices = self.get_base_indices(no_pad_slice, index)
        base_elements_limits = [self.get_scale_partition(index)[k] for k in base_indices]
        base_elements = {k: np.load(chunk_paths[k], mmap_mode="r+") for k in set(base_indices)}

        self.break_merged_patch(patch, no_pad_slice, base_elements_limits, base_elements, base_indices)

    def get_merged_img(self, chunk_paths: Dict = None):
        merged_img_size = self.model_shapes[-1]
        merged_img = np.zeros(merged_img_size, dtype=np.uint8)
        slices = self.get_scale_partition_slices(len(self.model_shapes) - 1)
        for i, in_slice in slices.items():
            try:
                chunk = np.load(chunk_paths[i], mmap_mode="r")
            except:
                chunk = np.load(chunk_paths[str(i)], mmap_mode="r")
            merged_img[in_slice] = chunk
        return merged_img[0, 0]


class InterpolationManagerMmap(InterpolationManager):
    def __init__(self, model_shapes, partition_spec, temp_dir, img_num_channel=1):
        super().__init__(model_shapes, partition_spec, img_num_channel)
        self.mmaps = {}
        self.out_imgs = {}
        self.temp_dir = temp_dir

    def create_temp_mmap(
        self,
        mmap_key,
        index=None,
        img=None,
    ):
        if index is not None:
            sizes = self.get_scale_partition_sizes(index)
            slices = self.get_scale_partition_slices(index)
            partition = self.get_scale_partition(index)

        elif img is not None:
            patch_dim = self.get_patch_dim(img.shape, self.partition_spec)
            partition = self.get_partition(img.shape, patch_dim)
            slices = self.get_partition_slices(img.shape)
            sizes = {}
            for i, element in enumerate(partition):
                sizes[i] = [element[i + 1] - element[i] for i in [0, 2, 4]]
        else:
            raise Exception("index or img must be specified.")

        self.mmaps[mmap_key] = {
            "paths": {},
            "shapes": {},
            "partition": partition,
            "mmaps": {},
        }

        for element_index, size in sizes.items():
            shape = (1, self.img_num_channel, *size)
            path = str(Path(f"{self.temp_dir}/{mmap_key}_chunk_{element_index}.mmap").absolute())
            self.mmaps[mmap_key]["paths"][element_index] = path
            self.mmaps[mmap_key]["shapes"][element_index] = shape
            mmap = np.memmap(
                filename=path,
                dtype=np.float32,
                mode="w+",
                shape=shape,
            )
            self.mmaps[mmap_key]["mmaps"][element_index] = mmap

            if img is not None:
                mmap[:] = img[slices[element_index]]

    def get_mmap(self, mmap_key, element_index):
        return self.mmaps[mmap_key]["mmaps"][element_index]

    def patch_to_mmap_partition(
        self,
        mmap_key,
        patch: np.array,
        no_pad_slice: slice,
        index: int,
    ):
        base_indices = self.get_base_indices(no_pad_slice, index)
        base_elements_limits = [self.get_scale_partition(index)[k] for k in base_indices]
        base_elements = {k: self.get_mmap(mmap_key, k) for k in set(base_indices)}

        self.break_merged_patch(patch, no_pad_slice, base_elements_limits, base_elements, base_indices)

    def mmap_partition_to_patch(
        self,
        mmap_key,
        no_pad_slice: slice,
        index: int,
    ):

        base_indices = self.get_base_indices(no_pad_slice, index)
        base_elements_limits = [self.get_scale_partition(index)[k] for k in base_indices]
        base_elements = {k: self.get_mmap(mmap_key, k) for k in set(base_indices)}

        merged_patch = self.get_merged_patch(no_pad_slice, base_elements_limits, base_elements, base_indices)

        merged_patch = torch.from_numpy(merged_patch)
        return merged_patch

    def get_merged_img_from_mmap(self, meta: Dict = None):
        merged_img_size = self.model_shapes[-1]
        merged_img = np.zeros(merged_img_size, dtype=np.uint8)
        slices = self.get_scale_partition_slices(len(self.model_shapes) - 1)

        for i, in_slice in slices.items():
            chunk = np.memmap(meta["paths"][str(i)], mode="r", shape=tuple(meta["shapes"][str(i)]))
            merged_img[in_slice] = chunk
        return merged_img[0, 0]

    def prepare_outputs(self, segmented_output, root_path, prefix, partition_spec=None):
        dtype = np.uint8 if segmented_output else np.float32
        index = len(self.model_shapes) - 1

        if partition_spec is None:
            sizes = self.get_scale_partition_sizes(index)
            partition = self.get_scale_partition(index)
        else:
            scale_shape = self.model_shapes[index]
            patch_dim = self.get_patch_dim(scale_shape, partition_spec)
            partition = self.get_partition(scale_shape, patch_dim)
            sizes = {}
            for i, element in enumerate(partition):
                sizes[i] = [element[i + 1] - element[i] for i in [0, 2, 4]]

        self.out_imgs = {
            "patch_dim": patch_dim,
            "dtype": dtype,
            "paths": {},
            "shapes": {},
            "partition": partition,
            "mmaps": {},
        }

        for element_index, size in sizes.items():
            shape = (1, self.img_num_channel, *size)
            path = str(Path(f"{root_path}/{prefix}_chunk_{element_index}.mmap").absolute())
            mmap = np.memmap(
                filename=path,
                dtype=dtype,
                mode="w+",
                shape=shape,
            )
            self.out_imgs["mmaps"][element_index] = mmap
            self.out_imgs["paths"][element_index] = path[:-4] + "nc"
            self.out_imgs["shapes"][element_index] = shape

        with open(f"{root_path}/meta.json") as meta_file:
            meta = json.load(meta_file)

        meta["out_imgs"] = {
            "dtype": "np.uint8" if segmented_output else "np.float32",
            "paths": self.out_imgs["paths"],
            "shapes": self.out_imgs["shapes"],
            "partition": partition,
        }

        with open(f"{root_path}/meta.json", "w") as out_file:
            json.dump(meta, out_file)

    def patch_to_out_imgs(
        self,
        patch: np.array,
        no_pad_slice: slice,
    ):
        index = len(self.model_shapes) - 1
        base_indices = self.get_base_indices(no_pad_slice, index, self.out_imgs["patch_dim"])
        base_elements_limits = [self.out_imgs["partition"][k] for k in base_indices]
        base_elements = {k: self.out_imgs["mmaps"][k] for k in set(base_indices)}

        self.break_merged_patch(patch, no_pad_slice, base_elements_limits, base_elements, base_indices)

    def delete_mmap(self, mmap_key):
        for mmap in self.mmaps[mmap_key]["mmaps"].values():
            mmap._mmap.close()

        for key in self.mmaps[mmap_key]["mmaps"].keys():
            self.mmaps[mmap_key]["mmaps"][key]._mmap.close()

        for path in self.mmaps[mmap_key]["paths"].values():
            if os.path.exists(path):
                os.remove(path)
        del self.mmaps[mmap_key]

    def to_netcdf(self, base_volume=None):
        dtype = self.out_imgs["dtype"]

        for k, path in self.out_imgs["paths"].items():
            shape = self.out_imgs["shapes"][k]
            ranges = self.out_imgs["partition"][k]

            with nc.Dataset(path, "w", format="NETCDF4") as ds:
                ds.createDimension("x", shape[2])
                ds.createDimension("y", shape[3])
                ds.createDimension("z", shape[4])

                x = ds.createVariable("x", np.uint64, ("x"))
                y = ds.createVariable("y", np.uint64, ("y"))
                z = ds.createVariable("z", np.uint64, ("z"))
                segments = ds.createVariable(
                    "segments",
                    dtype,
                    (
                        "x",
                        "y",
                        "z",
                    ),
                    # chunksizes=(base_volume, base_volume, base_volume),
                    # zlib=True,
                )
                segments.units = "Unknown"

                x[:] = np.arange(ranges[0], ranges[1], dtype=np.uint64)
                y[:] = np.arange(ranges[2], ranges[3], dtype=np.uint64)
                z[:] = np.arange(ranges[4], ranges[5], dtype=np.uint64)
                segments[:] = self.out_imgs["mmaps"][k][0, 0]

            os.remove(path[:-2] + "mmap")


class InterpolationManagerMmapNc(InterpolationManagerMmap):
    def prepare_outputs(self, segmented_output, root_path, prefix, partition_spec, chunk_size):
        dtype = np.uint8 if segmented_output else np.float32
        index = len(self.model_shapes) - 1

        if partition_spec is None:
            partition = self.get_scale_partition(index)
        else:
            scale_shape = self.model_shapes[index]
            patch_dim = self.get_patch_dim(scale_shape, partition_spec)
            partition = self.get_partition(scale_shape, patch_dim)

        self.out_imgs = {
            "patch_dim": patch_dim,
            "partition": partition,
            "ncs": {},
        }

        # with open(f'{root_path}/meta.json') as out_file:
        #     meta = json.load(out_file)

        # meta["out_imgs"] = {
        #     "dtype" : "np.uint8" if segmented_output else "np.float32",
        #     "paths" : {},
        #     "shapes" : {},
        #     "partition" : partition,
        # }

        for i, element in enumerate(partition):
            shape = [element[k + 1] - element[k] for k in [0, 2, 4]]
            path = str(Path(f"{root_path}/{prefix}_chunk_{i}.nc").absolute())
            # meta["out_imgs"]["shapes"][i] = shape
            # meta["out_imgs"]["paths"][i] = path
            chunk_size = (
                chunk_size if chunk_size <= min(shape[0], shape[1], shape[2]) else min(shape[0], shape[1], shape[2])
            )

            ds = nc.Dataset(path, "w", format="NETCDF4")
            ds.createDimension("x", shape[0])
            ds.createDimension("y", shape[1])
            ds.createDimension("z", shape[2])
            x = ds.createVariable("x", np.uint64, ("x"))
            y = ds.createVariable("y", np.uint64, ("y"))
            z = ds.createVariable("z", np.uint64, ("z"))
            # Chunk size must be equal or smaller than the smaller spacial dimension of the image
            chunk_size = (
                chunk_size if chunk_size <= min(shape[0], shape[1], shape[2]) else min(shape[0], shape[1], shape[2])
            )
            segments = ds.createVariable(
                "segments",
                dtype,
                (
                    "x",
                    "y",
                    "z",
                ),
                chunksizes=(chunk_size, chunk_size, chunk_size),
                zlib=True,
            )
            segments.units = "Unknown"

            x[:] = np.arange(element[0], element[1], dtype=np.uint64)
            y[:] = np.arange(element[2], element[3], dtype=np.uint64)
            z[:] = np.arange(element[4], element[5], dtype=np.uint64)

            self.out_imgs["ncs"][i] = ds

        # with open(f'{root_path}/meta.json', 'w') as out_file:
        #     json.dump(meta, out_file)

    def patch_to_out_imgs(
        self,
        patch: np.array,
        no_pad_slice: slice,
    ):
        index = len(self.model_shapes) - 1
        base_indices = self.get_base_indices(no_pad_slice, index, self.out_imgs["patch_dim"])
        base_elements_limits = [self.out_imgs["partition"][k] for k in base_indices]
        base_elements = {k: self.out_imgs["ncs"][k] for k in set(base_indices)}

        sources, destinations, merge_specifications = self.merging_gymnastics(no_pad_slice, base_elements_limits)

        for spec_num, (i, j, k) in enumerate(merge_specifications):
            slice_destination = np.s_[
                # :,
                # :,
                destinations[i],
                destinations[j],
                destinations[k],
            ]
            slice_source = np.s_[
                :,
                :,
                sources[i],
                sources[j],
                sources[k],
            ]
            base_elements[base_indices[spec_num]]["segments"][slice_destination] = patch[slice_source][0, 0]

    def to_netcdf(self):
        pass
