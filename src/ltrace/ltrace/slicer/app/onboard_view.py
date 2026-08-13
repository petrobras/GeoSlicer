"""
Custom GeoSlicer onboarding view.

Replaces the legacy ``ui_DataLoaderSelectorDialog`` (see ``onboard.py``).

Implementation note: an earlier version of this module registered a custom
Slicer layout ID with a ``qSlicerSingletonViewFactory``. That worked the first
time the layout was shown, but Slicer's singleton factory is not built for
repeated entry/exit — re-parenting the widget across many layout switches
left Qt's paint state in an inconsistent state and produced black squares
over the UI. We now keep an :class:`OnboardWidget` parented to the active
layout's viewport (``layoutManager.viewport()``) and toggle its visibility
on demand. The widget covers whatever layout is underneath while shown,
and clearing it on environment start reveals the normal layout views again.

The view shows two columns:

  * START / RECENT   — the environment launchers (one click enters an
    environment, like the old "Start a project" button), the two project-open
    actions (``.mrml`` / ``.nc``), and the recently loaded files.
  * SECOND COLUMN    — a swappable panel: the WALKTHROUGHS page (Learn the
    Fundamentals + What's New) is shown by default, and hovering an
    environment launcher swaps it to that environment's capability preview.

A footer at the bottom-right shows ``<version> · <build-date> · LTrace``.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import qt
import slicer

from ltrace.slicer.app import (
    MANUAL_BASE_URL,
    getApplicationInfo,
    getApplicationVersion,
)
from ltrace.slicer.app.onboard import LOADERS, LoaderInfo, getLastEnvironment, loadEnvironment
from ltrace.slicer.helpers import svgToQIcon
from ltrace.slicer.ui import LineSeparator

YOUTUBE_CHANNEL_URL = "https://www.youtube.com/@ltracegeo/featured"

# QSettings key holding a JSON dict of {absolute path: env display name}.
PATH_ENV_SETTINGS_KEY = "GeoSlicer/RecentFileEnvironment"

# Grace period before an environment preview falls back to Walkthroughs on
# hover-out. Sliding between adjacent launchers fires leave-then-enter with a
# gap in between; deferring the revert lets the next enter cancel it so the
# preview swaps directly instead of flashing Walkthroughs.
_PREVIEW_REVERT_DELAY_MS = 180


# ---------------------------------------------------------------------------
# Environment intro content
# ---------------------------------------------------------------------------


@dataclass
class EnvironmentIntro:
    summary: str
    features: List[str] = field(default_factory=list)


ENVIRONMENT_INTROS: Dict[str, EnvironmentIntro] = {
    "Volumes": EnvironmentIntro(
        summary=(
            "Process and analyse micro-CT 3D rock volumes. Crop, register, "
            "segment and run pore-network or microtom simulations to extract "
            "petrophysical properties from digital rock samples."
        ),
        features=[
            "Volume loaders (MicroCT, RAW, NetCDF)",
            "Manual and automatic registration",
            "Segmentation and modelling tools",
            "Pore network extraction and simulation",
            "Microtom remote workflows",
            "Big-image and multiscale processing",
        ],
    ),
    "Thin Section": EnvironmentIntro(
        summary=(
            "Inspect and segment thin-section images. Register paired "
            "transmitted/reflected captures, import QEMSCAN data, and extract "
            "mineralogy or porosity from petrographic images."
        ),
        features=[
            "Thin Section and QEMSCAN loaders",
            "Crop and registration",
            "Segmentation tools",
            "Charts and quantitative analysis",
        ],
    ),
    "Core": EnvironmentIntro(
        summary=(
            "Visualise full-bore core CTs. Unwrap, transform, crop and "
            "segment longitudinal core scans for facies analysis and "
            "downstream image-log integration."
        ),
        features=[
            "Multicore loader",
            "Multicore transforms",
            "Crop volume",
            "Segmentation tools",
        ],
    ),
    "Well Logs": EnvironmentIntro(
        summary=(
            "Load DLIS, LAS and CSV well-log curves alongside borehole image "
            "logs. Filter spirals, compute eccentricity and quality, segment "
            "fractures and model permeability along depth."
        ),
        features=[
            "DLIS / LAS / CSV import",
            "Spiral filter and eccentricity",
            "Quality indicator",
            "Manual, instance and inspector segmentation",
            "Unwrap registration",
            "Permeability modelling",
        ],
    ),
    "Multiscale": EnvironmentIntro(
        summary=(
            "Combine multi-resolution imagery into a single petrophysical "
            "model. Train and apply MPS or SinGAN generators to upscale "
            "features from thin section to core to whole-image resolution."
        ),
        features=[
            "Multi-resolution data wrangling",
            "MPS workflow",
            "SinGAN model integration",
            "Post-processing tools",
        ],
    ),
}


# ---------------------------------------------------------------------------
# Path → environment persistence
# ---------------------------------------------------------------------------


def _loadPathEnvMap() -> Dict[str, str]:
    raw = slicer.app.userSettings().value(PATH_ENV_SETTINGS_KEY, "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def _savePathEnvMap(mapping: Dict[str, str]) -> None:
    slicer.app.userSettings().setValue(PATH_ENV_SETTINGS_KEY, json.dumps(mapping))


def recordEnvironmentForPath(path: str, envName: str) -> None:
    """Persist the environment last used for ``path``.

    Keeps the map bounded to the most recent 64 entries to avoid unbounded growth.
    """
    if not path or not envName:
        return
    try:
        normalized = str(Path(path).resolve())
    except OSError:
        normalized = path

    mapping = _loadPathEnvMap()
    mapping.pop(normalized, None)
    mapping[normalized] = envName
    if len(mapping) > 64:
        # Drop oldest insertion order entries.
        for key in list(mapping.keys())[:-64]:
            mapping.pop(key, None)
    _savePathEnvMap(mapping)


def getEnvironmentForPath(path: str) -> Optional[str]:
    if not path:
        return None
    try:
        normalized = str(Path(path).resolve())
    except OSError:
        normalized = path
    mapping = _loadPathEnvMap()
    return mapping.get(normalized) or mapping.get(path)


# ---------------------------------------------------------------------------
# NetCDF evaluation (suggest an environment from a NetCDF/HDF5 file)
# ---------------------------------------------------------------------------


# Environment-suggestion thresholds (tunable). Coordinates are in millimetres,
# so 50 micrometres == 0.05.
_WELL_LOGS_SPACING_RATIO = 7.0  # 2D: max/min axis spacing >= this -> image log
_CORE_ELONGATION_RATIO = 5.0  # 3D: longest physical extent >= this x the next
_CORE_COARSE_SPACING_MM = 0.05  # 3D: voxel spacing above this (50 um) is core-scale


def _axis_spacing(array: "xr.DataArray", dim: str) -> float:
    """Spacing (coordinate delta) for ``dim`` in millimetres, 1.0 if unknown.

    Reads only the (small, eager) coordinate — never the variable's data.
    """
    coord = array.coords.get(dim)
    if coord is None or coord.size < 2:
        return 1.0
    try:
        return abs(float(coord.values[1] - coord.values[0]))
    except (TypeError, ValueError, IndexError):
        return 1.0


def _classifyNetcdfVariable(array: "xr.DataArray") -> Optional[str]:
    """Guess the environment for a single NetCDF variable from its geometry.

    Uses only metadata (dims, sizes, coordinate spacing) — it never reads the
    array data. Returns a LOADERS display name, or None when the variable is
    not a classifiable image/volume (table columns, fewer than 2 spatial dims).
    """
    dims = list(array.dims)
    if not dims or dims[0].startswith("table__"):
        return None

    has_channel = "c" in dims
    spatial = [d for d in dims if d != "c"]

    # Vector / RGB data (a colour channel) is thin-section imagery.
    if has_channel:
        return "Thin Section"

    if len(spatial) == 2:
        spacings = [_axis_spacing(array, d) for d in spatial]
        low = min(spacings)
        if low > 0 and max(spacings) / low >= _WELL_LOGS_SPACING_RATIO:
            return "Well Logs"
        return "Thin Section"

    if len(spatial) >= 3:
        axes = spatial[:3]
        spacings = [_axis_spacing(array, d) for d in axes]
        extents = sorted((array.sizes[d] * sp for d, sp in zip(axes, spacings)), reverse=True)
        elongated = extents[1] > 0 and extents[0] / extents[1] >= _CORE_ELONGATION_RATIO
        coarse = max(spacings) > _CORE_COARSE_SPACING_MM
        return "Core" if (elongated and coarse) else "Volumes"

    return None


def _suggestEnvForDataset(dataset: "xr.Dataset") -> List[str]:
    """Suggest an environment for an already-open dataset.

    Returns a single-element list when one environment is determined,
    ``["Multiscale"]`` when an image log is combined with another type, or an
    empty list when ambiguous / undetermined (the caller shows the picker).
    """
    envs: List[str] = []
    for name in dataset.data_vars:
        env = _classifyNetcdfVariable(dataset[name])
        if env is not None and env not in envs:
            envs.append(env)

    if not envs:
        return []
    if len(envs) == 1:
        return envs
    if "Well Logs" in envs:  # image log + another type -> Multiscale
        return ["Multiscale"]
    return []  # ambiguous multi-type -> let the user pick


def _suggestEnvForNetcdf(path: Path) -> List[str]:
    """Suggest an environment for a NetCDF/HDF5 file without loading its data.

    Returns a single-element list when one environment is determined (the
    caller enters it automatically), or an empty list when ambiguous or
    unreadable (the caller shows the environment picker).
    """
    try:
        import xarray as xr  # netcdf is optional but available at runtime

        with xr.open_dataset(path, engine="h5netcdf", backend_kwargs={"lock": False}) as dataset:
            return _suggestEnvForDataset(dataset)
    except Exception:
        return []


def _notifyAutoSelectedEnvironment(displayName: str) -> None:
    """Tell the user an environment was chosen automatically for their project."""
    slicer.util.infoDisplay(
        f"The '{displayName}' environment was selected automatically based on the "
        f"project data.\n\nYou can switch environments at any time using the "
        f"environment selector in the top toolbar.",
        "Environment selected",
    )


def _isGeoslicerNetcdf(path: Path) -> bool:
    try:
        import xarray as xr

        with xr.open_dataset(path, engine="h5netcdf", backend_kwargs={"lock": False}) as dataset:
            return "geoslicer_version" in dataset.attrs
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iconsRoot() -> Path:
    return Path(slicer.app.slicerHome) / "LTrace" / "Resources" / "Icons"


def _svgIcon(name: str) -> qt.QIcon:
    iconPath = _iconsRoot() / "svg" / name
    if iconPath.exists():
        return svgToQIcon(iconPath)
    return qt.QIcon()


def _formatBytes(numBytes: float) -> str:
    if numBytes is None:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(numBytes)
    # Iterate every unit but the last: as soon as the value fits, return it.
    # If the loop is exhausted the value is >= 1 TB, so the trailing return
    # (the largest unit) is the reachable fall-through — no dead path.
    for unit in units[:-1]:
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} {units[-1]}"


def _pathSize(path: Path) -> Optional[int]:
    try:
        if path.is_dir():
            total = 0
            for root, _dirs, files in os.walk(path):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        continue
            return total
        if path.exists():
            return path.stat().st_size
    except OSError:
        return None
    return None


def _ellipsizeMiddle(text: str, maxLen: int = 64) -> str:
    if len(text) <= maxLen:
        return text
    head = (maxLen - 1) // 2
    tail = maxLen - 1 - head
    return f"{text[:head]}…{text[-tail:]}"


def _environmentForFile(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".mrml":
        return "Project"
    if suffix == ".nc":
        return "NetCDF"
    if suffix in (".dcm", ".dicom"):
        return "DICOM"
    if suffix in (".las", ".dlis"):
        return "Well Logs"
    return suffix.lstrip(".").upper() or "File"


def _readChangelogLatest() -> str:
    changelogPath = Path(slicer.app.slicerHome) / "LTrace" / "CHANGELOG"
    if not changelogPath.exists():
        # Best-effort fallback when running from source / dev.
        candidates = [
            Path(__file__).resolve().parents[5] / "CHANGELOG",
            Path(__file__).resolve().parents[6] / "CHANGELOG",
        ]
        for candidate in candidates:
            if candidate.exists():
                changelogPath = candidate
                break
        else:
            return "No changelog available."

    try:
        text = changelogPath.read_text(encoding="utf-8")
    except OSError:
        return "Unable to read the changelog."

    sections = re.split(r"^# ", text, flags=re.MULTILINE)
    sections = [s for s in sections if s.strip()]
    if not sections:
        return text
    return "# " + sections[0].strip()


def _markdownToHtml(markdown: str) -> str:
    """Tiny markdown subset → HTML so we can avoid a markdown dependency."""

    lines = markdown.splitlines()
    html: List[str] = []
    inList = False

    def closeList():
        nonlocal inList
        if inList:
            html.append("</ul>")
            inList = False

    for raw in lines:
        line = raw.rstrip()
        if not line:
            closeList()
            html.append("")
            continue
        if line.startswith("# "):
            closeList()
            html.append(f"<h2 style='margin:0 0 8px 0;'>{line[2:].strip()}</h2>")
        elif line.startswith("## "):
            closeList()
            html.append(f"<h3 style='margin:14px 0 4px 0;color:#bbb;font-weight:600;'>" f"{line[3:].strip()}</h3>")
        elif line.startswith("- "):
            if not inList:
                html.append("<ul style='margin:4px 0 4px 18px;padding:0;'>")
                inList = True
            html.append(f"<li>{line[2:].strip()}</li>")
        else:
            closeList()
            html.append(f"<p style='margin:4px 0;'>{line}</p>")
    closeList()
    return "\n".join(html)


def _buildFooterText() -> str:
    parts = []
    version = getApplicationVersion()
    if version:
        parts.append(version)

    buildTimeRaw = getApplicationInfo("GEOSLICER_BUILD_TIME")
    if buildTimeRaw:
        try:
            buildTime = datetime.strptime(buildTimeRaw, "%Y-%m-%d %H:%M:%S.%f")
            parts.append(buildTime.strftime("%Y-%m-%d"))
        except (ValueError, TypeError):
            pass

    parts.append("LTrace")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Section header
# ---------------------------------------------------------------------------


class _SectionHeader(qt.QLabel):
    """Uppercase, non-bold section header."""

    def __init__(self, text: str, parent=None):
        super().__init__(text.upper(), parent)
        self.setStyleSheet(
            "QLabel { color: #9a9a9a; letter-spacing: 1px; " "padding: 0; margin: 0; font-weight: normal; }"
        )


# ---------------------------------------------------------------------------
# Action button
# ---------------------------------------------------------------------------


class _ActionButton(qt.QPushButton):
    """Flat row-style button with leading icon and left-aligned label."""

    def __init__(self, text: str, icon: qt.QIcon, parent=None):
        super().__init__(icon, "  " + text, parent)
        self.setIconSize(qt.QSize(20, 20))
        self.setCursor(qt.Qt.PointingHandCursor)
        self.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Fixed)
        self.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 3px;
                color: #ddd;
                /* No left padding so the icon/label lines up flush with the
                   section header above (which has zero padding). */
                padding: 6px 10px 6px 0px;
                text-align: left;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 24);
            }
            QPushButton:pressed {
                background: rgba(255, 255, 255, 40);
            }
            QPushButton:checked {
                background: rgba(255, 255, 255, 36);
                border-color: rgba(255, 255, 255, 50);
                color: #fff;
            }
            """
        )


