from ltrace.slicer.helpers import getSourceVolume
import qt
import slicer
from ltrace.workflow.workstep import Workstep, WorkstepWidget
from SegmentInspector import OSWatershedSettingsWidget, SegmentInspectorLogic


class InspectorWatershed(Workstep):
    NAME = "Segmentation: Over-segmented Watershed"

    INPUT_TYPES = (slicer.vtkMRMLSegmentationNode, slicer.vtkMRMLLabelMapVolumeNode)
    OUTPUT_TYPE = slicer.vtkMRMLLabelMapVolumeNode

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.params = {
            "method": OSWatershedSettingsWidget.METHOD,
            "sigma": 1.0,
            "d_min_filter": 5.0,
            "size_min_threshold": 0.0,
            "direction": None,
            "generate_throat_analysis": False,
        }
        self.delete_inputs = True

    def run(self, segmentation_nodes):
        queue = []
        logic = SegmentInspectorLogic(results_queue=queue)

        def run_watershed(node):
            def get_label_index(node):
                segmentation = node.GetSegmentation()

                for i in range(segmentation.GetNumberOfSegments()):
                    if segmentation.GetNthSegment(i).GetLabelValue() == 1:
                        return i
                raise ValueError("Could not find an appropriate segment to be used as input.")

            master_volume = getSourceVolume(node) if isinstance(node, slicer.vtkMRMLSegmentationNode) else node
            if master_volume is None:
                raise RuntimeError(f"No master volume found for segmentation node {node.GetName()}")

            logic.runSelectedMethod(
                node,
                segments=[get_label_index(node)],
                outputPrefix=node.GetName() + "_{type}",
                referenceNode=master_volume,
                soiNode=None,
                params=self.params,
                products=["all"],
                wait=True,
            )
            slicer.app.processEvents()

        if not segmentation_nodes:
            return

        for segmentation_node in segmentation_nodes:
            run_watershed(segmentation_node)
            result = queue.pop(0)

            if not result:
                continue
            node = slicer.mrmlScene.GetNodeByID(result.outputVolume)
            if node:
                self.discard_input(segmentation_node)
                yield node

    def widget(self):
        return InspectorWatershedWidget(self)


class InspectorWatershedWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)
        self.watershed_widget = OSWatershedSettingsWidget()
        self.layout().addWidget(self.watershed_widget)

        self.delete_inputs_checkbox = qt.QCheckBox("Remove input from project after watershed")
        self.delete_inputs_checkbox.setToolTip(
            "Remove input images from project as soon as they are no longer needed in order to reduce memory usage."
        )
        self.layout().addWidget(self.delete_inputs_checkbox)
        self.layout().addStretch(1)

    def save(self):
        params = self.watershed_widget.toJson()
        params["direction"] = params["direction"].GetID() if params["direction"] else None
        self.workstep.params = params
        self.workstep.delete_inputs = self.delete_inputs_checkbox.isChecked()

    def load(self):
        params = self.workstep.params.copy()
        params["direction"] = slicer.mrmlScene.GetNodeByID(params["direction"]) if params["direction"] else None
        self.watershed_widget.fromJson(params)
        self.delete_inputs_checkbox.setChecked(self.workstep.delete_inputs)
