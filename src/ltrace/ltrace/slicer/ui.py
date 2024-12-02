import textwrap
from functools import reduce
from pathlib import Path

import ctk
import numpy as np
import qt
import slicer
from natsort import natsorted

from ltrace.slicer.helpers import getSegmentList, createLabelmapInput
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar


def volumeInput(onChange=None, hasNone=False, nodeTypes=None, onActivation=None):
    inputSelector = slicer.qMRMLNodeComboBox()
    inputSelector.nodeTypes = nodeTypes if nodeTypes else ["vtkMRMLScalarVolumeNode"]
    inputSelector.baseName = "OutputEccentricityAdjusted"
    inputSelector.selectNodeUponCreation = True
    inputSelector.addEnabled = False
    inputSelector.editEnabled = False
    inputSelector.removeEnabled = False
    inputSelector.renameEnabled = False
    inputSelector.noneEnabled = hasNone
    inputSelector.showHidden = False
    inputSelector.showChildNodeTypes = True
    inputSelector.setMRMLScene(slicer.mrmlScene)
    if onChange:
        inputSelector.connect("currentNodeChanged(vtkMRMLNode*)", onChange)
    if onActivation:
        inputSelector.connect("nodeActivated(vtkMRMLNode*)", onActivation)
    return inputSelector


def volumeOutput(onChange=None, hasNone=False, nodeTypes=None, onActivation=None):
    inputSelector = slicer.qMRMLNodeComboBox()
    inputSelector.nodeTypes = nodeTypes if nodeTypes else ["vtkMRMLScalarVolumeNode"]
    inputSelector.baseName = "OutputEccentricityAdjusted"
    inputSelector.selectNodeUponCreation = True
    inputSelector.addEnabled = True
    inputSelector.editEnabled = True
    inputSelector.removeEnabled = True
    inputSelector.renameEnabled = True
    inputSelector.noneEnabled = hasNone
    inputSelector.showHidden = False
    inputSelector.showChildNodeTypes = True
    inputSelector.setMRMLScene(slicer.mrmlScene)
    if onChange:
        inputSelector.connect("currentNodeChanged(vtkMRMLNode*)", onChange)
    if onActivation:
        inputSelector.connect("nodeActivated(vtkMRMLNode*)", onActivation)
    return inputSelector


def hierarchyVolumeInput(
    onChange=None,
    hasNone=False,
    nodeTypes=["vtkMRMLScalarVolumeNode", "vtkMRMLLabelMapVolumeNode"],
    onActivation=None,
    tooltip=None,
    defaultText=None,
    showSegments=False,
    allowFolders=False,
):
    from ltrace.slicer.widget.hierarchy_volume_input import HierarchyVolumeInput

    widget = HierarchyVolumeInput(hasNone, nodeTypes, defaultText, allowFolders)
    if tooltip:
        widget.setToolTip(tooltip)

    if not showSegments:
        widget.selectorWidget.setExcludeItemAttributeNamesFilter(("segmentID",))

    if onChange is not None:
        widget.currentItemChanged.connect(onChange)

    if onActivation is not None:  # Not implemented
        pass

    return widget


def filteredNodeComboBox(nodeTypes=["vtkMRMLScalarVolumeNode", "vtkMRMLLabelMapVolumeNode"], tooltip=None):
    from ltrace.slicer.widget.filtered_node_combo_box import FilteredNodeComboBox

    widget = FilteredNodeComboBox(nodeTypes=nodeTypes)
    if tooltip:
        widget.setToolTip(tooltip)

    return widget


def numericInput(value=100.0, onChange=None):
    widget = qt.QDoubleSpinBox()
    widget.setRange(-999999, 9999999)
    widget.setDecimals(2)
    widget.singleStep = 0.1
    widget.value = value
    if onChange:
        widget.connect("valueChanged(double)", onChange)

    edit = widget.findChild(qt.QLineEdit)
    validator = qt.QDoubleValidator(edit)
    locale = qt.QLocale()
    locale.setNumberOptions(qt.QLocale.RejectGroupSeparator)
    validator.setLocale(locale)
    edit.setValidator(validator)

    return widget


