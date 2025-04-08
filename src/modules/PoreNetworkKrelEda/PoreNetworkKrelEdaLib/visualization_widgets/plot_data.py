import re

import numpy as np
import slicer
import statsmodels.api as sm
from statsmodels.formula.api import ols

from ltrace.pore_networks.krel_result import ERROR_PREFIX, INPUT_PREFIX, RESULT_PREFIX
from ltrace.slicer_utils import dataframeFromTable


class PlotData:
    def __init__(self, *args, **kwargs):
        self.input_node = None
        self.errors = []
        self.parameters_list = []
        self.parameters_df = None
        self.krel_result_curves = None

    def is_valid(self) -> bool:
        return self.input_node is not None

    def update_data(self, input_node):
        if input_node is self.input_node:
            return
        if input_node is None:
            self.input_node = None
            self.cycle_nodes = {}
            self.errors = []
            self.parameters_list = []
            self.parameters_df = None
            self.krel_result_curves = None
            return

        self.input_node = input_node
        self.krel_result_curves = KrelResultCurves(self.input_node)
        self.parameters_df = self.krel_result_curves.get_parameters_df()

        angle_columns = [column for column in self.parameters_df if ("_min" in column) or ("_max" in column)]

        self.parameters_df = self.parameters_df.drop(angle_columns, axis=1)
        self.parameters_df = self.parameters_df.drop(f"{RESULT_PREFIX}no", axis=1)
        self.parameters_df = self.parameters_df.drop(f"{RESULT_PREFIX}nw", axis=1)

        has_pc = f"{INPUT_PREFIX}enforced_pc_1" in self.parameters_df.keys()

        if has_pc:
            input_enforced_pc_1 = self.parameters_df[f"{INPUT_PREFIX}enforced_pc_1"].values
            input_enforced_pc_2 = self.parameters_df[f"{INPUT_PREFIX}enforced_pc_2"].values
        columns = self.parameters_df.columns
        self.parameters_list = [None] * len(columns)  # Preallocate the list

        for i, column in enumerate(columns):
            if has_pc and f"{RESULT_PREFIX}pc" in column:
                column_values = self.parameters_df[column].values
                signal = np.sign(column_values)
                signal[signal == 0] = 1
                absolute = np.abs(column_values)
                absolute[absolute < 1] = 1
                self.parameters_df[column] = (
                    (signal * np.log10(absolute) + np.log10(-input_enforced_pc_2))
                    / (np.log10(input_enforced_pc_1) + np.log10(-input_enforced_pc_2))
                ) * 2 - 1
            elif "input" not in column:
                continue
            elif self.parameters_df[column].nunique() > 1:
                self.parameters_list[i] = column

        self.parameters_list = [column for column in self.parameters_list if column is not None]  # Remove None elements

        self.results = [column for column in self.parameters_df if "result" in column]

        result_columns = self.results.copy()
        mean = self.parameters_df[result_columns].mean()
        for column in result_columns:
            result_name = column.split("-")[1]
            self.parameters_df[f"{ERROR_PREFIX}{result_name}"] = self.parameters_df[column] - mean[column]

        error_columns = self.parameters_df.filter(like="error")
        self.parameters_df[f"{ERROR_PREFIX}sum"] = (error_columns**2).sum(axis=1)
        self.errors = [column for column in self.parameters_df if "error" in column]

        square_error_df = self._calculate_square_error_df(self.parameters_df)
        self.sqerror_result_list = self._extract_square_results(square_error_df)
        self.error_correlation = self._calculate_error_correlation(square_error_df, self.sqerror_result_list)

    def get_parameters_dataframe(self):
        return self.parameters_df

    def get_number_of_simulations(self) -> int:
        if self.krel_result_curves:
            return self.krel_result_curves.get_number_of_simulations()
        else:
            return 0

    def get_krel_result_curves(self):
        return self.krel_result_curves

    def get_variable_parameters_list(self):
        return self.parameters_list

    def get_errors_list(self):
        return self.errors

    def get_sqerror_result_list(self):
        return self.sqerror_result_list

    def get_error_correlation_dataframe(self):
        return self.error_correlation

    def anova(self, order):
        df = self.get_parameters_dataframe().copy()

        renamed_df = df.rename(lambda x: x.replace("-", "_"), axis=1)
        params_list = []
        parameters = self.get_variable_parameters_list()
        for p in parameters:
            params_list.append(p.replace("-", "_"))
        params_string = " + ".join(params_list)

        mod = ols(formula=f"error_sum ~ ({params_string}) ** {order}", data=renamed_df).fit()
        anova = sm.stats.anova_lm(mod, typ=3)

        return anova

    @staticmethod
    def _calculate_square_error_df(parameters_df):
        sqerror_df = parameters_df.copy()
        for column in sqerror_df:
            if "error" in column and "sum" not in column:
                sqerror_df[column] = sqerror_df[column] ** 2
        return sqerror_df

    def _calculate_error_correlation(self, sqerror_df, results):
        errors = self.get_errors_list()
        parameters = self.get_variable_parameters_list()

        return sqerror_df[parameters + results + errors].corr()

    def _extract_square_results(self, sqerror_df):
        results = []
        for column in sqerror_df:
            if "result" in column:
                results.append(column)
        return results


