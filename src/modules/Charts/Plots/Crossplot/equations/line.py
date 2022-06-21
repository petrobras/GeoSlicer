from ltrace.slicer.equations.line_equation import LineEquation
from Plots.Crossplot.equations.equation_widget import EquationWidget


class LineWidget(EquationWidget):
    DISPLAY_NAME = "Line"
    EQUATION_TEXT = "y = mx + b"
    PARAMETERS = ["m", "b"]


class Line:
    def __init__(self, enable_refit_button=True):
        self.equation = LineEquation()
        self.widget = LineWidget(enable_refit_button)
