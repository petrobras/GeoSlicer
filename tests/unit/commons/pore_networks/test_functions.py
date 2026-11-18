import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

import numpy as np

from commons.pore_networks.functions_extract import get_connected_geo_network, geo2pnf, geo2spy, get_sub_spy
from commons.pore_networks.functions_simulation import (
    manual_valvatne_blunt,
    set_subresolution_conductance,
    single_phase_permeability,
    get_flow_rate,
)


def create_custom_node(cls_name: str, attributes: dict):
    mock = MagicMock()
    mock.__class__ = cls_name

    def MockGetAttributes(attr: str):
        return attributes.get(attr, None)

    def MockGetName():
        return cls_name

    mock.GetAttribute = MockGetAttributes
    mock.GetName = MockGetName

    return mock


class TestPoreNetworkFunctions(unittest.TestCase):
    pore_dict = {
        "pore.all": np.array([0, 1, 2]),
        "pore.surface_area": np.array([0.04, 0.05, 0.06]),
        "pore.coords_0": np.array([1, 1, 1]),
        "pore.coords_1": np.array([1, 1, 1]),
        "pore.coords_2": np.array([1, 1, 1]),
        "pore.geometric_centroid_0": np.array([1, 1, 1]),
        "pore.geometric_centroid_1": np.array([2, 2, 1]),
        "pore.geometric_centroid_2": np.array([3, 2, 0]),
        "pore.equivalent_diameter": np.array([0.04, 0.05, 0.06]),
        "pore.extended_diameter": np.array([0.04, 0.05, 0.06]),
        "pore.xmin": np.array([True, False, False]),
        "pore.xmax": np.array([False, True, False]),
        "pore.ymin": np.array([True, False, True]),
        "pore.ymax": np.array([True, False, False]),
        "pore.zmin": np.array([False, True, False]),
        "pore.zmax": np.array([False, True, False]),
        "pore.phase": np.array([1, 1, 2]),
        "pore.subresolution_porosity": np.array([1, 1, 0.5]),
        "pore.number_of_capilaries": np.array([1, 2, 2]),
        "pore.cap_radius": np.array([0.01, 0.02, 0.03]),
        "pore.volume": np.array([0.01, 0.02, 0.03]),
    }

    throat_dict = {
        "throat.all": np.array([1, 2, 3]),
        "throat.conns_0": np.array([0, 1, 2]),
        "throat.conns_1": np.array([1, 2, 0]),
        "throat.inscribed_diameter": np.array([0.01, 0.02, 0.03]),
        "throat.equivalent_diameter": np.array([0.01, 0.02, 0.03]),
        "throat.cross_sectional_area": np.array([0.1, 0.2, 0.6]),
        "throat.perimeter": np.array([0.01, 0.02, 0.03]),
        "throat.direct_length": np.array([0.4, 0.5, 0.3]),
        "throat.phases_0": np.array([1, 2, 2]),
        "throat.phases_1": np.array([1, 2, 2]),
        "throat.phases_2": np.array([1, 2, 2]),
        "throat.cap_radius": np.array([0.01, 0.02, 0.03]),
        "throat.mid_length": np.array([0.01, 0.02, 0.03]),
        "throat.number_of_capilaries": np.array([1, 2, 2]),
        "throat.conns_0_length": np.array([0.01, 0.02, 0.03]),
        "throat.conns_1_length": np.array([0.01, 0.02, 0.03]),
        "throat.subresolution_porosity": np.array([1, 1, 0.5]),
        "throat.total_length": np.array([0.01, 0.02, 0.03]),
    }

    spy_network = {
        "throat.all": np.array([1, 2, 3]),
        "throat.shape_factor": np.array([0.04, 0.06, 0.1]),
        "throat.inscribed_diameter": np.array([0.01, 0.02, 0.03]),
        "throat.equivalent_diameter": np.array([0.01, 0.02, 0.03]),
        "throat.cross_sectional_area": np.array([0.1, 0.2, 0.6]),
        "throat.cap_radius": np.array([0.01, 0.02, 0.03]),
        "throat.number_of_capilaries": np.array([1, 2, 2]),
        "throat.conns_0_length": np.array([0.5, 0.4, 0.6]),
        "throat.conns_1_length": np.array([0.5, 0.4, 0.6]),
        "throat.conns": np.array([[0, 1], [1, 2], [2, 0]]),
        "throat.mid_length": np.array([0.4, 0.5, 0.6]),
        "throat.phases": np.array([[1, 2, 2], [1, 2, 2], [1, 2, 2]]),
        "throat.subresolution_porosity": np.array([1, 1, 0.5]),
        "throat.total_length": np.array([0.01, 0.02, 0.03]),
        "pore.shape_factor": np.array([0.4, 0.5, 0.6]),
        "pore.equivalent_diameter": np.array([0.04, 0.05, 0.06]),
        "pore.extended_diameter": np.array([0.04, 0.05, 0.06]),
        "pore.xmin": np.array([True, False, False]),
        "pore.xmax": np.array([False, True, False]),
        "pore.ymin": np.array([True, False, True]),
        "pore.ymax": np.array([True, False, False]),
        "pore.zmin": np.array([False, True, False]),
        "pore.zmax": np.array([False, True, False]),
        "pore.phase": np.array([1, 1, 2]),
        "pore.phase2": np.array([False, False, True]),
        "pore.subresolution_porosity": np.array([1, 1, 0.5]),
        "pore.number_of_capilaries": np.array([1, 2, 2]),
        "pore.cap_radius": np.array([0.01, 0.02, 0.03]),
        "pore.volume": np.array([0.01, 0.02, 0.03]),
    }

    def test_geo2spy(self):
        network = geo2spy(self.pore_dict, self.throat_dict)

        template_keys = set(["pore.all", "pore.geometric_centroid", "throat.all", "throat.conns"])
        self.assertTrue(template_keys.issubset(network.keys()))

        self.assertTrue(network["pore.geometric_centroid"].shape == (3, 3))
        self.assertTrue(network["throat.conns"].shape == (3, 2))

    @patch("commons.pore_networks.functions_extract.geo2spy", return_value=spy_network.copy())
    @patch(
        "commons.pore_networks.functions_extract.get_connected_geo_network",
        return_value=([True], [True]),
    )
    @patch("commons.pore_networks.functions_extract.get_sub_geo")
    def test_geo2pnf(self, mock_get_sub_geo, mock_get_connected_geo_network, mock_geo2spy):
        mock_get_sub_geo.return_value = (self.pore_dict, self.throat_dict)

        params = {
            "extraction_algorithm": "porespy",
            "size": {"x": 100, "y": 100, "z": 100},
            "edge_throats": "x",
        }

        def subresolution_function(r):
            return r**2

        pnf = geo2pnf(
            self.pore_dict,
            self.throat_dict,
            subresolution_function,
            params["extraction_algorithm"],
            params["size"],
            edge_throats=params["edge_throats"],
        )

        expected_pnf = set(["link1", "link2", "node1", "node2"])
        self.assertTrue(expected_pnf.issubset(pnf))

    def test_manual_valvatne_blunt(self):
        manual_valvatne_blunt(self.spy_network)
        template_keys = set(
            [
                "throat.manual_valvatne_conductivity",
                "throat.manual_valvatne_conductance",
                "pore.manual_valvatne_conductivity",
                "pore.shape",
                "throat.shape",
            ]
        )
        self.assertTrue(template_keys.issubset(self.spy_network.keys()))

    def test_set_subresolution_conductance(self):
        def subresolution_function(r):
            return r**2

        set_subresolution_conductance(self.spy_network, subresolution_function, 1.0, 0.04)
        template_keys = set(
            [
                "throat.cap_pressure",
                "throat.cap_radius",
                "throat.sub_conductivity",
                "throat.manual_valvatne_conductance_former",
                "throat.manual_valvatne_conductance",
                "throat.number_of_capilaries",
                "pore.cap_pressure",
                "pore.cap_radius",
                "pore.sub_conductivity",
                "pore.number_of_capilaries",
            ]
        )
        self.assertTrue(template_keys.issubset(self.spy_network.keys()))

    def test_get_connected_geo_network(self):
        for axis in ("x", "y", "z"):
            pore_dict, throat_dict = get_connected_geo_network(
                self.pore_dict, self.throat_dict, f"{axis}min", f"{axis}max"
            )
            self.assertTrue(pore_dict.all())
            self.assertTrue(throat_dict.all())

    def test_get_sub_spy(self):
        sub_pn = get_sub_spy(self.spy_network, [True, False, True], [True, False, True])
        template_sub = set(
            [
                "throat.shape_factor",
                "throat.inscribed_diameter",
                "throat.cross_sectional_area",
                "throat.conns_0_length",
                "throat.conns_1_length",
                "throat.conns",
                "throat.mid_length",
                "pore.shape_factor",
                "pore.extended_diameter",
            ]
        )
        self.assertTrue(template_sub.issubset(sub_pn))

    def test_single_phase_permeability(self):
        def subresolution_function(r):
            return r**2

        results = single_phase_permeability(self.spy_network, subresolution_function=subresolution_function)

        template1 = set(
            {
                "pore.extended_diameter",
                "pore.manual_valvatne_conductivity",
                "pore.shape",
                "pore.shape_factor",
                "pore.contact_angle",
                "pore.density",
                "pore.molar_density",
                "pore.pressure",
                "pore.surface_tension",
                "pore.temperature",
                "pore.thermal_conductivity",
                "pore.vapor_pressure",
                "pore.viscosity",
                "pore.bc.rate",
                "pore.bc.value",
            }
        )
        template2 = set(
            {
                "throat.conns_0",
                "throat.conns_1",
                "throat.conns_0_length",
                "throat.conns_1_length",
                "throat.cross_sectional_area",
                "throat.hydraulic_conductance",
                "throat.inscribed_diameter",
                "throat.manual_valvatne_conductance",
                "throat.manual_valvatne_conductivity",
                "throat.mid_length",
                "throat.shape",
                "throat.shape_factor",
            }
        )

        self.assertTrue(template1.issubset(results[1]))
        self.assertTrue(template2.issubset(results[2]))

    def test_get_flow_rate(self):
        pn_pores = {
            "pore.inlets": np.array([True, False, False]),
            "pore.outlets": np.array([False, False, True]),
            "pore.pressure": np.array([101325.0, 50000.0, 0.0]),
        }
        pn_throats = {
            "throat.all": np.array([0, 1]),
            "throat.conns_0": np.array([0, 1]),
            "throat.conns_1": np.array([1, 2]),
            "throat.conductance": np.array([0.000001, 0.000001]),
            "throat.conns": np.array([[0, 1], [1, 2]]),
        }

        flow_rate = get_flow_rate(pn_pores, pn_throats, pressure_drop=101325.0, viscosity=1.0)
        self.assertAlmostEqual(flow_rate, 0.0506625)
        flow_rate = get_flow_rate(pn_pores, pn_throats, pressure_drop=101.325, viscosity=1.0)
        self.assertAlmostEqual(flow_rate, 0.0000506625)
        flow_rate = get_flow_rate(pn_pores, pn_throats, pressure_drop=101325.0, viscosity=10.0)
        self.assertAlmostEqual(flow_rate, 0.00506625)
