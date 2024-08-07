import os
import re
from collections import namedtuple
from pathlib import Path

import ctk
import cv2
import logging
import numpy as np
import pytesseract
import qt
import slicer
from Customizer import Customizer

from dataclasses import dataclass
from ltrace.image.io import volume_from_image
from ltrace.slicer.widget.pixel_size_editor import PixelSizeEditor
from ltrace.slicer.helpers import getTesseractCmd, save_path, isImageFile, tryGetNode
from ltrace.slicer.widget.status_panel import StatusPanel
from ltrace.slicer_utils import *
from ltrace.slicer import loader
from ltrace.slicer.node_observer import NodeObserver
from ltrace.utils.Markup import MarkupLine
from ltrace.units import global_unit_registry as ureg, SLICER_LENGTH_UNIT  # ureg comes from pint library
from ltrace.slicer.node_attributes import LosslessAttribute

from Libs.scale_detect_rect import detect_scale, image_corners

# Checks if closed source code is available
try:
    from Test.ThinSectionLoaderTest import ThinSectionLoaderTest
except ImportError:
    ThinSectionLoaderTest = None

os.environ["TESSDATA_PREFIX"] = f"{slicer.app.slicerHome}/bin/Tesseract-OCR/tessdata/"
pytesseract.pytesseract.tesseract_cmd = getTesseractCmd()

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

MAX_OCR_SIZE = 1 * 10**8
BLACK_THRESHOLD = 30
RE_STRING = r".*?[^\d]*((?:[1-9]\d*)|(?:\d+[.,]\d*[1-9]\d*)) *([cmnuμ]?m|μ).*"


