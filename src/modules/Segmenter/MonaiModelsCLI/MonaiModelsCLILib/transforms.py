import numpy as np
import xarray as xr
import torch
from scipy.ndimage import distance_transform_edt, distance_transform_cdt
import warnings
import pickle as pkl
from ast import literal_eval
import pickle as pkl
from sklearn.preprocessing import QuantileTransformer


def get_torch_dtype(name):
    types = {
        "float16": torch.float16,
        "float32": torch.float32,
        "float64": torch.float64,
        "int8": torch.int8,
        "uint8": torch.uint8,
    }
    return types[name]


class ComposedTransform:
    def __init__(self, transforms):
        self.transforms = transforms

    def __call__(self, sample):
        for transform in self.transforms:
            sample = transform(sample)
        return sample


class IdentityTransform:
    def __call__(self, sample):
        return sample


class ReadFirstNetCDFVariableTransform:
    def __init__(self, path_key, out_key, dtype="float32"):
        self.path_key = path_key
        self.out_key = out_key
        self.dtype = "float32"

    def __call__(self, sample):
        dataset = xr.open_dataset(sample[self.path_key])
        data_var_name = next(iter(dataset.data_vars))

        sample[self.out_key] = dataset[data_var_name].data.astype(self.dtype)

        dataset.close()
        return sample


class ReadNetCDFTransform:
    def __init__(self, key="path", variables=None, attrs=None, out_attr_sep=".", del_dataset=True):
        if not isinstance(variables, dict) and variables is not None:
            variables = {k: None for k in variables}
        if not isinstance(attrs, dict) and attrs is not None:
            attrs = {k: None for k in attrs}

        self.key = key
        self.variables = variables
        self.attrs = attrs
        self.out_attr_sep = out_attr_sep
        self.del_dataset = del_dataset

    def __call__(self, sample):
        dataset = xr.open_dataset(sample[self.key])

        # saving variables
        if self.variables is not None:
            variables = self.variables
        else:
            variables = {k: None for k in dataset.data_vars.keys()}

        for var_name, var_desc in variables.items():
            # extract variable
            var = dataset[var_name]
            var_data = var.data
            if isinstance(var_desc, dict):
                var_dtype = var_desc.get("dtype", None)
                if var_dtype is not None:
                    var_data = var_data.astype(var_dtype)
            sample[var_name] = var_data

            # extract variable attributes
            if not isinstance(var_desc, dict):
                continue

            var_attrs = var_desc.get("attrs")
            if not var_attrs:
                continue

            if var_attrs is True:
                var_attrs = {k: None for k in tuple(var.attrs.keys())}

            for attr_name, attr_desc in var_attrs.items():
                if isinstance(attr_desc, dict):
                    attr_dtype = attr_desc.get("dtype")
                else:
                    attr_dtype = None

                attr_data = var.attrs[attr_name]

                #                 try:
                #                     # try block needed for when all vars are being considered
                #                     # if one of them is wicked, we've got a problem
                #                     attr_data = np.asarray(attr_data)

                #                     if attr_dtype is not None:
                #                         attr_data = attr_data.astype(dtype)
                #                 except Exception:
                #                     pass

                var_attr_name = f"{var_name}{self.out_attr_sep}{attr_name}"
                sample[var_attr_name] = attr_data

        # extract NetCDF attributes
        if self.attrs is not None:
            attrs = self.attrs
        else:
            attrs = {k: None for k in dataset.attrs.keys()}

        for attr_name, attr_desc in attrs.items():
            attr_data = dataset.attrs[attr_name]
            try:
                attr_data = np.asarray(attr_data)
                attr_dtype = attr_desc.get("dtype", None)
                if attr_dtype is not None:
                    attr_data = attr_data.astype(dtype=attr_data)
            except Exception:
                pass
            sample[attr_name] = attr_data

        dataset.close()

        return sample


