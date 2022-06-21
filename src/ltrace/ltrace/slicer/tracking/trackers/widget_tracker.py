import ctk
import logging
import qt
import slicer
import re

from abc import abstractclassmethod
from dataclasses import dataclass
from ltrace.slicer.application_observables import ApplicationObservables
from ltrace.slicer.tracking.tracker import Tracker
from ltrace.slicer_utils import LTracePluginWidget
from typing import Dict


@dataclass
class SignalTracking:
    widget: qt.QWidget
    signal: qt.Signal
    callback: object

    def __get_signal_object(self):
        signal_str = self.signal.__name__.split("(")[0]
        if not self.widget or not self.callback or not hasattr(self.widget, signal_str):
            return None

        return getattr(self.widget, signal_str, None)

    def __post_init__(self) -> None:
        self.connect()

    def connect(self):
        signal_obj = self.__get_signal_object()
        if not signal_obj:
            raise AttributeError(
                f"Invalid signal parameters. Widget: {self.widget}, Signal: {self.signal}, Callback {self.callback}"
            )

        signal_obj.connect(self.callback)

    def __del__(self):
        self.disconnect()

    def disconnect(self):
        signal_obj = self.__get_signal_object()
        if not signal_obj:
            return

        signal_obj.disconnect(self.callback)


def getAllWidgets(widget):
    widgets = [widget]
    try:
        if isinstance(widget, tuple):
            for child in widget:
                if not hasattr(child, "children"):
                    continue

                widgets += getAllWidgets(child)
        else:
            for child in widget.children():
                if not hasattr(child, "children"):
                    continue

                widgets += getAllWidgets(child)
    except Exception as error:
        logging.warning(error)

    return list(widgets)


def getPluginFromWidget(widget):
    currentWidget = widget
    while currentWidget.parent() is not None:
        if isinstance(currentWidget.parent(), LTracePluginWidget) or isinstance(
            currentWidget.parent(), slicer.qSlicerScriptedLoadableModuleWidget
        ):
            return currentWidget.parent()

        currentWidget = currentWidget.parent()

    return None


def getBuddyLabel(widget) -> str:
    widgets = []

    def formatLabelText(text):
        return re.sub(r":", "", text).strip()

    module_widget = getPluginFromWidget(widget)
    if module_widget:
        widgets.extend(getAllWidgets(module_widget.children()))

    labels = [wid for wid in widgets if isinstance(wid, qt.QLabel) and wid.isVisible()]
    labelText = ""
    rect = widget.geometry
    point = widget.parentWidget().mapToGlobal(widget.pos)
    globalRect = qt.QRect(point, rect.size())
    xDistance = globalRect.left()
    globalRect.adjust(-xDistance, 0, 0, 0)

    for label in labels:
        if label.buddy() == widget:
            labelText = formatLabelText(label.text)
            break

        labelRect = label.geometry
        labelRectPoint = label.parentWidget().mapToGlobal(label.pos)
        globalLabelRect = qt.QRect(labelRectPoint, labelRect.size())

        if globalRect.intersects(globalLabelRect) and hasattr(label, "text"):
            if len(label.text) < len(labelText):
                continue

            labelText = formatLabelText(label.text)

    return labelText


def getValidObjectName(widget):
    return widget.objectName if widget.objectName and not widget.objectName.startswith("qt_") else ""


class WidgetTrackerHandler(qt.QObject):
    logSignal = qt.Signal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.signalTracking: SignalTracking = None

    @abstractclassmethod
    def handleEventFilter(self, obj: object, event: qt.QEvent) -> bool:
        """
        Handle the event filter for the given object.
        Args:
            obj: The object to handle the event filter for.
        Returns:
            None
        """
        pass

    @abstractclassmethod
    def toDict(self, *args, **kwargs) -> Dict:
        """Convert the given object to a dictionary.

        Returns:
            Dict: the object description as dict
        """
        pass


class ButtonWidgetTracker(WidgetTrackerHandler):
    def handleEventFilter(self, obj: object, event: qt.QEvent) -> None:

        if event.type() != qt.QEvent.MouseButtonRelease or not (
            isinstance(obj, qt.QPushButton)
            or isinstance(obj, qt.QToolButton)
            or ("Button" in obj.__class__.__name__ and not isinstance(obj, (ctk.ctkCollapsibleButton, qt.QRadioButton)))
        ):
            return

        infoDict = self.toDict(obj=obj)
        if not infoDict:
            return

        self.logSignal.emit(f"Button clicked: {infoDict}")

    def toDict(self, obj: object) -> Dict:
        return {
            "name": obj.objectName or obj.text or qt.QTextDocumentFragment.fromHtml(obj.toolTip).toPlainText(),
            "isChecked": obj.isChecked(),
        }