class KrelResultCurves:
    def __init__(self, krel_result_node):
        self.parameters_df = dataframeFromTable(krel_result_node)
        self.krel_curve_list = {}

        if krel_result_node is None:
            return

        for cycle_id in range(1, 4):
            cycle_node_id = krel_result_node.GetAttribute(f"cycle_table_{cycle_id}_id")
            cycle_node = slicer.mrmlScene.GetNodeByID(cycle_node_id)
            self.krel_curve_list[cycle_id] = KrelCycleCurves(cycle_node)

    def get_number_of_simulations(self):
        if len(self.krel_curve_list.values()) > 0:
            return list(self.krel_curve_list.values())[0].get_number_of_simulations()
        else:
            return 0

    def get_cycle(self, cycle_id):
        return self.krel_curve_list[cycle_id]

    def get_parameters_df(self):
        return self.parameters_df

    def get_cycle_df(self, cycle_id):
        return self.krel_curve_list[cycle_id].get_dataframe()


class KrelCycleCurves:
    def __init__(self, cycle_node):
        self.cycle_df = dataframeFromTable(cycle_node)
        self.number_of_simulations = len([i for i in self.cycle_df.columns if re.search("Kro_\\d+", i)])
        self.krw_data = {}
        self.kro_data = {}
        self.pressure_data = {}
        self.sw_data = list(self.cycle_df[f"Sw"])
        for id in range(self.number_of_simulations):
            if f"Krw_{id}" in self.cycle_df.columns:
                self.krw_data[id] = list(self.cycle_df[f"Krw_{id}"])
            if f"Kro_{id}" in self.cycle_df.columns:
                self.kro_data[id] = list(self.cycle_df[f"Kro_{id}"])
            if f"Pc_{id}" in self.cycle_df.columns:
                self.pressure_data[id] = list(self.cycle_df[f"Pc_{id}"])
        if "Kro_middle" in self.cycle_df.columns:
            self.krw_data["middle"] = list(self.cycle_df[f"Krw_middle"])
            self.kro_data["middle"] = list(self.cycle_df[f"Kro_middle"])
            self.pressure_data["middle"] = list(self.cycle_df[f"Pc_middle"])

    def get_number_of_simulations(self):
        return self.number_of_simulations

    def get_sw_data(self):
        return self.sw_data

    def get_krw_data(self, simulation_id):
        if simulation_id in self.krw_data:
            return self.krw_data[simulation_id]
        else:
            return None

    def get_kro_data(self, simulation_id):
        if simulation_id in self.kro_data:
            return self.kro_data[simulation_id]
        else:
            return None

    def get_pressure_data(self, simulation_id):
        if simulation_id in self.pressure_data:
            return self.pressure_data[simulation_id]
        else:
            return None

    def get_dataframe(self):
        return self.cycle_df


class PressureResultCurves:
    def __init__(self, pressure_result_node):
        self.parameters_df = dataframeFromTable(pressure_result_node)
        self.pressure_curve_list = {}

        if pressure_result_node is None:
            return

        for cycle_id in range(1, 4):
            cycle_node_id = pressure_result_node.GetAttribute(f"cycle_table_{cycle_id}_id")
            cycle_node = slicer.mrmlScene.GetNodeByID(cycle_node_id)
            self.pressure_curve_list[cycle_id] = KrelCycleCurves(cycle_node)

    def get_number_of_simulations(self):
        if len(self.pressure_curve_list.values()) > 0:
            return list(self.pressure_curve_list.values())[0].get_number_of_simulations()
        else:
            return 0

    def get_cycle(self, cycle_id):
        return self.pressure_curve_list[cycle_id]

    def get_parameters_df(self):
        return self.parameters_df

    def get_cycle_df(self, cycle_id):
        return self.pressure_curve_list[cycle_id].get_dataframe()
