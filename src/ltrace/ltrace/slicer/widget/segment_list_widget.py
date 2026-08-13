import qt
import slicer
import numpy as np
import typing

from ltrace.slicer import helpers
from ltrace.slicer.node_observer import NodeObserver


class SegmentListWidget(qt.QListWidget):
    def __init__(
        self,
        parent: typing.Optional[qt.QWidget] = None,
        checkable: bool = False,
        defaultState: qt.Qt.CheckState = qt.Qt.Unchecked,
        hideBackground: bool = True,
    ) -> None:
        """Widget to display a list of segments from a segmentation node or a labelmap volume node.

        Args:
            parent (typing.Optional[qt.QWidget], optional): Parent widget. Defaults to None.
            checkable (bool, optional): If True, items can be checked. Defaults to False.
            defaultState (qt.Qt.CheckState, optional): Default check state for items. Defaults to qt.Qt.Unchecked.
            hideBackground (bool, optional): If True, the background segment (index 0) from labelmaps is hidden.
                                             Defaults to True.
        """
        super().__init__(parent)
        self.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Fixed)
        self.setFixedHeight(120)
        self.setToolTip(
            "List of segments available in the segmentation. Check the segments to account them in the computation."
        )
        self.objectName = "Segment List"
        self.checkable = checkable
        self.defaultState = defaultState
        self.currentNodeId = None
        self.hideBackground = hideBackground
        self.__nodeObservers = []
        self.destroyed.connect(self.__del__)

    def __del__(self) -> None:
        """Destructor. Clears all node observers."""
        self._clearNodeObservers()

    def setDefaultState(self, state: qt.Qt.CheckState) -> None:
        """Sets the default check state for new items.

        Args:
            state (qt.Qt.CheckState): The new default check state.
        """
        self.defaultState = state

    def setCheckable(self, checkable: bool) -> None:
        """Sets whether items in the list are checkable.

        Args:
            checkable (bool): True to make items checkable, False otherwise.
        """
        if self.checkable == checkable:
            return

        self.checkable = checkable
        self._updateList()

    def setHideBackground(self, hideBackground: bool) -> None:
        """Sets whether to hide the background segment from labelmaps.

        Args:
            hideBackground (bool): True to hide the background, False otherwise.
        """
        if self.hideBackground == hideBackground:
            return

        self.hideBackground = hideBackground
        self._updateList()

    def _clearNodeObservers(self) -> None:
        """Removes and deletes all node observers."""
        for observer in self.__nodeObservers[:]:
            observer.clear()
            observer.deleteLater()

        self.__nodeObservers.clear()

    def observeNode(self, node: slicer.vtkMRMLNode) -> None:
        """Adds an observer to the given node to update the list on modification.

        Args:
            node (slicer.vtkMRMLNode): The node to observe.
        """
        if node is None:
            return

        nodeObserver = NodeObserver(node=node, parent=self)
        nodeObserver.modifiedSignal.connect(self._updateList)
        self.__nodeObservers.append(nodeObserver)

    def check(self, index: int) -> None:
        """Checks the item at the given index.

        Args:
            index (int): The index of the item to check.
        """
        item = self.item(index)
        item.setCheckState(qt.Qt.Checked)

    def createItem(
        self,
        name: str,
        color: typing.Union[tuple, np.ndarray],
        segmentID: typing.Any = None,
        state: qt.Qt.CheckState = qt.Qt.Unchecked,
    ) -> qt.QListWidgetItem:
        """Creates a new QListWidgetItem with the given properties.

        Args:
            name (str): The name of the segment.
            color (typing.Union[tuple, np.ndarray]): The color of the segment as a tuple or numpy array of RGB values.
            segmentID (typing.Any, optional): The segment ID. Defaults to None.
            state (qt.Qt.CheckState, optional): The initial check state. Defaults to qt.Qt.Unchecked.

        Returns:
            qt.QListWidgetItem: The created item.
        """
        from ltrace.slicer.widgets import ColoredIcon  # avoid circular import

        item = qt.QListWidgetItem(name)
        flags = item.flags()
        if self.checkable:
            flags |= qt.Qt.ItemIsUserCheckable

        item.setFlags(flags)

        if self.checkable:
            item.setCheckState(state)
        icon = ColoredIcon(*[int(c * 255) for c in color[:3]])
        item.setIcon(icon)
        item.setData(qt.Qt.UserRole, segmentID)
        return item

    def newItem(
        self,
        name: str,
        color: typing.Union[tuple, np.ndarray],
        segmentID: typing.Any = None,
        state: qt.Qt.CheckState = qt.Qt.Unchecked,
    ) -> None:
        """Creates a new item and adds it to the list.

        Args:
            name (str): The name of the segment.
            color (typing.Union[tuple, np.ndarray]): The color of the segment.
            segmentID (typing.Any, optional): The segment ID. Defaults to None.
            state (qt.Qt.CheckState, optional): The initial check state. Defaults to qt.Qt.Unchecked.
        """
        item = self.createItem(name, color, segmentID, state)
        self.addItem(item)

    def getCheckedItems(self) -> typing.List[typing.Any]:
        """Gets the segment IDs of all checked items.

        Returns:
            typing.List[typing.Any]: A list of segment IDs for the checked items.
        """
        checkedItems = []
        for index in range(self.count):
            item = self.item(index)
            if item.checkState() == qt.Qt.Checked:
                if item.data(qt.Qt.UserRole):
                    checkedItems.append(item.data(qt.Qt.UserRole))
        return checkedItems

    def setNode(self, node: typing.Optional[slicer.vtkMRMLNode]) -> None:
        """Sets the node to display the segments from.

        It can be a vtkMRMLSegmentationNode or a vtkMRMLLabelMapVolumeNode.
        If None, the list is cleared.

        Args:
            node (typing.Optional[slicer.vtkMRMLNode]): The node to display segments from.
        """
        self._clearNodeObservers()
        self.clear()
        self.currentNodeId = node.GetID() if node is not None else None

        self._updateList()

        if node is None:
            return

        self.observeNode(node)

    def _updateList(self) -> None:
        """Updates the list of segments based on the current node."""
        checkedIndexes = self.getCheckedIndexes()

        self.clear()

        if self.currentNodeId is None:
            return

        node = helpers.tryGetNode(self.currentNodeId)

        if node is None:
            return

        if node.IsA("vtkMRMLSegmentationNode"):
            self.setDataFromSegmentation(node, checkedIndexes)
        else:
            self.setDataFromLabelMap(node, checkedIndexes)

    def setDataFromSegmentation(self, node: slicer.vtkMRMLSegmentationNode, checkedIndexes: typing.List[int]) -> None:
        """Populates the list with segments from a vtkMRMLSegmentationNode.

        Args:
            node (slicer.vtkMRMLSegmentationNode): The segmentation node.
            checkedIndexes (typing.List[int]): List of previously checked item indices to preserve selection.
        """
        if node is None:
            return

        segmentation = node.GetSegmentation()
        displayNode = node.GetDisplayNode()

        for index in range(segmentation.GetNumberOfSegments()):
            segment = segmentation.GetNthSegment(index)
            segmentID = segmentation.GetNthSegmentID(index)
            if segment:
                segmentName = segment.GetName()
                checkState = qt.Qt.Checked if index in checkedIndexes else self.defaultState
                self.newItem(
                    segmentName,
                    np.array(segment.GetColor() + (1,)),
                    segmentID,
                    checkState,
                )

    def setDataFromLabelMap(self, node: slicer.vtkMRMLLabelMapVolumeNode, checkedIndexes: typing.List[int]) -> None:
        """Populates the list with segments from a vtkMRMLLabelMapVolumeNode.

        Args:
            node (slicer.vtkMRMLLabelMapVolumeNode): The labelmap node.
            checkedIndexes (typing.List[int]): List of previously checked item indices to preserve selection.
        """
        if node is None or not node.GetDisplayNode():
            return

        inputColors = node.GetDisplayNode().GetColorNode()
        if inputColors is None:
            return

        imageData = node.GetImageData()
        if imageData is None:
            return

        scalarRange = imageData.GetScalarRange()
        startIndex = 1 if self.hideBackground else 0
        for index in range(startIndex, inputColors.GetNumberOfColors()):
            if scalarRange[0] <= index <= scalarRange[1]:
                color = np.zeros(4)
                inputColors.GetColor(index, color)
                name = inputColors.GetColorName(index)

                if index == 0 and not any(color):
                    name = name if not self._isSegmentNameBackground(name) else "Background"

                if name.lower() == "background" and self.hideBackground:
                    continue

                checkState = qt.Qt.Checked if index in checkedIndexes else self.defaultState
                self.newItem(
                    name,
                    np.array(color),
                    index,
                    checkState,
                )

    def _isSegmentNameBackground(self, name: str) -> bool:
        """Checks if a segment name is the background.

        Args:
            name (str): The name of the segment.

        Returns:
            bool: True if the segment is the background, False otherwise.
        """
        if name is None:
            return False

        return name.lower() == "background" or name.strip() == "" or name == "(none)"

    def setStateByID(self, id: typing.Any, state: qt.Qt.CheckState) -> None:
        """Sets the check state of an item by its segment ID.

        Args:
            id (typing.Any): The segment ID of the item.
            state (qt.Qt.CheckState): The new check state.
        """
        for index in range(self.count):
            item = self.item(index)
            if item.data(qt.Qt.UserRole) != id:
                continue

            item.setCheckState(state)
            break

    def setStateByIndex(self, index: int, state: qt.Qt.CheckState) -> None:
        """Sets the check state of an item by its index in the list.

        Args:
            index (int): The index of the item.
            state (qt.Qt-CheckState): The new check state.
        """
        if index > self.count or index < 0:
            return

        item = self.item(index)
        item.setCheckState(state)

    def getCheckedIndexes(self) -> typing.List[int]:
        """Gets the indices of all checked items.

        Returns:
            typing.List[int]: A list of indices for the checked items.
        """
        if self.currentNodeId is None:
            return []

        node = helpers.tryGetNode(self.currentNodeId)
        if not node:
            return []

        if node.IsA("vtkMRMLSegmentationNode"):
            return self._getCheckedIndexesFromSegmentation(node)

        return self._getCheckedIndexesFromLabelMap(node)

    def _getCheckedIndexesFromSegmentation(self, node: slicer.vtkMRMLSegmentationNode) -> typing.List[int]:
        if self.currentNodeId is None:
            return []

        segmentation = node.GetSegmentation()

        checkedIndexes = []
        for listIndex in range(self.count):
            item = self.item(listIndex)
            if item.checkState() == qt.Qt.Checked:
                segmentID = item.data(qt.Qt.UserRole)
                segmentIdx = segmentation.GetSegmentIndex(segmentID)
                if segmentIdx == -1:
                    continue

                checkedIndexes.append(segmentIdx)

        return checkedIndexes

    def _getCheckedIndexesFromLabelMap(self, node: slicer.vtkMRMLLabelMapVolumeNode) -> typing.List[int]:
        if self.currentNodeId is None:
            return []

        checkedIndexes = []
        for index in range(self.count):
            item = self.item(index)
            if item.checkState() == qt.Qt.Checked:
                checkedIndexes.append(index)

        return checkedIndexes
