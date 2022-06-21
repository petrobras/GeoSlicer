import math

import numpy as np

import qt


class HeatMap(qt.QWidget):
    def __init__(self, df=None):
        super().__init__()
        self.font_size = 13
        self.rotation_deg = 45
        self.rotation = self.rotation_deg * np.pi / 180
        self.setStyleSheet("background-color:white;")
        self.set_dataframe(df)
        self.border = 10
        self.setMouseTracking(False)
        self.cell_width = 0
        self.cell_height = 20
        self.setMinimumHeight(400)

    def paintEvent(self, event):
        if self.correlation_dataframe is None:
            self.setMouseTracking(False)
            return
        else:
            self.setMouseTracking(True)

        painter = qt.QPainter(self)
        # painter.setRenderHint(qt.QPainter.Antialiasing)
        painter.setRenderHints(qt.QPainter.Antialiasing | qt.QPainter.HighQualityAntialiasing)
        widget_width = self.width
        map_width = widget_width - (2 * self.border) - self.longest_row_length
        self.cell_width = map_width / self.num_rows
        self.cell_width = max(self.cell_width, 1)
        self.cell_height = 20
        pen = qt.QPen()

        self.map_min_x = self.border + self.longest_row_length
        self.map_max_x = self.border + self.longest_row_length + int((self.num_columns + 1) * self.cell_width)
        self.map_min_y = self.border - 5
        self.map_max_y = self.border + self.cell_height * self.num_rows

        for row_i in range(self.num_rows):
            y = self.border + 10 + self.cell_height * row_i
            row_text = self.correlation_dataframe.index[row_i]
            font = qt.QFont()
            font.setPixelSize(self.font_size)
            painter.setFont(font)
            fm = qt.QFontMetrics(font)
            row_width = fm.width(row_text)
            text_height = fm.height()
            font_qcolor = qt.QColor(qt.Qt.black)
            pen.setColor(font_qcolor)
            painter.setPen(pen)
            painter.drawText(
                self.border + (self.longest_row_length - row_width) - 2,
                y,
                row_text,
            )

            for column_i in range(self.num_columns):
                x = self.border + self.longest_row_length + int(column_i * self.cell_width)
                next_x = self.border + self.longest_row_length + int((column_i + 1) * self.cell_width)
                delta_x = next_x - x
                cell_val = self.correlation_dataframe.iloc[row_i, column_i]
                back_color, font_color = self.color_scale(cell_val)
                cell_text = f"{cell_val:.2f}"
                text_width = fm.width(cell_text)
                rect = qt.QRect(
                    x,
                    int(y - self.font_size / 1.33 - (self.cell_height - self.font_size / 1.33) / 2) + 1,
                    delta_x,
                    self.cell_height,
                )

                back_color = qt.QColor(*back_color)
                pen.setColor(back_color)
                pen.setWidth(0)
                pen.setStyle(qt.Qt.SolidLine)
                painter.setPen(pen)
                back_brush = qt.QBrush(back_color)
                painter.setBrush(back_brush)
                painter.drawRect(rect)

                if self.cell_width < 30:
                    continue
                font_qcolor = qt.QColor(*font_color)
                pen.setColor(font_qcolor)
                painter.setPen(pen)
                painter.drawText(x + (delta_x - text_width) // 2, y, cell_text)

        rotation = self.rotation
        font.setPixelSize(self.font_size)
        painter.setFont(font)
        fm = qt.QFontMetrics(font)
        text_width = fm.width(row_text)
        text_height = fm.height()
        font_qcolor = qt.QColor(qt.Qt.black)
        pen.setColor(font_qcolor)
        painter.setPen(pen)
        for column_i in range(self.num_columns):
            column_text = self.correlation_dataframe.columns[column_i]
            text_width = fm.width(column_text)
            # centered base of cell point
            x = self.map_min_x + (column_i + 0.5) * self.cell_width
            y = self.map_max_y
            # bottom left at base of cell
            x = x - text_width * np.cos(rotation)
            y = y + text_width * np.sin(rotation)
            # top right at base of cell
            x = x + text_height / 2 * np.sin(rotation)
            y = y + text_height / 2 * np.cos(rotation)
            painter.rotate(-self.rotation_deg)
            painter.drawText(
                int(x * np.cos(rotation) - y * np.sin(rotation)),
                int(y * np.sin(rotation) + x * np.cos(rotation)),
                column_text,
            )
            painter.rotate(self.rotation_deg)

    def set_dataframe(self, df):
        self.correlation_dataframe = df
        if df is None:
            return
        self.num_rows, self.num_columns = self.correlation_dataframe.shape
        self.longest_row = None
        self.longest_row_length = 0
        self.longest_column = None
        self.longest_column_length = 0
        for column in self.correlation_dataframe.columns:
            q_label = qt.QLabel(column)
            font = q_label.font
            font.setPixelSize(self.font_size)
            q_label.setFont(font)
            fm = qt.QFontMetrics(font)
            column_length = fm.boundingRect(q_label.text).width() + 2
            if column_length > self.longest_column_length:
                self.longest_column_length = column_length
                self.longest_column = column
        for row in self.correlation_dataframe.index:
            q_label = qt.QLabel(row)
            font = q_label.font
            font.setPixelSize(self.font_size)
            q_label.setFont(font)
            fm = qt.QFontMetrics(font)
            row_length = fm.boundingRect(q_label.text).width() + 2
            if row_length > self.longest_row_length:
                self.longest_row_length = row_length
                self.longest_row = row
        for column in self.correlation_dataframe.columns:
            q_label = qt.QLabel(row)
            font = q_label.font
            font.setPixelSize(self.font_size)
            q_label.setFont(font)
            fm = qt.QFontMetrics(font)
            column_length = (fm.boundingRect(q_label.text).width() + 2) * np.cos(self.rotation)
            if column_length > self.longest_row_length:
                self.longest_row_length = row_length
                self.longest_row = row

        self.setMinimumHeight(2 * self.border + self.cell_height * self.num_rows + self.longest_column_length)

    def mouseMoveEvent(self, event):
        if self.correlation_dataframe is None:
            return
        # Get the current mouse position
        mouse_position = event.pos()
        mouse_x = mouse_position.x()
        mouse_y = mouse_position.y()

        row_i = int((mouse_y - self.map_min_y) // self.cell_height)
        column_i = int((mouse_x - self.map_min_x) // self.cell_width)

        if (row_i < 0) or (row_i >= self.num_rows) or (column_i < 0) or (column_i >= self.num_columns):
            qt.QToolTip.hideText()
            return

        row_i = int((mouse_y - self.map_min_y) // self.cell_height)
        column_i = int((mouse_x - self.map_min_x) // self.cell_width)
        row_name = self.correlation_dataframe.index[row_i]
        column_name = self.correlation_dataframe.columns[column_i]
        cell_val = self.correlation_dataframe.iloc[row_i, column_i]
        back_color, font_color = self.color_scale(cell_val)
        cell_text = f"{cell_val:.5f}"

        self.setStyleSheet(
            f"""
                           QToolTip {{ 
                           background-color: rgb{str(back_color)}; 
                           color: rgb{str(font_color)}; 
                           border: black solid 2px;
                           font: bold 14px;
                           }};
                           background-color:white;
                           """
        )

        # Set the tooltip text based on the mouse position
        tooltip_text = f"{row_name} x {column_name}\nPearson correlation: {cell_text}"

        # Show the dynamic tooltip
        qt.QToolTip.showText(self.mapToGlobal(mouse_position), tooltip_text, self)

    def color_scale(self, value):
        if math.isnan(value):
            font_color = (0, 0, 0)
            back_color = (255, 255, 255)
        elif value >= 0:
            back_color = (int(255 * (1 - value)), int(255 * (1 - value)), 255)
            if value > 0.8:
                font_color = (255, 255, 255)
            else:
                font_color = (0, 0, 0)
        else:
            back_color = (255, int(255 * (1 + value)), int(255 * (1 + value)))
            if value > 0.8:
                font_color = (255, 255, 255)
            else:
                font_color = (0, 0, 0)
        return back_color, font_color
