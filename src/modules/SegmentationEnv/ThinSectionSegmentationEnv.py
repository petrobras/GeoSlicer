from SegmentationEnv import SegmentationEnv, SegmentationEnvWidget


class ThinSectionSegmentationEnv(SegmentationEnv):
    SETTING_KEY = "Thin Section Segmentation Environment"

    def __init__(self, parent):
        SegmentationEnv.__init__(self, parent)
        self.parent.title = "Thin Section Segmentation Tools"


class ThinSectionSegmentationEnvWidget(SegmentationEnvWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hasPetrography = True
