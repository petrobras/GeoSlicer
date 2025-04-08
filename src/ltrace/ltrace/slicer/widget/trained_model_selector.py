import slicer
import qt

from pathlib import Path
from ltrace.assets_utils import get_models_by_tag, get_metadata, get_pth, get_h5
from ltrace.slicer.ai_models.widget import AIModelsPathDialog
from ltrace.slicer.ai_models.defs import get_model_download_links
from ltrace.slicer.application_observables import ApplicationObservables


class TrainedModelSelector(qt.QComboBox):
    def __init__(self, tags: list[str], *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.tags = None
        self.setToolTip("Select pre-trained model to use in this module")
        self.setTags(tags)
        self.__populateSelf()
        ApplicationObservables().modelPathUpdated.connect(self.__populateSelf)

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

    def setTags(self, tags: list[str]) -> None:
        if tags == self.tags:
            return

        self.tags = tags
        self.__populateSelf()

    def triggerMissingModel(self) -> None:
        modelLinksDict = get_model_download_links()
        linksListHtml = ""

        for model in modelLinksDict:
            linksListHtml += f'<li><a href="{modelLinksDict[model]}">{model}</a></<li>'

        text = f"""No AI models have been installed. Models can be found at the following links:
                {linksListHtml}
        """

        messageBox = qt.QMessageBox(slicer.modules.AppContextInstance.mainWindow)
        messageBox.setWindowTitle("No model found for this module")
        messageBox.setIcon(qt.QMessageBox.Warning)
        messageBox.setTextFormat(qt.Qt.RichText)
        messageBox.setText(text)
        loadModelsButton = messageBox.addButton("&Load Models", qt.QMessageBox.ActionRole)
        cancelButton = messageBox.addButton("&Cancel Exit", qt.QMessageBox.ActionRole)

        messageBox.exec_()

        if messageBox.clickedButton() == loadModelsButton:
            modelsDialog = AIModelsPathDialog(slicer.util.mainWindow())
            modelsDialog.exec_()

    def getSelectedModelPath(self) -> str:
        return Path(self.currentData).as_posix()

    def getSelectedModelPth(self) -> str:
        return Path(get_pth(self.currentData)).as_posix()

    def getSelectedModelH5(self) -> str:
        return Path(get_h5(self.currentData)).as_posix()

    def getSelectedModelMetadata(self) -> dict:
        return get_metadata(self.currentData)
