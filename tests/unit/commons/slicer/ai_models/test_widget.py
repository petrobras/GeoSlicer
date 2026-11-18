from unittest.mock import MagicMock, patch
from pathlib import Path
from commons.slicer.ai_models.widget import AIModelsPathModel, ModelInfo
from commons.assets_utils import get_public_asset_path
import tempfile
import json
import pytest


class TestAIModelsPathModel:
    def setup_method(self):
        self.model = AIModelsPathModel()

    def create_test_model(self, path, tag, name, title):

        tagPath = path / tag
        if not tagPath.exists():
            tagPath.mkdir()

        modelPath = tagPath / name
        modelPath.mkdir()

        pthPath = modelPath / "model.pth"
        pthPath.touch()

        metadata = modelPath / "meta.json"
        metaDataData = {
            "title": title,
        }
        with open(metadata, "w") as f:
            json.dump(metaDataData, f)

        return tagPath, modelPath, pthPath

    def test_remove_path_not_in_paths(self):
        self.model.addPath("/path1")
        self.model.addPath("/path2")
        self.model.removePath("/path3")
        assert self.model.paths == [get_public_asset_path(), "/path1", "/path2"]

    def test_remove_path_in_paths(self):
        self.model.addPath("/path1")
        self.model.addPath("/path2")
        self.model.removePath("/path1")
        assert self.model.paths == [get_public_asset_path(), "/path2"]

    def test_remove_path_calls_update_paths_to_settings(self):
        mockUpdatePathsToSettings = MagicMock()

        self.model.addPath("/path1")
        self.model.addPath("/path2")
        self.model._AIModelsPathModel__updatePathsToSettings = mockUpdatePathsToSettings
        self.model.removePath("/path1")

        mockUpdatePathsToSettings.assert_called_once()

    def test_remove_path_calls_update_models(self):
        self.model.addPath("/path1")
        self.model.addPath("/path2")
        self.model._AIModelsPathModel__updateModels = MagicMock()
        self.model.removePath("/path1")
        self.model._AIModelsPathModel__updateModels.assert_called_once()

    def test_get_paths_from_settings(self):
        with patch("slicer.app.settings") as mockSettings:
            mockSettingsObj = MagicMock()
            mockSettings.return_value = mockSettingsObj

            mockSettingsValue = MagicMock()
            mockSettingsValue.return_value = ["/path1", "/path2"]

            mockSettingsObj.value = mockSettingsValue
            assert self.model.getPathsFromSettings() == ["/path1", "/path2"]

    def test_update_paths_to_settings(self):
        self.model.addPath("/path1")
        with patch("slicer.app.settings") as mockSettings:
            mockSettingsObj = MagicMock()
            mockSettingsSetValue = MagicMock()
            mockSettings.return_value = mockSettingsObj
            mockSettingsObj.setValue = mockSettingsSetValue

            self.model.addPath("/path2")

            mockSettingsSetValue.assert_any_call("AIModelsPaths", ["/path1", "/path2"])
            assert get_public_asset_path() in self.model.paths

    def test_update_models_path_to_settings(self):
        with tempfile.TemporaryDirectory() as tempDir:
            tempDirPath = Path(tempDir)
            with patch("slicer.app.settings") as mockSettings:
                mockSettingsObj = MagicMock()
                mockSettingsSetValue = MagicMock()
                mockSettings.return_value = mockSettingsObj
                mockSettingsObj.setValue = mockSettingsSetValue

                tagPath, modelPath, pthPath = self.create_test_model(tempDirPath, "tag", "model_name", "title")

                self.model.addPath(tempDirPath)

                modelsSettings = {"model_name": pthPath.as_posix()}

                mockSettingsSetValue.assert_called_with("AISingleModelsPaths", modelsSettings)

    def test_add_path(self):
        self.model.addPath("/path1")
        self.model.addPath("/path2")
        assert self.model.paths == [get_public_asset_path(), "/path1", "/path2"]

    def test_add_path_calls_update_paths_to_settings(self):
        mockUpdatePathsToSettings = MagicMock()

        self.model.addPath("/path1")
        self.model._AIModelsPathModel__updatePathsToSettings = mockUpdatePathsToSettings
        self.model.addPath("/path2")

        mockUpdatePathsToSettings.assert_called_once()

    def test_add_path_calls_update_models(self):
        mockUpdateModels = MagicMock()

        self.model.addPath("/path1")
        self.model._AIModelsPathModel__updateModels = mockUpdateModels
        self.model.addPath("/path2")

        mockUpdateModels.assert_called_once()

    def test_validate_paths(self):
        with tempfile.TemporaryDirectory() as tempDir:
            tempDirPath = Path(tempDir)
            path1 = tempDirPath / "path1"
            path1.mkdir()
            path2 = tempDirPath / "path2"
            path2.mkdir()
            path3 = tempDirPath / "path3"
            path4 = tempDirPath / "path4" / "file.txt"

            pathsToValidate = [str(path1), str(path2), str(path3), str(path4)]
            expectedPaths = [str(path1), str(path2)]
            assert self.model._AIModelsPathModel__validatePaths(pathsToValidate) == expectedPaths

    def test_models(self):
        with tempfile.TemporaryDirectory() as tempDir:
            models = ["Test Model", "Another Test Model"]
            modelFiles = []
            for model in models:
                tempDirPath = Path(tempDir)
                modelName = f"{model.lower().replace(' ', '')}"
                tagPath, modelPath, pthPath = self.create_test_model(tempDirPath, "tag", modelName, model)
                modelFiles.append(pthPath)

            self.model.addPath(str(tempDirPath))

            expectedModelInfo = [
                ModelInfo(title="Test Model", name="testmodel", path=modelFiles[0], environment=""),
                ModelInfo(title="Another Test Model", name="anothertestmodel", path=modelFiles[1], environment=""),
            ]
            for model in expectedModelInfo:
                assert model in self.model.models

    def test_models_with_environment(self):
        expectedModelInfo = []
        with tempfile.TemporaryDirectory() as tempDir:
            models = ["Test Model", "Another Test Model", "Third Model"]
            environments = ["ThinSectionEnv", "MicroCTEnv", "None"]
            for model, environment in zip(models, environments):
                tempDirPath = Path(tempDir)
                modelName = f"{model.lower().replace(' ', '')}"

                expectedEnvironment = environment.replace("Env", "")
                if environment == "None":
                    expectedEnvironment = ""

                tagPath, modelPath, pthPath = self.create_test_model(tempDirPath, environment, modelName, model)

                (
                    expectedModelInfo.append(
                        ModelInfo(title=model, name=modelPath.name, path=pthPath, environment=expectedEnvironment)
                    ),
                )

            self.model.addPath(str(tempDirPath))

            expectedModelInfoList = sorted(expectedModelInfo, key=lambda x: x.title)
            currentModelInfoList = sorted(self.model.models, key=lambda x: x.title)
            for model in expectedModelInfoList:
                assert model in currentModelInfoList

    @pytest.mark.parametrize("pathType", ["directory", "file"])
    def test_loading_model_directly(self, tmp_path, pathType):
        tempDirPath = Path(tmp_path)

        pthPath = tempDirPath / "model.pth"
        pthPath.touch()

        metadata = tempDirPath / "meta.json"
        metaDataData = {
            "title": "Test Model",
        }
        with open(metadata, "w") as f:
            json.dump(metaDataData, f)

        if pathType == "directory":
            pathToAdd = str(tempDirPath)
        else:  # file
            pathToAdd = str(pthPath)

        self.model.addPath(pathToAdd)

        expectedModelInfo = ModelInfo(title="Test Model", name=tempDirPath.name, path=pthPath, environment="")

        assert expectedModelInfo in self.model.models