class ToTensorTransform:
    def __init__(self, keys):
        if not isinstance(keys, dict):
            keys = {k: None for k in keys}
        self.keys = keys

    def __call__(self, sample):
        for key, dtype in self.keys.items():
            if not key in sample:
                continue

            tensor = torch.as_tensor(sample[key])
            if dtype is not None:
                tensor = tensor.to(get_torch_dtype(dtype))
            sample[key] = tensor

        return sample


class XarrayToTensorsTransform:
    def __init__(self, key="dataset", variables=None, attrs=None, out_attr_sep=".", del_dataset=True):
        if not isinstance(variables, dict) and variables is not None:
            variables = {k: None for k in variables}
        if not isinstance(attrs, dict) and attrs is not None:
            attrs = {k: None for k in attrs}

        self.key = key
        self.variables = variables
        self.attrs = attrs
        self.out_attr_sep = out_attr_sep
        self.del_dataset = del_dataset

    def __call__(self, sample):
        dataset = sample[self.key]

        # saving variables
        if self.variables is not None:
            variables = self.variables
        else:
            variables = {k: None for k in dataset.data_vars.keys()}

        for var_name, var_desc in variables.items():
            # save variable as tensors
            var = dataset[var_name]
            var_tensor = torch.from_numpy(var.data)
            var_dtype = var_desc.get("dtype", None)
            if var_dtype is not None:
                var_tensor = var_tensor.to(dtype=get_torch_dtype(var_dtype))
            sample[var_name] = var_tensor

            # save variable attributes as tensors
            var_attrs = var_desc.get("attrs")
            if not var_attrs:
                continue
            if var_attrs is True:
                var_attrs = {k: None for k in tuple(var.attrs.keys())}

            for attr_name, attr_desc in var_attrs.items():
                if isinstance(attr_desc, dict):
                    attr_dtype = attr_desc.get("dtype")
                else:
                    attr_dtype = None

                attr = var.attrs[attr_name]

                attr_tensor = attr
                try:
                    attr_tensor = torch.from_numpy(np.asarray(attr))

                    if attr_dtype is not None:
                        attr_tensor = attr_tensor.to(dtype=get_torch_dtype(attr_dtype))
                except:
                    pass

                var_attr_name = f"{var_name}{self.out_attr_sep}{attr_name}"
                sample[var_attr_name] = attr_tensor

        # save attributes as tensors
        if self.attrs is not None:
            attrs = self.attrs
        else:
            attrs = {k: None for k in dataset.attrs.keys()}

        for attr_name, attr_desc in attrs.items():
            attr = dataset.attrs[attr_name]
            attr_tensor = torch.from_numpy(np.asarray(attr))
            attr_dtype = attr_desc.get("dtype", None)
            if attr_dtype is not None:
                attr_tensor = attr_tensor.to(dtype=get_torch_dtype(attr_dtype))
            sample[attr_name] = attr_tensor

        if self.del_dataset:
            dataset.close()
            del sample["dataset"]

        return sample


def quantile_transform(
    x,
    quantiles=(0.02, 0.50),
    move_to=(0.0, 0.5),
    quantile_values=None,
    n_samples=1000,
    idx_sample=None,
    return_idx_sample=False,
    out=None,
):
    """
    Scale data range from the given `quantiles` to another range (`move_to`).
    Input shape: (D1[, D2,...]), with no channels.
    Tip: Make `out=x` for an inplace transform.
    """
    x_out = out if out is not None else np.empty_like(x)

    min_moved, max_moved = move_to
    delta_moved = max_moved - min_moved

    if not quantile_values:
        # getting internal sub-volume for not including borders in the transform
        dy = slice(round(x.shape[1] / 4), round(3 * x.shape[1] / 4))
        dx = slice(round(x.shape[2] / 4), round(3 * x.shape[2] / 4))
        dz = slice(round(x.shape[3] / 4), round(3 * x.shape[3] / 4))

        table = x[:, dy, dx, dz].ravel()
        if idx_sample is None:
            idx_sample = np.random.choice(len(table), n_samples)
            idx_sample = np.sort(idx_sample)
        table_sample = table[idx_sample]
        min_quantile, max_quantile = np.quantile(table_sample, quantiles)
    else:
        min_quantile, max_quantile = quantile_values
    delta_quantile = max_quantile - min_quantile

    # transform entire array
    x_out[...] = (x - min_quantile) / delta_quantile * delta_moved + min_moved
    if return_idx_sample:
        return idx_sample, x_out
    return x_out


