"""Warn about accounts that were saved by an older GeoSlicer version.

TargetManager flags them when it loads the accounts file: their configuration
lacks keys the current account templates have. They are not updated in place
-- a job started by the older version may still depend on the old settings --
so the user is told to wrap up those jobs there, then create the account again.
"""

import html
from typing import List

import qt

BANNER_STYLE = "QLabel { background-color: #c62828; color: white; border-radius: 3px; padding: 8px; }"
TAG_STYLE = "QLabel { color: #e53935; font-weight: 600; }"


def _enumerate(names: List[str]) -> str:
    quoted = [f"“{html.escape(name)}”" for name in names]
    if len(quoted) == 1:
        return quoted[0]
    return ", ".join(quoted[:-1]) + " and " + quoted[-1]


def outdatedMessage(names: List[str]) -> str:
    """The advice for these accounts, as rich text."""
    single = len(names) == 1
    return (
        f"<b>{_enumerate(names)} {'was' if single else 'were'} configured in an older version of GeoSlicer.</b> "
        f"If {'it has' if single else 'they have'} jobs, collect their results or cancel them in that older "
        f"version first. Then, in this version, remove {'the account' if single else 'these accounts'} and "
        f"create {'it' if single else 'them'} again."
    )


def outdatedTooltip() -> str:
    return (
        "Configured in an older version of GeoSlicer. Collect or cancel its jobs in that version, "
        "then remove this account and create it again."
    )


class OutdatedHostsBanner(qt.QLabel):
    """A red banner naming the outdated accounts. Hidden while there are none."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("OutdatedHostsBanner")
        self.setWordWrap(True)
        self.setTextFormat(qt.Qt.RichText)
        self.setStyleSheet(BANNER_STYLE)
        self.setHosts([])

    def setHosts(self, names: List[str]) -> None:
        self.setText(outdatedMessage(names) if names else "")
        self.setVisible(bool(names))


def outdatedTag(parent=None) -> qt.QLabel:
    """A short red marker for the row of an outdated account."""
    tag = qt.QLabel("Older version", parent)
    tag.setStyleSheet(TAG_STYLE)
    tag.setToolTip(outdatedTooltip())
    return tag
