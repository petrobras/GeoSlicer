import slicer
import qt
from Customizer import Customizer
from ltrace.slicer import helpers
from ltrace.slicer.node_observer import NodeObserver
from ltrace.utils.Markup import MarkupLine


class PixelSizeEditor(qt.QWidget):
    FIELD_SCALE_SIZE_PX = 0
    FIELD_SCALE_SIZE_MM = 1
    FIELD_PIXEL_SIZE = 2

    imageSpacingSet = qt.Signal()
    scaleSizeInputChanged = qt.Signal()
    imageSpacingInputChanged = qt.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._currentNodeId = None

        self.loadFormLayout = qt.QFormLayout(self)
        self.loadFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.loadFormLayout.setContentsMargins(0, 0, 0, 0)

        self.imageSpacing1Validator = qt.QRegExpValidator(qt.QRegExp("[+]?[0-9]*\\.?[0-9]+([eE][-+]?[0-9]+)?"))

        self.scaleSizePxLineEdit = qt.QLineEdit()
        self.scaleSizePxLineEdit.setObjectName("scaleSizePxLineEdit")
        self.scaleSizePxLineEdit.setValidator(self.imageSpacing1Validator)
        self.scaleSizePxLineEdit.setToolTip("Scale size in pixels")
        self.scaleSizePxLineEdit.textEdited.connect(lambda: self.__on_size_field_edited(self.FIELD_SCALE_SIZE_PX))
        self.scaleSizePxRuler = qt.QPushButton()
        self.scaleSizePxRuler.setIcon(qt.QIcon(str(Customizer.ANNOTATION_DISTANCE_ICON_PATH)))
        self.scaleSizePxRuler.connect("clicked()", self.onScaleSizeRulerButtonClicked)
        self.scaleSizePxFrame = qt.QFrame()
        scaleSizePxLayout = qt.QHBoxLayout(self.scaleSizePxFrame)
        scaleSizePxLayout.setContentsMargins(0, 0, 0, 0)
        scaleSizePxLayout.addWidget(self.scaleSizePxLineEdit)
        scaleSizePxLayout.addWidget(self.scaleSizePxRuler)
        self.loadFormLayout.addRow("Scale size (px):", self.scaleSizePxFrame)

        self.scaleSizeMmLineEdit = qt.QLineEdit()
        self.scaleSizeMmLineEdit.setObjectName("scaleSizeMmLineEdit")
        self.scaleSizeMmLineEdit.setValidator(self.imageSpacing1Validator)
        self.scaleSizeMmLineEdit.setToolTip("Scale size in millimeters")
        self.scaleSizeMmLineEdit.textEdited.connect(lambda: self.__on_size_field_edited(self.FIELD_SCALE_SIZE_MM))
        self.loadFormLayout.addRow("Scale size (mm):", self.scaleSizeMmLineEdit)

        self.imageSpacingLineEdit = qt.QLineEdit()
        self.imageSpacingLineEdit.setObjectName("imageSpacing1LineEdit")
        self.imageSpacingLineEdit.setValidator(self.imageSpacing1Validator)
        self.imageSpacingLineEdit.setToolTip("Pixel size in millimeters")
        self.imageSpacingLineEdit.textEdited.connect(lambda: self.__on_size_field_edited(self.FIELD_PIXEL_SIZE))
        self.loadFormLayout.addRow("Pixel size (mm):", self.imageSpacingLineEdit)

        self.savePixelSizeButton = qt.QPushButton("Save pixel size")
        self.savePixelSizeButton.setObjectName("savePixelSizeButton")
        self.loadFormLayout.addRow(None, self.savePixelSizeButton)
        self.savePixelSizeButton.clicked.connect(self.__on_save_button_clicked)

        self.__set_retain_size_when_hidden(self.loadFormLayout.labelForField(self.scaleSizePxFrame), True)
        self.__set_retain_size_when_hidden(self.loadFormLayout.labelForField(self.scaleSizeMmLineEdit), True)
        self.__set_retain_size_when_hidden(self.loadFormLayout.labelForField(self.imageSpacingLineEdit), True)

    def onScaleSizeRulerButtonClicked(self):
        def finish(caller_markup, point_index=None):
            self.scaleSizePxLineEdit.text = round(caller_markup.get_line_length_in_pixels())
            self.__on_size_field_edited(self.FIELD_SCALE_SIZE_PX)

        self.markup = MarkupLine(finish)
        self.markup.start_picking()

    def reset(self):
        self.scaleSizePxLineEdit.text = ""
        self.scaleSizeMmLineEdit.text = ""
        self.imageSpacingLineEdit.text = ""
        self.__reset_style(self.scaleSizePxLineEdit)
        self.__reset_style(self.scaleSizeMmLineEdit)
        self.__reset_style(self.imageSpacingLineEdit)

    def getImageSpacing(self):
        return self.imageSpacingLineEdit.text

    def getScaleSizeMm(self):
        return self.scaleSizeMmLineEdit.text

    def getScaleSizePx(self):
        return self.scaleSizePxLineEdit.text

    def setImageSpacingText(self, text):
        self.imageSpacingLineEdit.text = text

    def setScaleSizeMmText(self, text):
        self.scaleSizeMmLineEdit.text = text

    def setScaleSizePxText(self, text):
        self.scaleSizePxLineEdit.text = text

    def activateScaleSizeErrorStyle(self):
        self.__set_lineedit_style_red(self.scaleSizePxLineEdit)
        self.__set_lineedit_style_red(self.scaleSizeMmLineEdit)

    def resetImageScalingText(self):
        self.scaleSizePxLineEdit.text = ""

    def resetScaleSizeText(self):
        self.scaleSizePxLineEdit.text = ""
        self.scaleSizeMmLineEdit.text = ""

    def resetImageScalingStyle(self):
        self.__reset_style(self.scaleSizePxLineEdit)

    def resetScaleSizeStyle(self):
        self.__reset_style(self.scaleSizePxLineEdit)
        self.__reset_style(self.scaleSizeMmLineEdit)

    def __set_retain_size_when_hidden(self, widget, enable):
        size_policy = widget.sizePolicy
        size_policy.setRetainSizeWhenHidden(enable)
        widget.setSizePolicy(size_policy)

    def __on_size_field_edited(self, edited_field):
        if edited_field == self.FIELD_SCALE_SIZE_MM or edited_field == self.FIELD_SCALE_SIZE_PX:
            if self.scaleSizePxLineEdit.text and self.scaleSizeMmLineEdit.text:
                self.scaleSizeInputChanged.emit()
                self.__reset_style(self.scaleSizePxLineEdit)
                self.__reset_style(self.scaleSizeMmLineEdit)
                self.__set_lineedit_style_highlighted(self.imageSpacingLineEdit)
                self.imageSpacingLineEdit.text = str(
                    float(self.scaleSizeMmLineEdit.text) / float(self.scaleSizePxLineEdit.text)
                )
                return
        else:
            if self.imageSpacingLineEdit.text:
                self.imageSpacingInputChanged.emit()
                self.__set_lineedit_style_highlighted(self.scaleSizePxLineEdit)
                self.__set_lineedit_style_highlighted(self.scaleSizeMmLineEdit)
                self.__reset_style(self.imageSpacingLineEdit)
                self.scaleSizePxLineEdit.text = ""
                self.scaleSizeMmLineEdit.text = ""
                return
        self.__reset_style(self.scaleSizePxLineEdit)
        self.__reset_style(self.scaleSizeMmLineEdit)
        self.__reset_style(self.imageSpacingLineEdit)

    def __on_save_button_clicked(self):
        if not self.imageSpacingLineEdit.text:
            slicer.util.warningDisplay('Failed to save image scale. "Pixel size" field is empty.')
        elif not self.setImageSpacingOnVolume(float(self.imageSpacingLineEdit.text)):
            slicer.util.warningDisplay("Failed to save image scale. No image was loaded yet.")

    def setImageSpacingOnVolume(self, imageSpacing):
        node = helpers.tryGetNode(self._currentNodeId)
        if not node:
            return False

        node.SetSpacing(imageSpacing, imageSpacing, imageSpacing)
        slicer.util.setSliceViewerLayers(background=node, fit=True)
        self.imageSpacingSet.emit()
        return True

    def __reset_style(self, line_edit_widget):
        line_edit_widget.setStyleSheet("")

    def __set_lineedit_style_red(self, line_edit_widget):
        helpers.highlight_error(line_edit_widget)

    def __set_lineedit_style_highlighted(self, line_edit_widget):
        line_edit_widget.setStyleSheet(
            "QLineEdit {" "    border-color: yellow;" "    border-width: 1px;" "    border-style: outset;" "}"
        )

    @property
    def currentNode(self):
        return helpers.tryGetNode(self._currentNodeId)

    @currentNode.setter
    def currentNode(self, node):
        self._currentNodeId = node.GetID() if node is not None else None

        if node is not None:
            self._currentNodeObserver = NodeObserver(node, parent=self)
            self._currentNodeObserver.removedSignal.connect(self.onCurrentNodeRemoved)

    def onCurrentNodeRemoved(self, node_observer: NodeObserver, node: slicer.vtkMRMLNode):
        self._currentNodeId = None
        del self._currentNodeObserver
        self._currentNodeObserver = None
