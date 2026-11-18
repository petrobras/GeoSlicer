# ruff: noqa: F401 - imports register the test classes with Slicer
import qt
import slicer

from commons.slicer_utils import LTracePlugin, LTracePluginWidget


try:
    from Test.NodeCustomBehaviorTest import NodeCustomBehaviorTest, NodeCustomBehaviorFactoryTest
    from Test.FindSlicerWidgetsTest import FindSlicerWidgetsTest
    from Test.HelpersTest import HelpersTest
    from Test.WidgetsTest import WidgetsTest
    from Test.NodeObserverTest import NodeObserverTest
    from Test.DirectoryNodeTest import DirectoryNodeTest
    from Test.ProjectManagerTest import ProjectManagerTest
    from Test.CenterSubjectHierarchyPluginTest import CenterSubjectHierarchyPluginTest
    from Test.TrackingTest import TrackingTest
    from Test.CorrelatedLabelMapVolumeTest import CorrelatedLabelMapVolumeTest
    from Test.LTracePluginTestTest import LTracePluginTestTest
    from Test.SlicerUtilsTest import SlicerUtilsTest

    # from Test.WorkflowTest import WorkflowTest
    from Test.SlicerAppTest import SlicerAppTest
    from Test.CustomMainWindowEventFilterTest import CustomMainWindowEventFilterTest
    from Test.MainWindowTest import MainWindowTest
    from Test.ScreenshotTest import ScreenshotTest
    from Test.SideBySideLayoutViewTest import SideBySideLayoutViewTest
    from Test.BugReportTest import BugReportTest
    from Test.DataLoaderSelectorDialogTest import DataLoaderSelectorDialogTest
    from Test.OnboardViewTest import OnboardViewTest
    from Test.SlicerRCTest import SlicerRCTest
    from Test.SegmentListWidgetTest import SegmentListWidgetTest
    from Test.HelpButtonTest import HelpButtonTest
    from Test.Show3DSegmentationButtonTest import Show3DSegmentationButtonTest
    from Test.CliQueueTest import CliQueueTest
    from Test.ProgressBarProcTest import ProgressBarProcTest
    from Test.GraphDataTest import GraphDataTest
    from Test.NodeGraphDataTest import NodeGraphDataTest
    from Test.ThroatAnalysisTest import ThroatAnalysisTest
    from Test.LTraceModelTestTest import LTraceModelTestTest
except ImportError:
    pass


#
# TestsModule
#
class TestsModule(LTracePlugin):
    SETTING_KEY = "Tests Module"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "LTrace Tests Module"
        self.parent.categories = ["Tests"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.hidden = True
        self.parent.helpText = """
This module implements tests for code that do not belong to other modules.
"""
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = """
"""


#
# TestsModuleWidget
#
class TestsModuleWidget(LTracePluginWidget):
    """Uses LTracePluginWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/LTracePlugin.py
    """

    def setup(self):
        LTracePluginWidget.setup(self)
        button = qt.QPushButton("Run tests")
        button.toolTip = "Open test GUI"
        button.clicked.connect(lambda: slicer.selfTests["TestsModule"]())
        button.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Preferred)
        button.setStyleSheet(
            """
            QPushButton {font-size: 12px;
                         font-weight: bold;
                         padding: 10px;
                         margin: 4px}
            """
        )
        self.layout.addWidget(button)
