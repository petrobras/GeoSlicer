import datetime
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import numba
import numpy as np
from scipy.ndimage import gaussian_filter1d


@numba.njit(fastmath=True, nogil=True)
def _get_radial_scale(x, y, cx, cy):
    dx = x.astype(np.float64) - cx
    dy = y.astype(np.float64) - cy
    radius = np.sqrt(dx * dx + dy * dy)
    scale = np.max(radius)

    if not np.isfinite(scale) or scale < 1.0:
        scale = 1.0

    return scale


@numba.njit(fastmath=True, nogil=True)
def _solve_radial_stable_kernel(x, y, values, cx, cy, polynomial_order, regularization=False):
    radius_scale = _get_radial_scale(x, y, cx, cy)
    n = x.shape[0]

    xn = (x.astype(np.float64) - cx) / radius_scale
    yn = (y.astype(np.float64) - cy) / radius_scale
    r2 = xn * xn + yn * yn

    if polynomial_order == 2:
        n_coef = 4
    elif polynomial_order == 4:
        n_coef = 5
    else:
        n_coef = 6

    design = np.empty((n, n_coef), dtype=np.float64)
    design[:, 0] = 1.0
    design[:, 1] = xn
    design[:, 2] = yn
    design[:, 3] = r2

    if n_coef >= 5:
        r4 = r2 * r2
        design[:, 4] = r4
        if n_coef >= 6:
            design[:, 5] = r4 * r2

    vals = values.astype(np.float64)

    if regularization:
        reg_matrix = np.eye(n_coef, dtype=np.float64) * 1e-8
        reg_matrix[0, 0] = 0.0

        design_aug = np.empty((n + n_coef, n_coef), dtype=np.float64)
        design_aug[:n, :] = design
        design_aug[n:, :] = reg_matrix

        vals_aug = np.zeros(n + n_coef, dtype=np.float64)
        vals_aug[:n] = vals

        res = np.linalg.lstsq(design_aug, vals_aug)
    else:
        res = np.linalg.lstsq(design, vals)

    coefficients = res[0]
    singular_values = res[3]

    if len(singular_values) == 0:
        condition_number = np.inf
    else:
        smallest = singular_values[-1]
        if smallest <= 0:
            condition_number = np.inf
        else:
            condition_number = singular_values[0] / smallest

    fitted = design @ coefficients
    residual = fitted - vals
    error = np.mean(residual * residual)

    return coefficients, radius_scale, error, condition_number


@numba.njit(fastmath=True, nogil=True)
def _search_radial_center(x, y, values, initial_cx, initial_cy, polynomial_order, nx, ny):
    cx = float(initial_cx)
    cy = float(initial_cy)
    step = max(2.0, min(nx, ny) * 0.08)

    for _ in range(4):
        best_error = np.inf
        best_cx = cx
        best_cy = cy

        for dx in (-step, 0.0, step):
            for dy in (-step, 0.0, step):
                test_cx = cx + dx
                test_cy = cy + dy

                if test_cx < -0.10 * nx:
                    test_cx = -0.10 * nx
                elif test_cx > 1.10 * nx:
                    test_cx = 1.10 * nx

                if test_cy < -0.10 * ny:
                    test_cy = -0.10 * ny
                elif test_cy > 1.10 * ny:
                    test_cy = 1.10 * ny

                try:
                    _, _, error, cond = _solve_radial_stable_kernel(
                        x, y, values, test_cx, test_cy, polynomial_order, False
                    )
                    if not np.isfinite(error) or not np.isfinite(cond):
                        error = np.inf
                except Exception:
                    error = np.inf

                if error < best_error:
                    best_error = error
                    best_cx = test_cx
                    best_cy = test_cy

        cx = best_cx
        cy = best_cy
        step *= 0.35

    return cx, cy


