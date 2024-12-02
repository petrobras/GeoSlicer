import vtk
import qt
import slicer


class FilteredNodeComboBox(qt.QComboBox):
    nodeAboutToBeRemoved = qt.Signal(object)
    currentNodeChanged = qt.Signal(object)

    def __init__(
        self,
        nodeTypes=["vtkMRMLScalarVolumeNode", "vtkMRMLLabelMapVolumeNode"],
    ):
        super().__init__()
        self.addItem("None", None)
        self.nodeTypes = nodeTypes
        slicer.mrmlScene.AddObserver(slicer.mrmlScene.NodeAddedEvent, self.onNodeAdded)
        slicer.mrmlScene.AddObserver(slicer.mrmlScene.NodeAboutToBeRemovedEvent, self.onNodeAboutToBeRemoved)

        self.attributeFilters = dict()
        for nodeType in nodeTypes:
            self.attributeFilters[nodeType] = dict()

        nodesToAdd = []

        for nodeType in self.nodeTypes:
            nodesToAdd += slicer.mrmlScene.GetNodesByClass(nodeType)

        for node in nodesToAdd:
            # Avoid duplication of imagelog proportions node in current widget
            if node.GetAttribute("ShowInFilteredNodeComboBox") == "False":
                continue
            else:
                self.addNode(node)

        def changeNode(index):
            self.blockSignals(True)
            self.setCurrentIndex(
                index
            )  # currentIndexChanged is sent before the index is actually changed; this forces the change to occur before currentNodeChanged is sent
            self.blockSignals(False)
            self.currentNodeChanged.emit(self.currentNode())

        self.currentIndexChanged.connect(changeNode)

    def currentNode(self):
        if self:
            if not self.currentData:
                return None
            return slicer.mrmlScene.GetNodeByID(self.currentData)

    def setCurrentNode(self, node):
        self.setCurrentNodeID(self, node.GetID())

    def setCurrentNodeID(self, nodeID):
        if self:
            index = self.findData(nodeID)
            index = index if index != -1 else 0
            self.setCurrentIndex(index)

    def addAttributeFilter(self, attributeName, attributeValue, classNames=None):
        if classNames == None:
            classNames = self.nodeTypes

        for name in classNames:
            if name not in self.nodeTypes:
                continue
            try:
                self.attributeFilters[name][attributeName].update({attributeValue})
            except KeyError:
                self.attributeFilters[name][attributeName] = {attributeValue}

        for index in range(1, self.count):
            nodeID = self.itemData(index)
            node = slicer.mrmlScene.GetNodeByID(nodeID)
            if node and self._applyFilter(node):
                self.setItemData(index, None, qt.Qt.TextColorRole)
            else:
                self.setItemData(index, qt.QColor(154, 154, 154), qt.Qt.TextColorRole)

    def removeAttributeFilter(self, attributeName, attributeValue, classNames=None):
        if classNames == None:
            classNames = self.nodeTypes
        for name in classNames:
            try:
                nodesToRemove = []
                for index in range(1, self.count):
                    node = slicer.mrmlScene.GetNodeByID(self.itemData(index))
                    if node.GetAttribute(attributeName) == attributeValue:
                        nodesToRemove.append(node)
                for node in nodesToRemove:
                    self.removeNode(node)
                self.attributeFilters[name][attributeName].remove(attributeValue)
            except KeyError:
                continue

    def addNode(self, node):
        if not self._isAcceptedType(node):
            return
        if self and self.findData(node.GetID()) == -1:
            self.addItem(node.GetName(), node.GetID())
            if not self._applyFilter(node):
                self.setItemData(self.count - 1, qt.QColor(154, 154, 154), qt.Qt.TextColorRole)

    def removeNode(self, node):
        if self:
            indexToBeRemoved = self.findData(node.GetID())
            if indexToBeRemoved:
                self.blockSignals(True)
                self.removeItem(indexToBeRemoved)
                self.blockSignals(False)
                self.nodeAboutToBeRemoved.emit(node)

    def _applyFilter(self, node):
        if not self.attributeFilters or node is None:
            return True
        filtersForNodeClass = self.attributeFilters[node.GetClassName()]
        for attributeName in filtersForNodeClass:
            filteredValues = filtersForNodeClass[attributeName]
            attributeValue = node.GetAttribute(attributeName)
            if attributeValue in filteredValues:
                return True
        return False

    def _isAcceptedType(self, data):
        for nodeType in self.nodeTypes:
            if nodeType == type(data).__name__:
                return True
        return False

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def onNodeAdded(self, caller, eventId, callData):
        if not callData.GetHideFromEditors() and self._isAcceptedType(callData):
            self.addNode(callData)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def onNodeAboutToBeRemoved(self, caller, eventId, callData):
        self.removeNode(callData)
