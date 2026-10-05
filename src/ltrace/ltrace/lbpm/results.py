"""Reading what an LBPM run produced, and turning it into report-ready curves.

A colour simulation writes, next to its configuration:

* ``timelog.csv`` — one row per steady point: saturation and relative permeabilities;
* ``subphase.csv`` — one row per analysis interval: sub-phase volumes, areas, curvatures and pressures;
* ``solid.csv`` / ``minkowski.csv`` — geometric measures of the solid and of the non-wetting phase;
* ``vis<timestep>/`` — the visualization frames (surfaced separately as a 4D dataset);
* ``LBM.visit`` — the index of those frames.

Both CSVs are whitespace-separated despite their extension, which is why they are read through the same
sniffing table reader the deferred sources use.

Everything here is plain pandas: no ``slicer`` import, so it can be unit-tested and reused outside the
application. Building nodes and plots from these curves is the module's job.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

TIMELOG_NAME = "timelog.csv"
SUBPHASE_NAME = "subphase.csv"
SOLID_NAME = "solid.csv"
MINKOWSKI_NAME = "minkowski.csv"
VISIT_NAME = "LBM.visit"


@dataclass
class Curve:
    """One plot of a report: a shared x axis and one or more named series."""

    key: str
    title: str
    x_label: str
    y_label: str
    x: Sequence[float]
    series: Dict[str, Sequence[float]]
    note: str = ""

    @property
    def points(self) -> int:
        return len(self.x)


@dataclass
class LBPMResults:
    case_dir: Path
    timelog: Optional["pd.DataFrame"] = None
    subphase: Optional["pd.DataFrame"] = None
    solid: Dict[str, float] = field(default_factory=dict)
    frames: List[str] = field(default_factory=list)

    # -- loading --------------------------------------------------------------------------------------
    @classmethod
    def load(cls, case_dir) -> "LBPMResults":
        case_dir = Path(case_dir)
        return cls(
            case_dir=case_dir,
            timelog=_read_table(case_dir / TIMELOG_NAME),
            subphase=_read_table(case_dir / SUBPHASE_NAME),
            solid=_read_single_row(case_dir / SOLID_NAME),
            # What is on disk first: a report describes the frames the user can actually open, and
            # LBM.visit still lists frames that were written and later removed.
            frames=_list_frames(case_dir) or _read_visit(case_dir / VISIT_NAME),
        )

    @property
    def has_data(self) -> bool:
        return self.timelog is not None or self.subphase is not None

    # -- derived quantities ---------------------------------------------------------------------------
    def saturation(self) -> Optional["pd.Series"]:
        """Water saturation over time, from the sub-phase volumes.

        ``subphase.csv`` reports volumes per sub-phase — connected and disconnected wetting (``Vwc``,
        ``Vwd``) and non-wetting (``Vnc``, ``Vnd``) — so saturation is their ratio rather than a column.
        """
        if self.subphase is None:
            return None

        columns = self.subphase.columns
        wetting = [name for name in ("Vwc", "Vwd") if name in columns]
        non_wetting = [name for name in ("Vnc", "Vnd") if name in columns]
        if not wetting or not non_wetting:
            return None

        water = self.subphase[wetting].sum(axis=1)
        total = water + self.subphase[non_wetting].sum(axis=1)
        return (water / total.replace(0, float("nan"))).rename("sw")

    def capillary_pressure(self) -> Optional["pd.Series"]:
        """``pnc - pwc``: the pressure difference between the connected phases."""
        if self.subphase is None or "pnc" not in self.subphase or "pwc" not in self.subphase:
            return None
        return (self.subphase["pnc"] - self.subphase["pwc"]).rename("pc")

    # -- report ---------------------------------------------------------------------------------------
    def curves(self) -> List[Curve]:
        curves: List[Curve] = []

        if self.timelog is not None and "sw" in self.timelog:
            available = {
                label: self.timelog[column].tolist()
                for label, column in (("krw", "krw"), ("krn", "krn"))
                if column in self.timelog
            }
            if available:
                curves.append(
                    Curve(
                        key="relative_permeability",
                        title="Relative permeability",
                        x_label="Water saturation (Sw)",
                        y_label="Relative permeability",
                        x=self.timelog["sw"].tolist(),
                        series=available,
                        note="One point per steady state reached by the flow adaptor.",
                    )
                )

            if "peff" in self.timelog:
                curves.append(
                    Curve(
                        key="effective_pressure",
                        title="Effective pressure",
                        x_label="Water saturation (Sw)",
                        y_label="Effective pressure (lattice units)",
                        x=self.timelog["sw"].tolist(),
                        series={"peff": self.timelog["peff"].tolist()},
                    )
                )

        saturation = self.saturation()
        if saturation is not None and self.subphase is not None and "time" in self.subphase:
            curves.append(
                Curve(
                    key="saturation_history",
                    title="Saturation history",
                    x_label="Timestep",
                    y_label="Water saturation (Sw)",
                    x=self.subphase["time"].tolist(),
                    series={"sw": saturation.tolist()},
                    note="Computed from the sub-phase volumes written at each analysis interval.",
                )
            )

            pressure = self.capillary_pressure()
            if pressure is not None:
                curves.append(
                    Curve(
                        key="capillary_pressure",
                        title="Capillary pressure",
                        x_label="Water saturation (Sw)",
                        y_label="pn - pw (lattice units)",
                        x=saturation.tolist(),
                        series={"pc": pressure.tolist()},
                    )
                )

            if "Ai" in self.subphase:
                curves.append(
                    Curve(
                        key="interfacial_area",
                        title="Interfacial area",
                        x_label="Water saturation (Sw)",
                        y_label="Area (voxel²)",
                        x=saturation.tolist(),
                        series={"Ai": self.subphase["Ai"].tolist()},
                    )
                )

            euler = {name: self.subphase[name].tolist() for name in ("Xnc", "Xwc") if name in self.subphase}
            if euler:
                curves.append(
                    Curve(
                        key="euler_characteristic",
                        title="Euler characteristic",
                        x_label="Water saturation (Sw)",
                        y_label="Euler characteristic",
                        x=saturation.tolist(),
                        series=euler,
                        note="Connectivity of each phase: a drop means the phase broke into disconnected blobs.",
                    )
                )

        return curves

    def summary(self) -> Dict[str, object]:
        """Headline numbers for the report header."""
        summary: Dict[str, object] = {"frames": len(self.frames)}

        if self.timelog is not None and "sw" in self.timelog and len(self.timelog):
            summary["steady_points"] = int(len(self.timelog))
            summary["sw_initial"] = float(self.timelog["sw"].iloc[0])
            summary["sw_final"] = float(self.timelog["sw"].iloc[-1])
            for column in ("krw", "krn"):
                if column in self.timelog:
                    summary[f"{column}_final"] = float(self.timelog[column].iloc[-1])

        saturation = self.saturation()
        if saturation is not None and len(saturation.dropna()):
            summary["sw_last_analysis"] = float(saturation.dropna().iloc[-1])

        if self.subphase is not None and "time" in self.subphase and len(self.subphase):
            summary["last_timestep"] = int(self.subphase["time"].iloc[-1])

        if self.solid:
            summary["porosity"] = _porosity(self.solid, self.subphase)

        return summary


def _porosity(solid: Dict[str, float], subphase) -> Optional[float]:
    """Pore fraction from the solid volume and the fluid volumes, when both are available."""
    solid_volume = solid.get("Vs")
    if not solid_volume or subphase is None:
        return None

    columns = [name for name in ("Vwc", "Vwd", "Vnc", "Vnd") if name in subphase]
    if not columns or not len(subphase):
        return None

    pore = float(subphase[columns].iloc[0].sum())
    total = pore + float(solid_volume)
    return pore / total if total else None


def _read_table(path: Path):
    """Read one of LBPM's logs, whose extension says csv but whose separator is whitespace."""
    if not path.is_file() or path.stat().st_size == 0:
        return None

    try:
        import pandas as pd

        from ltrace.slicer.virtual.sources.tables import sniff_separator

        frame = pd.read_csv(path, sep=sniff_separator(path), engine="python")
        return frame if len(frame) else None
    except Exception as error:
        logging.warning(f"Unable to read {path.name}: {error}")
        return None


def _read_single_row(path: Path) -> Dict[str, float]:
    frame = _read_table(path)
    if frame is None or not len(frame):
        return {}
    row = frame.iloc[0]
    return {str(column): float(row[column]) for column in frame.columns if _is_number(row[column])}


def _is_number(value) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _read_visit(path: Path) -> List[str]:
    """Frame list from ``LBM.visit`` (one ``vis<timestep>/summary.xmf`` per line)."""
    if not path.is_file():
        return []

    frames = []
    for line in path.read_text(errors="replace").splitlines():
        entry = line.strip()
        if entry:
            frames.append(Path(entry).parent.name or entry)
    return frames


def _list_frames(case_dir: Path) -> List[str]:
    try:
        return sorted(item.name for item in case_dir.glob("vis*") if item.is_dir())
    except OSError:
        return []
