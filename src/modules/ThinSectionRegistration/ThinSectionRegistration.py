import logging
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Union

import RegistrationLib
import numpy as np
import qt
import slicer
import vtk
from skimage.transform import resize

import ThinSectionRegistrationLib
from ltrace.slicer import ui
from ltrace.slicer_utils import *
from ltrace.slicer_utils import getResourcePath
from ltrace.transforms import getRoundedInteger
from ltrace.utils.ProgressBarProc import ProgressBarProc

try:
    from Test.ThinSectionRegistrationTest import ThinSectionRegistrationTest
except ImportError:
    ThinSectionRegistrationTest = None


class ThinSectionRegistration(LTracePlugin):
    SETTING_KEY = "ThinSectionRegistration"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Registration"
        self.parent.categories = ["Registration", "Thin Section"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = (
            f"file:///{(getResourcePath('manual') / 'Modules/Thin_section/Registration.html').as_posix()}"
        )

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ThinSectionRegistrationWidget(LTracePluginWidget):
    FILTER_NONE = 0
    FILTER_HISTOGRAM_EQUALIZATION_1 = 1

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = ThinSectionRegistrationLogic(parent)
        self.logic.registrationState = self.registrationState
        self.sliceNodesByViewName = {}
        self.sliceNodesByVolumeID = {}
        self.observerTags = []
        self.interactorObserverTags = []
        self.viewNames = ("Fixed", "Moving", "Transformed")
        self.volumeSelectDialog = None
        self.selectedVolumes = {}
        self.transformNode = None
        self.registering = False
        self.previousLayout = None

    def setup(self):
        LTracePluginWidget.setup(self)

        self.selectVolumesButton = qt.QPushButton("Select the images to register")
        self.selectVolumesButton.objectName = "Select Volumes Button"
        self.selectVolumesButton.setFixedHeight(40)
        self.selectVolumesButton.setProperty("class", "actionButtonBackground")
        self.selectVolumesButton.connect("clicked(bool)", self.setupDialog)
        self.layout.addWidget(self.selectVolumesButton)

        self.interfaceFrame = qt.QWidget(self.parent)
        self.layout.addWidget(self.interfaceFrame)

        # Parameters Area
        self.imagesFrame = qt.QFrame()
        imagesLayout = qt.QFormLayout(self.imagesFrame)
        parametersFormLayout = qt.QFormLayout(self.interfaceFrame)
        parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        parametersFormLayout.setContentsMargins(0, 0, 0, 0)

        self.fixedNodeLineEdit = qt.QLineEdit()
        self.fixedNodeLineEdit.setReadOnly(True)
        imagesLayout.addRow("Fixed image:", self.fixedNodeLineEdit)

        self.movingNodeLineEdit = qt.QLineEdit()
        self.movingNodeLineEdit.setReadOnly(True)
        imagesLayout.addRow("Moving image:", self.movingNodeLineEdit)

        self.transformedNodeLineEdit = qt.QLineEdit()
        self.transformedNodeLineEdit.setReadOnly(True)
        imagesLayout.addRow("Transformed image:", self.transformedNodeLineEdit)

        parametersFormLayout.addRow(self.imagesFrame)

        # Visualization Widget
        self.visualizationWidget = ThinSectionRegistrationLib.VisualizationWidget(self.logic)
        self.visualizationWidget.connect("layoutRequested(mode,volumesToShow)", self.onLayout)

        # Image Tools widget (disabling Image Tools from this module because it uses UndoEnabledOn, and it is causing the image node state to be saved
        # when a visualization change is applied: flickering, rock, etc, consuming a lot o memory and ruining the undo/redo state of the image)
        # self.imageToolsCollapsibleButton = ctk.ctkCollapsibleButton()
        # self.imageToolsCollapsibleButton.text = "Image Tools"
        # self.imageToolsCollapsibleButton.collapsed = True
        # self.visualizationWidget.groupBoxLayout.addRow(self.imageToolsCollapsibleButton)
        # imageToolsFormLayout = qt.QFormLayout(self.imageToolsCollapsibleButton)
        # self.imageToolsWidget = slicer.modules.imagetools.createNewWidgetRepresentation()
        # self.imageToolsWidget.self().configureInterfaceForThinSectionRegistrationModule()
        # imageToolsFormLayout.addRow(self.imageToolsWidget)

        parametersFormLayout.addRow(self.visualizationWidget.widget)

        # Landmarks Widget
        self.landmarksWidget = ThinSectionRegistrationLib.LandmarksWidget(self.logic)
        parametersFormLayout.addRow(self.landmarksWidget.widget)

        self.applyCancelButtons = ui.ApplyCancelButtons(
            onApplyClick=self.finishRegistration,
            onCancelClick=self.cancelRegistration,
            applyTooltip="Finish registration",
            cancelTooltip="Cancel registration",
            applyText="Finish registration",
            cancelText="Cancel registration",
            enabled=True,
            applyObjectName="Finish Registration Button",
            cancelObjectName="Cancel Registration Button",
        )

        parametersFormLayout.addRow(self.applyCancelButtons)
        # Add vertical spacer
        self.layout.addStretch(1)

        # Connections
        self.landmarksWidget.connect("landmarkAdded()", self.onLandmarkAdded)
        self.landmarksWidget.connect("landmarkPicked(landmarkName)", self.onLandmarkPicked)
        self.landmarksWidget.connect("landmarkMoved(landmarkName)", self.onLandmarkMoved)
        self.landmarksWidget.connect("landmarkEndMoving(landmarkName)", self.onLandmarkEndMoving)
        self.landmarksWidget.connect("fiducialNodeRenamed(fiducialNodeId)", self.onFiducialNodeRenamed)
        self.interfaceFrame.enabled = False
        self.interfaceFrame.visible = False

    def finishRegistration(self):
        with ProgressBarProc() as progressBar:
            progressBar.nextStep(0, f"Finishing registration (applying transform)...")
            transformedVolume = self.selectedVolumes.get("Transformed")
            transformedVolume.HardenTransform()
            self.fixHardenTransformBug(transformedVolume)

            progressBar.nextStep(70, f"Finishing registration (equalizing spacing)...")
            self.logic.equalizeSpacing(transformedVolume, self.selectedVolumes["Fixed"])

            progressBar.nextStep(90, f"Finishing registration...")
            self.reset()

            progressBar.nextStep(100, f"Registration finished.")
        return transformedVolume

    def fixHardenTransformBug(self, volume):
        """
        Sometimes, the HardenTransform function will include extra (empty) dimensions in the image. This function discards them.
        """
        array = slicer.util.arrayFromVolume(volume)
        # Array in case the rules inside the for loop can't find anything meaningful
        newArray = array[0].reshape(1, *array[0].shape)
        firstDimensionShape = array.shape[0]
        if firstDimensionShape > 1:
            sliceLargestStandardDeviation = 0
            for i in range(firstDimensionShape):
                # If the is more variation in the slice data, it is probably the best slice to select
                sliceStandardDeviation = np.std(array[i])
                if sliceStandardDeviation > sliceLargestStandardDeviation:
                    newArray = array[i].reshape(1, *array[i].shape)
                    sliceLargestStandardDeviation = sliceStandardDeviation
        slicer.util.updateVolumeFromArray(volume, newArray)
        origin = volume.GetOrigin()
        volume.SetOrigin(origin[0], origin[1], 0)

    def cancelRegistration(self):
        if not self.registering:
            return

        transformedVolume = self.selectedVolumes.get("Transformed")
        self.reset()

        if transformedVolume is not None:
            slicer.mrmlScene.RemoveNode(transformedVolume)

    def enter(self) -> None:
        super().enter()
        self.previousLayout = slicer.app.layoutManager().layout
        if self.interfaceFrame.enabled:
            self.onLayout()

    def cleanup(self):
        super().cleanup()
        if self.logic is not None:
            self.logic.registrationState = None

        self.removeObservers()
        self.landmarksWidget.cleanUp()
        self.visualizationWidget.cleanUp()

    def _clearNodes(self) -> None:
        """Remove related nodes from the references and from the scene"""
        if self.transformNode:
            slicer.mrmlScene.RemoveNode(self.transformNode)
            self.transformNode = None

        fiducialNode = self.logic.getNodeByName("F", "vtkMRMLMarkupsFiducialNode")
        if fiducialNode is not None:
            slicer.mrmlScene.RemoveNode(fiducialNode)

        for key, volume in self.selectedVolumes.items():
            if volume is None:
                continue

            node = self.logic.getNodeByName(volume.GetName() + "-landmarks", "vtkMRMLMarkupsFiducialNode")
            if node is None:
                continue

            slicer.mrmlScene.RemoveNode(node)
            self.selectedVolumes[key] = None

    def reset(self) -> None:
        """Restore values to initial state"""
        # Reset the markup interaction with slice view
        self.removeObservers()
        self.registering = False

        interactionNode = slicer.mrmlScene.GetNodeByID("vtkMRMLInteractionNodeSingleton")
        if interactionNode:
            interactionNode.SwitchToViewTransformMode()

        slicer.util.setSliceViewerLayers(background=None, foreground=None, label=None)

        self.selectVolumesButton.show()
        self.interfaceFrame.enabled = False
        self.interfaceFrame.visible = False
        self.visualizationWidget.resetDisplaySettings()
        self._clearNodes()

        # self.imageToolsWidget.self().reset()  # Changes from Image Tools for registration are not permanent
        # self.imageToolsCollapsibleButton.collapsed = True
        if self.previousLayout:
            slicer.app.layoutManager().setLayout(self.previousLayout)

        self.selectedVolumes.clear()

    def setupDialog(self) -> None:
        if not self.volumeSelectDialog:
            self.volumeSelectDialog = qt.QDialog(self.parent)
            self.volumeSelectDialog.setModal(True)
            self.volumeSelectDialog.setMinimumSize(400, 180)
            self.volumeSelectDialog.setMaximumSize(800, 280)
            self.volumeSelectDialog.objectName = "Thin Section Registration Volume Select"
            self.volumeSelectDialog.setLayout(qt.QVBoxLayout())

            self.volumeSelectLabel = qt.QLabel()
            self.volumeSelectDialog.layout().addWidget(self.volumeSelectLabel)

            self.volumeSelectorFrame = qt.QFrame()
            self.volumeSelectorFrame.objectName = "VolumeSelectorFrame"
            self.volumeSelectorFrame.setLayout(qt.QFormLayout())
            self.volumeSelectorFrame.layout().setLabelAlignment(qt.Qt.AlignRight)
            self.volumeSelectorFrame.layout().setContentsMargins(0, 0, 0, 0)
            self.volumeSelectDialog.layout().addWidget(self.volumeSelectorFrame)
            self.volumeSelectorFrame.layout().addRow(" ", None)

            self.volumeDialogSelectors = {}
            for viewName in (
                "Fixed",
                "Moving",
            ):
                self.volumeDialogSelectors[viewName] = slicer.qMRMLNodeComboBox()
                self.volumeDialogSelectors[viewName].nodeTypes = (("vtkMRMLScalarVolumeNode"), "")
                self.volumeDialogSelectors[viewName].selectNodeUponCreation = False
                self.volumeDialogSelectors[viewName].addEnabled = False
                self.volumeDialogSelectors[viewName].removeEnabled = False
                self.volumeDialogSelectors[viewName].noneEnabled = False
                self.volumeDialogSelectors[viewName].showHidden = False
                self.volumeDialogSelectors[viewName].showChildNodeTypes = True
                self.volumeDialogSelectors[viewName].setMRMLScene(slicer.mrmlScene)
                self.volumeDialogSelectors[viewName].setToolTip("Pick the %s image." % viewName.lower())
                self.volumeDialogSelectors[viewName].objectName = f"{viewName} Volume Node Combo Box"
                self.volumeSelectorFrame.layout().addRow("%s image:" % viewName, self.volumeDialogSelectors[viewName])

            self.volumeSelectorFrame.layout().addRow(" ", None)

            self.volumeButtonFrame = qt.QFrame()
            self.volumeButtonFrame.objectName = "VolumeButtonFrame"
            self.volumeButtonFrame.setLayout(qt.QHBoxLayout())
            self.volumeSelectDialog.layout().addWidget(self.volumeButtonFrame)

            self.volumeDialogApplyCancelButtons = ui.ApplyCancelButtons(
                onApplyClick=self.onVolumeDialogApply,
                onCancelClick=lambda: self.volumeSelectDialog.hide(),
                applyTooltip="Use currently selected images.",
                cancelTooltip="Cancel current operation.",
                applyText="Apply",
                cancelText="Cancel",
                enabled=True,
                applyObjectName="Volume Dialog Apply",
                cancelObjectName="Volume Dialog Cancel",
                parent=self.volumeButtonFrame,
            )
            self.volumeButtonFrame.layout().addWidget(self.volumeDialogApplyCancelButtons)

        if self.volumeDialogSelectors["Fixed"].nodeCount() <= 1:
            slicer.util.warningDisplay("You need at least two different images to register.")
            return

        self.volumeDialogSelectors["Fixed"].setCurrentNodeIndex(0)
        self.volumeDialogSelectors["Moving"].setCurrentNodeIndex(1)

        self.volumeSelectLabel.setText("Select the images to register:")
        self.volumeSelectDialog.show()

    def onVolumeDialogApply(self) -> None:
        fixedVolume = self.volumeDialogSelectors["Fixed"].currentNode()
        movingVolume = self.volumeDialogSelectors["Moving"].currentNode()

        if not self.imageSizesCompatible(fixedVolume, movingVolume):
            if not slicer.util.confirmYesNoDisplay(
                "Are you sure you want to continue? The moving image has a size that is two times larger than the fixed image. "
                "The registration result may have problems. To avoid it, adjust the pixel size in one of the images to make them "
                "comparable in sizes, ou change the order fixed-moving."
            ):
                return

        if fixedVolume == movingVolume:
            slicer.util.errorDisplay(
                "You selected the same image for both fixed and moving images. Please select different images."
            )
            return

        if fixedVolume is None or movingVolume is None:
            return

        self.volumeSelectDialog.hide()
        self.selectVolumesButton.hide()
        self.selectedVolumes["Fixed"] = fixedVolume
        self.selectedVolumes["Moving"] = movingVolume
        self.fixedNodeLineEdit.text = fixedVolume.GetName()
        self.movingNodeLineEdit.text = movingVolume.GetName()
        self.transformNode = slicer.mrmlScene.AddNewNodeByClass(slicer.vtkMRMLTransformNode.__name__)
        volumesLogic = slicer.modules.volumes.logic()
        transformedName = "%s - Transformed" % movingVolume.GetName()
        transformed = volumesLogic.CloneVolume(slicer.mrmlScene, movingVolume, transformedName)
        self.selectedVolumes["Transformed"] = transformed
        transformed.SetAndObserveTransformNodeID(self.transformNode.GetID())
        self.transformedNodeLineEdit.text = transformed.GetName()
        self.onLayout()
        self.interfaceFrame.enabled = True
        self.interfaceFrame.visible = True

        volumeNodes = self.currentVolumeNodes()
        self.landmarksWidget.setVolumeNodes(volumeNodes)
        self.logic.hiddenFiducialVolumes = (transformed,)

        subjectHierarchyNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        itemParent = subjectHierarchyNode.GetItemParent(subjectHierarchyNode.GetItemByDataNode(movingVolume))
        subjectHierarchyNode.SetItemParent(subjectHierarchyNode.GetItemByDataNode(transformed), itemParent)

        segmentationNodes = slicer.util.getNodesByClass("vtkMRMLSegmentationDisplayNode")
        for node in segmentationNodes:
            node.SetVisibility(False)

        self.registering = True
        self.addObservers()

    def imageSizesCompatible(
        self, fixedImage: slicer.vtkMRMLScalarVolumeNode, movingImage: slicer.vtkMRMLScalarVolumeNode
    ) -> bool:
        boundsFixed = np.zeros(6)
        boundsMoving = np.zeros(6)
        fixedImage.GetBounds(boundsFixed)
        movingImage.GetBounds(boundsMoving)
        sidesFixed = [boundsFixed[i + 1] - boundsFixed[i] for i in [0, 2]]
        sidesMoving = [boundsMoving[i + 1] - boundsMoving[i] for i in [0, 2]]
        ratio = np.array(sidesMoving) / sidesFixed
        if np.max(ratio) > 2:
            return False
        return True

    def addObservers(self) -> None:
        """Observe the mrml scene for changes that we wish to respond to.
        scene observer:
         - whenever a new node is added, check if it was a new fiducial.
           if so, transform it into a landmark by creating a matching
           fiducial for other volumes
        fiducial obserers:
         - when fiducials are manipulated, perform (or schedule) an update
           to the currently active registration method.
        """
        self.observerTags.append(
            (
                slicer.mrmlScene,
                slicer.mrmlScene.AddObserver(
                    slicer.mrmlScene.NodeAddedEvent, self.landmarksWidget.requestNodeAddedUpdate
                ),
            )
        )
        self.observerTags.append(
            (
                slicer.mrmlScene,
                slicer.mrmlScene.AddObserver(
                    slicer.mrmlScene.NodeRemovedEvent, self.landmarksWidget.requestNodeAddedUpdate
                ),
            )
        )
        self.observerTags.append(
            (slicer.mrmlScene, slicer.mrmlScene.AddObserver(slicer.mrmlScene.NodeRemovedEvent, self._onNodeRemoved))
        )
        self.observerTags.append(
            (slicer.mrmlScene, slicer.mrmlScene.AddObserver(slicer.mrmlScene.StartCloseEvent, self._onCloseScene))
        )

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _onNodeRemoved(self, caller, event, node) -> None:
        """Handle node removed from scene event. If the removed node is related to the current process, then cancel the registration."""
        if not self.registering or not self.selectedVolumes:
            return

        fixedVolume = self.selectedVolumes.get("Fixed")
        movingVolume = self.selectedVolumes.get("Moving")
        transformedVolume = self.selectedVolumes.get("Transformed")

        if node not in [fixedVolume, movingVolume, transformedVolume, self.transformNode]:
            return

        self.cancelRegistration()

    def _onCloseScene(self, *args, **kwargs) -> None:
        """Handle node removed from scene event."""
        if not self.registering:
            return

        self.cancelRegistration()

    def removeObservers(self) -> None:
        """Remove observers and any other cleanup needed to
        disconnect from the scene"""
        self.removeInteractorObservers()
        for obj, tag in self.observerTags:
            obj.RemoveObserver(tag)
        self.observerTags = []

    def addInteractorObservers(self) -> None:
        """Add observers to the Slice interactors"""
        self.removeInteractorObservers()
        layoutManager = slicer.app.layoutManager()
        for sliceNodeName in self.sliceNodesByViewName.keys():
            sliceWidget = layoutManager.sliceWidget(sliceNodeName)
            sliceView = sliceWidget.sliceView()
            interactor = sliceView.interactorStyle().GetInteractor()
            tag = interactor.AddObserver(vtk.vtkCommand.MouseMoveEvent, self.processSliceEvents)
            self.interactorObserverTags.append((interactor, tag))

    def onFiducialNodeRenamed(self, fiducialNodeId: str) -> None:
        """Handle fiducial node rename event."""
        self.processSliceEvents(self, vtk.vtkCommand.MouseMoveEvent)

    def removeInteractorObservers(self) -> None:
        """Remove observers from the Slice interactors"""
        for obj, tag in self.interactorObserverTags:
            obj.RemoveObserver(tag)
        self.interactorObserverTags = []

    def registrationState(self) -> RegistrationLib.RegistrationState:
        """Return an instance of RegistrationState populated
        with current gui parameters"""
        state = RegistrationLib.RegistrationState()
        state.logic = self.logic
        state.fixed = self.selectedVolumes.get("Fixed")
        state.moving = self.selectedVolumes.get("Moving")
        state.transformed = self.selectedVolumes.get("Transformed")
        state.fixedFiducials = self.logic.volumeFiducialList(state.fixed)
        state.movingFiducials = self.logic.volumeFiducialList(state.moving)
        state.transformedFiducials = self.logic.volumeFiducialList(state.transformed)
        state.transform = self.transformNode
        state.currentLandmarkName = self.landmarksWidget.selectedLandmark

        return state

    def currentVolumeNodes(self) -> List[slicer.vtkMRMLScalarVolumeNode]:
        """List of currently selected volume nodes"""
        return self.selectedVolumes.values()

    def onLayout(self, layoutMode="Axial", volumesToShow=None) -> None:
        """When the layout is changed by the VisualizationWidget
        volumesToShow: list of the volumes to include, None means include all
        """
        volumeNodes = []
        activeViewNames = []
        for viewName in self.viewNames:
            volumeNode = self.selectedVolumes[viewName]
            if volumeNode and not (volumesToShow and viewName not in volumesToShow):
                volumeNodes.append(volumeNode)
                activeViewNames.append(viewName)
        import CompareVolumes

        compareLogic = CompareVolumes.CompareVolumesLogic()
        oneViewModes = (
            "Axial",
            "Sagittal",
            "Coronal",
        )
        orientationNames = {
            "Axial": "XY",
            "Sagittal": "YZ",
            "Coronal": "XZ",
        }
        if layoutMode in oneViewModes:
            self.sliceNodesByViewName = compareLogic.viewerPerVolume(
                volumeNodes, viewNames=activeViewNames, orientation=orientationNames[layoutMode]
            )
            compareLogic.zoom("Fit")
        elif layoutMode == "Axi/Sag/Cor":
            self.sliceNodesByViewName = compareLogic.viewersPerVolume(volumeNodes)
        self.overlayFixedOnTransformed()
        self.updateSliceNodesByVolumeID()
        self.onLandmarkPicked(self.landmarksWidget.selectedLandmark)

        self.__disable_sliceview_doubleclick_maximization()

    def overlayFixedOnTransformed(self) -> None:
        """If there are viewers showing the tranfsformed volume
        in the background, make the foreground volume be the fixed volume
        and set opacity to 0.5"""
        fixedNode = self.selectedVolumes.get("Fixed")
        transformedNode = self.selectedVolumes.get("Transformed")
        if transformedNode:
            compositeNodes = slicer.util.getNodesByClass("vtkMRMLSliceCompositeNode")
            for compositeNode in compositeNodes:
                if compositeNode.GetBackgroundVolumeID() == transformedNode.GetID():
                    compositeNode.SetForegroundVolumeID(fixedNode.GetID())
                    compositeNode.SetForegroundOpacity(0.5)

    def updateSliceNodesByVolumeID(self) -> None:
        """Build a mapping to a list of slice nodes
        node that are currently displaying a given volumeID"""
        compositeNodes = slicer.util.getNodesByClass("vtkMRMLSliceCompositeNode")
        self.sliceNodesByVolumeID = {}
        if self.sliceNodesByViewName:
            for sliceNode in self.sliceNodesByViewName.values():
                for compositeNode in compositeNodes:
                    if compositeNode.GetLayoutName() == sliceNode.GetLayoutName():
                        volumeID = compositeNode.GetBackgroundVolumeID()
                        if volumeID in self.sliceNodesByVolumeID:
                            self.sliceNodesByVolumeID[volumeID].append(sliceNode)
                        else:
                            self.sliceNodesByVolumeID[volumeID] = [
                                sliceNode,
                            ]

        self.addInteractorObservers()

    def processSliceEvents(self, caller=None, event=None) -> None:
        if caller is None:
            return

        layoutManager = slicer.app.layoutManager()
        compositeNode = None
        for sliceNodeName in self.sliceNodesByViewName.keys():
            sliceWidget = layoutManager.sliceWidget(sliceNodeName)
            sliceLogic = sliceWidget.sliceLogic()

            compositeNode = sliceLogic.GetSliceCompositeNode()
            break

        if compositeNode is None:
            return

        volumeID = compositeNode.GetBackgroundVolumeID()
        if volumeID is None:

            return

        volumeNode = slicer.util.getNode(volumeID)
        if volumeNode is None:
            return

        fiducialNode = self.logic.volumeFiducialList(volumeNode)
        if not fiducialNode:
            return

        fiducialsInLandmarks = False
        volumeNodes = self.currentVolumeNodes()
        landmarks = self.logic.landmarksForVolumes(volumeNodes)
        for landmarkName in landmarks:
            if fiducialsInLandmarks:
                break
            for tempList, index in landmarks[landmarkName]:
                if tempList == fiducialNode:
                    fiducialsInLandmarks = True
                    break

        if fiducialsInLandmarks:
            markupsLogic = slicer.modules.markups.logic()
            markupsLogic.SetActiveListID(fiducialNode)

    def restrictLandmarksToViews(self) -> None:
        """Set fiducials so they only show up in the view
        for the volume on which they were defined.
        Also turn off other fiducial lists, since leaving
        them visible can interfere with picking.
        Since multiple landmarks will be in the same lists, keep track of the
        lists that have been processed to avoid duplicated updates.
        """
        slicer.mrmlScene.StartState(slicer.mrmlScene.BatchProcessState)
        volumeNodes = self.currentVolumeNodes()
        if self.sliceNodesByViewName:
            landmarks = self.logic.landmarksForVolumes(volumeNodes)
            activeFiducialLists = []
            processedFiducialLists = []
            for landmarkName in landmarks:
                for fiducialList, index in landmarks[landmarkName]:
                    if fiducialList in processedFiducialLists:
                        continue
                    processedFiducialLists.append(fiducialList)
                    activeFiducialLists.append(fiducialList)
                    displayNode = fiducialList.GetDisplayNode()
                    displayNode.RemoveAllViewNodeIDs()
                    volumeNodeID = fiducialList.GetAttribute("AssociatedNodeID")
                    if volumeNodeID:
                        if volumeNodeID in self.sliceNodesByVolumeID:
                            for sliceNode in self.sliceNodesByVolumeID[volumeNodeID]:
                                displayNode.AddViewNodeID(sliceNode.GetID())
                                for hiddenVolume in self.logic.hiddenFiducialVolumes:
                                    if hiddenVolume and volumeNodeID == hiddenVolume.GetID():
                                        displayNode.SetVisibility(False)
            allFiducialLists = slicer.util.getNodesByClass("vtkMRMLMarkupsFiducialNode")
            for fiducialList in allFiducialLists:
                if fiducialList not in activeFiducialLists:
                    displayNode = fiducialList.GetDisplayNode()
                    if displayNode:
                        displayNode.SetVisibility(False)
                        displayNode.RemoveAllViewNodeIDs()
                        displayNode.AddViewNodeID("__invalid_view_id__")
        slicer.mrmlScene.EndState(slicer.mrmlScene.BatchProcessState)

    def onLocalRefineClicked(self) -> None:
        """Refine the selected landmark"""
        timing = True
        slicer.mrmlScene.StartState(slicer.mrmlScene.BatchProcessState)

        if self.landmarksWidget.selectedLandmark != None:
            if self.currentLocalRefinementInterface:
                state = self.registrationState()
                self.currentLocalRefinementInterface.refineLandmark(state)
            if timing:
                onLandmarkPickedStart = time.time()
            self.onLandmarkPicked(self.landmarksWidget.selectedLandmark)
            if timing:
                onLandmarkPickedEnd = time.time()
                logging.debug(
                    f"Time to update visualization: {str(onLandmarkPickedEnd - onLandmarkPickedStart)} seconds"
                )

        slicer.mrmlScene.EndState(slicer.mrmlScene.BatchProcessState)

    def onLandmarkAdded(self) -> None:
        """Landmark added event handler"""
        self.processSliceEvents(caller=self)

    def onLandmarkPicked(self, landmarkName) -> None:
        """Jump all slice views such that the selected landmark
        is visible"""
        if not self.landmarksWidget.movingView:
            # only change the fiducials if they are not being manipulated
            self.restrictLandmarksToViews()
        self.updateSliceNodesByVolumeID()
        volumeNodes = self.currentVolumeNodes()
        landmarksByName = self.logic.landmarksForVolumes(volumeNodes)
        if landmarkName in landmarksByName:
            for fiducialList, index in landmarksByName[landmarkName]:
                volumeNodeID = fiducialList.GetAttribute("AssociatedNodeID")
                if volumeNodeID in self.sliceNodesByVolumeID:
                    point = [
                        0,
                    ] * 3
                    fiducialList.GetNthControlPointPosition(index, point)
                    for sliceNode in self.sliceNodesByVolumeID[volumeNodeID]:
                        if sliceNode.GetLayoutName() != self.landmarksWidget.movingView:
                            sliceNode.JumpSliceByCentering(*point)

    def onLandmarkMoved(self, landmarkName) -> None:
        """Called when a landmark is moved (probably through
        manipulation of the widget in the slice view).
        This updates the active registration"""
        # self.onThinPlateApply()

    def onLandmarkEndMoving(self, landmarkName) -> None:
        """Called when a landmark is done being moved (e.g. when mouse button released)"""
        self.onThinPlateApply()

    def onThinPlateApply(self) -> None:
        """Call this whenever thin plate needs to be calculated"""
        state = self.registrationState()

        if state.fixed and state.moving and state.transformed:
            landmarks = state.logic.landmarksForVolumes((state.fixed, state.moving))
            self.logic.performThinPlateRegistration(state, landmarks)

    def __disable_sliceview_doubleclick_maximization(self) -> None:
        layoutManager = slicer.app.layoutManager()
        for sliceNodeName in self.sliceNodesByViewName.keys():
            sliceWidget = layoutManager.sliceWidget(sliceNodeName)
            sliceView = sliceWidget.sliceView()
            displayable_manager = sliceView.displayableManagerByClassName("vtkMRMLCrosshairDisplayableManager")
            slice_intersection_widget = displayable_manager.GetSliceIntersectionWidget()
            slice_intersection_widget.SetEventTranslation(
                slice_intersection_widget.WidgetStateIdle,
                vtk.vtkCommand.LeftButtonDoubleClickEvent,
                vtk.vtkEvent.NoModifier,
                vtk.vtkWidgetEvent.NoEvent,
            )


class ThinSectionRegistrationLogic(LTracePluginLogic):
    def __init__(self, parent):
        super().__init__(parent)
        self.linearMode = "Rigid"
        self.hiddenFiducialVolumes = ()
        self.cropLogic = None
        if hasattr(slicer.modules, "cropvolume"):
            self.cropLogic = slicer.modules.cropvolume.logic()

        self.thinPlateTransform = None

    def setFiducialNodeDisplay(self, fiducialNode: slicer.vtkMRMLMarkupsFiducialNode) -> None:
        displayNode = fiducialNode.GetDisplayNode()
        # TODO: pick appropriate defaults
        # 135,135,84
        displayNode.SetTextScale(3.0)
        displayNode.SetGlyphScale(3.0)
        displayNode.SetGlyphTypeFromString("StarBurst2D")
        displayNode.SetColor((1, 0, 153 / 255))
        displayNode.SetSelectedColor((1, 0, 153 / 255))
        # displayNode.GetAnnotationTextDisplayNode().SetColor((1,1,0))
        displayNode.SetVisibility(True)

    def addFiducial(self, name, position=(0, 0, 0), associatedNode=None) -> None:
        """Add an instance of a fiducial to the scene for a given
        volume node.  Creates a new list if needed.
        If list already has a fiducial with the given name, then
        set the position to the passed value.
        """
        aname = associatedNode.GetName() if associatedNode is not None else "None"
        markupsLogic = slicer.modules.markups.logic()
        originalActiveListID = markupsLogic.GetActiveListID()  # TODO: naming convention?
        slicer.mrmlScene.StartState(slicer.mrmlScene.BatchProcessState)
        fiducialNode = None

        # make the fiducial list if required
        if associatedNode:
            listName = associatedNode.GetName() + "-landmarks"
            fiducialNode = slicer.mrmlScene.GetFirstNodeByName(listName)

            if not fiducialNode:
                fiducialNodeNodeID = markupsLogic.AddNewFiducialNode(listName, slicer.mrmlScene)
                fiducialNode = slicer.mrmlScene.GetNodeByID(fiducialNodeNodeID)
                fiducialNode.SetMarkupLabelFormat("F-%d")

            if associatedNode:
                fiducialNode.SetAttribute("AssociatedNodeID", associatedNode.GetID())
            self.setFiducialNodeDisplay(fiducialNode)

        # make this active so that the fids will be added to it
        markupsLogic.SetActiveListID(fiducialNode)

        foundLandmarkFiducial = False
        fiducialSize = fiducialNode.GetNumberOfControlPoints()
        for fiducialIndex in range(fiducialSize):
            if fiducialNode.GetNthControlPointLabel(fiducialIndex) == name:
                fiducialNode.SetNthControlPointPosition(fiducialIndex, *position)
                foundLandmarkFiducial = True
                break

        if not foundLandmarkFiducial:
            if associatedNode:
                # clip point to min/max bounds of target volume
                rasBounds = [
                    0,
                ] * 6
                associatedNode.GetRASBounds(rasBounds)
                for i in range(3):
                    if position[i] < rasBounds[2 * i]:
                        position[i] = rasBounds[2 * i]
                    if position[i] > rasBounds[2 * i + 1]:
                        position[i] = rasBounds[2 * i + 1]
            fiducialNode.AddControlPoint(*position)
            fiducialIndex = fiducialNode.GetNumberOfControlPoints() - 1

        fiducialNode.SetNthControlPointLabel(fiducialIndex, name)
        fiducialNode.SetNthControlPointSelected(fiducialIndex, False)
        fiducialNode.SetNthControlPointLocked(fiducialIndex, False)

        originalActiveList = slicer.mrmlScene.GetNodeByID(originalActiveListID)
        if originalActiveList:
            markupsLogic.SetActiveListID(originalActiveList)
        slicer.mrmlScene.EndState(slicer.mrmlScene.BatchProcessState)

    def addLandmark(self, volumeNodes=[], position=(0, 0, 0), movingPosition=(0, 0, 0)) -> str:
        """Add a new landmark by adding correspondingly named
        fiducials to all the current volume nodes.
        Find a unique name for the landmark and place it at the origin.
        As a special case if the fiducial list corresponds to the
        moving volume in the current state, then assign the movingPosition
        (this way it can account for the current transform).
        """
        state = self.registrationState()
        landmarks = self.landmarksForVolumes(volumeNodes)
        index = 1

        currentLandmarksName = list(landmarks.keys())
        if len(currentLandmarksName) > 0:
            lastLandmarkName = currentLandmarksName[-1]
            match = re.findall(r"\d+", lastLandmarkName)
            if match:
                index = int(match[0]) + 1

        landmarkName = f"F-{index}"

        for volumeNode in volumeNodes:
            # if the volume is the moving on, map position through transform to world
            if volumeNode == state.moving:
                positionToAdd = movingPosition
            else:
                positionToAdd = position
            fiducial = self.addFiducial(landmarkName, position=positionToAdd, associatedNode=volumeNode)
        return landmarkName

    def removeLandmarkForVolumes(self, landmark, volumeNodes) -> None:
        """Remove the fiducial nodes from all the volumes."""
        slicer.mrmlScene.StartState(slicer.mrmlScene.BatchProcessState)
        landmarks = self.landmarksForVolumes(volumeNodes)
        if landmark in landmarks:
            for fiducialList, fiducialIndex in landmarks[landmark]:
                fiducialList.RemoveNthControlPoint(fiducialIndex)
        slicer.mrmlScene.EndState(slicer.mrmlScene.BatchProcessState)

    def volumeFiducialList(self, volumeNode) -> None:
        """return fiducial list node that is
        list associated with the given volume node"""
        if not volumeNode:
            return None
        listName = volumeNode.GetName() + "-landmarks"
        listNode = slicer.mrmlScene.GetFirstNodeByName(listName)
        if listNode:
            if listNode.GetAttribute("AssociatedNodeID") != volumeNode.GetID():
                self.setFiducialNodeDisplay(listNode)
                listNode.SetAttribute("AssociatedNodeID", volumeNode.GetID())
        return listNode

    def landmarksForVolumes(self, volumeNodes) -> None:
        """Return a dictionary of keyed by
        landmark name containing pairs (fiducialListNodes,index)
        Only fiducials that exist for all volumes are returned."""
        landmarksByName = {}
        for volumeNode in volumeNodes:
            listForVolume = self.volumeFiducialList(volumeNode)
            if listForVolume:
                fiducialSize = listForVolume.GetNumberOfControlPoints()
                for fiducialIndex in range(fiducialSize):
                    fiducialName = listForVolume.GetNthControlPointLabel(fiducialIndex)
                    if fiducialName in landmarksByName:
                        landmarksByName[fiducialName].append((listForVolume, fiducialIndex))
                    else:
                        landmarksByName[fiducialName] = [
                            (listForVolume, fiducialIndex),
                        ]
        for fiducialName in list(landmarksByName.keys()):
            if len(landmarksByName[fiducialName]) != len(volumeNodes):
                landmarksByName.__delitem__(fiducialName)
        return landmarksByName

    def ensureFiducialInListForVolume(self, volumeNode, landmarkName, landmarkPosition) -> Union[None, str]:
        """Make sure the fiducial list associated with the given
        volume node contains a fiducial named landmarkName and that it
        is associated with volumeNode.  If it does not have one, add one
        and put it at landmarkPosition.
        Returns landmarkName if a new one is created, otherwise none
        """
        fiducialList = self.volumeFiducialList(volumeNode)
        if not fiducialList:
            return None
        fiducialSize = fiducialList.GetNumberOfControlPoints()
        for fiducialIndex in range(fiducialSize):
            if fiducialList.GetNthControlPointLabel(fiducialIndex) == landmarkName:
                fiducialList.SetNthControlPointAssociatedNodeID(fiducialIndex, volumeNode.GetID())
                return None
        # if we got here, then there is no fiducial with this name so add one
        fiducialList.AddControlPoint(*landmarkPosition)
        fiducialIndex = fiducialList.GetNumberOfControlPoints() - 1
        fiducialList.SetNthControlPointLabel(fiducialIndex, landmarkName)
        fiducialList.SetNthControlPointSelected(fiducialIndex, False)
        fiducialList.SetNthControlPointLocked(fiducialIndex, False)
        return landmarkName

    def collectAssociatedFiducials(self, volumeNodes) -> str:
        """Look at each fiducial list in scene and find any fiducials associated
        with one of our volumes but not in in one of our lists.
        Add the fiducial as a landmark and delete it from the other list.
        Return the name of the last added landmark if it exists.
        """
        state = self.registrationState()
        addedLandmark = None
        volumeNodeIDs = []
        for volumeNode in volumeNodes:
            volumeNodeIDs.append(volumeNode.GetID())
        landmarksByName = self.landmarksForVolumes(volumeNodes)
        fiducialListsInScene = slicer.util.getNodesByClass("vtkMRMLMarkupsFiducialNode")
        landmarkFiducialLists = []
        for landmarkName in landmarksByName.keys():
            for fiducialList, index in landmarksByName[landmarkName]:
                if fiducialList not in landmarkFiducialLists:
                    landmarkFiducialLists.append(fiducialList)
        listIndexToRemove = []  # remove back to front after identifying them
        for fiducialList in fiducialListsInScene:
            if fiducialList not in landmarkFiducialLists:
                # this is not one of our fiducial lists, so look for fiducials
                # associated with one of our volumes
                fiducialSize = fiducialList.GetNumberOfControlPoints()
                for fiducialIndex in range(fiducialSize):
                    status = fiducialList.GetNthControlPointPositionStatus(fiducialIndex)
                    if status != fiducialList.PositionDefined:
                        continue

                    associatedID = fiducialList.GetNthControlPointAssociatedNodeID(fiducialIndex)
                    if associatedID in volumeNodeIDs:
                        # found one, so add it as a landmark
                        landmarkPosition = fiducialList.GetNthControlPointPositionVector(fiducialIndex)
                        volumeNode = slicer.mrmlScene.GetNodeByID(associatedID)
                        # if new fiducial is associated with moving volume,
                        # then map the position back to where it would have been
                        # if it were not transformed, if not, then calculate where
                        # the point would be on the moving volume
                        movingPosition = [
                            0.0,
                        ] * 3
                        volumeTransformNode = state.transformed.GetParentTransformNode()
                        volumeTransform = vtk.vtkGeneralTransform()
                        if volumeTransformNode:
                            if volumeNode == state.moving:
                                # in this case, moving stays and other point moves
                                volumeTransformNode.GetTransformToWorld(volumeTransform)
                                movingPosition[:] = landmarkPosition
                                volumeTransform.TransformPoint(movingPosition, landmarkPosition)
                            else:
                                # in this case, landmark stays and moving point moves
                                volumeTransformNode.GetTransformFromWorld(volumeTransform)
                                volumeTransform.TransformPoint(landmarkPosition, movingPosition)
                        addedLandmark = self.addLandmark(volumeNodes, landmarkPosition, movingPosition)
                        listIndexToRemove.insert(0, (fiducialList, fiducialIndex))

        for fiducialList, fiducialIndex in listIndexToRemove:
            fiducialList.RemoveNthControlPoint(fiducialIndex)

        return addedLandmark

    def landmarksFromFiducials(self, volumeNodes) -> str:
        """Look through all fiducials in the scene and make sure they
        are in a fiducial list that is associated with the same
        volume node.  If they are in the wrong list fix the node id, and make a new
        duplicate fiducial in the correct list.
        This can be used when responding to new fiducials added to the scene.
        Returns the most recently added landmark (or None).
        """
        slicer.mrmlScene.StartState(slicer.mrmlScene.BatchProcessState)
        addedLandmark = None
        for volumeNode in volumeNodes:
            fiducialList = self.volumeFiducialList(volumeNode)
            if not fiducialList:
                continue

            fiducialSize = fiducialList.GetNumberOfControlPoints()
            for fiducialIndex in range(fiducialSize):
                status = fiducialList.GetNthControlPointPositionStatus(fiducialIndex)
                if status != fiducialList.PositionDefined:
                    continue

                fiducialAssociatedVolumeID = fiducialList.GetNthControlPointAssociatedNodeID(fiducialIndex)
                landmarkName = fiducialList.GetNthControlPointLabel(fiducialIndex)
                landmarkPosition = fiducialList.GetNthControlPointPositionVector(fiducialIndex)
                if fiducialAssociatedVolumeID != volumeNode.GetID():
                    # fiducial was placed on a viewer associated with the non-active list, so change it
                    fiducialList.SetNthControlPointAssociatedNodeID(fiducialIndex, volumeNode.GetID())
                # now make sure all other lists have a corresponding fiducial (same name)
                for otherVolumeNode in volumeNodes:
                    if otherVolumeNode != volumeNode:
                        addedFiducial = self.ensureFiducialInListForVolume(
                            otherVolumeNode, landmarkName, landmarkPosition
                        )
                        if addedFiducial:
                            addedLandmark = addedFiducial
        slicer.mrmlScene.EndState(slicer.mrmlScene.BatchProcessState)
        return addedLandmark

    def vtkPointsForVolumes(self, volumeNodes, fiducialNodes) -> Dict:
        """Return dictionary of vtkPoints instances containing the fiducial points
        associated with current landmarks, indexed by volume"""
        points = {}
        for volumeNode in volumeNodes:
            points[volumeNode] = vtk.vtkPoints()
        sameNumberOfNodes = len(volumeNodes) == len(fiducialNodes)
        noNoneNodes = None not in volumeNodes and None not in fiducialNodes
        if sameNumberOfNodes and noNoneNodes:
            fiducialCount = fiducialNodes[0].GetNumberOfControlPoints()
            for fiducialNode in fiducialNodes:
                if fiducialCount != fiducialNode.GetNumberOfControlPoints():
                    raise Exception("Fiducial counts don't match {0}".format(fiducialCount))
            point = [
                0,
            ] * 3
            indices = range(fiducialCount)
            for fiducials, volumeNode in zip(fiducialNodes, volumeNodes):
                for index in indices:
                    fiducials.GetNthControlPointPosition(index, point)
                    points[volumeNode].InsertNextPoint(point)
        return points

    #
    #
    # Thin Plate Plugin code
    #

    def performThinPlateRegistration(self, state, landmarks):
        """Perform the thin plate transform using the vtkThinPlateSplineTransform class"""

        volumeNodes = (state.fixed, state.moving)
        fiducialNodes = (state.fixedFiducials, state.movingFiducials)
        points = state.logic.vtkPointsForVolumes(volumeNodes, fiducialNodes)

        # since this is a resample transform, source is the fixed (resampling target) space
        # and moving is the target space
        if not self.thinPlateTransform:
            self.thinPlateTransform = vtk.vtkThinPlateSplineTransform()
        self.thinPlateTransform.SetSourceLandmarks(points[state.moving])
        self.thinPlateTransform.SetTargetLandmarks(points[state.fixed])
        self.thinPlateTransform.Update()

        if points[state.moving].GetNumberOfPoints() != points[state.fixed].GetNumberOfPoints():
            logging.debug("Error: fixed and moving fiducials must have same number of points")

        state.transform.SetAndObserveTransformToParent(self.thinPlateTransform)

    def getNodeByName(self, name, className=None) -> Union[None, slicer.vtkMRMLNode]:
        """get the first MRML node that has the given name
        - use a regular expression to match names post-pended with addition characters
        - optionally specify a classname that must match
        """
        nodes = slicer.util.getNodes(name + "*")
        for nodeName in nodes.keys():
            if not className:
                return nodes[nodeName]  # return the first one
            else:
                if nodes[nodeName].IsA(className):
                    return nodes[nodeName]
        return None

    def equalizeSpacing(self, firstVolume, secondVolume) -> None:
        """
        Equalizes the spacings of the volumes, by setting the low resolution volume spacing (bigger spacing) to the
        spacing of the high resolution volume and applying a resize. If the low resolution volume is a label map,
        then the resize interpolation order is set to zero and anti-aliasing is disabled, to avoid creating new labels on process.
        """
        # if there are significant differences in spacings
        if not np.all(np.isclose(firstVolume.GetSpacing(), secondVolume.GetSpacing())):

            if Counter(np.array(firstVolume.GetSpacing()) < np.array(secondVolume.GetSpacing())).most_common(1)[0][0]:
                highResolutionVolume = firstVolume
                lowResolutionVolume = secondVolume
            else:
                highResolutionVolume = secondVolume
                lowResolutionVolume = firstVolume

            array = slicer.util.arrayFromVolume(lowResolutionVolume)
            spacingFactors = (np.array(lowResolutionVolume.GetSpacing()) / highResolutionVolume.GetSpacing())[::-1]
            # we need these selections [1:3] because sometimes we have a vector volume, and sometimes a scalar volume
            imageSize = getRoundedInteger(np.array(array.shape[1:3]) * spacingFactors[1:3])
            newArraySize = np.array(array.shape)
            newArraySize[1:3] = imageSize

            # when resizing a labelmap we set order=0 (nearest-neighbor) and disable anti-aliasing
            if type(lowResolutionVolume) is slicer.vtkMRMLLabelMapVolumeNode:
                resizedArray = resize(array, newArraySize, preserve_range=True, anti_aliasing=False, order=0).astype(
                    array.dtype
                )
            else:
                resizedArray = resize(array, newArraySize, preserve_range=True).astype(array.dtype)
            slicer.util.updateVolumeFromArray(lowResolutionVolume, resizedArray)
            lowResolutionVolume.SetSpacing(highResolutionVolume.GetSpacing())
