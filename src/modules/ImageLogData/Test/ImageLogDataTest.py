import slicer
import qt
import vtk

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import (
    process_events,
    load_project,
    wait,
    save_project,
    close_project,
    loadEnvironmentByName,
    waitCondition,
)
from commons.slicer.helpers import tryGetNode, make_directory_writable, getCurrentEnvironment, createTemporaryVolumeNode
from commons.slicer.metadata import Metadata

from pathlib import Path
import numpy as np
import shutil
import tempfile
import pyqtgraph as pg


TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
SINGLE_VOLUME_PROJECT_FILE = TEST_RESOURCES_DIR / "SingleVolume" / "SingleVolume.mrml"
IMAGELOG_PROJECT_FILE = TEST_RESOURCES_DIR / "ImageLogLoader" / "ImageLogLoader.mrml"
SEGMENTED_VOLUME_PROJECT_FILE = TEST_RESOURCES_DIR / "SegmentedVolume" / "SegmentedVolume.mrml"
FOUR_VOLUMES_1SEG_PROJECT_FILE = TEST_RESOURCES_DIR / "FourVolumesOneSeg" / "FourVolumesOneSeg.mrml"
NMR_PROJECT_FILE = TEST_RESOURCES_DIR / "NMR" / "NMR.mrml"


def _simulateMouseWheel(widget=None, delta: int = 200) -> None:
    centerPosF = centerGlobalPosF = qt.QPointF(0, 0)

    # Move
    event = qt.QMouseEvent(
        qt.QEvent.MouseMove, centerPosF, centerGlobalPosF, qt.Qt.NoButton, qt.Qt.NoButton, qt.Qt.NoModifier
    )
    slicer.app.sendEvent(widget, event)

    wait(0.1)

    event = qt.QWheelEvent(centerPosF, centerGlobalPosF, delta, qt.Qt.NoModifier, qt.Qt.NoModifier, qt.Qt.Vertical)
    # Wheel
    slicer.app.sendEvent(widget, event)

    wait(0.1)


def _addNodeToView(widget, node):
    addViewButton = widget.logic.containerWidgets["toolBarWidget"].findChild(qt.QPushButton, "Add view button")
    assert addViewButton is not None

    leftPanelSubjectHierarchyTreeView = slicer.modules.ImageLogDataWidget.subjectHierarchyTreeView
    assert leftPanelSubjectHierarchyTreeView is not None

    def getItemIdFromNode(node):
        return leftPanelSubjectHierarchyTreeView.subjectHierarchyNode().GetItemByDataNode(node)

    leftPanelSubjectHierarchyTreeView.setCurrentItem(getItemIdFromNode(node))
    process_events()
    widget.addView()


