import os
from pathlib import Path

import qt
import slicer
from ltrace.slicer_utils import *


class ModuleToolBarCustomizer(LTracePlugin):
    SETTING_KEY = "ModuleToolBarCustomizer"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Module ToolBar Customizer"

    def customize(self):
        moduleToolBar = slicer.util.findChild(slicer.modules.AppContextInstance.mainWindow, "ModuleToolBar")

        # Actions black-list
        actionBlackList = ["Customized Data", "Segmentation Tools"]
        for action in moduleToolBar.actions():
            if action.text in actionBlackList:
                moduleToolBar.removeAction(action)

        # Renaming and changing icons
        for action in moduleToolBar.actions():
            if action.text == "Volume Rendering":
                action.setText("3D Color Scales")
                action.setIcon(qt.QIcon(self.RES_DIR / "VolumeRendering.png"))

        # Adding separators (after renaming)
        moduleToolBar.setStyleSheet("QToolBar::separator {background-color:#505050; width:1px;}")
        for action in moduleToolBar.actions():
            if action.text == "Image Log Environment":
                moduleToolBar.insertSeparator(action)
                moduleToolBar.insertWidget(action, qt.QLabel("  Environments:"))
            elif action.text == "3D Color Scales":
                moduleToolBar.insertSeparator(action)
                moduleToolBar.insertWidget(action, qt.QLabel("  Tools:"))

        self.workflowAction = qt.QAction("Workflow")
        self.workflowAction.setIcon(qt.QIcon(self.RES_DIR / "Workflow.png"))
        self.workflowAction.triggered.connect(self.workflow)

        # Hiding workflow for now
        # moduleToolBar.addAction(self.workflowAction)

    def workflow(self):
        slicer.modules.welcomegeoslicer.widgetRepresentation().self().workflow()
