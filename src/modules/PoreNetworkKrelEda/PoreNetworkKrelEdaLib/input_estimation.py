import numpy as np
import pandas as pd
from scipy import optimize
from sklearn import preprocessing, linear_model

from ltrace.pore_networks.krel_result import INPUT_PREFIX, KrelParameterParser, RESULT_PREFIX
from ltrace.pore_networks.pnflow_parameter_defs import PARAMETERS


def closest_estimate(parameters_df, output_ranges):
    estimated_inputs = get_closest_row(parameters_df, output_ranges)

    parameter_dict = {}
    for row_name, row_data in estimated_inputs.to_frame().iterrows():
        value = list(row_data)[0]
        parameter_dict[row_name] = {
            "start": value,
            "stop": value,
            "steps": 1,
        }

    return parameter_dict


def get_closest_row(parameters_df, output_ranges):
    df = parameters_df
    closest_row = None
    closest_sse = None
    number_of_simulations = len(df.index)
    for i in range(number_of_simulations):
        row = df.iloc[i]
        sse = get_SSE(row, output_ranges)
        if closest_sse is None or sse < closest_sse:
            closest_row = row
            closest_sse = sse

    return closest_row.filter(like="input")


def get_SSE(row, ranges):
    sse = 0
    for column in ranges.keys():
        mid = (ranges[column][0] + ranges[column][1]) / 2
        normalization_factor = (ranges[column][1] - ranges[column][0]) / 2
        delta = (row[column] - mid) / normalization_factor
        sse += delta**2
    return sse


class ErrorToReference:
    def __init__(self, ref_simulation_result_df: pd.DataFrame, filtered_simulations_df: pd.DataFrame):
        self.ref_simulation_result_df = ref_simulation_result_df
        self.filtered_simulations_df = filtered_simulations_df

    def getErrorFromColumns(self, column_name_list: list) -> np.ndarray:
        error_ratio_array = np.array([0.0] * self.filtered_simulations_df.shape[0])
        for column_name in column_name_list:
            error_ratio_array += self.__getErrorFromColumn(column_name)
        return error_ratio_array

    def __getErrorFromColumn(self, column_name: str) -> np.ndarray:
        error_ratio_array = np.array([0.0] * self.filtered_simulations_df.shape[0])
        for row_id in range(self.ref_simulation_result_df[column_name].shape[0]):
            error_ratio_array += self.__getErrorFromRow(column_name, row_id) ** 2
        return error_ratio_array

    def __getErrorFromRow(self, column_name: str, row: int) -> np.ndarray:
        ref_simulation_result = float(self.ref_simulation_result_df[column_name][row])
        filtered_simulations_results = np.array(list(self.filtered_simulations_df[column_name]))
        if False:  # Error method
            return self.__getSimulationError(ref_simulation_result, filtered_simulations_results)
        else:
            return self.__getSimulationDiff(ref_simulation_result, filtered_simulations_results)

    def __getSimulationError(
        self, ref_simulation_result: float, filtered_simulations_results: np.ndarray
    ) -> np.ndarray:
        filtered_value_range = np.nanmax(filtered_simulations_results) - np.nanmin(filtered_simulations_results)
        reference_error = np.absolute(ref_simulation_result - filtered_simulations_results)
        error_ratio = reference_error / filtered_value_range
        return error_ratio

    def __getSimulationDiff(self, ref_simulation_result: float, filtered_simulations_results: np.ndarray) -> np.ndarray:
        reference_error = np.absolute(ref_simulation_result - filtered_simulations_results)
        return reference_error


class ErrorToReferences:
    def __init__(self, ref_simulation_result_df_list: list, filtered_simulations_df: pd.DataFrame):
        self.ref_simulation_result_df_list = ref_simulation_result_df_list
        self.filtered_simulations_df = filtered_simulations_df

    def getMinimalErrorId(self, column_list: list) -> int:
        error_array = self.getErrors(column_list)
        return np.argmin(error_array)

    def getErrors(self, column_list: list) -> np.ndarray:
        simulation_error_sum = np.array([0.0] * self.filtered_simulations_df.shape[0])
        for ref_simulation_result_df in self.ref_simulation_result_df_list:
            filter = ErrorToReference(ref_simulation_result_df, self.filtered_simulations_df)
            simulation_error = filter.getErrorFromColumns(column_list)
            simulation_error_sum += simulation_error
        return simulation_error_sum


