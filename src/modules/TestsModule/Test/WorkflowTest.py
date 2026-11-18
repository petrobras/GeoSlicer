import slicer
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import wait, load_project
from pathlib import Path
import numpy as np
from commons.workflow.workstep.data import ThinSectionLoader, ExportLAS
from commons.workflow.workstep.segmentation import ThinSectionPores, InspectorWatershed, InspectorIslands
from commons.workflow import WorkflowWidget
import qt
import os
import lasio
import glob

RESOURCE_DIR = Path(__file__).parent / "Resources"
DATASET_PATH = RESOURCE_DIR / "ThinSections"
SEGMENTATIONS_PROJECT_PATH = DATASET_PATH / "PoreSegs" / "PoreSegs.mrml"


class WorkflowTest(LTracePluginTest):
    def _add_worksteps(self, widget, workstepNames):
        for workstepName in workstepNames:
            widget.findChild(qt.QPushButton, "addWorkstepButton").clicked()
            widget.addWorkstepDialog.findChild(qt.QComboBox, "workstepsComboBox").setCurrentText(workstepName)
            widget.addWorkstepDialog.findChild(qt.QPushButton, "addWorkstepOkButton").clicked()

    def _test_las_files_are_equal(self, las1_path, las2_path):
        def must_be_different(key, item):
            return key == "Well" and item.mnemonic == "DATE"

        las1 = lasio.read(las1_path)
        las2 = lasio.read(las2_path)

        assert las1.header.keys() == las2.header.keys()
        for key in las1.header.keys():
            las1_header = las1.header[key]
            las2_header = las2.header[key]

            assert type(las1_header) is type(las2_header)

            if isinstance(las1.header[key], list):
                assert len(las1_header) == len(las2_header)

                for las1_item, las2_item in zip(las1_header, las2_header):
                    assert type(las1_item) is type(las2_item)

                    assert las1_item.mnemonic == las2_item.mnemonic
                    assert las1_item.unit == las2_item.unit
                    assert las1_item.descr == las2_item.descr
                    # VALUE COMPARISON:
                    # - equals (==) will work for all types of values (including absent);
                    # - np.isclose() will handle floating values that are essentially equal but diverge by precision issues;
                    # - must_be_different() refers to Well.DATE, which will be different on every run
                    assert (
                        las1_item.value == las2_item.value
                        or must_be_different(key, las1_item)
                        or np.isclose(las1_item.value, las2_item.value)
                    )

                    if isinstance(las1_item, lasio.las_items.CurveItem):
                        # Results are slightly variable for watershed, so let's verify if each of them differ by less than 1% with the template
                        epsilon = 1e-10  # for handling zero division
                        curve1 = las1_item.data + epsilon
                        curve2 = las2_item.data + epsilon
                        ratio = curve1 / curve2
                        assert np.all((ratio > 0.99) & (ratio < 1.01))
            else:
                assert las1_header == las2_header

    def _test_zero_result_when_no_report(self, las_path):
        def isDataAllZeros(las, index):
            return all([curve.data[index] == 0 for curve in las.curves if curve.mnemonic != "DEPT"])

        las = lasio.read(las_path)

        for i, depth in enumerate(las["DEPT"]):
            labelmap = slicer.util.getNode(f"sample_{str(depth).replace('.', ',')}m_c1_Segmentation_LabelMap")
            assert labelmap is not None

            has_report = labelmap.GetAttribute("ResultReport") is not None

            assert has_report != isDataAllZeros(las, i)

    def _test_sorted_depths(self, las_path):
        las = lasio.read(las_path)
        assert np.all(np.diff(las["DEPT"]) >= 0)

    def _test_pore_statistics_workflow(
        self,
        inspectorWorkstep,
        byDirectory,
        waitMethodSingleShotTimer=False,
        sortFilePathsInversely=False,
        minimumIslandSize=100.0,
        templateFileName=None,
    ):
        workflowWidget = WorkflowWidget()

        self._add_worksteps(
            workflowWidget,
            [ThinSectionLoader.NAME],
        )
        if byDirectory:
            workflowWidget.currentWorkstepWidget.multiplePathsWidget.directoryListView.directoryList = [DATASET_PATH]
        else:
            imagePaths = glob.glob(os.path.join(DATASET_PATH, "*.jpg"))
            if not sortFilePathsInversely:
                workflowWidget.currentWorkstepWidget.multiplePathsWidget.directoryListView.directoryList = imagePaths
            else:
                workflowWidget.currentWorkstepWidget.multiplePathsWidget.directoryListView.directoryList = tuple(
                    sorted(imagePaths, reverse=True)
                )

        self._add_worksteps(
            workflowWidget,
            [ThinSectionPores.NAME, inspectorWorkstep.NAME],
        )
        if waitMethodSingleShotTimer:
            wait(1)
        methodWidget = workflowWidget.currentWorkstepWidget.layout().itemAt(0).widget()
        methodWidget.sizeFilterThreshold.value = minimumIslandSize

        result_las_path = os.path.join(DATASET_PATH, "result.las")
        template_las_path = os.path.join(
            DATASET_PATH,
            f"pore_seg_{methodWidget.METHOD}_template.las" if templateFileName is None else templateFileName,
        )

        self._add_worksteps(
            workflowWidget,
            [ExportLAS.NAME],
        )
        workflowWidget.currentWorkstepWidget.exportPathFileSelector.setCurrentPath(result_las_path)

        workflowWidget.run()

        try:
            assert os.path.exists(result_las_path)
            self._test_zero_result_when_no_report(result_las_path)
            self._test_sorted_depths(result_las_path)
            self._test_las_files_are_equal(result_las_path, template_las_path)
        except Exception as e:
            raise e
        finally:
            os.remove(result_las_path)

    def test_deep_pore_segmentation_workstep(self):
        def getArrayFromSegmentationNode(segmentationNode):
            dummyReferenceVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode")
            dummyReferenceVolume.CreateDefaultDisplayNodes()

            segmentID = segmentationNode.GetSegmentation().GetSegmentIDs()[0]
            return slicer.util.arrayFromSegmentBinaryLabelmap(segmentationNode, segmentID, dummyReferenceVolume)

        load_project(SEGMENTATIONS_PROJECT_PATH)
        workflowWidget = WorkflowWidget()

        self._add_worksteps(
            workflowWidget,
            [ThinSectionLoader.NAME],
        )
        imagePaths = glob.glob(os.path.join(DATASET_PATH, "*.jpg"))
        workflowWidget.currentWorkstepWidget.multiplePathsWidget.directoryListView.directoryList = imagePaths

        self._add_worksteps(
            workflowWidget,
            [ThinSectionPores.NAME],
        )

        workflowWidget.run()

        for imagePath in imagePaths:
            imageName = os.path.basename(imagePath)
            resultSegName = imageName.replace(".jpg", "_1_Segmentation")
            templateName = f"{resultSegName}_template".replace("_1_", "_")

            resultSegNode = slicer.util.getNode(resultSegName)
            templateNode = slicer.util.getNode(templateName)

            assert resultSegNode is not None
            assert templateNode is not None

            np.testing.assert_array_equal(
                getArrayFromSegmentationNode(resultSegNode), getArrayFromSegmentationNode(templateNode)
            )

    def test_inspector_islands_workstep(self):
        load_project(SEGMENTATIONS_PROJECT_PATH)
        workflowWidget = WorkflowWidget()

        self._add_worksteps(
            workflowWidget,
            [ThinSectionLoader.NAME],
        )
        imagePaths = glob.glob(os.path.join(DATASET_PATH, "*.jpg"))
        workflowWidget.currentWorkstepWidget.multiplePathsWidget.directoryListView.directoryList = imagePaths

        self._add_worksteps(
            workflowWidget,
            [ThinSectionPores.NAME, InspectorIslands.NAME],
        )

        workflowWidget.run()

        for imagePath in imagePaths:
            imageName = os.path.basename(imagePath)
            resultSegName = imageName.replace(".jpg", "_1_Segmentation_LabelMap")
            templateName = f"{resultSegName}_template".replace("_1_", "_")

            resultSegNode = slicer.util.getNode(resultSegName)
            templateNode = slicer.util.getNode(templateName)

            assert resultSegNode is not None
            assert templateNode is not None

            np.testing.assert_array_equal(
                slicer.util.arrayFromVolume(resultSegNode), slicer.util.arrayFromVolume(templateNode)
            )

    def test_export_las_workstep(self):
        self._test_pore_statistics_workflow(
            InspectorIslands,
            byDirectory=False,  # selecting data files instead of directory
            sortFilePathsInversely=True,  # forcing files not to be processed in depth order to test if the final .LAS gets sorted by depth either way
            minimumIslandSize=1000.0,  # to produce one result without any valid pore and, consequently, without any report (corresponding .LAS entry must be all-zeros)
            templateFileName="las_template.las",  # template sorted by depth and with one all-zeros entry
        )

    def test_pore_stats_with_watershed_by_directory(self):
        self._test_pore_statistics_workflow(InspectorWatershed, byDirectory=True, waitMethodSingleShotTimer=True)

    def test_pore_stats_with_islands_by_directory(self):
        self._test_pore_statistics_workflow(InspectorIslands, byDirectory=True)

    def test_pore_stats_with_watershed_by_file_list(self):
        self._test_pore_statistics_workflow(InspectorWatershed, byDirectory=False, waitMethodSingleShotTimer=True)

    def test_pore_stats_with_islands_by_file_list(self):
        self._test_pore_statistics_workflow(InspectorIslands, byDirectory=False)

    def test_inspector_watershed_get_positive_label(self):
        newLabelValue = 5
        load_project(SEGMENTATIONS_PROJECT_PATH)

        imagePath = glob.glob(os.path.join(DATASET_PATH, "*.jpg"))[0]
        imageName = os.path.basename(imagePath)
        resultSegName = imageName.replace(".jpg", "_Segmentation_template")
        resultSegNode = slicer.util.getNode(resultSegName)

        assert resultSegNode is not None
        assert resultSegNode.GetSegmentation().GetNthSegment(0).GetLabelValue() == 1

        workstep = InspectorWatershed()
        workstep.delete_inputs = False
        assert next(workstep.run([resultSegNode])) is not None

        resultSegNode.GetSegmentation().GetNthSegment(0).SetLabelValue(newLabelValue)
        try:
            next(workstep.run([resultSegNode]))
        except Exception as e:
            assert isinstance(e, ValueError)
            assert str(e) == "Could not find an appropriate segment to be used as input."

        resultSegNode.GetSegmentation().AddEmptySegment()
        assert resultSegNode.GetSegmentation().GetNthSegment(0).GetLabelValue() == newLabelValue
        assert resultSegNode.GetSegmentation().GetNthSegment(1).GetLabelValue() == 1

        assert next(workstep.run([resultSegNode])) is not None