def textInput(value="", onChange=None):
    widget = qt.QLineEdit()
    widget.text = value
    widget.setReadOnly(True)

    if onChange:
        widget.connect("textChanged(const QString &)", onChange)
    return widget


class SegmentInput(qt.QComboBox):
    """Combobox for choosing a label/segment from a given labelmap/segmentation input."""

    def __init__(self):
        super().__init__()
        self.nodes = None

    def set_input(self, nodes, segments=None):
        self.nodes = nodes
        self.clear()

        names = ["None"]
        input_ = self.nodes[0]
        if input_:
            # segments can be passed by parameter if they have already been computed
            if segments is None:
                segments = getSegmentList(input_)

            segments = {k: v for k, v in segments.items() if isinstance(k, int)}
            names += [segment["name"] for _, segment in sorted(segments.items())]
        self.addItems(names)

    def binary_array(self) -> np.ndarray:
        """Returns binary array of selected label/segment."""
        input_, soi, reference = self.nodes
        if self.currentIndex == 0:
            return None
        segments = [self.currentIndex]
        labelmap, _ = createLabelmapInput(
            input_, "tmp_segment_input", segments=segments, referenceNode=reference, soiNode=soi
        )
        array = slicer.util.arrayFromVolume(labelmap)
        slicer.mrmlScene.RemoveNode(labelmap)
        return array


def InputVolumeFormWidget(parent, types, label="", tooltip="", onSelect=None, **kwargs):
    inputSelector = slicer.qMRMLNodeComboBox()
    inputSelector.nodeTypes = types
    inputSelector.selectNodeUponCreation = kwargs.get("autoSelectEnabled", False)
    inputSelector.addEnabled = kwargs.get("addEnabled", False)
    inputSelector.removeEnabled = kwargs.get("removeEnabled", False)
    inputSelector.noneEnabled = kwargs.get("noneEnabled", False)
    inputSelector.renameEnabled = kwargs.get("renameEnabled", False)
    inputSelector.showHidden = False
    inputSelector.showChildNodeTypes = False
    inputSelector.setMRMLScene(slicer.mrmlScene)
    inputSelector.setToolTip(tooltip)
    if onSelect:
        inputSelector.connect("currentNodeChanged(vtkMRMLNode*)", onSelect)
    actions = kwargs.get("actions", [])

    if len(actions) > 0:
        hbox = qt.QHBoxLayout()
        hbox.addWidget(inputSelector)
        for action in actions:
            hbox.addWidget(action)
        widget = hbox
    else:
        widget = inputSelector

    if parent is not None:
        parent.addRow(label, widget)

    return inputSelector


def SliderFormWidget(parent, label="", step=0.1, minimum=0, maximum=1, value=None, tooltip=""):
    sliderWidget = ctk.ctkSliderWidget()
    sliderWidget.singleStep = step
    sliderWidget.minimum = minimum
    sliderWidget.maximum = maximum
    sliderWidget.value = value if value is not None else 0.5 * (maximum - minimum)
    sliderWidget.setToolTip(tooltip)
    parent.addRow(label, sliderWidget)
    return sliderWidget


