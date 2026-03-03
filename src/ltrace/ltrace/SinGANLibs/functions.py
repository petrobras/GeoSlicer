import os
import tifffile as tif
import numpy as np
import math
import psutil
import torch
import logging
from ltrace.SinGANLibs.custom_layer import imresize
from ltrace.SinGANLibs.unwraputils import return_sorted_coordinates, get_unwrap
from skimage.transform import resize as skimage_resize


def weights_init(m):
    classname = m.__class__.__name__
    if classname.find("Conv3d") != -1:
        m.weight.data.normal_(0.0, 0.02)
    elif classname.find("Norm") != -1:
        m.weight.data.normal_(1.0, 0.02)
        m.bias.data.fill_(0)


def denorm(x):
    out = (x + 1) / 2
    return out.clamp(0, 1)


def norm(x):
    out = (x - 0.5) * 2
    return out.clamp(-1, 1)


def np2torch(x, opt):
    x = x.squeeze()

    if opt.img_num_channel == 3 and len(x.shape) == 3:
        x = np.stack((x,) * 3, axis=-1)

    if len(x.shape) == 3:
        x = np.expand_dims(x, -1)

    x = x[:, :, :, :, None]
    x = x.transpose((4, 3, 0, 1, 2))

    x = torch.from_numpy(x)
    x = x.type(torch.FloatTensor)
    x = norm(x)

    return x


def torch2np(inp):
    inp = denorm(inp)
    inp = inp[-1, :, :, :, :].cpu().numpy()
    inp = np.clip(inp, 0, 1)

    return inp.astype(np.float32)


def range_transform(img, in_range=[0, 255], out_range=[-1, 1]):
    if in_range != out_range:
        scale = np.float32(out_range[1] - out_range[0]) / np.float32(in_range[1] - in_range[0])
        bias = np.float32(out_range[0]) - np.float32(in_range[0]) * scale
        img = img * scale + bias

    return img


def read_image(opt):
    extension = os.path.splitext(opt.input_path)[1]

    if extension == ".tif" or extension == ".tiff":
        image = tif.imread(opt.input_path)
    elif extension == ".npy":
        image = np.load(opt.input_path)
    else:
        raise RuntimeError("Image type not supported. Supported=('.tif', '.tiff', '.npy')")

    image = range_transform(image, opt.img_color_range, [0, 1])
    image = np2torch(image, opt)

    return image[:, 0:3, :, :, :]


def adjust_scales2image(image, opt):
    scale = opt.max_size / max([image.shape[2], image.shape[3], image.shape[4]])
    out_shape = np.uint(np.round(np.array([image.shape[2], image.shape[3], image.shape[4]]) * scale)).tolist()

    real = imresize(image, out_shape)

    opt.scale_factor = math.pow(opt.min_size / (min(real.shape[2], real.shape[3], real.shape[4])), 1 / opt.stop_scale)

    return real


def generate_piramid(image, opt):
    reals = []

    for i in range(opt.stop_scale + 1):
        scale = math.pow(opt.scale_factor, opt.stop_scale - i)
        out_shape = np.uint(np.round(np.array([image.shape[2], image.shape[3], image.shape[4]]) * scale)).tolist()
        curr_real = imresize(image, out_shape)
        reals.append(curr_real)

    return reals


def reset_grads(model, require_grad=False):
    for p in model.parameters():
        p.requires_grad_(require_grad)

    return model


def generate_noise(size, device, num_samp=1, scale=1):
    noise = torch.randn(num_samp, size[0], *[round(s / scale) for s in size[1:]], device=device)

    if scale != 1:
        noise = imresize(noise, size[1:])

    return noise


def calc_gradient_penalty(netD, real_data, fake_data, LAMBDA, device):
    alpha = torch.rand(1, 1)
    alpha = alpha.expand(real_data.size())
    alpha = alpha.to(device)

    interpolates = alpha * real_data + ((1 - alpha) * fake_data)
    interpolates = interpolates.to(device)
    interpolates = torch.autograd.Variable(interpolates, requires_grad=True)

    disc_interpolates = netD(interpolates)

    gradients = torch.autograd.grad(
        outputs=disc_interpolates,
        inputs=interpolates,
        grad_outputs=torch.ones(disc_interpolates.size()).to(device),
        create_graph=True,
        retain_graph=True,
        only_inputs=True,
    )[0]

    gradient_penalty = ((gradients.norm(2, dim=1) - 1) ** 2).mean() * LAMBDA

    return gradient_penalty


def create_dirs(path):
    try:
        if not os.path.exists(path):
            os.makedirs(path)
    except Exception as e:
        raise e


