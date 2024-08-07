import os
import qt
import slicer
import numpy as np

from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic
from ltrace.slicer import widgets
from ltrace.slicer.helpers import createTemporaryVolumeNode, highlight_error
from pathlib import Path
from Libs.patchmatch import PatchMatch

try:
    from Test.CoreInpaintTest import CoreInpaintTest
except ImportError:
    CoreInpaintTest = None  # tests not deployed to final version or closed source


class CoreInpaint(LTracePlugin):
    SETTING_KEY = "CoreInpaint"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Core Inpaint"
        self.parent.categories = ["Core"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.helpText = CoreInpaint.help()

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class CoreInpaintWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = CoreInpaintLogic()

    def setup(self):
        LTracePluginWidget.setup(self)

        self.inputWidget = widgets.SingleShotInputWidget(
            hideSoi=True, hideCalcProp=True, allowedInputNodes=["vtkMRMLSegmentationNode"]
        )

        self.inputWidget.onReferenceSelectedSignal.connect(self.onReferenceSelected)

        self.outputNameField = qt.QLineEdit()
        self.outputNameField.setToolTip("Name of the output volume")

        self.progressBar = qt.QProgressBar()

        self.applyButton = qt.QPushButton("Apply")
        self.applyButton.setFixedHeight(40)
        self.applyButton.clicked.connect(self.onApplyClicked)

        formLayout = qt.QFormLayout()
        formLayout.addRow(self.inputWidget)
        formLayout.addRow("Output name:", self.outputNameField)

        self.layout.addLayout(formLayout)
        self.layout.addWidget(self.progressBar)
        self.layout.addWidget(self.applyButton)
        self.layout.addStretch(1)

        self.onReferenceSelected(self.inputWidget.referenceInput.currentNode())

    def onProgress(self, progress):
        self.progressBar.setValue(progress)
        slicer.app.processEvents()

    def onReferenceSelected(self, node, updateName=True):
        if node is not None:
            if updateName:
                self.outputNameField.setText(node.GetName() + " Inpainted")
            self.applyButton.enabled = True
        else:
            self.outputNameField.setText("")
            self.applyButton.enabled = False

    def onApplyClicked(self):
        self.applyButton.enabled = False
        segmentNode = self.inputWidget.mainInput.currentNode()
        imageNode = self.inputWidget.referenceInput.currentNode()
        selectedSegments = self.inputWidget.getSelectedSegments()

        if not selectedSegments:
            highlight_error(self.inputWidget.segmentListGroup[1])
            return

        labelMapNode = createTemporaryVolumeNode(slicer.vtkMRMLLabelMapVolumeNode, "mask")
        labelMapNode.CopyContent(segmentNode)
        slicer.modules.segmentations.logic().ExportVisibleSegmentsToLabelmapNode(segmentNode, labelMapNode, imageNode)

        outNode = slicer.vtkSlicerVolumesLogic().CloneVolume(
            slicer.mrmlScene, imageNode, self.outputNameField.text, False
        )

        try:
            self.logic.apply(imageNode, labelMapNode, selectedSegments, outNode, self.onProgress)
        except (ValueError, RuntimeError) as err:
            slicer.mrmlScene.RemoveNode(outNode)
            self.onReferenceSelected(self.inputWidget.referenceInput.currentNode(), updateName=False)
            if str(err) == "User cancelled":
                raise

            slicer.util.errorDisplay(str(err))
            raise

        self.progressBar.setValue(100)
        self.onReferenceSelected(self.inputWidget.referenceInput.currentNode(), updateName=False)


class CoreInpaintLogic(LTracePluginLogic):
    def __init__(self):
        LTracePluginLogic.__init__(self)

    def apply(self, imageNode, labelMapNode, selectedSegments, outNode, callback):
        image = slicer.util.arrayFromVolume(imageNode)
        mask = np.isin(slicer.util.arrayFromVolume(labelMapNode), [segment + 1 for segment in selectedSegments])

        has_color = image.shape[-1] == 3

        if has_color:
            patchmatch = PatchMatch(
                n_levels=4,
                n_iters=4,
                blend_dilation=7,
                blend_sigma=1.5,
                random_samples=128,
                patch_size=9,
                stride=7,
                similarity_by_mean=True,
                progress_callback=callback,
            )
        else:
            patchmatch = PatchMatch(
                n_levels=3,
                similarity_by_mean=False,
                progress_callback=callback,
            )

        factor = 2 ** (patchmatch.n_levels - 1)
        descaled_shape = tuple(dim // factor for dim in mask.shape)
        slices = tuple(slice(0, 1) if 1 < size <= patchmatch.patch_size else slice(None) for size in descaled_shape)

        original_shape = mask.shape

        image = image[slices]
        mask = mask[slices]

        def shape_to_str(shape):
            return "×".join(str(dim) for dim in shape)

        changed = sum(old != new for old, new in zip(original_shape, image.shape))
        if changed > 1:
            raise ValueError(
                f"Image of size {shape_to_str(original_shape)} is too small to inpaint. Each dimension must have at least {(patchmatch.patch_size+1) * factor} voxels."
            )

        if changed == 1:
            dialog = qt.QMessageBox()
            dialog.setWindowTitle("Warning")
            dialog.setText(
                f"Image of size {shape_to_str(original_shape)} is not currently supported for 3D inpainting because it is too thin. The image will be cropped to {shape_to_str(mask.shape)} and inpainted in 2D."
            )
            dialog.setInformativeText("Do you want to continue?")
            dialog.setStandardButtons(qt.QMessageBox.Ok | qt.QMessageBox.Cancel)
            dialog.setDefaultButton(qt.QMessageBox.Ok)
            dialog.setIcon(qt.QMessageBox.Warning)

            if dialog.exec_() != qt.QMessageBox.Ok:
                raise RuntimeError("User cancelled")

        filledVolumeArray = patchmatch(image, mask)
        slicer.util.updateVolumeFromArray(outNode, filledVolumeArray)
