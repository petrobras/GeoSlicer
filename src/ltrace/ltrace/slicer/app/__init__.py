import json
from pathlib import Path
from typing import Dict

import slicer
import vtk
import os

from datetime import datetime


def parseApplicationVersion(data: Dict) -> str:
    geoslicerVersion = data["GEOSLICER_VERSION"]
    geoslicerHash = data["GEOSLICER_HASH"]
    geoslicerHashDirty = data["GEOSLICER_HASH_DIRTY"]
    geoslicerBuildTime = datetime.strptime(data["GEOSLICER_BUILD_TIME"], "%Y-%m-%d %H:%M:%S.%f")

    versionString = geoslicerVersion
    if not geoslicerVersion:
        hash_ = geoslicerHash[:8] + "*" if geoslicerHashDirty else ""
        date = geoslicerBuildTime.strftime("%Y-%m-%d")
        versionString = "{} {}".format(hash_, date)

    return versionString


def getApplicationVersion():
    return slicer.modules.AppContextInstance.appVersionString


def getApplicationInfo(key):
    return slicer.modules.AppContextInstance.appData.get(key, None)


def updateWindowTitle(versionString):
    """Updates main window's title according to the current project"""

    projectString = "Untitled project"
    projectURL = slicer.mrmlScene.GetURL()
    if projectURL != "":
        projectString = os.path.dirname(projectURL)

    windowTitle = "GeoSlicer {} - {} [*]".format(versionString, projectString)
    slicer.modules.AppContextInstance.mainWindow.setWindowTitle(windowTitle)


def tryDetectProjectDataType():

    nodes = slicer.util.getNodesByClass("vtkMRMLVolumeNode")
    if len(nodes) == 0:
        return False

    sceneTree = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    rootItemID = sceneTree.GetSceneItemID()

    children = vtk.vtkIdList()
    sceneTree.GetItemChildren(rootItemID, children)

    for i in reversed(range(children.GetNumberOfIds())):
        child = children.GetId(i)
        name = sceneTree.GetItemName(child)
        print("name", name)
        if "Thin Section" in name:
            return "Thin Section"
        elif "Micro CT" in name:
            return "Volumes"
        elif "Multicore" in name:
            return "Core"
        elif "Well Logs" in name:
            return "Well Logs"
        elif "Multiscale" in name:
            return "Multiscale"

    return None


def getJsonData() -> Dict:
    appName = slicer.app.applicationName
    appHome = Path(slicer.app.slicerHome)
    appSlicerVersion = f"{slicer.app.majorVersion}.{slicer.app.minorVersion}"
    scriptedModulesDir = appHome / "lib" / f"{appName}-{appSlicerVersion}" / "qt-scripted-modules"
    appJson = scriptedModulesDir / "Resources" / "json" / "GeoSlicer.json"
    with open(appJson, "r") as file:
        jsonData = json.load(file)

    return jsonData