def get_imagelog_info(img, outputshape, segments):
    if len(outputshape) != 3:
        logging.info(f"outputshape given is {len(outputshape)}, but it must be 3")
        return
    if outputshape[1] != outputshape[2]:
        logging.info(f"outputshape given is {outputshape}, but it must be (height, width, width)")
        return
    radius = radius_shift = outputshape[-1] // 2 - 1
    height = outputshape[0]
    # logging.info(f"radius: {radius}, height: {height}")
    coords = return_sorted_coordinates(radius) + radius_shift
    # logging.info("coords.shape: ", coords.shape)

    imglog3d = img
    unwrapradius = imglog3d.shape[-1] // 2 - 1
    imglog2d = get_unwrap(imglog3d, unwrapradius)
    output_shape = (height, coords.shape[0])
    imglog2d = skimage_resize(imglog2d, output_shape=output_shape, order=0, anti_aliasing=False)

    i_s, j_s = np.where((imglog2d != 0) & (np.isin(imglog2d, segments)))
    pos = np.concatenate([np.expand_dims(i_s, axis=1), coords[j_s]], axis=1)
    vals = imglog2d[i_s, j_s]
    return pos, vals


def generate_cond_pos_val(cond, shapes, segments):
    cond_pos = []
    cond_vals = []

    for shape in shapes:
        pos, vals = get_imagelog_info(cond, shape, segments)
        vals_max = vals.max()
        vals_min = vals.min()
        vals = ((vals - vals_min) / (vals_max - vals_min) - 0.5) * 2
        cond_pos.append(pos)
        cond_vals.append(torch.from_numpy(vals).float())
    return cond_pos, cond_vals


def find_safe_radiuses(shapes, cond_pos):
    safe_radiuses = {k: {} for k in range(len(shapes))}
    for index in range(len(shapes)):
        center = shapes[index][-1] // 2 - 1
        safe_radiuses[index]["center"] = center
        internal_defined = False
        external_defined = False
        internal_delta = 1
        external_delta = 1

        while not (internal_defined and external_defined):
            if not internal_defined:
                internal_safe_radius = center - internal_delta
                if np.all(
                    (cond_pos[index][:, 1] - center) ** 2 + (cond_pos[index][:, 2] - center) ** 2
                    > internal_safe_radius**2
                ):
                    safe_radiuses[index]["internal"] = internal_safe_radius
                    internal_defined = True
                else:
                    internal_delta += 1

            if not external_defined:
                external_safe_radius = center + external_delta
                if np.all(
                    (cond_pos[index][:, 1] - center) ** 2 + (cond_pos[index][:, 2] - center) ** 2
                    < external_safe_radius**2
                ):
                    safe_radiuses[index]["external"] = external_safe_radius
                    external_defined = True
                else:
                    external_delta += 1
    return safe_radiuses


def load(path, device=torch.device("cpu")):
    # Load file with 'weights_only=True' is recomended to prevent malicious code running
    # return torch.load(path, map_location=device, weights_only=True)
    return torch.load(path, map_location=device)


def unique_path(file_path):
    folder, file = os.path.split(file_path)
    file_name, ext = os.path.splitext(file)

    if os.path.exists(file_path):
        count = 1
        while os.path.exists(os.path.join(folder, f"{file_name}_({count}){ext}")):
            count += 1
        file_path = os.path.join(folder, f"{file_name}_({count}){ext}")

    return file_path


def get_slices(shape, patch_dim, padd):
    start_z = []
    for i in range(math.ceil((shape[-3] - 2 * padd) / patch_dim)):
        start_z.append(i * patch_dim)

    start_y = []
    for i in range(math.ceil((shape[-2] - 2 * padd) / patch_dim)):
        start_y.append(i * patch_dim)

    start_x = []
    for i in range(math.ceil((shape[-1] - 2 * padd) / patch_dim)):
        start_x.append(i * patch_dim)

    coords = []
    coords_no_padd = []
    for k in range(len(start_z)):
        end_z = min(start_z[k] + patch_dim + 2 * padd, shape[-3])
        end_z_no_padd = min(start_z[k] + patch_dim, shape[-3])

        for i in range(len(start_y)):
            end_y = min(start_y[i] + patch_dim + 2 * padd, shape[-2])
            end_y_no_padd = min(start_y[i] + patch_dim, shape[-2])

            for j in range(len(start_x)):
                end_x = min(start_x[j] + patch_dim + (2 * padd), shape[-1])
                end_x_no_padd = min(start_x[j] + patch_dim, shape[-1])

                coords.append(np.s_[:, :, start_z[k] : end_z, start_y[i] : end_y, start_x[j] : end_x])
                coords_no_padd.append(
                    np.s_[:, :, start_z[k] : end_z_no_padd, start_y[i] : end_y_no_padd, start_x[j] : end_x_no_padd]
                )

    return coords, coords_no_padd


