import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
import vtk

from ltrace.slicer.equations.equation_base import EquationBase
from ltrace.slicer.equations.fit_data import FitData


class TimurCoatesEquation(EquationBase):
    NAME = "timur_coates"
    PARAMETERS = ["A", "B", "C"]

    def __init__(self):
        super().__init__()

    @staticmethod
    def _fit(name, x, y, fixed_values=None, custom_bounds=None):
        coef_a, coef_b, coef_c = TimurCoatesEquation.__calc_fit_parameters(x, y, fixed_values, custom_bounds)
        return TimurCoatesEquation.__create_fit_data(name, coef_a, coef_b, coef_c, 0, 0.4, 1000)

    @staticmethod
    def append_to_node(fit_data, table_node):
        column_a = vtk.vtkFloatArray()
        column_b = vtk.vtkFloatArray()
        column_c = vtk.vtkFloatArray()
        column_x_min = vtk.vtkFloatArray()
        column_x_max = vtk.vtkFloatArray()
        column_bins = vtk.vtkIntArray()
        column_a.SetName("A")
        column_b.SetName("B")
        column_c.SetName("C")
        column_x_min.SetName("x_min")
        column_x_max.SetName("x_max")
        column_bins.SetName("bins")
        column_a.InsertNextValue(fit_data.parameters["A"])
        column_b.InsertNextValue(fit_data.parameters["B"])
        column_c.InsertNextValue(fit_data.parameters["C"])
        column_x_min.InsertNextValue(fit_data.parameters["x_min"])
        column_x_max.InsertNextValue(fit_data.parameters["x_max"])
        column_bins.InsertNextValue(fit_data.parameters["bins"])
        table_node.AddColumn(column_a)
        table_node.AddColumn(column_b)
        table_node.AddColumn(column_c)
        table_node.AddColumn(column_x_min)
        table_node.AddColumn(column_x_max)
        table_node.AddColumn(column_bins)

    @staticmethod
    def from_table(name, vtk_table):
        coef_a = vtk_table.GetValueByName(0, "A").ToFloat()
        coef_b = vtk_table.GetValueByName(0, "B").ToFloat()
        coef_c = vtk_table.GetValueByName(0, "C").ToFloat()
        x_min = vtk_table.GetValueByName(0, "x_min").ToFloat()
        x_max = vtk_table.GetValueByName(0, "x_max").ToFloat()
        number_of_bins = vtk_table.GetValueByName(0, "bins").ToInt()
        return TimurCoatesEquation.__create_fit_data(name, coef_a, coef_b, coef_c, x_min, x_max, number_of_bins)

    @staticmethod
    def from_df(name, dataframe):
        coef_a = dataframe["A"][0]
        coef_b = dataframe["B"][0]
        coef_c = dataframe["C"][0]
        x_min = dataframe["x_min"][0]
        x_max = dataframe["x_max"][0]
        number_of_bins = dataframe["bins"][0]
        return TimurCoatesEquation.__create_fit_data(name, coef_a, coef_b, coef_c, x_min, x_max, number_of_bins)

    @staticmethod
    def to_df(fit_data):
        df_dict = {
            "Fitting equation": [TimurCoatesEquation.NAME],
            "A": [fit_data.parameters["A"]],
            "B": [fit_data.parameters["B"]],
            "C": [fit_data.parameters["C"]],
            "x_min": [fit_data.parameters["x_min"]],
            "x_max": [fit_data.parameters["x_max"]],
            "bins": [fit_data.parameters["bins"]],
        }
        return pd.DataFrame(df_dict)

    @staticmethod
    def create_default(name):
        return TimurCoatesEquation.__create_fit_data(name, 30000.0, 0.5, 0.25, 0, 0.4, 1000)

    @staticmethod
    def __create_fit_data(name, coef_a, coef_b, coef_c, x_min, x_max, number_of_bins):
        plot_indices = np.linspace(x_min, x_max, number_of_bins)
        y_line = TimurCoatesEquation._equation(plot_indices, coef_a, coef_b, coef_c)
        fit_data = FitData(
            name,
            TimurCoatesEquation.NAME,
            {"A": coef_a, "B": coef_b, "C": coef_c, "x_min": x_min, "x_max": x_max, "bins": number_of_bins},
            plot_indices,
            y_line,
        )
        return fit_data

    @staticmethod
    def _equation(phi, A, B, C):
        K = np.where(phi > C, A * (phi - C) ** B, 0)
        return K

    @staticmethod
    def __calc_fit_parameters(x, y, fixed_values=None, custom_bounds=None):
        if fixed_values is None:
            fixed_values = [None, None, None]
        if custom_bounds is None:
            custom_bounds = [(None, None), (None, None), (None, None)]

        x_min = np.nanmin(x)
        y_max = np.nanmax(y)
        bounds = [
            {  # A
                "min": 0,
                "max": np.inf,
                "p0": y_max,
            },
            {  # B
                "min": 0,
                "max": np.inf,
                "p0": 1,
            },
            {  # C
                "min": 0,
                "max": x_min,
                "p0": x_min,
            },
        ]

        if x_min <= 0:
            # Fix C
            if fixed_values[2] == None:
                fixed_values[2] = 0

        p0 = []
        min_bounds = []
        max_bounds = []
        for i, fixed_value in enumerate(fixed_values):
            if fixed_value is None:
                min_value = custom_bounds[i][0] or bounds[i]["min"]
                max_value = custom_bounds[i][1] or bounds[i]["max"]
                p0_value = bounds[i]["p0"]

                min_bounds.append(min_value)
                max_bounds.append(max_value)
                if p0_value < min_value:
                    p0_value = min_value
                elif p0_value > max_value:
                    p0_value = max_value
                p0.append(p0_value)

        fitted_parameters, covariance = curve_fit(
            lambda x, *args, **kwargs: TimurCoatesEquation.__equation_wrapper(fixed_values, x, *args, **kwargs),
            x,
            y,
            p0=p0,
            bounds=(min_bounds, max_bounds),
        )

        fitted_parameters = fitted_parameters.tolist()
        parameters = []
        for i, fixed_value in enumerate(fixed_values):
            if fixed_value is None:
                parameters.append(fitted_parameters.pop(0))
            else:
                parameters.append(fixed_value)

        coef_a = parameters[0]
        coef_b = parameters[1]
        coef_c = parameters[2]

        return coef_a, coef_b, coef_c

    @staticmethod
    def __equation_wrapper(fixed_values, x, *args, **kwargs):
        equation_arguments = []
        args_i = 0
        for value in fixed_values:
            if value is None:
                equation_arguments.append(args[args_i])
                args_i += 1
            else:
                equation_arguments.append(value)
        return TimurCoatesEquation._equation(x, *equation_arguments)
