import logging
import qt
import slicer

from humanize import naturalsize

from ltrace.slicer.virtual import attributes as virtualAttributes
from ltrace.slicer.virtual import virtual_node
from ltrace.slicer.widget.elided_label import ElidedLabel


class VirtualNodeWidget(qt.QWidget):
    """Explorer card for a virtual node: what it samples, from where, and how to get the rest.

    Shown in addition to the regular per-type information, because the sample *is* a table/volume and the
    user still wants its usual details — this card only explains that it is a sample and offers the actions
    that turn it into the full data.
    """

    def __init__(self, parent=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.node = None
        self.setup()

    def setup(self):
        layout = qt.QFormLayout(self)
        layout.setLabelAlignment(qt.Qt.AlignRight)
        layout.setContentsMargins(0, 0, 0, 0)

        self.warningLabel = qt.QLabel()
        self.warningLabel.setStyleSheet("QLabel { color: #ff6060; }")
        self.warningLabel.setWordWrap(True)
        self.warningLabel.visible = False
        layout.addRow(self.warningLabel)

        self.sampleLabel = qt.QLabel()
        self.sampleLabel.setToolTip("What this node currently holds. The rest of the data is still on disk.")
        layout.addRow("Loaded:", self.sampleLabel)

        self.originalLabel = qt.QLabel()
        self.originalLabel.setToolTip("Size of the original data on disk.")
        layout.addRow("Original:", self.originalLabel)

        self.sourceLabel = ElidedLabel()
        self.sourceLabel.setToolTip("Location of the original data.")
        layout.addRow("Source:", self.sourceLabel)

        self.refreshButton = qt.QPushButton("Refresh")
        self.refreshButton.objectName = "Virtual Node Refresh Button"
        self.refreshButton.setToolTip("Read the sample again, picking up changes made to the source.")
        self.refreshButton.clicked.connect(self.onRefreshClicked)

        self.loadFullButton = qt.QPushButton("Load full data")
        self.loadFullButton.objectName = "Virtual Node Load Full Button"
        self.loadFullButton.clicked.connect(self.onLoadFullClicked)

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.addWidget(self.refreshButton)
        buttonsLayout.addWidget(self.loadFullButton)
        layout.addRow(buttonsLayout)

    # -- population -------------------------------------------------------------------------------
    def setNode(self, node):
        self.node = node
        spec = virtual_node.spec(node)
        if spec is None:
            self.setVisible(False)
            return

        self.sourceLabel.setText(spec.uri)
        self.sourceLabel.setToolTip(spec.uri)

        if spec.is_volume:
            shape = tuple(reversed(spec.full_shape or ()))
            self.originalLabel.setText(
                f"{'×'.join(str(size) for size in shape)} {spec.dtype or ''} ({naturalsize(self._fullBytes(spec))})"
                if shape
                else "unknown"
            )
            sampled = self._sampledShapeText(node)
            self.sampleLabel.setText(f"{sampled} — 1:{spec.factor} of each axis")
            self.loadFullButton.setText("Load full resolution")
            self.loadFullButton.setToolTip(
                "Read the image at full resolution into a new node. This can take a while and use "
                f"about {naturalsize(self._fullBytes(spec))} of memory."
            )
        else:
            total = "unknown number of" if spec.full_rows is None else f"{spec.full_rows}"
            self.originalLabel.setText(f"{total} rows × {len(spec.columns) or '?'} columns")
            self.sampleLabel.setText(f"first {spec.rows} rows")
            self.loadFullButton.setText("Load all rows")
            self.loadFullButton.setToolTip("Read every row of the file into a new table node.")

        stale = virtual_node.is_stale(node)
        self.warningLabel.visible = stale
        if stale:
            self.warningLabel.setText("The original data could not be read. Showing the last known sample.")

    def _sampledShapeText(self, node) -> str:
        image = node.GetImageData() if hasattr(node, "GetImageData") else None
        if image is None:
            return "sample"
        return "×".join(str(size) for size in image.GetDimensions())

    @staticmethod
    def _fullBytes(spec) -> int:
        import numpy as np

        if not spec.full_shape:
            return 0
        itemsize = np.dtype(spec.dtype).itemsize if spec.dtype else 1
        count = 1
        for size in spec.full_shape:
            count *= int(size)
        return count * itemsize

    # -- actions ----------------------------------------------------------------------------------
    def onRefreshClicked(self):
        if self.node is None:
            return

        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            changed = virtual_node.refresh(self.node, force=True)
            self.setNode(self.node)
            slicer.util.showStatusMessage(
                f"{self.node.GetName()}: sample {'updated' if changed else 'unchanged'}", 3000
            )
        except Exception as error:
            logging.exception("Failed to refresh a virtual node")
            slicer.util.errorDisplay(f"Could not refresh the sample: {error}")
        finally:
            qt.QApplication.restoreOverrideCursor()

    def onLoadFullClicked(self):
        if self.node is None:
            return

        spec = virtual_node.spec(self.node)
        if spec is not None and spec.is_volume:
            size = self._fullBytes(spec)
            if size > 512 * 1024**2 and not slicer.util.confirmYesNoDisplay(
                f"Reading {self.node.GetName()} at full resolution needs about {naturalsize(size)} of memory. "
                "Continue?"
            ):
                return

        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            loaded = virtual_node.load_full(self.node)
            slicer.util.showStatusMessage(f"{loaded.GetName()} loaded", 3000)
        except Exception as error:
            logging.exception("Failed to load a virtual node at full resolution")
            slicer.util.errorDisplay(f"Could not load the full data: {error}")
        finally:
            qt.QApplication.restoreOverrideCursor()
