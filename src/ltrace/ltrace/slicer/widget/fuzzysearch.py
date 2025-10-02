import logging
from collections import defaultdict
from typing import List, Iterable, Dict, Tuple

import pandas as pd
import qt, slicer

from ltrace.slicer.module_info import ModuleInfo
from ltrace.slicer.module_utils import loadModule
from ltrace.slicer_utils import getResourcePath


class FuzzySearchDialog(qt.QDialog):
    def __init__(self, model=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowIcon(qt.QIcon((getResourcePath("Icons") / "ico" / "GeoSlicer.ico").as_posix()))

        layout = qt.QVBoxLayout(self)

        self.search_field = qt.QLineEdit()
        layout.addWidget(self.search_field)

        self.search_field.setPlaceholderText("Search for a module or a keyword")
        self.search_field.textChanged.connect(self.on_search_changed)

        self.results_layout = qt.QHBoxLayout()
        self.result_macros_list = qt.QListWidget()
        self.result_modules_list = qt.QListWidget()

        self.results_layout.addWidget(self.result_macros_list)
        self.results_layout.addWidget(self.result_modules_list)

        layout.addLayout(self.results_layout)

        self.model = model
        self.model.setEventHandler(self.eventHandler)

        self.result_macros_list.currentTextChanged.connect(self.on_macro_selected)
        self.result_modules_list.currentRowChanged.connect(self.on_module_selected)
        self.result_modules_list.itemDoubleClicked.connect(self.on_module_activated)
        self.result_modules_list.installEventFilter(self)

        self.update_results([], self.model.macros)

    def on_search_changed(self, query: str) -> None:
        macros, moduleNames = self.model.search("".join(query.split()))
        self.update_results(moduleNames, macros)

    def update_results(
        self,
        moduleNames: List[str],
        macros: List[str] = None,
    ) -> None:
        if macros is not None:
            self.result_macros_list.clear()
            self.result_macros_list.addItems(macros)

        self.result_modules_list.clear()

        self.displayData(moduleNames)

    def displayData(self, moduleNames):
        for name in moduleNames:
            try:
                module = getattr(slicer.modules, name.lower())
                item = qt.QListWidgetItem()
                item.setIcon(module.icon)
                item.setText(module.title)
                item.setData(qt.Qt.UserRole, name)
                self.result_modules_list.addItem(item)

            except AttributeError:
                pass

    def on_macro_selected(self, macro: str) -> None:
        moduleNames = self.model.select_macro(macro)
        self.update_results(moduleNames)

    def on_module_selected(self, index) -> None:
        listItem = self.result_modules_list.item(index)
        if listItem is None:
            return

        moduleName = listItem.data(qt.Qt.UserRole)
        slicer.util.selectModule(moduleName)

    def on_module_activated(self, item) -> None:
        # Called on double click
        if item is None:
            return
        moduleName = item.data(qt.Qt.UserRole)
        slicer.util.selectModule(moduleName)
        self.accept()  # Close the dialog

    def eventFilter(self, obj, event):
        # Handle Enter/Return key on module list
        if obj == self.result_modules_list and event.type() == qt.QEvent.KeyPress:
            if event.key() in (qt.Qt.Key_Return, qt.Qt.Key_Enter):
                currentItem = self.result_modules_list.currentItem()
                if currentItem is not None:
                    self.on_module_activated(currentItem)
                    return True
        return qt.QObject.eventFilter(self, obj, event)

    def eventHandler(self, event):
        if event == "new-data":
            self.update_results([], self.model.macros)


class LinearSearchModel:
    def __init__(self):
        self.db: pd.DataFrame = None
        self.modules = None
        self.grouped = defaultdict(list)
        self.macros = []
        self.__eventHandler = None

    def setEventHandler(self, handler):
        self.__eventHandler = handler

    def setDataSource(self, modules: dict):
        self.modules = modules
        self.db, self.grouped = self.compile(modules)
        self.macros = [k for k in self.grouped]
        self.__eventHandler("new-data")

    @staticmethod
    def compile(modules: Dict[str, ModuleInfo]) -> Tuple[pd.DataFrame, Dict[str, List[ModuleInfo]]]:
        db_raw = []
        by_category = defaultdict(list)
        for name in modules:
            module = modules[name]
            if module.hidden:
                continue

            db_raw.append((module.key, module.key))
            for tag in module.categories:
                db_raw.append((tag, module.key))
                by_category[tag].append(module)

        return pd.DataFrame(db_raw, columns=["tag", "module"]), by_category

    def search(self, text):
        if len(self.db.index) == 0:
            return self.macros, []

        res = self.db.loc[self.db["tag"].str.contains(text, case=False)]
        lowtext = text.lower()
        macros = [v for v in self.macros if lowtext in v.lower()]
        return macros, res["module"].unique().tolist()

    def select_macro(self, macro: str):
        return self.db.loc[self.db["tag"].str.lower() == macro.lower(), "module"].unique().tolist()
