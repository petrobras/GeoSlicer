import torch.nn as nn

from ltrace.SinGANLibs.custom_layer import ConvBlock


class Discriminator(nn.Module):
    def __init__(self, num_feature, min_num_feature, num_layer, ker_size, padd_size, img_num_channel):
        super(Discriminator, self).__init__()

        self.head = ConvBlock(img_num_channel, num_feature, ker_size, padd_size, 1)
        self.body = nn.Sequential()

        for i in range(num_layer - 2):
            n = int(num_feature / pow(2, (i + 1)))
            block = ConvBlock(max(2 * n, min_num_feature), max(n, min_num_feature), ker_size, padd_size, 1)
            self.body.add_module("block%d" % (i + 1), block)

        self.tail = nn.Conv3d(max(n, min_num_feature), 1, kernel_size=ker_size, stride=1, padding=padd_size)

    def forward(self, x):
        x = self.head(x)
        x = self.body(x)
        x = self.tail(x)

        return x
