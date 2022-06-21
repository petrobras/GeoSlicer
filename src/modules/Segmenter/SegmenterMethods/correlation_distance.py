import qt

from ltrace.slicer.widgets import PixelLabel


class CorrelationDistance:
    NAME = "variogram"
    DISPLAY_NAME = "Variogram range"

    def __init__(self):
        self.kernel_input = None
        self.pixel_label = None

    def create_layout(self, node_input):
        layout = qt.QFormLayout()
        boxLayout = qt.QHBoxLayout()

        self.kernel_input = qt.QLineEdit()
        validator = qt.QDoubleValidator(self.kernel_input)
        locale = qt.QLocale()
        locale.setNumberOptions(qt.QLocale.RejectGroupSeparator)
        validator.setLocale(locale)
        self.kernel_input.setValidator(validator)

        boxLayout.addWidget(qt.QLabel("Kernel size (mm): "))
        boxLayout.addWidget(self.kernel_input)

        self.pixel_label = PixelLabel(value_input=self.kernel_input, node_input=node_input)
        boxLayout.addWidget(self.pixel_label)

        layout.addRow(boxLayout)

        return layout

    def get_options(self):
        options = {}
        options["kernel_size"] = [float(self.kernel_input.text)]
        return options