class MenuWidgetTracker(WidgetTrackerHandler):
    def handleEventFilter(self, obj: object, event: qt.QEvent) -> None:

        if event.type() != qt.QEvent.MouseButtonRelease or not isinstance(obj, qt.QMenu):
            return

        infoDict = self.toDict(obj=obj, event=event)
        if not infoDict:
            return

        self.logSignal.emit(f"Menu action clicked: {infoDict}")

    def toDict(self, obj: object, event: qt.QEvent) -> Dict:
        name = obj.objectName or obj.text if hasattr(obj, "text") else obj.title if hasattr(obj, "title") else ""
        action = obj.actionAt(qt.QPoint(int(event.localPos().x()), int(event.localPos().y())))
        actionName = action.text if action is not None else "None"
        return {"name": name, "action": actionName}


class CollapsibleButtonWidgetTracker(WidgetTrackerHandler):
    def handleEventFilter(self, obj: object, event: qt.QEvent) -> None:

        if event.type() != qt.QEvent.MouseButtonRelease or not isinstance(obj, ctk.ctkCollapsibleButton):
            return

        infoDict = self.toDict(obj=obj)
        if not infoDict:
            return

        self.logSignal.emit(f"Collapsible button clicked: {infoDict}")

    def toDict(self, obj: object) -> Dict:
        return {"name": getValidObjectName(obj) or obj.text, "collapsed": obj.collapsed}


class ComboBoxWidgetTrackerHandler(WidgetTrackerHandler):
    def onCurrentTextChanged(self, text: str) -> None:
        if not self.signalTracking:
            return

        obj = self.signalTracking.widget

        infoDict = self.toDict(obj=obj)
        if infoDict is not None:
            self.logSignal.emit(f"Combo box changed: {infoDict}")

        if not obj.hasFocus():
            self.signalTracking.disconnect()
            del self.signalTracking
            self.signalTracking = None

    def handleEventFilter(self, obj: object, event: qt.QEvent) -> None:
        if event.type() == qt.QEvent.MouseButtonPress:
            if isinstance(obj, qt.QComboBox) or issubclass(obj.__class__, qt.QComboBox):
                self.signalTracking = SignalTracking(
                    widget=obj, signal=obj.currentTextChanged, callback=self.onCurrentTextChanged
                )

        if event.type() == qt.QEvent.MouseButtonRelease:
            comboBox = None
            if obj.__class__.__name__ == "QComboBoxPrivateContainer":
                comboBox = obj.parentWidget()
            elif hasattr(obj, "parentWidget") and obj.parentWidget().__class__.__name__ == "QComboBoxPrivateContainer":
                comboBox = obj.parentWidget().parentWidget()

            if comboBox:
                self.signalTracking = SignalTracking(
                    widget=comboBox, signal=comboBox.currentTextChanged, callback=self.onCurrentTextChanged
                )

    def toDict(self, obj: object) -> Dict:
        return {"name": getValidObjectName(obj) or getBuddyLabel(obj), "text": obj.currentText}


class HierarchyComboBoxWidgetTrackerHandler(WidgetTrackerHandler):
    def onHierarchyItemChanged(self) -> None:
        if not self.signalTracking:
            return

        obj = self.signalTracking.widget

        infoDict = self.toDict(obj=obj)
        if not infoDict:
            return

        self.logSignal.emit(f"Hierarchy combo box changed: {infoDict}")

    def handleEventFilter(self, obj: object, event: qt.QEvent) -> None:
        if event.type() != qt.QEvent.MouseButtonRelease:
            return

        try:
            comboBox = obj.parentWidget().parentWidget().parentWidget()
        except Exception:
            return

        if not (
            isinstance(comboBox, slicer.qMRMLSubjectHierarchyComboBox)
            or issubclass(comboBox.__class__, slicer.qMRMLSubjectHierarchyComboBox)
        ):
            return

        self.signalTracking = SignalTracking(
            widget=comboBox, signal=comboBox.currentItemChanged, callback=self.onHierarchyItemChanged
        )

    def toDict(self, obj: object) -> Dict:
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemId = obj.currentItem()
        node = subjectHierarchyNode.GetItemDataNode(itemId)

        return {
            "name": getValidObjectName(obj) or getBuddyLabel(obj),
            "selectedNodeName": node.GetName() if node is not None else "None",
            "selectedNodeId": node.GetID() if node is not None else "None",
        }


