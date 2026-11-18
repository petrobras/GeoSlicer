import unittest

import numpy as np

from commons.pore_networks.krel_result import KrelParameterParser, KrelTables


class TestKrelTables(unittest.TestCase):
    def test_interpolation(self):
        interpolated_x = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], np.float64)
        x_values = np.array([0.05, 0.15, 0.25, 0.35, 0.45], np.float64)
        y_values = np.array([0.1, 0.2, 0.3, 0.4, 0.5], np.float64)
        interpolated_y = KrelTables._interpolate(interpolated_x, x_values, y_values)

        expected_y = np.array([0.1, 0.15, 0.25, 0.35, 0.45, 0.5, np.nan, np.nan, np.nan, np.nan, np.nan], np.float64)

        np.testing.assert_array_almost_equal(interpolated_y, expected_y)


class TestKrelParameterParser(unittest.TestCase):
    def test_regex(self):
        krel_parameter_parser = KrelParameterParser()
        self.assertEqual(krel_parameter_parser.get_input_name("input-test0"), "test0")
        self.assertEqual(krel_parameter_parser.get_result_name("result-test1"), "test1")
        self.assertEqual(krel_parameter_parser.get_error_name("error-test2"), "test2")
