from unittest.mock import patch
import slicer
import ctk
import qt

import numpy as np

from commons.slicer.tests.utils import wait
from commons.slicer.widgets import SingleShotInputWidget
from commons.slicer_utils import LTracePluginTest
from commons.slicer.node_attributes import NodeEnvironment, TableDataOrientation, TableDataTypeAttribute, TableType
from commons.constants import SIDE_BY_SIDE_IMAGE_LAYOUT_ID


class FindSlicerWidgetsTest(LTracePluginTest):
    """Test suite to assert slicer default widgets existence."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.__created_widget_list = []

    def tear_down(self) -> None:
        """Tear down method for test suite.
        Close and delete used widgets objects.
        """
        for widget in self.__created_widget_list:
            widget.close()
            del widget

    def create_widget_representation(
        self, module: slicer.qSlicerScriptedLoadableModule
    ) -> slicer.qSlicerScriptedLoadableModuleWidget:
        """Helper method to create and store modules' new widgets.

        Args:
            module (slicer.qSlicerScriptedLoadableModule): the module reference.

        Returns:
            slicer.qSlicerScriptedLoadableModuleWidget: the widget's module object.
        """
        widget = module.createNewWidgetRepresentation()
        self.__created_widget_list.append(widget)
        return widget

    def test_helpers_widgets(self) -> None:
        r"""From src\ltrace\ltrace\slicer\helpers.py"""
        mainWindow = slicer.modules.AppContextInstance.mainWindow
        modulePanel = mainWindow.findChild(slicer.qSlicerModulePanel, "ModulePanel")
        assert modulePanel.findChild(ctk.ctkCollapsibleButton, "HelpCollapsibleButton")

    def test_side_by_side_image_layout_widgets(self) -> None:
        r"""From src\ltrace\ltrace\slicer\side_by_side_image_layout.py:"""
        layoutManager = slicer.app.layoutManager()
        layoutManager.setLayout(SIDE_BY_SIDE_IMAGE_LAYOUT_ID)

        for i in (1, 2):
            sliceWidget = slicer.app.layoutManager().sliceWidget(f"SideBySideSlice{i}")
            for widgetName in (
                "SegmentationIconLabel",
                "SegmentationVisibilityButton",
                "SegmentationOpacitySlider",
                "SegmentationOutlineButton",
                "SegmentSelectorWidget",
                "qMRMLSliceControllerWidget",
                "MoreButton",
            ):
                assert sliceWidget.findChild(qt.QWidget, widgetName)

            slicerControllerWidget = sliceWidget.findChild(qt.QWidget, "qMRMLSliceControllerWidget")
            assert slicerControllerWidget.findChild(SingleShotInputWidget, "CustomSegmentSelector")
            assert slicerControllerWidget.findChild(SingleShotInputWidget, "PaddingWidget")

    def test_global_progress_bar_widgets(self) -> None:
        r"""From src\ltrace\ltrace\slicer\widget\global_progress_bar.py"""
        progressBar = slicer.qSlicerCLIProgressBar()
        assert progressBar.findChild(ctk.ctkExpandButton, "DetailsTextExpandButton")
        assert slicer.modules.AppContextInstance.mainWindow.moduleSelector().findChildren(qt.QToolButton)[
            -2
        ]  # This one doesn't have an object name
        assert slicer.modules.AppContextInstance.mainWindow.findChild(
            slicer.qSlicerModuleSelectorToolBar, "ModuleSelectorToolBar"
        )

    def test_slicer_volumes_widgets(self) -> None:
        r"""From src\ltrace\ltrace\slicer\widget\histogram_popup.py,
        src\ltrace\ltrace\slicer\widget\histogram_frame.py
        """
        volumesWidget = self.create_widget_representation(slicer.modules.volumes)
        volumesWidget.show()

        assert volumesWidget.findChild(slicer.qMRMLSubjectHierarchyTreeView, "ActiveVolumeNodeSelector")

        volumeDisplayWidget = volumesWidget.findChild(
            slicer.qSlicerScalarVolumeDisplayWidget, "qSlicerScalarVolumeDisplayWidget"
        )
        assert volumeDisplayWidget
        windowLevelWidget = volumeDisplayWidget.findChild(slicer.qMRMLWindowLevelWidget, "MRMLWindowLevelWidget")
        assert windowLevelWidget
        assert windowLevelWidget.findChild(ctk.ctkDoubleSpinBox, "MinSpinBox").findChild(qt.QDoubleSpinBox)
        assert windowLevelWidget.findChild(ctk.ctkDoubleSpinBox, "MaxSpinBox").findChild(qt.QDoubleSpinBox)
        assert windowLevelWidget.findChild(ctk.ctkDoubleSpinBox, "WindowSpinBox").findChild(qt.QDoubleSpinBox)
        assert windowLevelWidget.findChild(ctk.ctkDoubleSpinBox, "LevelSpinBox").findChild(qt.QDoubleSpinBox)

        window_level_combo_box = windowLevelWidget.findChild(qt.QComboBox, "AutoManualComboBox")
        assert window_level_combo_box

        thresholdWidget = volumeDisplayWidget.findChild(slicer.qMRMLVolumeThresholdWidget, "MRMLVolumeThresholdWidget")
        assert thresholdWidget
        autoManualComboBox = thresholdWidget.findChild(qt.QComboBox, "AutoManualComboBox")
        assert autoManualComboBox
        assert thresholdWidget.findChild(ctk.ctkRangeWidget, "VolumeThresholdRangeWidget")

    def test_slicer_segment_editor_widgets(self) -> None:
        """From slicer.qMRMLSegmentEditorWidget"""
        editorWidget = slicer.qMRMLSegmentEditorWidget()
        self.__created_widget_list.append(editorWidget)
        editorWidget.show()
        assert editorWidget.findChild(slicer.qMRMLNodeComboBox, "SegmentationNodeComboBox")
        assert editorWidget.findChild(slicer.qMRMLNodeComboBox, "SourceVolumeNodeComboBox")
        assert editorWidget.findChild(qt.QPushButton, "AddSegmentButton")
        assert editorWidget.findChild(qt.QPushButton, "RemoveSegmentButton")
        assert editorWidget.findChild(slicer.qMRMLSegmentationShow3DButton, "Show3DButton")
        assert editorWidget.findChild(qt.QToolButton, "SwitchToSegmentationsButton")
        assert editorWidget.findChild(ctk.ctkExpandableWidget, "SegmentsTableResizableFrame")

    def test_customized_data_widgets(self) -> None:
        r"""From src\modules\CustomizedData\CustomizedData.py"""
        dataWidget = self.create_widget_representation(slicer.modules.customizeddata)
        dataWidget.show()
        subjectHierarchyTreeView = dataWidget.findChild(qt.QObject, "SubjectHierarchyTreeView")
        assert subjectHierarchyTreeView
        assert subjectHierarchyTreeView.findChild(qt.QMenu, "nodeMenuTreeView")

    def test_customized_data_volume_widgets(self) -> None:
        r"""From src\modules\CustomizedData\CustomizedDataLib\ScalarVolume.py,
        src\modules\CustomizedData\CustomizedDataLib\VectorVolume.py
        """
        volumesWidget = self.create_widget_representation(slicer.modules.volumes)
        volumesWidget.show()

        volumeDisplayWidget = volumesWidget.findChild(
            slicer.qSlicerScalarVolumeDisplayWidget, "qSlicerScalarVolumeDisplayWidget"
        )
        assert volumeDisplayWidget
        assert volumesWidget.findChild(slicer.qMRMLSubjectHierarchyTreeView, "ActiveVolumeNodeSelector")
        assert volumesWidget.findChild(qt.QCheckBox, "InterpolateCheckbox")
        assert volumesWidget.findChild(slicer.qMRMLColorTableComboBox, "ColorTableComboBox")
        assert volumesWidget.findChild(slicer.qMRMLWindowLevelWidget, "MRMLWindowLevelWidget")
        thresholdWidget = volumesWidget.findChild(slicer.qMRMLVolumeThresholdWidget, "MRMLVolumeThresholdWidget")
        assert thresholdWidget
        assert thresholdWidget.findChild(qt.QComboBox, "AutoManualComboBox")
        assert thresholdWidget.findChild(ctk.ctkRangeWidget, "VolumeThresholdRangeWidget")

    def test_customized_segment_editor_widgets(self) -> None:
        r"""From src\modules\CustomizedSegmentEditor\CustomizedSegmentEditor.py"""
        import qSlicerSegmentationsModuleWidgetsPythonQt

        editor = qSlicerSegmentationsModuleWidgetsPythonQt.qMRMLSegmentEditorWidget()
        assert editor.findChild(qt.QToolButton, "SliceRotateWarningButton")
        assert editor.findChild(qt.QPushButton, "AddSegmentButton")
        assert editor.findChild(qt.QLabel, "SourceVolumeNodeLabel")
        assert editor.findChild(qt.QLabel, "SegmentationNodeLabel")
        assert editor.findChild(slicer.qMRMLNodeComboBox, "SourceVolumeNodeComboBox")
        assert editor.findChild(slicer.qMRMLNodeComboBox, "SegmentationNodeComboBox")

    def test_customized_tables_widgets(self) -> None:
        r"""From src\modules\CustomizedTables\CustomizedTables.py"""
        tablesWidget = self.create_widget_representation(slicer.modules.customizedtables)
        tablesWidget.show()
        displayEditCollapsibleWidget = tablesWidget.findChild(ctk.ctkCollapsibleButton, "DisplayEditCollapsibleWidget")
        assert displayEditCollapsibleWidget
        assert displayEditCollapsibleWidget.children()[0]
        assert displayEditCollapsibleWidget.children()[3].layout()
        assert tablesWidget.findChild(slicer.qMRMLNodeComboBox, "TableNodeSelector")
        assert tablesWidget.findChild(slicer.qMRMLTableView, "TableView")
        assert tablesWidget.findChild(slicer.qMRMLNodeComboBox, "TableNodeSelector")

        columnPropertiesCollapsibleButton = tablesWidget.findChild(
            ctk.ctkCollapsibleButton, "NewColumnPropertiesCollapsibleButton"
        )
        assert columnPropertiesCollapsibleButton
        tableColumnPropertiesWidget = columnPropertiesCollapsibleButton.findChild(
            slicer.qSlicerTableColumnPropertiesWidget
        )
        assert tableColumnPropertiesWidget
        assert tableColumnPropertiesWidget.findChild(qt.QLineEdit, "NullValueLineEdit")

        newPropertiesDataTypeBox = columnPropertiesCollapsibleButton.findChild(qt.QComboBox, "DataTypeComboBox")
        assert newPropertiesDataTypeBox

    def test_image_log_data_widgets(self) -> None:
        r"""From src\modules\ImageLogData\ImageLogData.py"""
        with patch("ImageLogData.getCurrentEnvironment", lambda: NodeEnvironment.IMAGE_LOG):
            imageLogDataWidget = slicer.util.getModuleWidget("ImageLogData")

            centralWidgetLayoutFrame = slicer.modules.AppContextInstance.mainWindow.findChild(
                qt.QFrame, "CentralWidgetLayoutFrame"
            )
            logic = imageLogDataWidget.logic

            # resetting the views
            logic.imageLogViewList = []
            logic.refreshViews()
            wait(0.2)

            # testing image nodes
            logic.addView()
            scalarVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
            logic.primaryNodeChanged(0, scalarVolumeNode)
            segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
            logic.segmentationNodeChanged(0, segmentationNode)

            logic.refreshViews()
            wait(0.2)

            assert centralWidgetLayoutFrame
            assert centralWidgetLayoutFrame.findChild(qt.QLabel, "viewLabel0")
            assert centralWidgetLayoutFrame.findChild(qt.QToolButton, "settingsToolButton0")
            assert centralWidgetLayoutFrame.findChild(ctk.ctkPopupWidget, "settingsPopup0")
            assert centralWidgetLayoutFrame.findChild(qt.QComboBox, "primaryNodeComboBox0")
            assert centralWidgetLayoutFrame.findChild(qt.QPushButton, "showHidePrimaryNodeButton0")
            assert centralWidgetLayoutFrame.findChild(slicer.qMRMLNodeComboBox, "segmentationNodeComboBox0")
            assert centralWidgetLayoutFrame.findChild(qt.QToolButton, "showHideSegmentationNodeButton0")
            assert centralWidgetLayoutFrame.findChild(ctk.ctkSliderWidget, "segmentationOpacitySlider0")
            assert centralWidgetLayoutFrame.findChild(qt.QLineEdit, "proportionsNodeLineEdit0")
            assert centralWidgetLayoutFrame.findChild(qt.QPushButton, "showHideProportionsNodeButton0")

            # resetting the views
            logic.imageLogViewList = []
            logic.refreshViews()
            wait(0.2)

            # testing table nodes
            logic.addView()
            tableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
            slicer.util.updateTableFromArray(tableNode, np.zeros((2, 2)))
            logic.primaryNodeChanged(0, tableNode)
            assert not logic.imageLogViewList[0].viewData.primaryTableHistogram

            logic.refreshViews()
            wait(0.6)
            centralWidgetLayoutFrame = slicer.modules.AppContextInstance.mainWindow.findChild(
                qt.QFrame, "CentralWidgetLayoutFrame"
            )

            assert centralWidgetLayoutFrame
            assert centralWidgetLayoutFrame.findChild(qt.QLabel, "viewLabel0")
            assert centralWidgetLayoutFrame.findChild(qt.QToolButton, "settingsToolButton0")
            assert centralWidgetLayoutFrame.findChild(ctk.ctkPopupWidget, "settingsPopup0")
            assert centralWidgetLayoutFrame.findChild(qt.QComboBox, "primaryNodeComboBox0")
            assert centralWidgetLayoutFrame.findChild(qt.QComboBox, "secondaryTableNodeComboBox0")
            assert centralWidgetLayoutFrame.findChild(qt.QComboBox, "primaryTableNodeColumnComboBox0")
            assert centralWidgetLayoutFrame.findChild(qt.QComboBox, "primaryTableNodePlotTypeComboBox0")
            assert centralWidgetLayoutFrame.findChild(qt.QWidget, "primaryTableNodePlotColorPicker0")
            assert not centralWidgetLayoutFrame.findChild(qt.QWidget, "primaryTableNodePlotColorPicker0").histogramMode
            assert centralWidgetLayoutFrame.findChild(qt.QComboBox, "secondaryTableNodeColumnComboBox0")
            assert centralWidgetLayoutFrame.findChild(qt.QComboBox, "secondaryTableNodePlotTypeComboBox0")
            assert centralWidgetLayoutFrame.findChild(qt.QWidget, "secondaryTableNodePlotColorPicker0")

            # resetting the views
            logic.imageLogViewList = []
            logic.refreshViews()
            wait(0.2)
            centralWidgetLayoutFrame = slicer.modules.AppContextInstance.mainWindow.findChild(
                qt.QFrame, "CentralWidgetLayoutFrame"
            )

            # testing histogram nodes
            logic.addView()
            histogramNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")
            histogramNode.SetAttribute(TableType.name(), TableType.HISTOGRAM_IN_DEPTH.value)
            histogramNode.SetAttribute(TableDataTypeAttribute.name(), TableDataTypeAttribute.IMAGE_2D.value)
            histogramNode.SetAttribute(TableDataOrientation.name(), TableDataOrientation.ROW.value)
            slicer.util.updateTableFromArray(histogramNode, np.random.rand(4, 4))
            logic.primaryNodeChanged(0, histogramNode)
            assert logic.imageLogViewList[0].viewData.primaryTableHistogram

            logic.refreshViews()
            wait(0.2)

            assert centralWidgetLayoutFrame
            assert centralWidgetLayoutFrame.findChild(qt.QToolButton, "settingsToolButton0")
            assert centralWidgetLayoutFrame.findChild(ctk.ctkPopupWidget, "settingsPopup0")
            assert centralWidgetLayoutFrame.findChild(qt.QComboBox, "primaryNodeComboBox0")
            assert centralWidgetLayoutFrame.findChild(qt.QComboBox, "secondaryTableNodeComboBox0")
            assert centralWidgetLayoutFrame.findChild(qt.QComboBox, "primaryTableNodeColumnComboBox0")
            assert centralWidgetLayoutFrame.findChild(qt.QComboBox, "primaryTableNodePlotTypeComboBox0")
            assert not centralWidgetLayoutFrame.findChild(qt.QComboBox, "primaryTableNodePlotTypeComboBox0").isEnabled()
            assert centralWidgetLayoutFrame.findChild(qt.QWidget, "primaryTableNodePlotColorPicker0")
            assert centralWidgetLayoutFrame.findChild(qt.QWidget, "primaryTableNodePlotColorPicker0").histogramMode
            assert centralWidgetLayoutFrame.findChild(qt.QComboBox, "secondaryTableNodeColumnComboBox0")
            assert centralWidgetLayoutFrame.findChild(qt.QComboBox, "secondaryTableNodePlotTypeComboBox0")
            assert centralWidgetLayoutFrame.findChild(qt.QWidget, "secondaryTableNodePlotColorPicker0")

    def test_track_image_widgets(self) -> None:
        """From src\modules\ImageLogData\ImageLogDataLib\treeview\TrackImage.py"""
        scalarVolumeDisplayWidget = slicer.qSlicerScalarVolumeDisplayWidget()
        assert scalarVolumeDisplayWidget.findChild(qt.QCheckBox, "InterpolateCheckbox")
        assert scalarVolumeDisplayWidget.findChild(slicer.qMRMLColorTableComboBox, "ColorTableComboBox")
        windowLevelWidget = scalarVolumeDisplayWidget.findChild(slicer.qMRMLWindowLevelWidget, "MRMLWindowLevelWidget")
        assert windowLevelWidget
        assert windowLevelWidget.findChild(qt.QComboBox, "AutoManualComboBox")
        assert windowLevelWidget.findChild(qt.QComboBox, "AutoManualComboBox")
        thresholdWidget = scalarVolumeDisplayWidget.findChild(
            slicer.qMRMLVolumeThresholdWidget, "MRMLVolumeThresholdWidget"
        )
        assert thresholdWidget
        assert thresholdWidget.findChild(qt.QComboBox, "AutoManualComboBox")
        assert thresholdWidget.findChild(ctk.ctkRangeWidget, "VolumeThresholdRangeWidget")

    def test_image_log_segmenter_widgets(self) -> None:
        r"""From src\modules\ImageLogSegmentEditor\ImageLogSegmentEditor.py"""
        customizedSegmentEditorWidget = self.create_widget_representation(slicer.modules.customizedsegmenteditor)
        customizedSegmentEditorWidget.show()
        segmentEditorWidget = customizedSegmentEditorWidget.self().editor
        segmentEditorWidget.findChild(ctk.ctkMenuButton, "Show3DButton").setVisible(False)
        segmentEditorWidget.findChild(slicer.qMRMLNodeComboBox, "SegmentationNodeComboBox")

    def test_slicer_main_window_widgets(self) -> None:
        """General widgets from the slicer's main window."""
        # src\modules\InstanceSegmenterEditor\InstanceSegmenterEditor.py:
        assert slicer.util.findChild(slicer.modules.AppContextInstance.mainWindow, "MouseModeToolBar")

        # src\modules\ModuleToolBarCustomizer\ModuleToolBarCustomizer.py:
        assert slicer.util.findChild(slicer.modules.AppContextInstance.mainWindow, "ModuleToolBar")

    def test_slicer_transforms_widgets(self) -> None:
        """From slicer.modules.transforms"""
        transformWidget = self.create_widget_representation(slicer.modules.transforms)
        transformWidget.show()
        assert transformWidget.findChild(qt.QObject, "TransformNodeSelector")

    def test_micro_ct_transforms_widgets(self) -> None:
        r"""From src\modules\MicroCTTransforms\MicroCTTransforms.py"""
        microCtTransformWidget = slicer.modules.microcttransforms.createNewWidgetRepresentation()

        minMaxWidget = microCtTransformWidget.findChild(qt.QObject, "MinMaxWidget")
        assert minMaxWidget.findChild(qt.QObject, "MinValueSpinBox")
        assert minMaxWidget.findChild(qt.QObject, "MaxValueSpinBox")
        assert microCtTransformWidget.findChild(qt.QObject, "RotationSliders")
        assert microCtTransformWidget.findChild(ctk.ctkCollapsibleButton, "DisplayEditCollapsibleWidget")

        transformWidget = slicer.modules.transforms.createNewWidgetRepresentation()
        assert transformWidget.findChild(qt.QObject, "TransformableTreeView")
        assert transformWidget.findChild(qt.QObject, "TransformToolButton")
        assert transformWidget.findChild(qt.QObject, "UntransformToolButton")
        assert transformWidget.findChild(qt.QObject, "TransformedTreeView")

        rotationSliders = microCtTransformWidget.findChild(qt.QObject, "RotationSliders")
        sliderNames = ["LRSlider", "PASlider", "ISSlider"]
        for i in range(len(["LRSlider", "PASlider", "ISSlider"])):
            slider = rotationSliders.findChild(slicer.qMRMLLinearTransformSlider, sliderNames[i])
            assert slider.findChild(ctk.ctkDoubleSlider, "Slider")
            assert slider.findChild(ctk.ctkDoubleSpinBox, "SpinBox")

        microCtTransformWidget.close()
        del microCtTransformWidget

    def test_multicore_transforms_widgets(self) -> None:
        r"""From src\modules\MulticoreTransforms\MulticoreTransforms.py:"""
        multiCoreTransformsWidget = self.create_widget_representation(slicer.modules.multicoretransforms)
        multiCoreTransformsWidget.show()

        assert multiCoreTransformsWidget.findChild(qt.QObject, "TransformableTreeView")
        assert multiCoreTransformsWidget.findChild(qt.QObject, "TransformToolButton")
        assert multiCoreTransformsWidget.findChild(qt.QObject, "UntransformToolButton")
        assert multiCoreTransformsWidget.findChild(qt.QObject, "TransformedTreeView")
        minMaxWidget = multiCoreTransformsWidget.findChild(qt.QObject, "MinMaxWidget")
        assert minMaxWidget.findChild(qt.QObject, "MinValueSpinBox")
        assert minMaxWidget.findChild(qt.QObject, "MaxValueSpinBox")
        assert multiCoreTransformsWidget.findChild(qt.QObject, "Translation ISSlider")
        iSSLider = multiCoreTransformsWidget.findChild(qt.QObject, "Rotation ISSlider")
        assert iSSLider.children()[-1]

    def test_volume_calculator_widgets(self) -> None:
        r"""From src\modules\VolumeCalculator\VolumeCalculator.py"""
        volumeCalculatorWidget = self.create_widget_representation(slicer.modules.volumecalculator)
        volumeCalculatorWidget.show()
        assert volumeCalculatorWidget.findChild(qt.QObject, "FilterLabel")
        assert volumeCalculatorWidget.findChild(qt.QObject, "FilterLineEdit")
        assert volumeCalculatorWidget.findChild(qt.QObject, "SubjectHierarchyTreeView")

    def test_slicer_data_widget(self) -> None:
        """From slicer.modules.data"""
        dataWidget = self.create_widget_representation(slicer.modules.data)
        dataWidget.show()
        qtTabwidgetStackedwidget = dataWidget.findChild(qt.QObject, "qt_tabwidget_stackedwidget")
        assert qtTabwidgetStackedwidget
        assert qtTabwidgetStackedwidget.findChild(qt.QObject, "SubjectHierarchyDisplayTransformsCheckBox")

    def test_welcome_slicer_widgets(self) -> None:
        r"""From src\modules\WelcomeGeoSlicer\WelcomeGeoSlicer.py"""
        mainWindow = slicer.modules.AppContextInstance.mainWindow
        assert mainWindow.findChild(qt.QObject, "dockWidgetContents")
        assert slicer.util.findChild(mainWindow, "DataProbeCollapsibleWidget")

    def test_customizer_widgets(self) -> None:
        r"""From tools\deploy\Customizer.py:"""
        mainWindow = slicer.modules.AppContextInstance.mainWindow
        assert mainWindow.findChild(ctk.ctkCollapsibleButton, "DataProbeCollapsibleWidget")
        assert mainWindow.findChild(qt.QWidget, "PanelDockWidget")

        assert mainWindow.findChild("QMenu", "FileMenu")
        assert mainWindow.findChild("QMenu", "HelpMenu")
        assert mainWindow.findChild(qt.QToolBar, "MainToolBar")
        assert mainWindow.findChild(qt.QToolBar, "DialogToolBar")

        volumeRenderingModule = self.create_widget_representation(slicer.modules.volumerendering)
        volumeRenderingModule.show()
        assert volumeRenderingModule.findChild(qt.QObject, "PresetComboBox").children()[2].children()[-1]
        assert volumeRenderingModule.findChild(qt.QObject, "DisplayCollapsibleButton").children()[0]
        assert volumeRenderingModule.findChild(qt.QObject, "VolumeNodeSelector")

        viewWidget = slicer.app.layoutManager().threeDWidget(0)
        assert viewWidget.findChild(qt.QMenu, "orientationMarkerMenu")

        statusBar = mainWindow.findChild(qt.QObject, "StatusBar")
        assert statusBar
        assert statusBar.findChild(qt.QToolButton)

        assert mainWindow.findChild(qt.QMenu, "ViewMenu").actions()[5]
        assert mainWindow.findChild(qt.QToolBar, "DialogToolBar").actions()[0]
        assert mainWindow.findChild("QToolBar", "ViewToolBar")
        assert mainWindow.findChild("QToolBar", "MainToolBar")
        assert mainWindow.findChild("QToolBar", "CaptureToolBar")

        module_panel = mainWindow.findChild(slicer.qSlicerModulePanel, "ModulePanel")
        assert module_panel
        assert module_panel.findChild(ctk.ctkFittedTextBrowser, "HelpLabel")
