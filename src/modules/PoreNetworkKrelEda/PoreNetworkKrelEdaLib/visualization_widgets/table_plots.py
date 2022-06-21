import pandas as pd
import qt

from PoreNetworkKrelEdaLib.visualization_widgets.plot_base import PlotBase


class SecondOrderInteractions(PlotBase):
    DISPLAY_NAME = "Second order interactions list"
    METHOD = "plot7"

    def __init__(self, *args, **kwargs):
        super().__init__()

        self.data_manager = kwargs["data_manager"]

        self.mainLayout = qt.QFormLayout(self)
        self.textBrowser = qt.QTextEdit()
        self.textBrowser.setReadOnly(True)
        self.mainLayout.addRow(self.textBrowser)

    def update(self):
        self.textBrowser.setHtml(self._to_html())

    def clear_saved_plots(self):
        self.textBrowser.clear()

    def _to_html(self):
        anova = anova = self.data_manager.anova(2)

        anova_p = anova["PR(>F)"]

        for i in anova_p.index:
            if i.count(":") < 1:
                anova_p = anova_p.drop(i)

        anova_p.sort_values(inplace=True)

        alpha = 0.05
        gcolor = anova_p.copy()
        for i in gcolor.index:
            if gcolor[i] == alpha:
                gcolor[i] = 0.5
            elif gcolor[i] < 0.8 * alpha:
                gcolor[i] = 1 - (0.25 - ((gcolor[i] - 0.8 * alpha) / (0 - 0.8 * alpha)) * 0.25)
            elif gcolor[i] < alpha and gcolor[i] >= 0.8 * alpha:
                gcolor[i] = 1 - (0.40 - ((gcolor[i] - alpha) / (0.8 * alpha - alpha)) * 0.15)
            elif gcolor[i] > alpha and gcolor[i] <= 2 * alpha:
                gcolor[i] = 1 - (0.5 + ((gcolor[i] - alpha) / (2 * alpha - alpha)) * 0.40)
            elif gcolor[i] > 2 * alpha:
                gcolor[i] = 1 - (0.90 + ((gcolor[i] - 2 * alpha) / (1 - 2 * alpha)) * 0.10)
            if gcolor[i] == alpha:
                gcolor[i] = 0.5
        styler = pd.DataFrame(anova_p).style
        styler.background_gradient(cmap="RdYlGn", gmap=gcolor, vmin=0, vmax=1)
        styler.set_table_styles([{"selector": "th.row_heading.level0", "props": "text-align: right;"}])
        return styler.to_html()


class ThirdOrderInteractions(PlotBase):
    DISPLAY_NAME = "Third order interactions list"
    METHOD = "plot8"

    def __init__(self, *args, **kwargs):
        super().__init__()

        self.data_manager = kwargs["data_manager"]

        self.mainLayout = qt.QFormLayout(self)
        self.textBrowser = qt.QTextEdit()
        self.textBrowser.setReadOnly(True)
        self.mainLayout.addRow(self.textBrowser)

    def update(self):
        self.textBrowser.setHtml(self._to_html())

    def clear_saved_plots(self):
        self.textBrowser.clear()

    def _to_html(self):
        anova = anova = self.data_manager.anova(3)

        anova_p = anova["PR(>F)"]

        for i in anova_p.index:
            if i.count(":") < 2:
                anova_p = anova_p.drop(i)

        anova_p.sort_values(inplace=True)

        alpha = 0.05
        gcolor = anova_p.copy()
        for i in gcolor.index:
            if gcolor[i] == alpha:
                gcolor[i] = 0.5
            elif gcolor[i] < 0.8 * alpha:
                gcolor[i] = 1 - (0.25 - ((gcolor[i] - 0.8 * alpha) / (0 - 0.8 * alpha)) * 0.25)
            elif gcolor[i] < alpha and gcolor[i] >= 0.8 * alpha:
                gcolor[i] = 1 - (0.40 - ((gcolor[i] - alpha) / (0.8 * alpha - alpha)) * 0.15)
            elif gcolor[i] > alpha and gcolor[i] <= 2 * alpha:
                gcolor[i] = 1 - (0.5 + ((gcolor[i] - alpha) / (2 * alpha - alpha)) * 0.40)
            elif gcolor[i] > 2 * alpha:
                gcolor[i] = 1 - (0.90 + ((gcolor[i] - 2 * alpha) / (1 - 2 * alpha)) * 0.10)
            if gcolor[i] == alpha:
                gcolor[i] = 0.5
        styler = pd.DataFrame(anova_p).style
        styler.background_gradient(cmap="RdYlGn", gmap=gcolor, vmin=0, vmax=1)
        styler.set_table_styles([{"selector": "th.row_heading.level0", "props": "text-align: right;"}]),
        return styler.to_html()
