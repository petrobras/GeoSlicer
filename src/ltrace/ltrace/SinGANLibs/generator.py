import torch
import torch.nn as nn
import torch.nn.functional as F
import math
from ltrace.SinGANLibs.custom_layer import ConvBlock, imresize
from ltrace.SinGANLibs.interpolation_manager import InterpolationManagerMmapNc
from ltrace.SinGANLibs.functions import get_inference, range_transform
from ltrace.SinGANLibs.patch_inference import (
    get_inference_patch_on_gpu,
    get_inference_using_disk,
    get_inference_interpolation_by_chunks,
    get_inference_early_crop,
    get_equal_size_slices,
)
import numpy as np
import os
import gc
import datetime
from tqdm import tqdm

from ltrace.slicer.cli_utils import progressUpdate

GENERATION_METHODS = {
    "Generation patch on gpu": "generation_patch_on_gpu",
    "Patch Inference": "generation_using_disk",
    "Early crop": "generation_early_cropping",
    "By chunks": "generation_by_chunks",
}


class Generator(nn.Module):
    def __init__(self, num_layer, ker_size, padd_size, img_num_channel, crop_size, img_color_range):
        super(Generator, self).__init__()

        self.num_layer = num_layer
        self.ker_size = ker_size
        self.padd_size = padd_size
        self.img_num_channel = img_num_channel
        self.crop_size = crop_size
        self.zero_padd = self.num_layer * math.floor(self.ker_size / 2)
        self.full_zero_padd = 2 * self.zero_padd
        self.crop_with_padd = self.crop_size + self.full_zero_padd
        self.img_color_range = img_color_range
        self.gens = nn.ModuleList()

    def forward(
        self,
        z,
        amp,
        crop_indexes=[],
        cond_pos=None,
        cond_vals=None,
        in_img=None,
        start_scale=0,
        stop_scale=None,
        use_crop=False,
        use_patch_inference=False,
        patch_size=None,
    ):
        is_cropped = False

        if in_img is None:
            in_img = torch.zeros(
                [
                    z[start_scale].shape[0],
                    z[start_scale].shape[1],
                    z[start_scale].shape[2] - self.full_zero_padd,
                    z[start_scale].shape[3] - self.full_zero_padd,
                    z[start_scale].shape[4] - self.full_zero_padd,
                ],
                device=z[start_scale].device,
            )

        if stop_scale is None:
            stop_scale = len(self.gens) - 1

        for index in range(start_scale, stop_scale + 1):

            # Check if all sides of the cube are larger than the crop size
            is_larger = min(*z[index].shape[2:], self.crop_with_padd) == self.crop_with_padd

            if use_crop and is_larger and len(crop_indexes) == 3:
                img_shape = [s - self.full_zero_padd for s in z[index].shape[2:]]
                last_img_shape = [s - self.full_zero_padd for s in z[-1].shape[2:]]
                scales = [img_shape[i] / last_img_shape[i] for i in range(3)]

                # Get resized indexes
                start = [round(crop_indexes[i] * scales[i]) for i in range(3)]
                end = [round((crop_indexes[i] + self.crop_size) * scales[i]) for i in range(3)]

                # Crop only once at the first scale larger than the crop size,
                # then proceed with the downscaled cropped patch until it reaches the 'crop_size' at the last scale
                if is_cropped:
                    in_img = imresize(in_img, [end[i] - start[i] for i in range(3)])
                else:
                    in_img = imresize(in_img, [img_shape[0], img_shape[1], img_shape[2]])
                    in_img = in_img[:, :, start[0] : end[0], start[1] : end[1], start[2] : end[2]]
                    is_cropped = True

                z[index] = z[index][
                    :,
                    :,
                    start[0] : end[0] + self.full_zero_padd,
                    start[1] : end[1] + self.full_zero_padd,
                    start[2] : end[2] + self.full_zero_padd,
                ]
            else:
                in_img = imresize(
                    in_img,
                    [
                        z[index].shape[2] - self.full_zero_padd,
                        z[index].shape[3] - self.full_zero_padd,
                        z[index].shape[4] - self.full_zero_padd,
                    ],
                )

            self.check_coditional_data(index, in_img, cond_pos, cond_vals)

            z_in = amp[index] * z[index] + F.pad(in_img, [self.zero_padd] * 6, value=0)

            if use_patch_inference and is_larger:

                if patch_size is None:
                    patch_size = self.crop_size

                out_img = get_inference(self.gens[index], z_in, patch_size, self.zero_padd)
            else:
                out_img = self.gens[index](z_in)

            out_img = out_img + in_img

            self.check_coditional_data(index, out_img, cond_pos, cond_vals)

            in_img = out_img

        return out_img

    def forward_generation(
        self,
        z=None,
        amp=None,
        in_img=None,
        start_scale=0,
        stop_scale=None,
        model_shapes=None,
        gpu_device=None,
        segmented_output=False,
        injection=False,
        injection_kwargs=None,
        imagelog_integration=False,
        imagelog_integration_kwargs=None,
    ):

        if in_img is None:
            in_img = torch.zeros(
                [
                    model_shapes[start_scale][0],
                    model_shapes[start_scale][1],
                    model_shapes[start_scale][2],
                    model_shapes[start_scale][3],
                    model_shapes[start_scale][4],
                ],
                device=torch.device("cpu"),
            )

        if stop_scale is None:
            stop_scale = len(self.gens) - 1

        for index in range(start_scale, stop_scale + 1):
            print(f"\nindex: {index}  start: {datetime.datetime.now()}")
            scale_shape = model_shapes[index]

            in_img = imresize(
                in_img,
                [
                    scale_shape[2],
                    scale_shape[3],
                    scale_shape[4],
                ],
            )

            if injection:
                in_img = self.perform_injection(
                    index,
                    scale_shape,
                    in_img,
                    injection_kwargs["cond_img"],
                    injection_kwargs["injection_scale"],
                    injection_kwargs["hard_data"],
                )

            if imagelog_integration:
                self.check_coditional_data_generation(
                    index,
                    in_img,
                    imagelog_integration_kwargs["cond_pos"],
                    imagelog_integration_kwargs["cond_vals"],
                )

            z_in = amp[index] * z.get_scale_noise(index) + F.pad(in_img, [self.zero_padd] * 6, value=0)
            model = self.gens[index].to(gpu_device)
            out_img = model(z_in.to(gpu_device)).to("cpu")
            out_img = out_img + in_img

            if injection:
                out_img = self.perform_injection(
                    index,
                    scale_shape,
                    out_img,
                    injection_kwargs["cond_img"],
                    injection_kwargs["injection_scale"],
                    injection_kwargs["hard_data"],
                )

            if imagelog_integration:
                self.check_coditional_data_generation(
                    index, out_img, imagelog_integration_kwargs["cond_pos"], imagelog_integration_kwargs["cond_vals"]
                )

            in_img = out_img

        if index == len(model_shapes) - 1 and segmented_output:
            out_img = range_transform(
                out_img.numpy().clip(-1, 1),
                in_range=[-1, 1],
                out_range=self.img_color_range,
            )
            out_img = np.round(out_img).astype(np.uint8)

        return out_img

    def generation_patch_on_gpu(
        self,
        z=None,
        amp=None,
        in_img=None,
        start_scale=0,
        stop_scale=None,
        base_volume=None,
        crop_scale=None,
        model_shapes=None,
        gpu_device=None,
        segmented_output=False,
        injection=False,
        injection_kwargs=None,
        imagelog_integration=False,
        imagelog_integration_kwargs=None,
        segments=None,
    ):
        assert start_scale <= crop_scale, "start_scale > crop_scale"

        if stop_scale is None:
            stop_scale = len(self.gens) - 1

        if crop_scale > start_scale:
            in_img = self.forward_generation(
                z,
                amp,
                in_img,
                start_scale=start_scale,
                stop_scale=crop_scale - 1,
                model_shapes=model_shapes,
                gpu_device=gpu_device,
                injection=injection,
                injection_kwargs=injection_kwargs,
                imagelog_integration=imagelog_integration,
                imagelog_integration_kwargs=imagelog_integration_kwargs,
            )
            range_start = crop_scale

        else:
            # case start_scale == crop_scale
            if in_img is None:
                in_img = torch.zeros(
                    [
                        model_shapes[start_scale][0],
                        model_shapes[start_scale][1],
                        model_shapes[start_scale][2],
                        model_shapes[start_scale][3],
                        model_shapes[start_scale][4],
                    ],
                    device=torch.device("cpu"),
                )
            range_start = start_scale

        if injection:
            injection_scale = injection_kwargs["injection_scale"]
            hard_data = injection_kwargs["hard_data"]
            cond_img = injection_kwargs["cond_img"]
        else:
            injection_scale = None
            hard_data = None
            cond_img = None

        if imagelog_integration:
            cond_pos = imagelog_integration_kwargs["cond_pos"]
            cond_vals = imagelog_integration_kwargs["cond_vals"]
            safe_radiuses = imagelog_integration_kwargs["safe_radiuses"]
        else:
            cond_pos = None
            cond_vals = None
            safe_radiuses = None

        for index in range(range_start, stop_scale + 1):
            print(f"\nindex: {index}  start: {datetime.datetime.now()}")
            scale_shape = model_shapes[index]

            in_img = imresize(
                in_img,
                [
                    scale_shape[2],
                    scale_shape[3],
                    scale_shape[4],
                ],
            )
            gc.collect()

            if injection:
                resized_original_cond_img = F.interpolate(
                    cond_img,
                    [
                        scale_shape[2],
                        scale_shape[3],
                        scale_shape[4],
                    ],
                    mode="nearest-exact",
                    align_corners=None,
                )
            else:
                resized_original_cond_img = None

            z.reset_cache()
            is_last_scale = index == len(model_shapes) - 1
            out_img = get_inference_patch_on_gpu(
                self.gens[index],
                index,
                scale_shape,
                amp[index],
                base_volume,
                self.zero_padd,
                gpu_device,
                in_img,
                injection,
                resized_original_cond_img,
                hard_data,
                injection_scale,
                imagelog_integration,
                cond_pos,
                cond_vals,
                safe_radiuses,
                segmented_output,
                is_last_scale,
                z,
                segments,
            )
            in_img = out_img
            del resized_original_cond_img
            gc.collect()

        del in_img
        gc.collect()
        return out_img

    def generation_using_disk(
        self,
        z=None,
        amp=None,
        in_img=None,
        start_scale=0,
        stop_scale=None,
        base_volume=None,
        crop_scale=None,
        disk_scale=None,
        gpu_device=None,
        model_shapes=None,
        segmented_output=False,
        injection=False,
        injection_kwargs=None,
        imagelog_integration=False,
        imagelog_integration_kwargs=None,
        progress_update=False,
        tempPath=None,
        final_partition_spec=None,
        prefix=None,
        root_path=None,
        segments=None,
    ):
        assert start_scale <= crop_scale, "start_scale > crop_scale"
        assert crop_scale <= disk_scale, "crop_scale > disk_scale"

        if stop_scale is None:
            stop_scale = len(self.gens) - 1

        if disk_scale > crop_scale:
            in_img = self.generation_patch_on_gpu(
                z,
                amp,
                in_img,
                start_scale=start_scale,
                stop_scale=disk_scale - 1,
                base_volume=base_volume,
                crop_scale=crop_scale,
                model_shapes=model_shapes,
                gpu_device=gpu_device,
                injection=injection,
                injection_kwargs=injection_kwargs,
                imagelog_integration=imagelog_integration,
                imagelog_integration_kwargs=imagelog_integration_kwargs,
            )
            range_start = disk_scale

        elif (disk_scale == crop_scale) and crop_scale > start_scale:
            in_img = self.forward_generation(
                z,
                amp,
                in_img,
                start_scale=start_scale,
                stop_scale=disk_scale - 1,
                model_shapes=model_shapes,
                gpu_device=gpu_device,
                injection=injection,
                injection_kwargs=injection_kwargs,
                imagelog_integration=imagelog_integration,
                imagelog_integration_kwargs=imagelog_integration_kwargs,
            )
            range_start = disk_scale

        else:
            # case disk_scale == crop_scale == start_scale
            if in_img is None:
                in_img = torch.zeros(
                    [
                        model_shapes[start_scale][0],
                        model_shapes[start_scale][1],
                        model_shapes[start_scale][2],
                        model_shapes[start_scale][3],
                        model_shapes[start_scale][4],
                    ],
                    device=torch.device("cpu"),
                )
            range_start = start_scale

        interpolation_mng = InterpolationManagerMmapNc(model_shapes, partition_spec=[1, 1, 1], temp_dir=tempPath)
        if final_partition_spec is not None:
            interpolation_mng.prepare_outputs(
                segmented_output,
                root_path,
                prefix,
                final_partition_spec,
                base_volume,
            )

        if injection:
            injection_scale = injection_kwargs["injection_scale"]
            hard_data = injection_kwargs["hard_data"]
            cond_img = injection_kwargs["cond_img"]

            interpolation_mng.create_temp_mmap(mmap_key="original_cond_img", img=cond_img)
            del cond_img
            gc.collect()

        else:
            injection_scale = None
            hard_data = None

        if imagelog_integration:
            cond_pos = imagelog_integration_kwargs["cond_pos"]
            cond_vals = imagelog_integration_kwargs["cond_vals"]
            safe_radiuses = imagelog_integration_kwargs["safe_radiuses"]
        else:
            cond_pos = None
            cond_vals = None
            safe_radiuses = None

        for index in range(range_start, stop_scale + 1):
            print(f"\nindex: {index}  start: {datetime.datetime.now()}")
            scale_shape = model_shapes[index]

            in_img = imresize(
                in_img,
                [
                    scale_shape[2],
                    scale_shape[3],
                    scale_shape[4],
                ],
            )

            interpolation_mng.create_temp_mmap(
                mmap_key=f"in_img_index_{index}",
                index=index,
                img=in_img,
            )
            del in_img
            gc.collect()

            if injection:
                interpolation_mng.create_temp_mmap(
                    mmap_key=f"cond_img_index_{index}",
                    index=index,
                )
                original_cond_img = interpolation_mng.get_mmap(f"original_cond_img", 0)
                cond_img = interpolation_mng.get_mmap(f"cond_img_index_{index}", 0)
                resized_original_cond_img = F.interpolate(
                    torch.from_numpy(original_cond_img),
                    size=[
                        model_shapes[index][2],
                        model_shapes[index][3],
                        model_shapes[index][4],
                    ],
                    mode="nearest-exact",
                    align_corners=None,
                )
                cond_img[:] = resized_original_cond_img[:]
                del resized_original_cond_img
                gc.collect()

            z.reset_cache()
            is_last_scale = index == len(model_shapes) - 1
            out_img = get_inference_using_disk(
                self.gens[index],
                index,
                scale_shape,
                amp[index],
                base_volume,
                self.zero_padd,
                gpu_device,
                injection,
                hard_data,
                injection_scale,
                imagelog_integration,
                cond_pos,
                cond_vals,
                safe_radiuses,
                segmented_output,
                is_last_scale,
                z,
                interpolation_mng,
                segments=segments,
            )

            in_img = out_img
            if index < stop_scale:
                del out_img
                gc.collect()

            if injection:
                interpolation_mng.delete_mmap(f"cond_img_index_{index}")

            interpolation_mng.delete_mmap(f"in_img_index_{index}")

            temp_files = [f"{tempPath}/z_{index}.pth"]
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    os.remove(temp_file)

        if injection:
            interpolation_mng.delete_mmap(f"original_cond_img")

        return out_img

    def generation_interpolation_by_chunks(
        self,
        z=None,
        amp=None,
        in_img=None,
        start_scale=0,
        stop_scale=None,
        base_volume=None,
        crop_scale=None,
        disk_scale=None,
        split_scale=None,
        gpu_device=None,
        model_shapes=None,
        segmented_output=False,
        prefix="",
        injection=None,
        injection_kwargs=None,
        imagelog_integration=False,
        imagelog_integration_kwargs=None,
        root_path=None,
        tempPath=None,
        partition_spec=None,
        final_partition_spec=None,
        segments=None,
    ):
        assert start_scale <= crop_scale, "start_scale > crop_scale"
        assert crop_scale <= disk_scale, "crop_scale > disk_scale"
        assert disk_scale <= split_scale, "disk_scale > split_scale"

        interpolation_mng = InterpolationManagerMmapNc(model_shapes, partition_spec, temp_dir=tempPath)

        if stop_scale is None:
            stop_scale = len(self.gens) - 1

        if split_scale > disk_scale:
            in_img = self.generation_using_disk(
                z,
                amp,
                in_img,
                start_scale=start_scale,
                stop_scale=split_scale - 1,
                base_volume=base_volume,
                crop_scale=crop_scale,
                disk_scale=disk_scale,
                model_shapes=model_shapes,
                gpu_device=gpu_device,
                injection=injection,
                injection_kwargs=injection_kwargs,
                imagelog_integration=imagelog_integration,
                imagelog_integration_kwargs=imagelog_integration_kwargs,
                tempPath=tempPath,
                prefix=prefix,
                root_path=root_path,  # ?
            )
            range_start = split_scale

        elif split_scale == disk_scale and disk_scale > crop_scale:
            in_img = self.generation_patch_on_gpu(
                z,
                amp,
                in_img,
                start_scale=start_scale,
                stop_scale=split_scale - 1,
                base_volume=base_volume,
                crop_scale=crop_scale,
                model_shapes=model_shapes,
                gpu_device=gpu_device,
                injection=injection,
                injection_kwargs=injection_kwargs,
                imagelog_integration=imagelog_integration,
                imagelog_integration_kwargs=imagelog_integration_kwargs,
            )
            range_start = split_scale

        elif split_scale == disk_scale == crop_scale and crop_scale > start_scale:
            in_img = self.forward_generation(
                z,
                amp,
                in_img,
                start_scale=start_scale,
                stop_scale=split_scale - 1,
                model_shapes=model_shapes,
                gpu_device=gpu_device,
                injection=injection,
                injection_kwargs=injection_kwargs,
                imagelog_integration=imagelog_integration,
                imagelog_integration_kwargs=imagelog_integration_kwargs,
            )
            range_start = split_scale

        else:
            # case split_scale == disk_scale == crop_scale == start_scale
            range_start = start_scale

            if in_img is None:
                in_img = torch.zeros(
                    [
                        model_shapes[max(start_scale - 1, 0)][0],
                        model_shapes[max(start_scale - 1, 0)][1],
                        model_shapes[max(start_scale - 1, 0)][2],
                        model_shapes[max(start_scale - 1, 0)][3],
                        model_shapes[max(start_scale - 1, 0)][4],
                    ],
                    device=torch.device("cpu"),
                )

        # in_img is of size model.shapes[range_start - 1]
        interpolation_mng.create_temp_mmap(
            mmap_key=f"out_img_index_{max(range_start - 1, 0)}", index=max(range_start - 1, 0), img=in_img
        )

        del in_img
        gc.collect()

        if injection:
            injection_scale = injection_kwargs["injection_scale"]
            hard_data = injection_kwargs["hard_data"]
            cond_img = injection_kwargs["cond_img"]

            interpolation_mng.create_temp_mmap(mmap_key="original_cond_img", img=cond_img)

            del cond_img
            gc.collect()

        else:
            injection_scale = None
            hard_data = None

        if imagelog_integration:
            cond_pos = imagelog_integration_kwargs["cond_pos"]
            cond_vals = imagelog_integration_kwargs["cond_vals"]
            safe_radiuses = imagelog_integration_kwargs["safe_radiuses"]
        else:
            cond_pos = None
            cond_vals = None
            safe_radiuses = None

        interpolation_mng.prepare_outputs(
            segmented_output,
            root_path,
            prefix,
            final_partition_spec,
            base_volume,
        )

        for index in range(range_start, stop_scale + 1):
            print(f"\nindex: {index}  start: {datetime.datetime.now()}")

            scale_shape = model_shapes[index]

            interpolation_mng.create_temp_mmap(
                mmap_key=f"in_img_index_{index}",
                index=index,
            )

            if injection:
                interpolation_mng.create_temp_mmap(
                    mmap_key=f"cond_img_index_{index}",
                    index=index,
                )

            sizes = interpolation_mng.get_scale_partition_sizes(index)
            for i, size in sizes.items():
                out_img = interpolation_mng.get_mmap(f"out_img_index_{max(index - 1, 0)}", i)
                in_img = interpolation_mng.get_mmap(f"in_img_index_{index}", i)
                resized_in_img = imresize(
                    torch.from_numpy(out_img),
                    [
                        size[0],
                        size[1],
                        size[2],
                    ],
                )
                in_img[:] = resized_in_img[:]
                del resized_in_img
                gc.collect()

                if injection:
                    original_cond_img = interpolation_mng.get_mmap(f"original_cond_img", i)
                    cond_img = interpolation_mng.get_mmap(f"cond_img_index_{index}", i)
                    resized_original_cond_img = F.interpolate(
                        torch.from_numpy(original_cond_img),
                        [
                            size[0],
                            size[1],
                            size[2],
                        ],
                        mode="nearest-exact",
                        align_corners=None,
                    )
                    cond_img[:] = resized_original_cond_img[:]
                    del resized_original_cond_img
                    gc.collect()

            interpolation_mng.delete_mmap(f"out_img_index_{max(index - 1, 0)}")

            z.reset_cache()

            is_last_scale = index == len(model_shapes) - 1
            get_inference_interpolation_by_chunks(
                self.gens[index],
                index,
                scale_shape,
                amp[index],
                base_volume,
                self.zero_padd,
                gpu_device,
                is_last_scale,
                segmented_output,
                injection,
                hard_data,
                injection_scale,
                imagelog_integration,
                cond_pos,
                cond_vals,
                safe_radiuses,
                z,
                interpolation_mng,
                segments,
            )

            if injection:
                interpolation_mng.delete_mmap(f"cond_img_index_{index}")

            interpolation_mng.delete_mmap(f"in_img_index_{index}")

        if injection:
            interpolation_mng.delete_mmap(f"original_cond_img")

    def generation_early_cropping(
        self,
        z=None,
        amp=None,
        in_img=None,
        start_scale=0,
        stop_scale=None,
        base_volume=None,
        crop_scale=None,
        disk_scale=None,
        split_scale=None,
        gpu_device=None,
        model_shapes=None,
        segmented_output=False,
        injection=None,
        injection_kwargs=None,
        imagelog_integration=False,
        imagelog_integration_kwargs=None,
        type_2=False,
        tempPath=None,
        final_partition_spec=None,
        prefix=None,
        root_path=None,
        segments=None,
    ):
        assert start_scale <= crop_scale, "start_scale > crop_scale"
        assert crop_scale <= disk_scale, "crop_scale > disk_scale"
        assert disk_scale <= split_scale, "disk_scale > split_scale"

        if stop_scale is None:
            stop_scale = len(self.gens) - 1

        progressUpdate(0.1)

        if split_scale > disk_scale:
            pre_split_in_img = self.generation_using_disk(
                z,
                amp,
                in_img,
                start_scale=start_scale,
                stop_scale=split_scale - 1,
                base_volume=base_volume,
                crop_scale=crop_scale,
                disk_scale=disk_scale,
                model_shapes=model_shapes,
                gpu_device=gpu_device,
                injection=injection,
                injection_kwargs=injection_kwargs,
                imagelog_integration=imagelog_integration,
                imagelog_integration_kwargs=imagelog_integration_kwargs,
                tempPath=tempPath,
                final_partition_spec=None,
                prefix=prefix,
                root_path=root_path,
            )
            range_start = split_scale

        elif split_scale == disk_scale and disk_scale > crop_scale:
            pre_split_in_img = self.generation_patch_on_gpu(
                z,
                amp,
                in_img,
                start_scale=start_scale,
                stop_scale=split_scale - 1,
                base_volume=base_volume,
                crop_scale=crop_scale,
                model_shapes=model_shapes,
                gpu_device=gpu_device,
                injection=injection,
                injection_kwargs=injection_kwargs,
                imagelog_integration=imagelog_integration,
                imagelog_integration_kwargs=imagelog_integration_kwargs,
            )
            range_start = split_scale

        elif split_scale == disk_scale == crop_scale and crop_scale > start_scale:
            pre_split_in_img = self.forward_generation(
                z,
                amp,
                in_img,
                start_scale=start_scale,
                stop_scale=split_scale - 1,
                model_shapes=model_shapes,
                gpu_device=gpu_device,
                injection=injection,
                injection_kwargs=injection_kwargs,
                imagelog_integration=imagelog_integration,
                imagelog_integration_kwargs=imagelog_integration_kwargs,
            )
            range_start = split_scale

        else:
            # case disk_scale == crop_scale == start_scale
            if in_img is None:
                pre_split_in_img = torch.zeros(model_shapes[start_scale])
            else:
                pre_split_in_img = in_img

            range_start = start_scale

        interpolation_mng = InterpolationManagerMmapNc(model_shapes, partition_spec=[1, 1, 1], temp_dir=tempPath)
        interpolation_mng.prepare_outputs(
            segmented_output,
            root_path,
            prefix,
            final_partition_spec,
            base_volume,
        )

        if injection:
            cond_img = injection_kwargs["cond_img"]
            cond_img_shape = cond_img.shape[2:]
            last_img_shape = model_shapes[-1][2:]
            cond_img_scales = {}
            cond_img_scales = [cond_img_shape[i] / last_img_shape[i] for i in range(3)]
        else:
            cond_img_scales = None

        z.force_dynamic_base_size()
        z.reset_cache()

        models = {}
        for index in range(range_start, stop_scale + 1):
            models[index] = self.gens[index].to(gpu_device)

        if not type_2:
            scale_shape = model_shapes[range_start]
            img_shape = scale_shape[2:]
            pre_split_in_img = imresize(pre_split_in_img, [img_shape[0], img_shape[1], img_shape[2]])

        interpolation_mng.create_temp_mmap(
            mmap_key=f"pre_split_in_img",
            img=pre_split_in_img,
        )
        pre_split_in_img = interpolation_mng.get_mmap(f"pre_split_in_img", 0)

        final_shape = model_shapes[-1]
        full_z_size = torch.Size(
            [
                1,
                final_shape[1],
                final_shape[2] + 2 * self.zero_padd,
                final_shape[3] + 2 * self.zero_padd,
                final_shape[4] + 2 * self.zero_padd,
            ]
        )
        slices, slices_no_padd = get_equal_size_slices(
            full_z_size,
            patch_dim=base_volume,
            pad=self.zero_padd,
        )

        all_scales = {}
        last_img_shape = model_shapes[-1][2:]
        for index in range(len(model_shapes)):
            scale_shape = model_shapes[index]
            img_shape = scale_shape[2:]
            all_scales[index] = [img_shape[i] / last_img_shape[i] for i in range(3)]

        if imagelog_integration:
            cond_pos = imagelog_integration_kwargs["cond_pos"]
            cond_vals = imagelog_integration_kwargs["cond_vals"]
            safe_radiuses = imagelog_integration_kwargs["safe_radiuses"]
            out_h_start = None
            filtered_cond_pos = {}
            filtered_cond_vals = {}
        else:
            filtered_cond_pos = None
            filtered_cond_vals = None
            safe_radiuses = None

        for i in tqdm(range(len(slices))):
            slice_ = slices_no_padd[i]

            if imagelog_integration:
                out_i_start = slice_[2:][0].start
                out_i_stop = slice_[2:][0].stop

                if out_i_start != out_h_start:
                    for index in range(range_start, len(model_shapes)):
                        scales = all_scales[index]
                        start = round(out_i_start * scales[0])
                        end = round(out_i_stop * scales[0])
                        out_h_start = start
                        filter = (start <= cond_pos[index][:, 0]) & (cond_pos[index][:, 0] < end)
                        filtered_cond_pos[index] = cond_pos[index][filter]
                        filtered_cond_vals[index] = cond_vals[index][filter]

            out_img = get_inference_early_crop(
                range_start,
                model_shapes,
                type_2,
                pre_split_in_img,
                injection,
                injection_kwargs,
                cond_img_scales,
                imagelog_integration,
                filtered_cond_pos,
                filtered_cond_vals,
                safe_radiuses,
                segmented_output,
                self.zero_padd,
                models,
                gpu_device,
                amp,
                z,
                all_scales,
                slice_,
                segments,
            )

            interpolation_mng.patch_to_out_imgs(
                out_img,
                slices_no_padd[i],
            )

        interpolation_mng.delete_mmap(f"pre_split_in_img")

    def check_coditional_data(self, index, img, cond_pos, cond_vals):
        if cond_pos is not None and cond_vals is not None:
            pos = cond_pos[index]
            img[..., pos[:, 0], pos[:, 1], pos[:, 2]] = cond_vals

    def check_coditional_data_generation(self, index, img, cond_pos, cond_vals, start_imagelog_integration=2):
        if index >= start_imagelog_integration:
            pos = cond_pos[index]
            img[..., pos[:, 0], pos[:, 1], pos[:, 2]] = cond_vals[index]

    def create_scale(self, num_feature, min_num_feature):
        head = ConvBlock(self.img_num_channel, num_feature, self.ker_size, self.padd_size, 1)
        body = nn.Sequential()

        for i in range(self.num_layer - 2):
            n = int(num_feature / pow(2, (i + 1)))
            block = ConvBlock(max(2 * n, min_num_feature), max(n, min_num_feature), self.ker_size, self.padd_size, 1)
            body.add_module("block%d" % (i + 1), block)

        tail = nn.Sequential(
            nn.Conv3d(
                max(n, min_num_feature),
                self.img_num_channel,
                kernel_size=self.ker_size,
                stride=1,
                padding=self.padd_size,
            ),
            nn.Tanh(),
        )

        self.gens.append(nn.Sequential(head, body, tail))

    def perform_injection(
        self,
        index,
        scale_shape,
        out_img,
        cond_img,
        injection_scale,
        hard_data,
    ):
        if cond_img is not None:
            cond_img = nn.functional.interpolate(
                cond_img,
                size=[
                    scale_shape[2],
                    scale_shape[3],
                    scale_shape[4],
                ],
                mode="nearest-exact",
                align_corners=None,
            )
            if index in injection_scale:
                # Remember that the mask is created using the value of the hard_data
                mask = torch.zeros_like(cond_img)
                for i in hard_data:
                    mask = mask + torch.isclose(cond_img, i, rtol=0.2)
                out_img[mask != 0] = cond_img[mask != 0]
        return out_img

    def generation_router(
        self,
        method="generation_early_cropping",
        z=None,
        amp=None,
        in_img=None,
        start_scale=0,
        stop_scale=None,
        base_volume=None,
        crop_scale=None,
        disk_scale=None,
        split_scale=None,
        gpu_device=None,
        model_shapes=None,
        segmented_output=False,
        injection=None,
        injection_kwargs=None,
        imagelog_integration=False,
        imagelog_integration_kwargs=None,
        type_2=False,
        chunks=[3, 3, 3],
        final_partition_spec=None,
        tempPath="",
        prefix="",
        outputPath="",
        segments=None,
    ):
        if method == GENERATION_METHODS["Patch Inference"]:
            print("Using generation using disk")
            generatedImage = self.generation_using_disk(
                z=z,
                amp=amp,
                in_img=in_img,
                start_scale=start_scale,
                stop_scale=stop_scale,
                base_volume=base_volume,
                crop_scale=crop_scale,
                disk_scale=disk_scale,
                gpu_device=gpu_device,
                model_shapes=model_shapes,
                segmented_output=segmented_output,
                injection=injection,
                injection_kwargs=injection_kwargs,
                imagelog_integration=imagelog_integration,
                imagelog_integration_kwargs=imagelog_integration_kwargs,
                progress_update=True,
                tempPath=tempPath,
                final_partition_spec=final_partition_spec,
                prefix=prefix,
                root_path=outputPath,
                segments=segments,
            )
        elif method == GENERATION_METHODS["Early crop"]:
            print("Using early cropping")
            generatedImage = self.generation_early_cropping(
                z=z,
                amp=amp,
                in_img=in_img,
                start_scale=start_scale,
                stop_scale=stop_scale,
                base_volume=base_volume,
                crop_scale=crop_scale,
                disk_scale=disk_scale,
                split_scale=split_scale,
                gpu_device=gpu_device,
                model_shapes=model_shapes,
                segmented_output=segmented_output,
                injection=injection,
                injection_kwargs=injection_kwargs,
                imagelog_integration=imagelog_integration,
                imagelog_integration_kwargs=imagelog_integration_kwargs,
                type_2=type_2,
                tempPath=tempPath,
                final_partition_spec=final_partition_spec,
                prefix=prefix,
                root_path=outputPath,
                segments=segments,
            )
        elif method == GENERATION_METHODS["By chunks"]:
            self.generation_interpolation_by_chunks(
                z=z,
                amp=amp,
                in_img=in_img,
                start_scale=start_scale,
                stop_scale=stop_scale,
                base_volume=base_volume,
                crop_scale=crop_scale,
                disk_scale=disk_scale,
                split_scale=split_scale,
                gpu_device=gpu_device,
                model_shapes=model_shapes,
                segmented_output=segmented_output,
                prefix=prefix,
                injection=injection,
                injection_kwargs=injection_kwargs,
                imagelog_integration=imagelog_integration,
                imagelog_integration_kwargs=imagelog_integration_kwargs,
                root_path=outputPath,
                tempPath=tempPath,
                partition_spec=chunks,
                final_partition_spec=final_partition_spec,
                segments=segments,
            )
            generatedImage = None

        elif method == GENERATION_METHODS["Generation patch on gpu"]:
            print("Using generation_patch_on_gpu")
            generatedImage = self.generation_patch_on_gpu(
                z=z,
                amp=amp,
                in_img=in_img,
                start_scale=start_scale,
                stop_scale=stop_scale,
                base_volume=base_volume,
                crop_scale=crop_scale,
                gpu_device=gpu_device,
                model_shapes=model_shapes,
                segmented_output=segmented_output,
                injection=injection,
                injection_kwargs=injection_kwargs,
                imagelog_integration=imagelog_integration,
                imagelog_integration_kwargs=imagelog_integration_kwargs,
                segments=segments,
            )
        return generatedImage
