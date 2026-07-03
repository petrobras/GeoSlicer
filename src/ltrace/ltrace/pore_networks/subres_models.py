from abc import ABC, abstractmethod

import numpy as np
import scipy as sp

HG_SURFACE_TENSION = 480  # 480N/km 0.48N/m 48e-5N/mm 48dyn/mm 480dyn/cm
HG_CONTACT_ANGLE = 140  # º
MINIMUM_THROAT_RADIUS = 1e-8


def estimate_radius(capilary_pressure):
    theta = (np.pi * HG_CONTACT_ANGLE) / 180.0
    return abs(2.0 * HG_SURFACE_TENSION * np.cos(theta)) / capilary_pressure


def estimate_pressure(radius):
    theta = (np.pi * HG_CONTACT_ANGLE) / 180.0
    return abs(2.0 * HG_SURFACE_TENSION * np.cos(theta)) / radius


class FixedRadiusLogic:
    required_params = ("radius",)

    @classmethod
    def get_capillary_radius_function(cls, pore_network, params):
        return lambda _: params["subres_params"]["radius"]


class TruncatedGaussianLogic:
    required_params = (
        "mean radius",
        "standard deviation",
        "min radius",
        "max radius",
    )

    @classmethod
    def get_capillary_radius_function(cls, pore_network, params):
        subres_params = params["subres_params"]
        loc = subres_params["mean radius"]
        scale = subres_params["standard deviation"]
        a_trunc = subres_params["min radius"]
        b_trunc = subres_params["max radius"]
        a, b = (a_trunc - loc) / scale, (b_trunc - loc) / scale
        return lambda _: sp.stats.truncnorm.rvs(a, b, size=1)[0] * scale + loc


class LogTruncatedGaussianLogic:
    """Truncated Gaussian distribution applied in log-radius space (i.e., a truncated log-normal).

    The user provides the radii (mean, min, max) in the usual linear units; they are
    transformed via log() internally. The standard deviation is the log-space sigma
    (dimensionless) — the natural parameterization of a log-normal distribution.
    """

    required_params = (
        "mean radius",
        "standard deviation",
        "min radius",
        "max radius",
    )

    @classmethod
    def get_capillary_radius_function(cls, pore_network, params):
        subres_params = params["subres_params"]
        loc = np.log10(subres_params["mean radius"])
        scale = subres_params["standard deviation"]
        a_trunc = np.log10(subres_params["min radius"])
        b_trunc = np.log10(subres_params["max radius"])
        a, b = (a_trunc - loc) / scale, (b_trunc - loc) / scale
        return lambda _: 10 ** (sp.stats.truncnorm.rvs(a, b, size=1)[0] * scale + loc)


class ModelBase(ABC):
    @staticmethod
    def _create_radius_function(porosity_cdf, pressure_cdf):
        def radius_function(phi):
            phi_position = np.interp(phi, porosity_cdf["x"], porosity_cdf["y"])
            estimated_pressure = np.interp(phi_position, pressure_cdf["y"], pressure_cdf["x"])
            return estimate_radius(estimated_pressure)

        return radius_function

    @classmethod
    def _get_cumulative_dist_function(cls, x, y):
        x = np.asarray(x)
        y = np.asarray(y, dtype=float)
        order = np.argsort(x)
        cumulative_y = np.cumsum(y[order])
        cumulative_y /= cumulative_y[-1]
        return {"x": x[order], "y": cumulative_y}

    @classmethod
    def _get_cumulative_dist_points(cls, points):
        cumulative_y = np.zeros(99)
        cumulative_x = np.zeros(99)
        hist, hist_edges = np.histogram(points, 99)
        cumulative_x[0] = hist_edges[0]
        for i in range(99):
            area = (hist[i]) * (hist_edges[i + 1] - hist_edges[i])
            cumulative_x[i] = hist_edges[i]
            cumulative_y[i] = cumulative_y[i - 1] + area
        cumulative_y /= cumulative_y[-1]
        return {"x": cumulative_x, "y": cumulative_y}


