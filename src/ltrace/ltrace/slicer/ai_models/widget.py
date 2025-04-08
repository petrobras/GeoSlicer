import logging
import json
import qt
import slicer

from dataclasses import dataclass
from typing import List
from pathlib import Path

from ltrace.assets_utils import get_metadata, get_public_asset_path
from ltrace.slicer.ai_models.defs import get_model_download_links
from ltrace.slicer.application_observables import ApplicationObservables
from ltrace.slicer.node_attributes import NodeEnvironment
from ltrace.slicer.widget.help_button import HelpButton

ENVIRONMENTS = [env.value for env in NodeEnvironment]


@dataclass
class ModelInfo:
    title: str
    name: str
    path: Path
    environment: str = ""


class AIModelsPathModel:
    SETTINGS_PATH_KEY = "AIModelsPaths"
    SETTINGS_MODELS_KEY = "AISingleModelsPaths"

    def __init__(self, *args, **kwargs) -> None:
        self.__paths: List[str] = []
        self.__models: List[ModelInfo] = []

        self.initialize()

    @property
    def models(self) -> List[ModelInfo]:
        return self.__models

    @property
    def paths(self) -> List[str]:
        return self.__paths

    def initialize(self) -> None:
        self.__updatePaths()
        self.__updateModels()

    def __validatePaths(self, paths: List[str]) -> List[str]:
        """Filter out invalid paths from the path list. The path is considered valid only if its a directory and exists.

        Args:
            paths (List): the path list.

        Returns:
            List: the list contained only valid paths
        """
        validPaths = [path for path in paths if Path(path).is_dir() and Path(path).exists()]
        return validPaths

    @staticmethod
    def getPathsFromSettings() -> List[str]:
        paths = slicer.app.settings().value(AIModelsPathModel.SETTINGS_PATH_KEY, [])
        return paths if paths is not None else []

    def __updatePathsToSettings(self) -> None:
        paths = [path for path in self.paths if path != get_public_asset_path()]
        slicer.app.settings().setValue(AIModelsPathModel.SETTINGS_PATH_KEY, paths)

    def __updateModelsToSettings(self) -> None:
        modelSettings = {}
        for model in self.__models:
            modelSettings[model.name] = model.path.as_posix()

        slicer.app.settings().setValue(AIModelsPathModel.SETTINGS_MODELS_KEY, modelSettings)

    def __update(self):
        self.__updatePathsToSettings()
        self.__updateModels()
        self.__updateModelsToSettings()
        appObservables = ApplicationObservables()
        appObservables.modelPathUpdated.emit()

    def addPath(self, path: str) -> None:
        if path in self.paths:
            return

        self.paths.append(path)
        self.__update()
        logging.debug(f"Adding model path: {path}")

    def removePath(self, path: str) -> None:
        if path not in self.paths:
            return

        logging.debug(f"Removing model path: {path}")
        self.paths.remove(path)
        self.__update()

    def __addPublicPath(self) -> None:
        publicPath = get_public_asset_path()
        self.addPath(publicPath)

    def __updatePaths(self) -> None:
        paths = self.getPathsFromSettings()
        paths = self.__validatePaths(paths=paths)
        self.__paths = paths
        self.__addPublicPath()

    def __updateModels(self) -> None:
        self.__models.clear()

        for path in self.paths:
            path = Path(path)

            for subdir in path.rglob("*"):
                if not subdir.is_dir():
                    continue

                pth = subdir / f"model.pth"
                h5 = subdir / f"model.h5"
                if not (pth.exists() or h5.exists()):
                    continue

                modelPath = pth if pth.exists() else h5
                metaData = get_metadata(subdir)
                if not metaData:
                    continue

                title = metaData["title"]
                environment = ""

                # Identify the environment
                for env in ENVIRONMENTS:
                    if env.lower() in subdir.as_posix().lower():
                        environment = env.replace("Env", "")
                        break

                self.__models.append(ModelInfo(title=title, name=subdir.name, path=modelPath, environment=environment))

        logging.debug(f"Models identified from listed paths: {self.__models}")


class AIModelsPathDialog(qt.QDialog):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setWindowFlags(self.windowFlags() & ~qt.Qt.WindowContextHelpButtonHint & ~qt.Qt.WindowSystemMenuHint)
        self.setWindowTitle("Models Path")
        self.__widget = AIModelsPathWidget(self)

        layout = qt.QVBoxLayout()
        layout.addWidget(self.__widget)
        self.setLayout(layout)

        self.setFixedSize(478, 610)


