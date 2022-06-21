import numpy as np

from ltrace.slicer.equations.fit_data import FitData


class EquationBase:
    NAME = ""
    PARAMETERS = []

    def __init__(self):
        pass

    def fit(self, name, x, y, fixed_values=None, custom_bounds=None) -> FitData:
        """
        Fit points to this equation

        Args:
            name (str):
                Name of the fit output
            x (List[float]):
                X values of each point
            y (List[float]):
                Y values of each point
            fixed_values (List[float]):
                List of fixed equation parameters. The list size is equal to the number of parameters.
                The parameters that have no fixed value will be used to fit the equation.
                Float values in the list will be used as the parameter's fixed value.
                None values in the list means that the corresponding parameter will not have a fixed value.
                If fixed_values == None it is infered that there's no fixed value for any parameter.
            custom_bounds (List[tuple[float, float]]):
                List of custom parameter bounds. The list size is equal to the number of parameters.

        Return:
            fit_data: Points with the data
        """
        fit_data = self._fit(name, x, y, fixed_values, custom_bounds)

        fixed_parameters = []
        if fixed_values is not None:
            for i, parameter_name in enumerate(self.PARAMETERS):
                if fixed_values[i] is not None:
                    fixed_parameters.append(parameter_name)
        fit_data.fixed_parameters = fixed_parameters
        fit_data.r_squared = self.get_r_squared(x, y, fit_data.parameters)
        fit_data.custom_bounds = custom_bounds

        return fit_data

    def equation(self, x, parameters_dict):
        parameter_list = []

        if not self.PARAMETERS:
            return np.nan

        for parameter in self.PARAMETERS:
            try:
                parameter_list.append(parameters_dict[parameter])
            except KeyError:
                return np.nan

        return self._equation(x, *parameter_list)

    @staticmethod
    def append_to_node(fit_data, table_node):
        pass

    @staticmethod
    def from_table(name, vtk_table):
        return None

    @staticmethod
    def from_df(name, dataframe):
        return None

    @staticmethod
    def create_default(name):
        return None

    @staticmethod
    def _fit(name, x, y, fixed_values=None):
        return None

    def get_r_squared(self, x_values, y_values, parameters_dict):
        y_mean = np.mean(y_values)
        fitted_y = []
        for x in x_values:
            fitted_y.append(self.equation(x, parameters_dict))
        fitted_y = np.array(fitted_y)
        ssr = np.sum((y_values - fitted_y) ** 2)
        sst = np.sum((y_values - y_mean) ** 2)
        return 1 - (ssr / sst)