# ---------------------------------------------------------------------------
# Environment launcher
# ---------------------------------------------------------------------------


class _EnvironmentButton(_ActionButton):
    """Flat row launcher for an environment that previews it on hover.

    Clicking launches the environment; entering/leaving the button asks the
    parent view to show/clear the environment preview in the second column.
    """

    previewRequested = qt.Signal(str)  # emits the environment display name
    previewCleared = qt.Signal()

    def __init__(self, displayName: str, icon: qt.QIcon, parent=None):
        super().__init__(displayName, icon, parent)
        self.__displayName = displayName

    def enterEvent(self, event):
        self.previewRequested.emit(self.__displayName)

    def leaveEvent(self, event):
        self.previewCleared.emit()


# ---------------------------------------------------------------------------
# Recent file row
# ---------------------------------------------------------------------------


class _RecentItemWidget(qt.QFrame):
    """Single recent-file row: name, environment badge, path, size."""

    activated = qt.Signal(object)  # emits the underlying QAction

    def __init__(self, action: qt.QAction, parent=None):
        super().__init__(parent)
        self.__action = action

        path = Path(action.text)
        envLabel = getEnvironmentForPath(action.text) or _environmentForFile(path)
        size = _pathSize(path)
        sizeText = _formatBytes(size) if size is not None else "—"

        self.setObjectName("RecentItem")
        self.setCursor(qt.Qt.PointingHandCursor)
        self.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Fixed)
        self.setStyleSheet(
            """
            QFrame#RecentItem {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 3px;
            }
            QFrame#RecentItem:hover {
                background: rgba(255, 255, 255, 16);
                border-color: rgba(255, 255, 255, 30);
            }
            """
        )

        layout = qt.QGridLayout(self)
        layout.setContentsMargins(0, 6, 8, 6)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(2)

        nameLabel = qt.QLabel(path.name or path.as_posix())
        nameLabel.setStyleSheet("color: #eee; font-weight: 600;")

        envBadge = qt.QLabel(envLabel)
        envBadge.setStyleSheet(
            "background: rgba(255,255,255,30); color: #ddd; " "padding: 1px 6px; border-radius: 8px; font-size: 10px;"
        )
        envBadge.setSizePolicy(qt.QSizePolicy.Fixed, qt.QSizePolicy.Fixed)

        pathLabel = qt.QLabel(_ellipsizeMiddle(path.as_posix(), 60))
        pathLabel.setToolTip(path.as_posix())
        pathLabel.setStyleSheet("color: #999; font-size: 11px;")

        sizeLabel = qt.QLabel(sizeText)
        sizeLabel.setStyleSheet("color: #999; font-size: 11px;")
        sizeLabel.setAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)

        layout.addWidget(nameLabel, 0, 0)
        layout.addWidget(envBadge, 0, 1, qt.Qt.AlignRight)
        layout.addWidget(pathLabel, 1, 0)
        layout.addWidget(sizeLabel, 1, 1, qt.Qt.AlignRight)
        layout.setColumnStretch(0, 1)

    def mouseReleaseEvent(self, event):
        # Note: PythonQt does not expose ``super().mouseReleaseEvent`` for Qt
        # event handlers; QFrame's default does nothing useful here, so we
        # don't chain it.
        if event.button() == qt.Qt.LeftButton:
            self.activated.emit(self.__action)


