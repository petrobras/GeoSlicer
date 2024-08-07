from Segmenter import Segmenter, SegmenterWidget


class ImageLogSmartSegmenter(Segmenter):
    SETTING_KEY = "Image Log Smart Segmenter"


class ImageLogSmartSegmenterWidget(SegmenterWidget):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.imageLogMode = True
