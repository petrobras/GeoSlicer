from SegmentationEnv import SegmentationEnv, SegmentationEnvWidget


class MicroCTSegmentationEnv(SegmentationEnv):
    SETTING_KEY = "Micro CT Segmentation Environment"

    def __init__(self, parent):
        SegmentationEnv.__init__(self, parent)
        self.parent.title = "Micro CT Segmentation Tools"


class MicroCTSegmentationEnvWidget(SegmentationEnvWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hasModelling = True