class SearchableSelectorWidget:
    def __init__(
        self,
        parent,
        filterLabel="Search for: ",
        nameLabel="Name: ",
        onChange=None,
        onSelect=None,
        contentSource=None,
        value="name",
    ):
        self.formLayout = qt.QFormLayout(parent)

        # filter search
        searchBox = ctk.ctkSearchBox()
        self.formLayout.addRow(filterLabel, searchBox)

        # filter selector
        self.modelSelector = qt.QComboBox()
        self.formLayout.addRow(nameLabel, self.modelSelector)

        self.onChange = onChange or (lambda v: None)
        self.onSelect = onSelect or (lambda v: None)

        self.valueKey = value
        self.contentSource = contentSource or (lambda: set([]))

        # connections
        searchBox.connect("textChanged(QString)", self._onChange)
        self.modelSelector.connect("currentIndexChanged(int)", self._onSelect)

        # update items
        self._updateItems()

    def _updateItems(self, filter=None):
        self.items = self.contentSource()

        if filter:
            # split text on whitespace of and string search
            searchTextList = filter.split()
            for idx, item in enumerate(self.items):
                lname = item[self.valueKey].lower()
                # require all elements in list, to add to select. case insensitive
                if reduce(
                    lambda x, y: x and (lname.find(y.lower()) != -1),
                    [True] + searchTextList,
                ):
                    self.modelSelector.addItem(item[self.valueKey], idx)
        else:
            for i, item in enumerate(self.items):
                self.modelSelector.addItem(item[self.valueKey], i)

    def _onChange(self, value: str):
        # clean up combobox to show search results only
        self.modelSelector.clear()

        self._updateItems(filter=value)
        self.onChange(value)

    def _onSelect(self, value: int):
        self.onSelect(self.items[value])


def ButtonWidget(onClick=None, text="", tooltip="", enabled=True, object_name=None):
    button = qt.QPushButton(text)
    if object_name:
        button.objectName = object_name
    button.toolTip = tooltip
    button.enabled = enabled
    if callable(onClick):
        button.clicked.connect(onClick)
    return button


def ApplyButton(onClick=None, tooltip="", text="Apply", enabled=True, object_name=None):
    btn = ButtonWidget(onClick, text, tooltip, enabled, object_name)
    btn.setStyleSheet("QPushButton {font-size: 11px; font-weight: bold; padding: 8px; margin: 0px}")
    btn.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Minimum)
    return btn


class ApplyCancelButtons(qt.QWidget):
    def __init__(
        self,
        onApplyClick=None,
        onCancelClick=None,
        applyTooltip="Apply",
        cancelTooltip="Cancel",
        applyText="Apply",
        cancelText="Cancel",
        enabled=True,
        applyObjectName="Apply Button",
        cancelObjectName="Cancel Button",
        parent=None,
    ):
        super().__init__(parent)

        # Create Apply button
        self.applyBtn = ButtonWidget(onApplyClick, applyText, applyTooltip, enabled, applyObjectName)
        self.applyBtn.setProperty("class", "actionButtonBackground")
        self.applyBtn.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Minimum)

        # Create Cancel button
        self.cancelBtn = ButtonWidget(onCancelClick, cancelText, cancelTooltip, enabled, cancelObjectName)
        self.cancelBtn.setStyleSheet("QPushButton {font-size: 11px; padding: 8px; margin: 0px}")
        self.cancelBtn.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Minimum)

        # Create layout and add buttons
        self.buttonLayout = qt.QHBoxLayout(self)
        self.buttonLayout.addWidget(self.applyBtn)
        self.buttonLayout.addWidget(self.cancelBtn)

    # Method to enable/disable both buttons at once
    def setEnabled(self, enabled):
        self.applyBtn.setEnabled(enabled)
        self.cancelBtn.setEnabled(enabled)

    @property
    def text(self):
        return f"ApplyCancelButtons"


def CheckBoxLayout(text="", tooltip="", onToggle=None):
    hbox = qt.QHBoxLayout()

    checkbox = qt.QCheckBox()
    checkbox.checked = 0
    checkbox.setToolTip(tooltip)
    checkbox.connect("toggled ( bool )", lambda v: onToggle(checkbox, v))
    hbox.addWidget(checkbox)

    label = qt.QLabel(text)
    label.setToolTip(tooltip)
    hbox.addWidget(label)

    return hbox


def CheckBoxWidget(tooltip="", onToggle=None, checked=False):
    checkbox = qt.QCheckBox()
    checkbox.checked = checked
    checkbox.setToolTip(tooltip)
    checkbox.connect("toggled ( bool )", lambda v: onToggle(checkbox, v))
    return checkbox


