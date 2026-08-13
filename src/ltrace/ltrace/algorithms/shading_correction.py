import logging

import numpy as np
from scipy.interpolate import interp1d
from scipy.ndimage import convolve1d
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import curve_fit

from ltrace.slicer.helpers import safe_convert_array


def normalize_z(data_3d, sigma=3.0, quantile_low=0.4, quantile_high=0.95, downsample=8, null_value=np.nan):
    if null_value is None:
        null_value = np.nan

    orig_dtype = data_3d.dtype
    z_size = data_3d.shape[0]

    data_downsampled = data_3d[::downsample].astype(np.float32)
    data_downsampled[data_downsampled == null_value] = np.nan

    low_q = np.nanquantile(data_downsampled, quantile_low, axis=(1, 2))
    high_q = np.nanquantile(data_downsampled, quantile_high, axis=(1, 2))

    global_low = np.nanmean(low_q)
    global_high = np.nanmean(high_q)

    low_q_smooth = gaussian_filter1d(np.nan_to_num(low_q, nan=global_low), sigma)
    high_q_smooth = gaussian_filter1d(np.nan_to_num(high_q, nan=global_high), sigma)

    z_down = np.arange(0, z_size, downsample)
    z_full = np.arange(z_size)
    interp_low = interp1d(z_down, low_q_smooth, kind="linear", bounds_error=False, fill_value="extrapolate")
    interp_high = interp1d(z_down, high_q_smooth, kind="linear", bounds_error=False, fill_value="extrapolate")

    low_q_interp = interp_low(z_full)[:, None, None]
    high_q_interp = interp_high(z_full)[:, None, None]

    range_q = np.clip(high_q_interp - low_q_interp, 1e-8, None)

    data_float = data_3d.astype(np.float32)
    mult = (global_high - global_low) / range_q
    normalized_float = (data_float - low_q_interp) * mult + global_low

    normalized_float[data_3d == null_value] = null_value

    if np.issubdtype(orig_dtype, np.integer):
        mask = data_3d != null_value
        normalized_float[mask] = np.clip(
            normalized_float[mask],
            np.iinfo(orig_dtype).min,
            np.iinfo(orig_dtype).max,
        )

    normalized_data = normalized_float.astype(orig_dtype)

    return normalized_data


def gaussian_filter1d_nans(input_array, sigma, truncate=4.0, axis=-1):
    input_array = np.asarray(input_array, dtype=float)

    radius = int(truncate * sigma + 0.5)
    x = np.arange(-radius, radius + 1)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel /= kernel.sum()

    if axis < 0:
        axis = input_array.ndim + axis

    axes = list(range(input_array.ndim))
    axes.remove(axis)
    axes.append(axis)
    transposed = np.transpose(input_array, axes)

    original_shape = transposed.shape
    reshaped = transposed.reshape(-1, original_shape[-1])

    valid_mask = ~np.isnan(reshaped)
    safe_data = reshaped.copy()
    safe_data[~valid_mask] = 0

    numerator = convolve1d(safe_data, kernel, axis=1, mode="constant", cval=0.0)
    denominator = convolve1d(valid_mask.astype(float), kernel, axis=1, mode="constant", cval=0.0)

    with np.errstate(divide="ignore", invalid="ignore"):
        result = numerator / denominator

    result = result.reshape(original_shape)
    inverse_axes = [0] * len(axes)
    for i, a in enumerate(axes):
        inverse_axes[a] = i
    return np.transpose(result, inverse_axes)


