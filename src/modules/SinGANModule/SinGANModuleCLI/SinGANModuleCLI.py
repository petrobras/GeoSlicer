#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
import vtk, slicer, slicer.util, mrml
import json
import logging
import numpy as np
import os
import sys
import time
import xarray as xr

from pathlib import Path
from ltrace.slicer.cli_utils import writeDataInto, readFrom, progressUpdate

import torch
from types import SimpleNamespace
from ltrace.SinGANLibs.config import OPT_FILE
from ltrace.SinGANLibs.functions import range_transform, prepare_injection, prepare_imagelog_integration
from ltrace.SinGANLibs.noise import DynamicNoise, NoiseReconstruction
from ltrace.SinGANLibs.singan import SinGAN
from ltrace.SinGANLibs.unwraputils import get_wrap


def generate_image(args):
    noise_type = "dynamic"

    with open(os.path.join(args.model_path, OPT_FILE), "r") as f:
        opt = json.load(f, object_hook=lambda x: SimpleNamespace(**x))

    if arguments.use_gpu and torch.cuda.is_available():
        if arguments.gpu_device >= torch.cuda.device_count():
            raise ValueError(f"Device {arguments.gpu_device} is not available, please choose a valid device.")

    device = torch.device(f"cuda:{arguments.gpu_device}" if arguments.use_gpu else "cpu")

    model = SinGAN(device, opt=opt)
    model.load(args.model_path, load_D=False)
    model.G.eval()
    injection_start_scale = None
    segments = getattr(opt, "segments", 3)

    imagelog = None
    cond_img = None
    if arguments.imagelog is not None:
        volume = readFrom(arguments.imagelog, mrml.vtkMRMLScalarVolumeNode)
        imagelog = slicer.util.arrayFromVolume(volume)
        del volume

        if imagelog.shape[1] == 1:
            imagelog = imagelog.squeeze(axis=1)
            try:
                radius = int((imagelog.shape[1] / np.pi) // 2 - 1)
                imagelog = get_wrap(imagelog, radius)
            except:
                radius = int((imagelog.shape[1] / np.pi) // 2 - 1) - 1
                imagelog = get_wrap(imagelog, radius)

        imglog_injection_scale = 1

        multz = imagelog.shape[0] / model.shapes[imglog_injection_scale][2]
        multy = imagelog.shape[1] / model.shapes[imglog_injection_scale][3]
        multx = imagelog.shape[2] / model.shapes[imglog_injection_scale][4]
        model.shapes = [
            torch.Size([1, 1, int(i[2] * multz), int(i[3] * multy), int(i[4] * multx)]) for i in model.shapes
        ]

    if arguments.cond_img is not None:
        volume = readFrom(arguments.cond_img, mrml.vtkMRMLScalarVolumeNode)
        cond_img = slicer.util.arrayFromVolume(volume)
        del volume

        ti_res = opt.ti_resolution_mm
        ti_size = np.array([i * ti_res for i in model.shapes[-1][-3:]])
        resolutions = np.array([[ti_size[-3] / i[-3], ti_size[-2] / i[-2], ti_size[-1] / i[-1]] for i in model.shapes])
        mean_resolutions = resolutions.mean(axis=1)
        coreCT_resolution = arguments.cond_img_resolution
        abs_diff = np.absolute(mean_resolutions - coreCT_resolution)
        injection_start_scale = np.argmin(abs_diff)

        if arguments.imagelog is None:
            multz = cond_img.shape[0] / model.shapes[injection_start_scale][2]
            multy = cond_img.shape[1] / model.shapes[injection_start_scale][3]
            multx = cond_img.shape[2] / model.shapes[injection_start_scale][4]
            model.shapes = [
                torch.Size([1, 1, int(i[2] * multz), int(i[3] * multy), int(i[4] * multx)]) for i in model.shapes
            ]
        else:
            final_size = model.shapes[injection_start_scale]
            pad_z1 = (final_size[2] - cond_img.shape[0]) // 2
            pad_z2 = final_size[2] - cond_img.shape[0] - pad_z1
            pad_y1 = (final_size[3] - cond_img.shape[1]) // 2
            pad_y2 = final_size[3] - cond_img.shape[1] - pad_y1
            pad_x1 = (final_size[4] - cond_img.shape[2]) // 2
            pad_x2 = final_size[4] - cond_img.shape[2] - pad_x1
            cond_img = np.pad(
                cond_img,
                pad_width=((pad_z1, pad_z2), (pad_y1, pad_y2), (pad_x1, pad_x2)),
                mode="constant",
                constant_values=2,
            )

    chunks = list(map(int, args.chunks.split(",")))
    args.hard_data = list(map(int, args.hard_data.split(",")))
    args.imagelog_segments = list(map(int, args.imagelog_segments.split(",")))

    progressUpdate(0.1)

    for i in range(args.number_realizations):
        current_out_name = args.out_name + f"_R{i}"
        current_out_path = Path(args.out_path + f"/R{i}")
        if args.save_file:
            current_out_path.mkdir(parents=True, exist_ok=True)
        if args.rec:
            noise = model.get_noise(rec=True)
            noise = [i.to("cpu") for i in noise]
            noise = NoiseReconstruction(noise, model.zero_padd)
            args.method = "generation_patch_on_gpu"
        elif args.rec is False and noise_type == "dynamic":
            noise = DynamicNoise(
                model.shapes,
                args.base_volume,
                model.zero_padd,
                img_num_channel=model.img_num_channel,
                seed=args.seed + i,
                use_cache=True,
            )
            print(
                f"\nz : Dynamic noise, use_cache : {noise.use_cache}, dynamic_base_size : {noise.dynamic_base_size} \n"
            )
        elif args.rec is False and noise_type != "dynamic":
            noise = noise_type
            print(f"\nz : using noise saved in {noise_type}\n")

        with torch.no_grad():
            injection_scale = None
            hard_data = None
            injection = None
            injection_cond_img = cond_img
            if cond_img is not None:
                injection = True
                injection_scale, hard_data, injection_cond_img = prepare_injection(
                    injection_scale=args.injection_scale,
                    hard_data=args.hard_data,
                    cond_img=cond_img,
                    opt=opt,
                    injection_start_scale=injection_start_scale,
                )

            if imagelog is not None:  # TODO Check if image log is used as conditional input
                cond_pos, cond_vals, safe_radiuses = prepare_imagelog_integration(
                    imagelog, model.shapes, segments=args.imagelog_segments
                )
            else:
                cond_pos = None
                cond_vals = None
                safe_radiuses = None

            injection_kwargs = {}
            injection_kwargs["injection_scale"] = injection_scale
            injection_kwargs["hard_data"] = hard_data
            injection_kwargs["cond_img"] = injection_cond_img
            imagelog_integration_kwargs = {
                "cond_pos": cond_pos,
                "cond_vals": cond_vals,
                "safe_radiuses": safe_radiuses,
            }

            generatedImage = model.G.generation_router(
                method=args.method,
                z=noise,
                amp=model.noise_amp,
                in_img=None,
                start_scale=0,
                stop_scale=None,
                base_volume=args.base_volume,
                crop_scale=args.crop_scale,
                disk_scale=args.disk_scale,
                split_scale=args.split_scale,
                gpu_device=device,
                model_shapes=model.shapes,
                segmented_output=True,
                injection=injection,
                injection_kwargs=injection_kwargs,
                imagelog_integration=False,
                imagelog_integration_kwargs=imagelog_integration_kwargs,
                type_2=args.p2p,
                chunks=chunks,
                final_partition_spec=[args.partitions, 1, 1],
                tempPath=args.temp_path,
                prefix=current_out_name,
                outputPath=current_out_path,
                segments=segments,
            )
            if generatedImage is not None:
                generatedImage = generatedImage[0, ...]

                if arguments.save_bin:
                    writeNpBinary(generatedImage[0], args.temp_path, name=f"output_{i}")

                if arguments.save_file:
                    writeNC(generatedImage[0], current_out_path, f"{args.out_name}_{i}", opt.ti_resolution_mm)


def writeNC(image, path, name, ti_res):
    shape = list(image.shape)

    attrs = {}
    attrs["dimx"] = shape[0]
    attrs["dimy"] = shape[1]
    attrs["dimz"] = shape[2]
    attrs["resolution"] = float(ti_res)
    attrs["type"] = "labelmap"
    attrs["labels"] = ["Name,Index,Color", "Pores,1,#ff0000", "Matrix 1,2,#57fff7", "Matrix 2,3,#0000ff"]

    x = np.arange(shape[0]) * ti_res
    y = np.arange(shape[1]) * ti_res
    z = np.arange(shape[2]) * ti_res
    ds = xr.Dataset(
        {"SinGAN": (("z", "y", "x"), image, attrs)},
        coords={"z": z, "y": y, "x": x},
    )

    ds.x.attrs["units"] = "mm"
    ds.y.attrs["units"] = "mm"
    ds.z.attrs["units"] = "mm"

    ds.to_netcdf(Path(path).joinpath(f"{name}.nc"), "w", format="NETCDF4")


def writeNpBinary(image, tempPath, name):
    np.save(os.path.join(tempPath, f"{name}.npy"), image)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    # Inputs
    parser.add_argument("--model_path", dest="model_path", help="models path", type=str, required=True)
    parser.add_argument("--temp_path", dest="temp_path", help="path to hold temporary files", type=str)
    parser.add_argument("--use_gpu", help="use available GPU", action="store_true")
    parser.add_argument("--gpu_device", help="GPU device", type=int, default=0)
    parser.add_argument("--cond_img", dest="cond_img", type=str, default=None, help="Conditional image")
    parser.add_argument("--cond_img_resolution", type=float, default=0.0, help="Conditional image resolution")
    parser.add_argument("--injection_scale", dest="injection_scale", help="Injection scale(s)", type=str, default="hd")
    parser.add_argument(
        "--hard_data",
        help="Target class/classes that will be kept as hard data",
        type=str,
        default="1,3",
    )
    #
    parser.add_argument("--imagelog", dest="imagelog", type=str, default=None, help="Conditional image")
    parser.add_argument(
        "--imagelog_segments",
        help="Target class/classes that will be kept as hard data",
        type=str,
        default="1,3",
    )

    #
    parser.add_argument("--number_realizations", help="Number of generated Images", type=int, default=1)
    parser.add_argument(
        "--rec",
        help="generate a sample with the reconstruction noise. The reconstruction sample will have the same size as the TI",
        action="store_true",
    )
    # TODO: Fix help text
    parser.add_argument(
        "--method", dest="method", help="cropping method", type=str, default="generation_early_cropping", required=True
    )
    parser.add_argument("--seed", help="Seed to generate reproducible results", type=int, default=0)
    parser.add_argument("--base_volume", help="Base volume for cropping", type=int, default=128)
    parser.add_argument("--split_scale", help="Split scale", type=int, default=14)
    parser.add_argument("--crop_scale", help="Crop scale", type=int, default=0)
    parser.add_argument("--disk_scale", help="Disk scale", type=int, default=5)
    parser.add_argument("--p2p", help="Use p2p in early crop", action="store_true")
    parser.add_argument("--chunks", dest="chunks", help="Chunks", type=str, default="3,3,3")

    # Outputs
    parser.add_argument("--out_name", dest="out_name", help="Name of the files to be generated", type=str)
    parser.add_argument("--out_path", dest="out_path", help="Path to write files", type=str)
    parser.add_argument(
        "--save_bin", help="Save generated image as binary files to be read by geoslicer", action="store_true"
    )
    parser.add_argument("--save_file", help="Save generated image as file at output path", action="store_true")
    parser.add_argument("--partitions", help="Number of partitioned files to be created", type=int, default=1)

    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument(
        "--returnparameterfile", type=str, default=None, help="File destination to store an execution outputs"
    )

    arguments = parser.parse_args()
    image = generate_image(arguments)
