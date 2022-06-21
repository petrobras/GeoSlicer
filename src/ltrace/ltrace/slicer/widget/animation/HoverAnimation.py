import qt
from ltrace.slicer.widget.animation.BaseAnimation import BaseAnimation


class HoverAnimation(BaseAnimation):
    """Hover custom animation. Highlights the background."""

    def __init__(
        self,
        target: qt.QWidget,
        normalColor: qt.QColor = qt.QColor(85, 85, 85),
        highlightColor: qt.QColor = None,
        borderRadiusSize: qt.QSize = None,
        durationMs: float = 80,
        *args,
        **kwargs
    ) -> None:
        super().__init__(target, *args, **kwargs)
        self.currentColor = normalColor
        self.highlightColor = highlightColor
        self.borderRadiusSize = borderRadiusSize
        self.durationMs = durationMs

    def eventFilter(self, object: object, event: qt.QEvent) -> bool:
        """Custom event filter for qt events.

        Args:
            object (object): the sender's object reference
            event (qt.QEvent): the related qt.QEvent object.

        Returns:
            bool: True if event was completely handled and doesn't need to propagate,
                  False otherwise.
        """
        if event.type() == qt.QEvent.HoverEnter:
            self.animateHover(True)
        elif event.type() == qt.QEvent.HoverLeave:
            self.animateHover(False)
        elif event.type() == qt.QEvent.Paint:
            self.paintEvent(event)

        return self._widget.event(event)

    def paintEvent(self, event: qt.QPaintEvent) -> None:
        """Custom paint event handler.

        Args:
            event (qt.QPaintEvent): the qt.QPaintEvent object.
        """
        painter = qt.QStylePainter(self._widget)
        option = qt.QStyleOptionButton()

        option.state &= ~qt.QStyle.State_MouseOver

        painter.drawControl(qt.QStyle.CE_ShapedFrame, option)
        painter.setOpacity(0.25)

        if self.borderRadiusSize is None:
            painter.fillRect(self._widget.rect, self.currentColor)
        else:
            path = qt.QPainterPath()
            path.addRoundedRect(
                qt.QRectF(self._widget.rect), self.borderRadiusSize.width() - 1, self.borderRadiusSize.height() - 1
            )

        painter.fillPath(path, self.currentColor)

    def animateHover(self, entered: bool) -> None:
        """Hover animation handler method

        Args:
            entered (bool): the animation state.
        """
        if hasattr(self, "__hoverAnimation") and self.__hoverAnimation is not None:
            self.__hoverAnimation.stop()

        highlightColor = (
            self.highlightColor if self.highlightColor is not None else self._widget.palette.highlight().color()
        )
        self.__hoverAnimation = qt.QVariantAnimation(self._widget)
        self.__hoverAnimation.setDuration(self.durationMs)  # ms
        self.__hoverAnimation.setStartValue(self.currentColor)
        self.__hoverAnimation.setEndValue(highlightColor if entered else qt.QColor(85, 85, 85))

        def onValueChanged(value) -> None:
            self.currentColor = value
            self._widget.repaint()

        def onDestroyed() -> None:
            if hasattr(self, "__hoverAnimation"):
                self.__hoverAnimation = None
            self._widget.repaint()

        self.__hoverAnimation.valueChanged.connect(onValueChanged)
        self.__hoverAnimation.destroyed.connect(onDestroyed)
        self.__hoverAnimation.start(qt.QAbstractAnimation.DeleteWhenStopped)
