from pathlib import Path

import qt
import slicer
import vtk
import pyqtgraph.exporters
import pyqtgraph as pg

from ltrace.slicer_utils import getResourcePath

GRAPHIC_VIEW_DATA = "GraphicViewData"
SLICE_VIEW_DATA = "SliceViewData"


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


def _captureGraphView(viewIdentifier, fileName):
    plotItem = slicer.util.getModuleWidget("ImageLogData").getGraphicViewPlotItem(viewIdentifier)
    if isinstance(plotItem, pg.PlotItem):
        exporter = pg.exporters.ImageExporter(plotItem.scene())
        exporter.export(fileName)


class ScreenshotWidget(qt.QDialog):
    VIEW_OPTION = ["Red", "Green", "Yellow"]
    THREED_VIEW_OPTION = "3D View"
    FONT_ANNOTATION_INITIAL_VALUE = 12

    SETTINGS_NAME = "ScreenShotWidget"
    VIEW_SETTINGS_KEY = "/".join((SETTINGS_NAME, "view"))
    IS_TRANSPARENT_SETTINGS_KEY = "/".join((SETTINGS_NAME, "isTransparent"))
    SAVE_DIRECTORY_SETTINGS_KEY = "/".join((SETTINGS_NAME, "saveDirectory"))

    ICON = "ScreenShot.png"

    def __init__(self):
        super().__init__(
            0,
            qt.Qt.WindowSystemMenuHint | qt.Qt.WindowTitleHint | qt.Qt.WindowCloseButtonHint,
        )

        self.setWindowTitle("ScreenShot")
        self.setAttribute(qt.Qt.WA_DeleteOnClose)
        self.saved_lines = []

        try:
            self.imagelogViews = slicer.util.getModuleWidget("ImageLogData").getVisibleViews()
        except:
            self.imagelogViews = None

        self.setup()

    def setup(self):
        layout = qt.QFormLayout(self)

        # View option
        self.viewCombobox = qt.QComboBox()

        imagelogOptions = []
        if self.imagelogViews:
            self.imagelogValidIds = []
            for key, value in self.imagelogViews.items():
                if value["type"] in [GRAPHIC_VIEW_DATA, SLICE_VIEW_DATA]:
                    imagelogOptions.append(value["name"])
                    self.imagelogValidIds.append(key)

        options = [self.THREED_VIEW_OPTION] + self.VIEW_OPTION + imagelogOptions
        for option in options:
            self.viewCombobox.addItem(option)
        self.viewCombobox.currentText = slicer.app.settings().value(self.VIEW_SETTINGS_KEY, self.THREED_VIEW_OPTION)
        self.transparentCheck = qt.QCheckBox()
        self.transparentCheck.checked = slicer.app.settings().value(self.IS_TRANSPARENT_SETTINGS_KEY, False) == "True"
        layout.addRow("View to capture:", self.viewCombobox)
        layout.addRow("Transparent background:", self.transparentCheck)

        # Annotations options
        self.annotationsOptionsWidget = qt.QWidget()
        annotationsOptionsLayout = qt.QFormLayout(self.annotationsOptionsWidget)
        annotationsOptionsLayout.setContentsMargins(0, 0, 0, 0)

        hbox_line = qt.QHBoxLayout()
        hbox_line.setSpacing(10)
        line_left = qt.QFrame()
        line_left.setFrameShape(qt.QFrame.HLine)
        line_left.setFrameShadow(qt.QFrame.Sunken)
        hbox_line.addWidget(line_left)
        text_label = qt.QLabel("Add Annotations")
        hbox_line.addWidget(text_label)
        line_right = qt.QFrame()
        line_right.setFrameShape(qt.QFrame.HLine)
        line_right.setFrameShadow(qt.QFrame.Sunken)
        line = qt.QFrame()
        line.setFrameShape(qt.QFrame.HLine)
        line.setFrameShadow(qt.QFrame.Sunken)
        hbox_line.addWidget(line_right)
        annotationsOptionsLayout.addRow(hbox_line)

        self.input = qt.QLineEdit("Click Add")
        annotationsOptionsLayout.addRow("Annotation:", self.input)

        hbox = qt.QHBoxLayout()
        self.radio_left = qt.QRadioButton("Left")
        self.radio_center = qt.QRadioButton("Center")
        self.radio_right = qt.QRadioButton("Right")
        self.radio_center.setChecked(True)
        hbox.addWidget(self.radio_left)
        hbox.addWidget(self.radio_center)
        hbox.addWidget(self.radio_right)
        annotationsOptionsLayout.addRow("Text Position:", hbox)

        self.fontSizeSlider = slicer.qMRMLSliderWidget()
        self.fontSizeSlider.maximum = 100
        self.fontSizeSlider.minimum = 12
        self.fontSizeSlider.value = 15
        self.fontSizeSlider.singleStep = 1
        annotationsOptionsLayout.addRow("Font Size:", self.fontSizeSlider)

        textButtons = qt.QHBoxLayout()
        addTextButton = qt.QPushButton("Add")
        removeTextButton = qt.QPushButton("Remove")
        addTextButton.setFixedWidth(100)
        removeTextButton.setFixedWidth(100)
        textButtons.addWidget(addTextButton)
        textButtons.addWidget(removeTextButton)
        textButtons.setAlignment(qt.Qt.AlignCenter)
        annotationsOptionsLayout.addRow(textButtons)

        layout.addRow(self.annotationsOptionsWidget)
        layout.addRow(line)
        layout.addRow(qt.QFrame())

        # Save options
        buttonBox = qt.QDialogButtonBox()
        buttonBox.addButton(qt.QPushButton("Save as…"), qt.QDialogButtonBox.AcceptRole)
        buttonBox.addButton(qt.QPushButton("Cancel"), qt.QDialogButtonBox.RejectRole)
        buttonBox.accepted.connect(self.onSaveAs)
        buttonBox.rejected.connect(self.onReject)
        layout.addRow(buttonBox)

        self.viewCombobox.currentIndexChanged.connect(self.viewIndexChange)
        self.radio_left.clicked.connect(lambda: self.clearAll())
        self.radio_center.clicked.connect(lambda: self.clearAll())
        self.radio_right.clicked.connect(lambda: self.clearAll())
        self.fontSizeSlider.valueChanged.connect(lambda: self.renderText())
        addTextButton.clicked.connect(self.addText)
        removeTextButton.clicked.connect(self.removeText)

        self.setWindowIcon(qt.QIcon(getResourcePath("Icons") / "png" / self.ICON))

    def addText(self):
        input_text = self.input.text
        if input_text:
            self.saved_lines.append(input_text)
        self.input.text = ""
        self.renderText()

    def removeText(self):
        if self.saved_lines:
            del self.saved_lines[-1]
            self.renderText()

    def viewIndexChange(self, index):
        self.annotationsOptionsWidget.setEnabled(True)
        if index > 3:
            id = self.imagelogValidIds[index - 4]
            if self.imagelogViews[id]["type"] == GRAPHIC_VIEW_DATA:
                self.annotationsOptionsWidget.setEnabled(False)

        self.clearAll()

    def clearAll(self):
        textColor = (1.0, 1.0, 1.0)
        for viewName in self.VIEW_OPTION:
            self.renderInView("", viewName, textColor)
        self.renderIn3DView("", textColor)
        self.renderText()

    def renderText(self):
        textColor = (1.0, 1.0, 1.0)
        viewName = self.viewCombobox.currentText
        viewIndex = self.viewCombobox.currentIndex
        text = self.get_saved_text()
        if viewIndex == 0:  # 3D VIEW
            self.renderIn3DView(text, textColor)

        elif viewIndex in [1, 2, 3]:  # RED, GREEN or YELLOW Camera
            self.renderInView(text, viewName, textColor)

        else:  # ImageLog Views
            id = self.imagelogValidIds[viewIndex - 4]
            if self.imagelogViews[id]["type"] == SLICE_VIEW_DATA:
                self.renderInView(text, f"ImageLogSliceView{id}", textColor)

    def renderInView(self, text, viewName, textColor):
        lm = slicer.app.layoutManager()
        view = lm.sliceWidget(viewName).sliceView()
        # Set font
        view.cornerAnnotation().ClearAllTexts()
        view.cornerAnnotation().SetLinearFontScaleFactor(2)
        view.cornerAnnotation().SetNonlinearFontScaleFactor(1)
        view.cornerAnnotation().SetMaximumFontSize(int(self.fontSizeSlider.value))
        self.setText(view, text)
        # Set color
        textProperty = view.cornerAnnotation().GetTextProperty()
        textProperty.SetColor(textColor)
        view.forceRender()

    def renderIn3DView(self, text, textColor):
        view = slicer.app.layoutManager().threeDWidget(0).threeDView()
        # Set font
        view.cornerAnnotation().SetLinearFontScaleFactor(1.0)
        view.cornerAnnotation().SetNonlinearFontScaleFactor(2.0)
        view.cornerAnnotation().SetMaximumFontSize(int(self.fontSizeSlider.value))
        self.setText(view, text)
        # Set color
        textProperty = view.cornerAnnotation().GetTextProperty()
        textProperty.SetColor(textColor)

        view.forceRender()

    def setText(self, view, text):
        if self.radio_right.checked:
            view.cornerAnnotation().SetText(vtk.vtkCornerAnnotation.UpperRight, text)
            view.cornerAnnotation().SetText(vtk.vtkCornerAnnotation.UpperLeft, "")
            view.cornerAnnotation().SetText(vtk.vtkCornerAnnotation.UpperEdge, "")
        if self.radio_center.checked:
            view.cornerAnnotation().SetText(vtk.vtkCornerAnnotation.UpperRight, "")
            view.cornerAnnotation().SetText(vtk.vtkCornerAnnotation.UpperLeft, "")
            view.cornerAnnotation().SetText(vtk.vtkCornerAnnotation.UpperEdge, text)
        if self.radio_left.checked:
            view.cornerAnnotation().SetText(vtk.vtkCornerAnnotation.UpperRight, "")
            view.cornerAnnotation().SetText(vtk.vtkCornerAnnotation.UpperLeft, text)
            view.cornerAnnotation().SetText(vtk.vtkCornerAnnotation.UpperEdge, "")

    def get_saved_text(self):
        return "\n".join(self.saved_lines)

    def onSaveAs(self):
        viewName = self.viewCombobox.currentText
        viewIndex = self.viewCombobox.currentIndex
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

        if viewIndex == 0:  # 3D VIEW
            _capture3DView(isTransparent, fileName)

        elif viewIndex in [1, 2, 3]:  # RED, GREEN or YELLOW Camera
            _captureSliceView(viewName, isTransparent, fileName)

        else:  # ImageLog Views
            id = self.imagelogValidIds[viewIndex - 4]
            if self.imagelogViews[id]["type"] == GRAPHIC_VIEW_DATA:
                _captureGraphView(id, fileName)
            else:
                _captureSliceView(f"ImageLogSliceView{id}", isTransparent, fileName)

        self.accept()

    def onReject(self):
        self.saved_lines = []
        self.fontSizeSlider.value = self.FONT_ANNOTATION_INITIAL_VALUE
        self.clearAll()
        self.reject()

    def closeEvent(self, event):
        self.fontSizeSlider.value = self.FONT_ANNOTATION_INITIAL_VALUE
        self.saved_lines = []
        self.clearAll()
