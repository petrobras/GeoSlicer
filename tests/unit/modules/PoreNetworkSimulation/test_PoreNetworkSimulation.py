"""
from PySide2.QtWidgets import QLabel
from PoreNetworkSimulation.PoreNetworkSimulationWidget import BaseEditWidget

@pytest.fixture
def label(qtbot):
    qlabel = BaseEditWidget()
    qtbot.addWidget(qlabel)
    return qlabel

def test_label(label):
    assert True
"""

import unittest

import copy
import numpy as np

from commons.pore_networks.subres_models import *


class TestMercurySimulationLogic(unittest.TestCase):
    net = {
        "throat.phases": np.array([[2, 2], [1, 2], [1, 1], [0, 0]]),
        "throat.inscribed_diameter": np.array([0.001, 0.2, 4, 10]),
        "throat.equivalent_diameter": np.array([0.001, 0.2, 0.4, 0.8]),
        "throat.subresolution_porosity": np.array([0.1, 0.2, 0.6, 1.0]),
        "throat.total_length": np.array([0.1, 0.2, 0.6, 0.9]),
        "throat.cross_sectional_area": np.array([0.1, 0.2, 0.6, 0.9]),
        "pore.volume": np.array([0.1, 0.2, 0.6, 0.9]),
        "pore.subresolution_porosity": np.array([0.1, 0.2, 1.0, 1.0]),
        "pore.region_volume": np.array([0.1, 0.2, 0.6, 0.9]),
    }

    def test_radius_pressure_conversion(self):
        inputs = np.array([0.1, 200.0, 40000.0])
        template = np.array([7354.026654, 3.677013, 0.018385])

        pressure = estimate_pressure(inputs)
        self.assertTrue(np.allclose(pressure, template))

        radii = estimate_radius(pressure)
        self.assertTrue(np.allclose(radii, inputs))

    def test_FixedRadiusLogic(self):
        scalar_volume_data = {
            "size": {
                "x": 1.0,
                "y": 1.0,
                "z": 1.0,
            },
            "spacing": {
                "x": 0.5,
                "y": 0.5,
                "z": 0.5,
            },
        }

        params = {"subres_params": {"radius": 0.1}}

        params.update(scalar_volume_data)

        logic = FixedRadiusLogic()
        func = logic.get_capillary_radius_function(self.net, params)

        inputs = np.array([0.1, 0.3, 0.7, 0.9])
        self.assertTrue(np.allclose(func(inputs), 0.1))

    def test_LeverettOldLogic(self):
        scalar_volume_data = {
            "size": {
                "x": 1.0,
                "y": 1.0,
                "z": 1.0,
            },
            "spacing": {
                "x": 0.5,
                "y": 0.5,
                "z": 0.5,
            },
        }

        params = {
            "subres_params": {
                "J": 200.0,
                "Sw": np.array([0.1, 0.2, 0.5, 0.8]),
                "corey_a": 0.5,
                "corey_b": 0.3,
                "model": "k = a * phi ** b",
            }
        }

        params.update(scalar_volume_data)

        logic = LeverettOldLogic()
        func = logic.get_capillary_radius_function(self.net, params)

        inputs = np.array([0.1, 0.3, 0.7, 0.9])
        results = 1470805.3307884375
        self.assertTrue(np.allclose(func(inputs), results))

    def test_LeverettNewLogic(self):
        scalar_volume_data = {
            "size": {
                "x": 1.0,
                "y": 1.0,
                "z": 1.0,
            },
            "spacing": {
                "x": 0.5,
                "y": 0.5,
                "z": 0.5,
            },
        }

        params = {
            "subres_params": {
                "J": 200.0,
                "Sw": np.array([0.1, 0.2, 0.5, 0.8]),
                "permeability": 0.2,
            }
        }

        params.update(scalar_volume_data)

        net = copy.deepcopy(self.net)
        net["pore.region_volume"] = np.array([0.00005, 0.0001, 0.0001, 0.00025])

        logic = LeverettNewLogic()
        func = logic.get_capillary_radius_function(net, params)

        inputs = np.array([0.1, 0.3, 0.7, 0.9])
        results = 1470805.3307884375
        self.assertTrue(np.allclose(func(inputs), results))

    def test_PressureCurveLogic_capillaryPressure(self):
        params = {}

        scalar_volume_data = {
            "size": {
                "x": 1.0,
                "y": 1.0,
                "z": 1.0,
            },
            "spacing": {
                "x": 0.5,
                "y": 0.5,
                "z": 0.5,
            },
        }

        subres_params = {
            "throat radii": None,
            "capillary pressure": np.array([0.001, 0.2, 0.5, 0.8]),
            "dsn": np.array([0.1, 0.5, 1.0, 0.07]),
            "radii_cutoff_mm": 1,
        }

        params.update(scalar_volume_data)
        params["subres_params"] = subres_params

        logic = PressureCurveLogic()
        func = logic.get_capillary_radius_function(self.net, params)

        inputs = np.array([0.1, 0.3, 0.7, 0.9])
        results = np.array([5773.97766572, 2718.67898482, 1858.25057585, 1858.25057585])
        self.assertTrue(np.allclose(func(inputs), results))

    def test_PressureCurveLogic_throatRadii(self):
        params = {}

        scalar_volume_data = {
            "size": {
                "x": 1.0,
                "y": 1.0,
                "z": 1.0,
            },
            "spacing": {
                "x": 0.5,
                "y": 0.5,
                "z": 0.5,
            },
        }

        subres_params = {
            "throat radii": np.array([0.001, 0.2, 0.5, 0.8]),
            "capillary pressure": None,
            "dsn": np.array([0.1, 0.5, 1.0, 0.07]),
            "radii_cutoff_mm": 1,
        }

        params.update(scalar_volume_data)
        params["subres_params"] = subres_params

        logic = PressureCurveLogic()
        func = logic.get_capillary_radius_function(self.net, params)

        inputs = np.array([0.1, 0.3, 0.7, 0.9])
        results = np.array([0.66197766, 0.54832077, 0.32310178, 0.32310178])
        self.assertTrue(np.allclose(func(inputs), results))
