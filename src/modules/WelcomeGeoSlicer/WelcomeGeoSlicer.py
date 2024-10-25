import qt
import slicer
import logging
import traceback
import os

from collections import OrderedDict
from dataclasses import dataclass
from ltrace.slicer_utils import *
from ltrace.workflow import WorkflowWidget
from pathlib import Path
from typing import Callable, Tuple
from typing import OrderedDict as OrderedDictType

try:
    from Test.WelcomeGeoslicerTest import WelcomeGeoslicerTest
except ImportError as error:
    WelcomeSlicerTest = None

RESOURCES_PATH = Path(__file__).parent.absolute() / "Resources"


class WelcomeGeoSlicer(LTracePlugin):
    SETTING_KEY = "WelcomeGeoSlicer"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Welcome GeoSlicer"
        self.parent.categories = [""]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ""


def getFeatures() -> OrderedDictType:
    return OrderedDict(
        {
            "Environments": [
                Feature("Image Log", "ImageLogEnv.png", "ImageLogEnv"),
                Feature("Core", "CoreEnv.png", "CoreEnv"),
                Feature("Micro CT", "MicroCTEnv.png", "MicroCTEnv"),
                Feature("Thin Section", "ThinSectionEnv.png", "ThinSectionEnv"),
            ],
            "Tools": [
                Feature("2D Color Scales", "CustomizedData.png", "CustomizedData"),
                Feature("3D Color Scales", "VolumeRendering.png", "VolumeRendering"),
                Feature("Volume Calculator", "VolumeCalculator.png", "VolumeCalculator"),
                Feature("Tables", "Tables.png", "CustomizedTables"),
                Feature("Segmentation Tools", "Segmentation.png", "SegmentationEnv"),
                Feature("Charts", "Charts.png", "Charts"),
                Feature("Table Filter", "TableFilter.png", "TableFilter"),
                Feature("NetCDF", "NetCDF.png", "NetCDF"),
                Feature("Workflow (Beta)", "Workflow.png", None, customActionWorkflow),
                Feature("BIAEP Browser", "BIAEPBrowser.png", "BIAEPBrowser"),
                (
                    Feature("Digital Rocks Portal", "OpenRockData.png", "OpenRockData")
                    if os.getenv("GEOSLICER_MODE") != "Remote"
                    else None
                ),  # Not working in cluster
                Feature(
                    "Multiple\nImage Analysis",
                    "MultipleImageAnalysis.png",
                    "ThinSectionEnv",
                    customActionMultipleImageAnalysis,
                ),
                Feature("Representative\nVolume", "VariogramAnalysis.png", "VariogramAnalysis"),
                Feature("Geolog integration", "icon_geolog.svg", "GeologEnv"),
            ],
        }
    )


def customActionMultipleImageAnalysis():
    slicer.modules.ThinSectionEnvWidget.switchToMultipleImageAnalysis()


def customActionWorkflow():
    workflowWidget = WorkflowWidget(slicer.util.mainWindow())
    workflowWidget.show()


class FeatureToolButton(qt.QToolButton):
    def __init__(
        self,
        text: str,
        moduleName: str,
        image: str,
        parent: qt.QWidget = None,
        gridPosition=None,
        customAction: Callable[[None], None] = None,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.__updateStyleSheet()
        self.__moduleName = moduleName
        self.__customAction = customAction
        formatedName = text.replace("\n", " ")
        self.objectName = f"{formatedName} Tool Button"

        icon = qt.QIcon((RESOURCES_PATH / image).as_posix())
        self.setToolButtonStyle(qt.Qt.ToolButtonTextUnderIcon)
        self.setIcon(icon)
        self.setText(text)
        self.setIconSize(qt.QSize(60, 60))
        self.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)

        if parent is not None:
            if gridPosition is None:
                parent.addWidget(self)
            else:
                parent.addWidget(self, *gridPosition)

        self.clicked.connect(self._action)

    def __updateStyleSheet(self) -> None:
        self.setStyleSheet(
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

    def _action(self):
        try:
            if self.__moduleName is not None:
                slicer.util.selectModule(self.__moduleName)

            if self.__customAction is not None:
                self.__customAction()
        except Exception as error:
            logging.debug(f"Error in {self.__moduleName} shortcut: {error}. Traceback:\n{traceback.print_exc()}")


@dataclass
class Feature:
    text: str
    image: str
    moduleName: str
    customAction: Callable[[None], None] = None

    def createToolButton(self, parent: qt.QWidget = None, gridPosition: Tuple[int, int] = None) -> FeatureToolButton:
        if self.moduleName is not None and slicer.app.moduleManager().module(self.moduleName) is None:
            return None

        return FeatureToolButton(
            text=self.text,
            moduleName=self.moduleName,
            image=self.image,
            customAction=self.customAction,
            parent=parent,
            gridPosition=gridPosition,
        )


class WelcomeGeoSlicerWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

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

        maxColumns = 4
        for groupName, features in getFeatures().items():
            groupBox, vBoxLayout = self.createFeaturesSectionFrame(groupName)
            currentColumn = 0
            currentRow = 0
            for feature in features:
                if not feature:
                    continue
                gridPosition = (currentRow, currentColumn)

                button = feature.createToolButton(parent=vBoxLayout, gridPosition=gridPosition)
                if button is None:
                    continue

                currentColumn += 1
                if currentColumn >= maxColumns:
                    currentColumn = 0
                    currentRow += 1

            self.gridLayout.addWidget(groupBox)

        self.gridLayout.addStretch(1)
        self.__mainWindow = slicer.util.mainWindow()

    def createFeaturesSectionFrame(self, title: str) -> Tuple[qt.QGroupBox, qt.QGridLayout]:
        hBoxLayout = qt.QGridLayout()
        groupBox = qt.QGroupBox(title)
        groupBox.setStyleSheet("QGroupBox {font-size: 20px;}")
        groupBox.setLayout(hBoxLayout)
        return groupBox, hBoxLayout

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