def Row(widgets):
    widget = qt.QWidget()
    layout = qt.QHBoxLayout(widget)
    for w in widgets:
        layout.addWidget(w)
    layout.setAlignment(qt.Qt.AlignLeft)
    layout.setContentsMargins(0, 0, 0, 0)
    widget.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)
    return widget


def Col(widgets):
    widget = qt.QWidget()
    layout = qt.QVBoxLayout(widget)
    for w in widgets:
        layout.addWidget(w)
    layout.setAlignment(qt.Qt.AlignTop)
    layout.setContentsMargins(0, 0, 0, 0)
    widget.setSizePolicy(qt.QSizePolicy.Minimum, qt.QSizePolicy.Minimum)
    return widget


def createEntryModuleButton(text, moduleName):
    pushButton = qt.QPushButton(text)
    # pushButton.setStyleSheet("QPushButton {font-weight: bold; padding: 10px;}")
    pushButton.setSizePolicy(qt.QSizePolicy.Preferred, qt.QSizePolicy.Preferred)
    pushButton.clicked.connect(lambda: slicer.util.selectModule(moduleName))
    return pushButton


class CheckButton(qt.QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._checked = False

        self.stylesheet = (
            "font-weight: bold; "
            "padding-left: 10px;padding-right: 12px;"
            "padding-top: 7px; padding-bottom: 7px;"
            "font-size: 12px;"
        )

        self.setStyleSheet(self.stylesheet)

    def is_checked(self):
        return self._checked

    def setChecked(self, value):
        if self._checked == value:
            return
        self._checked = value
        if self._checked:
            self.setStyleSheet(f"{self.stylesheet}background-color: rgb(255, 85, 0);")
        else:
            self.setStyleSheet(self.stylesheet)


class CLIProgressBarDialog:
    def __init__(self, **kwargs):
        self.dialog = qt.QDialog()

        self.dialog.setWindowTitle(kwargs.get("title", ""))
        # icon = qt.QIcon(Customizer.GEOSLICER_LOGO_ICON_PATH)
        # self.dialog.setWindowIcon(icon)

        self.progressBar = LocalProgressBar()
        self.progressBar.progressBar.progressVisibility = slicer.qSlicerCLIProgressBar.AlwaysVisible

        QBtn = qt.QDialogButtonBox.Cancel

        self.buttonBox = qt.QDialogButtonBox(QBtn)
        self.buttonBox.rejected.connect(kwargs.get("cancel", None))

        self.layout = qt.QVBoxLayout()
        self.layout.addWidget(self.progressBar)
        self.layout.addWidget(self.buttonBox)
        self.dialog.setLayout(self.layout)

    def show(self):
        self.buttonBox.show()
        self.dialog.exec_()

    def cancel(self):
        self.dialog.reject()

    def close(self):
        self.dialog.close()

    def done(self):
        # self.dialog.setWindowFlags(self.flags)
        self.buttonBox.hide()
        self.dialog.show()

    def listen(self, cliNode):
        self.progressBar.setCommandLineModuleNode(cliNode)


class StackedSelector(qt.QWidget):
    currentWidgetChanged = qt.Signal()

    def __init__(self, text="", *args, **kwargs):
        super().__init__(*args, **kwargs)

        layout = qt.QFormLayout(self)

        self.previousIndex = 0

        self.selector = qt.QComboBox()
        self.content = qt.QStackedWidget()

        layout.addRow(text, self.selector)
        layout.addRow(self.content)

        self.selector.currentIndexChanged.connect(self.onIndexChanged)

    def addWidget(self, widget):
        self.selector.addItem(widget.DISPLAY_NAME, widget.METHOD)
        self.content.addWidget(widget)

    def widget(self, index):
        return self.content.widget(index)

    def currentWidget(self):
        return self.content.currentWidget()

    def count(self):
        return self.selector.count

    def onIndexChanged(self, index):
        previousWidget = self.content.widget(self.previousIndex)
        if previousWidget:
            previousWidget.shrink()

        self.content.setCurrentIndex(index)
        try:
            self.content.currentWidget().select()
        except:
            pass
        finally:
            self.previousIndex = self.content.currentIndex
        self.currentWidgetChanged.emit()

    # def setToolTip(self, text):
    #     self.selector.setToolTip(text)


class FeedbackNumberParam(qt.QWidget):
    def __init__(self, parent=None, hint="", minimum=0, maximum=99999, value=0, decimals=3, onChange=None):
        super().__init__(parent)

        step = 1 * (10**-decimals)
        self.valueInput = numberParam((minimum, maximum), value=value, step=step, decimals=decimals)
        # valueInput.setValidator(qt.QDoubleValidator(minimum, maximum, decimals))
        self.valueInput.setToolTip(hint)
        # valueInput.setText(value)

        valuePixelLabel = qt.QLabel("")

        layout = qt.QHBoxLayout(self)
        layout.addWidget(self.valueInput)
        layout.addWidget(valuePixelLabel)
        layout.setContentsMargins(0, 0, 0, 0)  # Set the zero padding

        if onChange:
            self.valueInput.textChanged.connect(lambda v, w=valuePixelLabel: onChange(v, w))

    def value(self):
        return self.valueInput.value

    def setValue(self, value):
        self.valueInput.value = value


class BaseLayout:
    TAG = "EmptyScreen"
    UID = 1010
    LAYOUT = textwrap.dedent(
        f"""
        <layout type="vertical">
            <item>
                <{TAG}></{TAG}>
            </item>
        </layout>
    """
    )

    @classmethod
    def register(cls):
        viewFactory = slicer.qSlicerSingletonViewFactory()
        viewFactory.setTagName(cls.TAG)
        if slicer.app.layoutManager() is not None:
            slicer.app.layoutManager().registerViewFactory(viewFactory)

        container = cls.build(viewFactory)

        layoutManager = slicer.app.layoutManager()
        layoutManager.layoutLogic().GetLayoutNode().AddLayoutDescription(cls.UID, cls.LAYOUT)

        return container

    @classmethod
    def build(cls, factory):
        viewWidget = qt.QWidget()
        viewWidget.setAutoFillBackground(True)
        factory.setWidget(viewWidget)
        viewLayout = qt.QVBoxLayout()

        viewWidget.setLayout(viewLayout)

        return viewWidget

    @classmethod
    def show(cls):
        slicer.app.layoutManager().setLayout(cls.UID)


class DirOrFileWidget(qt.QWidget):
    # User has selected a path, either by typing or by file dialog
    pathSelected = qt.Signal(str)

    def __init__(self, settingKey, dirCaption=None, fileCaption=None, filters=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.lastPath = ""
        self.settingKey = settingKey
        self.dirCaption = dirCaption
        self.fileCaption = fileCaption
        self.filters = filters

        self.chooseDirButton = qt.QPushButton("Choose folder…")
        self.chooseFileButton = qt.QPushButton("Choose file…")
        self.pathLineEdit = qt.QLineEdit()
        self.pathLineEdit.setObjectName("Path Line")

        layout = qt.QVBoxLayout(self)
        buttonLayout = qt.QHBoxLayout()
        buttonLayout.addWidget(self.chooseDirButton)
        buttonLayout.addWidget(self.chooseFileButton)

        self.chooseDirButton.setIcon(self.style().standardIcon(qt.QStyle.SP_DirIcon))
        self.chooseFileButton.setIcon(self.style().standardIcon(qt.QStyle.SP_FileIcon))

        layout.addLayout(buttonLayout)
        layout.addWidget(self.pathLineEdit)

        self.pathLineEdit.editingFinished.connect(self.onEditingFinished)
        self.setStyleSheet(
            """
            QPushButton {
                height: 30px;
            }
        """
        )
        self.chooseDirButton.clicked.connect(self.onChooseDir)
        self.chooseFileButton.clicked.connect(self.onChooseFile)
        self.setContentsMargins(0, 0, 0, 0)
        layout.setContentsMargins(0, 0, 0, 0)

        self.path = self.getDefaultPath()

    def getDefaultPath(self):
        return slicer.app.settings().value(self.settingKey, "")

    def _updateLastPath(self):
        newPath = self.pathLineEdit.text
        if Path(newPath).exists():
            slicer.app.settings().setValue(self.settingKey, newPath)
        if newPath != self.lastPath:
            self.pathSelected.emit(newPath)
        self.lastPath = newPath

    @property
    def path(self):
        return self.pathLineEdit.text

    @path.setter
    def path(self, path):
        self.pathLineEdit.setText(path)
        self._updateLastPath()

    def onEditingFinished(self):
        self._updateLastPath()

    def onChooseDir(self):
        directory = self.getDefaultPath()
        path = qt.QFileDialog.getExistingDirectory(self, self.dirCaption, directory)
        if not path:
            return
        self.path = path

    def onChooseFile(self):
        directory = self.getDefaultPath()
        if self.filters:
            path = qt.QFileDialog.getOpenFileName(self, self.fileCaption, directory, self.filters)
        else:
            path = qt.QFileDialog.getOpenFileName(self, self.fileCaption, directory)
        if not path:
            return
        self.path = path


class MultiplePathsWidget(qt.QWidget):
    def __init__(
        self,
        initialFileDialogDirectory,
        addCallback,
        removeCallback=None,
        directoriesOnly=False,
        singleDirectory=True,
        fileExtensions="",
        *args,
        **kwargs,
    ):
        super().__init__(self, *args, **kwargs)
        self.initialFileDialogDirectory = initialFileDialogDirectory
        self.addCallback = addCallback
        self.removeCallback = removeCallback
        self.directoriesOnly = directoriesOnly
        self.singleDirectory = singleDirectory
        self.fileExtensions = fileExtensions
        self.setup()

    def setup(self):
        layout = qt.QFormLayout(self)
        layout.setLabelAlignment(qt.Qt.AlignRight)
        layout.setContentsMargins(0, 0, 0, 0)

        buttonsHBoxLayout = qt.QHBoxLayout()
        self.addDirectoriesButton = qt.QPushButton("Add directories")
        self.addDirectoriesButton.setFixedHeight(40)
        buttonsHBoxLayout.addWidget(self.addDirectoriesButton)
        self.addDirectoriesButton.clicked.connect(lambda: self.add(True))
        if not self.directoriesOnly:
            self.addFilesButton = qt.QPushButton("Add files")
            self.addFilesButton.setFixedHeight(40)
            buttonsHBoxLayout.addWidget(self.addFilesButton)
            self.addFilesButton.clicked.connect(lambda: self.add(False))
        self.removePathButton = qt.QPushButton("Remove")
        self.removePathButton.setFixedHeight(40)
        buttonsHBoxLayout.addWidget(self.removePathButton)
        self.removePathButton.clicked.connect(self.remove)
        layout.addRow(buttonsHBoxLayout)

        self.directoryListView = slicer.qSlicerDirectoryListView()
        layout.addRow(self.directoryListView)

    def remove(self):
        self.directoryListView.removeSelectedDirectories()
        if self.removeCallback is not None:
            self.removeCallback()

    def add(self, directories=False):
        if directories:
            fileDialog = qt.QFileDialog(self, "Select directories", self.initialFileDialogDirectory)
            fileDialog.setFileMode(qt.QFileDialog.DirectoryOnly)

            if not self.singleDirectory:
                # Don't use the native dialog, because it doesn't allow to select multiple directories
                fileDialog.setOption(qt.QFileDialog.DontUseNativeDialog, True)
        else:
            fileDialog = qt.QFileDialog(
                self,
                "Select files",
                self.initialFileDialogDirectory,
                "Image files (*" + " *".join(self.fileExtensions) + ")",
            )
            fileDialog.setFileMode(qt.QFileDialog.ExistingFiles)
        listView = fileDialog.findChild(qt.QListView, "listView")
        if listView:
            listView.setSelectionMode(qt.QAbstractItemView.ExtendedSelection)
        treeView = fileDialog.findChild(qt.QTreeView)
        if treeView:
            treeView.setSelectionMode(qt.QAbstractItemView.ExtendedSelection)
        if fileDialog.exec():
            paths = fileDialog.selectedFiles()
            # Save the last path used
            lastPath = Path(paths[-1])
            if lastPath.is_file():
                lastPathString = str(lastPath.parent)
            else:
                lastPathString = str(lastPath)
            self.initialFileDialogDirectory = lastPathString
            for path in natsorted(paths):
                if len(path):
                    self.directoryListView.addDirectory(path)
            self.addCallback(lastPathString)

        fileDialog.delete()


def numberParam(vrange, value=0.1, step=0.1, decimals=1):
    param = qt.QDoubleSpinBox()
    param.setRange(*vrange)
    param.setDecimals(decimals)
    param.singleStep = step
    param.value = value

    edit = param.findChild(qt.QLineEdit)
    validator = qt.QDoubleValidator(edit)
    locale = qt.QLocale()
    locale.setNumberOptions(qt.QLocale.RejectGroupSeparator)
    validator.setLocale(locale)
    edit.setValidator(validator)

    return param


def numberParamInt(vrange=(0, 0), value=0, step=1):
    param = qt.QSpinBox()
    param.setRange(*vrange)
    param.singleStep = step
    param.value = value

    edit = param.findChild(qt.QLineEdit)
    validator = qt.QDoubleValidator(edit)
    locale = qt.QLocale()
    locale.setNumberOptions(qt.QLocale.RejectGroupSeparator)
    validator.setLocale(locale)
    edit.setValidator(validator)

    return param


def floatParam(value=0.0):
    widget = qt.QLineEdit()
    locale = qt.QLocale()
    locale.setNumberOptions(qt.QLocale.RejectGroupSeparator)
    validator = qt.QDoubleValidator(widget)
    validator.setLocale(locale)
    widget.setValidator(validator)
    widget.text = str(value)
    return widget


class FloatInput(qt.QLineEdit):
    def __init__(self, parent=None, value=0.0):
        super().__init__(parent)

        locale = qt.QLocale()
        locale.setNumberOptions(qt.QLocale.RejectGroupSeparator)
        validator = qt.QDoubleValidator(self)
        validator.setLocale(locale)
        self.setValidator(validator)
        self.text = str(value)

    @property
    def value(self):
        return float(self.text)

    @value.setter
    def value(self, value):
        self.text = str(value)

    def setValue(self, value):
        self.value = value

    def setRange(self, minimum, maximum, decimals=None):
        if decimals is None:
            self.validator().setRange(minimum, maximum)
        else:
            self.validator().setRange(minimum, maximum, decimals)


def intParam(value=0):
    widget = qt.QLineEdit()
    locale = qt.QLocale()
    locale.setNumberOptions(qt.QLocale.RejectGroupSeparator)
    validator = qt.QIntValidator(widget)
    validator.setLocale(locale)
    widget.setValidator(validator)
    widget.text = str(value)
    return widget


def fixedRangeNumberParam(minimum, maximum, value=0):
    slider = qt.QSlider()
    slider.singleStep = 1
    slider.pageStep = 1
    slider.minimum = minimum
    slider.maximum = maximum
    slider.setOrientation(qt.Qt.Horizontal)
    slider.setValue(value)
    return slider


class TemporaryStatusLabel(qt.QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setVisible(False)
        self.setAlignment(qt.Qt.AlignRight)

        self.timer = qt.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self.__hide)

    def setStatus(self, message, color="green"):
        self.setStyleSheet(f"font-weight: bold; color: {color}")
        self.setText(message)
        self.setVisible(True)
        self.timer.start()

    def setVisibleInterval(self, visibleIntervalMs):
        self.timer.setInterval(visibleIntervalMs)

    def __hide(self):
        self.setVisible(False)


class ClickableLabel(qt.QLabel):
    clicked = qt.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

    def mousePressEvent(self, event):
        self.clicked.emit()
