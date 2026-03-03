import os
import math
import json
import numpy as np
import torch
import torch.nn.functional as F
import torch.nn as nn
import ltrace.SinGANLibs.functions as functions

from ltrace.SinGANLibs.config import G_FILE, D_FILE, REC_FILE, AMP_FILE, SHAPE_FILE, OPT_FILE
from ltrace.SinGANLibs.discriminator import Discriminator
from ltrace.SinGANLibs.generator import Generator
from types import SimpleNamespace


def load_singan_model(device, model_path):

    with open(os.path.join(model_path, OPT_FILE), "r") as f:
        opt = json.load(f, object_hook=lambda x: SimpleNamespace(**x))

    model = SinGAN(device, opt=opt)
    model.load(model_path, load_D=False)

    return model


def reshape_singan_model(model, model_path, cond_img, cond_img_resolution):
    with open(os.path.join(model_path, OPT_FILE), "r") as f:
        opt = json.load(f, object_hook=lambda x: SimpleNamespace(**x))

    ti_res = opt.ti_resolution_mm
    ti_size = np.array([i * ti_res for i in model.shapes[-1][-3:]])
    resolutions = np.array([[ti_size[-3] / i[-3], ti_size[-2] / i[-2], ti_size[-1] / i[-1]] for i in model.shapes])
    mean_resolutions = resolutions.mean(axis=1)
    coreCT_resolution = cond_img_resolution
    abs_diff = np.absolute(mean_resolutions - coreCT_resolution)
    injection_start_scale = np.argmin(abs_diff)
    multz = cond_img.shape[0] / model.shapes[injection_start_scale][2]
    multy = cond_img.shape[1] / model.shapes[injection_start_scale][3]
    multx = cond_img.shape[2] / model.shapes[injection_start_scale][4]
    model.shapes = [torch.Size([1, 1, int(i[2] * multz), int(i[3] * multy), int(i[4] * multx)]) for i in model.shapes]


