import re

import numpy as np
import pandas as pd
from numba import njit
from scipy import optimize


INPUT_PREFIX = "input-"
RESULT_PREFIX = "result-"
ERROR_PREFIX = "error-"


class KrelResult:
    def __init__(self):
        self._params_table = []
        self._krel_tables = []
        self._curve_analysis_list = []
        self._model_node = None

        self._con_angles_final_node = None
        self._con_angles_wb1_node = None
        self._con_angles_wb2_node = None

    def add_single_result(self, input_params: dict, pnflow_table: dict):
        if pnflow_table is not None:
            pnflow_table = KrelResult._post_treatment(pnflow_table, input_params)
            curve_analysis = KrelResult._krel_curve_analysis(pd.DataFrame(pnflow_table))
            self._params_table.append(input_params.copy())
            self._curve_analysis_list.append(curve_analysis.copy())
            self._krel_tables.append(pnflow_table.copy())
            self._model_node = None

    def add_table_result(self, pnflow_df: dict):
        if pnflow_df is not None:
            curve_analysis = KrelResult._krel_curve_analysis(pd.DataFrame(pnflow_df))
            self._curve_analysis_list.append(curve_analysis.copy())
            self._krel_tables.append(pnflow_df.copy())
            self._model_node = None

    @property
    def krel_tables(self):
        return self._krel_tables

    @property
    def model_node(self):
        return self._model_node

    @property
    def con_angles_final_node(self):
        return self._con_angles_final_node

    @property
    def con_angles_wb1_node(self):
        return self._con_angles_wb1_node

    @property
    def con_angles_wb2_node(self):
        return self._con_angles_wb2_node

    def to_dataframe(self):
        curve_analysis_protodf = {}
        for params_table in self._params_table:
            for param_key, param_val in params_table.items():
                curve_analysis_protodf.setdefault(f"{INPUT_PREFIX}{param_key}", []).append(param_val)
        for curve_analysis in self._curve_analysis_list:
            for result_key, result_val in curve_analysis.items():
                curve_analysis_protodf.setdefault(f"{RESULT_PREFIX}{result_key}", []).append(result_val)
        return pd.DataFrame(curve_analysis_protodf)

    @staticmethod
    def _post_treatment(pnflow_table: dict, input_params: dict):
        subresolution_volume = input_params["subresolution_volume"]
        pnflow_table["Sw"] = np.array(pnflow_table["Sw"]) * (1 - subresolution_volume) + subresolution_volume
        return pnflow_table

    @staticmethod
    def _krel_curve_analysis(values: pd.DataFrame) -> dict:
        """
        output keys:
        swi - Irredutible water saturation (lowest Sw after first cycle)
        kro_swi - Oil relative permeability at Swi
        pc_swi - Capillary pressure at Swi
        k_cross - Permeability at crossover point
        sw_cross - Saturation at crossover
        pc_cross - Capillary pressure at crossover
        swr - Residual water saturation (highest SW after second cycle)
        krw_swr - Water relative permeability at Swr
        pc_swr - Capillary pressure at Swr
        nw - Corey coefficient for water
        no - Corey coefficient for oil
        amott - Amott wettability index
        usbm - USBM* wettability index
        """

        second_cycle = values.loc[values["cycle"] == 2]
        has_pc = "Pc" in second_cycle.keys()
        second_cycle_rows_n = len(second_cycle.index)
        total_rows = len(second_cycle.index)

        if total_rows == 0:
            return {  # these are default values, return dict should be replaced with a class
                "swi": 0,
                "kro_swi": 0,
                "pc_swi": 0,
                "k_cross": 0,
                "sw_cross": 0,
                "pc_cross": 0,
                "swr": 0,
                "krw_swr": 0,
                "pc_swr": 0,
                "nw": 0,
                "no": 0,
                "amott": 0,
                "usbm": 0,
            }

        results = {}
        results["swi"] = second_cycle.iloc[0].loc["Sw"]
        results["kro_swi"] = second_cycle.iloc[0].loc["Kro"]
        for i in range(1, second_cycle_rows_n):
            if has_pc and second_cycle.iloc[i].loc["Sw"] > second_cycle.iloc[i - 1].loc["Sw"]:
                results["pc_swi"] = second_cycle.iloc[i].loc["Pc"]
                break
        else:
            results["pc_swi"] = 0

        # crossover point
        for i in range(1, second_cycle_rows_n):
            if second_cycle.iloc[i].loc["Kro"] <= second_cycle.iloc[i].loc["Krw"]:
                ko1 = second_cycle.iloc[i - 1].loc["Kro"]
                ko2 = second_cycle.iloc[i].loc["Kro"]
                kw1 = second_cycle.iloc[i - 1].loc["Krw"]
                kw2 = second_cycle.iloc[i].loc["Krw"]
                s1 = second_cycle.iloc[i - 1].loc["Sw"]
                s2 = second_cycle.iloc[i].loc["Sw"]
                if has_pc:
                    pc1 = second_cycle.iloc[i - 1].loc["Pc"]
                    pc2 = second_cycle.iloc[i].loc["Pc"]
                else:
                    pc1 = 0
                    pc2 = 0

                ds = s2 - s1
                if ds == 0:
                    ds = 1e-5
                dko = ko2 - ko1
                dkw = kw2 - kw1
                dpc = pc1 - pc2
                diff_dkw = dkw / ds
                diff_dko = dko / ds
                diff_dpc = dpc / ds
                try:
                    s_prime = (ko1 - kw1) / (diff_dkw - diff_dko)
                except ZeroDivisionError:
                    s_prime = 0

                results["sw_cross"] = s1 + s_prime
                results["k_cross"] = ko1 + s_prime * diff_dko
                results["pc_cross"] = pc1 + s_prime * diff_dpc
                break
        else:
            results["sw_cross"] = 0
            results["k_cross"] = 0
            results["pc_cross"] = 0

        results["swr"] = second_cycle.iloc[-1].loc["Sw"]
        results["krw_swr"] = second_cycle.iloc[-1].loc["Krw"]
        for i in range(second_cycle_rows_n - 2, 0, -1):
            if second_cycle.iloc[i].loc["Sw"] < second_cycle.iloc[i + 1].loc["Sw"] and has_pc:
                results["pc_swr"] = second_cycle.iloc[i].loc["Pc"]
                break
        else:
            results["pc_swr"] = 0

        swc = results["swi"]
        sor = 1 - results["swr"]
        kro_max = results["kro_swi"]
        krw_max = results["krw_swr"]

        @njit
        def corey_o(s, n):
            return kro_max * (((1 - s) - swc) / (1 - sor - swc)) ** n

        @njit
        def corey_w(s, n):
            return krw_max * ((s - swc) / (1 - sor - swc)) ** n

        # fmt: off
        try:
            results["no"] = optimize.curve_fit(  
                corey_o,
                second_cycle["Sw"].to_numpy(),
                second_cycle["Kro"].to_numpy(),
                )[0][0]
        except ValueError:
            results["no"] = 0
        except RuntimeError:
            results["no"] = 0

        try:
            results["nw"] = optimize.curve_fit(
                corey_w, 
                second_cycle["Sw"].to_numpy(), 
                second_cycle["Krw"].to_numpy(),
                )[0][0]
        except:
            results["nw"] = 0
        # fmt: on

        third_cycle = values.loc[values["cycle"] == 3]
        third_cycle_rows_n = len(third_cycle.index)

        if third_cycle_rows_n == 0:
            results["amott"] = 0
            results["usbm"] = 0
        else:
            amott, usbm = KrelResult._get_amott_index(second_cycle, third_cycle, has_pc)
            results["amott"] = amott
            results["usbm"] = usbm

        return results

    @staticmethod
    def _get_amott_index(second_cycle, third_cycle, has_pc: bool):
        a1 = 0
        for i in range(1, len(second_cycle.index)):
            if has_pc and second_cycle.iloc[i].loc["Pc"] < 0:
                s1 = second_cycle.iloc[i - 1].loc["Sw"]
                s2 = second_cycle.iloc[i].loc["Sw"]
                delta_s = s2 - s1
                if s1 == s2:
                    s_spw = s1
                    break
                pc1 = second_cycle.iloc[i - 1].loc["Pc"]
                pc2 = second_cycle.iloc[i].loc["Pc"]
                diff_pc = (pc2 - pc1) / (delta_s)
                s_prime = -pc1 / diff_pc
                a1 += np.abs((delta_s - s_prime) * pc2)
                s_spw = s1 + s_prime
                break
        for j in range(i, len(second_cycle.index)):
            s1 = second_cycle.iloc[j - 1].loc["Sw"]
            s2 = second_cycle.iloc[j].loc["Sw"]
            if has_pc:
                pc1 = second_cycle.iloc[j - 1].loc["Pc"]
                pc2 = second_cycle.iloc[j].loc["Pc"]
            else:
                pc1 = 0
                pc2 = 0
            delta_s = s2 - s1
            a1 += np.abs(pc1 * delta_s)
            a1 += np.abs((pc2 - pc1) * (delta_s / 2))

        a2 = 0
        for i in range(1, len(third_cycle.index)):
            if has_pc and third_cycle.iloc[i].loc["Pc"] > 0:
                s1 = third_cycle.iloc[i - 1].loc["Sw"]
                s2 = third_cycle.iloc[i].loc["Sw"]
                delta_s = s2 - s1
                if s1 == s2:
                    s_spo = 1 - s1
                    break
                pc1 = third_cycle.iloc[i - 1].loc["Pc"]
                pc2 = third_cycle.iloc[i].loc["Pc"]
                diff_pc = (pc2 - pc1) / (delta_s)
                s_prime = -pc1 / diff_pc
                a2 += np.abs((delta_s - s_prime) * pc2)
                s_spo = 1 - (s1 + s_prime)
                break
        for j in range(i, len(third_cycle.index)):
            s1 = third_cycle.iloc[j - 1].loc["Sw"]
            s2 = third_cycle.iloc[j].loc["Sw"]
            if has_pc:
                pc1 = third_cycle.iloc[j - 1].loc["Pc"]
                pc2 = third_cycle.iloc[j].loc["Pc"]
            else:
                pc1 = 0
                pc2 = 0
            delta_s = s2 - s1
            a2 += np.abs(pc1 * delta_s)
            a2 += np.abs((pc2 - pc1) * (delta_s / 2))

        try:
            s_cw = second_cycle.iloc[0].loc["Sw"]
            s_or = 1 - second_cycle.iloc[-1].loc["Sw"]
            Iw = (s_spw - s_cw) / (1 - s_or - s_cw)
            Io = (s_spo - s_or) / (1 - s_or - s_cw)
            amott = Iw - Io

            usbm = (a2 - a1) / (a1 + a2)
        except UnboundLocalError:
            # crossover point not found
            amott = 0
            usbm = 0

        return amott, usbm