class ShadingMathematicalModel:
    def __init__(self, function_type, order, center_x, center_y, max_val):
        self.function_type = function_type
        self.cx = center_x
        self.cy = center_y
        self.max_val = max_val

        if function_type == "Polynomial":
            if order == 2:
                self.evaluate = self.cartesian_2
                self.initial_parameters = [self.cx, self.cy, self.max_val, 0.0, 0.0, 1.0, 1.0, 0.0]
            elif order == 4:
                self.evaluate = self.cartesian_4
                self.initial_parameters = [self.cx, self.cy, self.max_val, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0]
            else:  # 6
                self.evaluate = self.cartesian_6
                self.initial_parameters = [self.cx, self.cy, self.max_val, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        elif function_type == "Polynomial Radial":
            if order == 2:
                self.evaluate = self.radial_2
                self.initial_parameters = [self.cx, self.cy, self.max_val, 0.0, 0.0, 1.0]
            elif order == 4:
                self.evaluate = self.radial_4
                self.initial_parameters = [self.cx, self.cy, self.max_val, 0.0, 0.0, 1.0, 0.0]
            else:  # 6
                self.evaluate = self.radial_6
                self.initial_parameters = [self.cx, self.cy, self.max_val, 0.0, 0.0, 1.0, 0.0, 0.0]
        else:
            self.evaluate = None
            self.initial_parameters = []

    def get_plane_initial_parameters(self):
        return [1.0, self.cx, 1.0, self.cy, self.max_val]

    def fit_and_evaluate_slice(self, xData, yData, zData, x_grid, y_grid):
        if self.function_type == "Spline Radial":
            try:
                rData = np.hypot(xData - self.cx, yData - self.cy)
                r_ints = np.round(rData).astype(int)

                order = np.argsort(r_ints)
                sorted_r = r_ints[order]
                sorted_z = zData[order]

                valid_r, indices = np.unique(sorted_r, return_index=True)
                splits = np.split(sorted_z, indices[1:])
                valid_z = np.array([np.median(arr) for arr in splits])

                if len(valid_r) < 4:
                    raise ValueError("Not enough radial points for profiling.")

                max_r = int(valid_r[-1])
                full_r = np.arange(0, max_r + 1)

                fill_func = interp1d(
                    valid_r, valid_z, kind="linear", bounds_error=False, fill_value=(valid_z[0], valid_z[-1])
                )
                filled_z = fill_func(full_r)

                smoothed_z = gaussian_filter1d(filled_z, sigma=15.0)

                final_func = interp1d(
                    full_r, smoothed_z, kind="linear", bounds_error=False, fill_value=(smoothed_z[0], smoothed_z[-1])
                )

                r_grid = np.hypot(x_grid - self.cx, y_grid - self.cy)
                return final_func(r_grid)

            except Exception as e:
                logging.warning(f"Spline Radial failed: {e}. Falling back to plane.")
                return self._fallback_to_plane(xData, yData, zData, x_grid, y_grid)
        else:
            try:
                fittedParameters, _ = curve_fit(
                    self.evaluate, [xData, yData], zData, p0=self.initial_parameters, check_finite=False
                )
                self.initial_parameters = fittedParameters
                return self.evaluate((x_grid, y_grid), *fittedParameters)
            except Exception:
                return self._fallback_to_plane(xData, yData, zData, x_grid, y_grid)

    def _fallback_to_plane(self, xData, yData, zData, x_grid, y_grid):
        try:
            fittedParameters, _ = curve_fit(
                self.plane, [xData, yData], zData, p0=self.get_plane_initial_parameters(), check_finite=False
            )
            return self.plane((x_grid, y_grid), *fittedParameters)
        except Exception:
            raise ValueError("Both main function and fallback plane failed to fit.")

    @staticmethod
    def cartesian_2(data, cx, cy, c0, c1_x, c1_y, c2_x, c2_y, c2_xy):
        x, y = data
        xb = (x - cx) * 0.01
        yd = (y - cy) * 0.01
        return c0 + c1_x * xb + c1_y * yd + c2_x * (xb * xb) + c2_y * (yd * yd) + c2_xy * (xb * yd)

    @staticmethod
    def cartesian_4(data, cx, cy, c0, c1_x, c1_y, c2_x, c2_y, c2_xy, c4_x, c4_y):
        x, y = data
        xb = (x - cx) * 0.01
        yd = (y - cy) * 0.01
        xb2 = xb * xb
        yd2 = yd * yd
        return (
            c0
            + c1_x * xb
            + c1_y * yd
            + c2_x * xb2
            + c2_y * yd2
            + c2_xy * (xb * yd)
            + c4_x * (xb2 * xb2)
            + c4_y * (yd2 * yd2)
        )

    @staticmethod
    def cartesian_6(data, cx, cy, c0, c1_x, c1_y, c2_x, c2_y, c2_xy, c4_x, c4_y, c6_x, c6_y):
        x, y = data
        xb = (x - cx) * 0.01
        yd = (y - cy) * 0.01
        xb2 = xb * xb
        yd2 = yd * yd
        return (
            c0
            + c1_x * xb
            + c1_y * yd
            + c2_x * xb2
            + c2_y * yd2
            + c2_xy * (xb * yd)
            + c4_x * (xb2 * xb2)
            + c4_y * (yd2 * yd2)
            + c6_x * (xb2 * xb2 * xb2)
            + c6_y * (yd2 * yd2 * yd2)
        )

    @staticmethod
    def radial_2(data, cx, cy, c0, c1_x, c1_y, c2_r):
        x, y = data
        xb = (x - cx) * 0.01
        yd = (y - cy) * 0.01
        r2 = xb * xb + yd * yd
        return c0 + c1_x * xb + c1_y * yd + c2_r * r2

    @staticmethod
    def radial_4(data, cx, cy, c0, c1_x, c1_y, c2_r, c4_r):
        x, y = data
        xb = (x - cx) * 0.01
        yd = (y - cy) * 0.01
        r2 = xb * xb + yd * yd
        return c0 + c1_x * xb + c1_y * yd + c2_r * r2 + c4_r * (r2 * r2)

    @staticmethod
    def radial_6(data, cx, cy, c0, c1_x, c1_y, c2_r, c4_r, c6_r):
        x, y = data
        xb = (x - cx) * 0.01
        yd = (y - cy) * 0.01
        r2 = xb * xb + yd * yd
        return c0 + c1_x * xb + c1_y * yd + c2_r * r2 + c4_r * (r2 * r2) + c6_r * (r2 * r2 * r2)

    @staticmethod
    def plane(data, a, b, c, d, e):
        x, y = data
        return a * (x - b) + c * (y - d) + e


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
    cancelCallback=None,
):
    inputImageArray = np.asarray(inputImageArray)
    inputShadingMaskArray = np.asarray(inputShadingMaskArray)

    if inputNullValue is None:
        inputNullValue = np.nan

    outputImageArray = np.full_like(inputImageArray, np.nan, dtype=np.float32)

    valid_mask = inputShadingMaskArray != 0
    valid_mask &= inputImageArray != inputNullValue
    valid_count = np.count_nonzero(valid_mask)

    if valid_count == 0:
        return safe_convert_array(np.zeros_like(inputImageArray, dtype=np.float32), inputImageArray.dtype.name)

    if np.issubdtype(inputImageArray.dtype, np.integer):
        maxInitial = np.iinfo(inputImageArray.dtype).min
    else:
        maxInitial = -np.inf

    inputArrayShadingMaskMax = np.max(inputImageArray, initial=maxInitial, where=valid_mask)
    inputArrayShadingMaskMean = np.sum(inputImageArray, where=valid_mask, dtype=np.float64) / valid_count

    if useCustomCenter:
        mx, my = centerY, centerX
    else:
        mx = inputImageArray.shape[1] / 2.0
        my = inputImageArray.shape[2] / 2.0

    model = ShadingMathematicalModel(functionType, polynomialOrder, mx, my, inputArrayShadingMaskMax)

    x, y = np.meshgrid(
        np.arange(inputImageArray.shape[1], dtype=np.float32),
        np.arange(inputImageArray.shape[2], dtype=np.float32),
        indexing="ij",
    )

    iterationIndexes = np.arange(sliceGroupSize // 2, len(inputImageArray), sliceGroupSize)
    total_slices = len(inputImageArray)

    for i in iterationIndexes:
        if cancelCallback and cancelCallback():
            break

        if progressCallback:
            progressCallback(i, total_slices)

        mask_i = (inputShadingMaskArray[i] != 0) & (inputImageArray[i] != inputNullValue)
        valid_x, valid_y = np.nonzero(mask_i)
        num_valid = valid_x.size

        if num_valid == 0:
            continue

        # Dynamic conversion: convert the percentage into an absolute target for this slice
        numberOfFittingPoints = max(1, int(num_valid * (fittingPointsPercentage / 100.0)))

        if num_valid <= numberOfFittingPoints:
            xData_sub = valid_x
            yData_sub = valid_y
        else:
            step = max(1, int(np.round(np.sqrt(num_valid / numberOfFittingPoints))))

            grid_mask = np.zeros_like(mask_i, dtype=bool)
            grid_mask[::step, ::step] = True

            combined_mask = mask_i & grid_mask
            xData_sub, yData_sub = np.nonzero(combined_mask)

            if xData_sub.size == 0:
                xData_sub = valid_x[:numberOfFittingPoints]
                yData_sub = valid_y[:numberOfFittingPoints]

        zData_sub = inputImageArray[i, xData_sub, yData_sub]

        try:
            z = model.fit_and_evaluate_slice(xData_sub, yData_sub, zData_sub, x, y)
        except ValueError:
            continue

        zz = z / inputArrayShadingMaskMean

        start_idx = max(0, i - sliceGroupSize // 2)
        end_idx = total_slices if i == iterationIndexes[-1] else i + sliceGroupSize // 2 + 1
        outputImageArray[start_idx:end_idx] = zz

    outputImageArray = gaussian_filter1d_nans(outputImageArray, sigma=3, axis=0)

    input_float = inputImageArray.astype(np.float32)
    input_float[input_float == inputNullValue] = np.nan

    with np.errstate(divide="ignore", invalid="ignore"):
        outputImageArray = np.where(~np.isnan(outputImageArray), input_float / outputImageArray, np.nan)

    outputImageArray[np.isnan(input_float)] = inputNullValue
    outputImageArray = np.where(np.isnan(outputImageArray), 0, outputImageArray)

    if np.issubdtype(inputImageArray.dtype, np.integer):
        info = np.iinfo(inputImageArray.dtype)
        outputImageArray = np.clip(outputImageArray, info.min, info.max)

    return safe_convert_array(outputImageArray, inputImageArray.dtype.name)