# ---------------------------------------------------------------------------
# Onboard widget
# ---------------------------------------------------------------------------


class OnboardWidget(qt.QWidget):
    """Two-column onboarding screen embedded in the layout view."""

    closeRequested = qt.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.objectName = "OnboardWidget"
        self.__toolbar = None
        # "Picker" mode: an environment must be chosen for an already-loaded
        # project (undetected/ambiguous). In this mode clicking an environment
        # enters it directly instead of starting a fresh project.
        self.__pickerMode = False
        self.__pendingNetcdfPath: Optional[Path] = None
        self.__envButtons: Dict[str, _EnvironmentButton] = {}

        # Single-shot debounce so quickly moving between environment launchers
        # swaps their previews directly instead of flashing Walkthroughs.
        self.__previewClearTimer = qt.QTimer(self)
        self.__previewClearTimer.objectName = "Onboard Preview Revert Timer"
        self.__previewClearTimer.setSingleShot(True)
        self.__previewClearTimer.setInterval(_PREVIEW_REVERT_DELAY_MS)
        self.__previewClearTimer.timeout.connect(self.__doClearPreview)

        self.__buildUi()

    # -- public API -------------------------------------------------------

    def setToolbar(self, toolbar):
        self.__toolbar = toolbar

    def toolbar(self):
        return self.__toolbar

    def refresh(self):
        self.__refreshRecentList()
        if not self.__pickerMode:
            self.__showWalkthroughs()

    def setDataTypesOnly(self, enabled: bool, suggestedEnvs: Optional[List[str]] = None) -> None:
        """Environment-picker mode for an already-loaded project.

        When ``enabled``, only the environment launchers remain in the first
        column (optionally filtered to ``suggestedEnvs``); the project-open
        actions and the recent list are hidden, clicking an environment enters
        it directly (rather than starting a fresh project), and the Back button
        is shown so the user can return to the regular onboarding view.
        """
        self.__pickerMode = enabled

        self.__startHeader.setText(("Choose a data type" if enabled else "Start").upper())
        self.__openSeparator.setVisible(not enabled)
        self.__openMrmlButton.setVisible(not enabled)
        self.__openNetcdfButton.setVisible(not enabled)
        self.__recentHeader.setVisible(not enabled)
        self.__recentScroll.setVisible(not enabled)
        self.__backBtn.setVisible(enabled)

        self.__filterEnvironments(suggestedEnvs)

        if enabled:
            self.__showPickerHint()
        else:
            self.__pendingNetcdfPath = None
            self.__showWalkthroughs()

    def closeRequest(self) -> None:
        self.closeRequested.emit()

    # -- ui ---------------------------------------------------------------

    def __buildUi(self):
        self.setAutoFillBackground(True)
        rootLayout = qt.QVBoxLayout(self)
        rootLayout.setContentsMargins(28, 12, 28, 14)
        rootLayout.setSpacing(12)

        rootLayout.addWidget(self.__buildHeader())

        # Body: a horizontally-centered, max-width block holding the two
        # columns. The top/bottom stretches (2 : 3) push the block just above
        # the vertical centre, leaving clear space at the top.
        rootLayout.addStretch(1)

        centerRow = qt.QHBoxLayout()
        centerRow.setContentsMargins(0, 0, 0, 0)
        centerRow.setSpacing(0)
        centerRow.addStretch(1)

        centerFrame = qt.QFrame()
        centerFrame.setObjectName("OnboardCenterFrame")
        centerFrame.setMaximumWidth(1736)
        centerFrame.setMinimumHeight(680)
        centerLayout = qt.QHBoxLayout(centerFrame)
        centerLayout.setContentsMargins(0, 0, 0, 0)
        centerLayout.setSpacing(32)

        self.__startColumn = self.__buildStartColumn()
        self.__secondColumn = self.__buildSecondColumn()
        for col in (self.__startColumn, self.__secondColumn):
            col.setMinimumWidth(560)

        centerLayout.addWidget(self.__startColumn, 1)
        centerLayout.addWidget(self.__secondColumn, 1)

        centerRow.addWidget(centerFrame, 0)
        centerRow.addStretch(1)

        rootLayout.addLayout(centerRow, 0)
        rootLayout.addStretch(4)

        footer = qt.QLabel(_buildFooterText())
        footer.setObjectName("OnboardFooter")
        footer.setAlignment(qt.Qt.AlignRight | qt.Qt.AlignVCenter)
        footer.setStyleSheet("color: #888; font-size: 11px;")
        rootLayout.addWidget(footer)

    def __buildHeader(self) -> qt.QWidget:
        header = qt.QFrame()
        layout = qt.QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        headerButtonStyle = """
            QToolButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 3px;
                padding: 4px 8px;
                color: #ddd;
            }
            QToolButton:hover {
                background: rgba(255, 255, 255, 24);
            }
            """

        self.__backBtn = qt.QToolButton()
        self.__backBtn.objectName = "Onboard Back Button"
        self.__backBtn.setIcon(_svgIcon("ArrowLeft.svg"))
        self.__backBtn.setIconSize(qt.QSize(18, 18))
        self.__backBtn.setText(" Back")
        self.__backBtn.setToolButtonStyle(qt.Qt.ToolButtonTextBesideIcon)
        self.__backBtn.setCursor(qt.Qt.PointingHandCursor)
        self.__backBtn.setToolTip("Back to onboarding")
        self.__backBtn.setStyleSheet(headerButtonStyle)
        self.__backBtn.clicked.connect(self.__onBackClicked)
        self.__backBtn.setVisible(False)
        layout.addWidget(self.__backBtn)

        layout.addStretch(1)

        closeBtn = qt.QToolButton()
        closeBtn.objectName = "Onboard Close Button"
        closeBtn.setIcon(_svgIcon("Close.svg"))
        closeBtn.setIconSize(qt.QSize(18, 18))
        closeBtn.setCursor(qt.Qt.PointingHandCursor)
        closeBtn.setToolTip("Close onboarding (Esc)")
        closeBtn.setStyleSheet(headerButtonStyle)
        closeBtn.clicked.connect(self.closeRequest)
        layout.addWidget(closeBtn)
        return header

    def __onBackClicked(self) -> None:
        # Leave picker mode and re-show the regular onboarding view.
        OnboardLayout.show(self.__toolbar)

    # -- columns ----------------------------------------------------------

    def __buildStartColumn(self) -> qt.QWidget:
        col = qt.QFrame()
        col.objectName = "OnboardStartColumn"
        layout = qt.QVBoxLayout(col)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.__startHeader = _SectionHeader("Start")
        layout.addWidget(self.__startHeader)

        # Environment launchers — one click enters the environment.
        self.__envButtons = {}
        for displayName, loader in LOADERS.items():
            button = _EnvironmentButton(displayName, qt.QIcon(loader.icon.as_posix()))
            button.objectName = f"{displayName} Environment Button"
            intro = ENVIRONMENT_INTROS.get(displayName)
            button.setToolTip(intro.summary if intro else loader.description)
            button.clicked.connect(lambda checked=False, name=displayName: self.__onEnvironmentLaunch(name))
            button.previewRequested.connect(self.__previewEnvironment)
            button.previewCleared.connect(self.__clearPreview)
            layout.addWidget(button)
            self.__envButtons[displayName] = button

        self.__openSeparator = LineSeparator()
        layout.addWidget(self.__openSeparator)

        self.__openMrmlButton = _ActionButton("Open Project (.mrml)", _svgIcon("Project.svg"))
        self.__openMrmlButton.objectName = "Open Project Button"
        self.__openMrmlButton.clicked.connect(self.__onOpenMrmlProject)
        layout.addWidget(self.__openMrmlButton)

        self.__openNetcdfButton = _ActionButton("Open NetCDF4 Project (.nc)", _svgIcon("Open.svg"))
        self.__openNetcdfButton.objectName = "Open NetCDF Project Button"
        self.__openNetcdfButton.clicked.connect(self.__onOpenNetcdfProject)
        layout.addWidget(self.__openNetcdfButton)

        layout.addSpacing(12)
        self.__recentHeader = _SectionHeader("Recent")
        layout.addWidget(self.__recentHeader)

        self.__recentScroll = qt.QScrollArea()
        self.__recentScroll.setWidgetResizable(True)
        self.__recentScroll.setFrameShape(qt.QFrame.NoFrame)
        self.__recentScroll.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        self.__recentScroll.setStyleSheet("QScrollArea { background: transparent; }")

        self.__recentContainer = qt.QWidget()
        self.__recentLayout = qt.QVBoxLayout(self.__recentContainer)
        self.__recentLayout.setContentsMargins(0, 0, 0, 0)
        self.__recentLayout.setSpacing(2)
        self.__recentLayout.addStretch(1)

        self.__recentScroll.setWidget(self.__recentContainer)
        layout.addWidget(self.__recentScroll, 1)

        # Keeps the content top-anchored when the recent scroll (the stretchy
        # element) is hidden in picker mode. Stretch 0 means it yields all
        # surplus to the recent scroll in full mode, so nothing shifts there.
        layout.addStretch(0)

        return col

    def __buildSecondColumn(self) -> qt.QWidget:
        col = qt.QFrame()
        col.objectName = "OnboardSecondColumn"
        layout = qt.QVBoxLayout(col)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.__secondHeader = _SectionHeader("Walkthroughs")
        layout.addWidget(self.__secondHeader)

        self.__contentStack = qt.QStackedWidget()
        self.__contentStack.objectName = "Onboard Content Stack"
        self.__pageWalkthroughs = self.__buildWalkthroughsPage()
        self.__pageEnvironment = self.__buildEnvironmentPage()
        self.__pagePickerHint = self.__buildPickerHintPage()

        self.__contentStack.addWidget(self.__pageWalkthroughs)
        self.__contentStack.addWidget(self.__pageEnvironment)
        self.__contentStack.addWidget(self.__pagePickerHint)

        layout.addWidget(self.__contentStack, 1)
        return col

    def __filterEnvironments(self, suggested: Optional[List[str]]) -> None:
        """Hide environment launchers not in ``suggested`` (None → show all)."""
        for displayName, button in self.__envButtons.items():
            button.setVisible(suggested is None or displayName in suggested)

    # -- second-column pages ----------------------------------------------

    def __buildWalkthroughsPage(self) -> qt.QWidget:
        page = qt.QWidget()
        layout = qt.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # ---- Learn the Fundamentals ----
        title = qt.QLabel("Learn the Fundamentals")
        title.setStyleSheet("color: #eee; font-size: 16px;")
        layout.addWidget(title)

        intro = qt.QLabel(
            "GeoSlicer is a digital-rock platform for geoscientists — it brings "
            "micro-CT, thin section, core and well-log workflows under one roof "
            "so you can register, segment, model and quantify rock samples without "
            "switching tools."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #ccc;")
        layout.addWidget(intro)

        docsBtn = _ActionButton("GeoSlicer documentation", _svgIcon("BookOpen.svg"))
        docsBtn.objectName = "Open Documentation Button"
        docsBtn.clicked.connect(lambda: qt.QDesktopServices.openUrl(qt.QUrl(MANUAL_BASE_URL)))
        layout.addWidget(docsBtn)

        youtubeBtn = _ActionButton("GeoSlicer on YouTube", _svgIcon("Youtube.svg"))
        youtubeBtn.objectName = "Open Youtube Button"
        youtubeBtn.clicked.connect(lambda: qt.QDesktopServices.openUrl(qt.QUrl(YOUTUBE_CHANNEL_URL)))
        layout.addWidget(youtubeBtn)

        layout.addWidget(LineSeparator())

        # ---- What's New ----
        whatsNewLabel = qt.QLabel("What's New")
        whatsNewLabel.setStyleSheet("color: #eee; font-size: 16px;")
        layout.addWidget(whatsNewLabel)

        self.__whatsNewBrowser = qt.QTextBrowser()
        self.__whatsNewBrowser.setObjectName("Whats New Browser")
        self.__whatsNewBrowser.setOpenExternalLinks(True)
        self.__whatsNewBrowser.setFrameShape(qt.QFrame.NoFrame)
        self.__whatsNewBrowser.setStyleSheet("QTextBrowser { background: transparent; border: none; color: #ddd; }")
        layout.addWidget(self.__whatsNewBrowser, 1)
        return page

    def __buildEnvironmentPage(self) -> qt.QWidget:
        page = qt.QWidget()
        layout = qt.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.__envTitle = qt.QLabel("")
        self.__envTitle.setObjectName("Onboard Env Title")
        self.__envTitle.setStyleSheet("color: #eee; font-size: 18px;")
        layout.addWidget(self.__envTitle)

        self.__envSummary = qt.QLabel("")
        self.__envSummary.setWordWrap(True)
        self.__envSummary.setStyleSheet("color: #ccc;")
        layout.addWidget(self.__envSummary)

        featuresLabel = qt.QLabel("What you can do")
        featuresLabel.setStyleSheet("color: #aaa; letter-spacing: 1px; margin-top: 8px;")
        layout.addWidget(featuresLabel)

        self.__envFeatures = qt.QLabel("")
        self.__envFeatures.setWordWrap(True)
        self.__envFeatures.setTextFormat(qt.Qt.RichText)
        self.__envFeatures.setStyleSheet("color: #ccc;")
        layout.addWidget(self.__envFeatures)

        layout.addStretch(1)
        return page

    def __buildPickerHintPage(self) -> qt.QWidget:
        page = qt.QWidget()
        layout = qt.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        hint = qt.QLabel("Select an environment to open your project.")
        hint.setWordWrap(True)
        hint.setAlignment(qt.Qt.AlignTop)
        hint.setStyleSheet("color: #ccc; font-size: 14px;")
        layout.addWidget(hint)

        layout.addStretch(1)
        return page

    # -- recent list ------------------------------------------------------

    def __recentMenu(self) -> Optional[qt.QMenu]:
        mainWindow = slicer.modules.AppContextInstance.mainWindow
        fileMenu = mainWindow.findChild("QMenu", "FileMenu")
        if fileMenu is None:
            return None
        return fileMenu.findChild("QMenu", "RecentlyLoadedMenu")

    def __refreshRecentList(self) -> None:
        # Drop existing rows (keep the trailing stretch).
        while self.__recentLayout.count() > 1:
            child = self.__recentLayout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        recentMenu = self.__recentMenu()
        actions: List[qt.QAction] = []
        if recentMenu is not None:
            for action in recentMenu.actions():
                if not action.text:
                    continue
                if action.text == "Clear History":
                    continue
                if action.isSeparator():
                    continue
                actions.append(action)

        if not actions:
            empty = qt.QLabel("No recent files yet.")
            empty.setStyleSheet("color: #888; padding: 12px 4px;")
            self.__recentLayout.insertWidget(self.__recentLayout.count() - 1, empty)
            return

        for action in actions:
            row = _RecentItemWidget(action)
            row.activated.connect(self.__onRecentActivated)
            self.__recentLayout.insertWidget(self.__recentLayout.count() - 1, row)

    # -- callbacks --------------------------------------------------------

    def __onRecentActivated(self, action: qt.QAction) -> None:
        if action is None:
            return

        pathText = action.text or ""
        suffix = Path(pathText).suffix.lower() if pathText else ""

        # Project formats go through the same flow as Open Project so the
        # environment is detected and loaded automatically.
        if suffix == ".mrml":
            self.__openMrmlScene(Path(pathText))
            return
        if suffix == ".nc":
            self.__openNetcdfProject(Path(pathText))
            return

        try:
            action.trigger()
        except Exception as error:  # pragma: no cover - defensive
            logging.error(f"Failed to load recent entry: {error}")
            return

        # Best effort: after a non-project recent load, see whether the new
        # scene fits a known data type and enter that environment.
        self.__autoEnterEnvironmentFromScene(pathHint=pathText)

    def __autoEnterEnvironmentFromScene(self, pathHint: Optional[str] = None) -> None:
        from ltrace.slicer.app import tryDetectProjectDataType

        category = tryDetectProjectDataType()
        if not category or category not in LOADERS:
            return
        if pathHint:
            recordEnvironmentForPath(pathHint, category)
        self.__loadEnvironmentByName(category)

    def __onOpenMrmlProject(self) -> None:
        path = qt.QFileDialog.getOpenFileName(
            self,
            "Open Project",
            slicer.app.defaultScenePath,
            "GeoSlicer scene (*.mrml)",
        )
        if not path:
            return
        self.__openMrmlScene(Path(path))

    def __onOpenNetcdfProject(self) -> None:
        path = qt.QFileDialog.getOpenFileName(
            self,
            "Open NetCDF4 Project",
            slicer.app.defaultScenePath,
            "NetCDF (*.nc)",
        )
        if not path:
            return
        self.__openNetcdfProject(Path(path))

    # -- routing helpers --------------------------------------------------

    def __openMrmlScene(self, path: Path) -> None:
        events = slicer.modules.AppContextInstance.projectEventsLogic
        if not events.loadScene(path):
            return
        self.__refreshRecentList()

        from ltrace.slicer.app import tryDetectProjectDataType

        category = tryDetectProjectDataType()
        if category and category in LOADERS:
            recordEnvironmentForPath(str(path), category)
            self.__loadEnvironmentByName(category)
            return
        OnboardLayout.showOnlyDataTypes(self.__toolbar)

    def __openNetcdfProject(self, path: Path) -> None:
        suggested = [env for env in _suggestEnvForNetcdf(path) if env in LOADERS]

        if len(suggested) == 1:
            # We could determine the environment: enter it, load the data
            # directly, and let the user know it was chosen automatically.
            environment = suggested[0]
            recordEnvironmentForPath(str(path), environment)
            self.__loadEnvironmentByName(environment)
            self.__importNetcdf(path)
            _notifyAutoSelectedEnvironment(environment)
            return

        # Ambiguous / undetermined → user picks the environment; remember the
        # path so its data is imported once they choose. Set it *after* entering
        # picker mode (showOnlyDataTypes resets pending state via show()).
        OnboardLayout.showOnlyDataTypes(self.__toolbar, suggestedEnvs=suggested or None)
        self.__pendingNetcdfPath = path

    def __importNetcdf(self, path: Path) -> None:
        """Import a NetCDF/HDF5 file (or directory) into the current scene.

        Loads the data directly via ``ltrace.slicer.netcdf`` so the user does
        not have to open the NetCDF module's Import tab. Best-effort: failures
        are surfaced but never crash onboarding. Imports are lazy to keep the
        onboarding/startup path light.
        """
        try:
            from ltrace.slicer import netcdf
            from ltrace.utils.ProgressBarProc import ProgressBarProc
        except Exception as error:  # pragma: no cover - optional dependency
            logging.error(f"NetCDF import support is unavailable: {error}")
            slicer.util.errorDisplay(
                "NetCDF support is not available in this installation.",
                "Open NetCDF4 Project",
            )
            return

        try:
            with ProgressBarProc() as pb:

                def onProgress(message, progress, *args, **kwargs):
                    pb.nextStep(int(max(0, min(100, progress))), str(message))

                if path.is_dir():
                    netcdf.import_directory(path, onProgress)
                else:
                    netcdf.import_file(path, onProgress)
        except Exception as error:
            logging.error(f"Failed to import NetCDF data from {path}: {error}")
            slicer.util.errorDisplay(
                f"Failed to import the NetCDF project:\n{error}",
                "Open NetCDF4 Project",
            )

    def __loadEnvironmentByName(self, displayName: str) -> None:
        loader = LOADERS.get(displayName)
        if loader is None or self.__toolbar is None:
            return
        OnboardLayout.hide()
        layoutManager = slicer.app.layoutManager()
        layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
        loadEnvironment(self.__toolbar, loader)

    # -- second-column swapping -------------------------------------------

    def __showWalkthroughs(self) -> None:
        markdown = _readChangelogLatest()
        self.__whatsNewBrowser.setHtml(_markdownToHtml(markdown))
        self.__secondHeader.setText("Walkthroughs".upper())
        self.__contentStack.setCurrentWidget(self.__pageWalkthroughs)

    def __showPickerHint(self) -> None:
        self.__secondHeader.setText("Choose a data type".upper())
        self.__contentStack.setCurrentWidget(self.__pagePickerHint)

    def __previewEnvironment(self, displayName: str) -> None:
        # Cancel any pending fall-back so moving onto this launcher swaps the
        # preview immediately (no Walkthroughs flash between environments).
        self.__previewClearTimer.stop()

        loader = LOADERS.get(displayName)
        if loader is None:
            return

        intro = ENVIRONMENT_INTROS.get(displayName)
        summary = intro.summary if intro else loader.description
        features = intro.features if intro else []

        self.__secondHeader.setText(displayName.upper())
        self.__envTitle.setText(displayName)
        self.__envSummary.setText(summary)
        if features:
            bullets = "".join(f"<li>{f}</li>" for f in features)
            self.__envFeatures.setText(f"<ul style='margin:0 0 0 18px;padding:0;'>{bullets}</ul>")
        else:
            self.__envFeatures.setText("")

        self.__contentStack.setCurrentWidget(self.__pageEnvironment)

    def __clearPreview(self) -> None:
        # Defer the revert: if the pointer lands on another launcher within the
        # grace period, __previewEnvironment cancels this and swaps directly.
        self.__previewClearTimer.start()

    def __doClearPreview(self) -> None:
        # Fired by the debounce timer — the pointer has left the launchers.
        if self.__pickerMode:
            self.__showPickerHint()
        else:
            self.__showWalkthroughs()

    def __onEnvironmentLaunch(self, displayName: str) -> None:
        if displayName not in LOADERS:
            return

        if self.__pickerMode:
            # A project is already chosen; enter the environment and, for a
            # pending NetCDF project, import its data directly.
            self.__loadEnvironmentByName(displayName)
            if self.__pendingNetcdfPath is not None:
                self.__importNetcdf(self.__pendingNetcdfPath)
                self.__pendingNetcdfPath = None
            return

        # Normal mode: starting fresh in this environment closes the current
        # scene first. ``onCloseScene`` shows the save/discard/cancel dialog
        # when there are unsaved changes; if the user cancels, we abort and
        # leave the onboarding view untouched.
        events = slicer.modules.AppContextInstance.projectEventsLogic
        if not events.onCloseScene():
            return
        self.__loadEnvironmentByName(displayName)


# ---------------------------------------------------------------------------
# Viewport-overlay management
# ---------------------------------------------------------------------------


class _ViewportResizeFilter(qt.QObject):
    """Keeps an overlay widget's geometry pinned to its viewport parent."""

    def __init__(self, target: qt.QWidget):
        super().__init__(target)
        self.__target = target

    def eventFilter(self, watched, event):
        if event.type() == qt.QEvent.Resize and self.__target is not None and self.__target.isVisible():
            self.__target.setGeometry(watched.rect)
        return False


class OnboardLayout:
    """Manages the onboarding view as an overlay above the layout viewport.

    Earlier this used a registered Slicer layout ID + ``qSlicerSingletonViewFactory``,
    but repeated layout switches eventually corrupted Qt's paint state for the
    re-parented singleton widget (black squares). The overlay approach keeps
    the same widget parented to ``layoutManager.viewport()`` and just toggles
    visibility — no reparenting, no factory.
    """

    _container: Optional["OnboardWidget"] = None
    _resizeFilter: Optional[_ViewportResizeFilter] = None
    _filteredViewport: Optional[qt.QWidget] = None

    @classmethod
    def _viewport(cls) -> Optional[qt.QWidget]:
        layoutManager = slicer.app.layoutManager()
        if layoutManager is None:
            return None
        try:
            return layoutManager.viewport()
        except Exception:
            return None

    @classmethod
    def isActive(cls) -> bool:
        return cls._container is not None and cls._container.isVisible()

    @classmethod
    def refresh(cls) -> None:
        if cls._container is not None:
            cls._container.refresh()

    @classmethod
    def hide(cls) -> None:
        if cls._container is not None:
            cls._container.hide()

    @classmethod
    def _onCloseRequested(cls) -> None:
        cls.hide()
        # Best effort: bring the user back to the last loaded environment.
        # If none was ever loaded (e.g. fresh boot), the underlying layout
        # remains and the user can pick something from the menus.
        last = getLastEnvironment()
        if last is None or cls._container is None:
            return
        toolbar = cls._container.toolbar()
        if toolbar is None:
            return
        try:
            loadEnvironment(toolbar, last)
        except Exception as error:  # pragma: no cover - defensive
            logging.warning(f"Failed to re-enter last environment: {error}")

    @classmethod
    def show(cls, toolbar=None) -> None:
        viewport = cls._viewport()
        if viewport is None:
            return

        if cls._container is None:
            cls._container = OnboardWidget(viewport)
            cls._container.closeRequested.connect(cls._onCloseRequested)
        elif cls._container.parent() is not viewport:
            cls._container.setParent(viewport)

        if cls._resizeFilter is None:
            cls._resizeFilter = _ViewportResizeFilter(cls._container)
        if cls._filteredViewport is not viewport:
            if cls._filteredViewport is not None:
                cls._filteredViewport.removeEventFilter(cls._resizeFilter)
            viewport.installEventFilter(cls._resizeFilter)
            cls._filteredViewport = viewport

        if toolbar is not None:
            cls._container.setToolbar(toolbar)

        # Reset to full mode by default; callers override via showOnlyDataTypes.
        cls._container.setDataTypesOnly(False)

        cls._container.setGeometry(viewport.rect)
        cls._container.raise_()
        cls._container.show()
        cls._container.refresh()

    @classmethod
    def showOnlyDataTypes(cls, toolbar=None, suggestedEnvs: Optional[List[str]] = None) -> None:
        cls.show(toolbar=toolbar)
        if cls._container is not None:
            cls._container.setDataTypesOnly(True, suggestedEnvs=suggestedEnvs)


def showOnboardView(toolbar=None) -> None:
    """Show the onboarding overlay above the active layout's viewport."""

    OnboardLayout.show(toolbar=toolbar)
