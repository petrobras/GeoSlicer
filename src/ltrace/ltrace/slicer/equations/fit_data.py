from pyqtgraph.Qt import QtCore

from ltrace.slicer.graph_data import GraphStyle


class FitData(QtCore.QObject):
    signalVisibleChanged = QtCore.Signal(bool)

    def __init__(self, name, type, parameters, x_values, y_values, plot_type=None, color=None, symbol=None, size=None):
        super().__init__()

        self.__name = name
        self.__type = type
        self.__parameters = parameters
        self.__x_values = x_values
        self.__y_values = y_values
        self.style = GraphStyle(plot_type, color, symbol, size)

        self.__fixed_parameters = []
        self.__visible = True
        self.__r_squared = 0
        self.__custom_bounds = None

    @property
    def name(self):
        return self.__name

    @name.setter
    def name(self, new_name):
        self.__name = new_name

    @property
    def parameters(self):
        return self.__parameters

    def set_parameter(self, name, value):
        self.__parameters[name] = value

    @property
    def r_squared(self):
        return self.__r_squared

    @r_squared.setter
    def r_squared(self, new_r_squared):
        self.__r_squared = new_r_squared

    @property
    def custom_bounds(self):
        return self.__custom_bounds

    @custom_bounds.setter
    def custom_bounds(self, new_custom_bounds):
        self.__custom_bounds = new_custom_bounds

    @property
    def fixed_parameters(self):
        return self.__fixed_parameters

    @fixed_parameters.setter
    def fixed_parameters(self, fixed_parameters):
        self.__fixed_parameters = fixed_parameters

    @property
    def x(self):
        return self.__x_values

    @property
    def y(self):
        return self.__y_values

    @y.setter
    def y(self, new_y):
        self.__y_values = new_y

    @property
    def type(self):
        return self.__type

    @property
    def visible(self):
        return self.__visible

    @visible.setter
    def visible(self, is_visible):
        if self.__visible == is_visible:
            return

        self.__visible = is_visible
        self.signalVisibleChanged.emit(self.__visible)

    def set_plot_item(self, plot_item):
        self.__plot_item = plot_item

    def get_plot_item(self):
        return self.__plot_item