@numba.njit(fastmath=True, nogil=True)
def _evaluate_radial_model(nx, ny, cx, cy, coefficients, polynomial_order, radius_scale):
    x = (np.arange(nx, dtype=np.float64) - cx) / radius_scale
    y = (np.arange(ny, dtype=np.float64) - cy) / radius_scale

    shading = np.empty((nx, ny), dtype=np.float64)
    c0 = coefficients[0]
    c1 = coefficients[1]
    c2 = coefficients[2]
    c3 = coefficients[3]
    has_c4 = polynomial_order >= 4
    c4 = coefficients[4] if has_c4 else 0.0
    has_c5 = polynomial_order >= 6
    c5 = coefficients[5] if has_c5 else 0.0

    for i in range(nx):
        xi = x[i]
        xi2 = xi * xi
        for j in range(ny):
            yj = y[j]
            yj2 = yj * yj
            r2 = xi2 + yj2
            val = c0 + c1 * xi + c2 * yj + c3 * r2
            if has_c4:
                r4 = r2 * r2
                val += c4 * r4
                if has_c5:
                    val += c5 * r4 * r2
            shading[i, j] = val

    return shading


@numba.njit(fastmath=True, nogil=True)
def _fit_cartesian_slice_kernel(x_data, y_data, z_data, polynomial_order, nx, ny):
    n = x_data.shape[0]
    xb = x_data.astype(np.float64) * 0.01
    yd = y_data.astype(np.float64) * 0.01

    xb2 = xb * xb
    yd2 = yd * yd

    if polynomial_order == 2:
        n_coef = 6
        design = np.empty((n, 6), dtype=np.float64)
        design[:, 0] = 1.0
        design[:, 1] = xb
        design[:, 2] = yd
        design[:, 3] = xb2
        design[:, 4] = yd2
        design[:, 5] = xb * yd
    elif polynomial_order == 4:
        n_coef = 8
        design = np.empty((n, 8), dtype=np.float64)
        design[:, 0] = 1.0
        design[:, 1] = xb
        design[:, 2] = yd
        design[:, 3] = xb2
        design[:, 4] = yd2
        design[:, 5] = xb * yd
        design[:, 6] = xb2 * xb2
        design[:, 7] = yd2 * yd2
    else:
        n_coef = 10
        design = np.empty((n, 10), dtype=np.float64)
        design[:, 0] = 1.0
        design[:, 1] = xb
        design[:, 2] = yd
        design[:, 3] = xb2
        design[:, 4] = yd2
        design[:, 5] = xb * yd
        design[:, 6] = xb2 * xb2
        design[:, 7] = yd2 * yd2
        design[:, 8] = xb2 * xb2 * xb2
        design[:, 9] = yd2 * yd2 * yd2

    res = np.linalg.lstsq(design, z_data.astype(np.float64))
    coefficients = res[0]

    x = np.arange(nx, dtype=np.float64) * 0.01
    y = np.arange(ny, dtype=np.float64) * 0.01

    shading = np.empty((nx, ny), dtype=np.float64)
    c0, c1, c2, c3, c4, c5 = (
        coefficients[0],
        coefficients[1],
        coefficients[2],
        coefficients[3],
        coefficients[4],
        coefficients[5],
    )
    c6 = coefficients[6] if polynomial_order >= 4 else 0.0
    c7 = coefficients[7] if polynomial_order >= 4 else 0.0
    c8 = coefficients[8] if polynomial_order >= 6 else 0.0
    c9 = coefficients[9] if polynomial_order >= 6 else 0.0

    for i in range(nx):
        xi = x[i]
        xi2 = xi * xi
        xi4 = xi2 * xi2
        xi6 = xi4 * xi2
        for j in range(ny):
            yj = y[j]
            yj2 = yj * yj
            yj4 = yj2 * yj2
            yj6 = yj4 * yj2
            val = c0 + c1 * xi + c2 * yj + c3 * xi2 + c4 * yj2 + c5 * (xi * yj)
            if polynomial_order >= 4:
                val += c6 * xi4 + c7 * yj4
            if polynomial_order >= 6:
                val += c8 * xi6 + c9 * yj6
            shading[i, j] = val

    return shading


@numba.njit(parallel=True, fastmath=True, nogil=True)
def _fused_normalize_z_kernel(
    data_3d, mult, low_q_interp, global_low, null_value, is_null_nan, is_int, min_val, max_val, out
):
    nz, nx, ny = data_3d.shape

    for z in numba.prange(nz):
        m = mult[z]
        interp = low_q_interp[z]
        s = m
        o = global_low - interp * m

        for x in range(nx):
            for y in range(ny):
                val = float(data_3d[z, x, y])

                if not is_null_nan and val == null_value:
                    out[z, x, y] = null_value
                else:
                    res = val * s + o

                    if is_int:
                        if res < min_val:
                            res = min_val
                        elif res > max_val:
                            res = max_val

                    out[z, x, y] = res


