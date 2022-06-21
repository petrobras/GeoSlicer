import qt
import slicer
import vtk
from pathlib import Path


def _captureRenderWindow(renderWindow, isTransparent, fileName):
    renderWindow.Render()

    windowToImage = vtk.vtkWindowToImageFilter()
    if isTransparent:
        windowToImage.SetInputBufferTypeToRGBA()
    windowToImage.SetInput(renderWindow)

    writer = vtk.vtkPNGWriter()
    writer.SetFileName(fileName)
    writer.SetInputConnection(windowToImage.GetOutputPort())
    writer.Write()


def _capture3DView(isTransparent, fileName):
    view = slicer.app.layoutManager().threeDWidget(0).threeDView()
    renderWindow = view.renderWindow()

    if isTransparent:
        viewNode = view.mrmlViewNode()
        color = viewNode.GetBackgroundColor()
        color2 = viewNode.GetBackgroundColor2()
        alphaBitPlanes = renderWindow.GetAlphaBitPlanes()

        # Prepare views for capture with transparency
        viewNode.SetBackgroundColor(0, 0, 0)
        viewNode.SetBackgroundColor2(0, 0, 0)
        renderWindow.SetAlphaBitPlanes(1)

    _captureRenderWindow(renderWindow, isTransparent, fileName)

    if isTransparent:
        # Restore properties
        viewNode.SetBackgroundColor(color)
        viewNode.SetBackgroundColor2(color2)
        renderWindow.SetAlphaBitPlanes(alphaBitPlanes)


def _captureSliceView(sliceName, isTransparent, fileName):
    view = slicer.app.layoutManager().sliceWidget(sliceName).sliceView()
    renderWindow = view.renderWindow()

    if isTransparent:
        color = view.backgroundColor
        color2 = view.backgroundColor2
        alphaBitPlanes = renderWindow.GetAlphaBitPlanes()

        # Prepare views for capture with transparency
        view.setBackgroundColor(qt.QColor("black"))
        view.setBackgroundColor2(qt.QColor("black"))
        renderWindow.SetAlphaBitPlanes(1)

    _captureRenderWindow(renderWindow, isTransparent, fileName)

    if isTransparent:
        # Restore properties
        view.setBackgroundColor(color)
        view.setBackgroundColor2(color2)
        renderWindow.SetAlphaBitPlanes(alphaBitPlanes)


class ScreenshotWidget(qt.QDialog):
    THREED_VIEW_OPTION = "3D View"

    SETTINGS_NAME = "ScreenShotWidget"
    VIEW_SETTINGS_KEY = "/".join((SETTINGS_NAME, "view"))
    IS_TRANSPARENT_SETTINGS_KEY = "/".join((SETTINGS_NAME, "isTransparent"))
    SAVE_DIRECTORY_SETTINGS_KEY = "/".join((SETTINGS_NAME, "saveDirectory"))

    def __init__(self, icon):
        super().__init__(
            0,
            qt.Qt.WindowSystemMenuHint | qt.Qt.WindowTitleHint | qt.Qt.WindowCloseButtonHint,
        )

        self.iconPath = icon
        self.setWindowTitle("Screenshot")
        self.setAttribute(qt.Qt.WA_DeleteOnClose)

        self.setup()

    def setup(self):
        self.viewCombobox = qt.QComboBox()
        options = (self.THREED_VIEW_OPTION,) + slicer.app.layoutManager().sliceViewNames()
        for option in options:
            self.viewCombobox.addItem(option)
        self.viewCombobox.currentText = slicer.app.settings().value(self.VIEW_SETTINGS_KEY, self.THREED_VIEW_OPTION)

        self.transparentCheck = qt.QCheckBox()
        self.transparentCheck.checked = slicer.app.settings().value(self.IS_TRANSPARENT_SETTINGS_KEY, False) == "True"

        buttonBox = qt.QDialogButtonBox()
        buttonBox.addButton(qt.QPushButton("Save as…"), qt.QDialogButtonBox.AcceptRole)
        buttonBox.addButton(qt.QPushButton("Cancel"), qt.QDialogButtonBox.RejectRole)
        buttonBox.accepted.connect(self.onSaveAs)
        buttonBox.rejected.connect(self.reject)

        layout = qt.QFormLayout(self)
        layout.addRow("View to capture:", self.viewCombobox)
        layout.addRow("Transparent background:", self.transparentCheck)
        layout.addRow(buttonBox)

        self.setWindowIcon(qt.QIcon(self.iconPath))

    def onSaveAs(self):
        viewName = self.viewCombobox.currentText
        isTransparent = self.transparentCheck.checked
        directory = slicer.app.settings().value(
            self.SAVE_DIRECTORY_SETTINGS_KEY,
            slicer.mrmlScene.GetRootDirectory(),
        )
        fileName = qt.QFileDialog.getSaveFileName(self, "Save screenshot", directory, "Images (*.png)")

        if not fileName:
            return

        directory = str(Path(fileName).parent.absolute())
        slicer.app.settings().setValue(self.VIEW_SETTINGS_KEY, viewName)
        slicer.app.settings().setValue(self.IS_TRANSPARENT_SETTINGS_KEY, str(isTransparent))
        slicer.app.settings().setValue(self.SAVE_DIRECTORY_SETTINGS_KEY, directory)

        if viewName == self.THREED_VIEW_OPTION:
            _capture3DView(isTransparent, fileName)
        else:
            _captureSliceView(viewName, isTransparent, fileName)

        self.accept()