class QuantileTransform:
    """
    Works with data with 0 or 1 channel dimensions.
    """

    def __init__(
        self, key, quantiles=(0.02, 0.50), move_to=(0.0, 0.5), quantile_keys=None, quantile_values=None, n_samples=1000
    ):
        self.key = key
        self.quantiles = quantiles
        self.move_to = move_to
        self.quantile_keys = quantile_keys
        self.quantile_values = quantile_values
        self.n_samples = n_samples

    def __call__(self, sample):
        if self.quantile_values:
            quantile_values = self.quantile_values
        elif self.quantile_keys:
            min_quantile = sample[self.quantile_keys[0]].item()
            max_quantile = sample[self.quantile_keys[1]].item()
            quantile_values = min_quantile, max_quantile
        else:
            quantile_values = None

        quantile_transform(
            sample[self.key],
            quantiles=self.quantiles,
            move_to=self.move_to,
            quantile_values=quantile_values,
            n_samples=1000,
            out=sample[self.key],
        )
        return sample


def apply_table_transform(transform, x):
    shape = x.shape
    x = x.ravel()[:, None]
    x = transform(x)
    x = x.reshape(shape)
    return x


def dump_to_str(obj):
    return str(pkl.dumps(obj))


def load_from_str(s):
    return pkl.loads(literal_eval(s))


class ApplyPickledTransform:
    def __init__(self, key, transform_key, del_transform_key=True):
        self.key = key
        self.transform_key = transform_key
        self.del_transform_key = del_transform_key

    def __call__(self, sample):
        x = sample[self.key]
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning)
            scaler = load_from_str(sample[self.transform_key])
        x = torch.from_numpy(apply_table_transform(scaler.transform, x.numpy()))
        sample[self.key] = x

        if self.del_transform_key:
            del sample[self.transform_key]

        return sample


class QuantileDeformationTransform:
    def __init__(
        self,
        key,
        output_distribution="uniform",
        transform_key=None,
        del_transform_key=True,
        pickled=False,
        mode="train",
    ):
        self.key = key
        self.transform_key = transform_key
        self.del_transform_key = del_transform_key
        self.mode = mode
        self.pickled = pickled
        if self.pickled:
            self.scaler = None
        else:
            self.scaler = QuantileTransformer(
                output_distribution=output_distribution,
                n_quantiles=1_000,
            )

    def __call__(self, sample):
        x = sample[self.key]
        x = x.numpy()
        shape = x.shape
        x_table = x.ravel()[:, None]

        if self.pickled:
            import warnings

            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning)
                scaler = load_from_str(sample[self.transform_key])
        else:
            scaler = self.scaler

            n_samples = 100_000
            # sort is desired at indexing (performance)
            idx_sample = np.sort(np.random.choice(len(x_table), n_samples))
            x_table_sample = x_table[idx_sample]
            x_table_sample = np.asarray(x_table_sample)
            x_table_sample = np.sort(x_table_sample, axis=0)
            scaler.fit(x_table_sample)

        # apply transform
        x_table = scaler.transform(x_table)

        x = x_table.reshape(shape)
        x = torch.from_numpy(x)

        sample[self.key] = x

        if self.del_transform_key and self.transform_key:
            del sample[self.transform_key]

        return sample


class MultiChannelTransform:
    def __init__(self, key, transform):
        self.key = key
        self.transform = transform

    def __call__(self, sample):
        for channel in sample[self.key]:
            channel[...] = self.transform(channel)
        return sample