class CurveFilter:
    def __init__(self):
        self.column_name = ""
        self.min_value = 0
        self.max_value = 0


def filter_simulations(parameters_df, curve_filter_list):
    number_of_rows = parameters_df.shape[0]
    filter_bool_index = np.array([True] * number_of_rows)
    for filter in curve_filter_list:
        column_name = filter.column_name
        min = filter.min_value
        max = filter.max_value

        if column_name in parameters_df.columns:
            filter_bool_index &= (parameters_df[column_name] >= min) & (parameters_df[column_name] <= max)
    return list(np.where(filter_bool_index)[0])


def regression_estimate(df, reference_curves):
    input_columns = [i for i in df.columns if INPUT_PREFIX in i]
    result_columns = [i for i in df.columns if RESULT_PREFIX in i and "-pc_" not in i]

    # Get the variables whose values differ between simulations
    independent_variables = []
    fixed_variables = []
    for column in input_columns:
        n_of_vals = np.unique(df[column]).size
        if n_of_vals > 1:
            independent_variables.append(column)
        else:
            fixed_variables.append(column)

    multiplier = preprocessing.PolynomialFeatures()

    n_rows = len(df.index)
    n_variables = len(independent_variables)
    coef_array = np.empty((n_rows, n_variables), dtype=np.float32)
    for i, column in enumerate(independent_variables):
        coef_array[:, i] = df[column]

    second_order_array = multiplier.fit_transform(coef_array)
    powers = multiplier.powers_

    # regression
    regressions = {}
    for result in result_columns:
        rgr_ridge = linear_model.LinearRegression()
        if not np.isnan(np.array(df[result])).any():
            rgr_ridge.fit(second_order_array, df[result])
            rec_l2 = rgr_ridge.coef_
            regressions[result] = rec_l2
        else:
            print(f"warning: result {result} could not be used in estimation")

    # Bounds
    parameter_constrainer = ParameterConstrainer()

    initial_guess = []
    bounds = []
    for i, column in enumerate(independent_variables):
        min_val = df[column].min()
        max_val = df[column].max()
        mean_val = df[column].mean()
        initial_guess.append(mean_val)
        lower_bound = min_val - (max_val - min_val)
        upper_bound = max_val + (max_val - min_val)

        lower_bound = parameter_constrainer.get_value(column, lower_bound)
        upper_bound = parameter_constrainer.get_value(column, upper_bound)

        bounds.append((lower_bound, upper_bound))

    # Minimize
    def objective_function(x, *args):
        sse = 0
        for result_name in regressions.keys():
            result = 0
            for i in range(powers.shape[0]):
                coef_power = powers[i, :]
                sub_result = regressions[result_name][i]
                for j in range(coef_power.size):
                    sub_result *= x[j] ** coef_power[j]
                result += sub_result
            for curve in reference_curves:
                sse += (result - curve[result_name].iloc[0]) ** 2
        return sse

    minimized = optimize.minimize(objective_function, initial_guess, bounds=bounds)

    parameter_dict = {}
    for i, variable in enumerate(independent_variables):
        minimized_value = minimized.x[i]
        std_deviation = np.std(list(df[variable])) * 2
        parameter_dict[variable] = {
            "start": parameter_constrainer.get_value(variable, minimized_value - std_deviation),
            "stop": parameter_constrainer.get_value(variable, minimized_value + std_deviation),
            "steps": 3,
        }
    for variable in fixed_variables:
        value = df[variable].iloc[0]
        parameter_dict[variable] = {
            "start": value,
            "stop": value,
            "steps": 1,
        }
    return parameter_dict


class ParameterConstrainer:
    """
    Limit given parameter values to its maximum or minimum values
    """

    def __init__(self):
        self.parameter_parser = KrelParameterParser()

    def get_value(self, column_name, value):
        constrained_value = value
        parameter_defs = PARAMETERS[self.parameter_parser.get_input_name(column_name)]
        try:
            min_value = parameter_defs["min_value"]
            if constrained_value < min_value:
                constrained_value = min_value
        except KeyError:
            pass
        try:
            max_value = parameter_defs["max_value"]
            if constrained_value > max_value:
                constrained_value = max_value
        except KeyError:
            pass
        return constrained_value
