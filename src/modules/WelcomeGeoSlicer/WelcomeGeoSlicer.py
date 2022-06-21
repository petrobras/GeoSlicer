from pathlib import Path

import qt
import slicer
import logging
from ltrace.slicer_utils import *
from ltrace.workflow import WorkflowWidget


class WelcomeGeoSlicer(LTracePlugin):
    SETTING_KEY = "WelcomeGeoSlicer"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Welcome GeoSlicer"
        self.parent.categories = [""]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ""


class WelcomeGeoSlicerWidget(LTracePluginWidget):
    RESOURCES_PATH = Path(__file__).parent.absolute() / "Resources"
    CARBONATE_CT_ICON_PATH = RESOURCES_PATH / "Carbonate-CT.png"
    SANDSTONE_CT_ICON_PATH = RESOURCES_PATH / "Sandstone-CT.png"

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.workflowWidget = None

    def setup(self):
        LTracePluginWidget.setup(self)

        self.gridLayout = qt.QVBoxLayout()
        self.gridLayout.setContentsMargins(10, 10, 10, 0)
        self.gridLayout.setSpacing(10)
        frame = qt.QFrame()
        frame.setLayout(self.gridLayout)
        self.layout.addWidget(frame)

        generalInformationTextEdit = qt.QLabel()
        generalInformationTextEdit.setStyleSheet("QWidget {font-size: 12px;}")
        generalInformationTextEdit.setText(
            "Welcome to <b>GeoSlicer</b>, an integrated digital rocks platform developed by LTrace."
        )
        self.gridLayout.addWidget(generalInformationTextEdit)

        for group_name in self._get_shortcut_grid():
            groupBox, vBoxLayout = self.creatyEntryModuleFrame(group_name[0])
            for label, image, callback, gridPosition in group_name[1]:
                self.createEntryModuleButton(label, callback, vBoxLayout, image, gridPosition)
            self.gridLayout.addWidget(groupBox)
        self.gridLayout.addStretch(1)
        self.__mainWindow = slicer.util.mainWindow()

    def _get_shortcut_grid(self):
        return [
            (
                "Environments",
                [
                    ("Image Log", "ImageLogEnv.png", "ImageLogEnv", [0, 0]),
                    ("Core", "CoreEnv.png", "CoreEnv", [0, 1]),
                    ("Micro CT", "MicroCTEnv.png", "MicroCTEnv", [0, 2]),
                    ("Thin Section", "ThinSectionEnv.png", "ThinSectionEnv", [0, 3]),
                ],
            ),
            (
                "Tools",
                [
                    ("2D Color Scales", "CustomizedData.png", "CustomizedData", [0, 0]),
                    ("3D Color Scales", "VolumeRendering.png", "VolumeRendering", [0, 1]),
                    ("Volume Calculator", "VolumeCalculator.png", "VolumeCalculator", [0, 2]),
                    ("Tables", "Tables.png", "CustomizedTables", [0, 3]),
                    ("Segmentation Tools", "Segmentation.png", "SegmentationEnv", [1, 0]),
                    ("Charts", "Charts.png", "Charts", [1, 1]),
                    ("Table Filter", "TableFilter.png", "TableFilter", [1, 2]),
                    ("NetCDF", "NetCDF.png", "NetCDF", [1, 3]),
                    ("Workflow (Beta)", "Workflow.png", self.workflow, [2, 0]),  # Hiding workflow for now
                    ("BIAEP Browser", "BIAEPBrowser.png", "BIAEPBrowser", [2, 1]),
                    ("Multiple\nImage Analysis", "MultipleImageAnalysis.png", "MultipleImageAnalysis", [2, 2]),
                    ("Representative\nVolume", "VariogramAnalysis.png", "VariogramAnalysis", [2, 3]),
                ],
            ),
        ]

    def workflow(self):
        if self.workflowWidget is None:
            self.workflowWidget = WorkflowWidget(slicer.util.mainWindow())
        self.workflowWidget.show()

    def creatyEntryModuleFrame(self, title):
        hBoxLayout = qt.QGridLayout()
        groupBox = qt.QGroupBox(title)
        groupBox.setStyleSheet("QGroupBox {font-size: 20px;}")
        groupBox.setLayout(hBoxLayout)
        return groupBox, hBoxLayout

    def createEntryModuleButton(self, text, action, parent, image, gridPosition):
        pushButton = qt.QToolButton()
        pushButton.setStyleSheet(
            "QToolButton {\
                background-color: transparent;\
                border: none;\
                padding-top: 8px;\
                padding-bottom: 8px;\
            }\
            QToolButton:hover {\
                background-color: gray;\
                border-radius: 3px;\
            }\
            QToolButton:pressed {\
                background-color: #6B6B6B;\
            }"
        )
        icon = qt.QIcon(self.RESOURCES_PATH.joinpath(image))
        pushButton.setToolButtonStyle(qt.Qt.ToolButtonTextUnderIcon)
        pushButton.setIcon(icon)
        pushButton.setText(text)
        pushButton.setIconSize(qt.QSize(60, 60))
        pushButton.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)

        if isinstance(action, str):
            if action == "MultipleImageAnalysis":

                def callback():
                    slicer.util.selectModule("ThinSectionEnv")
                    slicer.modules.ThinSectionEnvWidget.switchToMultipleImageAnalysis()

                pushButton.clicked.connect(callback)
            elif action.lower() in slicer.modules.__dict__:
                pushButton.clicked.connect(lambda: self.__mainWindow.moduleSelector().selectModule(action))
            else:
                logging.info(action + " is not available in this version. Skipping shortcut creation")
                return
        else:
            pushButton.clicked.connect(lambda: action())

        if action is None:
            pushButton.setEnabled(False)

        parent.addWidget(pushButton, *gridPosition)

    def enter(self) -> None:
        super().enter()
        try:
            self.setDataProbeVisible(False)
            self.showLTraceLogo(False)
        except Exception as error:
            logging.debug("WelcomeGeoSlicer error: {}".format(error))
            return

    def exit(self):
        try:
            self.setDataProbeVisible(True)
            self.showLTraceLogo(False)
        except Exception as error:
            logging.debug("WelcomeGeoSlicer error: {}".format(error))
            return

    def showLTraceLogo(self, show):
        try:
            if self.__mainWindow is None:
                return
            dockWidgetContents = self.__mainWindow.findChild(qt.QObject, "dockWidgetContents")
            slicerLogoLabel = dockWidgetContents.findChild(qt.QLabel, "LogoLabel")
            if slicerLogoLabel:
                slicerLogoLabel.setVisible(show)
        except Exception as error:
            logging.debug("WelcomeGeoSlicer error: {}".format(error))
            return

    def setDataProbeVisible(self, visible):
        widget = slicer.util.findChild(self.__mainWindow, "DataProbeCollapsibleWidget")
        if not widget:
            return
        widget.setVisible(visible)


class WelcomeGeoSlicerLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)
