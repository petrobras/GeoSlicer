from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget
from ltrace.slicer_utils import getResourcePath
from pathlib import Path
import qt
import os
import slicer


class FlowButton(qt.QPushButton):
    def __init__(self, iconPath, richText, parent=None):
        super().__init__(parent)
        self.setStyleSheet("padding: 10px; margin: 0px 10px 10px 10px;")

        layout = qt.QHBoxLayout(self)

        iconLabel = qt.QLabel()
        iconLabel.setPixmap(qt.QPixmap(iconPath))

        textLabel = qt.QLabel(richText)
        textLabel.setWordWrap(True)
        textLabel.setAttribute(qt.Qt.WA_TransparentForMouseEvents)

        layout.addWidget(iconLabel)
        layout.addWidget(textLabel)
        layout.addStretch()

        self.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Preferred)


class ThinSectionFlows(LTracePlugin):
    SETTING_KEY = "ThinSectionFlows"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Thin Section Flows"
        self.parent.categories = ["Tools", "Thin Section"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = (
            f"file:///{(getResourcePath('manual') / 'Modules/Thin_section/Fluxo%20PP.html').as_posix()}"
        )

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ThinSectionFlowsWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def setup(self):
        LTracePluginWidget.setup(self)

        helpLabel = qt.QLabel(
            """<p><b>Flows</b> are a way to follow a sequence of work steps in a simpler, streamlined way.</p>
            <p>Choose a flow to start.</p>
            """
        )
        helpLabel.setStyleSheet("margin: 10px;")
        helpLabel.setWordWrap(True)
        self.layout.addWidget(helpLabel)
        iconPath = ThinSectionFlows.MODULE_DIR / "Resources" / "Icons"

        text = """
<h3>PP Flow</h3>
<ul>
    <li><b>Load</b> PP image from file</li>
    <li><b>Segment</b>, manually or automatically</li>
    <li><b>Split</b> segmentation into labels and generate a report table</li>
</ul>
"""
        ppButton = FlowButton(iconPath / "pp.png", text)
        ppButton.clicked.connect(lambda: slicer.util.selectModule("PpFlow"))
        self.layout.addWidget(ppButton)

        text = """
<h3>PP/PX Flow</h3>
<ul>
    <li><b>Load</b> PP, PX images from file</li>
    <li><b>Register</b> images</li>
    <li><b>Segment</b>, manually or automatically</li>
    <li><b>Split</b> segmentation into labels and generate a report table</li>
</ul>
"""
        ppPxButton = FlowButton(iconPath / "pppx.png", text)
        ppPxButton.clicked.connect(lambda: slicer.util.selectModule("PpPxFlow"))
        self.layout.addWidget(ppPxButton)

        text = """
<h3>QEMSCAN Flow</h3>
<ul>
    <li><b>Load</b> QEMSCAN image from file</li>
    <li><b>Split</b> segments into labels and generate a report table</li>
</ul>
"""
        qemscanButton = FlowButton(iconPath / "qs.png", text)
        qemscanButton.clicked.connect(lambda: slicer.util.selectModule("QemscanFlow"))
        self.layout.addWidget(qemscanButton)
        self.layout.addStretch(1)
