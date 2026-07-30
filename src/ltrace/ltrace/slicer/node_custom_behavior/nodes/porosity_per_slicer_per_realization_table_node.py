import slicer

from ltrace.slicer.node_attributes import TableType
from ltrace.slicer.node_custom_behavior.node_custom_behavior_base import (
    NodeCustomBehaviorBase,
    CustomBehaviorRequirements,
)
from ltrace.slicer.node_custom_behavior.defs import TriggerEvent


class PorosityPerSlicePerRealizationTableNodeCustomBehavior(NodeCustomBehaviorBase):
    """Custom behavior for vtkMRMLTableNode with TableType.POROSITY_PER_REALIZATION.value attribute.
    This change rewrites the .tsv file with higher precision. Table storage nodes convert double and float data to scientific notation,
    causing the values to be rounded."""

    REQUIREMENTS = CustomBehaviorRequirements(
        nodeTypes=[slicer.vtkMRMLTableNode], attributes={TableType.name(): TableType.POROSITY_PER_REALIZATION.value}
    )

    def __init__(self, node: slicer.vtkMRMLNode, event: TriggerEvent) -> None:
        super().__init__(node=node, event=event)

    def _afterSave(self) -> None:
        storagePath = self._node.GetStorageNode().GetFileName()
        df = slicer.util.dataframeFromTable(self._node)
        df.to_csv(storagePath, sep="\t", index=False, float_format="%.17g")
