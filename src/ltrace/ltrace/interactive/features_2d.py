"""Computing 2D feature planes, at full resolution and on a downsampled grid.

Every feature keeps full-resolution semantics whatever the preview factor, so one model
serves every zoom level and the full-image apply.
"""

import cv2
import numpy as np

from ltrace.interactive.ipc import FeatureIndex


# False restores cv2's exact 4-sigma kernels, at ~1.4x the cost.
GAUSSIAN_TRUNCATE_3SIGMA = True


def _gaussian_ksize(sigma):
    """Kernel size for cv2.GaussianBlur, truncated at 3 sigma, or (0, 0) to let cv2
    derive its default 4-sigma kernel."""
    if not GAUSSIAN_TRUNCATE_3SIGMA:
        return (0, 0)
    radius = max(1, int(round(3 * sigma)))
    size = 2 * radius + 1
    return (size, size)


def compute_features_2d(sample, feature_indices, scale):
    """Compute the selected features over a 2D sample of shape (h, w) or (h, w, c),
    one plane per channel. Returns float32 of shape (n_feature_planes, h, w)."""
    if sample.ndim == 2:
        sample = sample[:, :, np.newaxis]
    sample = np.ascontiguousarray(sample, dtype=np.float32)

    sample_sq = None
    # Gaussian cascade: blurring by sigma_a then sigma_b equals blurring once by
    # sqrt(sigma_a^2 + sigma_b^2), and sorted FeatureIndex order visits sigmas
    # ascending, so each larger gaussian is one small incremental blur.
    gauss_running = None
    gauss_prev_sigma = 0.0

    planes = []
    for index in sorted(feature_indices):
        feature = FeatureIndex(index)
        if feature == FeatureIndex.SOURCE:
            result = sample
        elif feature in scale.gaussian_sigmas:
            sigma = scale.gaussian_sigmas[feature]
            incremental_sigma = np.sqrt(sigma * sigma - gauss_prev_sigma * gauss_prev_sigma)
            base = sample if gauss_running is None else gauss_running
            ksize = _gaussian_ksize(incremental_sigma)
            gauss_running = cv2.GaussianBlur(base, ksize, sigmaX=incremental_sigma, sigmaY=incremental_sigma)
            gauss_prev_sigma = sigma
            result = gauss_running
        elif feature in scale.winvar_sizes:
            if sample_sq is None:
                sample_sq = sample * sample
            wlen = scale.winvar_sizes[feature]
            wmean = cv2.boxFilter(sample, -1, (wlen, wlen), borderType=cv2.BORDER_REFLECT)
            wsqmean = cv2.boxFilter(sample_sq, -1, (wlen, wlen), borderType=cv2.BORDER_REFLECT)
            result = wsqmean - wmean * wmean
        else:
            raise ValueError(f"Unsupported feature: {feature}")

        if result.ndim == 2:
            result = result[:, :, np.newaxis]
        for channel in range(result.shape[2]):
            planes.append(np.asarray(result[:, :, channel], dtype=np.float32))

    return np.stack(planes, axis=0)


