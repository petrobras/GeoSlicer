import qt
import slicer

from ltrace.utils.custom_event_filter import CustomEventFilter


class HierarchyVolumeInput(slicer.qMRMLSubjectHierarchyComboBox):
    def __init__(
        self,
        onChange=None,
        hasNone=False,
        nodeTypes=["vtkMRMLScalarVolumeNode", "vtkMRMLLabelMapVolumeNode"],
        defaultText=None,
    ):
        super().__init__()
        self.subjectHierarchy = slicer.mrmlScene.GetSubjectHierarchyNode()
        self.setNodeTypes(nodeTypes)
        self.setMRMLScene(slicer.mrmlScene)
        self.noneEnabled = hasNone
        if onChange:
            self.currentItemChanged.connect(lambda: onChange(self.currentItem()))
        self.customDefaultText = defaultText
        if self.customDefaultText:
            self.setProperty("defaultText", self.customDefaultText)

        self.node_attribute_filter_list = []
        self.event_filter = CustomEventFilter(self.eventFilter, self)
        self.event_filter.install()

        self.end_close_scene_observer_handler = slicer.mrmlScene.AddObserver(
            slicer.mrmlScene.EndCloseEvent, self.__onEndCloseScene
        )

    def eventFilter(self, object, event):
        if type(event) == qt.QMouseEvent:
            if event.type() == qt.QEvent.MouseButtonPress:
                self.refreshAttributeFilter()
                return True
        return False

    def refreshAttributeFilter(self):
        # This is a workaround to properly update the node list
        for attribute_name, attribute_value in self.node_attribute_filter_list:
            self.removeNodeAttributeFilter(attribute_name, attribute_value)
            self.addNodeAttributeFilter(attribute_name, attribute_value)

    def currentNode(self):
        itemId = self.currentItem()
        if itemId:
            return self.subjectHierarchy.GetItemDataNode(itemId)
        return None

    def setCurrentNode(self, node):
        self.refreshAttributeFilter()
        if node is None or isinstance(node, slicer.vtkMRMLNode):
            self.setCurrentItem(self.subjectHierarchy.GetItemByDataNode(node))

    def addNodeAttributeIncludeFilter(self, attribute_name, attribute_value):
        self.node_attribute_filter_list.append((attribute_name, attribute_value))
        self.addNodeAttributeFilter(attribute_name, attribute_value)

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
        self.removeNodeAttributeFilter(attribute_name, attribute_value)

    def resetStyleOnValidNode(self):
        def inputChanged():
            if self.currentNode():
                self.setStyleSheet("")

        self.currentItemChanged.connect(inputChanged)

    def clearSelection(self):
        slicer.qMRMLSubjectHierarchyComboBox.clearSelection(self)
        if self.customDefaultText:
            self.setProperty("defaultText", self.customDefaultText)

    def __onEndCloseScene(self, *args):
        if self.customDefaultText:
            self.setProperty("defaultText", self.customDefaultText)
