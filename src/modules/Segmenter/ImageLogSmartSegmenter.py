from Segmenter import Segmenter, SegmenterWidget


class ImageLogSmartSegmenter(Segmenter):
    SETTING_KEY = "Image Log Smart Segmenter"


class ImageLogSmartSegmenterWidget(SegmenterWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.imageLogMode = True
