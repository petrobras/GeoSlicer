import time
import qt, ctk, slicer

from .table_viewer_widget import ImageLogTableViewer
from .import_logic import (
    DLISLoader,
    LASLoader,
    CSVLoader,
    blank_fn,
    get_loader,
    LoaderError,
    ImageLogImportError,
)
from ltrace.image.optimized_transforms import DEFAULT_NULL_VALUES
from ltrace.slicer import ui, widgets
from ltrace.utils.ProgressBarProc import ProgressBarProc
from ltrace.slicer import helpers


class WellLogImportWidget(qt.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(qt.QVBoxLayout())
        self.appFolder = None
        self.dataLoader = None

        self.loadClicked = blank_fn

        self.tableView = ImageLogTableViewer()
        self.tableView.setMinimumHeight(500)
        self.tableView.loadClicked = self.onLoadClicked

        self.layout().addWidget(self.buildFileInputWidget())
        self.layout().addWidget(self.buildWellName())
        self.layout().addWidget(self.tableView)

        self.layout().addStretch()

    def setAppFolder(self, folderName):
        self.appFolder = folderName

    def currentPath(self):
        return self.ioFileInputLineEdit.currentPath

    def buildWellName(self):
        ioWellnameInputFrame = qt.QFrame()
        ioWellnameInputGroup = qt.QHBoxLayout(ioWellnameInputFrame)
        self.wellNameInput = qt.QLineEdit()
        self.wellNameInput.setObjectName("Well Name Input")
        self.wellNameInput.setReadOnly(True)
        ioWellnameInputGroup.addWidget(qt.QLabel("Well name:"))
        ioWellnameInputGroup.addWidget(self.wellNameInput)
        return ioWellnameInputFrame

    def buildFileInputWidget(self):
        ioFileInputFrame = qt.QFrame()

        formLayout = qt.QFormLayout(ioFileInputFrame)
        self.ioFileInputLineEdit = ctk.ctkPathLineEdit()
        self.ioFileInputLineEdit.setObjectName("File Input")
        self.ioFileInputLineEdit.filters = ctk.ctkPathLineEdit.Files | ctk.ctkPathLineEdit.Readable
        self.ioFileInputLineEdit.settingKey = "ioFileInputMicrotom"
        # Needs to be initialized blank to allow loading the file metadata
        self.ioFileInputLineEdit.setCurrentPath("")
        self.ioFileInputLineEdit.findChild("QLineEdit").enabled = False

        nullsLayout = qt.QHBoxLayout()
        self.nullValuesListText = qt.QLineEdit()
        self.nullValuesListText.setObjectName("Null Values List Text")
        self.nullValuesListText.text = str(DEFAULT_NULL_VALUES)[1:-1]
        self.nullValuesListText.textChanged.connect(lambda: self.setNullValuesFieldState(widgets.InputState.OK))
        nullsLayout.addWidget(self.nullValuesListText)

        self.resetNullValuesListButton = qt.QPushButton("Reset list")
        self.resetNullValuesListButton.setObjectName("Reset Null Values List Button")
        self.resetNullValuesListButton.clicked.connect(
            lambda: self.nullValuesListText.setText(str(DEFAULT_NULL_VALUES)[1:-1])
        )
        nullsLayout.addWidget(self.resetNullValuesListButton)

        self.wellDiameter = ui.floatParam("")
        self.wellDiameter.setObjectName("Well Diameter Input")
        self.wellDiameter.textChanged.connect(lambda: self.setWellDiameterFieldState(widgets.InputState.OK))

        wellDiameterLabel = qt.QLabel("Well diameter (inches):")

        formLayout.addRow("Well log file:", self.ioFileInputLineEdit)
        formLayout.addRow("Null values list:", nullsLayout)
        formLayout.addRow(wellDiameterLabel, self.wellDiameter)

        def onPathChanged(filepath):
            with ProgressBarProc() as progressBar:
                progressBar.nextStep(5, "Loading metadata...")

                progressBar.nextStep(80, "Setting context variables...")
                nullvalues = set(self.nullValuesListText.text.split(","))

                if self.nullValuesListText.text.split(",")[0]:
                    nullvalues = set(map(float, nullvalues))
                else:  # an empty nullValuesListText will give us a 1-element set ([""]). Reinitializing the set here
                    nullvalues = set()

                self.dataLoader = get_loader(filepath, nullvalues)

                nullvalues.union(self.dataLoader.null_value)

                if len(nullvalues):
                    self.nullValuesListText.text = str(nullvalues)[1:-1]
                else:
                    self.nullValuesListText.text = ""

                try:
                    progressBar.nextStep(90, "Showing metadata...")
                    well_name, metadata = self.dataLoader.load_metadata()
                    self.wellNameInput.text = well_name
                    if well_name is None:
                        return
                    self.tableView.setDatabase(metadata)
                except LoaderError as e:
                    slicer.util.infoDisplay(str(e))
                    self.ioFileInputLineEdit.setCurrentPath("")
                    progressBar.nextStep(100, "Error loading metadata.")
                    return

                progressBar.nextStep(100, "Finished loading metadata.")

            wellDiameterApplies = True
            try:
                wellDiameterApplies = self.dataLoader.loaded_as_image
            except AttributeError:  # no loaded_as_image
                pass
            self.wellDiameter.setVisible(wellDiameterApplies)
            wellDiameterLabel.setVisible(wellDiameterApplies)
            if not wellDiameterApplies:
                self.wellDiameter.setText("0")
            else:
                self.wellDiameter.setText("")

        self.ioFileInputLineEdit.connect("currentPathChanged(QString)", onPathChanged)

        return ioFileInputFrame

    def onLoadClicked(self, mnemonic_and_files):
        if not self.wellDiameter.text and self.wellDiameter.visible:
            self.setWellDiameterFieldState(widgets.InputState.MISSING)
            return

        if not self.nullValuesListText.text and self.nullValuesListText.visible:
            self.setNullValuesFieldState(widgets.InputState.MISSING)
            return

        with ProgressBarProc() as progressBar:

            def progressCallback(progressLabel, progressValue):
                percent = round((progressValue - 1) * 100 / len(mnemonic_and_files))
                progressBar.nextStep(percent, f"Loading Files... {progressLabel}")
                slicer.app.processEvents()

            try:
                curves = self.dataLoader.load_data(self.ioFileInputLineEdit.currentPath, mnemonic_and_files)

                helpers.save_path(self.ioFileInputLineEdit)

                nullvalues = set(self.nullValuesListText.text.split(","))
                nullvalues = set(map(float, nullvalues))

                well_diameter = float(self.wellDiameter.text) * 25.4  # inches to mm
                well_name = self.wellNameInput.text

                itemIDs = self.dataLoader.load_volumes(
                    curves,
                    stepCallback=progressCallback,
                    appFolder=self.appFolder,
                    nullValue=nullvalues,
                    well_diameter_mm=well_diameter,
                    well_name=well_name,
                )

                self.loadClicked(itemIDs)
                progressBar.nextStep(100, f"Finished Loading Files.")
                time.sleep(0.5)

                numSelectedCurves = len(self.tableView.selected_rows)
                self.tableView.statusLabel.setStatus(
                    "Successfully loaded "
                    + str(numSelectedCurves)
                    + (" curve." if numSelectedCurves == 1 else " curves.")
                )
            except ImageLogImportError as e:
                progressBar.nextStep(100, f"Error Loading Files.")
                time.sleep(0.5)
                self.tableView.statusLabel.setStatus("Error while loading curves.", color="red")
                slicer.util.errorDisplay(e)

    def setWellDiameterFieldState(self, state):
        color = widgets.get_input_widget_color(state)
        if color:
            self.wellDiameter.setStyleSheet("QLineEdit { background-color: " + color + "; }")
        else:
            self.wellDiameter.setStyleSheet("")

    def setNullValuesFieldState(self, state):
        color = widgets.get_input_widget_color(state)
        if color:
            self.nullValuesListText.setStyleSheet("QLineEdit { background-color: " + color + "; }")
        else:
            self.nullValuesListText.setStyleSheet("")
