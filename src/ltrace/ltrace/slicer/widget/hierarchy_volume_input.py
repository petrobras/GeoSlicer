import qt
import slicer
import logging
import traceback

from ltrace.slicer.helpers import BlockSignals
from ltrace.utils.custom_event_filter import CustomEventFilter


class HierarchyVolumeInput(qt.QWidget):

    currentItemChanged = qt.Signal(object)

    def __init__(
        self,
        hasNone=False,
        nodeTypes=["vtkMRMLScalarVolumeNode", "vtkMRMLLabelMapVolumeNode"],
        defaultText=None,
        allowFolders=False,
        parent=None,
    ):
        super().__init__(parent)

        self.__itemSelectedHandlerConnected = False

        self.__resetStylesheet = False

        self.allowedNodeTypes = nodeTypes
        self.foldersAllowed = allowFolders

        self.selectorWidget = slicer.qMRMLSubjectHierarchyComboBox(self)

        self.subjectHierarchy = slicer.mrmlScene.GetSubjectHierarchyNode()
        self.selectorWidget.setNodeTypes(nodeTypes)
        self.selectorWidget.setMRMLScene(slicer.mrmlScene)
        self.selectorWidget.noneEnabled = hasNone
        self.selectorWidget.setCurrentItem(0)

        layout = qt.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.selectorWidget)

        self.__previousItemId = self.selectorWidget.currentItem()

        self.customDefaultText = defaultText
        if self.customDefaultText:
            self.selectorWidget.setProperty("defaultText", self.customDefaultText)

        self.node_attribute_filter_list = []
        self.event_filter = CustomEventFilter(self.eventFilter, self.selectorWidget)
        self.event_filter.install()

        self.end_close_scene_observer_handler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.EndCloseEvent, self.__onEndCloseScene
        )

        self.setLayout(layout)
        self.destroyed.connect(self.__del__)

    def __del__(self, obj: qt.QObject = None) -> None:
        slicer.mrmlScene.RemoveObserver(self.end_close_scene_observer_handler)

    def setMRMLScene(self, scene: slicer.mrmlScene) -> None:
        """Wrapper for qMRMLSubjectHierarchyComboBox setMRMLScene method.

        Args:
            scene (slicer.mrmlScene): the scene object.
        """
        if self.selectorWidget is None:
            return

        self.selectorWidget.setMRMLScene(scene)

    def eventFilter(self, object, event):
        event_type = event.type()

        if event_type == qt.QEvent.MouseButtonPress or event_type == qt.QEvent.KeyPress:
            self.refreshAttributeFilter()  # This is a workaround to properly update the node list
        elif event_type == qt.QEvent.Show:
            self._connectItemChangedHandler()
        elif event_type == qt.QEvent.Hide:
            self._disconnectItemChangedHandler()

        return False

    def _connectItemChangedHandler(self):
        if not self.__itemSelectedHandlerConnected:
            self.selectorWidget.currentItemChanged.connect(self.itemChangedHandler)
            self.__itemSelectedHandlerConnected = True

    def _disconnectItemChangedHandler(self):
        if self.__itemSelectedHandlerConnected:
            self.selectorWidget.currentItemChanged.disconnect(self.itemChangedHandler)
            self.__itemSelectedHandlerConnected = False

    def itemChangedHandler(self, itemId):

        if itemId == self.__previousItemId:
            return

        if itemId > 0:
            selectedNode = slicer.mrmlScene.GetSubjectHierarchyNode().GetItemDataNode(itemId)

            if selectedNode is None and not self.foldersAllowed:
                if not self.selectorWidget.noneEnabled:
                    self.selectorWidget.setCurrentItem(0)
                return

            if selectedNode and (
                selectedNode.GetHideFromEditors()
                or not any(selectedNode.IsA(nodeType) for nodeType in self.allowedNodeTypes)
            ):
                self.selectorWidget.setCurrentItem(0)
                return

        if self.__resetStylesheet:
            self.resetStyleSheetOnChange()

        self.currentItemChanged.emit(itemId)
        self.__previousItemId = itemId

    def refreshAttributeFilter(self):
        # This is a workaround to properly update the node list
        for attribute_name, attribute_value in self.node_attribute_filter_list:
            self.selectorWidget.removeNodeAttributeFilter(attribute_name, attribute_value)
            self.selectorWidget.addNodeAttributeFilter(attribute_name, attribute_value)

    def currentNode(self):
        itemId = self.selectorWidget.currentItem()
        if itemId:
            return self.subjectHierarchy.GetItemDataNode(itemId)
        return None

    def currentItem(self):
        """Deprecated. Use currentNode() instead. Keeping just for back compatibility."""
        return self.selectorWidget.currentItem()

    def setCurrentNode(self, node):
        self._connectItemChangedHandler()
        self.refreshAttributeFilter()
        if node is None or isinstance(node, slicer.vtkMRMLNode):
            self.selectorWidget.setCurrentItem(self.subjectHierarchy.GetItemByDataNode(node))

    def setCurrentItem(self, itemId: int):
        self._connectItemChangedHandler()
        self.selectorWidget.setCurrentItem(itemId)

    def addNodeAttributeIncludeFilter(self, attribute_name, attribute_value):
        self.node_attribute_filter_list.append((attribute_name, attribute_value))
        self.selectorWidget.addNodeAttributeFilter(attribute_name, attribute_value)

    def removeNodeAttributeIncludeFilter(self, attribute_name, attribute_value=None):
        """Remove attribute filter that includes items in the combobox

        Args:
            attribute_name (str): The name of the attribute of the filter.
            attribute_value (str): The value of the attribute. If None, all filter with the "attribute_name" will be
                                   removed.
        """
        if attribute_value is None:
            self.node_attribute_filter_list = [
                filter for filter in self.node_attribute_filter_list if filter[0] != attribute_name
            ]
            attribute_value = True
        else:
            try:
                self.node_attribute_filter_list.remove((attribute_name, attribute_value))
            except ValueError:
                pass

        self.selectorWidget.removeNodeAttributeFilter(attribute_name, attribute_value)

    def resetStyleOnValidNode(self):
        self.__resetStylesheet = True

    def resetStyleSheetOnChange(self):
        if self.currentNode():
            self.setStyleSheet("")

    def clearSelection(self):
        if self.customDefaultText:
            self.selectorWidget.setProperty("defaultText", self.customDefaultText)
        previousStateConnected = self.__itemSelectedHandlerConnected
        self._connectItemChangedHandler()
        if self.selectorWidget.currentItem() != 0:
            self.selectorWidget.setCurrentItem(0)
        else:
            self.itemChangedHandler(0)

        if not previousStateConnected:
            self._disconnectItemChangedHandler()

    def __onEndCloseScene(self, *args):
        try:
            self.clearSelection()
        except Exception as e:
            logging.error(f"{e}.\n{traceback.format_exc()}")
