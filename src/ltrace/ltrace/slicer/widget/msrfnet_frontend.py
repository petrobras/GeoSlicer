import qt, ctk, slicer


from ltrace.slicer.ui import hierarchyVolumeInput


def FormSection(title="", flat=False, collapsed=False, align=qt.Qt.AlignLeft, children: list = None):
    widget = ctk.ctkCollapsibleButton()
    widget.text = title
    widget.flat = flat
    widget.collapsed = collapsed
    layout = qt.QFormLayout(widget)

    layout.setLabelAlignment(qt.Qt.AlignLeft)

    if children:
        for child in children:
            if not isinstance(child, (tuple, list)) or len(child) == 0:
                raise TypeError("FormSection expects a list/tuple as child.")

            if len(child) >= 2:
                name, row_widget = child[:2]
                layout.addRow(name, row_widget)
            else:
                layout.addRow(child[0])

    return widget


def ComboBox(objectName=None, items=None, tooltip=None, onIndexChange=None):
    widget = qt.QComboBox()
    if objectName:
        widget.setObjectName(objectName)

    if items:
        for item in items:
            widget.addItem(item)

    if tooltip:
        widget.setToolTip(tooltip)

    if onIndexChange:
        widget.connect("currentIndexChanged(int)", onIndexChange)

    return widget


class MSRFNetFrontend(qt.QWidget):

    EMPTY = " ... "

    def __init__(self, parent=None, align=qt.Qt.AlignLeft) -> None:
        super().__init__(parent)

        layout = qt.QVBoxLayout(self)

        self.alignment = align

        self.amplitudeImageInputWidget = hierarchyVolumeInput(
            nodeTypes=["vtkMRMLScalarVolumeNode"],
            onChange=self.onAmplitudeImageNodeChanged,
            tooltip="Select the amplitude image.",
        )

        self.classOfInterestComboBox = ComboBox(
            "classOfInterestComboBox",
            items=["Breakouts", "Fraturas", "Vugs"],
            tooltip="Select a class to be segmented.",
        )

        self.outputPrefixLineEdit = qt.QLineEdit()

        self.segmentButton = qt.QPushButton("Segment")
        self.segmentButton.setFixedHeight(40)

        sections = [
            FormSection("Inputs", children=[("Image: ", self.amplitudeImageInputWidget)], align=self.alignment),
            FormSection(
                "Parameters",
                children=[
                    ("Class of Interest: ", self.classOfInterestComboBox),
                    ("Depth range (m): ", self.buildDepthRange()),
                    ("Model: ", self.buildModelPicker()),
                ],
                align=self.alignment,
            ),
            FormSection("Output", children=[("Output prefix: ", self.outputPrefixLineEdit), (self.segmentButton,)]),
        ]

        for sec in sections:
            layout.addWidget(sec)

        layout.addStretch(1)

    def segmentButtonClicked(self, callback):
        self.segmentButton.clicked.connect(callback)

    def onAmplitudeImageNodeChanged(self, itemId):
        amplitudeImage = self.amplitudeImageInputWidget.subjectHierarchy.GetItemDataNode(itemId)
        if amplitudeImage:
            outputPrefix = amplitudeImage.GetName()
        else:
            outputPrefix = ""
        self.outputPrefixLineEdit.setText(outputPrefix)

    def buildDepthRange(self):
        locale = qt.QLocale()
        locale.setNumberOptions(qt.QLocale.RejectGroupSeparator)

        self.initialDepthLineEdit = qt.QLineEdit()
        self.initialDepthValidator = qt.QIntValidator(0, 10000)
        self.initialDepthValidator.setLocale(locale)
        self.initialDepthLineEdit.setValidator(self.initialDepthValidator)
        self.initialDepthLineEdit.setToolTip("Initial depth to set a range to which perform the segmentation.")

        self.finalDepthLineEdit = qt.QLineEdit()
        self.finalDepthValidator = qt.QIntValidator(0, 10000)
        self.finalDepthValidator.setLocale(locale)
        self.finalDepthLineEdit.setValidator(self.finalDepthValidator)
        self.finalDepthLineEdit.setToolTip("Final depth to set a range to which perform the segmentation.")

        widget = qt.QFrame()
        depthRangeHBoxLayout = qt.QVBoxLayout(widget)
        depthRangeHBoxLayout.addWidget(self.initialDepthLineEdit)
        depthRangeHBoxLayout.addWidget(self.finalDepthLineEdit)

        return widget

    def buildModelPicker(self):
        widget = qt.QFrame()
        layout = qt.QHBoxLayout(widget)

        self.modelLabel = qt.QLabel(self.EMPTY)

        selectBtn = qt.QPushButton("Select")
        selectBtn.clicked.connect(self.displayModelPicker)
        selectBtn.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)

        layout.addWidget(self.modelLabel)
        layout.addWidget(selectBtn)

        return widget
