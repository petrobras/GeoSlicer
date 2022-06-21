import qt
import re


def guess_widget_by_name(widgets_dict: dict, name: str):
    """
    Retrieve the value of widget dict
    """
    name_formated = re.sub(r":", "", name).strip()
    return widgets_dict.get(name_formated, None)


class widgetsIdentificationModule:
    """Class to identify automatically the widgets in a specific module without necessity of objectName declaration."""

    def __init__(self, module):
        self.widgets = self.__get_widgets_dict(module)

    def __get_widgets_dict(self, module, qt_type="QWidget"):
        """
        Returns a dictionary with a mapping between the possible names for each widget based on the objectNames or some intuitive text related to it
        """
        format_name = lambda text: re.sub(r":", "", text).strip()

        if module is None:
            raise RuntimeError("No module was defined.")

        obj = module.parent

        widgets_dict = {}
        widgets_list = list(obj.findChildren(qt_type))
        labels = [i for i in widgets_list if isinstance(i, qt.QLabel) and i.text != "No items"]
        labels_with_buddy = [label for label in labels if label.buddy() is not None]
        labels = [label for label in labels if label not in labels_with_buddy]

        # get all widgets with objectNames defined
        for widget in widgets_list:
            if hasattr(widget, "objectName") and widget.objectName:
                widgets_dict[widget.objectName] = widget

        # take labels and seek for respective buddys
        for label in labels_with_buddy:
            widget = label.buddy()
            if widget in widgets_list:
                text_label = format_name(label.text)
                widgets_dict[text_label] = widget

        unknown_count = {}
        for widget in widgets_list:
            # if is a widget with text, take the text
            if hasattr(widget, "text") and isinstance(widget, (qt.QPushButton, qt.QRadioButton, qt.QCheckBox)):
                text_label = format_name(widget.text)
                widgets_dict[text_label] = widget

            # if nothing else works, still look to the left based in geometry
            for label in labels:
                if label.parent() != widget.parent():
                    continue

                if type(label.parent()).__name__ == "ctkCollapsibleButton":
                    label.parent().collapsed = False

                label_rect = self.__get_global_widget_rect(label, obj)
                rect = self.__get_global_widget_rect(widget, obj)
                left_pos = rect.left()
                rect.adjust(-left_pos, 0, 0, 0)
                if rect.intersects(label_rect):
                    if type(widget).__name__ == "ctkCollapsibleButton":
                        continue

                    if hasattr(label, "text") and label.text:
                        text_label = format_name(label.text)
                    else:
                        if type(widget).__name__ not in unknown_count:
                            unknown_count[type(widget).__name__] = 0
                        else:
                            unknown_count[type(widget).__name__] += 1
                        text_label = f"Unknown {type(widget).__name__} {unknown_count[type(widget).__name__]}"

                    if type(widget).__name__ == "QWidget":
                        child = widget.findChildren("QWidget")
                        if child:
                            widgets_dict[text_label] = child[0]
                    else:
                        widgets_dict[text_label] = widget

        return widgets_dict

    def __get_global_widget_rect(self, widget, ref_widget):
        rect = widget.geometry
        p = qt.QPoint(rect.x(), rect.y())
        p_mapped = ref_widget.mapToGlobal(p)
        rect = qt.QRect(p_mapped, rect.size())
        return rect
