import numpy as np
import qt
from ltrace.slicer import widgets


class MultiscaleSingleShotWidget(widgets.SingleShotInputWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.mainName = kwargs.get("mainName")
        self.resolutions = []

        self.setup()

    def setup(self) -> None:
        self.resolutionsText = qt.QLabel("0 x 0 x 0 (mm)")
        self.resolutionsText.setToolTip(
            f"Resolution of {self.mainName.lower()} voxel in mm. For the multiscale simulations, the units are converted to micrometers"
        )
        self.resolutionsText.setObjectName(f"{self.mainName} Resolution Text")
        self.resolutionsText.hide()

        self.resolutionsLabel = qt.QLabel("Resolution:")
        self.resolutionsLabel.setObjectName(f"{self.mainName} Resolution Label")
        self.resolutionsLabel.hide()

        self.formLayout.addRow(self.resolutionsLabel, self.resolutionsText)

        self.onReferenceSelectedSignal.connect(self.onSourceChange)

    def onSourceChange(self, node=None):
        if node is not None:
            self.resolutions = np.array(node.GetSpacing())
            self.updateResolution(self.resolutions)
        else:
            self.updateResolution(None)

    def updateResolution(self, spacing):
        if spacing is not None:
            self.resolutionsText.setText(f"{spacing[0]:.3f} x {spacing[1]:.3f} x {spacing[2]:.3f} (mm)")
            self.resolutionsText.show()
            self.resolutionsLabel.show()
        else:
            self.resolutionsText.setText("0 x 0 x 0 (mm)")
            self.resolutionsText.hide()
            self.resolutionsLabel.hide()
