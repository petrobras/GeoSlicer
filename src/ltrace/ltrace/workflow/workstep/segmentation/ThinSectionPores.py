import os
import slicer
from ltrace.workflow.workstep import Workstep, WorkstepWidget
from ltrace.assets_utils import get_model_by_name
from ltrace.slicer.tests.utils import wait_cli_to_finish
from Segmenter import MonaiModelsLogic
from types import SimpleNamespace


class ThinSectionPores(Workstep):
    NAME = "Segmentation: Thin Section Pores"

    INPUT_TYPES = (slicer.vtkMRMLVectorVolumeNode,)
    OUTPUT_TYPE = slicer.vtkMRMLSegmentationNode

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        return

    def run(self, nodes):
        inputModel = {"currentData": get_model_by_name("carb_pore")}

        for node in nodes:
            logic = MonaiModelsLogic(imageLogMode=False, onFinish=None)
            cliNode = logic.run(
                inputModelComboBox=SimpleNamespace(**inputModel),
                referenceNode=node,
                extraNodes=[],
                soiNode=None,
                outputPrefix=node.GetName() + "_{type}",
                deterministic=False,
            )

            wait_cli_to_finish(cliNode)

            yield slicer.util.getNode(node.GetName() + "_Segmentation")

    def widget(self):
        return ThinSectionPoresWidget(self)


class ThinSectionPoresWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)

    def save(self):
        return

    def load(self):
        return