class SinGAN:
    def __init__(self, device, opt):
        self.device = device

        # Image parameters
        self.img_num_channel = opt.img_num_channel
        self.img_color_range = opt.img_color_range
        self.zero_padd = opt.num_layer * math.floor(opt.ker_size / 2)

        # Trainig parameters
        self.D_steps = opt.D_steps
        self.G_steps = opt.G_steps
        self.lambda_grad = opt.lambda_grad
        self.alpha = opt.alpha

        # Network parameters
        self.num_feature = opt.num_feature
        self.min_num_feature = opt.min_num_feature
        self.num_layer = opt.num_layer
        self.ker_size = opt.ker_size
        self.padd_size = opt.padd_size

        self.shapes = []
        self.rec_noise = []
        self.noise_amp = []

        self.G = Generator(
            self.num_layer,
            self.ker_size,
            self.padd_size,
            self.img_num_channel,
            opt.crop_size,
            self.img_color_range,
        ).to(self.device)
        self.D = None

    def init_scale_G(self, scale):
        num_feature, min_num_feature = self.get_num_features(scale)

        self.G.create_scale(num_feature, min_num_feature)
        self.G.gens[-1] = self.G.gens[-1].to(self.device)

        # If the Generator features were doubled, reinitialize the weights.
        # If not, continue with the current weights
        if scale % 4 == 0:
            self.G.gens[-1].apply(functions.weights_init)
        else:
            self.G.gens[-1].load_state_dict(self.G.gens[-2].state_dict())

        if len(self.G.gens) > 1:
            self.G.gens[-2] = functions.reset_grads(self.G.gens[-2])
            self.G.gens[-2].eval()

    def init_scale_D(self, scale):
        num_feature, min_num_feature = self.get_num_features(scale)

        # If the Dicriminator features were doubled, recreate the Discriminator and reinitialize the weights.
        # If not, continue with the current Discriminator
        if scale % 4 == 0:
            self.D = Discriminator(
                num_feature, min_num_feature, self.num_layer, self.ker_size, self.padd_size, self.img_num_channel
            ).to(self.device)
            self.D.apply(functions.weights_init)

    def get_num_features(self, scale):
        # Doubles the number of features every 4 scales
        num_feature = min(self.num_feature * pow(2, math.floor(scale / 4)), 128)
        min_num_feature = min(self.min_num_feature * pow(2, math.floor(scale / 4)), 128)

        return num_feature, min_num_feature

    def get_noise(self, rec=False, last=False):
        def generate_noise(index):
            if index == 0:
                z = functions.generate_noise([1, *self.shapes[index][2:]], device=self.device)
                z = z.expand(1, self.img_num_channel, *self.shapes[index][2:])
            else:
                z = functions.generate_noise([self.img_num_channel, *self.shapes[index][2:]], device=self.device)

            z = F.pad(z, [self.zero_padd] * 6, value=0)

            return z

        if rec:
            # Return the reconstruction noise
            return self.rec_noise.copy()
        elif last:
            # Return only the last scale noise
            return generate_noise(len(self.rec_noise) - 1)
        else:
            # Return all scales random gausian noise
            noises = []

            for index in range(len(self.rec_noise)):
                noises.append(generate_noise(index))

            return noises

    def optimize_D(self, indexes, real, optimizerD):
        fixed_noise = self.get_noise(last=True)

        for _ in range(self.D_steps):
            optimizerD.zero_grad()

            D_loss_real = self.D(real)
            D_loss_real = -D_loss_real.mean()

            noises = self.get_noise()
            noises[-1] = fixed_noise

            with torch.no_grad():
                fake = self.G(noises, self.noise_amp, indexes, use_crop=True)

            D_loss_fake = self.D(fake.detach())
            D_loss_fake = D_loss_fake.mean()

            D_loss_real.backward()
            D_loss_fake.backward()

            D_loss_GP = functions.calc_gradient_penalty(self.D, real, fake, self.lambda_grad, self.device)
            D_loss_GP.backward()

            D_loss = D_loss_real.item() + D_loss_fake.item() + D_loss_GP.item()

            optimizerD.step()

        return D_loss, D_loss_real.item(), D_loss_fake.item(), D_loss_GP.item()

    def optimize_G(self, indexes, real, rec_in, optimizerG):
        for _ in range(self.G_steps):
            optimizerG.zero_grad()

            noises = self.get_noise()
            fake = self.G(noises, self.noise_amp, indexes, use_crop=True)

            G_loss_fake = self.D(fake)
            G_loss_fake = -G_loss_fake.mean()
            G_loss_fake.backward()

            G_loss_rec = torch.zeros(1)
            rec = None

            if self.alpha != 0:
                rec_noise = self.get_noise(rec=True)
                rec = self.G(
                    rec_noise, self.noise_amp, indexes, in_img=rec_in, start_scale=len(self.G.gens) - 1, use_crop=True
                )
                G_loss_rec = self.alpha * nn.MSELoss()(rec, real)
                G_loss_rec.backward()

            G_loss = G_loss_fake.item() + G_loss_rec.item()

            optimizerG.step()

        return G_loss, G_loss_fake.item(), G_loss_rec.item(), fake.detach(), rec.detach()

    def save_scale(self, scale, path):
        torch.save(self.G.gens[scale].state_dict(), os.path.join(path, G_FILE))
        torch.save(self.D.state_dict(), os.path.join(path, D_FILE))
        torch.save(self.rec_noise[scale], os.path.join(path, REC_FILE))
        torch.save(self.shapes[scale], os.path.join(path, SHAPE_FILE))

        with open(os.path.join(path, AMP_FILE), "w") as f:
            f.write(str(self.noise_amp[scale]))

    def load(self, path, load_D=True, load_shapes=True, until_scale=None):
        # Get all scale paths as integer
        scales_path = sorted(list(map(int, next(os.walk(path))[1])))

        if until_scale is not None:
            scales_path = list(filter(lambda x: x <= until_scale, scales_path))

        for scale in scales_path:
            try:
                num_feature, min_num_feature = self.get_num_features(scale)

                if load_D:
                    self.D = Discriminator(
                        num_feature,
                        min_num_feature,
                        self.num_layer,
                        self.ker_size,
                        self.padd_size,
                        self.img_num_channel,
                    ).to(self.device)
                    self.D.load_state_dict(functions.load(os.path.join(path, str(scale), D_FILE), self.device))

                if load_shapes:
                    self.shapes.append(functions.load(os.path.join(path, str(scale), SHAPE_FILE)))

                self.G.create_scale(num_feature, min_num_feature)
                self.G.gens[scale].to(self.device)
                self.G.gens[scale].load_state_dict(functions.load(os.path.join(path, str(scale), G_FILE), self.device))
                self.G.gens[scale] = functions.reset_grads(self.G.gens[scale])
                self.G.gens[scale].eval()

                self.rec_noise.append(functions.load(os.path.join(path, str(scale), REC_FILE), self.device))

                with open(os.path.join(path, str(scale), AMP_FILE)) as f:
                    self.noise_amp.append(float(f.readline().strip()))

            except Exception as e:
                print(f"Error loading models from {path}/{scale}. There may be files missing.")
                raise e

        return len(scales_path)
