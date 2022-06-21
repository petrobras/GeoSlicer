from __future__ import absolute_import

import qt, slicer, os
from RegistrationLib import pqWidget


class LandmarksWidget(pqWidget):
    """
    A "QWidget"-like class that manages a set of landmarks
    that are pairs of fiducials
    """

    def __init__(self, logic):
        super(LandmarksWidget, self).__init__()
        self.logic = logic
        self.volumeNodes = []
        self.selectedLandmark = None  # a landmark name
        self.landmarkGroupBox = None  # a QGroupBox
        self.labels = {}  # the current buttons in the group box
        self.pendingUpdate = False  # update on new scene nodes
        self.updatingFiducials = False  # don't update while update in process
        self.observerTags = []  # for monitoring fiducial changes
        self.movingView = None  # layoutName of slice node where fiducial is being moved

        self.widget = qt.QWidget()
        self.layout = qt.QFormLayout(self.widget)
        self.landmarkArrayHolder = qt.QWidget()
        self.landmarkArrayHolder.setLayout(qt.QVBoxLayout())
        self.layout.addRow(self.landmarkArrayHolder)
        self.updateLandmarkArray()

    def setVolumeNodes(self, volumeNodes):
        """Set up the widget to reflect the currently selected
        volume nodes.  This triggers an update of the landmarks"""
        self.volumeNodes = volumeNodes
        self.updateLandmarkArray()

    def iconActive(self, active):
        pngFile = "icon_Active.png" if active == True else "icon_Inactive.png"
        iconPath = os.path.join(os.path.dirname(__file__), pngFile)
        if os.path.exists(iconPath):
            return qt.QIcon(iconPath)
        return qt.QIcon()

    def updateLandmarkArray(self):
        """Rebuild the list of buttons based on current landmarks"""
        # reset the widget
        if self.landmarkGroupBox:
            self.landmarkGroupBox.setParent(None)
        self.landmarkGroupBox = qt.QGroupBox("Landmarks")
        self.landmarkGroupBox.setLayout(qt.QFormLayout())
        # add the action buttons at the top
        actionButtons = qt.QHBoxLayout()
        # add button - http://www.clipartbest.com/clipart-jTxpEM8Bc
        self.addButton = qt.QPushButton("Add")
        self.addButton.setIcon(
            qt.QIcon(
                os.path.join(
                    os.path.dirname(slicer.modules.landmarkregistration.path), "Resources/Icons/", "icon_Add.png"
                )
            )
        )
        self.addButton.connect("clicked()", self.addLandmark)
        actionButtons.addWidget(self.addButton)
        self.renameButton = qt.QPushButton("Rename")
        self.renameButton.connect("clicked()", self.renameLandmark)
        self.renameButton.enabled = False
        actionButtons.addWidget(self.renameButton)
        self.landmarkGroupBox.layout().addRow(actionButtons)

        # for now, hide
        self.renameButton.hide()

        # make a button for each current landmark
        self.labels = {}
        landmarks = self.logic.landmarksForVolumes(self.volumeNodes)
        keys = sorted(landmarks.keys())
        for landmarkName in keys:
            row = qt.QWidget()
            rowLayout = qt.QHBoxLayout()
            rowLayout.setMargin(0)

            label = qt.QLabel(landmarkName)
            rowLayout.addWidget(label, 8)

            # active button - https://thenounproject.com/term/crosshair/4434/
            activeButton = qt.QPushButton()
            activeButton.setIcon(self.iconActive(False))
            activeButton.connect("clicked()", lambda l=landmarkName: self.pickLandmark(l))
            rowLayout.addWidget(activeButton, 1)

            if landmarkName == self.selectedLandmark:
                label.setStyleSheet("QWidget{font-weight: bold}")
                activeButton.setIcon(self.iconActive(True))

            # remove button - http://findicons.com/icon/158288/trash_recyclebin_empty_closed_w
            removeButton = qt.QPushButton()
            removeButton.setIcon(
                qt.QIcon(
                    os.path.join(
                        os.path.dirname(slicer.modules.landmarkregistration.path), "Resources/Icons/", "icon_Trash.png"
                    )
                )
            )
            removeButton.connect("clicked()", lambda l=landmarkName: self.removeLandmark(l))
            rowLayout.addWidget(removeButton, 1)

            row.setLayout(rowLayout)

            self.landmarkGroupBox.layout().addRow(row)
            self.labels[landmarkName] = [label, activeButton]
        self.landmarkArrayHolder.layout().addWidget(self.landmarkGroupBox)

        # observe manipulation of the landmarks
        self.addLandmarkObservers()

    def addLandmarkObservers(self):
        """Add observers to all fiducialLists in scene
        so we will know when new markups are added
        """
        self.removeLandmarkObservers()
        for fiducialList in slicer.util.getNodes("vtkMRMLMarkupsFiducialNode*").values():
            tag = fiducialList.AddObserver(
                fiducialList.PointModifiedEvent, lambda caller, event: self.onFiducialMoved(caller)
            )
            self.observerTags.append((fiducialList, tag))
            tag = fiducialList.AddObserver(
                fiducialList.PointEndInteractionEvent, lambda caller, event: self.onFiducialEndMoving(caller)
            )
            self.observerTags.append((fiducialList, tag))
            tag = fiducialList.AddObserver(fiducialList.PointPositionDefinedEvent, self.requestNodeAddedUpdate)
            self.observerTags.append((fiducialList, tag))
            tag = fiducialList.AddObserver(fiducialList.PointPositionUndefinedEvent, self.requestNodeAddedUpdate)
            self.observerTags.append((fiducialList, tag))

    def onFiducialMoved(self, fiducialList):
        """Callback when fiducialList's point has been changed.
        Check the Markups.State attribute to see if it is being
        actively moved and if so, skip the picked method."""
        self.movingView = fiducialList.GetAttribute("Markups.MovingInSliceView")
        movingIndexAttribute = fiducialList.GetAttribute("Markups.MovingMarkupIndex")
        if self.movingView and movingIndexAttribute:
            movingIndex = int(movingIndexAttribute)
            if movingIndex < fiducialList.GetNumberOfControlPoints():
                landmarkName = fiducialList.GetNthMarkupLabel(movingIndex)
                self.pickLandmark(landmarkName, clearMovingView=False)
                self.emit("landmarkMoved(landmarkName)", (landmarkName,))

    def onFiducialEndMoving(self, fiducialList):
        """Callback when fiducialList's point is done moving."""
        movingIndexAttribute = fiducialList.GetAttribute("Markups.MovingMarkupIndex")
        if movingIndexAttribute:
            movingIndex = int(movingIndexAttribute)
            landmarkName = fiducialList.GetNthMarkupLabel(movingIndex)
            self.pickLandmark(landmarkName, clearMovingView=False)
            self.emit("landmarkEndMoving(landmarkName)", (landmarkName,))

    def removeLandmarkObservers(self):
        """Remove any existing observers"""
        for obj, tag in self.observerTags:
            obj.RemoveObserver(tag)
        self.observerTags = []

    def pickLandmark(self, landmarkName, clearMovingView=True):
        """Hightlight the named landmark button and emit a 'signal'"""
        for key in self.labels.keys():
            self.labels[key][0].setStyleSheet("QWidget{font-weight: normal}")
            self.labels[key][1].setIcon(self.iconActive(False))
        try:
            self.labels[landmarkName][0].setStyleSheet("QWidget{font-weight: bold}")
            self.labels[landmarkName][1].setIcon(self.iconActive(True))
        except KeyError:
            pass
        self.selectedLandmark = landmarkName
        self.renameButton.enabled = True
        if clearMovingView:
            self.movingView = None
        self.emit("landmarkPicked(landmarkName)", (landmarkName,))

    def addLandmark(self):
        """Enable markup place mode so fiducial can be added.
        When the node is added it will be incorporated into the
        registration system as a landmark.
        """
        applicationLogic = slicer.app.applicationLogic()
        selectionNode = applicationLogic.GetSelectionNode()

        selectionNode.SetReferenceActivePlaceNodeClassName("vtkMRMLMarkupsFiducialNode")
        interactionNode = applicationLogic.GetInteractionNode()
        interactionNode.SwitchToSinglePlaceMode()

    def removeLandmark(self, landmarkName):
        self.logic.removeLandmarkForVolumes(landmarkName, self.volumeNodes)
        if landmarkName == self.selectedLandmark:
            self.selectedLandmark = None
        self.updateLandmarkArray()

    def renameLandmark(self):
        landmarks = self.logic.landmarksForVolumes(self.volumeNodes)
        if self.selectedLandmark in landmarks:
            newName = qt.QInputDialog.getText(
                slicer.util.mainWindow(), "Rename Landmark", "New name for landmark '%s'?" % self.selectedLandmark
            )
            if newName != "":
                for fiducialList, index in landmarks[self.selectedLandmark]:
                    fiducialList.SetNthFiducialLabel(newName)
                self.selectedLandmark = newName
                self.updateLandmarkArray()
                self.pickLandmark(newName)

    def requestNodeAddedUpdate(self, caller, event):
        """Start a SingleShot timer that will check the fiducials
        in the scene and turn them into landmarks if needed"""
        if not self.pendingUpdate:
            self.pendingUpdate = True
            qt.QTimer.singleShot(0, self.wrappedNodeAddedUpdate)

    def wrappedNodeAddedUpdate(self):
        try:
            self.nodeAddedUpdate()
        except Exception as e:
            import traceback

            traceback.print_exc()
            qt.QMessageBox.warning(
                slicer.util.mainWindow(),
                "Node Added",
                "Exception!\n\n" + str(e) + "\n\nSee Python Console for Stack Trace",
            )

    def nodeAddedUpdate(self):
        """Perform the update of any new fiducials.
        First collect from any fiducial lists not associated with one of our
        volumes (like when the process first gets started) and then check for
        new fiducials added to one of our lists.
        End result should be one fiducial per list with identical names and
        correctly assigned associated node ids.
        Most recently created new fiducial is picked as active landmark.
        """
        if self.updatingFiducials:
            return
        slicer.mrmlScene.StartState(slicer.mrmlScene.BatchProcessState)
        self.updatingFiducials = True
        addedAssociatedLandmark = self.logic.collectAssociatedFiducials(self.volumeNodes)
        addedLandmark = self.logic.landmarksFromFiducials(self.volumeNodes)
        if not addedLandmark:
            addedLandmark = addedAssociatedLandmark
        if addedLandmark:
            self.pickLandmark(addedLandmark)
        self.addLandmarkObservers()
        self.updateLandmarkArray()
        slicer.mrmlScene.EndState(slicer.mrmlScene.BatchProcessState)
        self.pendingUpdate = False
        self.updatingFiducials = False
