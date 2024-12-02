from typing import List
from unittest.mock import patch, MagicMock

import contextlib


@contextlib.contextmanager
def mockFileDialog(selectedFiles: List[str] = None, getSaveFileName: str = None, cancel=False) -> None:

    fileDialogClsMock = MagicMock()
    fileDialogMock = MagicMock()
    fileDialogMock.selectedFiles.return_value = selectedFiles
    fileDialogMock.exec.return_value = 0 if cancel else 1

    fileDialogClsMock.return_value = fileDialogMock
    fileDialogClsMock.getSaveFileName.return_value = getSaveFileName

    patcher = patch("qt.QFileDialog", fileDialogClsMock)
    patcher.start()

    yield

    patcher.stop()
