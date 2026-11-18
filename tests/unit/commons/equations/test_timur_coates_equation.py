import pytest

import numpy as np

from commons.slicer.equations.timur_coates_equation import TimurCoatesEquation


class TestTimurCoatesEquation:
    def setup_method(self):
        self.equation = TimurCoatesEquation()

    @pytest.mark.parametrize(
        "mock_params_dict",
        [
            pytest.param({"d": 1}, id="invalid_parameter"),
            pytest.param({}, id="empty_parameters_dict"),
            pytest.param({"A": 1.97, "B": -0.11, "D": 0.46}, id="one_wrong_parameter"),
        ],
    )
    def test_equation_invalid_inputs(self, mock_params_dict):
        result = self.equation.equation(1, mock_params_dict)
        assert np.isnan(result)

    def test_equation_valid_inputs(self):
        result = self.equation.equation(1, {"A": 1.97, "B": -0.11, "C": 0.46})
        expected = 2.1081568
        assert np.isclose(result, expected), f"Expected: {expected} - Actual: {result}"
