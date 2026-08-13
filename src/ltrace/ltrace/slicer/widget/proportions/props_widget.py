import logging
import traceback
import qt
import ctk
import slicer
import vtk.util.numpy_support

from ltrace.slicer.widget.segment_list_widget import SegmentListWidget
from ltrace.slicer.node_observer import NodeObserver
from ltrace.slicer.helpers import highlight_warning, remove_highlight, themeIsDark
from .props_logic import process_labelmap_volume, process_segmentation_node


class PropListView(SegmentListWidget):
    def __init__(self, *args, **kwargs):
        kwargs["checkable"] = False
        super().__init__(*args, **kwargs)
        self.__props = {}
        self.__is_final = False
        self.setToolTip("")

    def setProps(self, props: dict, is_final: bool = False) -> None:
        self.__props = props if props is not None else {}
        self.__is_final = is_final
        self._updateList()

    def clearProps(self) -> None:
        self.__props = {}
        self.__is_final = False
        self._updateList()

    def createItem(self, name, color, segmentID=None, state=qt.Qt.Unchecked):
        prop = self.__props.get(segmentID)
        if prop is not None:
            equals = "=" if self.__is_final else "≈"
            display_name = f"{name} {equals} {prop * 100:.4g}%"
        else:
            display_name = name
        return super().createItem(display_name, color, segmentID, state)


class PropSegmentListWidget(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(qt.QVBoxLayout(self))
        self.layout().setContentsMargins(0, 0, 0, 0)
        self._currentNodeId = ""
        self._nodeObserver = None
        self._roiObserver = None
        self._setupUI()

    def _setupUI(self):
        self.roiSelector = slicer.qMRMLNodeComboBox()
        self.roiSelector.nodeTypes = ["vtkMRMLSegmentationNode"]
        self.roiSelector.selectNodeUponCreation = False
        self.roiSelector.addEnabled = False
        self.roiSelector.removeEnabled = False
        self.roiSelector.noneEnabled = True
        self.roiSelector.setMRMLScene(slicer.mrmlScene)
        self.roiSelector.currentNodeChanged.connect(self._onRoiNodeChanged)
        self.roiSelector.setToolTip("Select SOI/Mask. Only parts within the first segment of the SOI will be counted.")

        roiLayout = qt.QHBoxLayout()
        roiLayout.addWidget(qt.QLabel("SOI (Optional):"))
        roiLayout.addWidget(self.roiSelector)

        self.segmentList = PropListView()
        self.segmentList.visible = False

        self.staleMessage = qt.QLabel("Data changed. Update required.")
        color = "yellow" if themeIsDark() else "#575700"
        self.staleMessage.setStyleSheet(f"color: {color}")

        self.updateButton = qt.QPushButton("Compute Proportions")
        self.updateButton.setProperty("class", "actionButtonBackground")
        self.updateButton.clicked.connect(self.onUpdateClicked)

        self.progressBar = qt.QProgressBar()
        self.progressBar.setVisible(False)

        self.layout().addLayout(roiLayout)
        self.layout().addWidget(self.segmentList)
        self.layout().addSpacing(5)
        self.layout().addWidget(self.staleMessage)
        self.layout().addWidget(self.updateButton)
        self.layout().addWidget(self.progressBar)

        self._setFresh()

    def setNode(self, node):
        currentNode = slicer.mrmlScene.GetNodeByID(self._currentNodeId)
        if currentNode == node:
            return

        self.segmentList.visible = False
        self.progressBar.setVisible(False)
        self.segmentList.clearProps()
        self._setFresh()

        if self._nodeObserver:
            self._nodeObserver.clear()
            self._nodeObserver.deleteLater()
            self._nodeObserver = None

        self._currentNodeId = node.GetID() if node is not None else ""
        self.segmentList.setNode(node)

        if node:
            self._nodeObserver = NodeObserver(node, parent=self)
            self._nodeObserver.modifiedSignal.connect(self._onNodeModified)

    def _setStale(self):
        if not self.segmentList.visible:
            return
        highlight_warning(self.segmentList)
        self.staleMessage.visible = True
        self.updateButton.text = "Update Proportions"

    def _setFresh(self):
        remove_highlight(self.segmentList)
        self.staleMessage.visible = False
        self.updateButton.text = "Compute Proportions"

    def _onRoiNodeChanged(self, node):
        if self._roiObserver:
            self._roiObserver.clear()
            self._roiObserver = None

        self._setStale()

        if node:
            self._roiObserver = NodeObserver(node)
            self._roiObserver.modifiedSignal.connect(self._onNodeModified)

    def _onNodeModified(self, observer, node):
        self._setStale()

    def onUpdateClicked(self):
        currentNode = slicer.mrmlScene.GetNodeByID(self._currentNodeId)
        if not currentNode:
            return

        self.updateButton.enabled = False
        self.progressBar.setVisible(True)
        self.progressBar.setValue(0)
        self.segmentList.clearProps()
        self.segmentList.visible = True
        self._setFresh()
        slicer.app.processEvents()

        roi_node = self.roiSelector.currentNode()
        processor = None

        try:
            # Determine processor based on node type
            if currentNode.IsA("vtkMRMLLabelMapVolumeNode"):
                processor = process_labelmap_volume(currentNode, roi_node)
            elif currentNode.IsA("vtkMRMLSegmentationNode"):
                processor = process_segmentation_node(currentNode, roi_node)

            if not processor:
                self.updateButton.enabled = True
                self.progressBar.setVisible(False)
                return

            for progress, props, isFinal in processor:
                self.progressBar.setValue(progress)
                self.segmentList.setProps(props, is_final=isFinal)
                slicer.app.processEvents()

        except Exception as e:
            slicer.util.errorDisplay(str(e))
            logging.error(traceback.format_exc())
            self.segmentList.visible = False
            self.segmentList.clearProps()
        finally:
            self.updateButton.enabled = True
            self.progressBar.setVisible(False)


class ProportionsSection(ctk.ctkCollapsibleButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = "Proportions (%)"
        self.setLayout(qt.QVBoxLayout(self))
        self.propList = PropSegmentListWidget()
        self.layout().addWidget(self.propList)

    def setNode(self, node):
        self.propList.setNode(node)
