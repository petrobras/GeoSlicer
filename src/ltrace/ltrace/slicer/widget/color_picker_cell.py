import qt


class ColorPickerCell(qt.QWidget):

    colorChanged = qt.Signal(str, int, int)

    def __init__(self, row, column, *args, color="#333333", **kwargs):
        super().__init__(*args, **kwargs)

        self.setLayout(qt.QVBoxLayout())

        self.button = qt.QPushButton("+")
        self.button.setFixedSize(20, 20)
        self.button.setStyleSheet(
            "QPushButton {"
            "font-size:11px;"
            f"color:{color};"
            f"background-color:{color};"
            "border: 2px solid #222222 }"
        )

        layout = self.layout()
        layout.addWidget(self.button)
        layout.setAlignment(qt.Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)

        self.color = color

        self.row = row
        self.column = column

        self.button.clicked.connect(self._on_clicked)

    def _on_clicked(self):
        new_color = qt.QColorDialog.getColor()
        if new_color.isValid():
            self.button.setStyleSheet(
                "QPushButton {"
                "font-size:11px;"
                f"color:{new_color};"
                f"background-color:{new_color};"
                "border: 2px solid #222222 }"
            )
            print("new color", new_color)
            self.color = new_color.name()
            self.colorChanged.emit(self.color, self.row, self.column)

    def currentColor(self):
        return self.color