def _is_nan_value(value):
    try:
        return bool(np.isnan(value))
    except TypeError:
        return False


def normalize_z(
    data_3d, sigma=3.0, quantile_low=0.4, quantile_high=0.95, downsample=8, null_value=np.nan, spatial_downsample="auto"
):
    if null_value is None:
        null_value = np.nan

    is_null_nan = _is_nan_value(null_value)
    orig_dtype = data_3d.dtype
    z_size, h_size, w_size = data_3d.shape

    if spatial_downsample == "auto":
        slice_pixels = h_size * w_size
        if slice_pixels > 40000:
            s_stride = max(1, int(np.sqrt(slice_pixels / 20000)))
        else:
            s_stride = 1
    elif isinstance(spatial_downsample, int) and spatial_downsample > 1:
        s_stride = spatial_downsample
    else:
        s_stride = 1

    data_q_samples = data_3d[::downsample, ::s_stride, ::s_stride].astype(np.float32, copy=False)

    if not is_null_nan:
        null_mask_down = data_q_samples == null_value
        if np.any(null_mask_down):
            data_q_samples = data_q_samples.copy()
            data_q_samples[null_mask_down] = np.nan

    data_q_2d = data_q_samples.reshape(data_q_samples.shape[0], -1)
    low_q, high_q = np.nanquantile(data_q_2d, (quantile_low, quantile_high), axis=1)

    global_low = np.nanmean(low_q)
    global_high = np.nanmean(high_q)

    low_q_smooth = gaussian_filter1d(np.nan_to_num(low_q, nan=global_low), sigma)
    high_q_smooth = gaussian_filter1d(np.nan_to_num(high_q, nan=global_high), sigma)

    z_down = np.arange(0, z_size, downsample)
    z_full = np.arange(z_size)

    low_q_interp = np.interp(z_full, z_down, low_q_smooth)
    high_q_interp = np.interp(z_full, z_down, high_q_smooth)

    if z_down[-1] < z_size - 1 and len(z_down) > 1:
        slope_low = (low_q_smooth[-1] - low_q_smooth[-2]) / (z_down[-1] - z_down[-2])
        slope_high = (high_q_smooth[-1] - high_q_smooth[-2]) / (z_down[-1] - z_down[-2])
        tail = z_full > z_down[-1]
        low_q_interp[tail] = low_q_smooth[-1] + slope_low * (z_full[tail] - z_down[-1])
        high_q_interp[tail] = high_q_smooth[-1] + slope_high * (z_full[tail] - z_down[-1])

    range_q = np.clip(high_q_interp - low_q_interp, 1e-8, None)
    mult = (global_high - global_low) / range_q
    out = np.empty_like(data_3d)

    is_int = np.issubdtype(orig_dtype, np.integer)

    if is_int:
        info = np.iinfo(orig_dtype)
        min_val = float(info.min)
        max_val = float(info.max)
    else:
        min_val = 0.0
        max_val = 0.0

    _fused_normalize_z_kernel(
        data_3d,
        mult.astype(np.float32),
        low_q_interp.astype(np.float32),
        float(global_low),
        (float(null_value) if not is_null_nan else 0.0),
        is_null_nan,
        is_int,
        min_val,
        max_val,
        out,
    )

    return out


@numba.njit(parallel=True, fastmath=True, nogil=True)
def _fused_shading_post_processing_kernel(
    input_img, shading_volume, kernel, radius, is_null_nan, input_null_val, fill_val, is_int, min_val, max_val, out
):
    nz, nx, ny = input_img.shape

    for z in numba.prange(nz):
        for x in range(nx):
            for y in range(ny):
                num = 0.0
                den = 0.0

                for dz in range(-radius, radius + 1):
                    zi = z + dz
                    if 0 <= zi < nz:
                        s_val = float(shading_volume[zi, x, y])
                        if not np.isnan(s_val):
                            w = kernel[dz + radius]
                            num += s_val * w
                            den += w

                shd = num / den if den > 0.0 else np.nan
                img_v = float(input_img[z, x, y])
                valid = not np.isnan(shd) and shd != 0.0

                if is_null_nan:
                    valid = valid and not np.isnan(img_v)
                else:
                    valid = valid and img_v != input_null_val

                if valid:
                    res = img_v / shd
                    if np.isnan(res) or np.isinf(res):
                        res = fill_val
                    elif is_int:
                        if res < min_val:
                            res = min_val
                        elif res > max_val:
                            res = max_val
                    out[z, x, y] = res
                else:
                    out[z, x, y] = fill_val