def build_mean_pyramid(source, paths, scale, progress_callback=None):
    """2x2 mean pyramid of the source image as memmapped files, so the large-sigma
    gaussians can be evaluated without reading full-resolution neighborhoods."""
    image = source[0]
    pyramid = {}
    previous = image
    total_rows = sum(image.shape[0] // (2**level) for level in range(1, scale.pyramid_levels + 1))
    done_rows = 0
    dtype = np.uint8 if image.dtype == np.uint8 else np.float32
    for level in range(1, scale.pyramid_levels + 1):
        out_h, out_w = previous.shape[0] // 2, previous.shape[1] // 2
        if out_h < 2 or out_w < 2:
            break
        out = np.lib.format.open_memmap(
            str(paths.pyramid_level(level)), mode="w+", dtype=dtype, shape=(out_h, out_w) + image.shape[2:]
        )
        chunk = max(1, 4_000_000 // max(1, out_w))
        for block_start in range(0, out_h, chunk):
            block_end = min(out_h, block_start + chunk)
            block = np.asarray(previous[2 * block_start : 2 * block_end, : 2 * out_w])
            a, b = block[0::2, 0::2], block[0::2, 1::2]
            c, d = block[1::2, 0::2], block[1::2, 1::2]
            if dtype == np.uint8:
                out[block_start:block_end] = ((a.astype(np.uint16) + b + c + d + 2) >> 2).astype(np.uint8)
            else:
                out[block_start:block_end] = (a.astype(np.float32) + b + c + d) * 0.25
            done_rows += block_end - block_start
            if progress_callback:
                progress_callback(int(99 * done_rows / total_rows), "Preparing image pyramid...")
        out.flush()
        pyramid[level] = out
        previous = out
    return pyramid


def _gaussian_kernel(sigma, radius):
    return cv2.getGaussianKernel(2 * radius + 1, float(sigma)).ravel().astype(np.float32)


def _axis_selector(centers, offset, size):
    """Selector for `centers + offset` along one axis: a slice when the positions are
    uniform and in bounds (strided memmap reads), index arrays otherwise."""
    indices = centers + offset
    if indices[0] >= 0 and indices[-1] < size:
        if indices.size == 1:
            return slice(int(indices[0]), int(indices[0]) + 1)
        steps = np.diff(indices)
        step = int(steps[0])
        if step > 0 and np.all(steps == step):
            return slice(int(indices[0]), int(indices[-1]) + 1, step)
    return np.clip(indices, 0, size - 1)


def sampled_features_2d(source, pyramid, i0, j0, out_w, out_h, factor, feature_indices, scale):
    """Features at the downsampled grid (i0 + n*factor, j0 + m*factor) without reading
    the full image. SOURCE, the sigma-1 gaussian and the window variances are exact,
    accumulated from their true full-resolution neighborhoods; the larger gaussians are
    approximated from the mean pyramid (~1% error).
    """
    height, width = source.shape[1], source.shape[2]
    image = source[0]
    rows = j0 + np.arange(out_h, dtype=np.int64) * factor
    cols = i0 + np.arange(out_w, dtype=np.int64) * factor

    selected = [FeatureIndex(index) for index in sorted(feature_indices)]
    winvars = [scale.winvar_sizes[feature] for feature in selected if feature in scale.winvar_sizes]
    has_source = FeatureIndex.SOURCE in selected
    has_g1 = FeatureIndex.GAUSSIAN_A in selected

    plane_shape = (out_h, out_w) + image.shape[2:]
    results = {}

    # Exact pass over the full-resolution image
    g1_radius = 4 * scale.gaussian_sigmas[FeatureIndex.GAUSSIAN_A]  # matches cv2's kernel radius
    base_radius = max([0] + ([g1_radius] if has_g1 else []) + [w // 2 for w in winvars])
    if has_source or has_g1 or winvars:
        g1_kernel = _gaussian_kernel(scale.gaussian_sigmas[FeatureIndex.GAUSSIAN_A], g1_radius) if has_g1 else None
        g1_acc = np.zeros(plane_shape, dtype=np.float32) if has_g1 else None
        sums = {w: np.zeros(plane_shape, dtype=np.float32) for w in winvars}
        square_sums = {w: np.zeros(plane_shape, dtype=np.float32) for w in winvars}
        square_buffer = np.empty(plane_shape, dtype=np.float32)
        column_selectors = {di: _axis_selector(cols, di, width) for di in range(-base_radius, base_radius + 1)}

        for dj in range(-base_radius, base_radius + 1):
            row_block = image[_axis_selector(rows, dj, height)]
            for di in range(-base_radius, base_radius + 1):
                use_g1 = has_g1 and abs(dj) <= g1_radius and abs(di) <= g1_radius
                use_winvars = [w for w in winvars if abs(dj) <= w // 2 and abs(di) <= w // 2]
                use_source = has_source and dj == 0 and di == 0
                if not (use_g1 or use_winvars or use_source):
                    continue

                shifted = np.asarray(row_block[:, column_selectors[di]], dtype=np.float32)
                if use_source:
                    results[FeatureIndex.SOURCE] = shifted.copy()
                if use_winvars:
                    np.multiply(shifted, shifted, out=square_buffer)
                    for w in use_winvars:
                        np.add(sums[w], shifted, out=sums[w])
                        np.add(square_sums[w], square_buffer, out=square_sums[w])
                if use_g1:
                    # `shifted` is a private copy at this point; scale it in place
                    shifted *= g1_kernel[dj + g1_radius] * g1_kernel[di + g1_radius]
                    np.add(g1_acc, shifted, out=g1_acc)

        if has_g1:
            results[FeatureIndex.GAUSSIAN_A] = g1_acc
        for feature in selected:
            if feature in scale.winvar_sizes:
                w = scale.winvar_sizes[feature]
                mean = sums[w] / (w * w)
                results[feature] = square_sums[w] / (w * w) - mean * mean

    # Pyramid pass for the band-limited gaussians
    for feature in selected:
        level = scale.gaussian_pyramid_level.get(feature)
        if level is None:
            continue
        level_image = pyramid[level]
        level_h, level_w = level_image.shape[0], level_image.shape[1]
        level_factor = 2**level
        sigma = scale.gaussian_sigmas[feature]
        # 2x2 mean pooling acts as a box filter; remove its variance from the target sigma
        box_variance = (level_factor * level_factor - 1) / 12.0
        sigma_level = np.sqrt(sigma * sigma - box_variance) / level_factor
        radius = max(1, int(np.ceil(3 * sigma_level)))
        kernel = _gaussian_kernel(sigma_level, radius)
        center_offset = (level_factor - 1) / 2.0
        level_rows = np.round((rows - center_offset) / level_factor).astype(np.int64)
        level_cols = np.round((cols - center_offset) / level_factor).astype(np.int64)

        accumulator = np.zeros(plane_shape, dtype=np.float32)
        column_selectors = {di: _axis_selector(level_cols, di, level_w) for di in range(-radius, radius + 1)}
        for dj in range(-radius, radius + 1):
            row_block = level_image[_axis_selector(level_rows, dj, level_h)]
            for di in range(-radius, radius + 1):
                shifted = np.asarray(row_block[:, column_selectors[di]], dtype=np.float32)
                shifted *= kernel[dj + radius] * kernel[di + radius]
                np.add(accumulator, shifted, out=accumulator)
        results[feature] = accumulator

    planes = []
    for feature in selected:
        result = results[feature]
        if result.ndim == 2:
            result = result[:, :, np.newaxis]
        for channel in range(result.shape[2]):
            planes.append(result[:, :, channel])
    return np.stack(planes, axis=0)
