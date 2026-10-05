"""Table sources: delimited text files read a few rows at a time.

Delimiter sniffing is deliberate rather than delegated to ``csv.Sniffer``: LBPM writes whitespace-separated
logs (``timelog.csv``, ``subphase.csv``) whose ``.csv`` extension lies, and the sniffer mis-reads those.
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

from .base import CLASS_TABLE, KIND_TABLE, SourceError, SourceInfo, VirtualSource

TABLE_EXTENSIONS = (".csv", ".tsv", ".txt", ".dat")

CANDIDATE_SEPARATORS = (",", ";", "\t", r"\s+")

ROW_COUNT_SIZE_LIMIT = 64 * 1024**2
"""Above this file size the row count is left unknown: counting means reading the whole file, which is
exactly what a virtual node exists to avoid."""


def sniff_separator(path: Path, sample_lines: int = 5) -> str:
    """Separator that splits the header and the first data lines into the same, plural, field count."""
    lines = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
            if len(lines) >= sample_lines:
                break

    if not lines:
        raise SourceError(f"{path} is empty")

    import re

    best = (1, ",")
    for separator in CANDIDATE_SEPARATORS:
        counts = [len(re.split(separator, line)) for line in lines]
        if min(counts) > 1 and len(set(counts)) == 1 and counts[0] > best[0]:
            best = (counts[0], separator)

    return best[1]


class TableSource(VirtualSource):
    KIND = KIND_TABLE
    EXTENSIONS = TABLE_EXTENSIONS

    def __init__(self, path, variable: str = None, separator: str = None, **options):
        super().__init__(path, variable=variable, **options)
        self._separator = separator

    @property
    def separator(self) -> str:
        if self._separator is None:
            self._separator = sniff_separator(self.path)
        return self._separator

    def _describe(self) -> SourceInfo:
        import pandas as pd

        header = pd.read_csv(self.path, sep=self.separator, engine="python", nrows=0)
        rows = self._count_rows()

        return SourceInfo(
            kind=KIND_TABLE,
            node_class=CLASS_TABLE,
            columns=tuple(str(column) for column in header.columns),
            rows=rows,
            variables=(self.path.stem,),
            variable=self.variable or self.path.stem,
            extra={"separator": self.separator},
        )

    def _count_rows(self) -> Optional[int]:
        try:
            if self.path.stat().st_size > ROW_COUNT_SIZE_LIMIT:
                return None
            with open(self.path, "rb") as handle:
                return max(0, sum(1 for line in handle if line.strip()) - 1)
        except OSError as error:
            logging.debug(f"Unable to count rows of {self.path}: {error}")
            return None

    def read_rows(self, limit: int = None, offset: int = 0):
        import pandas as pd

        skiprows = range(1, offset + 1) if offset else None
        return pd.read_csv(self.path, sep=self.separator, engine="python", nrows=limit, skiprows=skiprows)