@numba.njit(parallel=True, fastmath=True, nogil=True)
def _compute_valid_sum_and_count(img, mask, is_null_nan, null_val):
    nz, nx, ny = img.shape
    is_mask_3d = mask.ndim == 3
    total_sum = 0.0
    total_count = 0

    for z in numba.prange(nz):
        sub_sum = 0.0
        sub_count = 0

        for x in range(nx):
            for y in range(ny):
                m = mask[z, x, y] if is_mask_3d else mask[x, y]
                if m == 0:
                    continue

                v = float(img[z, x, y])

                if is_null_nan:
                    if np.isnan(v):
                        continue
                else:
                    if v == null_val:
                        continue

                sub_sum += v
                sub_count += 1

        total_sum += sub_sum
        total_count += sub_count

    return (total_sum, total_count)


def _select_fitting_points(mask, fitting_points_percentage):
    valid_x, valid_y = np.nonzero(mask)
    num_valid = valid_x.size

    if num_valid == 0:
        return None, None

    number_of_fitting_points = max(1, int(num_valid * (fitting_points_percentage / 100.0)))

    if num_valid <= number_of_fitting_points:
        return (valid_x, valid_y)

    step = max(1, int(np.round(np.sqrt(num_valid / number_of_fitting_points))))
    grid_mask = np.zeros_like(mask, dtype=bool)
    grid_mask[::step, ::step] = True

    combined_mask = mask & grid_mask
    x_sub, y_sub = np.nonzero(combined_mask)

    if x_sub.size == 0:
        x_sub = valid_x[:number_of_fitting_points]
        y_sub = valid_y[:number_of_fitting_points]

    return (x_sub, y_sub)


def _validate_radial_shading(shading, image_slice, mask_slice, global_mean):
    valid_mask = (mask_slice != 0) & np.isfinite(image_slice)
    valid_shading = shading[valid_mask]

    if valid_shading.size == 0:
        return False

    if not np.all(np.isfinite(valid_shading)):
        return False

    min_shading = np.min(valid_shading)
    max_shading = np.max(valid_shading)

    if min_shading <= 0 or max_shading <= 0:
        return False

    if global_mean > 0:
        relative_max = max_shading / global_mean
        relative_min = min_shading / global_mean

        if relative_max > 10.0:
            return False

        if relative_min < 0.05:
            return False

    return True


def _fit_radial_slice(
    image_slice, mask_slice, polynomial_order, initial_cx, initial_cy, fitting_points_percentage, nx, ny, global_mean
):
    mask = (mask_slice != 0) & ~np.isnan(image_slice)

    x_data, y_data = _select_fitting_points(mask, fitting_points_percentage)

    if x_data is None:
        return None

    values = image_slice[x_data, y_data].astype(np.float64, copy=False)

    cx, cy = _search_radial_center(x_data, y_data, values, initial_cx, initial_cy, polynomial_order, nx, ny)

    coefficients, radius_scale, error, condition_number = _solve_radial_stable_kernel(
        x_data, y_data, values, cx, cy, polynomial_order, False
    )

    if not np.isfinite(condition_number) or condition_number > 1e8:
        coefficients, radius_scale, error, condition_number = _solve_radial_stable_kernel(
            x_data, y_data, values, cx, cy, polynomial_order, True
        )

    return (cx, cy, coefficients, radius_scale)


