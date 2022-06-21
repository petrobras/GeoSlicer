import qt
from ltrace.slicer.widget.animation.BaseAnimation import BaseAnimation


class ScaleHoverAnimation(BaseAnimation):
    """Scale widget animation during hover event."""

    def __init__(self, target: qt.QWidget, scale: float = 1.05, duration_ms=150, *args, **kwargs) -> None:
        super().__init__(target, *args, **kwargs)
        self.zoomFactor = scale
        self.animation = qt.QPropertyAnimation(self._widget, "geometry")
        self.animation.setEasingCurve(qt.QEasingCurve(qt.QEasingCurve.InOutSine))
        self.animation.setDuration(duration_ms)
        self.__updatePositions()

    def __updatePositions(self) -> None:
        """Update geometry references (start/end value) to using during transform animation."""
        self.initialRect = self._widget.geometry
        self.finalRect = qt.QRect(
            0, 0, int(self.initialRect.width() * self.zoomFactor), int(self.initialRect.height() * self.zoomFactor)
        )
        self.finalRect.moveCenter(self.initialRect.center())

    def onEnterEvent(self, event: qt.QEvent) -> None:
        """Handles enter event in widget

        Args:
            event (qt.QEvent): the qt.QEvent object
        """
        self.animation.setStartValue(self.initialRect)
        self.animation.setEndValue(self.finalRect)
        self.animation.setDirection(qt.QAbstractAnimation.Forward)
        self.animation.start()

    def onLeaveEvent(self, event: qt.QEvent) -> None:
        """Handles leave event in widget

        Args:
            event (qt.QEvent): the qt.QEvent object
        """
        self.animation.setDirection(qt.QAbstractAnimation.Backward)
        self.animation.start()

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
            self.onEnterEvent(True)
        elif event.type() == qt.QEvent.HoverLeave:
            self.onLeaveEvent(False)
        elif event.type() == qt.QEvent.Move:
            self.onMoveEvent(event)

        return self._widget.event(event)

    def onMoveEvent(self, event: qt.QEvent) -> None:
        """Handles widget's move event.

        Args:
            event (qt.QEvent): the qt.QEvent object.
        """
        if self.animation.state == qt.QAbstractAnimation.Running:
            return

        self.__updatePositions()