def get_inference(model, volume, patch_dim, padd=0):
    result_volume = torch.zeros(
        (
            volume.shape[0],
            volume.shape[1],
            volume.shape[2] - (2 * padd),
            volume.shape[3] - (2 * padd),
            volume.shape[4] - (2 * padd),
        ),
        device=volume.device,
        dtype=volume.dtype,
    )
    slices, slices_no_padd = get_slices(volume.shape, patch_dim=patch_dim, padd=padd)

    for i in range(len(slices)):

        patch = volume[slices[i]]
        out = model(patch)
        result_volume[slices_no_padd[i]] = out

        del patch, out

    return result_volume


def prepare_injection(injection_scale, hard_data, cond_img, opt, injection_start_scale):
    # When hd is passed as injection_scale, this variable is updated to be a list starting at scale 1 up to the last scale
    # When just an int is passed, this variable is updated to be a list with this single value.
    assert cond_img is not None, "cond_image must be provided"

    if injection_scale == "hd":
        injection_scale = list(range(injection_start_scale, opt.stop_scale + 1))
    elif isinstance(injection_scale, int):
        injection_scale = [injection_scale]

    # Adjust hard_data range, and normalize it
    hard_data = np.array(hard_data, dtype=np.float32)
    hard_data = range_transform(hard_data, opt.img_color_range, [0, 1])
    hard_data = torch.from_numpy(hard_data)
    hard_data = norm(hard_data)

    # normalize cond_img
    cond_img = range_transform(cond_img, opt.img_color_range, [0, 1])
    cond_img = np2torch(cond_img, opt)

    return injection_scale, hard_data, cond_img


def prepare_imagelog_integration(imagelog, model_shapes, segments):
    # When hd is passed as injection_scale, this variable is updated to be a list starting at scale 1 up to the last scale
    # When just an int is passed, this variable is updated to be a list with this single value.
    assert imagelog is not None, "imagelog must be provided"
    shapes = [shape[2:] for shape in model_shapes]
    pos, vals = generate_cond_pos_val(imagelog, shapes, segments)
    safe_radiuses = find_safe_radiuses(shapes, pos)
    return pos, vals, safe_radiuses


def get_generation_params(model_shapes, corect_integration, security_factor=0.6, debug=False):
    free_ram_by = psutil.virtual_memory().free
    # print("free: ", free_ram_by / 1024 ** 3)
    # split_scale
    # previous scale out_image + upscaled out_image
    estimation_interpolation_by = [model_shapes[0].numel() * 4 * (1 + security_factor)]
    for k in range(1, len(model_shapes)):
        estimation = (model_shapes[k].numel() + model_shapes[k - 1].numel()) * 4 * (1 + security_factor)
        estimation_interpolation_by.append(estimation)

    estimation_interpolation_by = np.array(estimation_interpolation_by)
    if np.all(estimation_interpolation_by < free_ram_by):
        split_scale = -1
    else:
        split_scale = max(np.argmin(estimation_interpolation_by < free_ram_by) - 1, 0)

    # disk_scale
    if corect_integration:
        # in_img + corect_upscaled + out
        estimation_max_memory_by = [3 * shape.numel() * 4 * (1 + security_factor) for shape in model_shapes]
    else:
        # in_img + out
        estimation_max_memory_by = [2 * shape.numel() * 4 * (1 + security_factor) for shape in model_shapes]

    estimation_max_memory_by = np.array(estimation_max_memory_by)
    if np.all(estimation_max_memory_by < free_ram_by):
        disk_scale = -1
    else:
        disk_scale = max(np.argmin(estimation_max_memory_by < free_ram_by) - 2, 0)

    # crop_scale
    crop_scale = 0

    if debug:
        import pandas as pd

        df_memory = (
            pd.DataFrame(
                {
                    "estimation_interpolation_GB": estimation_interpolation_by,
                    "estimation_max_memory_GB": estimation_max_memory_by,
                }
            )
            / 1024**3
        )
        return df_memory, crop_scale, disk_scale, split_scale
    else:
        return crop_scale, disk_scale, split_scale


def get_base_volume(gpu_device):
    free_gpu_by = torch.cuda.mem_get_info(gpu_device)[0]
    # base_volume
    if 3 * 1024**3 <= free_gpu_by < 5 * 1024**3:
        base_volume = 50
    elif 5 * 1024**3 <= free_gpu_by < 9 * 1024**3:
        base_volume = 75
    elif 9 * 1024**3 <= free_gpu_by < 21 * 1024**3:
        base_volume = 100
    elif 21 * 1024**3 <= free_gpu_by:
        base_volume = 150
    else:
        raise Exception("base_volume could not be determined")
    return base_volume


def segment(image, segments):
    if segments == 2:
        output = np.zeros_like(image)
        output[image <= 2.5] = 1
        output[image > 2.5] = 3
        return output.astype(np.uint8)
    else:
        return np.round(image).astype(np.uint8)
