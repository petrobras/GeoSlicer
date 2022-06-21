import qt
import slicer
from ltrace.slicer.ui import MultiplePathsWidget
from ltrace.workflow.workstep import Workstep, WorkstepWidget
from pathlib import Path
from ltrace.units import global_unit_registry as ureg
import ThinSectionLoader as tsl

THIN_SECTION_LOADER_FILE_EXTENSIONS = [".tif", ".tiff", ".png", ".jpg", ".jpeg"]


class ThinSectionLoader(Workstep):
    NAME = "Thin Section: Loader"

    INPUT_TYPES = (type(None),)
    OUTPUT_TYPE = slicer.vtkMRMLVectorVolumeNode

    def __init__(self):
        super().__init__()

    def defaultValues(self):
        self.pathList = []
        self.imageSpacing = 1
        self.automaticImageSpacing = True

    def run(self, nodes):
        for args in self.files_to_load():
            path, baseName = args
            params = tsl.ThinSectionLoaderWidget.LoadParameters(
                path, self.imageSpacing * ureg.mm, self.automaticImageSpacing
            )
            logic = tsl.ThinSectionLoaderLogic()
            logic.load(params, baseName)
            yield logic.node

    def expected_length(self, input_length):
        return len(list(self.files_to_load()))

    def files_to_load(self):
        """Yields (path, base name) pairs for all files to be loaded."""
        for path in self.pathList:
            path = Path(path)
            if path.is_file():
                yield path, path.parent.name
            else:
                files = []
                for extension in THIN_SECTION_LOADER_FILE_EXTENSIONS:
                    files.extend(list(path.glob("*" + extension)))
                if len(files) > 0:
                    yield from self.searchDirectory(path)
                else:
                    files = []
                    for extension in THIN_SECTION_LOADER_FILE_EXTENSIONS:
                        files.extend(list(path.glob("*/*" + extension)))
                    if len(files) > 0:
                        subdirectoriesPaths = [x for x in path.iterdir() if x.is_dir()]
                        yield from self.searchSubdirectories(subdirectoriesPaths)

    def searchDirectory(self, datasetsDirectoryPath):
        baseName = datasetsDirectoryPath.name
        files = [x for x in datasetsDirectoryPath.iterdir() if x.is_file()]
        yield from self.iterateFiles(files, baseName)

    def searchSubdirectories(self, subdirectoriesPaths):
        for path in subdirectoriesPaths:
            baseName = path.name
            files = [x for x in path.iterdir() if x.is_file()]
            yield from self.iterateFiles(files, baseName)

    def iterateFiles(self, files, baseName):
        validFiles = [file for file in files if file.suffix.lower() in THIN_SECTION_LOADER_FILE_EXTENSIONS]
        for validFile in validFiles:
            yield validFile, baseName

    def widget(self):
        return ThinSectionLoaderWidget(self)

    def validate(self):
        if len(self.pathList) == 0:
            return "There are no data to be loaded. Add directories and/or files."

        if self.imageSpacing is None:
            return "Pixel size is required."
        return True


class ThinSectionLoaderWidget(WorkstepWidget):
    def __init__(self, workstep):
        WorkstepWidget.__init__(self, workstep)

    def setup(self):
        WorkstepWidget.setup(self)

        self.formLayout = qt.QFormLayout()
        self.formLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.layout().addLayout(self.formLayout)

        self.formLayout.addRow("Data to be loaded:", None)

        self.multiplePathsWidget = MultiplePathsWidget(
            "",
            lambda _: None,
            fileExtensions=THIN_SECTION_LOADER_FILE_EXTENSIONS,
        )
        self.formLayout.addRow(self.multiplePathsWidget)

        self.formLayout.addRow(" ", None)

        self.imageSpacingLineEdit = qt.QLineEdit()
        self.imageSpacingValidator = qt.QRegExpValidator(qt.QRegExp("[+]?[0-9]*\\.?[0-9]+([eE][-+]?[0-9]+)?"))
        self.imageSpacingLineEdit.setValidator(self.imageSpacingValidator)
        self.imageSpacingLineEdit.setToolTip("Pixel size in millimeters")
        self.formLayout.addRow("Pixel size (mm):", self.imageSpacingLineEdit)

        self.automaticImageSpacingCheckBox = qt.QCheckBox("Try to automatically detect the pixel size")
        self.formLayout.addRow(None, self.automaticImageSpacingCheckBox)

    def save(self):
        self.workstep.pathList = self.multiplePathsWidget.directoryListView.directoryList
        try:
            self.workstep.imageSpacing = float(self.imageSpacingLineEdit.text)
        except ValueError:
            self.workstep.imageSpacing = None
        self.workstep.automaticImageSpacing = self.automaticImageSpacingCheckBox.isChecked()

    def load(self):
        self.multiplePathsWidget.directoryListView.directoryList = self.workstep.pathList
        self.imageSpacingLineEdit.text = self.workstep.imageSpacing if self.workstep.imageSpacing is not None else ""
        self.automaticImageSpacingCheckBox.setChecked(self.workstep.automaticImageSpacing)
