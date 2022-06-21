import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
import vtk
import warnings

from ltrace.slicer.equations.equation_base import EquationBase
from ltrace.slicer.equations.fit_data import FitData


class LineEquation(EquationBase):
    NAME = "line"
    PARAMETERS = ["m", "b"]

    def __init__(self):
        super().__init__()

    @staticmethod
    def _fit(name, x, y, fixed_values=None, custom_bounds=None) -> FitData:
        m_coef, b_coef = LineEquation.__calc_fit_parameters(x, y, fixed_values, custom_bounds)
        x_min = np.nanmin(x)
        x_max = np.nanmax(x)
        margin = 0.1 * (x_max - x_min)
        x_min -= margin
        x_max += margin
        return LineEquation.__create_fit_data(name, m_coef, b_coef, x_min, x_max)

    @staticmethod
    def append_to_node(fit_data, table_node):
        column_m = vtk.vtkFloatArray()
        column_b = vtk.vtkFloatArray()
        column_x_min = vtk.vtkFloatArray()
        column_x_max = vtk.vtkFloatArray()
        column_m.SetName("m")
        column_b.SetName("b")
        column_x_min.SetName("x_min")
        column_x_max.SetName("x_max")
        column_m.InsertNextValue(fit_data.parameters["m"])
        column_b.InsertNextValue(fit_data.parameters["b"])
        column_x_min.InsertNextValue(fit_data.parameters["x_min"])
        column_x_max.InsertNextValue(fit_data.parameters["x_max"])
        table_node.AddColumn(column_m)
        table_node.AddColumn(column_b)
        table_node.AddColumn(column_x_min)
        table_node.AddColumn(column_x_max)

    @staticmethod
    def from_table(name, vtk_table):
        m_coef = vtk_table.GetValueByName(0, "m").ToFloat()
        b_coef = vtk_table.GetValueByName(0, "b").ToFloat()
        x_min = vtk_table.GetValueByName(0, "x_min").ToFloat()
        x_max = vtk_table.GetValueByName(0, "x_max").ToFloat()
        return LineEquation.__create_fit_data(name, m_coef, b_coef, x_min, x_max)

    @staticmethod
    def from_df(name, dataframe):
        m_coef = dataframe["m"][0]
        b_coef = dataframe["b"][0]
        x_min = dataframe["x_min"][0]
        x_max = dataframe["x_max"][0]
        return LineEquation.__create_fit_data(name, m_coef, b_coef, x_min, x_max)

    @staticmethod
    def to_df(fit_data):
        df_dict = {
            "Fitting equation": [LineEquation.NAME],
            "m": [fit_data.parameters["m"]],
            "b": [fit_data.parameters["b"]],
            "x_min": [fit_data.parameters["x_min"]],
            "x_max": [fit_data.parameters["x_max"]],
        }
        return pd.DataFrame(df_dict)

    @staticmethod
    def create_default(name):
        return LineEquation.__create_fit_data(name, 10000.0, 0.0, 0, 0.4)

    @staticmethod
    def _equation(x, m_coef, b_coef):
        return m_coef * x + b_coef

    @staticmethod
    def __calc_fit_parameters(x, y, fixed_values=None, custom_bounds=None):
        if fixed_values is None:
            fixed_values = [None, None]
        if custom_bounds is None:
            custom_bounds = [(None, None), (None, None)]

        bounds = [
            {  # m
                "min": -np.inf,
                "max": np.inf,
                "p0": 1,
            },
            {  # b
                "min": -np.inf,
                "max": np.inf,
                "p0": 1,
            },
        ]

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

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Covariance of the parameters could not be estimated")
            fitted_parameters, covariance = curve_fit(
                lambda x, *args, **kwargs: LineEquation.__equation_wrapper(fixed_values, x, *args, **kwargs),
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

        m_coef = parameters[0]
        b_coef = parameters[1]
        # m_coef, b_coef = np.polyfit(x, y, 1)
        return m_coef, b_coef

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
        return LineEquation._equation(x, *equation_arguments)

    @staticmethod
    def __create_fit_data(name, m_coef, b_coef, x_min, x_max):
        x = np.array([x_min, x_max])
        y_line = LineEquation._equation(x, m_coef, b_coef)
        fit_data = FitData(
            name,
            LineEquation.NAME,
            {"m": m_coef, "b": b_coef, "x_min": x_min, "x_max": x_max},
            x,
            y_line,
        )
        return fit_data