class ImageLogDataTest(LTracePluginTest):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def pre_setup(self):
        if getCurrentEnvironment() != "ImageLogEnv":
            loadEnvironmentByName("Well Logs")

    def post_setup(self) -> None:
        """Test case setup handler, applied before reloding the widgets"""
        self.tempDirectory = Path(tempfile.TemporaryDirectory().name)
        self.tempDirectory.mkdir(parents=True, exist_ok=True)

        trackImageWidget = self.find_widget(name="Track Image Widget")
        self.__widgets = {
            "trackImageWidget": trackImageWidget,
            "stdEditField": self.find_widget(name="STD Edit Field", obj=trackImageWidget),
            "subjectHierarchyTreeView": self.find_widget(name="SubjectHierarchyTreeView"),
        }

        for objectName, widget in self.__widgets.items():
            assert widget is not None, f"widget related to the objectName '{objectName}' is None!"

    def __selectNodeInSubjectHierarchyTreeView(self, node):
        subjectHierarchyTreeView = self.__widgets["subjectHierarchyTreeView"]
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemNodeId = subjectHierarchyNode.GetItemByDataNode(node)
        subjectHierarchyTreeView.setCurrentItem(itemNodeId)
        process_events()

    def __cloneNode(self, node) -> slicer.vtkMRMLScalarVolumeNode:
        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemIDToClone = subjectHierarchyNode.GetItemByDataNode(node)
        clonedItemID = slicer.modules.subjecthierarchy.logic().CloneSubjectHierarchyItem(
            subjectHierarchyNode, itemIDToClone
        )
        clonedNode = subjectHierarchyNode.GetItemDataNode(clonedItemID)
        process_events()

        return clonedNode

    def __assertViews(self, parent, widgetNamesAndTypes, numViews):
        for i in range(numViews):
            for widgetName, widgetType in widgetNamesAndTypes.items():
                fullWidgetName = f"{widgetName}{i}"
                widget = parent.findChild(widgetType, fullWidgetName)
                assert widget is not None, f"Widget {fullWidgetName} not found or has incorrect type"

    def tear_down(self) -> None:
        """Tear down method for test case."""
        shutil.rmtree(self.tempDirectory, onexc=make_directory_writable)

    def test_std_field_enablement_logic_when_cloning_volume(self) -> None:
        load_project(SINGLE_VOLUME_PROJECT_FILE)

        stdEditField = self.__widgets["stdEditField"]
        assert stdEditField.enabled

        node = tryGetNode("Volume")
        assert node is not None

        self.__selectNodeInSubjectHierarchyTreeView(node)
        process_events()
        assert stdEditField.enabled

        clonedVolumeNode = self.__cloneNode(node)
        clonedNode = tryGetNode("Volume Copy")
        assert clonedNode is not None and clonedNode is clonedVolumeNode

        self.__selectNodeInSubjectHierarchyTreeView(clonedNode)
        process_events()
        assert stdEditField.enabled

    def test_interface_default_values_for_widgets(self) -> None:
        # Track Image widget
        assert self.__widgets["stdEditField"].enabled

    def test_mouse_wheel_scroll_image_log_volume_view(self) -> None:
        mouseWheelForward = [False]
        mouseWheelBackward = [False]

        def onScrollForward(interactorStyle, *args):
            mouseWheelForward[0] = True

        def onScrollBackward(interactorStyle, *args):
            mouseWheelBackward[0] = True

        def setupSliceViewWidget(logic):
            for identifier in logic.getViewDataListIdentifiers():
                sliceViewWidget = logic.viewWidgets[identifier]
                if sliceViewWidget is None or not hasattr(sliceViewWidget, "sliceView"):
                    continue

                sliceView = sliceViewWidget.sliceView()
                sliceViewInteractorStyle = (
                    sliceView.interactorObserver()
                    if hasattr(sliceView, "interactorObserver")
                    else sliceView.sliceViewInteractorStyle()
                )

                forwardObserver = sliceViewInteractorStyle.GetInteractor().AddObserver(
                    vtk.vtkCommand.MouseWheelForwardEvent, onScrollForward
                )
                backwardObserver = sliceViewInteractorStyle.GetInteractor().AddObserver(
                    vtk.vtkCommand.MouseWheelBackwardEvent, onScrollBackward
                )

                observers = [forwardObserver, backwardObserver]

                return sliceViewWidget, observers

        load_project(SINGLE_VOLUME_PROJECT_FILE)

        imageLogDataWidget = self._module_widget.parent
        imageLogDataWidget.show()
        logic = imageLogDataWidget.self().logic

        logic.imageLogViewList = []
        logic.refreshViews()
        wait(0.2)

        logic.addView()
        wait(0.2)

        scalarVolumeNode = tryGetNode("Volume")
        logic.primaryNodeChanged(0, scalarVolumeNode)
        logic.refreshViews()
        wait(0.2)

        sliceViewWidget, observers = setupSliceViewWidget(logic=logic)

        widget = sliceViewWidget.childAt(sliceViewWidget.pos)
        _simulateMouseWheel(widget=widget, delta=200)
        wait(0.2)

        _simulateMouseWheel(widget=widget, delta=-200)
        wait(0.2)

        for observer in observers:
            sliceView = sliceViewWidget.sliceView()
            sliceViewInteractorStyle = (
                sliceView.interactorObserver()
                if hasattr(sliceView, "interactorObserver")
                else sliceView.sliceViewInteractorStyle()
            )
            sliceViewInteractorStyle.GetInteractor().RemoveObserver(observer)

        assert mouseWheelForward[0] is True
        assert mouseWheelBackward[0] is True

    def test_aspect_ratio(self):
        widget = self._module_widget
        widget.addView()

        array = np.random.rand(200, 1, 200)
        scalar = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        slicer.util.updateVolumeFromArray(scalar, array)

        widget.logic.primaryNodeChanged(0, scalar)

        wait(5)
        axisWidget = widget.logic.containerWidgets["axisWidget"]
        aspectRatioWidget = axisWidget.findChild(qt.QDoubleSpinBox, "scaleInput")
        viewLogic = slicer.app.layoutManager().sliceWidget("ImageLogSliceView0").sliceLogic()
        self.assertAlmostEqual(aspectRatioWidget.value, 1 / viewLogic.GetAspectRatio(), delta=0.01)

        aspectRatioWidget.setValue(10)
        wait(5)
        self.assertAlmostEqual(0.1, viewLogic.GetAspectRatio(), delta=0.01)

    def test_aspect_ratio_buttons(self):
        # Setup
        widget = self._module_widget
        widget.addView()

        array = np.random.rand(200, 1, 20)
        scalar = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        slicer.util.updateVolumeFromArray(scalar, array)
        widget.logic.primaryNodeChanged(0, scalar)
        wait(5)

        toolBarWidget = widget.logic.containerWidgets["toolBarWidget"]
        fitRealButton = toolBarWidget.findChild(qt.QPushButton, "Fit Real Button")
        fitAllButton = toolBarWidget.findChild(qt.QPushButton, "Fit All Button")
        viewLogic = slicer.app.layoutManager().sliceWidget("ImageLogSliceView0").sliceLogic()

        fitRealButton.click()
        wait(5)
        self.assertAlmostEqual(1.0, viewLogic.GetAspectRatio(), delta=0.01)

        fitAllButton.click()
        wait(5)
        self.assertLess(viewLogic.GetAspectRatio(), 0.8)

    def test_load_views_from_imagelog_project(self):
        projectFilePath = self.tempDirectory / "imagelog_dummy_project" / "imagelog_dummy_project.mrml"
        centralWidgetLayoutFrame = slicer.modules.AppContextInstance.mainWindow.findChild(
            qt.QFrame, "CentralWidgetLayoutFrame"
        )
        imageLogDataWidget = self._module_widget.parent
        imageLogDataWidget.show()
        logic = imageLogDataWidget.self().logic
        load_project(IMAGELOG_PROJECT_FILE)

        logic.refreshViews()
        wait(0.2)

        viewWidgets = {
            "viewLabel": qt.QLabel,
            "settingsToolButton": qt.QToolButton,
            "primaryNodeComboBox": qt.QComboBox,
        }

        # views loaded from project
        wait(0.3)
        numViews = 3
        assert centralWidgetLayoutFrame
        self.__assertViews(centralWidgetLayoutFrame, viewWidgets, numViews)

        # add a new table view
        logic.addView()
        tableNode = tryGetNode("TDEP [ft]")
        assert tableNode is not None
        logic.primaryNodeChanged(3, tableNode)
        logic.refreshViews()
        wait(0.2)

        save_project(projectFilePath)
        close_project()
        load_project(projectFilePath)
        wait(2)
        logic.refreshViews()
        wait(1)

        centralWidgetLayoutFrame = slicer.modules.AppContextInstance.mainWindow.findChild(
            qt.QFrame, "CentralWidgetLayoutFrame"
        )
        # views loaded from saved project
        numViews = 4
        assert centralWidgetLayoutFrame
        self.__assertViews(centralWidgetLayoutFrame, viewWidgets, numViews)

    def test_proportions_label_map_behavior(self):
        load_project(SEGMENTED_VOLUME_PROJECT_FILE)

        # Get nodes
        volumeNode = tryGetNode("Volume")
        segmentationNode = tryGetNode("Segmentation")
        assert volumeNode is not None
        assert segmentationNode is not None

        # Add view and select the nodes
        widget = self._module_widget
        widget.addView()
        widget.logic.primaryNodeChanged(0, volumeNode)
        widget.logic.segmentationNodeChanged(0, segmentationNode)
        widget.logic.refreshViews()
        wait(1)

        # Check proportion label map volume created
        proportionsNode = tryGetNode("Segmentation_Proportions")
        assert proportionsNode is not None

        # Check proportion label map volume is selected in the view
        proportionsNodeId = widget.logic.imageLogViewList[0].viewData.proportionsNodeId
        assert proportionsNodeId == proportionsNode.GetID()

    def test_proportion_label_map_exists_when_segmentation_is_empty(self):
        # Create dummy label map node
        labelMapArray = np.random.randint(3, size=(16, 16, 16))
        labelMapNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode", "LabelMap")
        slicer.util.updateVolumeFromArray(labelMapNode, labelMapArray.astype(np.uint32))

        # Create empty segmentation node
        segmentationNode = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLSegmentationNode.__name__, "Segmentation")
        segmentationNode.CreateDefaultDisplayNodes()

        # Add view and select the nodes
        widget = self._module_widget
        widget.addView()
        widget.logic.primaryNodeChanged(0, labelMapNode)
        widget.logic.segmentationNodeChanged(0, segmentationNode)
        widget.logic.refreshViews()
        process_events()

        # Check proportion label map volume created
        proportionsNode = tryGetNode("Segmentation_Proportions")
        assert proportionsNode is not None

        projectFilePath = self.tempDirectory / "test_project" / "test_project.mrml"
        saveStatus = save_project(projectFilePath)

        assert saveStatus is True, "Failed to save the project."
        assert projectFilePath.exists()

    def test_multi_axis_graphic_view(self):
        widget = self._module_widget
        widget.addView()

        array = np.zeros((10, 2))
        array[:, 0] = np.linspace(1, 10, 10) * 1000
        array[:, 1] = np.linspace(1, 10, 10)

        table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
        slicer.util.updateTableFromArray(table, array)
        table.GetTable().GetColumn(0).SetName("DEPTH")
        table.GetTable().GetColumn(1).SetName("DATA")

        widget.logic.primaryNodeChanged(0, table)
        widget.logic.refreshViews()
        wait(0.2)

        view = widget.logic.imageLogViewList[0]
        plot_item = view.widget.curve_plot._plot_item
        secondary_plot_view_box = view.widget.curve_plot.secondary_view_box

        assert not plot_item.layout.itemAt(0, 1) == view.widget.curve_plot.secondary_axis
        assert secondary_plot_view_box not in plot_item.scene().items()
        assert not any(isinstance(item, type(pg.PlotCurveItem())) for item in secondary_plot_view_box.allChildren())
        assert not [
            item for item in secondary_plot_view_box.allChildren() if isinstance(item, type(pg.PlotCurveItem()))
        ]

        array[:, 1] = np.linspace(10, 1, 10) * 1000
        secondary_table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
        slicer.util.updateTableFromArray(secondary_table, array)
        secondary_table.GetTable().GetColumn(0).SetName("DEPTH")
        secondary_table.GetTable().GetColumn(1).SetName("DATA")

        widget.logic.secondaryTableNodeChanged(0, secondary_table)
        widget.logic.refreshViews()
        wait(0.2)
        process_events()

        plot_item = view.widget.curve_plot._plot_item
        secondary_plot_view_box = view.widget.curve_plot.secondary_view_box

        assert plot_item.layout.itemAt(0, 1) == view.widget.curve_plot.secondary_axis, (
            f"Expected {view.widget.curve_plot.secondary_axis}, got {plot_item.layout.itemAt(0, 1)}"
        )
        assert secondary_plot_view_box in plot_item.scene().items()
        assert any(isinstance(item, type(pg.PlotCurveItem())) for item in secondary_plot_view_box.allChildren())
        assert [item for item in secondary_plot_view_box.allChildren() if isinstance(item, type(pg.PlotCurveItem()))]

    def test_mouse_wheel_interactor_observers_not_accumulating(self) -> None:
        load_project(SINGLE_VOLUME_PROJECT_FILE)

        imageLogDataWidget = self._module_widget.parent
        imageLogDataWidget.show()
        logic = imageLogDataWidget.self().logic

        assert len(logic.observedInteractors) == 0, f"Expected 0 observers, got {len(logic.observedInteractors)}"

        logic.imageLogViewList = []
        logic.refreshViews()
        wait(0.2)

        scalarVolumeNode = tryGetNode("Volume")
        for i in range(4):
            logic.addView()
            process_events()

            logic.primaryNodeChanged(i, scalarVolumeNode)

        wait(0.2)
        logic.refreshViews()
        process_events()

        # assert 2 interactor observers (up/down scroll move) for each view
        assert len(logic.observedInteractors) == 8, f"Expected 8 observers, got {len(logic.observedInteractors)}"

        for i in reversed(range(4)):
            logic.removeView(i)

        wait(0.2)
        logic.refreshViews()
        process_events()

        assert len(logic.observedInteractors) == 0, f"Expected 0 observers, got {len(logic.observedInteractors)}"

    def test_add_view_button(self):
        addViewButton = self._module_widget.logic.containerWidgets["toolBarWidget"].findChild(
            qt.QPushButton, "Add view button"
        )
        assert addViewButton is not None

        # Interact with the widget modules from slicer.modules due to the button is related to the ImageLogDataLogic,
        # which is an unique instance but use the widget references from slicer.modules
        leftPanelSubjectHierarchyTreeView = slicer.modules.ImageLogDataWidget.subjectHierarchyTreeView
        assert leftPanelSubjectHierarchyTreeView is not None

        rightPanelSubjectHierarchyTreeView = slicer.modules.ImageLogDataDockedWidget.subjectHierarchyTreeView
        assert rightPanelSubjectHierarchyTreeView is not None

        def getItemIdFromNode(node):
            return leftPanelSubjectHierarchyTreeView.subjectHierarchyNode().GetItemByDataNode(node)

        node = createTemporaryVolumeNode(
            slicer.vtkMRMLScalarVolumeNode, name="TestNode", environment="test", saveWithScene=True, hidden=False
        )
        array = np.random.randint(0, 255, size=(3, 500, 500))
        slicer.util.updateVolumeFromArray(node, array.astype(np.int32))
        node.SetOrigin(0, 0, 0)
        node.SetSpacing(1, 1, 1)

        leftPanelSubjectHierarchyTreeView.setCurrentItem(getItemIdFromNode(node))

        # Add #1: No selected node in both panels
        leftPanelSubjectHierarchyTreeView.setCurrentItem(0)
        rightPanelSubjectHierarchyTreeView.setCurrentItem(0)
        process_events()
        self._module_widget.addView()
        process_events()

        # Add #2: Selected node in left panel
        leftPanelSubjectHierarchyTreeView.setCurrentItem(getItemIdFromNode(node))
        rightPanelSubjectHierarchyTreeView.setCurrentItem(0)
        process_events()
        self._module_widget.addView()
        process_events()

        # Add 3: Selected node in the right panel
        leftPanelSubjectHierarchyTreeView.setCurrentItem(0)
        rightPanelSubjectHierarchyTreeView.setCurrentItem(getItemIdFromNode(node))
        process_events()
        self._module_widget.addView()
        process_events()

        # Add 4: Selected node in both panels, being the left panel the preffered for the view add logic
        leftPanelSubjectHierarchyTreeView.setCurrentItem(getItemIdFromNode(node))
        rightPanelSubjectHierarchyTreeView.setCurrentItem(0)
        process_events()
        self._module_widget.addView()
        process_events()

        assert len(self._module_widget.logic.imageLogViewList) == 4, (
            f"Expected 4 views, got {len(self._module_widget.logic.imageLogViewList)}"
        )
        assert self._module_widget.logic.getViewPrimaryNode(identifier=0) is None, (
            f"Expected None, got {self._module_widget.logic.getViewPrimaryNode(identifier=0)}"
        )
        assert self._module_widget.logic.getViewPrimaryNode(identifier=1) == node, (
            f"Expected {node.GetID()}, got {self._module_widget.logic.getViewPrimaryNode(identifier=1).GetID()}"
        )
        assert self._module_widget.logic.getViewPrimaryNode(identifier=2) == node, (
            f"Expected {node.GetID()}, got {self._module_widget.logic.getViewPrimaryNode(identifier=2).GetID()}"
        )
        assert self._module_widget.logic.getViewPrimaryNode(identifier=3) == node, (
            f"Expected {node.GetID()}, got {self._module_widget.logic.getViewPrimaryNode(identifier=3).GetID()}"
        )

    def test_drag_reordering_views(self):
        load_project(FOUR_VOLUMES_1SEG_PROJECT_FILE)

        node_WF1 = tryGetNode("Forge 78B-32_WF1 []")
        assert node_WF1 is not None
        node_STTA1 = tryGetNode("Forge 78B-32_STTA1 [us]")
        assert node_STTA1 is not None
        node_MUDT = tryGetNode(
            "MTEM [degF]"
        )  # this is 1D, leading to a GraphicView. The other three are 2D->SliceViews
        assert node_MUDT is not None
        node_VDL = tryGetNode("Forge 78B-32_VDL []")
        assert node_VDL is not None

        nodes = [node_WF1, node_STTA1, node_MUDT, node_VDL]
        initial_nodes_names = [n.GetName() for n in nodes]

        segmentationNodeName = "TestSegmentation"
        segmentationNode = tryGetNode(segmentationNodeName)

        assert segmentationNode

        imageLogDataWidget = self._module_widget.parent
        logic = imageLogDataWidget.self().logic
        imageLogDataWidget.show()

        #
        #  The layout arrays aren't saved in the scene. We have to populate them by adding views

        logic.addView()
        wait(0.2)
        logic.primaryNodeChanged(0, nodes[0])
        wait(0.2)
        logic.addView()
        wait(0.2)
        logic.primaryNodeChanged(1, nodes[1])
        logic.segmentationNodeChanged(1, segmentationNode)
        wait(0.2)
        logic.addView()
        wait(0.2)
        logic.primaryNodeChanged(2, nodes[2])
        wait(0.2)
        logic.addView()
        wait(0.2)
        logic.primaryNodeChanged(3, nodes[3])
        wait(0.2)

        #
        # Simulate dragging 3rd view to the 1st view.

        assert logic.getViewDataListIdentifiers() == [0, 1, 2, 3]

        primaryNodeComboBox0 = logic.viewControllerWidget_PrimaryNodeComboBox(0)
        assert primaryNodeComboBox0
        assert primaryNodeComboBox0.currentNode() == nodes[0]
        primaryNodeComboBox1 = logic.viewControllerWidget_PrimaryNodeComboBox(1)
        assert primaryNodeComboBox1
        assert primaryNodeComboBox1.currentNode() == nodes[1]
        primaryNodeComboBox2 = logic.viewControllerWidget_PrimaryNodeComboBox(2)
        assert primaryNodeComboBox2
        assert primaryNodeComboBox2.currentNode() == nodes[2]
        primaryNodeComboBox3 = logic.viewControllerWidget_PrimaryNodeComboBox(3)
        assert primaryNodeComboBox3
        assert primaryNodeComboBox3.currentNode() == nodes[3]
        label2 = logic.viewControllerWidget_Label(2)

        imageLogDataWidget = slicer.util.getModuleWidget("ImageLogData")
        eventSimulationDone = [False]

        def simulateDragnDropEvents():
            mimeData = qt.QMimeData()
            mimeData.setText("draggingView2")
            event = qt.QDragEnterEvent(
                qt.QPoint(
                    logic.viewControllerWidget_Label(2).rect.center().x(),
                    logic.viewControllerWidget_Label(2).rect.center().y(),
                ),
                qt.Qt.CopyAction | qt.Qt.MoveAction,
                mimeData,
                qt.Qt.LeftButton,
                qt.Qt.NoModifier,
            )
            slicer.app.sendEvent(label2, event)
            process_events()
            label2centerGlobal = logic.viewControllerWidget_Label(2).mapToGlobal(
                logic.viewControllerWidget_Label(2).rect.center()
            )
            event = qt.QMouseEvent(
                qt.QEvent.MouseMove,
                qt.QPointF(
                    logic.viewControllerWidget_Label(2).rect.center().x(),
                    logic.viewControllerWidget_Label(2).rect.center().y(),
                ),
                qt.QPointF(label2centerGlobal.x(), label2centerGlobal.y()),
                qt.Qt.LeftButton,
                qt.Qt.LeftButton,
                qt.Qt.NoModifier,
            )
            slicer.app.sendEvent(label2, event)  # slicer.modules.AppContextInstance.mainWindow, event)
            process_events()
            event = qt.QDragMoveEvent(
                qt.QPoint(
                    logic.viewControllerWidget_Label(2).rect.center().x(),
                    logic.viewControllerWidget_Label(2).rect.center().y(),
                ),
                qt.Qt.CopyAction | qt.Qt.MoveAction,
                mimeData,
                qt.Qt.LeftButton,
                qt.Qt.NoModifier,
            )
            slicer.app.sendEvent(label2, event)
            process_events()
            # enter view 0...
            label0centerGlobal = logic.viewControllerWidget_Label(0).mapToGlobal(
                logic.viewControllerWidget_Label(0).rect.center()
            )
            event = qt.QDragEnterEvent(
                qt.QPoint(label0centerGlobal.x(), label0centerGlobal.y()),
                qt.Qt.CopyAction | qt.Qt.MoveAction,
                mimeData,
                qt.Qt.LeftButton,
                qt.Qt.NoModifier,
            )
            slicer.app.sendEvent(label2, event)
            process_events()
            label0centerGlobal = logic.viewControllerWidget_Label(0).mapToGlobal(
                logic.viewControllerWidget_Label(0).rect.center()
            )
            event = qt.QMouseEvent(
                qt.QEvent.MouseMove,
                qt.QPointF(label0centerGlobal.x(), label0centerGlobal.y()),
                qt.QPointF(label0centerGlobal.x(), label0centerGlobal.y()),
                qt.Qt.LeftButton,
                qt.Qt.LeftButton,
                qt.Qt.NoModifier,
            )
            slicer.app.sendEvent(slicer.modules.AppContextInstance.mainWindow, event)
            process_events()
            event = qt.QDragMoveEvent(
                qt.QPoint(label0centerGlobal.x(), label0centerGlobal.y()),
                qt.Qt.CopyAction | qt.Qt.MoveAction,
                mimeData,
                qt.Qt.LeftButton,
                qt.Qt.NoModifier,
            )
            slicer.app.sendEvent(slicer.modules.AppContextInstance.mainWindow, event)
            process_events()
            # ... and drop
            label0ByLabel2 = logic.viewControllerWidget_Label(2).mapFromGlobal(label0centerGlobal)
            event = qt.QDropEvent(
                qt.QPointF(label0ByLabel2.x(), label0ByLabel2.y()),
                qt.Qt.CopyAction | qt.Qt.MoveAction,
                mimeData,
                qt.Qt.LeftButton,
                qt.Qt.NoModifier,
            )
            slicer.app.sendEvent(label2, event)
            process_events()
            event = qt.QMouseEvent(
                qt.QEvent.MouseButtonRelease,
                qt.QPointF(label0ByLabel2.x(), label0ByLabel2.y()),
                qt.QPointF(label0ByLabel2.x(), label0ByLabel2.y()),
                qt.Qt.LeftButton,
                qt.Qt.LeftButton,
                qt.Qt.NoModifier,
            )
            slicer.app.sendEvent(label2, event)
            process_events()
            eventSimulationDone[0] = True

        # Set a single shot timer to execute those events after
        # mouse button press causing a blocking event
        qt.QTimer.singleShot(1000, simulateDragnDropEvents)
        # Dragging: Mouse down at label2...
        event = qt.QMouseEvent(
            qt.QEvent.MouseButtonPress,
            qt.QPointF(label2.rect.center().x(), label2.rect.center().y()),
            qt.QPointF(label2.rect.center().x(), label2.rect.center().y()),
            qt.Qt.LeftButton,
            qt.Qt.LeftButton,
            qt.Qt.NoModifier,
        )
        slicer.app.sendEvent(label2, event)
        process_events()
        waitCondition(lambda: eventSimulationDone[0], timeoutSec=10)

        # The references are lost at this point because the layout reordering recreates the widgets
        primaryNodeComboBox0 = logic.viewControllerWidget_PrimaryNodeComboBox(0)
        primaryNodeComboBox1 = logic.viewControllerWidget_PrimaryNodeComboBox(1)
        primaryNodeComboBox2 = logic.viewControllerWidget_PrimaryNodeComboBox(2)
        primaryNodeComboBox3 = logic.viewControllerWidget_PrimaryNodeComboBox(3)

        assert primaryNodeComboBox0.currentNode().GetName() == initial_nodes_names[2]
        assert primaryNodeComboBox1.currentNode().GetName() == initial_nodes_names[0]
        assert primaryNodeComboBox2.currentNode().GetName() == initial_nodes_names[1]
        assert primaryNodeComboBox3.currentNode().GetName() == initial_nodes_names[3]

        # Finally, the segmentation node now should be in the view 2...
        segmentationNodeComboBox2 = logic.viewControllerWidget_segmentationNodeComboBox(2)
        assert segmentationNodeComboBox2.currentNode().GetName() == segmentationNodeName

        # ... and the view 1 shouldn't have a segmentation node anymore
        segmentationNodeComboBox1 = logic.viewControllerWidget_segmentationNodeComboBox(1)
        assert segmentationNodeComboBox1.currentNode() is None

    def test_observers_handling(self) -> None:
        """Test observer references life-time handling"""
        load_project(SEGMENTED_VOLUME_PROJECT_FILE)

        # Get nodes
        volumeNode = tryGetNode("Volume")
        segmentationNode = tryGetNode("Segmentation")
        assert volumeNode is not None
        assert segmentationNode is not None

        widget = self._module_widget
        logic = widget.logic

        # Due to an unidentified bug, the first time a view is created and filled with a volume node, it will process the same view identifier twice
        # So the steps below will populate the views, before the actual test, to avoid this behavior
        widget.addView()
        widget.addView()
        logic.primaryNodeChanged(0, volumeNode)
        logic.primaryNodeChanged(1, volumeNode)
        logic.refreshViews()
        wait(0.5)
        logic.primaryNodeChanged(0, None)
        logic.primaryNodeChanged(1, None)
        wait(0.5)

        assert len(logic.observedPrimaryNodes) == 0, (
            f"Expected a total of '0' observers. Actual: {len(logic.observedPrimaryNodes)}."
        )
        assert len(logic._ImageLogDataLogic__observerHandlers) == 6, (
            f"Expected a total of '6' observers. Actual: {len(logic._ImageLogDataLogic__observerHandlers)}."
        )
        assert len(logic.observedInteractors) == 0, (
            f"Expected a total of '0' observers. Actual: {len(logic.observedInteractors)}."
        )
        assert len(logic.observedDisplayNodes) == 0, (
            f"Expected a total of '0' observers. Actual: {len(logic.observedDisplayNodes)}."
        )

        # Select the nodes for the first view
        logic.primaryNodeChanged(0, volumeNode)
        logic.segmentationNodeChanged(0, segmentationNode)
        logic.refreshViews()
        process_events()
        logic.refreshViews()
        wait(1)

        assert len(logic.observedPrimaryNodes) == 1, (
            f"Expected a total of '1' observers. Actual: {len(logic.observedPrimaryNodes)}."
        )
        assert len(logic._ImageLogDataLogic__observerHandlers) == 6, (
            f"Expected a total of '6' observers. Actual: {len(logic._ImageLogDataLogic__observerHandlers)}."
        )
        assert len(logic.observedInteractors) == 2, (
            f"Expected a total of '2' observers. Actual: {len(logic.observedInteractors)}."
        )
        assert len(logic.observedDisplayNodes) == 1, (
            f"Expected a total of '1' observers. Actual: {len(logic.observedDisplayNodes)}."
        )

        # Populate the second view
        logic.primaryNodeChanged(1, volumeNode)
        logic.refreshViews()
        process_events()
        logic.refreshViews()
        wait(1)

        assert len(logic.observedPrimaryNodes) == 2, (
            f"Expected a total of '2' observers. Actual: {len(logic.observedPrimaryNodes)}."
        )
        assert len(logic._ImageLogDataLogic__observerHandlers) == 6, (
            f"Expected a total of '6' observers. Actual: {len(logic._ImageLogDataLogic__observerHandlers)}."
        )
        assert len(logic.observedInteractors) == 4, (
            f"Expected a total of '4' observers. Actual: {len(logic.observedInteractors)}."
        )
        assert len(logic.observedDisplayNodes) == 2, (
            f"Expected a total of '2' observers. Actual: {len(logic.observedDisplayNodes)}."
        )

        # Remove nodes from the views controller widget
        logic.segmentationNodeChanged(0, None)
        logic.primaryNodeChanged(0, None)
        logic.primaryNodeChanged(1, None)
        logic.refreshViews()
        process_events()
        logic.refreshViews()
        wait(1)

        assert len(logic.observedPrimaryNodes) == 0, (
            f"Expected a total of '0' observers. Actual: {len(logic.observedPrimaryNodes)}."
        )
        assert len(logic._ImageLogDataLogic__observerHandlers) == 6, (
            f"Expected a total of '6' observers. Actual: {len(logic._ImageLogDataLogic__observerHandlers)}."
        )
        assert len(logic.observedInteractors) == 0, (
            f"Expected a total of '0' observers. Actual: {len(logic.observedInteractors)}."
        )
        assert len(logic.observedDisplayNodes) == 0, (
            f"Expected a total of '0' observers. Actual: {len(logic.observedDisplayNodes)}."
        )

    def test_info_and_attributes_tabs(self):
        volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        slicer.util.updateVolumeFromArray(volume, np.zeros((10, 10, 10)))

        with Metadata(volume) as meta:
            meta["ImageLogInfoTest"] = "Passed"

        self.__selectNodeInSubjectHierarchyTreeView(volume)

        # Check if tabs are visible
        self.assertTrue(self._module_widget.tabWidget.visible)

        # Check Info tab (Index 0)
        self.assertEqual(self._module_widget.tabWidget.tabText(0), "Info")
        self.assertTrue(self._module_widget.trackImageWidget.visible)

        # Check Attributes tab (Index 1)
        self.assertEqual(self._module_widget.tabWidget.tabText(1), "Attributes")
        attributes_text = self._module_widget.attributesWidget.textEdit.toPlainText()
        self.assertIn("ImageLogInfoTest", attributes_text)
        self.assertIn("Passed", attributes_text)

    def test_view_with_nmr(self, timeout_ms=15000):
        load_project(NMR_PROJECT_FILE)

        # Get node
        node = tryGetNode("in_depth_data")
        assert node is not None
        # Add view and select the node
        viewRefreshed = [False]

        def onViewsRefreshed():
            viewRefreshed[0] = True

        widget = self._module_widget
        try:
            _addNodeToView(widget=widget, node=node)
            widget.logic.viewsRefreshed.connect(onViewsRefreshed)

            waitCondition(lambda: viewRefreshed[0], timeoutSec=15)
            assert len(widget.logic.imageLogViewList) == 1, f"Expected 1 view, got {len(widget.logic.imageLogViewList)}"
            assert widget.logic.getViewPrimaryNode(identifier=0) == node, (
                f"Expected {node.GetID()}, got {widget.logic.getViewPrimaryNode(identifier=0).GetID()}"
            )
        finally:
            widget.logic.viewsRefreshed.disconnect(onViewsRefreshed)
