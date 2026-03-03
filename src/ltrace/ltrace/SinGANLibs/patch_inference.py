import numpy as np
import torch
import torch.nn.functional as F
from ltrace.SinGANLibs.functions import range_transform, segment
from ltrace.SinGANLibs.interpolation_manager import InterpolationManagerMmapNc
from ltrace.SinGANLibs.custom_layer import imresize
import numpy as np
import torch


def get_equal_size_slices(shape, patch_dim, pad):
    start_z = []
    for i in range((shape[-3] - 2 * pad) // patch_dim):
        start_z.append(i * patch_dim)
    start_z.append(max(0, shape[-3] - 2 * pad - patch_dim))

    start_y = []
    for i in range((shape[-2] - 2 * pad) // patch_dim):
        start_y.append(i * patch_dim)
    start_y.append(max(0, shape[-2] - 2 * pad - patch_dim))

    start_x = []
    for i in range((shape[-1] - 2 * pad) // patch_dim):
        start_x.append(i * patch_dim)
    start_x.append(max(0, shape[-1] - 2 * pad - patch_dim))

    coords = []
    coords_no_pad = []
    for k in range(len(start_z)):
        end_z = min(start_z[k] + patch_dim + 2 * pad, shape[-3])
        end_z_no_pad = min(start_z[k] + patch_dim, shape[-3])

        for i in range(len(start_y)):
            end_y = min(start_y[i] + patch_dim + 2 * pad, shape[-2])
            end_y_no_pad = min(start_y[i] + patch_dim, shape[-2])

            for j in range(len(start_x)):
                end_x = min(start_x[j] + patch_dim + (2 * pad), shape[-1])
                end_x_no_pad = min(start_x[j] + patch_dim, shape[-1])

                coords.append(np.s_[:, :, start_z[k] : end_z, start_y[i] : end_y, start_x[j] : end_x])
                coords_no_pad.append(
                    np.s_[:, :, start_z[k] : end_z_no_pad, start_y[i] : end_y_no_pad, start_x[j] : end_x_no_pad]
                )
    return coords, coords_no_pad


def return_no_padded_patches3(padded_patch, pad, scale_shape):
    no_pad_patch = np.s_[
        :,
        :,
        max(0, padded_patch[2].start - pad) : min(padded_patch[2].stop - pad, scale_shape[2]),
        max(0, padded_patch[3].start - pad) : min(padded_patch[3].stop - pad, scale_shape[3]),
        max(0, padded_patch[4].start - pad) : min(padded_patch[4].stop - pad, scale_shape[4]),
    ]

    max_d = scale_shape[2]
    max_h = scale_shape[3]
    max_w = scale_shape[4]

    padding_spec = np.array(
        [
            max(0, pad - padded_patch[4].start),
            max(0, padded_patch[4].stop - pad - max_w),
            max(0, pad - padded_patch[3].start),
            max(0, padded_patch[3].stop - pad - max_h),
            max(0, pad - padded_patch[2].start),
            max(0, padded_patch[2].stop - pad - max_d),
        ]
    )
    return no_pad_patch, tuple(padding_spec)


def perform_patch_injection(out_img, cond_img, injection_scale, index, hard_data):
    if index in injection_scale:
        # Remember that the mask is created using the value of the hard_data
        """Diego
        mask = torch.isclose(cond_img, hard_data, rtol=0.2)
        out_img[mask == 0] = cond_img[mask == 0]"""
        mask = torch.zeros_like(cond_img)
        for i in hard_data:
            mask = mask + torch.isclose(cond_img, i, rtol=0.2)
        out_img[mask != 0] = cond_img[mask != 0]
    return out_img


def check_is_internal(j_start, j_stop, k_start, k_stop, center, internal_radius):
    vertices = np.array(
        [
            [j_start, k_start],
            [j_start, k_stop - 1],
            [j_stop - 1, k_start],
            [j_stop - 1, k_stop - 1],
        ]
    )

    return np.all((vertices[:, 0] - center) ** 2 + (vertices[:, 1] - center) ** 2 <= internal_radius**2)


def check_is_external(j_start, j_stop, k_start, k_stop, center, external_radius):
    vertices = np.array(
        [
            [j_start, k_start],
            [j_start, k_stop - 1],
            [j_stop - 1, k_start],
            [j_stop - 1, k_stop - 1],
        ]
    )

    return np.all((vertices[:, 0] - center) ** 2 + (vertices[:, 1] - center) ** 2 >= external_radius**2)


def get_patch_cond_pos_vals(no_padded_patch, index, cond_pos, cond_vals, safe_radiuses, start_imagelog_integration=1):
    if index < start_imagelog_integration:
        return None, None, None, None

    i_start = no_padded_patch[2].start
    i_stop = no_padded_patch[2].stop
    j_start = no_padded_patch[3].start
    j_stop = no_padded_patch[3].stop
    k_start = no_padded_patch[4].start
    k_stop = no_padded_patch[4].stop
    center = safe_radiuses[index]["center"]

    is_internal = check_is_internal(j_start, j_stop, k_start, k_stop, center, safe_radiuses[index]["internal"])
    if is_internal:
        return None, None, None, None

    if (j_stop - j_start < center // 4) and (k_stop - k_start < center // 4):
        is_external = check_is_external(j_start, j_stop, k_start, k_stop, center, safe_radiuses[index]["external"])
        if is_external:
            return None, None, None, None

    indices = np.where(
        (j_start <= cond_pos[:, 1])
        & (cond_pos[:, 1] < j_stop)
        & (k_start <= cond_pos[:, 2])
        & (cond_pos[:, 2] < k_stop)
    )

    if indices[0].size > 0:
        patch_vals = cond_vals[indices]
        i_s = cond_pos[indices][:, 0] - i_start
        j_s = cond_pos[indices][:, 1] - j_start
        k_s = cond_pos[indices][:, 2] - k_start
        return i_s, j_s, k_s, patch_vals

    return None, None, None, None


def get_inference_patch_on_gpu(
    model,
    index,
    scale_shape,
    amp,
    base_volume,
    pad,
    gpu_device,
    full_in_img,
    injection,
    full_cond_img,
    hard_data,
    injection_scale,
    imagelog_integration,
    cond_pos,
    cond_vals,
    safe_radiuses,
    segmented_output,
    last_scale,
    z,
    segments,
):
    dtype = torch.uint8 if (last_scale and segmented_output) else torch.float32
    results_patches = torch.empty(scale_shape, dtype=dtype)
    full_z_size = torch.Size(
        [
            scale_shape[0],
            scale_shape[1],
            scale_shape[2] + 2 * pad,
            scale_shape[3] + 2 * pad,
            scale_shape[4] + 2 * pad,
        ]
    )

    patches_coords, out_coords = get_equal_size_slices(full_z_size, patch_dim=base_volume, pad=pad)

    total_patches = len(patches_coords)
    model = model.to(gpu_device)

    patch_h_start = None
    patch_h_stop = None
    out_h_start = None
    out_h_stop = None

    for i in range(total_patches):
        no_padded_patch, padding_spec = return_no_padded_patches3(
            patches_coords[i],
            pad,
            scale_shape,
        )
        no_padded_z_patch = z.get_noise_patch(no_padded_patch, index)
        no_padded_in_img_patch = full_in_img[no_padded_patch]

        if injection:
            no_padded_cond_img = full_cond_img[no_padded_patch]
            no_padded_in_img_patch = perform_patch_injection(
                no_padded_in_img_patch, no_padded_cond_img, injection_scale, index, hard_data
            )

        if imagelog_integration:
            no_padded_patch_i_start = no_padded_patch[2].start
            no_padded_patch_i_stop = no_padded_patch[2].stop

            if (no_padded_patch_i_start != patch_h_start) or (no_padded_patch_i_stop != patch_h_stop):
                patch_h_start = no_padded_patch_i_start
                patch_h_stop = no_padded_patch_i_stop
                filter = (patch_h_start <= cond_pos[index][:, 0]) & (cond_pos[index][:, 0] < patch_h_stop)
                filtered_patch_cond_pos = cond_pos[index][filter]
                filtered_patch_cond_vals = cond_vals[index][filter]

            i_s, j_s, k_s, patch_vals = get_patch_cond_pos_vals(
                no_padded_patch,
                index,
                filtered_patch_cond_pos,
                filtered_patch_cond_vals,
                safe_radiuses,
            )

            if patch_vals is not None:
                no_padded_in_img_patch[:, :, i_s, j_s, k_s] = patch_vals

        img_patch = F.pad(
            no_padded_z_patch * amp + no_padded_in_img_patch,
            padding_spec,
        )

        with torch.no_grad():
            inf_patch = model(img_patch.to(gpu_device))

        out_img = inf_patch.cpu() + full_in_img[out_coords[i]]

        if injection:
            out_img = perform_patch_injection(out_img, full_cond_img[out_coords[i]], injection_scale, index, hard_data)

        if imagelog_integration:
            out_coords_i_start = out_coords[i][2].start
            out_coords_i_stop = out_coords[i][2].stop

            if (out_coords_i_start != out_h_start) or (out_coords_i_stop != out_h_stop):
                out_h_start = out_coords_i_start
                out_h_stop = out_coords_i_stop
                filter = (out_h_start <= cond_pos[index][:, 0]) & (cond_pos[index][:, 0] < out_h_stop)
                filtered_out_cond_pos = cond_pos[index][filter]
                filtered_out_cond_vals = cond_vals[index][filter]

            i_s, j_s, k_s, patch_vals = get_patch_cond_pos_vals(
                out_coords[i], index, filtered_out_cond_pos, filtered_out_cond_vals, safe_radiuses
            )

            if patch_vals is not None:
                out_img[:, :, i_s, j_s, k_s] = patch_vals

        if last_scale and segmented_output:
            out_img = range_transform(out_img.cpu().numpy().clip(-1, 1), in_range=[-1, 1], out_range=[1, 3])
            # out_img = out_img.round().astype(np.uint8)
            out_img = segment(out_img, segments)
            out_img = torch.from_numpy(out_img)

        results_patches[out_coords[i]] = out_img
        del img_patch, inf_patch
    return results_patches


def get_inference_using_disk(
    model,
    index,
    scale_shape,
    amp,
    base_volume,
    pad,
    gpu_device,
    injection,
    hard_data,
    injection_scale,
    imagelog_integration,
    cond_pos,
    cond_vals,
    safe_radiuses,
    segmented_output,
    last_scale,
    z,
    interpolation_mng: InterpolationManagerMmapNc,
    segments,
):
    results_patches = None if last_scale else torch.empty(scale_shape)

    full_z_size = torch.Size(
        [
            scale_shape[0],
            scale_shape[1],
            scale_shape[2] + 2 * pad,
            scale_shape[3] + 2 * pad,
            scale_shape[4] + 2 * pad,
        ]
    )

    full_in_img = interpolation_mng.get_mmap(f"in_img_index_{index}", 0)

    if injection:
        full_cond_img = interpolation_mng.get_mmap(f"cond_img_index_{index}", 0)

    patches_coords, out_coords = get_equal_size_slices(full_z_size, patch_dim=base_volume, pad=pad)

    total_patches = len(patches_coords)
    model = model.to(gpu_device)

    patch_h_start = None
    patch_h_stop = None
    out_h_start = None
    out_h_stop = None

    for i in range(total_patches):
        no_padded_patch, padding_spec = return_no_padded_patches3(
            patches_coords[i],
            pad,
            scale_shape,
        )

        no_padded_z_patch = z.get_noise_patch(no_padded_patch, index)

        no_padded_in_img_patch = torch.from_numpy(full_in_img[no_padded_patch])

        if injection:
            no_padded_cond_img = torch.from_numpy(full_cond_img[no_padded_patch])
            no_padded_in_img_patch = perform_patch_injection(
                no_padded_in_img_patch, no_padded_cond_img, injection_scale, index, hard_data
            )

        if imagelog_integration:
            no_padded_patch_i_start = no_padded_patch[2].start
            no_padded_patch_i_stop = no_padded_patch[2].stop

            if (no_padded_patch_i_start != patch_h_start) or (no_padded_patch_i_stop != patch_h_stop):
                patch_h_start = no_padded_patch_i_start
                patch_h_stop = no_padded_patch_i_stop
                filter = (patch_h_start <= cond_pos[index][:, 0]) & (cond_pos[index][:, 0] < patch_h_stop)
                filtered_patch_cond_pos = cond_pos[index][filter]
                filtered_patch_cond_vals = cond_vals[index][filter]

            i_s, j_s, k_s, patch_vals = get_patch_cond_pos_vals(
                no_padded_patch,
                index,
                filtered_patch_cond_pos,
                filtered_patch_cond_vals,
                safe_radiuses,
            )

            if patch_vals is not None:
                no_padded_in_img_patch[:, :, i_s, j_s, k_s] = patch_vals

        img_patch = F.pad(
            no_padded_z_patch * amp + no_padded_in_img_patch,
            padding_spec,
        )

        with torch.no_grad():
            inf_patch = model(img_patch.to(gpu_device))

        out_img = inf_patch.cpu() + torch.from_numpy(full_in_img[out_coords[i]])

        if injection:
            out_img = perform_patch_injection(
                out_img, torch.from_numpy(full_cond_img[out_coords[i]]), injection_scale, index, hard_data
            )

        if imagelog_integration:
            out_coords_i_start = out_coords[i][2].start
            out_coords_i_stop = out_coords[i][2].stop

            if (out_coords_i_start != out_h_start) or (out_coords_i_stop != out_h_stop):
                out_h_start = out_coords_i_start
                out_h_stop = out_coords_i_stop
                filter = (out_h_start <= cond_pos[index][:, 0]) & (cond_pos[index][:, 0] < out_h_stop)
                filtered_out_cond_pos = cond_pos[index][filter]
                filtered_out_cond_vals = cond_vals[index][filter]

            i_s, j_s, k_s, patch_vals = get_patch_cond_pos_vals(
                out_coords[i], index, filtered_out_cond_pos, filtered_out_cond_vals, safe_radiuses
            )

            if patch_vals is not None:
                out_img[:, :, i_s, j_s, k_s] = patch_vals

        if last_scale:
            if segmented_output:
                out_img = range_transform(out_img.cpu().numpy().clip(-1, 1), in_range=[-1, 1], out_range=[1, 3])
                # out_img = out_img.round().astype(np.uint8)
                out_img = segment(out_img, segments)

            interpolation_mng.patch_to_out_imgs(
                out_img,
                out_coords[i],
            )
        else:
            results_patches[out_coords[i]] = out_img
        del img_patch, inf_patch

    return results_patches


def get_inference_interpolation_by_chunks(
    model,
    index,
    scale_shape,
    amp,
    base_volume,
    pad,
    gpu_device,
    last_scale,
    segmented_output,
    injection,
    hard_data,
    injection_scale,
    imagelog_integration,
    cond_pos,
    cond_vals,
    safe_radiuses,
    z,
    interpolation_mng: InterpolationManagerMmapNc,
    segments,
):

    if not last_scale:
        interpolation_mng.create_temp_mmap(
            f"out_img_index_{index}",
            index,
        )

    full_z_size = torch.Size(
        [
            scale_shape[0],
            scale_shape[1],
            scale_shape[2] + 2 * pad,
            scale_shape[3] + 2 * pad,
            scale_shape[4] + 2 * pad,
        ]
    )

    patches_coords, out_coords = get_equal_size_slices(full_z_size, patch_dim=base_volume, pad=pad)

    total_patches = len(patches_coords)
    model = model.to(gpu_device)

    patch_h_start = None
    patch_h_stop = None
    out_h_start = None
    out_h_stop = None

    for i in range(total_patches):
        no_padded_patch, padding_spec = return_no_padded_patches3(
            patches_coords[i],
            pad,
            scale_shape,
        )

        no_padded_z_patch = z.get_noise_patch(no_padded_patch, index)

        no_padded_in_img_patch = interpolation_mng.mmap_partition_to_patch(
            f"in_img_index_{index}", no_padded_patch, index
        )

        if injection:
            no_padded_cond_img = interpolation_mng.mmap_partition_to_patch(
                f"cond_img_index_{index}", no_padded_patch, index
            )

            no_padded_in_img_patch = perform_patch_injection(
                no_padded_in_img_patch, no_padded_cond_img, injection_scale, index, hard_data
            )

        if imagelog_integration:
            no_padded_patch_i_start = no_padded_patch[2].start
            no_padded_patch_i_stop = no_padded_patch[2].stop

            if (no_padded_patch_i_start != patch_h_start) or (no_padded_patch_i_stop != patch_h_stop):
                patch_h_start = no_padded_patch_i_start
                patch_h_stop = no_padded_patch_i_stop
                filter = (patch_h_start <= cond_pos[index][:, 0]) & (cond_pos[index][:, 0] < patch_h_stop)
                filtered_patch_cond_pos = cond_pos[index][filter]
                filtered_patch_cond_vals = cond_vals[index][filter]

            i_s, j_s, k_s, patch_vals = get_patch_cond_pos_vals(
                no_padded_patch, index, filtered_patch_cond_pos, filtered_patch_cond_vals, safe_radiuses
            )

            if patch_vals is not None:
                no_padded_in_img_patch[:, :, i_s, j_s, k_s] = patch_vals

        img_patch = F.pad(
            no_padded_z_patch * amp + no_padded_in_img_patch,
            padding_spec,
        )

        with torch.no_grad():
            inf_patch = model(img_patch.float().to(gpu_device))

        no_padded_in_img_patch = interpolation_mng.mmap_partition_to_patch(
            f"in_img_index_{index}", out_coords[i], index
        )

        final_patch = inf_patch.cpu() + no_padded_in_img_patch

        if injection:
            no_padded_cond_img = interpolation_mng.mmap_partition_to_patch(
                f"cond_img_index_{index}", out_coords[i], index
            )

            final_patch = perform_patch_injection(final_patch, no_padded_cond_img, injection_scale, index, hard_data)

        if imagelog_integration:
            out_coords_i_start = out_coords[i][2].start
            out_coords_i_stop = out_coords[i][2].stop

            if (out_coords_i_start != out_h_start) or (out_coords_i_stop != out_h_stop):
                out_h_start = out_coords_i_start
                out_h_stop = out_coords_i_stop
                filter = (out_h_start <= cond_pos[index][:, 0]) & (cond_pos[index][:, 0] < out_h_stop)
                filtered_out_cond_pos = cond_pos[index][filter]
                filtered_out_cond_vals = cond_vals[index][filter]

            i_s, j_s, k_s, patch_vals = get_patch_cond_pos_vals(
                out_coords[i], index, filtered_out_cond_pos, filtered_out_cond_vals, safe_radiuses
            )

            if patch_vals is not None:
                final_patch[:, :, i_s, j_s, k_s] = patch_vals

        if last_scale:
            if segmented_output:
                final_patch = range_transform(final_patch.numpy().clip(-1, 1), in_range=[-1, 1], out_range=[1, 3])
                # final_patch = np.round(final_patch).astype(np.uint8)
                final_patch = segment(final_patch, segments)

            interpolation_mng.patch_to_out_imgs(
                final_patch,
                out_coords[i],
            )

        else:
            interpolation_mng.patch_to_mmap_partition(
                f"out_img_index_{index}",
                final_patch,
                out_coords[i],
                index,
            )
            del img_patch, inf_patch


def get_inference_early_crop(
    range_start,
    model_shapes,
    # crop_indexes,
    # base_volume,
    type_2,
    pre_split_in_img,
    injection,
    injection_kwargs,
    cond_img_scales,
    imagelog_integration,
    cond_pos,
    cond_vals,
    safe_radiuses,
    segmented_output,
    zero_padd,
    models,
    gpu_device,
    amp,
    z,
    all_scales,
    slice_,
    segments,
):

    is_cropped = False

    if injection:
        cond_img_start = [round(slice_[2:][i].start * cond_img_scales[i]) for i in range(3)]
        cond_img_end = [round(slice_[2:][i].stop * cond_img_scales[i]) for i in range(3)]
        cond_img = injection_kwargs["cond_img"]

        cond_img_slice = np.s_[
            :,
            :,
            cond_img_start[0] : cond_img_end[0],
            cond_img_start[1] : cond_img_end[1],
            cond_img_start[2] : cond_img_end[2],
        ]
        first_cond_img_patch = cond_img[cond_img_slice]

    for index in range(range_start, len(model_shapes)):
        scale_shape = model_shapes[index]
        scales = all_scales[index]

        # Get resized indexes
        start = [round(slice_[2:][i].start * scales[i]) for i in range(3)]
        end = [round(slice_[2:][i].stop * scales[i]) for i in range(3)]

        projected_slice = np.s_[
            :,
            :,
            start[0] : end[0],
            start[1] : end[1],
            start[2] : end[2],
        ]

        padded_projected_slice, padded_projected_slice_spec = get_padded_patch(projected_slice, scale_shape, zero_padd)

        if is_cropped:
            in_img = imresize(in_img, [end[i] - start[i] for i in range(3)])
            pad_in_img = imresize(pad_in_img_first, [end[i] - start[i] + 2 * zero_padd for i in range(3)])
        else:
            is_cropped = True

            if not type_2:
                # gera o primeiro patch a partir da imagem redimensionada
                pad_in_img_first = torch.from_numpy(pre_split_in_img[padded_projected_slice])
                pad_in_img_first = F.pad(pad_in_img_first, padded_projected_slice_spec, value=0)
                pad_in_img = pad_in_img_first
                in_img = torch.from_numpy(pre_split_in_img[projected_slice])
            else:
                # gera o primeiro patch a partir do redimensionamento de um patch
                previous_index = max(index - 1, 0)
                previous_scales = all_scales[previous_index]
                previous_start = [round(slice_[2:][i].start * previous_scales[i]) for i in range(3)]
                previous_end = [round(slice_[2:][i].stop * previous_scales[i]) for i in range(3)]

                previous_projected_slice = np.s_[
                    :,
                    :,
                    previous_start[0] : previous_end[0],
                    previous_start[1] : previous_end[1],
                    previous_start[2] : previous_end[2],
                ]

                prev_pad_projected_slice, prev_pad_projected_slice_spec = get_padded_patch(
                    previous_projected_slice, model_shapes[previous_index], zero_padd
                )

                pad_in_img_first = torch.from_numpy(pre_split_in_img[prev_pad_projected_slice])
                pad_in_img_first = F.pad(pad_in_img_first, prev_pad_projected_slice_spec, value=0)
                pad_in_img = imresize(pad_in_img_first, [end[i] - start[i] + 2 * zero_padd for i in range(3)])
                in_img = torch.from_numpy(pre_split_in_img[previous_projected_slice])
                in_img = imresize(in_img, [end[i] - start[i] for i in range(3)])

        if injection:
            cond_img_patch = F.interpolate(
                first_cond_img_patch,
                size=[end[i] - start[i] for i in range(3)],
                mode="nearest-exact",
                align_corners=None,
            )

            in_img = perform_patch_injection(
                in_img, cond_img_patch, injection_kwargs["injection_scale"], index, injection_kwargs["hard_data"]
            )

        if imagelog_integration:
            out_coords = np.s_[:, :, start[0] : end[0], start[1] : end[1], start[2] : end[2]]
            i_s, j_s, k_s, patch_vals = get_patch_cond_pos_vals(
                out_coords,
                index,
                cond_pos[index],
                cond_vals[index],
                safe_radiuses,
            )

            if patch_vals is not None:
                in_img[:, :, i_s, j_s, k_s] = patch_vals

        pad_in_img[:, :, zero_padd:-zero_padd, zero_padd:-zero_padd, zero_padd:-zero_padd] = in_img
        no_padded_z_patch = z.get_noise_patch(padded_projected_slice, index)
        z_in = F.pad(no_padded_z_patch * amp[index], padded_projected_slice_spec, value=0) + pad_in_img
        out_img = (models[index](z_in.to(gpu_device))).to("cpu")
        out_img = out_img + in_img

        if injection:
            out_img = perform_patch_injection(
                out_img, cond_img_patch, injection_kwargs["injection_scale"], index, injection_kwargs["hard_data"]
            )

        if imagelog_integration:
            i_s, j_s, k_s, patch_vals = get_patch_cond_pos_vals(
                out_coords,
                index,
                cond_pos[index],
                cond_vals[index],
                safe_radiuses,
            )

            if patch_vals is not None:
                out_img[:, :, i_s, j_s, k_s] = patch_vals

        in_img = out_img

    if segmented_output:
        out_img = range_transform(
            out_img.numpy().clip(-1, 1),
            in_range=[-1, 1],
            out_range=[1, 3],
        )
        # out_img = np.round(out_img).astype(np.uint8)
        out_img = segment(out_img, segments)
    return out_img


def get_padded_patch(no_pad_patch, scale_shape, pad):

    max_d = scale_shape[2]
    max_h = scale_shape[3]
    max_w = scale_shape[4]

    padded_patch = np.s_[
        :,
        :,
        max(0, no_pad_patch[2].start - pad) : min(no_pad_patch[2].stop + pad, max_d),
        max(0, no_pad_patch[3].start - pad) : min(no_pad_patch[3].stop + pad, max_h),
        max(0, no_pad_patch[4].start - pad) : min(no_pad_patch[4].stop + pad, max_w),
    ]

    padding_spec = np.array(
        [
            max(0, pad - no_pad_patch[4].start),
            max(0, no_pad_patch[4].stop + pad - max_w),
            max(0, pad - no_pad_patch[3].start),
            max(0, no_pad_patch[3].stop + pad - max_h),
            max(0, pad - no_pad_patch[2].start),
            max(0, no_pad_patch[2].stop + pad - max_d),
        ]
    )
    return padded_patch, tuple(padding_spec)
