from typing import Dict
import numpy as np
from abc import ABC, abstractmethod
from math import ceil


class PartitionManager(ABC):
    def __init__(self, model_shapes, img_num_channel):
        self.model_shapes = model_shapes
        self.img_num_channel = img_num_channel

    @abstractmethod
    def get_patch_dim(self):
        pass

    @abstractmethod
    def get_scale_patch_dim(self):
        pass

    @abstractmethod
    def get_scale_partition(self):
        pass

    def set_all_scale_partition(self) -> Dict:
        partitions = {}
        for index, scale_shape in enumerate(self.model_shapes):
            partitions[index] = self.get_partition(scale_shape, self.get_scale_patch_dim(index))
        return partitions

    def get_partition(self, shape, patch_dim):
        if len(shape) == 3:
            shape = [1, 1, *shape]
        if len(shape) != 5:
            raise Exception("Expected shape format DHW or BCDHW")
        if isinstance(patch_dim, int):
            patch_dim = [patch_dim] * 3

        if shape[2] >= patch_dim[0]:
            start_x = []
            end_x = []
            for i in range(shape[2] // patch_dim[0]):
                start_x.append(i * patch_dim[0])
                end_x.append((i + 1) * patch_dim[0])
            if shape[2] % patch_dim[0] != 0:
                start_x.append((i + 1) * patch_dim[0])
                end_x.append(shape[2])
        else:
            start_x = [0]
            end_x = [shape[2]]

        if shape[3] >= patch_dim[1]:
            start_y = []
            end_y = []
            for i in range(shape[3] // patch_dim[1]):
                start_y.append(i * patch_dim[1])
                end_y.append((i + 1) * patch_dim[1])
            if shape[3] % patch_dim[1] != 0:
                start_y.append((i + 1) * patch_dim[1])
                end_y.append(shape[3])
        else:
            start_y = [0]
            end_y = [shape[3]]

        if shape[4] >= patch_dim[2]:
            start_z = []
            end_z = []
            for i in range(shape[4] // patch_dim[2]):
                start_z.append(i * patch_dim[2])
                end_z.append((i + 1) * patch_dim[2])
            if shape[4] % patch_dim[2] != 0:
                start_z.append((i + 1) * patch_dim[2])
                end_z.append(shape[4])
        else:
            start_z = [0]
            end_z = [shape[4]]

        base_vertices = []
        for i in range(len(start_x)):
            for j in range(len(start_y)):
                for k in range(len(start_z)):
                    base_vertices.append([start_x[i], end_x[i], start_y[j], end_y[j], start_z[k], end_z[k]])
        return base_vertices

    def get_partition_base_index(self, vertex, scale_shape, partition_base_size):
        if isinstance(partition_base_size, int):
            partition_base_size = [partition_base_size] * 3
        num_partition_j = ceil(scale_shape[3] / partition_base_size[1])
        num_partition_k = ceil(scale_shape[4] / partition_base_size[2])
        partition_index = (
            (vertex[0] // partition_base_size[0]) * num_partition_j * num_partition_k
            + (vertex[1] // partition_base_size[1]) * num_partition_k
            + (vertex[2] // partition_base_size[2])
        )
        return partition_index

    def get_base_indices(self, no_pad_slice, index, partition_base_size=None):
        scale_shape = self.model_shapes[index]
        partition_base_size = partition_base_size if partition_base_size else self.get_scale_patch_dim(index)

        h_i = no_pad_slice[2].stop - no_pad_slice[2].start - 1
        h_j = no_pad_slice[3].stop - no_pad_slice[3].start - 1
        h_k = no_pad_slice[4].stop - no_pad_slice[4].start - 1

        indices = []
        for l, m, n in [(0, 0, 0), (0, 0, 1), (0, 1, 0), (1, 0, 0), (0, 1, 1), (1, 0, 1), (1, 1, 0), (1, 1, 1)]:
            vertex = [
                no_pad_slice[2].start + h_i * l,
                no_pad_slice[3].start + h_j * m,
                no_pad_slice[4].start + h_k * n,
            ]
            partition_index = self.get_partition_base_index(vertex, scale_shape, partition_base_size)
            indices.append(partition_index)
        return indices

    def merging_gymnastics(self, no_pad_slice, base_elements_limits):
        starts = [
            no_pad_slice[2].start,
            no_pad_slice[3].start,
            no_pad_slice[4].start,
        ]

        ends = [
            no_pad_slice[2].stop,
            no_pad_slice[3].stop,
            no_pad_slice[4].stop,
        ]

        l_limits = [base_elements_limits[0][k] for k in [0, 2, 4]]
        u_limits = [base_elements_limits[0][k] for k in [1, 3, 5]]

        intermediary_dest_idx = [
            u_limits[0] - starts[0] if ends[0] > u_limits[0] else ends[0] - starts[0],
            u_limits[1] - starts[1] if ends[1] > u_limits[1] else ends[1] - starts[1],
            u_limits[2] - starts[2] if ends[2] > u_limits[2] else ends[2] - starts[2],
        ]

        final_dest_idx = [
            intermediary_dest_idx[0] + ends[0] - u_limits[0] if ends[0] > u_limits[0] else intermediary_dest_idx[0],
            intermediary_dest_idx[1] + ends[1] - u_limits[1] if ends[1] > u_limits[1] else intermediary_dest_idx[1],
            intermediary_dest_idx[2] + ends[2] - u_limits[2] if ends[2] > u_limits[2] else intermediary_dest_idx[2],
        ]

        intermediary_source_idx = [
            u_limits[0] - l_limits[0] if ends[0] > u_limits[0] else ends[0] - l_limits[0],
            u_limits[1] - l_limits[1] if ends[1] > u_limits[1] else ends[1] - l_limits[1],
            u_limits[2] - l_limits[2] if ends[2] > u_limits[2] else ends[2] - l_limits[2],
        ]

        final_source_idx = [
            ends[0] - u_limits[0] if ends[0] > u_limits[0] else 0,
            ends[1] - u_limits[1] if ends[1] > u_limits[1] else 0,
            ends[2] - u_limits[2] if ends[2] > u_limits[2] else 0,
        ]

        destinations = [
            slice(0, intermediary_dest_idx[0]),
            slice(0, intermediary_dest_idx[1]),
            slice(0, intermediary_dest_idx[2]),
            slice(intermediary_dest_idx[0], final_dest_idx[0]),
            slice(intermediary_dest_idx[1], final_dest_idx[1]),
            slice(intermediary_dest_idx[2], final_dest_idx[2]),
        ]

        sources = [
            slice(starts[0] - l_limits[0], intermediary_source_idx[0]),
            slice(starts[1] - l_limits[1], intermediary_source_idx[1]),
            slice(starts[2] - l_limits[2], intermediary_source_idx[2]),
            slice(0, final_source_idx[0]),
            slice(0, final_source_idx[1]),
            slice(0, final_source_idx[2]),
        ]

        merge_specifications = [(0, 1, 2), (0, 1, 5), (0, 4, 2), (3, 1, 2), (0, 4, 5), (3, 1, 5), (3, 4, 2), (3, 4, 5)]
        return destinations, sources, merge_specifications

    def get_merged_patch(self, no_pad_slice, base_elements_limits, base_elements, base_indices):
        destinations, sources, merge_specifications = self.merging_gymnastics(no_pad_slice, base_elements_limits)

        merged_patch = np.zeros(
            shape=[
                1,
                self.img_num_channel,
                no_pad_slice[2].stop - no_pad_slice[2].start,
                no_pad_slice[3].stop - no_pad_slice[3].start,
                no_pad_slice[4].stop - no_pad_slice[4].start,
            ],
            dtype=np.float32,
        )

        for spec_num, (i, j, k) in enumerate(merge_specifications):
            slice_destination = np.s_[
                :,
                :,
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
            merged_patch[slice_destination] = base_elements[base_indices[spec_num]][slice_source]
        return merged_patch

    def break_merged_patch(self, patch, no_pad_slice, base_elements_limits, base_elements, base_indices):
        sources, destinations, merge_specifications = self.merging_gymnastics(no_pad_slice, base_elements_limits)

        for spec_num, (i, j, k) in enumerate(merge_specifications):
            slice_destination = np.s_[
                :,
                :,
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
            base_elements[base_indices[spec_num]][slice_destination] = patch[slice_source]

    def get_scale_partition_sizes(self, index: int) -> Dict:
        partition = self.get_scale_partition(index)
        sizes = {}
        for i, element in enumerate(partition):
            sizes[i] = [element[k + 1] - element[k] for k in [0, 2, 4]]
        return sizes

    def get_scale_partition_slices(self, index: int) -> Dict:
        partition = self.get_scale_partition(index)
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
