import qt

from ltrace.slicer.virtual.fourd.manager import get_manager
from ltrace.slicer.virtual.fourd import proxy
from ltrace.slicer.widget.fourd_player import FourDPlayerWidget


class FourDWidget(qt.QWidget):
    """Explorer card for a 4D proxy node: the player, plus what the sequence is.

    Selecting the node in the Explorer is what surfaces the controls, as required: the node *is* the
    sequence, so its information panel is where navigating it belongs.
    """

    def __init__(self, parent=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.node = None
        self.setup()

    def setup(self):
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.summaryLabel = qt.QLabel()
        self.summaryLabel.setWordWrap(True)
        layout.addWidget(self.summaryLabel)

        self.playerWidget = FourDPlayerWidget()
        layout.addWidget(self.playerWidget)

        self.problemLabel = qt.QLabel()
        self.problemLabel.setStyleSheet("QLabel { color: #ff6060; }")
        self.problemLabel.setWordWrap(True)
        self.problemLabel.visible = False
        layout.addWidget(self.problemLabel)

    def setNode(self, node):
        self.node = node
        if node is None or not proxy.is_proxy(node):
            self.playerWidget.clear()
            return

        # Reopening a saved project leaves the node without a player; attach rebuilds it on demand.
        player = get_manager().attach(node)
        self.playerWidget.setPlayer(player)

        if player is None:
            self.summaryLabel.setText("")
            self.problemLabel.visible = True
            self.problemLabel.setText(
                "This 4D dataset could not be reopened. Check that its folder is still available: "
                f"{proxy.dataset_uri(node) or 'unknown location'}"
            )
            return

        self.problemLabel.visible = False
        info = player.dataset.describe()
        shape = "×".join(str(size) for size in reversed(info.shape_zyx or ()))
        self.summaryLabel.setText(
            f"{player.frameCount} frames of {shape} {info.dtype} — {player.dataset.root.as_posix()}"
        )

    def cleanup(self):
        self.playerWidget.clear()