class AddAxisTransform:
    def __init__(self, keys=(), axis=0):
        self.keys = keys
        self.axis = axis

    def __call__(self, sample):
        for key in self.keys:
            if key in sample:
                sample[key] = torch.unsqueeze(sample[key], axis=self.axis)
        return sample


class SwapAxesTransform:
    def __init__(self, keys, axis_0=-1, axis_1=0):
        self.keys = keys
        self.axis_0 = axis_0
        self.axis_1 = axis_1

    def __call__(self, sample):
        for key in self.keys:
            sample[key] = torch.swapaxes(sample[key], self.axis_0, self.axis_1)
        return sample


class PermuteTransform:
    def __init__(self, keys, axes):
        self.keys = keys
        self.axes = axes

    def __call__(self, sample):
        for key in self.keys:
            if key in sample:
                sample[key] = torch.permute(sample[key], self.axes)
        return sample


class ConcatenateTransform:
    def __init__(self, key_groups, axis=0):
        self.key_groups = key_groups
        self.axis = axis

    def __call__(self, sample):
        for new_key, old_keys in self.key_groups.items():
            old_tensors = [sample[k] for k in old_keys]
            new_tensor = torch.concat(old_tensors, dim=self.axis)
            for old_key in old_keys:
                del sample[old_key]
            sample[new_key] = new_tensor
        return sample


class RenameTransform:
    def __init__(self, renames, axis=0):
        self.renames = renames

    def __call__(self, sample):
        for old_key, new_key in self.renames.items():
            if old_key in sample:
                sample[new_key] = sample[old_key]
                del sample[old_key]
        return sample


class BinarizerTransform:
    def __init__(self, key, threshold=0.5, dtype="int8"):
        self.key = key
        self.threshold = threshold
        self.dtype = dtype

    def __call__(self, sample):
        x = sample[self.key]
        x = (x > self.threshold).to(get_torch_dtype(self.dtype))
        sample[self.key] = x
        return sample


class ArgmaxTransform:
    def __init__(self, key, dtype="int8", dim=1, keepdim=True):
        self.key = key
        self.dim = dim
        self.dtype = dtype
        self.keepdim = keepdim

    def __call__(self, sample):
        x = sample[self.key]
        x = torch.argmax(x, dim=self.dim, keepdim=self.keepdim)
        x = x.to(get_torch_dtype(self.dtype))
        sample[self.key] = x
        return sample


class MinMaxTransform:
    def __init__(self, key, move_from=(0, 255), move_to=(0.0, 1.0)):
        self.key = key
        self.move_from = move_from
        self.move_to = move_to

    def __call__(self, sample):
        x = sample[self.key]
        old_min, old_max = self.move_from
        new_min, new_max = self.move_to
        new_delta = new_max - new_min
        old_delta = old_max - old_min

        x = (x - old_min) / old_delta * new_delta + new_min
        sample[self.key] = x
        return sample


def get_binary_boundary(labelmap, max_border_distance=1):
    fg_edt = distance_transform_edt(labelmap)
    bg_edt = distance_transform_edt(1 - labelmap)
    full_edt = fg_edt + bg_edt
    return np.uint8(full_edt <= max_border_distance)


class AddBinaryBoundaryMaskTransform:
    def __init__(self, key, label_key, max_border_distance=2):
        self.key = key
        self.label_key = label_key
        self.max_border_distance = max_border_distance

    def __call__(self, sample):
        boundary = get_binary_boundary(sample[self.label_key], self.max_border_distance)
        sample[self.key] = torch.from_numpy(boundary)
        return sample


class AddConstantTransform:
    def __init__(self, keys, constant):
        self.keys = keys
        self.constant = constant

    def __call__(self, sample):
        for key in self.keys:
            sample[key] = sample[key] + self.constant
        return sample


class TakeChannelsTransform:
    def __init__(self, key, channels=()):
        self.key = key
        self.channels = channels

    def __call__(self, sample):
        sample[self.key] = sample[self.key][:, self.channels]
        return sample