class AIModelsPathWidget(qt.QWidget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.__model = AIModelsPathModel()
        self.setUp()
        self.__updateModelPathList()
        self.__updateModelTable()
        self.__disablePublicPath()

    def __disablePublicPath(self) -> None:
        for index in range(self.pathList.count):
            item = self.pathList.item(index)
            if item.text() == get_public_asset_path():
                item.setFlags(item.flags() & ~qt.Qt.ItemIsEnabled)

    def __onAddPathClicked(self) -> None:
        path = qt.QFileDialog.getExistingDirectory(self, "Select directory")
        if not path:
            return

        self.__model.addPath(path)
        self.__addPathToList(path)
        self.__updateModelTable()

    def __addPathToList(self, path: str) -> None:
        item = qt.QListWidgetItem(path)
        item.setFlags(item.flags() | ~qt.Qt.ItemIsEditable)
        self.pathList.addItem(item)

    def __onRemovePathClicked(self) -> None:
        selectedItems = self.pathList.selectedItems()
        if len(selectedItems) == 0:
            return

        for item in selectedItems:
            path = item.text()
            self.__model.removePath(path)
            itemRow = self.pathList.row(item)
            self.pathList.takeItem(itemRow)
            del item

        self.__updateModelTable()
        self.pathList.setCurrentRow(-1)

    def __updateModelTable(self) -> None:
        def createTableItem(text: str):
            item = qt.QTableWidgetItem(text)
            item.setFlags(item.flags() & ~qt.Qt.ItemIsEditable)
            return item

        self.identifiedModelsTable.clearContents()
        self.identifiedModelsTable.setRowCount(0)

        for model in self.__model.models:
            currentRow = self.identifiedModelsTable.rowCount
            self.identifiedModelsTable.setRowCount(currentRow + 1)
            self.identifiedModelsTable.setItem(currentRow, 0, createTableItem(model.title))
            self.identifiedModelsTable.setItem(currentRow, 1, createTableItem(model.environment))

    def __updateModelPathList(self) -> None:
        self.pathList.clear()

        for path in self.__model.paths:
            self.__addPathToList(path)

    def __onPathListRowSelectionChanged(self) -> None:

        if len(self.pathList.selectedItems()) == 0:
            self.removePathButton.setEnabled(False)
            return

        self.removePathButton.setEnabled(True)

    def setUp(self) -> None:
        layout = qt.QVBoxLayout()
        layout.setSpacing(12)
        self.setLayout(layout)

        # Models path list
        self.pathList = qt.QListWidget()
        self.pathList.setSelectionMode(qt.QAbstractItemView.ExtendedSelection)
        self.pathList.itemSelectionChanged.connect(self.__onPathListRowSelectionChanged)
        self.pathList.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAsNeeded)

        self.addPathButton = qt.QPushButton("Add")
        self.addPathButton.setFixedSize(100, 30)
        self.addPathButton.clicked.connect(self.__onAddPathClicked)

        self.removePathButton = qt.QPushButton("Remove")
        self.removePathButton.setFixedSize(100, 30)
        self.removePathButton.clicked.connect(self.__onRemovePathClicked)
        self.removePathButton.setEnabled(False)

        pathListButtonsLayout = qt.QHBoxLayout()
        pathListButtonsLayout.setSpacing(6)
        pathListButtonsLayout.addStretch(1)
        pathListButtonsLayout.addWidget(self.addPathButton)
        pathListButtonsLayout.addWidget(self.removePathButton)

        pathListLayout = qt.QVBoxLayout()
        pathListLayout.addWidget(self.pathList)
        pathListLayout.addLayout(pathListButtonsLayout)

        pathsGroupBox = qt.QGroupBox("Paths")
        pathsGroupBox.setLayout(pathListLayout)

        # Identified model list
        self.identifiedModelsTable = qt.QTableWidget()
        self.identifiedModelsTable.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAsNeeded)
        self.identifiedModelsTable.setRowCount(0)
        self.identifiedModelsTable.setColumnCount(2)
        self.identifiedModelsTable.setHorizontalHeaderLabels(["Title", "Environment"])
        self.identifiedModelsTable.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        self.identifiedModelsTable.horizontalHeader().setSectionResizeMode(0, qt.QHeaderView.Stretch)
        self.identifiedModelsTable.verticalHeader().setVisible(False)
        self.identifiedModelsTable.setSortingEnabled(True)

        identifiedModelsTableLayout = qt.QHBoxLayout()
        identifiedModelsTableLayout.addWidget(self.identifiedModelsTable)

        modelsGroupBox = qt.QGroupBox("")
        modelsGroupBox.setLayout(identifiedModelsTableLayout)

        modelLinksDict = get_model_download_links()
        linksListHtml = ""

        for model in modelLinksDict:
            linksListHtml += f'<li><a href="{modelLinksDict[model]}">{model}</a></li>'

        text = f"""Standard models can be found at the following links:
                {linksListHtml}
        """
        modelsHelpButton = HelpButton(text)

        modelsLayout = qt.QVBoxLayout()
        modelsLayout.setContentsMargins(0, 0, 0, 0)
        modelsLayout.setSpacing(0)

        modelsTitleLayout = qt.QHBoxLayout()
        modelsTitleLayout.setSpacing(4)
        modelsTitleLayout.addWidget(qt.QLabel("Models"))
        modelsTitleLayout.addWidget(modelsHelpButton)
        modelsTitleLayout.addStretch(1)

        modelsLayout.addLayout(modelsTitleLayout)
        modelsLayout.addWidget(modelsGroupBox)

        layout.addWidget(pathsGroupBox)
        layout.addLayout(modelsLayout)
