import qt
import slicer

from ltrace.slicer.app import getApplicationVersion
from ltrace.slicer_utils import getResourcePath


class AboutDialog(qt.QDialog):
    def __init__(self, parent, *args, **kwargs) -> None:
        super().__init__(parent)

        self.setWindowTitle("About GeoSlicer")
        self.setWindowFlags(self.windowFlags() & ~qt.Qt.WindowContextHelpButtonHint)
        self.setWindowIcon(qt.QIcon((getResourcePath("Icons") / "GeoSlicer.ico").as_posix()))
        self.setFixedSize(600, 430)
        self.setupUi()
        self.setObjectName("GeoSlicer About Dialog")

    def setupUi(self) -> None:
        layout = qt.QVBoxLayout(self)

        pixMap = qt.QPixmap((getResourcePath("Icons") / "GeoSlicerLogo.png").as_posix())
        pixMap = pixMap.scaled(
            pixMap.width() // 10, pixMap.height() // 10, qt.Qt.KeepAspectRatio, qt.Qt.SmoothTransformation
        )
        logoLabel = qt.QLabel()
        logoLabel.setPixmap(pixMap)

        textBrowser = qt.QTextBrowser()
        textBrowser.setFixedSize(340, 370)
        textBrowser.setOpenExternalLinks(True)

        textBrowser.setFontPointSize(25)
        textBrowser.append("GeoSlicer")
        textBrowser.setFontPointSize(11)
        textBrowser.append("")
        textBrowser.append(getApplicationVersion())
        textBrowser.append("")
        textBrowser.insertHtml(slicer.modules.AppContextInstance.getAboutGeoSlicer())

        aboutQtButton = qt.QPushButton("About Qt")
        aboutQtButton.setAutoDefault(False)
        closeButton = qt.QPushButton("Close")
        closeButton.setAutoDefault(False)

        horizontalLayout = qt.QHBoxLayout()
        horizontalLayout.addWidget(logoLabel, 1, qt.Qt.AlignCenter)
        horizontalLayout.addWidget(textBrowser, 1, qt.Qt.AlignRight)

        buttonsLayout = qt.QHBoxLayout()
        buttonsLayout.addStretch(1)
        buttonsLayout.addWidget(aboutQtButton)
        buttonsLayout.addWidget(closeButton)

        layout.addLayout(horizontalLayout)
        layout.addLayout(buttonsLayout)
        self.setLayout(layout)

        # connections
        aboutQtButton.clicked.connect(self.__onAboutQtButtonClicked)
        closeButton.clicked.connect(self.__onCloseButtonClicked)

    def __onAboutQtButtonClicked(self):
        slicer.app.aboutQt()

    def __onCloseButtonClicked(self):
        self.close()
        self.deleteLater()

    def reject(self) -> None:
        self.__onCloseButtonClicked()
        qt.QDialog.reject(self)
