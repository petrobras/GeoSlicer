import qt
from abc import abstractmethod


class BaseAnimation(qt.QObject):
    """Base class for handling widget's animation.
       Auto-install custom event filter on the target widget for any customization.

    Args:
        target (qt.QWidget): the widget to be animated.
    """

    def __init__(self, target: qt.QWidget, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if target is None:
            raise RuntimeError("Please insert a valid QWidget as target.")

        self._widget = target
        self._widget.installEventFilter(self)

    @abstractmethod
    def eventFilter(self, object: object, event: qt.QEvent) -> bool:
        """Custom event filter for qt events.

        Args:
            object (object): the sender's object reference
            event (qt.QEvent): the related qt.QEvent object.

        Returns:
            bool: True if event was completely handled and doesn't need to propagate,
                  False otherwise.
        """
        return self._widget.event(event)
