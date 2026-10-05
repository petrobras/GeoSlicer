"""Reader/writer for LBPM's input database (``waterflow.db`` and friends).

The format is a nested, brace-delimited key/value file with ``//`` comments and optional ``;``
terminators::

    Domain {
       Filename = "image.raw"
       N = 1, 2119, 5280              // size of original image
    }
    Color {
        tauA = 1.1;             // relaxation time for fluid A
    }

The parser keeps the document as an ordered list of elements that remember their original text, so a file
edited through :meth:`WaterflowConfig.set` comes back byte-identical except for the values that changed.
That is a requirement, not a nicety: the module offers an "advanced" mode where users edit the file
directly, and a lossy round-trip would silently discard their comments.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

import re

READ_TYPE_TO_DTYPE = {
    "8bit": "uint8",
    "8bitraw": "uint8",
    "16bit": "uint16",
    "float": "float32",
    "double": "float64",
}

MICROMETER_IN_MM = 1e-3

_SECTION_START = re.compile(r"^(?P<indent>\s*)(?P<name>[A-Za-z_][\w]*)\s*\{\s*(?P<trailing>.*)$")
_SECTION_END = re.compile(r"^\s*\}\s*;?\s*$")
_ENTRY = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z_][\w]*)\s*=\s*(?P<value>.*?)\s*(?P<terminator>;?)\s*(?P<comment>//.*)?$"
)


class ConfigError(ValueError):
    pass


@dataclass
class _Entry:
    """One ``key = value`` line, remembering its original text.

    Only the value substring is rewritten when the entry is edited, so alignment padding, ``;``
    terminators, trailing comments and even trailing whitespace survive a round trip untouched.
    """

    key: str
    value: str
    section: str
    raw: str
    span: Tuple[int, int]
    dirty: bool = False

    @classmethod
    def create(cls, section: str, key: str, value: str, indent: str = "    ", terminator: str = "") -> "_Entry":
        prefix = f"{indent}{key} = "
        raw = f"{prefix}{value}{terminator}"
        return cls(key=key, value=value, section=section, raw=raw, span=(len(prefix), len(prefix) + len(value)))

    def set_value(self, value: str) -> None:
        self.value = value
        self.dirty = True

    def render(self) -> str:
        if not self.dirty:
            return self.raw
        start, end = self.span
        return f"{self.raw[:start]}{self.value}{self.raw[end:]}"


@dataclass
class _Literal:
    text: str

    def render(self) -> str:
        return self.text


@dataclass
class WaterflowConfig:
    """An LBPM input database, editable in place."""

    elements: List[Union[_Entry, _Literal]] = field(default_factory=list)
    path: Optional[Path] = None

    # -- construction ---------------------------------------------------------------------------------
    @classmethod
    def from_text(cls, text: str, path: Path = None) -> "WaterflowConfig":
        elements: List[Union[_Entry, _Literal]] = []
        stack: List[str] = []

        for line in text.splitlines():
            start = _SECTION_START.match(line)
            if start and not line.lstrip().startswith("//"):
                elements.append(_Literal(line))
                stack.append(start.group("name"))
                continue

            if _SECTION_END.match(line):
                elements.append(_Literal(line))
                if stack:
                    stack.pop()
                continue

            entry = _ENTRY.match(line)
            if entry and stack and not line.lstrip().startswith("//"):
                elements.append(
                    _Entry(
                        key=entry.group("key"),
                        value=entry.group("value"),
                        section=stack[-1],
                        raw=line,
                        span=entry.span("value"),
                    )
                )
                continue

            elements.append(_Literal(line))

        return cls(elements=elements, path=Path(path) if path else None)

    @classmethod
    def from_file(cls, path) -> "WaterflowConfig":
        path = Path(path)
        return cls.from_text(path.read_text(encoding="utf-8", errors="replace"), path=path)

    @classmethod
    def default(cls) -> "WaterflowConfig":
        """A runnable colour-simulation database with LBPM's documented defaults."""
        return cls.from_text(DEFAULT_WATERFLOW_DB)

    # -- serialization --------------------------------------------------------------------------------
    def to_text(self) -> str:
        text = "\n".join(element.render() for element in self.elements)
        return text if text.endswith("\n") else text + "\n"

    def write(self, path=None) -> Path:
        target = Path(path or self.path)
        if target is None:
            raise ConfigError("No path given to write the configuration to.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_text(), encoding="utf-8")
        self.path = target
        return target

    # -- access ---------------------------------------------------------------------------------------
    def sections(self) -> List[str]:
        seen = []
        for element in self.elements:
            if isinstance(element, _Entry) and element.section not in seen:
                seen.append(element.section)
        return seen

    def keys(self, section: str) -> List[str]:
        return [element.key for element in self._entries() if element.section == section]

    def as_dict(self) -> Dict[str, Dict[str, str]]:
        data: Dict[str, Dict[str, str]] = {}
        for entry in self._entries():
            data.setdefault(entry.section, {})[entry.key] = entry.value
        return data

    def get(self, section: str, key: str, default=None) -> Optional[str]:
        entry = self._find(section, key)
        return default if entry is None else entry.value

    def get_string(self, section: str, key: str, default: str = None) -> Optional[str]:
        value = self.get(section, key)
        return default if value is None else value.strip().strip('"').strip("'")

    def get_float(self, section: str, key: str, default: float = None) -> Optional[float]:
        value = self.get_string(section, key)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_int(self, section: str, key: str, default: int = None) -> Optional[int]:
        value = self.get_float(section, key)
        return default if value is None else int(value)

    def get_bool(self, section: str, key: str, default: bool = None) -> Optional[bool]:
        value = self.get_string(section, key)
        if value is None:
            return default
        return value.strip().lower() in ("true", "1", "yes", "on")

    def get_list(self, section: str, key: str, default: Sequence = None) -> Optional[List[str]]:
        value = self.get(section, key)
        if value is None:
            return list(default) if default is not None else None
        return [item.strip().strip('"') for item in value.split(",") if item.strip()]

    def get_int_list(self, section: str, key: str, default: Sequence[int] = None) -> Optional[List[int]]:
        values = self.get_list(section, key)
        if values is None:
            return list(default) if default is not None else None
        try:
            return [int(float(item)) for item in values]
        except ValueError:
            return list(default) if default is not None else None

    def get_float_list(self, section: str, key: str, default: Sequence[float] = None) -> Optional[List[float]]:
        values = self.get_list(section, key)
        if values is None:
            return list(default) if default is not None else None
        try:
            return [float(item) for item in values]
        except ValueError:
            return list(default) if default is not None else None

    # -- mutation -------------------------------------------------------------------------------------
    def set(self, section: str, key: str, value) -> None:
        """Set ``key`` in ``section``, preserving the original quoting, comment and indentation."""
        entry = self._find(section, key)
        if entry is not None:
            entry.set_value(self._format(value, previous=entry.value))
            return

        self._append_entry(section, key, self._format(value))

    def update(self, values: Dict[str, Dict[str, object]]) -> None:
        for section, entries in values.items():
            for key, value in entries.items():
                self.set(section, key, value)

    def remove(self, section: str, key: str) -> bool:
        entry = self._find(section, key)
        if entry is None:
            return False
        self.elements.remove(entry)
        return True

    # -- domain helpers -------------------------------------------------------------------------------
    def voxel_length_mm(self) -> Optional[float]:
        """``Domain.voxel_length`` (documented in micrometers by LBPM) converted to millimeters."""
        voxel_length = self.get_float("Domain", "voxel_length")
        return None if voxel_length is None else voxel_length * MICROMETER_IN_MM

    def domain_shape_zyx(self) -> Optional[Tuple[int, int, int]]:
        """``Domain.N`` (given as X, Y, Z) reordered to the ZYX order used by numpy and Slicer arrays."""
        extent = self.get_int_list("Domain", "N")
        if not extent or len(extent) != 3:
            return None
        x, y, z = extent
        return (z, y, x)

    def domain_dtype(self) -> str:
        read_type = (self.get_string("Domain", "ReadType", "8bit") or "8bit").lower().replace(" ", "")
        return READ_TYPE_TO_DTYPE.get(read_type, "uint8")

    def domain_geometry(self):
        """``(shape_zyx, dtype, is_labelmap, spacing_mm)`` for the RAW images this case reads and writes.

        Used to interpret LBPM's ``id_t<step>.raw`` snapshots, whose filenames carry no geometry.
        """
        shape = self.domain_shape_zyx()
        if shape is None:
            return None
        return shape, self.domain_dtype(), True, self.voxel_length_mm()

    def rank_count(self) -> int:
        grid = self.get_int_list("Domain", "nproc", [1, 1, 1])
        count = 1
        for value in grid:
            count *= max(1, value)
        return count

    def visualization_interval(self) -> Optional[int]:
        return self.get_int("Analysis", "visualization_interval")

    def validate(self) -> List[str]:
        """Human-readable problems that would make a run fail, for display before submitting."""
        problems = []

        if not self.get_string("Domain", "Filename"):
            problems.append("Domain.Filename is not set: LBPM needs the input image file name.")

        shape = self.domain_shape_zyx()
        if shape is None:
            problems.append("Domain.N must list three integers (X, Y, Z).")

        subdomain = self.get_int_list("Domain", "n")
        grid = self.get_int_list("Domain", "nproc")
        if shape and subdomain and grid and len(subdomain) == 3 and len(grid) == 3:
            extent_xyz = list(reversed(shape))
            for axis, name in enumerate("XYZ"):
                if subdomain[axis] * grid[axis] != extent_xyz[axis]:
                    problems.append(
                        f"Domain.n[{name}] x Domain.nproc[{name}] = {subdomain[axis] * grid[axis]} "
                        f"does not cover Domain.N[{name}] = {extent_xyz[axis]}."
                    )

        if self.voxel_length_mm() in (None, 0):
            problems.append("Domain.voxel_length must be a positive value in micrometers.")

        return problems

    # -- internals ------------------------------------------------------------------------------------
    def _entries(self) -> List[_Entry]:
        return [element for element in self.elements if isinstance(element, _Entry)]

    def _find(self, section: str, key: str) -> Optional[_Entry]:
        for entry in self._entries():
            if entry.section == section and entry.key == key:
                return entry
        return None

    def _append_entry(self, section: str, key: str, value: str) -> None:
        entries = [element for element in self._entries() if element.section == section]
        if entries:
            reference = entries[-1]
            index = self.elements.index(reference) + 1
            indent = reference.raw[: len(reference.raw) - len(reference.raw.lstrip())]
            terminator = ";" if reference.raw.rstrip().endswith(";") else ""
        else:
            # Create the section at the end of the document.
            self.elements.append(_Literal(""))
            self.elements.append(_Literal(f"{section} {{"))
            self.elements.append(_Literal("}"))
            index = len(self.elements) - 1
            indent, terminator = "    ", ""

        self.elements.insert(index, _Entry.create(section, key, value, indent=indent, terminator=terminator))

    @staticmethod
    def _format(value, previous: str = None) -> str:
        was_quoted = bool(previous) and previous.strip().startswith('"')

        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return f'"{value}"' if was_quoted or not value or " " in value else value
        if isinstance(value, (list, tuple)):
            return ", ".join(WaterflowConfig._format(item) for item in value)
        if isinstance(value, float):
            return repr(value)
        return str(value)


DEFAULT_WATERFLOW_DB = """Domain {
   Filename = ""                  // input image file
   ReadType = "8bit"              // data type
   N = 1, 1, 1                    // size of original image
   nproc = 1, 1, 1                // process grid
   n = 1, 1, 1                    // sub-domain size
   offset = 0, 0, 0               // offset to read sub-domain

   voxel_length = 1.0             // voxel length (in microns)
   ReadValues = 0, 1, 2           // labels within the original image
   WriteValues = 0, 1, 2          // associated labels to be used by LBPM
   BC = 4                         // boundary condition type (0 for periodic)
   Sw = 1.0                       // initial water saturation
}

Color {
    tauA = 0.7;                   // relaxation time for fluid A (labeled as "1")
    tauB = 0.7;                   // relaxation time for fluid B (labeled as "2")
    rhoA = 1.0;                   // density for fluid A (in lattice units)
    rhoB = 1.0;                   // density for fluid B (in lattice units)
    alpha = 1.0e-3;               // controls the surface tension
    beta = 0.95;                  // controls the interface width
    F = 0, 0, 0                   // controls the external force
    Restart = false               // initialize simulation from restart file?
    timestepMax = 1000000         // maximum number of timesteps to perform before exit
    ComponentLabels = 0           // immobile component labels in the input image
    ComponentAffinity = -1.0      // wetting condition for each immobile component
    flux = 0.0                    // volumetric flux at the z-inlet in voxels per timestep
}

Analysis {
    analysis_interval = 1000         // frequency to perform analysis
    subphase_analysis_interval = 1000   // logging interval for subphase.csv
    visualization_interval = 1000    // frequency to write visualization data
    restart_interval = 1000000       // frequency to write restart data
    restart_file = "Restart"         // filename to use for restart file (will append rank)
    N_threads = 0                    // number of threads to use for analysis
    load_balance = "independent"     // load balance method: "none", "default", "independent"
}

Visualization {
   format = "hdf5"
   write_silo = false        // write SILO databases with assigned variables
   save_8bit_raw = true      // write labeled 8-bit binary files with phase assignments
   save_phase_field = true   // save phase field
   save_pressure = true      // save pressure field
   save_velocity = true      // save velocity field
}

FlowAdaptor {
   min_steady_timesteps = 20000       // minimum number of timesteps per steady point
   max_steady_timesteps = 100000      // maximum number of timesteps per steady point
   mass_fraction_factor = 0.006       // controls the rate of mass seeding in adaptive step
   fractional_flow_increment = 0.05   // saturation change after each steady point
   endpoint_threshold = 0.001         // endpoint exit criterion (based on flow rates)
}
"""
