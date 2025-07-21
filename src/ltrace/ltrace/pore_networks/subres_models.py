import numpy as np
import scipy as sp

HG_SURFACE_TENSION = 480  # 480N/km 0.48N/m 48e-5N/mm 48dyn/mm 480dyn/cm
HG_CONTACT_ANGLE = 140  # º


def estimate_radius(capilary_pressure):
    theta = (np.pi * HG_CONTACT_ANGLE) / 180.0
    return abs(2.0 * HG_SURFACE_TENSION * np.cos(theta)) / capilary_pressure


def estimate_pressure(radius):
    theta = (np.pi * HG_CONTACT_ANGLE) / 180.0
    return abs(2.0 * HG_SURFACE_TENSION * np.cos(theta)) / radius


class FixedRadiusLogic:
    required_params = ("radius",)

    def __init__(self):
        pass

    @classmethod
    def get_capillary_radius_function(cls, params, pore_network, volume):
        for required_param in cls.required_params:
            params[required_param]

        return lambda _: params["radius"]


class TruncatedGaussianLogic:
    required_params = (
        "mean radius",
        "standard deviation",
        "min radius",
        "max radius",
    )

    def __init__(self):
        pass

    @classmethod
    def get_capillary_radius_function(cls, params, pore_network, volume):
        for required_param in cls.required_params:
            params[required_param]

        loc = params["mean radius"]
        scale = params["standard deviation"]
        a_trunc = params["min radius"]
        b_trunc = params["max radius"]
        a, b = (a_trunc - loc) / scale, (b_trunc - loc) / scale
        return lambda _: sp.stats.truncnorm.rvs(a, b, size=1)[0] * scale + loc

    @classmethod
    def get_capillary_pressure_function(cls, params, pore_network, volume):
        for required_param in cls.required_params:
            params[required_param]

        pressure_func = cls.get_capillary_radius_function(
            params,
            pore_network,
            volume,
        )

        return lambda _: estimate_pressure(pressure_func(None))


class LeverettOldLogic:
    required_params = ("J", "Sw", "corey_a", "corey_b", "model")
    models = {
        "k = a * phi ** b": lambda a, b, phi: a * phi**b,
    }

    def __init__(self):
        pass

    @classmethod
    def get_capillary_radius_function(cls, params, pore_network, volume):
        for required_param in cls.required_params:
            params[required_param]

        total_pore_volume = pore_network["pore.region_volume"].sum()
        porosity = total_pore_volume / volume
        corey = cls.models[params["model"]](params["corey_a"], params["corey_b"], porosity)
        Pc = (params["J"] / 2) * estimate_pressure(np.sqrt(corey / porosity))

        radii = pore_network["throat.equivalent_diameter"] / 2
        resolved_throats = np.logical_and(
            pore_network["throat.phases"][:, 0],
            pore_network["throat.phases"][:, 1],
        )
        resolved_radii = radii[resolved_throats]
        smallest_raddi = resolved_radii.min()
        highest_pc = estimate_pressure(smallest_raddi)
        highest_pc_index = Pc >= highest_pc
        if highest_pc_index.sum() == 0:
            return lambda _: highest_pc

        porosity_cdf = cls._get_cumulative_dist_points(pore_network["throat.subresolution_porosity"])
        pressure_cdf = cls._get_cumulative_dist_function(
            Pc[highest_pc_index],
            params["Sw"][highest_pc_index],
        )

        def radius_function(phi):
            phi_position = np.interp(phi, porosity_cdf["x"], porosity_cdf["y"])
            estimated_pressure = np.interp(phi_position, pressure_cdf["y"], pressure_cdf["x"])
            return estimate_radius(estimated_pressure)

        return radius_function

    @classmethod
    def _get_cumulative_dist_function(cls, x, y):
        cumulative_y = np.zeros(x.size)
        for i in range(1, x.size):
            area = ((y[i] + y[i - 1]) / 2) * (x[i] - x[i - 1])
            cumulative_y[i] = cumulative_y[i - 1] + area
        cumulative_y /= cumulative_y[-1]
        return {"x": x, "y": cumulative_y}

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