class LeverettBase(ModelBase):
    @classmethod
    def get_capillary_radius_function(cls, pore_network, params):
        size_x_cm = params["size"]["x"] / 10
        size_y_cm = params["size"]["y"] / 10
        size_z_cm = params["size"]["z"] / 10
        volume = size_x_cm * size_y_cm * size_z_cm

        total_pore_volume = pore_network["pore.region_volume"].sum()
        porosity = total_pore_volume / volume
        Pc = cls.get_pc(params, porosity)

        radii = pore_network["throat.equivalent_diameter"] / 2
        resolved_throats = np.logical_and(
            pore_network["throat.phases"][:, 0],
            pore_network["throat.phases"][:, 1],
        )
        resolved_radii = radii[resolved_throats]
        smallest_radii = resolved_radii.min()
        highest_pc = estimate_pressure(smallest_radii)
        highest_pc_index = Pc >= highest_pc
        if highest_pc_index.sum() == 0:
            return lambda _: highest_pc

        porosity_cdf = cls._get_cumulative_dist_points(pore_network["throat.subresolution_porosity"])
        pressure_cdf = cls._get_cumulative_dist_function(
            Pc[highest_pc_index],
            params["subres_params"]["Sw"][highest_pc_index],
        )

        return ModelBase._create_radius_function(porosity_cdf, pressure_cdf)

    @classmethod
    @abstractmethod
    def get_pc(cls, params, porosity):
        pass


class LeverettOldLogic(LeverettBase):
    required_params = ("J", "Sw", "corey_a", "corey_b", "model")
    models = {"k = a * phi ** b": lambda a, b, phi: a * phi**b}

    @classmethod
    def get_pc(cls, params, porosity):
        sp = params["subres_params"]
        corey = cls.models[sp["model"]](sp["corey_a"], sp["corey_b"], porosity)
        Pc = (sp["J"] / 2) * estimate_pressure(np.sqrt(corey / porosity))
        return Pc


class LeverettNewLogic(LeverettBase):
    required_params = ("J", "Sw", "permeability")

    @classmethod
    def get_pc(cls, params, porosity):
        sp = params["subres_params"]
        Pc = (sp["J"] / 2) * estimate_pressure(sp["permeability"] / porosity)
        return Pc


class PressureCurveLogic(ModelBase):
    required_params = ("throat radii", "capillary pressure", "dsn", "radii_cutoff_mm")

    @classmethod
    def get_capillary_radius_function(cls, pore_network, params):
        subres_params = params["subres_params"]
        if isinstance(subres_params.get("throat radii"), (list, np.ndarray)):
            smallest_radii = min(params["spacing"]["x"], params["spacing"]["y"], params["spacing"]["z"])

            throat_radii_arr = np.array(subres_params["throat radii"])
            subresolution_radii_bool_index = np.logical_and(
                throat_radii_arr > MINIMUM_THROAT_RADIUS,
                throat_radii_arr <= subres_params["radii_cutoff_mm"],
            )

            if subresolution_radii_bool_index.sum() == 0:
                return lambda _: smallest_radii / 2
            elif subresolution_radii_bool_index.sum() == 1:
                return lambda _: throat_radii_arr[subresolution_radii_bool_index][0]

            radius = throat_radii_arr[subresolution_radii_bool_index]

            Pc = estimate_pressure(radius)
            f_vol = np.array(subres_params["dsn"])[subresolution_radii_bool_index]
        elif subres_params.get("capillary pressure") is not None:
            Pc = subres_params["capillary pressure"]
            f_vol = subres_params["dsn"]

        porosity_cdf = cls._get_cumulative_dist_points(pore_network["throat.subresolution_porosity"])
        pressure_cdf = cls._get_cumulative_dist_function(Pc, f_vol)

        return ModelBase._create_radius_function(porosity_cdf, pressure_cdf)


MODEL_DICT = {
    "Fixed Radius": FixedRadiusLogic(),
    "Truncated Gaussian": TruncatedGaussianLogic(),
    "Log Truncated Gaussian": LogTruncatedGaussianLogic(),
    "Pressure Curve": PressureCurveLogic(),
    "Throat Radius Curve": PressureCurveLogic(),
    "Leverett Function - Permeability curve": LeverettOldLogic(),
    "Leverett Function - Sample Permeability": LeverettNewLogic(),
}


def get_pore_network_volume_data(pore_table_node):
    if pore_table_node is None:
        return {}
    # TODO The or operator here will garantee that old projects could be used
    # we need to remove this in future version
    x_size = float(pore_table_node.GetAttribute("x_size") or 1.0)
    y_size = float(pore_table_node.GetAttribute("y_size") or 1.0)
    z_size = float(pore_table_node.GetAttribute("z_size") or 1.0)
    x_spacing = float(pore_table_node.GetAttribute("x_spacing") or 1.0)
    y_spacing = float(pore_table_node.GetAttribute("y_spacing") or 1.0)
    z_spacing = float(pore_table_node.GetAttribute("z_spacing") or 1.0)
    extraction_algorithm = pore_table_node.GetAttribute("extraction_algorithm")
    is_multiscale = pore_table_node.GetAttribute("is_multiscale") == "True"

    volume_data = {
        "size": {"x": x_size, "y": y_size, "z": z_size},
        "spacing": {"x": x_spacing, "y": y_spacing, "z": z_spacing},
        "extraction_algorithm": extraction_algorithm,
        "is_multiscale": is_multiscale,
    }

    return volume_data


