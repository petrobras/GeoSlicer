import slicer
import qt


class SlicerLayoutWindow(qt.QObject):
    """Slicer's layout window for customization with Qt objects. It provides a QWidget (centralWidget) in a basic layout for futher personalization."""

    def __init__(self, layoutId: int) -> None:
        super().__init__()
        self.__centralWidget = self.create_slicer_layout_item(tag="centralWidget")
        self.__layoutId = layoutId
        layoutManager = slicer.app.layoutManager()
        layoutXml = self.generate_layoutXml()
        layoutManager.layoutLogic().GetLayoutNode().AddLayoutDescription(self.__layoutId, layoutXml)
        layoutManager.setLayout(self.__layoutId)

    def generate_layoutXml(self) -> str:
        """
        Uses the viewDataList to build a layout with views in the correct order and types.
        """
        layout = """<layout type="vertical">"""
        layout += """<item><centralWidget></centralWidget></item>"""
        layout += """</layout>"""
        return layout

    def create_slicer_layout_item(self, tag: str) -> qt.QWidget:
        """
        Create a qt.QWidget object inside slicer's layout view.
        """
        viewFactory = slicer.qSlicerSingletonViewFactory()
        viewFactory.setTagName(tag)
        slicer.app.layoutManager().registerViewFactory(viewFactory)
        widget = qt.QWidget()
        widget.setAutoFillBackground(True)
        widget.setObjectName(tag)
        viewFactory.setWidget(widget)
        return widget

    @property
    def layoutId(self) -> int:
        return self.__layoutId

    @property
    def centralWidget(self) -> qt.QWidget:
        return self.__centralWidget
