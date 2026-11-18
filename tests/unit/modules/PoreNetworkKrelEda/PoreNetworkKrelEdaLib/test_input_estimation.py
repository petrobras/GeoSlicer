import unittest

import pandas as pd

from PoreNetworkKrelEda.PoreNetworkKrelEdaLib.input_estimation import (
    CurveFilter,
    ErrorToReferences,
    get_closest_row,
    filter_simulations,
)


class TestInputEstimation(unittest.TestCase):
    def test_closest_column_to_single_reference(self):
        ref_simulation_result_df_list = [pd.DataFrame({"A": [0.5], "B": [0.8], "C": [0.51]})]
        filtered_simulations_df = pd.DataFrame({"A": [0.5, 0.5, 0.5], "B": [0.8, 0.1, 0.8], "C": [0.53, 0.52, 0.499]})
        error_to_reference = ErrorToReferences(ref_simulation_result_df_list, filtered_simulations_df)
        self.assertEqual(error_to_reference.getMinimalErrorId(["C"]), 1)

    def test_multiple_columns_to_single_reference(self):
        ref_simulation_result_df_list = [pd.DataFrame({"A": [0.5], "B": [0.8], "C": [0.51]})]
        filtered_simulations_df = pd.DataFrame({"A": [0.5, 0.5, 0.5], "B": [0.8, 0.1, 0.8], "C": [0.53, 0.52, 0.499]})
        error_to_reference = ErrorToReferences(ref_simulation_result_df_list, filtered_simulations_df)
        self.assertEqual(error_to_reference.getMinimalErrorId(["B", "C"]), 2)

    def test_multiple_columns_to_multiple_references(self):
        ref_simulation_result_df_list = [
            pd.DataFrame({"A": [0.5], "B": [0.8], "C": [0.51]}),
            pd.DataFrame({"A": [0.6], "B": [0.8], "C": [0.53]}),
        ]
        filtered_simulations_df = pd.DataFrame({"A": [0.5, 0.5, 0.6], "B": [0.8, 0.1, 0.8], "C": [0.53, 0.52, 0.525]})
        error_to_reference = ErrorToReferences(ref_simulation_result_df_list, filtered_simulations_df)
        self.assertEqual(error_to_reference.getMinimalErrorId(["B", "C"]), 2)

    def test_multiple_columns_to_composed_reference(self):
        ref_simulation_result_df_list = [
            pd.DataFrame({"A": [0.5, 0.6], "B": [0.8, 0.8], "C": [0.51, 0.53]}),
        ]
        filtered_simulations_df = pd.DataFrame({"A": [0.5, 0.5, 0.6], "B": [0.8, 0.1, 0.8], "C": [0.53, 0.52, 0.525]})
        error_to_reference = ErrorToReferences(ref_simulation_result_df_list, filtered_simulations_df)
        self.assertEqual(error_to_reference.getMinimalErrorId(["B", "C"]), 2)

    def test_simulation_filter(self):
        simulations_df = pd.DataFrame(
            {
                "A": [0.54, 0.55, 0.53],
                "B": [0.2, 0.1, 0.3],
                "C": [0.6, 0.8, 0.7],
            }
        )

        curve_filter_list = []

        filter = CurveFilter()
        filter.column_name = "A"
        filter.min_value = 0.52
        filter.max_value = 0.55
        curve_filter_list.append(filter)

        filter = CurveFilter()
        filter.column_name = "B"
        filter.min_value = 0.2
        filter.max_value = 0.3
        curve_filter_list.append(filter)

        self.assertEqual(filter_simulations(simulations_df, curve_filter_list), [0, 2])

    def test_estimate(self):
        simulations_df = pd.DataFrame(
            {
                "input-A": [0.54, 0.55, 0.53],
                "input-B": [0.2, 0.1, 0.3],
                "input-C": [0.6, 0.8, 0.7],
            }
        )
        estimated_row = get_closest_row(simulations_df, {"input-B": [0.11, 0.2]})
        self.assertTrue(simulations_df.iloc[0].equals(estimated_row))
