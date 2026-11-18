import pytest

import numpy as np

from commons.slicer.equations.line_equation import LineEquation


class TestLineEquation:
    def setup_method(self):
        self.line_equation = LineEquation()

    def test_calc_r_squared_a(self):
        x = np.array([1, 2, 3, 4, 5])
        y = np.array([1.9, 3.7, 5.8, 8.0, 9.6])
        r_squared = self.line_equation.get_r_squared(x, y, {"m": 1.97, "b": -0.11})
        assert r_squared == pytest.approx(0.998, 0.0005)

    @pytest.mark.parametrize(
        "mock_params_dict",
        [
            pytest.param({"d": 1}, id="invalid_parameter"),
            pytest.param({}, id="empty_parameters_dict"),
            pytest.param({"m": 1.97, "d": -0.11}, id="one_wrong_parameter"),
        ],
    )
    def test_equation_invalid_inputs(self, mock_params_dict):
        result = self.line_equation.equation(1, mock_params_dict)
        assert np.isnan(result)

    def test_equation_valid_inputs(self):
        result = self.line_equation.equation(1, {"m": 1.97, "b": -0.11})
        expected = 1.86
        assert np.isclose(result, expected), f"Expected: {expected} - Actual: {result}"
