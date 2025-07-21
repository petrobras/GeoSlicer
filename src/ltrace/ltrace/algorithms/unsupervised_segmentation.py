"""
Based on Asako Kanezaki. "Unsupervised Image Segmentation by Backpropagation."
IEEE International Conference on Acoustics, Speech and Signal Processing (ICASSP), 2018.
https://github.com/kanezaki/pytorch-unsupervised-segmentation
MIT License

Copyright (c) 2018 Asako Kanezaki

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Optimized by https://github.com/Yonv1943/Unsupervised-Segmentation
"""

import time
import argparse
from pathlib import Path
from typing import List, Tuple, Optional, Generator
from dataclasses import dataclass

import cv2
import numpy as np
from skimage import segmentation
import torch
import torch.nn as nn


@dataclass
class Config:
    """Configuration parameters for the segmentation algorithm."""

    input_channels: int
    train_epoch: int = 64
    mod_dim1: int = 64
    mod_dim2: int = 32
    min_label_num: int = 5
    max_label_num: int = 256


class SegmentationNetwork(nn.Module):
    """Neural network for image segmentation with a simple CNN architecture."""

    def __init__(self, inp_dim: int, mod_dim1: int, mod_dim2: int):
        super().__init__()

        self.seq = nn.Sequential(
            nn.Conv2d(inp_dim, mod_dim1, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(mod_dim1),
            nn.ReLU(inplace=True),
            nn.Conv2d(mod_dim1, mod_dim2, kernel_size=1, stride=1, padding=0),
            nn.BatchNorm2d(mod_dim2),
            nn.ReLU(inplace=True),
            nn.Conv2d(mod_dim2, mod_dim1, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(mod_dim1),
            nn.ReLU(inplace=True),
            nn.Conv2d(mod_dim1, mod_dim2, kernel_size=1, stride=1, padding=0),
            nn.BatchNorm2d(mod_dim2),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.seq(x)


def _preprocess_image_for_training(
    image1: np.ndarray, image2: Optional[np.ndarray] = None
) -> Tuple[torch.Tensor, List[np.ndarray]]:
    """
    Creates initial segmentation (superpixels) and prepares image tensor for network input.

    Args:
        image1: First input image (resized) as numpy array (H, W, 3).
        image2: Second input image (resized) as numpy array (H, W, 3) (optional for 6-channel mode).

    Returns:
        A tuple containing:
        - Processed image tensor (1, C, H, W).
        - A list of numpy arrays, where each array contains pixel indices belonging to an initial superpixel.
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    seg_map = segmentation.felzenszwalb(image1, scale=10, sigma=0.5, min_size=20)
    seg_map_flat = seg_map.flatten()

    seg_indices: List[np.ndarray] = []
    if seg_map_flat.size > 0:
        sidx = np.argsort(seg_map_flat)
        sorted_seg_map_flat = seg_map_flat[sidx]
        unique_sorted_labels, split_idx = np.unique(sorted_seg_map_flat, return_index=True)
        seg_indices = list(np.split(sidx, split_idx[1:]))

    tensor_image1 = image1.transpose((2, 0, 1)).astype(np.float32) / 255.0

    if image2 is not None:
        tensor_image2 = image2.transpose((2, 0, 1)).astype(np.float32) / 255.0
        tensor_image = np.concatenate([tensor_image1, tensor_image2], axis=0)
    else:
        tensor_image = tensor_image1

    tensor_image = tensor_image[np.newaxis, :, :, :]
    tensor_image = torch.from_numpy(tensor_image).to(device)

    return tensor_image, seg_indices


def _resize_images_if_needed(
    original_image1: np.ndarray, original_image2: Optional[np.ndarray] = None, max_dim: int = 2048
) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """
    Resizes images if necessary to a maximum dimension, maintaining aspect ratio.
    Also checks if dimensions match for two-image input.

    Args:
        original_image1: The first image as a numpy array.
        original_image2: The second image as a numpy array (or None).
        max_dim: Maximum dimension (height or width) for the processed image.

    Returns:
        A tuple containing:
        - resized_image1: The first image, potentially downsampled.
        - resized_image2: The second image, potentially downsampled (or None).

    Raises:
        ValueError: If image dimensions do not match in 6-channel mode.
    """
    if original_image2 is not None:
        if original_image1.shape != original_image2.shape:
            raise ValueError(
                f"Image dimensions do not match. Image1: {original_image1.shape}, Image2: {original_image2.shape}"
            )

    resized_image1 = original_image1
    resized_image2 = original_image2

    if original_image1.shape[0] > max_dim or original_image1.shape[1] > max_dim:
        h, w = original_image1.shape[0], original_image1.shape[1]

        if h > w:
            new_h = max_dim
            new_w = round(max_dim * w / h)
        else:
            new_w = max_dim
            new_h = round(max_dim * h / w)

        resized_image1 = cv2.resize(original_image1, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        if original_image2 is not None:
            resized_image2 = cv2.resize(original_image2, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    return resized_image1, resized_image2


class ProgressStatus:
    """
    Represents the current progress status of the segmentation pipeline.
    """

    def __init__(
        self,
        message: str,
        labelmap: Optional[np.ndarray] = None,
        colormap: Optional[np.ndarray] = None,
    ):
        self.message = message
        self.labelmap = labelmap
        self.colormap = colormap


def _perform_unsupervised_segmentation(
    config: Config, resized_image1: np.ndarray, resized_image2: Optional[np.ndarray]
) -> Generator[ProgressStatus, None, Tuple[np.ndarray, np.ndarray]]:
    """
    Performs the unsupervised segmentation using the CNN model.
    Yields ProgressStatus objects for each epoch, and returns the final labelmap and colormap.
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    tensor_image, seg_indices = _preprocess_image_for_training(resized_image1, resized_image2)

    model = SegmentationNetwork(
        inp_dim=config.input_channels,
        mod_dim1=config.mod_dim1,
        mod_dim2=config.mod_dim2,
    ).to(device)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=5e-2)

    H, W, _ = resized_image1.shape
    image_flatten1 = resized_image1.reshape((-1, 3))
    image_flatten2 = resized_image2.reshape((-1, 3)) if resized_image2 is not None else None

    # Keep track of the result with the minimum number of labels and best loss
    min_n_labels = float("inf")
    best_loss_at_min_labels = float("inf")
    best_labelmap = None
    best_colormap = None

    model.train()

    for epoch in range(config.train_epoch):
        optimizer.zero_grad()
        output = model(tensor_image)[0]
        output_reshaped = output.permute(1, 2, 0).view(-1, config.mod_dim2)
        pixel_labels_np_current = torch.argmax(output_reshaped, 1).data.cpu().numpy().astype(np.uint8)

        for indices in seg_indices:
            if indices.size > 0:
                sub_array = pixel_labels_np_current[indices]
                if sub_array.size > 0:
                    counts = np.bincount(sub_array, minlength=config.mod_dim2)
                    pixel_labels_np_current[indices] = np.argmax(counts)

        pixel_labels_np_latest = pixel_labels_np_current
        target_labels = torch.from_numpy(pixel_labels_np_latest).to(device)
        loss = criterion(output_reshaped, target_labels)
        loss.backward()
        optimizer.step()

        unique_labels_epoch, label_inverse_map_epoch = np.unique(pixel_labels_np_latest, return_inverse=True)
        label_inverse_map_epoch = label_inverse_map_epoch.astype(np.uint8)
        num_unique_labels_epoch = unique_labels_epoch.shape[0]

        if num_unique_labels_epoch < config.min_label_num:
            print(
                f"Stopping at epoch {epoch}: Number of labels ({num_unique_labels_epoch}) "
                f"is below the minimum required ({config.min_label_num}). "
                f"Using best result from a previous epoch."
            )
            break

        counts_for_epoch_colormap = np.bincount(label_inverse_map_epoch, minlength=num_unique_labels_epoch)
        epoch_colormap = np.zeros((num_unique_labels_epoch, 3), dtype=int)

        flat_images = [image_flatten1]
        if image_flatten2 is not None:
            flat_images.append(image_flatten2)

        for i in range(num_unique_labels_epoch):
            if counts_for_epoch_colormap[i] > 0:
                avg_colors_for_segment = []
                for img_flat in flat_images:
                    sum_r = np.bincount(
                        label_inverse_map_epoch, weights=img_flat[:, 0], minlength=num_unique_labels_epoch
                    )[i]
                    sum_g = np.bincount(
                        label_inverse_map_epoch, weights=img_flat[:, 1], minlength=num_unique_labels_epoch
                    )[i]
                    sum_b = np.bincount(
                        label_inverse_map_epoch, weights=img_flat[:, 2], minlength=num_unique_labels_epoch
                    )[i]
                    avg_colors_for_segment.append(np.array([sum_r, sum_g, sum_b]) / counts_for_epoch_colormap[i])
                epoch_colormap[i] = np.mean(avg_colors_for_segment, axis=0).astype(int)
            else:
                epoch_colormap[i] = [128, 128, 128]

        if num_unique_labels_epoch < min_n_labels or (
            num_unique_labels_epoch == min_n_labels and loss.item() < best_loss_at_min_labels
        ):
            min_n_labels = num_unique_labels_epoch
            best_loss_at_min_labels = loss.item()
            best_labelmap = label_inverse_map_epoch.reshape(H, W)
            best_colormap = epoch_colormap.astype(np.uint8)

        yield ProgressStatus(
            message=f"Epoch: {epoch:02d}, Loss: {loss.item():.4f}, Labels: {num_unique_labels_epoch}",
            labelmap=label_inverse_map_epoch.reshape(H, W),
            colormap=epoch_colormap.astype(np.uint8),
        )

    return best_labelmap, best_colormap


def _upsample_segmentation_results(
    downsampled_labelmap: np.ndarray, colormap: np.ndarray, original_image1: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Upsamples the downsampled labelmap to the original image resolution
    using guided filtering and maps labels to colors.
    """
    orig_h, orig_w = original_image1.shape[0], original_image1.shape[1]
    downsampled_h, downsampled_w = downsampled_labelmap.shape[0], downsampled_labelmap.shape[1]

    # Calculate guided filter radius dynamically based on downsampling ratio
    guided_filter_radius = round(orig_h / downsampled_h * 1.0)
    guided_filter_radius = max(1, guided_filter_radius)

    num_labels = colormap.shape[0]
    upscaled_label_probabilities = np.zeros((num_labels, orig_h, orig_w), dtype=np.float32)

    for label_idx in range(num_labels):
        label_mask_downsampled = (downsampled_labelmap == label_idx).astype(np.uint8) * 255
        label_mask_resized = cv2.resize(label_mask_downsampled, (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)
        filtered_mask = cv2.ximgproc.guidedFilter(
            original_image1, label_mask_resized, radius=guided_filter_radius, eps=(0.3 * 255) ** 2
        )
        upscaled_label_probabilities[label_idx] = filtered_mask / 255.0

    final_upsampled_labelmap_guided = np.argmax(upscaled_label_probabilities, axis=0).astype(np.uint8)

    return final_upsampled_labelmap_guided, colormap


def segment_image(
    original_image1: np.ndarray,
    original_image2: Optional[np.ndarray] = None,
    train_epoch: int = 64,
    mod_dim1: int = 64,
    mod_dim2: int = 32,
    min_label_num: int = 3,
    max_label_num: int = 256,
    processing_resolution: int = 2048,
) -> Generator[ProgressStatus, None, Tuple[np.ndarray, np.ndarray]]:
    """
    Main pipeline function to perform unsupervised image segmentation.
    This orchestrates image resizing, segmentation, and upsampling.
    Yields ProgressStatus objects during the segmentation training phase.

    Args:
        original_image1: First input image as a NumPy array.
        original_image2: Optional second input image for 6-channel mode.
        train_epoch: Number of training epochs.
        mod_dim1: Dimension 1 for the segmentation network.
        mod_dim2: Dimension 2 for the segmentation network.
        min_label_num: Minimum number of labels for early stopping.
        max_label_num: Maximum number of labels for early stopping.
        resize_max_dim: Maximum dimension for resizing input images.

    Yields:
        ProgressStatus: Current status during the segmentation process.

    Returns:
        A tuple containing:
        - final_rgb_image_guided: The final segmented RGB image (full resolution) with guided filter upsampling.
        - final_rgb_image_nearest: The final segmented RGB image (full resolution) with nearest neighbor upsampling.
    """
    input_channels = 6 if original_image2 is not None else 3
    config = Config(
        input_channels=input_channels,
        train_epoch=train_epoch,
        mod_dim1=mod_dim1,
        mod_dim2=mod_dim2,
        min_label_num=min_label_num,
        max_label_num=max_label_num,
    )

    resized_image1, resized_image2 = _resize_images_if_needed(
        original_image1, original_image2, max_dim=processing_resolution
    )
    yield ProgressStatus("Images validated and resized (if needed).")

    downsampled_labelmap, colormap = yield from _perform_unsupervised_segmentation(
        config, resized_image1, resized_image2
    )
    return _upsample_segmentation_results(downsampled_labelmap, colormap, original_image1)


if __name__ == "__main__":
    """This file can be used as a standalone script for debugging"""

    parser = argparse.ArgumentParser(description="Unsupervised image segmentation using a CNN.")
    parser.add_argument(
        "input_image_path",
        type=str,
        help="Path to the first input image (e.g., 'image/woof.jpg').",
    )
    parser.add_argument(
        "--second_image_path",
        type=str,
        default=None,
        help="Optional path to a second input image for 6-channel mode.",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="output",
        help="Directory to save the segmented images.",
    )
    # Add arguments for algorithm parameters
    parser.add_argument("--train_epoch", type=int, default=64)
    parser.add_argument("--mod_dim1", type=int, default=64)
    parser.add_argument("--mod_dim2", type=int, default=32)
    parser.add_argument("--min_label_num", type=int, default=3)
    parser.add_argument("--max_label_num", type=int, default=256)
    parser.add_argument("--resize_max_dim", type=int, default=2048)

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    final_rgb_image_guided = None
    final_rgb_image_nearest = None

    cv2.namedWindow("Segmentation Progress", cv2.WINDOW_AUTOSIZE)

    img1_np = cv2.imread(args.input_image_path)
    img2_np = cv2.imread(args.second_image_path) if args.second_image_path else None

    pipeline_generator = segment_image(
        img1_np,
        img2_np,
        train_epoch=args.train_epoch,
        mod_dim1=args.mod_dim1,
        mod_dim2=args.mod_dim2,
        min_label_num=args.min_label_num,
        max_label_num=args.max_label_num,
        processing_resolution=args.resize_max_dim,
    )

    try:
        while True:
            status = next(pipeline_generator)
            print(f"Progress: {status.message}")
            if status.labelmap is not None and status.colormap is not None:
                display_image = status.colormap[status.labelmap]
                cv2.imshow("Segmentation Progress", display_image)
                if cv2.waitKey(10) & 0xFF == ord("q"):
                    print("Quitting early due to user input.")
                    break
    except StopIteration as e:
        final_rgb_image_guided, final_rgb_image_nearest = e.value
    finally:
        cv2.destroyAllWindows()

    if final_rgb_image_guided is not None and final_rgb_image_nearest is not None:
        input_stem = Path(args.input_image_path).stem
        time_str = f"{int(time.time())}"

        if args.second_image_path:
            second_stem = Path(args.second_image_path).stem
            output_filename_guided = f"seg_guided_{input_stem}_{second_stem}_{time_str}.png"
            output_filename_nearest = f"seg_nearest_{input_stem}_{second_stem}_{time_str}.png"
        else:
            output_filename_guided = f"seg_guided_{input_stem}_{time_str}.png"
            output_filename_nearest = f"seg_nearest_{input_stem}_{time_str}.png"

        output_path_guided = output_dir / output_filename_guided
        output_path_nearest = output_dir / output_filename_nearest

        cv2.imwrite(str(output_path_guided), final_rgb_image_guided)
        print(f"Result (guided upsample) saved to {output_path_guided}")

        cv2.imwrite(str(output_path_nearest), final_rgb_image_nearest)
        print(f"Result (nearest upsample) saved to {output_path_nearest}")