class ThinSectionLoader(LTracePlugin):
    SETTING_KEY = "ThinSectionLoader"

    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))
    RES_DIR = MODULE_DIR / "Resources"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Thin Section Loader"
        self.parent.categories = ["Thin Section"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysical Solutions"]
        self.parent.helpText = ThinSectionLoader.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class ThinSectionLoaderWidget(LTracePluginWidget):
    # Settings constants
    AUTOMATIC_IMAGE_SPACING = "automaticImageSpacing"

    FIELD_SCALE_SIZE_PX = 0
    FIELD_SCALE_SIZE_MM = 1
    FIELD_PIXEL_SIZE = 2

    @dataclass
    class LoadParameters:
        path: str
        imageSpacing: float = SLICER_LENGTH_UNIT * 0.01
        automaticImageSpacing: bool = True
        lossless: bool = None

    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)

    def __getFormattedLabel(self, label):
        labelWidget = qt.QLabel(label)
        labelWidget.setMinimumWidth(80)
        return labelWidget

    def getAutomaticImageSpacing(self):
        return ThinSectionLoader.get_setting(self.AUTOMATIC_IMAGE_SPACING, default=str(True))

    def setup(self):
        LTracePluginWidget.setup(self)
        self.logic = ThinSectionLoaderLogic()

        frame = qt.QFrame()

        self.layout.addWidget(frame)
        self.loadFormLayout = qt.QFormLayout(frame)
        self.loadFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        self.loadFormLayout.setFormAlignment(qt.Qt.AlignLeft | qt.Qt.AlignBottom)
        self.loadFormLayout.setContentsMargins(0, 0, 0, 0)

        instructionsCollapsibleButton = ctk.ctkCollapsibleButton()
        instructionsCollapsibleButton.text = "Instructions"
        instructionsCollapsibleButton.flat = True
        instructionsCollapsibleButton.collapsed = False
        self.status_panel = StatusPanel("")
        self.status_panel.set_instruction("Select an input file")
        instructionsFormLayout = qt.QFormLayout(instructionsCollapsibleButton)
        instructionsFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        instructionsFormLayout.setContentsMargins(0, 0, 0, 0)
        instructionsFormLayout.addWidget(self.status_panel)

        self.loadFormLayout.addRow(instructionsCollapsibleButton)
        inputCollapsibleButton = ctk.ctkCollapsibleButton()
        inputCollapsibleButton.text = "Input"
        inputCollapsibleButton.flat = True
        inputCollapsibleButton.collapsed = False
        self.inputFileSelector = ctk.ctkPathLineEdit()
        self.inputFileSelector.setToolTip("Choose the input file.")
        self.inputFileSelector.currentPathChanged.connect(self.__on_file_selected)
        self.inputFileSelector.settingKey = "ThinSectionLoader/InputFile"
        self.inputFileSelector.objectName = "Input File Selector"
        inputFormLayout = qt.QFormLayout(inputCollapsibleButton)
        inputFormLayout.setLabelAlignment(qt.Qt.AlignRight)
        inputFormLayout.addRow(self.__getFormattedLabel("Input file:"), self.inputFileSelector)

        self.automaticImageSpacingCheckBox = qt.QCheckBox("Try to automatically detect the pixel size")
        self.automaticImageSpacingCheckBox.setChecked(self.getAutomaticImageSpacing() == "True")
        self.automaticImageSpacingCheckBox.objectName = "Automatic Detect Spacing CheckBox"
        inputFormLayout.addRow(None, self.automaticImageSpacingCheckBox)

        self.loadFormLayout.addRow(inputCollapsibleButton)

        # Advanced section
        self.advancedCollapsibleButton = ctk.ctkCollapsibleButton()
        self.advancedCollapsibleButton.text = "Advanced"
        self.advancedCollapsibleButton.flat = True
        self.advancedCollapsibleButton.collapsed = True
        self.advancedCollapsibleButton.objectName = "Advanced Collapsible Button"
        self.advancedFormLayout = qt.QFormLayout(self.advancedCollapsibleButton)
        self.advancedFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.losslessCheckBox = qt.QCheckBox("Lossless")
        self.losslessCheckBox.setChecked(True)
        self.losslessCheckBox.setEnabled(False)
        self.losslessCheckBox.objectName = "Lossless Checkbox"
        self.advancedFormLayout.addRow(self.__getFormattedLabel(""), self.losslessCheckBox)
        self.loadFormLayout.addRow(self.advancedCollapsibleButton)

        # Load button
        self.loadButton = qt.QPushButton("Load thin section")
        self.loadButton.objectName = "Load Thin Section Button"
        self.loadButton.setFixedHeight(40)
        self.loadButton.clicked.connect(self.onLoadButtonClicked)

        self.pixelSizeEditor = PixelSizeEditor()
        self.layout.addWidget(self.pixelSizeEditor)
        self.pixelSizeEditor.scaleSizeInputChanged.connect(
            lambda: self.status_panel.set_instruction("Click to save modifications")
        )
        self.pixelSizeEditor.imageSpacingSet.connect(
            lambda: self.status_panel.set_instruction("Thin section updated successfully")
        )
        self.loadFormLayout.addRow(self.loadButton)

        # Parameters section
        self.parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        self.parametersCollapsibleButton.text = "Parameters"
        self.parametersCollapsibleButton.flat = True
        self.parametersCollapsibleButton.collapsed = False
        self.parametersFormLayout = qt.QFormLayout(self.parametersCollapsibleButton)
        self.parametersFormLayout.setLabelAlignment(qt.Qt.AlignRight)

        self.parametersFormLayout.addRow(" ", None)
        self.loadFormLayout.addRow(self.parametersCollapsibleButton)

        statusLabel = qt.QLabel("Status: ")
        self.currentStatusLabel = qt.QLabel("Idle")
        statusHBoxLayout = qt.QHBoxLayout()
        statusHBoxLayout.addStretch(1)
        statusHBoxLayout.addWidget(statusLabel)
        statusHBoxLayout.addWidget(self.currentStatusLabel)
        self.layout.addLayout(statusHBoxLayout)

        self.layout.addStretch(1)

        self.__update_scalesize_parameters_visibility()
        self.__on_file_selected()

    def onLoadButtonClicked(self):
        if not self.inputFileSelector.currentPath:
            self.status_panel.set_instruction("Select an input file first", True)
            return
        save_path(self.inputFileSelector)

        try:
            if self.logic.loaded:
                return
            path = self.inputFileSelector.currentPath
            imageSpacing = self.pixelSizeEditor.getImageSpacing() or "1"
            automatic_image_spacing_enabled = self.automaticImageSpacingCheckBox.isChecked()
            ThinSectionLoader.set_setting(self.AUTOMATIC_IMAGE_SPACING, str(automatic_image_spacing_enabled))
            loadParameters = self.LoadParameters(
                path,
                float(imageSpacing) * ureg.millimeter,
                automatic_image_spacing_enabled,
                lossless=self.is_lossless_image(),
            )
            self.updateStatus(f"Loading {Path(path).name}...")
            detection_data = self.logic.load(loadParameters)
            self.logic.loaded = True
            self.pixelSizeEditor.currentNode = self.logic.getCurrentNode()
            failed_detection = "scale_size_mm" not in detection_data
            if failed_detection:
                self.pixelSizeEditor.activateScaleSizeErrorStyle()
            elif automatic_image_spacing_enabled:
                self.pixelSizeEditor.resetScaleSizeStyle()
                self.pixelSizeEditor.setImageSpacingText(detection_data["pixel_size_mm"])
                self.pixelSizeEditor.setScaleSizeMmText(detection_data["scale_size_mm"])
                self.pixelSizeEditor.setScaleSizePxText(detection_data["scale_size_px"])
        except LoadInfo as e:
            slicer.util.infoDisplay(str(e))
            return
        finally:
            self.updateStatus("")
        if failed_detection:
            slicer.util.warningDisplay("Failed to detect scale in the selected image")
            self.status_panel.set_instruction("Manually define scale in px and mm", True)
        else:
            if automatic_image_spacing_enabled:
                self.status_panel.set_instruction("Thin section loaded successfully")
            else:
                self.status_panel.set_instruction("Manually define scale in px and mm")
        self.__update_scalesize_parameters_visibility()

    def updateStatus(self, message):
        self.currentStatusLabel.text = message
        slicer.app.processEvents()

    def __on_file_selected(self):
        self.logic.loaded = False
        self.logic.reset()
        self.pixelSizeEditor.currentNode = self.logic.getCurrentNode()
        self.pixelSizeEditor.resetScaleSizeText()
        self.pixelSizeEditor.resetImageScalingText()
        self.pixelSizeEditor.resetScaleSizeStyle()
        self.pixelSizeEditor.resetImageScalingStyle()
        self.status_panel.set_instruction("Click to load thin section")
        self.__update_scalesize_parameters_visibility()
        self.__update_lossless_option()

    def __update_scalesize_parameters_visibility(self):
        visible = self.logic.getCurrentNode() != None
        self.pixelSizeEditor.setVisible(visible)

    def __update_lossless_option(self):
        file_path = self.inputFileSelector.currentPath
        enable = file_path and isImageFile(file_path)
        self.losslessCheckBox.setEnabled(enable)
        self.advancedCollapsibleButton.visible = enable
        # Default 'Lossy' check state for JPG related files. Otherwise 'Lossless'
        self.losslessCheckBox.setChecked(Path(file_path).suffix.lower() not in [".jpg", ".jpeg"])

    def is_lossless_image(self):
        if not self.advancedCollapsibleButton.visible or self.losslessCheckBox.isChecked():
            return True

        return False