class KrelTables:
    @staticmethod
    def get_complete_dict(krel_tables):
        cycles_id_list = KrelTables._get_cycle_list(krel_tables)
        max_x = KrelTables._get_max_sw(krel_tables, cycles_id_list)
        interpolated_x = KrelTables._linspace(max_x)
        new_dict = {}
        new_dict["cycle"] = []
        new_dict["Sw"] = []

        for cycle in cycles_id_list:
            new_dict["cycle"].extend([cycle] * len(interpolated_x))
            new_dict["Sw"].extend(interpolated_x)
        for i, table in enumerate(krel_tables):
            try:
                new_dict.update(KrelTables._interpolate_table(table, i, interpolated_x, cycles_id_list))
            except Exception as e:
                pass
        try:
            new_dict.update(KrelTables._calculate_mean(new_dict, len(krel_tables)))
        except Exception as e:
            pass
        return new_dict

    @staticmethod
    def _get_cycle_list(krel_tables):
        list_of_all_cycles_id = []
        for table in krel_tables:
            list_of_all_cycles_id.extend(table["cycle"])
        return np.unique(list_of_all_cycles_id).astype(int)

    @staticmethod
    def _get_max_sw(krel_tables, cycles_id_list):
        max_sw = 0
        for table in krel_tables:
            for cycle in cycles_id_list:
                indexes = np.where(np.array(table["cycle"]) == cycle)
                try:
                    max_sw = max(max_sw, np.array(table["Sw"])[indexes].max())
                except Exception as e:
                    pass
        return max_sw

    @staticmethod
    def _linspace(max_x, number_of_points=201):
        interpolated_x = np.linspace(0, max_x, number_of_points)
        return interpolated_x

    @staticmethod
    def _interpolate(interpolated_x, x_values, y_values):
        return np.interp(interpolated_x, x_values, y_values, left=np.nan, right=np.nan)

    @staticmethod
    def _interpolate_table(table, id, interpolated_x, cycles_id_list):
        cycle_dict = {}
        columns = []
        for column in table.keys():
            if column == "Sw":
                continue
            columns.append(column)
            cycle_dict[f"{column}_{id}"] = []

        for cycle_id in cycles_id_list:
            cycle_indexes = np.where(np.array(table["cycle"]) == cycle_id)
            x_values = np.array(table["Sw"])[cycle_indexes]

            for column in columns:
                y_values = np.array(table[column])[cycle_indexes]
                sorted_values = sorted(zip(x_values, y_values))
                sorted_x = [x for x, y in sorted_values]
                sorted_y = [y for x, y in sorted_values]
                cycle_dict[f"{column}_{id}"].extend(KrelTables._interpolate(interpolated_x, sorted_x, sorted_y))

        return cycle_dict

    @staticmethod
    def _calculate_mean(table_dict, number_of_tables):
        data_len = len(table_dict[f"Sw"])
        mean_dict = {}
        column_prefixes = KrelTables._get_prefixes(table_dict)

        for column_prefix in column_prefixes:
            valid_columns = np.zeros(data_len, np.int16)
            sum = np.zeros(data_len)
            mean = np.empty(data_len)
            for column in range(number_of_tables):
                column_name = f"{column_prefix}_{column}"
                if column_name not in table_dict:
                    continue
                values = np.array(table_dict[column_name])
                for j in range(data_len):
                    if np.isnan(values[j]):
                        continue
                    sum[j] += values[j]
                    valid_columns[j] += 1
            for j in range(data_len):
                if valid_columns[j] == 0:
                    mean[j] = np.nan
                else:
                    mean[j] = sum[j] / valid_columns[j]
            mean_dict[f"{column_prefix}_middle"] = mean

        """
        # clean zeroes
        for column_prefix in column_prefixes:
            for i in range(number_of_tables):
                indexes = np.where(table_dict[f"{column_prefix}_{i}"] == 0)
                mean_dict[f"{column_prefix}_middle"][indexes] = 0
        """

        return mean_dict

    @staticmethod
    def _get_prefixes(table_dict):
        column_prefixes = ["Pc", "Krw", "Kro"]
        if "RI_0" in table_dict.keys():
            column_prefixes.append("RI")
        return column_prefixes


class KrelParameterParser:
    def __init__(self):
        self.input_regex = re.compile(f"{INPUT_PREFIX}(\S+)")
        self.result_regex = re.compile(f"{RESULT_PREFIX}(\S+)")
        self.error_regex = re.compile(f"{ERROR_PREFIX}(\S+)")

    def get_input_name(self, column_name):
        match = self.input_regex.match(column_name)
        if match:
            return match[1]
        else:
            return None

    def get_result_name(self, column_name):
        match = self.result_regex.match(column_name)
        if match:
            return match[1]
        else:
            return None

    def get_error_name(self, column_name):
        match = self.error_regex.match(column_name)
        if match:
            return match[1]
        else:
            return None
