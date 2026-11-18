import numpy as np
from commons.slicer.equations.equation_base import EquationBase


class TestEquationBase:
    def test_equation_method_any_class(self):
        result = EquationBase().equation(1, {"m": 1})
        assert np.isnan(result)
