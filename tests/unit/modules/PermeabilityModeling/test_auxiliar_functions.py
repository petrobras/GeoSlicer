from PermeabilityModeling.PermeabilityModelingCLI.PermeabilityModelingLib import auxiliar_functions as aux
import pytest
import numpy as np


def test_error_correction_init():
    kdsOptimization = aux.KdsOptimization(startDepth=1, stopDepth=10, kDst=1, kRro=2)

    assert kdsOptimization.startDepth == 1
    assert kdsOptimization.stopDepth == 10
    assert kdsOptimization.kDst == 1
    assert kdsOptimization.kRro == 2
    assert kdsOptimization.depthInterval == 9


@pytest.mark.parametrize(
    "startDepth, stopDepth, kDst, kRro, depthArray, kiArray, expectedKiH",
    [
        pytest.param(1, 10, 0, 0, np.array([6]), np.array([1]), 0.0, id="single_depth_value"),
        pytest.param(1, 10, 0, 0, np.array([11, 20]), np.array([1, 1]), 0.0, id="error_correction_outside_depth_array"),
        pytest.param(1, 10, 0, 0, np.array([1, 5]), np.array([1, 1]), 4.0, id="depth_array_within_start_stop"),
        pytest.param(1, 10, 0, 0, np.array([6, 10]), np.array([1, 1]), 4.0, id="depth_array_goes_beyond"),
        pytest.param(5, 10, 0, 0, np.array([1, 10]), np.array([1, 1]), 5.0, id="start_stop_within_depth_array"),
        pytest.param(
            1, 10, 0, 0, np.array([6, 20]), np.array([1, 1]), 5.0, id="part_of_error_correction_within_depth_array"
        ),
        pytest.param(
            15, 25, 0, 0, np.array([6, 20]), np.array([1, 1]), 5.0, id="part_of_error_correction_within_depth_array_2"
        ),
        pytest.param(
            1,
            10,
            0,
            0,
            np.array([1, 3, 5]),
            np.array([1, 1, 1]),
            4.0,
            id="depth_array_within_start_stop_many_ki_values",
        ),
        pytest.param(
            1, 10, 0, 0, np.array([6, 7, 10]), np.array([1, 1, 1]), 4.0, id="depth_array_goes_beyond_many_ki_values"
        ),
        pytest.param(
            1,
            10,
            0,
            0,
            np.array([1, 5, 10]),
            np.array([1, 2, 1]),
            12,
            id="start_stop_within_depth_array_many_ki_values",
        ),
        pytest.param(
            1,
            10,
            0,
            0,
            np.array([6, 10, 20]),
            np.array([1, 1, 1]),
            4.0,
            id="part_of_error_correction_within_depth_array_many_ki_values",
        ),
        pytest.param(
            15,
            25,
            0,
            0,
            np.array([6, 17, 20]),
            np.array([1, 1, 1]),
            5.0,
            id="part_of_error_correction_within_depth_array_2_many_ki_values",
        ),
    ],
)
def test_error_correction_calculate_ki(startDepth, stopDepth, kDst, kRro, depthArray, kiArray, expectedKiH):
    kdsOptimization = aux.KdsOptimization(startDepth=startDepth, stopDepth=stopDepth, kDst=kDst, kRro=kRro)
    assert np.isclose(kdsOptimization.calculateKiH(kiArray=kiArray, depthArray=depthArray), expectedKiH)
