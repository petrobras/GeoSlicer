from pathlib import Path
from typing import Tuple
import requests
import slicer
import qt

from commons.slicer.custom_modules.logic import customModules
from commons.slicer_utils import LTracePluginTest, LTracePlugin
from commons.slicer.app import MANUAL_BASE_URL
from commons.slicer.node_attributes import NodeEnvironment
from unittest.mock import patch


def _listLTracePluginsInstance() -> list[LTracePlugin]:
    listOfInstances = []
    for module in dir(slicer.modules):
        if not module.endswith("Instance"):
            continue

        instance = getattr(slicer.modules, module)
        if not hasattr(instance, "helpUrl") or not hasattr(instance, "title"):
            continue  # Not a LTrace Plugin

        if instance.title().lower().endswith("effect"):
            continue

        if instance.parent.hidden:
            continue

        if customModules().isCustomModule(module.removesuffix("Instance")):
            continue  # Modules loaded from the user's folders don't ship with GeoSlicer

        listOfInstances.append(instance)

    return listOfInstances


def _getLocalManualRoot() -> Path:
    # This file lives at src/modules/TestsModule/Test/ — four parents up is the repo root
    return Path(__file__).resolve().parents[4] / "tools" / "deploy" / "manual"


def _testWebUrl(url: str) -> Tuple[bool, str]:
    """Request URL from manual path and assert success code

    Args:
        url (str): the manual web URL

    Returns:
        Tuple(bool, str): (status, error)
    """
    status = False
    error = ""
    try:
        r = requests.get(url)
        if r.status_code == 200:
            status = True
        else:
            status = False
            error = f"Manual page is not acessible: '{url}'"
    except Exception:
        status = False
        error = f"Manual page is not acessible: '{url}'"

    return (status, error)


def _testLocalUrl(url: str, manualRoot: Path, language: str) -> Tuple[bool, str]:
    relative = url.removeprefix(MANUAL_BASE_URL).split("#")[0]
    path = manualRoot / language / relative
    if path.exists():
        return True, ""
    return False, f"Manual page not found locally: '{url}'"


def _getAllHelpUrl(instance: LTracePlugin) -> dict:
    return instance._LTracePlugin__helpUrl


class SlicerUtilsTest(LTracePluginTest):
    def test_manual_path_validation(self, timeout_ms=300000) -> None:
        """Test the documentation URL for all LTrace plugins. This test might take a while to fisish."""
        exceptionModules = [
            "Explorer",
            "Histogram Segmenter",  # Disabled
            "PUC Image Log Segmenter",  # Disabled
            "Micro CT Cups Analysis (advanced)",  # Disabled
            "MONAILabel Server",  # Disabled
            "UpscaleTomoToLAS",  # Disabled
            "Upscale Plug To Core",  # Disabled,
            "Pre-salt Rock Generator (Beta)",  # Disabled
            "PNM Compare Models",  # Debug only
            "Porosity Mapping From Saturation",  # Disabled
            "Segmentation Kmeans",  # Disabled,
            "Pore Network Workflow",  # Under construction
            "Pore Network Remote Workflow",  # Under construction
        ]
        manualRoot = _getLocalManualRoot()

        failures = []
        for instance in _listLTracePluginsInstance():
            if instance.title() in exceptionModules:
                continue

            moduleTitle = instance.title()
            if not hasattr(instance, "helpUrl"):
                continue  # Not a LTrace Plugin

            if not instance.helpUrl:
                failures.append((moduleTitle, "Manual path is not defined"))
                continue

            for env, url in _getAllHelpUrl(instance).items():
                assert isinstance(url, qt.QUrl)
                manualPath = url.toString()

                if not manualPath:
                    failures.append((moduleTitle, f"Manual path is not defined for '{env}'"))
                    continue

                if ".html" not in manualPath:
                    failures.append((moduleTitle, f"Manual path is not referencing a HTML page in '{env}'"))
                    continue

                assert manualPath is not MANUAL_BASE_URL
                for lang in ["en", "pt"]:
                    status, error = _testLocalUrl(manualPath, manualRoot, lang)
                    if not status:
                        failures.append((moduleTitle, f"{error} in '{env}'"))
                        continue

        # Show all failures at once, if any
        if failures:
            failureText = "Failed to validate manual paths for the following modules:"
            for failure in failures:
                failureText += f"\n{failure[0]}: {failure[1]}"

            raise Exception(failureText)

    def test_manual_different_url_depending_on_environment(self) -> None:
        instance = slicer.modules.MultiScaleInstance
        assert instance is not None
        microCtUrl = multiscaleUrl = ""
        with patch("commons.slicer_utils.getCurrentEnvironment") as mockGetCurrentEnvironment:
            mockGetCurrentEnvironment.return_value = NodeEnvironment.MICRO_CT
            microCtUrl = instance.helpUrl
            mockGetCurrentEnvironment.assert_called_once()

        with patch("commons.slicer_utils.getCurrentEnvironment") as mockGetCurrentEnvironment:
            mockGetCurrentEnvironment.return_value = NodeEnvironment.MULTISCALE
            multiscaleUrl = instance.helpUrl
            mockGetCurrentEnvironment.assert_called_once()

        self.assertNotEqual(microCtUrl, multiscaleUrl)