class ThinSectionLoaderLogic(LTracePluginLogic):
    ROOT_DATASET_DIRECTORY_NAME = "Thin Section"
    THIN_SECTION_LOADER_FILE_EXTENSIONS = [".tif", ".tiff", ".png", ".jpg", ".jpeg"]

    def __init__(self):
        LTracePluginLogic.__init__(self)
        self.pytesseractMessageShowed = False
        self.nodeId = None
        self.loaded = False
        self.nodeObserver: NodeObserver = None

    def onNodeRemoved(self):
        if self.getCurrentNode():
            return

        self.loaded = False
        self.reset()

    def load(self, p, baseName=None):
        path = Path(p.path)
        baseName = baseName or path.parent.name
        return self.loadImage(path, p, baseName)

    def loadImage(self, file, p, baseName):
        node = volume_from_image(str(file))
        self.nodeObserver = NodeObserver(node=node, parent=None)
        self.nodeObserver.removedSignal.connect(self.onNodeRemoved)
        self.nodeId = node.GetID()
        image_info = {}
        imageSpacing = None
        if p.automaticImageSpacing:
            image = slicer.util.arrayFromVolume(node)
            scale_info = self.extract_scale(image)
            if scale_info:
                line_length = scale_info["line_length"]
                quantity = scale_info["quantity"]
                unit = scale_info["unit"]
                try:
                    scaleValue = ureg.Quantity(quantity, f"{unit}")
                except Exception as e:
                    logging.info(f'Failed to register scale text "{scale_info}": {str(e)}')
                imageSpacing = np.around(float(scaleValue.m_as(SLICER_LENGTH_UNIT)) / float(line_length), 6)
                image_info["scale_size_mm"] = scaleValue.m_as(SLICER_LENGTH_UNIT)
                image_info["scale_size_px"] = float(line_length)

        imageSpacing = imageSpacing or p.imageSpacing.m_as(SLICER_LENGTH_UNIT)
        image_info["pixel_size_mm"] = imageSpacing

        if p.lossless is None:
            lossless = file.suffix.lower() not in [".jpg", ".jpeg"]
        else:
            lossless = p.lossless
        losslessAttributeValue = LosslessAttribute.TRUE.value if lossless is True else LosslessAttribute.FALSE.value
        node.SetAttribute(LosslessAttribute.name(), losslessAttributeValue)
        self.setImageSpacingOnVolume(imageSpacing)

        loader.configureInitialNodeMetadata(self.ROOT_DATASET_DIRECTORY_NAME, baseName, node)
        slicer.util.resetSliceViews()
        return image_info

    def parse_tesseract_result(self, results, tolerance=-0.1):
        """
        Receives the result dict from tesseracts and searches for scale information
        Return None if scale text is not found

        return dict:
            'quantity' : int representing number of units per scale ruler
            'unit' : string for unit of sclae ruler (either cm, mm, um, μm or nm)
            'horizontal' : bool, false if scale text is horizontally aligned
            'bbox' : int tupple for text position (left, top, right, bottom)
            'extended_bbox' : extended_bbox
        """
        phrases = {}
        for word, block, confidence in (
            (i[0], int(i[1]), float(i[2])) for i in zip(results["text"], results["block_num"], results["conf"])
        ):
            if confidence < tolerance:
                continue
            if block not in phrases.keys():
                phrases[block] = word
            else:
                phrases[block] += f" {word}"
        for block, phrase in phrases.items():
            re_result = re.match(RE_STRING, phrase)
            if re_result:
                found_block = False
                for block_dict in (dict(zip(results.keys(), i)) for i in zip(*results.values())):
                    if block_dict["level"] != 2:
                        continue
                    if block_dict["block_num"] != block:
                        continue
                    found_block = True
                    break
                if not found_block:
                    logging.debug("Tesseract text block not found")
                    return None

                quantity = re_result[1].replace(",", ".")
                try:
                    quantity = float(quantity)
                except ValueError:
                    print(f"Detected quantity '{quantity}' is not valid")
                    return None

                width = block_dict["width"]
                height = block_dict["height"]
                bbox = (block_dict["left"], block_dict["top"], block_dict["left"] + width, block_dict["top"] + height)
                extended_bbox = (max(0, bbox[0] - width), max(0, bbox[1] - height), bbox[2] + width, bbox[3] + height)
                return {
                    "quantity": quantity,
                    "unit": re_result[2].replace("μ", "um"),
                    "horizontal": width > height,
                    "bbox": bbox,
                    "extended_bbox": extended_bbox,
                }
        return None

    def rect_detection_filter(self, arr):
        segment = detect_scale(arr)
        if segment is None:
            return None, None
        return self.resize_to_fit_ocr(segment)

    def resize_to_fit_ocr(self, arr):
        h, w = arr.shape[:2]

        if (h * w) > MAX_OCR_SIZE:
            scale_factor = np.sqrt(MAX_OCR_SIZE / (h * w))
            dim = (int(w * scale_factor), int(h * scale_factor))
            scaled_array = cv2.resize(arr, dim, interpolation=cv2.INTER_NEAREST)
        else:
            scaled_array = arr
            scale_factor = 1

        return scaled_array, scale_factor

    def extract_scale(self, image):
        image = image.squeeze()
        if max(image.shape) > 2000:
            image = image_corners(image)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        filtered_image, scale_factor = self.rect_detection_filter(image)
        using_rect_detection = True
        if filtered_image is None:
            return None
        image = filtered_image.astype("uint8")
        w, h = image.shape[:2]
        dpi = int(100 / scale_factor**2)

        sparse_text_with_osd_psm = 12
        legacy_plus_neural_oem = 0
        tesseract_config = (
            f"--psm {sparse_text_with_osd_psm} --oem {legacy_plus_neural_oem} "
            f'-c tessedit_char_whitelist=" .,0123456789cmnu" '  # μ
            f"-c tessedit_write_images=true"
        )

        results = pytesseract.image_to_data(
            image, lang="grc+eng", output_type=pytesseract.Output.DICT, config=tesseract_config
        )  # to debug tesseract input image, include '-c tessedit_write_images=true'
        parsed_scale = self.parse_tesseract_result(results)

        if not parsed_scale:  # Retry OSD/OCR after rotating the image 180º
            results = pytesseract.image_to_data(
                cv2.rotate(image, cv2.ROTATE_180),
                lang="grc+eng",
                output_type=pytesseract.Output.DICT,
                config=tesseract_config,
            )
            parsed_scale = self.parse_tesseract_result(results)
            if not parsed_scale:
                return None
            parsed_scale["bbox"] = (
                h - parsed_scale["bbox"][2],
                w - parsed_scale["bbox"][3],
                h - parsed_scale["bbox"][0],
                w - parsed_scale["bbox"][1],
            )
            parsed_scale["extended_bbox"] = (
                h - parsed_scale["extended_bbox"][2],
                w - parsed_scale["extended_bbox"][3],
                h - parsed_scale["extended_bbox"][0],
                w - parsed_scale["extended_bbox"][1],
            )

        gray_view = 255 - image
        if gray_view.ndim > 2:
            gray_view = cv2.cvtColor(gray_view, cv2.COLOR_BGR2GRAY)
        if not using_rect_detection:
            left, top, right, bottom = parsed_scale["extended_bbox"]
            gray_view = gray_view[top : min(w, bottom), left : min(h, right)]

        edge_view = cv2.Canny(gray_view, 100, 200)
        edge_view = cv2.dilate(edge_view, np.ones((3, 3)))

        largestLineLengths = []
        for view in (gray_view, edge_view):
            largestLineLength = 0
            line_index = None
            lines = cv2.HoughLinesP(view, 1, np.pi / 2, 10, minLineLength=30)
            if lines is not None:
                for i, line in enumerate(lines):
                    line = line[0]
                    lineLength = np.hypot(line[0] - line[2], line[1] - line[3])
                    if lineLength > largestLineLength:
                        largestLineLength = lineLength
                        line_index = i

            if lines is not None:
                view = np.repeat(view[..., np.newaxis], 3, axis=2)
                x0, y0, x1, y1 = lines[line_index][0]
                view = cv2.line(view, (x1, y1), (x0, y0), (0, 255, 0), 2)
            if largestLineLength > 0:
                largestLineLengths.append(largestLineLength)

        if largestLineLengths:
            finalLength = np.array(largestLineLengths).mean()
        else:
            finalLength = max(gray_view.shape)

        parsed_scale["line_length"] = finalLength / scale_factor

        return parsed_scale

    def setImageSpacingOnVolume(self, imageSpacing):
        if node := self.getCurrentNode():
            node.SetSpacing(imageSpacing, imageSpacing, imageSpacing)
            slicer.util.setSliceViewerLayers(background=node, fit=True)
            return True
        else:
            return False

    def getCurrentNode(self):
        return tryGetNode(self.nodeId)

    def reset(self):
        self.nodeId = None

        if self.nodeObserver is None:
            return

        self.nodeObserver.clear()
        del self.nodeObserver
        self.nodeObserver = None


class LoadInfo(RuntimeError):
    pass
