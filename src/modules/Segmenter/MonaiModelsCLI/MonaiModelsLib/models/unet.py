import torch
import monai
from monai.networks.blocks.convolutions import Convolution, ResidualUnit


class UNetAct(torch.nn.Module):
    def __init__(
        self,
        spatial_dims=3,
        in_channels=1,
        out_channels=None,
        base_channels=None,
        scales=3,
        act="prelu",
        last_act=None,
        stride=2,
        channel_multiplier=2,
        num_res_units=0,
    ):
        super().__init__()

        base_channels = base_channels or in_channels
        out_channels = out_channels or in_channels

        self.unet = monai.networks.nets.UNet(
            spatial_dims=spatial_dims,
            in_channels=in_channels,
            out_channels=out_channels,
            channels=[base_channels * channel_multiplier**i for i in range(scales)],
            strides=[stride for i in range(scales - 1)],
            num_res_units=num_res_units,
        )

        if last_act is not None:
            self.last_act = monai.networks.layers.utils.get_act_layer(last_act)
        else:
            self.last_act = lambda x: x

    def forward(self, x):
        x = self.unet(x)
        x = self.last_act(x)
        return x


class UNetActWithBoundarySupervision(torch.nn.Module):
    def __init__(
        self,
        spatial_dims=3,
        in_channels=1,
        out_channels=None,
        base_channels=None,
        scales=3,
        act="prelu",
        last_act=None,
        stride=2,
        channel_multiplier=2,
        num_res_units=0,
    ):
        super().__init__()

        base_channels = base_channels or in_channels
        out_channels = out_channels or in_channels

        self.unet = monai.networks.nets.UNet(
            spatial_dims=spatial_dims,
            in_channels=in_channels,
            out_channels=out_channels,
            channels=[base_channels * channel_multiplier**i for i in range(scales)],
            strides=[stride for i in range(scales - 1)],
            num_res_units=num_res_units,
        )

        self.segmentation_head = ResidualUnit(
            spatial_dims=spatial_dims,
            in_channels=in_channels,
            out_channels=out_channels,
            strides=1,
            kernel_size=3,
            subunits=num_res_units,
            act=self.unet.act,
            norm=self.unet.norm,
            dropout=self.unet.dropout,
        )

        self.boundary_head = ResidualUnit(
            spatial_dims=spatial_dims,
            in_channels=in_channels,
            out_channels=1,
            strides=1,
            kernel_size=3,
            subunits=num_res_units,
            act=self.unet.act,
            norm=self.unet.norm,
            dropout=self.unet.dropout,
        )

        if last_act is not None:
            self.last_act = monai.networks.layers.utils.get_act_layer(last_act)
        else:
            self.last_act = lambda x: x

        self.main_model = torch.nn.Sequential(self.unet, self.segmentation_head)

    def forward(self, x, boundary=False):
        x = self.unet(x)

        seg = self.segmentation_head(x)
        seg = self.last_act(seg)

        if not boundary:
            return seg

        bound = self.boundary_head(x)
        bound = torch.sigmoid(bound)
        return seg, bound


class PseudoDimModelWrapper(torch.nn.Module):
    def __init__(self, model, pseudo_dim_axis=2, **config):
        super().__init__()
        self.axis = pseudo_dim_axis
        self.model = model(**config)

    def forward(self, x, axis=None):
        if axis is None:
            axis = self.axis

        x_swapped = x.swapaxes(axis, 1)
        x_pseudo = x_swapped.reshape((-1, *x_swapped.shape[2:]))

        y_pseudo = self.model(x_pseudo)

        y_swapped = y_pseudo.reshape((x_swapped.shape[0], x_swapped.shape[1], -1, *x_swapped.shape[3:]))
        y = y_swapped.swapaxes(1, axis)
        return y
