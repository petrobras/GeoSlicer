from ltrace.slicer.equations.timur_coates_equation import TimurCoatesEquation
from Plots.Crossplot.equations.equation_widget import EquationWidget


class TimurCoatesWidget(EquationWidget):
    DISPLAY_NAME = "Power"
    EQUATION_TEXT = "K = A * (phi - C)^B"
    PARAMETERS = ["A", "B", "C"]


class TimurCoates:
    def __init__(self, enable_refit_button=True):
        self.equation = TimurCoatesEquation()
        self.widget = TimurCoatesWidget(enable_refit_button)