class SpinBoxWidgetTrackerHandler(WidgetTrackerHandler):
    def handleEventFilter(self, obj: object, event: qt.QEvent) -> None:
        if event.type() != qt.QEvent.MouseButtonRelease or not (
            isinstance(obj, qt.QSpinBox) or isinstance(obj, qt.QDoubleSpinBox)
        ):
            return

        infoDict = self.toDict(obj=obj)
        if not infoDict:
            return

        self.logSignal.emit(f"Spin box clicked: {infoDict}")

    def toDict(self, obj: object) -> Dict:
        return {"name": getValidObjectName(obj) or getBuddyLabel(obj), "value": obj.value}


class TabBarWidgetTrackingHandler(WidgetTrackerHandler):
    def handleEventFilter(self, obj: object, event: qt.QEvent) -> None:
        if event.type() != qt.QEvent.MouseButtonRelease or not isinstance(obj, qt.QTabBar):
            return

        infoDict = self.toDict(obj=obj)
        if not infoDict:
            return

        self.logSignal.emit(f"Tab clicked: {infoDict}")

    def toDict(self, obj: object) -> Dict:
        return {"text": obj.tabText(obj.currentIndex)}


class LineEditWidgetTrackerHandler(WidgetTrackerHandler):
    def onLineEditingFinished(self):
        if not self.signalTracking:
            return

        obj = self.signalTracking.widget

        if not obj.hasFocus():
            infoDict = self.toDict(obj=obj)
            if infoDict is not None:
                self.logSignal.emit(f"Line edit changed: {infoDict}")

            self.signalTracking.disconnect()
            del self.signalTracking
            self.signalTracking = None

    def handleEventFilter(self, obj: object, event: qt.QEvent) -> None:
        if event.type() != qt.QEvent.MouseButtonRelease or not isinstance(obj, qt.QLineEdit):
            return

        self.signalTracking = SignalTracking(
            widget=obj, signal=obj.editingFinished, callback=self.onLineEditingFinished
        )

    def toDict(self, obj: object) -> Dict:
        return {
            "name": getValidObjectName(obj) or getBuddyLabel(obj),
            "text": obj.text,
        }


class ListWidgetTrackingHandler(WidgetTrackerHandler):
    def onListWidgetItemClicked(self, item: qt.QListWidgetItem) -> None:
        if not self.signalTracking:
            return

        obj = self.signalTracking.widget

        infoDict = self.toDict(obj=obj, item=item)
        if infoDict is not None:
            self.logSignal.emit(f"List Item clicked: {infoDict}")

        self.signalTracking.disconnect()
        del self.signalTracking
        self.signalTracking = None

    def handleEventFilter(self, obj: object, event: qt.QEvent) -> None:
        if event.type() != qt.QEvent.MouseButtonRelease or not isinstance(obj.parentWidget(), qt.QListWidget):
            return

        listWidget = obj.parentWidget()
        self.signalTracking = SignalTracking(
            widget=listWidget, signal=listWidget.itemClicked, callback=self.onListWidgetItemClicked
        )

    def toDict(self, obj: object, item: qt.QListWidgetItem) -> Dict:
        return {
            "name": getValidObjectName(obj) or getBuddyLabel(obj),
            "itemText": item.text(),
            "checked": True if item.checkState() == qt.Qt.Checked else False,
            "selected": item.isSelected(),
        }


class TableWidgetTrackingHandler(WidgetTrackerHandler):
    def onTableWidgetItemClicked(self, item: qt.QTableWidgetItem) -> None:
        if not self.signalTracking:
            return

        obj = self.signalTracking.widget

        infoDict = self.toDict(obj=obj, item=item)
        if infoDict is not None:
            self.logSignal.emit(f"Table Item clicked: {infoDict}")
        self.signalTracking.disconnect()
        del self.signalTracking
        self.signalTracking = None

    def handleEventFilter(self, obj: object, event: qt.QEvent) -> None:
        if event.type() != qt.QEvent.MouseButtonRelease or not (
            isinstance(obj.parentWidget(), qt.QTableWidget) or issubclass(obj.parentWidget().__class__, qt.QTableWidget)
        ):
            return

        tableWidget = obj.parentWidget()
        infoDict = self.toDict(obj=tableWidget)
        if not infoDict:
            return

        self.logSignal.emit(f"Table cell clicked: {infoDict}")

    def toDict(self, obj: object) -> Dict:
        tableItem = obj.currentItem()
        if tableItem is None:
            return None

        row = tableItem.row()
        column = tableItem.column()

        rowName = obj.verticalHeaderItem(row).text() if obj.verticalHeaderItem(row) is not None else row
        columnName = obj.horizontalHeaderItem(column).text() if obj.horizontalHeaderItem(column) is not None else column

        return {
            "name": getValidObjectName(obj) or getBuddyLabel(obj),
            "itemText": tableItem.text(),
            "row": rowName,
            "column": columnName,
        }


