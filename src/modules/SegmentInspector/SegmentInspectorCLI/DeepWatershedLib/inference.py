import torch
from monai.inferers import sliding_window_inference
from ltrace.assets_utils import get_asset
import torch
import monai
from monai.networks.blocks.convolutions import Convolution
import numpy as np


class Deep_watershed_model(torch.nn.Module):
    def __init__(
        self,
        spatial_dims=3,
        in_channels=1,
        out_channels=None,
        base_channels=None,
        scales=5,
        act="relu",
        last_act="sigmoid",
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
            strides=[2 for i in range(scales - 1)],
            num_res_units=num_res_units,
            act=act,
        )

        if last_act is not None:
            self.last_act = monai.networks.layers.utils.get_act_layer(last_act)
        else:
            self.last_act = lambda x: x

        self.depth = Convolution(
            spatial_dims=spatial_dims,
            in_channels=in_channels,
            out_channels=1,
            strides=1,
            kernel_size=1,
            act="sigmoid",
        )

        self.log_depth = Convolution(
            spatial_dims=spatial_dims,
            in_channels=in_channels,
            out_channels=1,
            strides=1,
            kernel_size=1,
            act="sigmoid",
        )

    def forward(self, x):
        x = self.unet(x)
        x = self.last_act(x)
        conv1 = self.depth(x)
        y = self.log_depth(conv1)
        return y


class DWinference:
    def __init__(self, mode):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print("Device: ", self.device)
        if mode == "3D":
            self.model_path = get_asset("MicroCTEnv/deep_ws_3d/model.pth")
        elif mode == "2D":
            self.model_path = get_asset("ThinSectionEnv/deep_ws_2d/model.pth")

    def _prepare_sample(self, img):
        sample = {}
        sample["data"] = torch.as_tensor(img.astype(np.float32), device=self.device).unsqueeze(dim=0)
        return sample

    def run_model(self, img):
        """Read input volumes"""
        sample = self._prepare_sample(img)
        saved_model = torch.load(self.model_path)
        config = saved_model["config"]
        meta = config["meta"]
        model_params = config["model"].get("params", {})
        model_state_dict = saved_model["model_state_dict"]
        model = Deep_watershed_model(**model_params)
        model.load_state_dict(model_state_dict)
        input_roi_shape = meta["input_roi_shape"]
        pre_processed_inputs = "data"
        outputs = meta["outputs"]
        pre_processed_input_names = [pre_processed_inputs]
        output_names = list(outputs.keys())
        pre_processed_input_name = pre_processed_input_names[0]
        output_name = output_names[0]

        # create batch dimension for prediction
        batch = {name: tensor[None, ...] for name, tensor in sample.items()}

        for i in range(2):
            try:
                model = model.to(device=self.device)
                model.eval()
                with torch.no_grad():
                    batched_output = {
                        output_name: sliding_window_inference(
                            inputs=batch[pre_processed_input_name],
                            roi_size=input_roi_shape,
                            sw_batch_size=30,
                            predictor=model,
                            mode="gaussian",
                            progress=False,
                            sw_device=self.device,
                        ),
                    }
                    batched_inference = batched_output[output_name]
                break
            except RuntimeError as e:
                print(e)
                print("PyTorch is not able to use GPU: falling back to CPU.")
                self.device = "cpu"

        # remove batch and channel dimensions
        output = batched_inference.detach()[0, 0, ...]
        output = output.detach().cpu().numpy()

        return output
