from ltrace.slicer.ui import intParam
from ltrace.slicer.helpers import getSourceVolume
import qt
import slicer
from ltrace.workflow.workstep import Workstep, WorkstepWidget
from SegmentInspector import IslandsSettingsWidget, SegmentInspectorLogic


class InspectorIslands(Workstep):
    NAME = "Segmentation: Islands from Segment Inspector"

    INPUT_TYPES = (slicer.vtkMRMLSegmentationNode, slicer.vtkMRMLLabelMapVolumeNode)
    OUTPUT_TYPE = slicer.vtkMRMLLabelMapVolumeNode

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.params = {
            "method": IslandsSettingsWidget.METHOD,
            "size_min_threshold": 100,
            "direction": None,
        }

    def run(self, segmentation_nodes):
        queue = []
        logic = SegmentInspectorLogic(results_queue=queue)

        def run_islands(node):
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
            run_islands(segmentation_node)
            result = queue.pop(0)

            if not result:
                continue
            node = slicer.mrmlScene.GetNodeByID(result.outputVolume)
            if node:
                yield node

    def widget(self):
        return InspectorIslandsWidget(self)


class InspectorIslandsWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)
        self.islands_widget = IslandsSettingsWidget()
        self.layout().addWidget(self.islands_widget)

        self.formLayout = qt.QFormLayout()
        self.formLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.layout().addLayout(self.formLayout)

    def save(self):
        params = self.islands_widget.toJson()
        params["direction"] = params["direction"].GetID() if params["direction"] else None
        self.workstep.params = params

    def load(self):
        params = self.workstep.params.copy()
        params["direction"] = slicer.mrmlScene.GetNodeByID(params["direction"]) if params["direction"] else None
        self.islands_widget.fromJson(params)