def _fit_cartesian_slice(image_slice, mask_slice, polynomial_order, fitting_points_percentage, nx, ny):
    mask = (mask_slice != 0) & ~np.isnan(image_slice)

    x_data, y_data = _select_fitting_points(mask, fitting_points_percentage)

    if x_data is None:
        return None

    z_data = image_slice[x_data, y_data].astype(np.float64, copy=False)

    try:
        shading = _fit_cartesian_slice_kernel(x_data, y_data, z_data, polynomial_order, nx, ny)
    except Exception:
        return None

    return shading


def _process_slice_group(
    z_start,
    z_end,
    inputImageArray,
    inputShadingMaskArray,
    functionType,
    polynomialOrder,
    fittingPointsPercentage,
    initialCx,
    initialCy,
    globalMean,
    nx,
    ny,
):
    representative_z = z_start + (z_end - z_start) // 2
    image_slice = inputImageArray[representative_z]
    mask_slice = inputShadingMaskArray[representative_z]

    if functionType == "Polynomial Radial":
        fit = _fit_radial_slice(
            image_slice, mask_slice, polynomialOrder, initialCx, initialCy, fittingPointsPercentage, nx, ny, globalMean
        )

        if fit is None:
            return (z_start, z_end, None)

        cx, cy, coefficients, radius_scale = fit

        shading = _evaluate_radial_model(nx, ny, cx, cy, coefficients, polynomialOrder, radius_scale)

        if not _validate_radial_shading(shading, image_slice, mask_slice, globalMean):
            logging.warning(
                "Radial shading fit rejected for slice group %d-%d due to unstable edge behaviour.", z_start, z_end
            )

            mask = (mask_slice != 0) & ~np.isnan(image_slice)

            x_data, y_data = _select_fitting_points(mask, fittingPointsPercentage)

            if x_data is None or x_data.size == 0:
                return (z_start, z_end, None)

            values = image_slice[x_data, y_data].astype(np.float64, copy=False)

            coefficients, radius_scale, _, _ = _solve_radial_stable_kernel(
                x_data, y_data, values, cx, cy, polynomialOrder, True
            )

            shading = _evaluate_radial_model(nx, ny, cx, cy, coefficients, polynomialOrder, radius_scale)

        if not np.all(np.isfinite(shading)):
            return (z_start, z_end, None)

        shading = np.maximum(shading, np.float64(globalMean * 0.05))

        return (z_start, z_end, shading.astype(np.float32, copy=False) / np.float32(globalMean))

    if functionType == "Polynomial":
        shading = _fit_cartesian_slice(image_slice, mask_slice, polynomialOrder, fittingPointsPercentage, nx, ny)

        if shading is None:
            return (z_start, z_end, None)

        return (z_start, z_end, shading.astype(np.float32, copy=False) / np.float32(globalMean))

    return (z_start, z_end, None)


def _evaluate_slice_by_slice_correction(
    inputImageArray,
    inputShadingMaskArray,
    sliceGroupSize,
    fittingPointsPercentage,
    functionType,
    polynomialOrder,
    useCustomCenter,
    centerX,
    centerY,
    globalMean,
    progressCallback,
    cancelCallback,
    maxCores=None,
):
    nz, nx, ny = inputImageArray.shape

    if useCustomCenter:
        initial_cx = float(centerY)
        initial_cy = float(centerX)
    else:
        initial_cx = (nx - 1) * 0.5
        initial_cy = (ny - 1) * 0.5

    shading_volume = np.full((nz, nx, ny), np.nan, dtype=np.float32)

    groups = [(z, min(z + sliceGroupSize, nz)) for z in range(0, nz, sliceGroupSize)]
    cpu_count = os.cpu_count() or 4
    hard_max_cores = max(1, cpu_count - 2)

    if maxCores is not None and int(maxCores) > 0:
        max_workers = min(int(maxCores), len(groups), hard_max_cores)
    else:
        max_workers = min(hard_max_cores, len(groups))

    completed_groups = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_group = {
            executor.submit(
                _process_slice_group,
                z_start,
                z_end,
                inputImageArray,
                inputShadingMaskArray,
                functionType,
                polynomialOrder,
                fittingPointsPercentage,
                initial_cx,
                initial_cy,
                globalMean,
                nx,
                ny,
            ): (z_start, z_end)
            for z_start, z_end in groups
        }

        for future in as_completed(future_to_group):
            if cancelCallback and cancelCallback():
                executor.shutdown(wait=False, cancel_futures=True)
                break

            z_start, z_end, shading = future.result()

            if shading is not None:
                shading_volume[z_start:z_end] = shading

            completed_groups += 1

            if progressCallback:
                progressCallback(min(completed_groups * sliceGroupSize, nz), nz)

    return shading_volume


