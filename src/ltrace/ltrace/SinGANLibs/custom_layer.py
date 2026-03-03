import torch.nn as nn


class ConvBlock(nn.Sequential):
    def __init__(self, in_channel, out_channel, ker_size, padd, stride):
        super(ConvBlock, self).__init__()

        self.add_module("conv", nn.Conv3d(in_channel, out_channel, kernel_size=ker_size, stride=stride, padding=padd))
        self.add_module("norm", nn.BatchNorm3d(out_channel))
        self.add_module("LeakyRelu", nn.LeakyReLU(0.2, inplace=True))


def imresize(x, size):
    x_up = nn.functional.interpolate(x, size=size, mode="trilinear", align_corners=True)
    return x_up