class LeverettNewLogic:
    required_params = ("J", "Sw", "permeability")

    def __init__(self):
        pass

    @classmethod
    def get_capillary_radius_function(cls, params, pore_network, volume):
        for required_param in cls.required_params:
            params[required_param]

        total_pore_volume = pore_network["pore.region_volume"].sum()
        porosity = total_pore_volume / volume
        Pc = (params["J"] / 2) * estimate_pressure(params["permeability"] / porosity)

        radii = pore_network["throat.equivalent_diameter"] / 2
        resolved_throats = np.logical_and(
            pore_network["throat.phases"][:, 0],
            pore_network["throat.phases"][:, 1],
        )
        resolved_radii = radii[resolved_throats]
        smallest_raddi = resolved_radii.min()
        highest_pc = estimate_pressure(smallest_raddi)
        highest_pc_index = Pc >= highest_pc
        if highest_pc_index.sum() == 0:
            return lambda _: highest_pc

        porosity_cdf = cls._get_cumulative_dist_points(pore_network["throat.subresolution_porosity"])
        pressure_cdf = cls._get_cumulative_dist_function(
            Pc[highest_pc_index],
            params["Sw"][highest_pc_index],
        )

        def radius_function(phi):
            phi_position = np.interp(phi, porosity_cdf["x"], porosity_cdf["y"])
            estimated_pressure = np.interp(phi_position, pressure_cdf["y"], pressure_cdf["x"])
            return estimate_radius(estimated_pressure)

        return radius_function

    @classmethod
    def _get_cumulative_dist_function(cls, x, y):
        cumulative_y = np.zeros(x.size)
        for i in range(1, x.size):
            area = ((y[i] + y[i - 1]) / 2) * (x[i] - x[i - 1])
            cumulative_y[i] = cumulative_y[i - 1] + area
        cumulative_y /= cumulative_y[-1]
        return {"x": x, "y": cumulative_y}

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


class PressureCurveLogic:
    required_params = ("throat radii", "capillary pressure", "dsn", "smallest_raddi_multiplier")

    def __init__(self):
        pass

    @classmethod
    def get_capillary_radius_function(cls, params, pore_network, volume):
        for required_param in cls.required_params:
            params[required_param]
        pnm_radii = pore_network["throat.equivalent_diameter"] / 2

        resolved_throats = np.logical_and(
            pore_network["throat.phases"][:, 0] != 2,
            pore_network["throat.phases"][:, 1] != 2,
        )
        resolved_radii = pnm_radii[resolved_throats]
        if resolved_radii.size == 0:
            return lambda _: None

        smallest_resolved_raddi = resolved_radii.min()

        if params["throat radii"] is not None:
            subresolution_radii_bool_index = np.logical_and(
                params["throat radii"] > 1e-8,
                params["throat radii"] <= params["smallest_raddi_multiplier"] * smallest_resolved_raddi,
            )
            if subresolution_radii_bool_index.sum() == 0:
                return lambda _: smallest_resolved_raddi / 2
            elif subresolution_radii_bool_index.sum() == 1:
                return lambda _: params["throat radii"][subresolution_radii_bool_index][0]

            radius = params["throat radii"][subresolution_radii_bool_index]
            Pc = estimate_pressure(radius)
            Fvol = params["dsn"][subresolution_radii_bool_index]
        elif params["capillary pressure"] is not None:
            Pc = params["capillary pressure"]
            Fvol = params["dsn"]

        porosity_cdf = cls._get_cumulative_dist_points(pore_network["throat.subresolution_porosity"])
        pressure_cdf = cls._get_cumulative_dist_function(
            Pc,
            Fvol,
        )

        def radius_function(phi):
            phi_position = np.interp(phi, porosity_cdf["x"], porosity_cdf["y"])
            estimated_pressure = np.interp(phi_position, pressure_cdf["y"], pressure_cdf["x"])
            return estimate_radius(estimated_pressure)

        return radius_function

    @classmethod
    def _get_cumulative_dist_function(cls, x, y):
        cumulative_y = np.zeros(x.size)
        for i in range(1, x.size):
            area = ((y[i] + y[i - 1]) / 2) * (x[i] - x[i - 1])
            cumulative_y[i] = cumulative_y[i - 1] + area
        cumulative_y /= cumulative_y[-1]
        return {"x": x, "y": cumulative_y}

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


MODEL_DICT = {
    "Fixed Radius": FixedRadiusLogic(),
    "Truncated Gaussian": TruncatedGaussianLogic(),
    "Pressure Curve": PressureCurveLogic(),
    "Throat Radius Curve": PressureCurveLogic(),
    "Leverett Function - Permeability curve": LeverettOldLogic(),
    "Leverett Function - Sample Permeability": LeverettNewLogic(),
}


def set_subres_model(pore_network, params):
    x_size = params["sizes"]["x"]
    y_size = params["sizes"]["y"]
    z_size = params["sizes"]["z"]
    volume = x_size * y_size * z_size

    subres_model = params["subres_model_name"]
    subres_params = params["subres_params"]

    if (subres_model == "Throat Radius Curve" or subres_model == "Pressure Curve") and subres_params:
        subres_params = {
            i: np.asarray(subres_params[i]) if subres_params[i] is not None else None for i in subres_params.keys()
        }

    subresolution_function = MODEL_DICT[subres_model].get_capillary_radius_function(subres_params, pore_network, volume)

    return subresolution_function