def normalize_psd(x_values, y_values, bins=100):
    if x_values.size == 0:
        return np.array([]), np.array([])

    if isinstance(bins, int):
        edge_min = x_values.min()
        edge_max = x_values.max()
        if edge_min == edge_max:
            return np.array([y_values.sum() * 100]), np.array([edge_min])
        new_bin_edges = np.linspace(edge_min, edge_max, num=bins + 1)
    else:
        new_bin_edges = np.sort(bins)

    hist, bin_edges = np.histogram(x_values, bins=new_bin_edges, weights=y_values)
    hist = hist * 100  # convert fraction to pore volume %
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    return hist, bin_centers


def centers_to_edges(centers):
    centers = np.sort(centers)
    if centers.size < 2:
        return np.array([centers[0] - centers[0] * 0.1, centers[0] + centers[0] * 0.1])

    midpoints = (centers[:-1] + centers[1:]) / 2
    first_edge = centers[0] - (centers[1] - centers[0]) / 2
    last_edge = centers[-1] + (centers[-1] - centers[-2]) / 2
    return np.concatenate(([first_edge], midpoints, [last_edge]))


def make_log_uniform_bins(x_min, x_max, n_bins=50):
    """Create bin edges equally spaced in log scale."""
    return np.logspace(np.log10(x_min), np.log10(x_max), n_bins + 1)


def rebin_psd_log_uniform(x_values, y_values, bin_edges):
    """Rebin PSD data to given bin edges using linear interpolation of the CDF in log space.

    For each new bin [left, right], the fraction is the difference of the linearly
    interpolated cumulative distribution at the bin edges in log(x) space. This is
    equivalent to integrating the piecewise-linear PDF and is scale-invariant
    (avoids the unit-scaling problem of integrating y * dx in absolute x-units).

    Parameters
    ----------
    x_values : array-like
        Original x positions (positive values).
    y_values : array-like
        Original y values (raw fractions summing to ~1, not %).
    bin_edges : array-like
        New bin edges, must be sorted and positive.

    Returns
    -------
    new_y : np.ndarray
        New bin heights as pore volume fraction (%).
    bin_centers : np.ndarray
        Geometric mean centers of new bins.
    """
    x_values = np.asarray(x_values, dtype=float)
    y_values = np.asarray(y_values, dtype=float)
    bin_edges = np.asarray(bin_edges, dtype=float)

    if x_values.size == 0 or bin_edges.size < 2:
        return np.array([]), np.array([])

    sort_idx = np.argsort(x_values)
    x = x_values[sort_idx]
    y = y_values[sort_idx]

    valid = x > 0
    x, y = x[valid], y[valid]
    if x.size == 0:
        return np.array([]), np.array([])

    # Estimate original bin edges in log space to build a better CDF
    log_x = np.log(x)
    if log_x.size >= 2:
        log_midpoints = (log_x[:-1] + log_x[1:]) / 2
        log_first_edge = log_x[0] - (log_x[1] - log_x[0]) / 2
        log_last_edge = log_x[-1] + (log_x[-1] - log_x[-2]) / 2
        log_edges_orig = np.concatenate(([log_first_edge], log_midpoints, [log_last_edge]))
    else:
        log_edges_orig = np.array([log_x[0] - 0.1, log_x[0] + 0.1])

    cdf_y = np.concatenate(([0], np.cumsum(y)))

    log_edges_new = np.log(bin_edges)
    cdf_at_edges = np.interp(log_edges_new, log_edges_orig, cdf_y, left=0.0, right=cdf_y[-1])

    hist = np.diff(cdf_at_edges) * 100  # convert fraction to pore volume %
    bin_centers = np.sqrt(bin_edges[:-1] * bin_edges[1:])  # geometric mean
    return hist, bin_centers


def get_subres_function(pore_network, params):
    subres_model = params["subres_model_name"]
    subres_params = params["subres_params"]
    if (subres_model == "Throat Radius Curve" or subres_model == "Pressure Curve") and subres_params:
        params["subres_params"] = {
            i: np.asarray(subres_params[i]) if isinstance(subres_params[i], (list, np.ndarray)) else subres_params[i]
            for i in subres_params.keys()
        }
    model_logic = MODEL_DICT[params["subres_model_name"]]
    capillary_function = model_logic.get_capillary_radius_function(pore_network, params)
    return capillary_function