def _apply_shading_post_processing(
    inputImageArray, shading_volume, inputNullValue=np.nan, sigma=3.0, progressCallback=None, cancelCallback=None
):
    start = datetime.datetime.now()
    is_null_nan = _is_nan_value(inputNullValue)
    radius = int(4.0 * sigma + 0.5)

    x = np.arange(-radius, radius + 1, dtype=np.float32)

    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel = (kernel / kernel.sum()).astype(np.float32)

    fill_val = 0.0 if is_null_nan else float(inputNullValue)

    orig_dtype = inputImageArray.dtype
    is_int = np.issubdtype(orig_dtype, np.integer)

    if is_int:
        info = np.iinfo(orig_dtype)
        min_val = float(info.min)
        max_val = float(info.max)
    else:
        min_val = 0.0
        max_val = 0.0

    outputImageArray = np.empty_like(inputImageArray)

    _fused_shading_post_processing_kernel(
        inputImageArray,
        shading_volume,
        kernel,
        radius,
        is_null_nan,
        (float(inputNullValue) if not is_null_nan else 0.0),
        fill_val,
        is_int,
        min_val,
        max_val,
        outputImageArray,
    )

    if progressCallback:
        progressCallback(1.0)

    elapsed = (datetime.datetime.now() - start).total_seconds()

    return outputImageArray, elapsed


def compute_polynomial_shading_correction(
    inputImageArray,
    inputShadingMaskArray,
    sliceGroupSize=1,
    fittingPointsPercentage=60,
    functionType="Polynomial Radial",
    polynomialOrder=4,
    useCustomCenter=False,
    centerX=0,
    centerY=0,
    inputNullValue=None,
    progressCallback=None,
    postProcessingProgressCallback=None,
    cancelCallback=None,
    postProcessing=True,
    maxCores=None,
):
    cpu_count = os.cpu_count() or 4
    hard_max_cores = max(1, cpu_count - 2)

    if maxCores is not None and int(maxCores) > 0:
        num_cores = min(int(maxCores), hard_max_cores)
    else:
        num_cores = hard_max_cores

    try:
        numba.set_num_threads(num_cores)
    except Exception:
        pass

    inputImageArray = np.asarray(inputImageArray)
    inputShadingMaskArray = np.asarray(inputShadingMaskArray)

    if inputNullValue is None:
        inputNullValue = np.nan

    is_null_nan = _is_nan_value(inputNullValue)

    total_sum, valid_count = _compute_valid_sum_and_count(
        inputImageArray, inputShadingMaskArray, is_null_nan, (float(inputNullValue) if not is_null_nan else 0.0)
    )

    if valid_count == 0:
        return np.zeros_like(inputImageArray)

    globalMean = total_sum / valid_count

    group_size = max(1, int(sliceGroupSize))

    shading_volume = _evaluate_slice_by_slice_correction(
        inputImageArray,
        inputShadingMaskArray,
        group_size,
        fittingPointsPercentage,
        functionType,
        polynomialOrder,
        useCustomCenter,
        centerX,
        centerY,
        globalMean,
        progressCallback,
        cancelCallback,
        maxCores=maxCores,
    )

    post_processing_time = 0.0

    if postProcessing:
        if postProcessingProgressCallback:
            postProcessingProgressCallback(0.0)

        outputImageArray, post_processing_time = _apply_shading_post_processing(
            inputImageArray,
            shading_volume,
            inputNullValue,
            sigma=3.0,
            progressCallback=postProcessingProgressCallback,
            cancelCallback=cancelCallback,
        )

        if cancelCallback and cancelCallback():
            return outputImageArray
    else:
        outputImageArray = np.empty_like(inputImageArray)
        outputImageArray[:] = inputImageArray / shading_volume

        if progressCallback:
            progressCallback(inputImageArray.shape[0], inputImageArray.shape[0])

    compute_polynomial_shading_correction._last_post_processing_time = post_processing_time

    return outputImageArray
