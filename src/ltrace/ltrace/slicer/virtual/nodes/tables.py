"""Table backend: a virtual table node holds the first rows of a delimited file."""

from typing import Dict

from ..sources.base import CLASS_TABLE, DEFAULT_SAMPLE_ROWS, SourceInfo
from .base import VirtualNodeBackend


class TableBackend(VirtualNodeBackend):
    NODE_CLASS = CLASS_TABLE

    @classmethod
    def fill(cls, node, source, info: SourceInfo, rows: int = DEFAULT_SAMPLE_ROWS, offset: int = 0, **options) -> Dict:
        """Write ``rows`` rows into ``node``. ``rows=None`` means every row: that is how ``load_full``
        materializes the whole table, while the default keeps a virtual node cheap."""
        from ltrace.slicer.data_utils import dataFrameToTableNode

        frame = source.read_rows(limit=rows, offset=offset)
        dataFrameToTableNode(frame, tableNode=node, replace=True)

        return {"rows": int(len(frame)), "columns": tuple(str(column) for column in frame.columns)}
