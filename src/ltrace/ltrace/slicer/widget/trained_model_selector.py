import re
from typing import Callable, Union
import slicer
import qt

from pathlib import Path
from ltrace.assets_utils import get_models_by_tag, get_metadata, get_pth, get_h5
from ltrace.slicer.ai_models.widget import AIModelsPathDialog
from ltrace.slicer.ai_models.defs import get_model_download_links
from ltrace.slicer.application_observables import ApplicationObservables


class TrainedModelSelector(qt.QComboBox):
    def __init__(self, tags: list[str], modelCategory: Union[None, str] = None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.tags = None
        self.modelCategory = None
        self.setToolTip("Select pre-trained model to use in this module")
        self.setTags(tags, modelCategory)
        ApplicationObservables().modelPathUpdated.connect(self.__populateSelf)
        self.destroyed.connect(self.__del__)

    def __del__(self):
        ApplicationObservables().modelPathUpdated.disconnect(self.__populateSelf)

    def __formatTitle(self, title):  # remove model category from model title to avoid redundance
        if not self.modelCategory:
            return title
        title = title.replace(self.modelCategory, "").strip()
        if title.startswith("("):
            title = title[1:-1]
        elif title.startswith("-"):
            title = title[1:].strip()
        return " ".join(title.split())

    def __populateSelf(self) -> None:
        modelsList = get_models_by_tag(self.tags)
        self.clear()
        if modelsList:
            for model in modelsList:
                metaData = get_metadata(model)
                self.addItem(metaData["title"], model)

            self.setEnabled(True)
        else:
            self.addItem("No model found", None)
            self.setEnabled(False)

    def setTags(self, tags: list[str], modelCategory: Union[None, str] = None) -> None:
        if (tags == self.tags) and (modelCategory == self.modelCategory):
            return

        self.tags = tags
        self.modelCategory = modelCategory
        self.__populateSelf()

    def triggerMissingModel(self) -> None:
        loadModelsButtonText = "Load Models"
        cancelButtonText = "Cancel"

        modelLinksDict = get_model_download_links()
        linksListHtml = ""
        pluralSuffix = "s" if len(modelLinksDict) > 1 else ""

        for model in modelLinksDict:
            versionPattern = r"-\d+\.\d+\.\d+\.zip"
            versionMatch = re.search(versionPattern, modelLinksDict[model])

            versionedModel = model[:]
            if versionMatch:
                versionedModel += f" v{Path(versionMatch.group()).stem[1:]}"
            else:
                versionedModel += " (original)"

            linksListHtml += f'<li><a href="{modelLinksDict[model]}">{versionedModel}</a></<li>'

        text = f"""<p>The current version of GeoSlicer requires a specific AI model package for this task. 
            The compatible package version{pluralSuffix} can be found in the following
            link{pluralSuffix}:</p>
                {linksListHtml}
            <p>Make sure to download the appropriate package and add its path by clicking on
            "{loadModelsButtonText}" below. Remove older versions in order to avoid
            duplicates in other tasks.</p>
        """

        messageBox = qt.QMessageBox(slicer.modules.AppContextInstance.mainWindow)
        messageBox.setWindowTitle("No model found")
        messageBox.setIcon(qt.QMessageBox.Warning)
        messageBox.setTextFormat(qt.Qt.RichText)
        messageBox.setText(text)
        loadModelsButton = messageBox.addButton(f"&{loadModelsButtonText}", qt.QMessageBox.ActionRole)
        cancelButton = messageBox.addButton(f"&{cancelButtonText}", qt.QMessageBox.ActionRole)

        messageBox.exec_()

        if messageBox.clickedButton() == loadModelsButton:
            modelsDialog = AIModelsPathDialog(slicer.util.mainWindow())
            modelsDialog.exec_()

    def addItem(self, text: str, userData: Union[None, Path] = None) -> None:
        text = self.__formatTitle(text)
        qt.QComboBox.addItem(self, text, userData)

    def getSelectedModelPath(self) -> str:
        return Path(self.currentData).as_posix()

    def getSelectedModelPth(self) -> str:
        return Path(get_pth(self.currentData)).as_posix()

    def getSelectedModelH5(self) -> str:
        return Path(get_h5(self.currentData)).as_posix()

    def getSelectedModelMetadata(self) -> dict:
        return get_metadata(self.currentData)