class CheckBoxWidgetTrackingHandler(WidgetTrackerHandler):
    def onCheckBoxToggled(self, checked: bool = None) -> None:
        if not self.signalTracking:
            return

        obj = self.signalTracking.widget
        infoDict = self.toDict(obj=obj)
        if infoDict is not None:
            self.logSignal.emit(f"Check box toggled: {infoDict}")

        if not obj.hasFocus():
            self.signalTracking.disconnect()
            del self.signalTracking
            self.signalTracking = None

    def handleEventFilter(self, obj: object, event: qt.QEvent) -> None:
        if event.type() != qt.QEvent.MouseButtonRelease or not (
            isinstance(obj, qt.QCheckBox) or isinstance(obj, qt.QRadioButton)
        ):
            return

        self.signalTracking = SignalTracking(widget=obj, signal=obj.toggled, callback=self.onCheckBoxToggled)

    def toDict(self, obj: object) -> Dict:
        return {
            "name": obj.text or getBuddyLabel(obj),
            "checked": obj.isChecked(),
        }


class WidgetTrackerEventFilter(qt.QObject):
    logSignal = qt.Signal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.handlers = []
        self.installHandlers()

    def installHandlers(self):
        handlers = [
            ButtonWidgetTracker(),
            MenuWidgetTracker(),
            CollapsibleButtonWidgetTracker(),
            ComboBoxWidgetTrackerHandler(),
            HierarchyComboBoxWidgetTrackerHandler(),
            SpinBoxWidgetTrackerHandler(),
            TabBarWidgetTrackingHandler(),
            LineEditWidgetTrackerHandler(),
            ListWidgetTrackingHandler(),
            TableWidgetTrackingHandler(),
            CheckBoxWidgetTrackingHandler(),
        ]

        for handler in handlers:
            handler.logSignal.connect(self.logSignal)

        self.handlers = handlers

    def eventFilter(self, obj, event) -> bool:
        for handler in self.handlers:
            handler.handleEventFilter(obj, event)

        return False


class WidgetTracker(Tracker):
    def __init__(self) -> None:
        super().__init__()
        self.eventFilter = WidgetTrackerEventFilter()
        self.currentModuleWidget = None

    def onChangeModule(self, moduleObject=None):
        if self.currentModuleWidget:
            self.currentModuleWidget.removeEventFilter(self.eventFilter)

        if issubclass(moduleObject.__class__, LTracePluginWidget):
            self.currentModuleWidget = moduleObject.parent
            moduleName = moduleObject.moduleName
        else:
            if not moduleObject:
                moduleName = slicer.util.selectedModule().lower()
            else:
                moduleName = moduleObject.moduleName.lower()

            module = getattr(slicer.modules, moduleName, None)

            if not module:
                return
            self.currentModuleWidget = (
                module.widgetRepresentation() if hasattr(module, "widgetRepresentation") else None
            )

        if not self.currentModuleWidget:
            return

        widgets = getAllWidgets(self.currentModuleWidget)
        for wid in widgets:
            wid.installEventFilter(self.eventFilter)

    def install(self) -> None:
        self.onChangeModule()
        ApplicationObservables().moduleWidgetEnter.connect(self.onChangeModule)

        mainWindow = slicer.util.mainWindow()
        widgets = getAllWidgets(mainWindow)
        for widget in widgets:
            if not hasattr(widget, "installEventFilter"):
                continue

            widget.installEventFilter(self.eventFilter)

        self.eventFilter.logSignal.connect(self.log)

    def uninstall(self):
        if self.currentModuleWidget:
            self.currentModuleWidget.removeEventFilter(self.eventFilter)

        mainWindow = slicer.util.mainWindow()
        widgets = getAllWidgets(mainWindow)
        for widget in widgets:
            if not hasattr(widget, "removeEventFilter"):
                continue
            widget.removeEventFilter(self.eventFilter)

        self.eventFilter.logSignal.disconnect(self.log)
        ApplicationObservables().moduleWidgetEnter.disconnect(self.onChangeModule)
