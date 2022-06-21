""" This module implements the PatchMatch algorithm for single channel, 3D images.
    https://gfx.cs.princeton.edu/pubs/Barnes_2009_PAR/patchmatch.pdf
"""

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage
from skimage import color
from typing import List, Tuple, Generator, Callable
from itertools import product


Coords = Tuple
Image = NDArray[np.float_]
Mask = NDArray[np.bool_]


class RecursiveProgress:
    def __init__(self, callback: Callable[[float], None]):
        self._step_sizes = [100]
        self._progress = 0
        self._callback = callback

    def next_substep(self):
        self._progress += self._step_sizes[-1]
        self._callback(self._progress)

    def add_step(self, n_substeps):
        self._step_sizes.append(self._step_sizes[-1] / n_substeps)

    def end_step(self):
        self._step_sizes.pop()


class PatchMatch:
    def __init__(
        self,
        patch_size: int = 9,
        stride: int = 7,
        margin: int = 3,
        random_samples: int = 64,
        n_levels: int = 4,
        n_iters: int = 6,
        blend_sigma: float = 0.8,
        blend_dilation: int = 3,
        similarity_by_mean: bool = False,
        callback_every: int = 5,
        progress_callback: Callable[[float], None] = lambda x: None,
    ):
        """Sets constant parameters for the algorithm.
        patch_size: size of the cubic patch
        stride: distance between patches when going through holes
        margin: max distance between a patch and a hole
        random_samples: how many samples will be considered each iteration
                        of random search
        n_iters: how many iterations will run each pass
        blend_sigma: sigma used to gaussian blur the bool mask
                     into a soft blending mask
        blend_dilation: how much to dilate the soft blending mask
        similarity_by_mean: compute patch similarity using mean color difference
                            if True, otherwise use sum of square differences
        callback_every: how often to call the progress callback
        progress_callback: function to call with progress percentage
        """
        self.patch_size = patch_size
        self.stride = stride
        self.margin = margin
        self.random_samples = random_samples
        self.n_levels = n_levels
        self.n_iters = n_iters
        self.blend_sigma = blend_sigma
        self.blend_dilation = blend_dilation
        self.similarity_by_mean = similarity_by_mean
        self.callback_every = callback_every
        self.progress = RecursiveProgress(progress_callback)

    def create_weight_filter(self) -> Image:
        """Weight filter for blending patches softly.
        The greatest weight is at the center of the filter."""
        weight_filter = np.ones((self.patch_size,) * self.ndim)
        middle = np.array([self.patch_size // 2] * self.ndim)
        max_distance = self.patch_size * 0.5 * (self.ndim**0.5)
        ranges = (range(self.patch_size),) * self.ndim
        for offset in product(*ranges):
            offset = np.array(offset)
            index_distance = np.linalg.norm(offset - middle)
            offset = tuple(offset)
            weight_filter[offset] = ((max_distance * 2) / (index_distance + max_distance)) - 0.95

        # Make filter more pronounced
        weight_filter **= 2

        # Normalize
        weight_filter /= weight_filter.mean()

        return weight_filter

    def patch_offsets(self, pos_shape: Coords) -> Generator[Coords, None, None]:
        """Generates all possible offsets to be considered for the whole image."""
        ranges = (range(0, dim, self.stride) for dim in pos_shape)
        max_ = np.array(pos_shape) - self.patch_size
        for offset in product(*ranges):
            yield tuple(np.minimum(offset, max_))

    def thicken_mask(self, mask: Mask) -> Mask:
        """Thickens the mask. The thick mask is True where a patch at that offset
        would overlap with the mask."""
        thick = np.full(mask.shape, False)
        start = -self.patch_size - 1
        end = self.patch_size
        for offset in self.patch_offsets(mask.shape):
            if mask[offset]:
                slices = tuple(slice(x + start, x + end) for x in offset)
                thick[slices] = True
        return thick

    def find_offsets_to_visit(self, mask: Mask) -> List[Coords]:
        """Returns a list of image offsets that have holes."""
        will_visit = np.full(mask.shape, False)
        leftovers = mask.copy()
        offsets = []
        for offset in self.patch_offsets(mask.shape):
            will_visit[offset] = self.overlap(mask, offset, size=self.margin)
            if will_visit[offset]:
                self.patch_at_offset(leftovers, offset)[:] = False
        for offset in self.patch_offsets(mask.shape):
            will_visit[offset] |= self.overlap(leftovers, offset)
            if will_visit[offset]:
                offsets.append(offset)
                self.patch_at_offset(leftovers, offset)[:] = False
        return offsets

    def blend_patches(
        self, from_image: Image, from_weights: Image, to_image: Image, to_weights: Image
    ) -> Tuple[Image, Image]:
        """Blends two (image, weights) pair together.
        The contribution of each image is proportional to its weights."""
        from_weights = self.add_color_dim(from_weights)
        to_weights = self.add_color_dim(to_weights)
        res_weights = from_weights + to_weights
        res_image = (from_image * from_weights + to_image * to_weights) / res_weights
        return res_image, res_weights.squeeze()

    def patch_at_offset(self, image: Image, offset: Coords) -> Image:
        """Returns the patch at the given offset.
        The offset is the topmost, leftmost corner of the patch."""
        slices = tuple(slice(x, x + self.patch_size) for x in offset)
        return image[slices]

    def random_nnf(self, pos_shape: Coords) -> NDArray[np.int_]:
        """Returns a random nearest-neighbor field for initialization."""
        offsets = np.array([np.random.randint(0, dim - self.patch_size, pos_shape) for dim in pos_shape])
        axes = np.arange(self.ndim + 1) + 1
        axes[-1] = 0
        return np.transpose(offsets, axes=axes)

    def overlap(self, mask: Mask, offset: Coords, size: int = 0) -> bool:
        """Returns true if the patch at the given offset overlaps with the mask."""
        size = size or self.patch_size
        return np.any(self.patch_at_offset(mask, offset))

    def patch_similarity_mean(
        self,
        hole_patch: Image,
        zeroes_patch: Image,
        image_patch: Image,
        hole_mean,
        image_mean,
    ) -> float:
        """Returns the similarity of two patches by mean color difference only.
        Pixels that are zero in the zeroes_patch are ignored."""
        mean_diff = np.square(hole_mean - image_mean)
        return 1 / (np.sum(mean_diff) * self.similarity_by_mean + 0.00001)

    def patch_similarity_ssd(
        self,
        hole_patch: Image,
        zeroes_patch: Image,
        image_patch: Image,
        hole_mean,
        image_mean,
    ) -> float:
        """Returns the similarity of two patches by sum of squared differences.
        Pixels that are zero in the zeroes_patch are ignored."""
        diff = np.square((image_patch - hole_patch) * zeroes_patch)
        return 1 / (np.sum(diff) * self.diff_mul + 0.00001)

    def random_offsets(self, size: int, pos_shape: Coords, center: Coords) -> NDArray[np.int_]:
        """Returns an array of random offsets around a center offset,
        with radius exponentially decreasing."""
        pos_shape = np.array([pos_shape]) - self.patch_size
        uniform_offset = np.array([center]) / pos_shape
        uniform = np.random.random((size, self.ndim)) - uniform_offset
        exp_factor = np.power(0.5, np.arange(4, step=(4 / size)))[:, np.newaxis]
        direction = uniform * pos_shape * exp_factor * 0.5
        direction = direction.astype(int)
        return direction + center

    def add_color_dim(self, array):
        """If using color, adds a color dimension to an array
        for broadcasting operations."""
        return array[..., np.newaxis] if self.has_color else array

    def best_offset(
        self,
        offsets: NDArray[np.int_],
        patch: Image,
        patch_mean,
        mask_patch: Mask,
        image: Image,
        blur_image,
        mask: Mask,
    ) -> Tuple[Coords, float]:
        """Returns the offset whose patch has the highest similarity to the patch,
        along with the similarity value."""
        best_offset = None
        best_weight = -1
        mask_patch = self.add_color_dim(mask_patch.astype(float))

        for offset in offsets:
            offset = tuple(offset)
            if mask[offset]:
                weight = 0.001
            else:
                candidate_patch = self.patch_at_offset(image, offset)
                candidate_mean = blur_image[offset]
                weight = self.patch_similarity(
                    patch,
                    mask_patch,
                    candidate_patch,
                    patch_mean,
                    candidate_mean,
                )
            if weight > best_weight:
                best_offset = offset
                best_weight = weight
        return best_offset, best_weight

    def upscale_nnf(self, nnf: NDArray[np.int_]) -> NDArray[np.int_]:
        """Upscales the nearest-neighbor field."""
        expanded_shape = (1,) * self.ndim + (self.ndim,)
        downscale_broadcast = np.array(self.downscale_factors).reshape(expanded_shape)

        nnf = nnf * downscale_broadcast
        for axis, factor in enumerate(self.downscale_factors):
            nnf = nnf.repeat(factor, axis=axis)

        axes = np.arange(self.ndim + 1) + 1
        axes[-1] = 0

        indices = np.transpose(np.indices(nnf.shape[:-1]), axes=axes)
        nnf += np.mod(indices, downscale_broadcast)
        return nnf

    def blur_image(self, image: Image, mask: Mask):
        """Blurs image by calculating the mean color of the patch at each offset.
        Hole pixels are ignored. Patches with no valid pixels are set to 0 and
        are not used."""
        mask = self.add_color_dim((~mask).astype(float))
        image = image * mask

        filter_shape = (self.patch_size,) * self.ndim
        if self.has_color:
            filter_shape += (1,)
        origin = -(self.patch_size // 2)
        image = ndimage.uniform_filter(image, filter_shape, origin=origin)
        mask = ndimage.uniform_filter(mask, filter_shape, origin=origin)
        mask[mask < 0.001] = 1.0

        result = image / mask

        # Remove numeric error
        result = np.clip(result, 0, 1)

        return result

    def inpaint_level(self, image: Image, mask: Mask, nnf: NDArray[np.int_], hole_weight: float):
        """Inpaints the image on a single scale level."""
        image = image.copy()
        nnf = nnf.copy()

        weights = np.ones(mask.shape, dtype=float) - mask * (1 - hole_weight)

        blur_image = self.blur_image(image, mask)
        thick_mask = self.thicken_mask(mask)
        offsets_to_visit = self.find_offsets_to_visit(mask)

        self.progress.add_step(self.n_iters)

        for i in range(self.n_iters):
            new_image = self.iterate(
                image,
                weights,
                blur_image,
                thick_mask,
                offsets_to_visit,
                nnf,
                reverse=(i % 2),
            )

        self.progress.end_step()

        return new_image, nnf

    def iterate(
        self,
        image: Image,
        weights: Image,
        blur_image: Image,
        thick_mask: Mask,
        offsets_to_visit: List[Coords],
        nnf: NDArray[np.int_],
        reverse: bool,
    ):
        """Performs one iteration of the inpainting algorithm,
        which consists of propagation and random search for each hole patch."""
        image = image.copy()
        weights = weights.copy()
        direction = (-1 if reverse else 1) * self.stride
        pos_shape = thick_mask.shape

        debug_score = 0.0
        debug_changed = 0
        debug_propagated = 0
        n_offsets = len(offsets_to_visit)

        if reverse:
            offsets_to_visit = reversed(offsets_to_visit)

        self.progress.add_step(n_offsets // self.callback_every)
        for offset_i, offset in enumerate(offsets_to_visit):
            # Propagate
            offsets = [nnf[offset]]
            debug_prev_offset = nnf[offset].copy()

            max_offset = np.array(pos_shape) - self.patch_size
            neighbor = np.array(offset) + direction
            neighbor = np.clip(neighbor, 0, max_offset)

            for i in range(self.ndim):
                of = list(offset)
                of[i] = neighbor[i]
                of = tuple(of)
                delta = np.zeros(self.ndim, dtype=int)
                delta[i] = direction
                offsets.append(np.clip(nnf[of] + delta, 0, max_offset))

            offsets = np.unique(np.array(offsets), axis=0)

            hole_patch = self.patch_at_offset(image, offset).copy()
            weights_patch = self.patch_at_offset(weights, offset)
            mask_patch = self.add_color_dim(weights_patch != 0.0)
            hole_mean = np.sum(hole_patch * mask_patch, axis=tuple(range(self.ndim))) / np.sum(mask_patch)

            new_offset, new_weight = self.best_offset(
                offsets,
                hole_patch,
                hole_mean,
                mask_patch,
                image,
                blur_image,
                thick_mask,
            )
            if not np.array_equal(debug_prev_offset, new_offset):
                debug_propagated += 1

            # Random search
            offsets = self.random_offsets(self.random_samples, pos_shape, new_offset)
            offsets = np.append([new_offset], offsets, axis=0)
            new_offset, new_weight = self.best_offset(
                offsets,
                hole_patch,
                hole_mean,
                mask_patch,
                image,
                blur_image,
                thick_mask,
            )

            # Update NNF
            nnf[offset] = new_offset

            # Update image and weights
            similar_patch = self.patch_at_offset(image, new_offset)
            image_patch = self.patch_at_offset(image, offset)

            image_patch[:], weights_patch[:] = self.blend_patches(
                image_patch,
                weights_patch,
                similar_patch,
                new_weight * self.weight_filter,
            )

            debug_score += new_weight

            if not np.array_equal(debug_prev_offset, new_offset):
                debug_changed += 1

            if offset_i % self.callback_every == self.callback_every - 1:
                self.progress.next_substep()

        self.progress.end_step()

        print(
            debug_score / (n_offsets * self.patch_size**3),
            debug_propagated,
            "/",
            debug_changed,
            "/",
            n_offsets,
        )

        return image

    def downscale(self, array: NDArray, downscale_factors: Coords):
        slices = tuple(slice(None, None, x) for x in downscale_factors)
        return array[slices]

    def upscale(self, array: NDArray, pos_shape: Coords) -> NDArray:
        for axis, factor in enumerate(self.downscale_factors):
            array = np.repeat(array, factor, axis=axis)
        array = array[tuple(slice(None, dim) for dim in pos_shape)]
        return array

    def blend(self, image_a: Image, image_b: Image, mask: Image) -> Image:
        mask = self.add_color_dim(mask)
        return image_a * mask + image_b * (1 - mask)

    def __call__(self, image: NDArray, mask: Mask):
        """Entry point, inpaints the image.
        image: original image
        mask: holes mask, where True values represent holes
        """
        original_shape = image.shape
        image = image.squeeze()
        mask = mask.squeeze()

        self.ndim = len(mask.shape)
        self.weight_filter = self.create_weight_filter()

        self.diff_mul = 1 / (self.patch_size**2)
        self.patch_similarity = self.patch_similarity_mean if self.similarity_by_mean else self.patch_similarity_ssd
        self.downscale_factors = (2,) * self.ndim

        original_type = image.dtype
        image = image.astype(float)
        mask = mask.astype(bool)

        image_min = np.min(image)
        image_max = np.max(image)
        image_range = image_max - image_min

        image -= image_min
        image /= image_range

        self.has_color = image.ndim > mask.ndim
        if self.has_color:
            image = color.rgb2lab(image)
            expanded_shape = (1,) * self.ndim + (3,)
            lab_min = np.array([0, -128, -128]).reshape(expanded_shape)
            lab_range = np.array([100, 255, 255]).reshape(expanded_shape)
            image -= lab_min
            image /= lab_range

        factors = tuple(2 ** (self.n_levels - 1) for x in self.downscale_factors)
        downscaled_shape = np.array(mask.shape) // factors
        nnf = self.random_nnf(downscaled_shape)

        self.progress.add_step(self.n_levels)

        infill, nnf = self.inpaint_level(self.downscale(image, factors), self.downscale(mask, factors), nnf, 0)

        for i in reversed(range(self.n_levels - 1)):
            factors = tuple(x**i for x in self.downscale_factors)
            downscaled_image = self.downscale(image, factors)
            downscaled_mask = self.downscale(mask, factors)
            infill = self.upscale(infill, downscaled_mask.shape)
            infill = self.blend(infill, downscaled_image, downscaled_mask)
            nnf = self.upscale_nnf(nnf)
            infill, nnf = self.inpaint_level(infill, self.downscale(mask, factors), nnf, 0.001)

        smooth_mask = ndimage.gaussian_filter(mask.astype(float), sigma=self.blend_sigma)
        smooth_mask = ndimage.grey_dilation(smooth_mask, size=(self.blend_dilation,) * self.ndim)
        smooth_mask = np.maximum(mask, smooth_mask)

        infill = self.blend(infill, image, smooth_mask)

        self.progress.end_step()

        if self.has_color:
            infill *= lab_range
            infill += lab_min
            infill = color.lab2rgb(infill)

        infill *= image_range
        infill += image_min

        return infill.astype(original_type).reshape(original_shape)
