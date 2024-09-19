import qSlicerSegmentationsEditorEffectsPythonQt
import qSlicerSegmentationsModuleWidgetsPythonQt
import slicer
import qt
import distinctipy


def createSimplifiedSegmentEditor():
    # TODO: For some reason the instance() function cannot be called as a class function although it's static
    factory = qSlicerSegmentationsEditorEffectsPythonQt.qSlicerSegmentEditorEffectFactory()
    effectFactorySingleton = factory.instance()

    #
    # Segment editor widget
    #
    editor = qSlicerSegmentationsModuleWidgetsPythonQt.qMRMLSegmentEditorWidget()
    editor.setMaximumNumberOfUndoStates(10)
    # Set parameter node first so that the automatic selections made when the scene is set are saved
    # Note: Commented because preload make this unnecessary
    ### self.selectParameterNode()
    editor.setMRMLScene(slicer.mrmlScene)

    # Observe editor effect registrations to make sure that any effects that are registered
    # later will show up in the segment editor widget. For example, if Segment Editor is set
    # as startup module, additional effects are registered after the segment editor widget is created.
    # Increasing buttons width to improve visibility
    specifyGeometryButton = editor.findChild(qt.QToolButton, "SpecifyGeometryButton")
    specifyGeometryButton.setVisible(False)

    sliceRotateWarningButton = editor.findChild(qt.QToolButton, "SliceRotateWarningButton")
    sliceRotateWarningButton.setFixedWidth(100)

    sourceVolumeNodeLabel = editor.findChild(qt.QLabel, "SourceVolumeNodeLabel")
    sourceVolumeNodeLabel.visible = False

    segmentationNodeLabel = editor.findChild(qt.QLabel, "SegmentationNodeLabel")
    segmentationNodeLabel.visible = False

    sourceVolumeNodeComboBox = editor.findChild(slicer.qMRMLNodeComboBox, "SourceVolumeNodeComboBox")
    sourceVolumeNodeComboBox.visible = False

    segmentationNodeComboBox = editor.findChild(slicer.qMRMLNodeComboBox, "SegmentationNodeComboBox")
    segmentationNodeComboBox.visible = False

    helpWidget = editor.findChild(qt.QWidget, "EffectHelpBrowser")
    helpWidget.visible = False

    def onAddSegmentButton():
        segmentation = segmentationNodeComboBox.currentNode().GetSegmentation()
        nSegments = segmentation.GetNumberOfSegments()

        existentColors = []
        for i in range(nSegments):
            segmentID = segmentation.GetNthSegmentID(i)
            existentColors.append(segmentation.GetSegment(segmentID).GetColor())

        segmentID = segmentation.GetNthSegmentID(nSegments - 1)
        newColor = distinctipy.get_colors(1, existentColors)[0]
        segmentation.GetSegment(segmentID).SetColor(newColor)

    addSegmentButton = editor.findChild(qt.QPushButton, "AddSegmentButton")
    addSegmentButton.clicked.connect(onAddSegmentButton)

    switchToSegmentationsButton = editor.findChild(qt.QToolButton, "SwitchToSegmentationsButton")
    switchToSegmentationsButton.setVisible(False)

    tableView = editor.findChild(qt.QTableView, "SegmentsTable")
    tableView.setColumnHidden(0, True)
    editor.findChild(qt.QPushButton, "AddSegmentButton").visible = False
    editor.findChild(qt.QPushButton, "RemoveSegmentButton").visible = False
    editor.findChild(slicer.qMRMLSegmentationShow3DButton, "Show3DButton").visible = False

    return editor, effectFactorySingleton, sourceVolumeNodeComboBox, segmentationNodeComboBox


def onSegmentEditorEnter(editor, tag):
    """Runs whenever the module is reopened"""
    if editor.turnOffLightboxes():
        slicer.util.warningDisplay(
            "Segment Editor is not compatible with slice viewers in light box mode. Views are being reset.",
            windowTitle="Segment Editor",
        )

    # Allow switching between effects and selected segment using keyboard shortcuts
    editor.installKeyboardShortcuts()

    # Set parameter set node if absent
    segmentEditorNode = slicer.mrmlScene.GetSingletonNode(tag, "vtkMRMLSegmentEditorNode")
    if segmentEditorNode is None:
        segmentEditorNode = slicer.mrmlScene.CreateNodeByClass("vtkMRMLSegmentEditorNode")
        segmentEditorNode.UnRegister(None)
        segmentEditorNode.SetSingletonTag(tag)
        segmentEditorNode = slicer.mrmlScene.AddNode(segmentEditorNode)
    editor.setMRMLSegmentEditorNode(segmentEditorNode)

    editor.updateWidgetFromMRML()


def onSegmentEditorExit(editor):
    editor.setActiveEffect(None)
    editor.uninstallKeyboardShortcuts()
    editor.removeViewObservations()
