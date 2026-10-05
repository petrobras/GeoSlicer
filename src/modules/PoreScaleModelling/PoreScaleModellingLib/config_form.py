"""Form for the parameters of an LBPM input database that are usually tuned.

The form is declarative (see :data:`FIELDS`): every field reads from and writes to one
:class:`~ltrace.lbpm.config.WaterflowConfig`, and that object preserves the file verbatim apart from the
values that were edited. Anything the form does not cover is edited in the file itself, with a text
editor, and read back from it — the file is the only other view, so there is nothing else to keep in step.
"""

import qt

from ltrace.lbpm.config import WaterflowConfig

BOUNDARY_CONDITIONS = (
    (0, "0 — Periodic"),
    (3, "3 — Constant pressure"),
    (4, "4 — Constant flux"),
    (5, "5 — Constant velocity"),
)

FIELDS = (
    # (section, key, label, kind, tooltip)
    ("Domain", "voxel_length", "Voxel length (µm)", "float", "Physical size of one voxel, in micrometers."),
    ("Domain", "BC", "Boundary condition", "bc", "How the inlet and outlet of the domain are driven."),
    ("Domain", "Sw", "Initial water saturation", "float", "Fraction of the pore space initially filled with water."),
    ("Color", "tauA", "Relaxation time — fluid A", "float", "Controls the viscosity of the fluid labelled 1."),
    ("Color", "tauB", "Relaxation time — fluid B", "float", "Controls the viscosity of the fluid labelled 2."),
    ("Color", "rhoA", "Density — fluid A", "float", "Density of fluid A in lattice units."),
    ("Color", "rhoB", "Density — fluid B", "float", "Density of fluid B in lattice units."),
    ("Color", "alpha", "Surface tension (alpha)", "float", "Controls the interfacial tension."),
    ("Color", "beta", "Interface width (beta)", "float", "Controls how sharp the interface between fluids is."),
    ("Color", "flux", "Inlet flux", "float", "Volumetric flux at the z inlet, in voxels per timestep."),
    ("Color", "ComponentAffinity", "Component affinity", "list", "Wetting condition of each immobile label."),
    ("Color", "timestepMax", "Maximum timesteps", "int", "Hard stop for the simulation."),
    ("Analysis", "analysis_interval", "Analysis interval", "int", "How often the analysis runs."),
    ("Analysis", "subphase_analysis_interval", "Sub-phase interval", "int", "How often subphase.csv is written."),
    (
        "Analysis",
        "visualization_interval",
        "Visualization interval",
        "int",
        "How often a frame is written. This is the time resolution of the 4D output.",
    ),
    (
        "FlowAdaptor",
        "min_steady_timesteps",
        "Minimum steady timesteps",
        "int",
        "Shortest time the flow adaptor waits before accepting a steady point.",
    ),
    (
        "FlowAdaptor",
        "max_steady_timesteps",
        "Maximum steady timesteps",
        "int",
        "Longest time the flow adaptor waits for a steady point.",
    ),
    (
        "FlowAdaptor",
        "fractional_flow_increment",
        "Saturation increment",
        "float",
        "Saturation change targeted after each steady point.",
    ),
    (
        "FlowAdaptor",
        "endpoint_threshold",
        "Endpoint threshold",
        "float",
        "Flow-rate threshold at which the simulation is considered finished.",
    ),
    (
        "Visualization",
        "save_8bit_raw",
        "Save 8-bit RAW frames",
        "bool",
        "Write a full-domain 8-bit image per frame, next to the per-rank output.",
    ),
    ("Visualization", "save_phase_field", "Save phase field", "bool", "Include the phase field in each frame."),
    ("Visualization", "save_pressure", "Save pressure", "bool", "Include pressure in each frame."),
    ("Visualization", "save_velocity", "Save velocity", "bool", "Include velocity in each frame."),
)

INT_MAXIMUM = 2**31 - 1


class ConfigFormWidget(qt.QWidget):
    """Form over one configuration."""

    def __init__(self, parent=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.config = None
        self._widgets = {}
        self.setup()

    # -- construction ---------------------------------------------------------------------------------
    def setup(self):
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(self._buildForm())

        self.problemsLabel = qt.QLabel()
        self.problemsLabel.setWordWrap(True)
        self.problemsLabel.setStyleSheet("QLabel { color: #ff6060; }")
        self.problemsLabel.visible = False
        layout.addWidget(self.problemsLabel)

    def _buildForm(self):
        container = qt.QWidget()
        outer = qt.QVBoxLayout(container)

        sections = {}
        for section, key, label, kind, tooltip in FIELDS:
            if section not in sections:
                box = qt.QGroupBox(section)
                form = qt.QFormLayout(box)
                sections[section] = form
                outer.addWidget(box)
                if section == "Domain":
                    self._buildImageRow(form)

            widget = self._buildField(kind)
            widget.setToolTip(tooltip)
            widget.objectName = f"Config {section} {key}"
            self._widgets[(section, key)] = (widget, kind)
            sections[section].addRow(f"{label}:", widget)

        outer.addStretch(1)

        scroll = qt.QScrollArea()
        scroll.setWidget(container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(qt.QFrame.NoFrame)
        return scroll

    def _buildImageRow(self, form):
        # Which image the case reads is set by writing one from the Case section, not typed here, but it is
        # what a run depends on most, so the form shows it.
        self.imageLabel = qt.QLabel()
        self.imageLabel.objectName = "Config Domain Image Label"
        self.imageLabel.setWordWrap(True)
        self.imageLabel.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
        self.imageLabel.setToolTip("The RAW image this configuration reads (Domain.Filename) and its size (Domain.N).")
        form.addRow("Image:", self.imageLabel)

    @staticmethod
    def _buildField(kind):
        if kind == "bool":
            return qt.QCheckBox()

        if kind == "bc":
            combo = qt.QComboBox()
            for value, label in BOUNDARY_CONDITIONS:
                combo.addItem(label, value)
            return combo

        if kind == "int":
            box = qt.QSpinBox()
            box.setRange(0, INT_MAXIMUM)
            box.setSingleStep(1000)
            return box

        if kind == "float":
            box = qt.QDoubleSpinBox()
            box.setDecimals(6)
            box.setRange(-1e6, 1e6)
            box.setSingleStep(0.01)
            return box

        edit = qt.QLineEdit()
        edit.setPlaceholderText("comma separated values")
        return edit

    # -- binding --------------------------------------------------------------------------------------
    def setConfig(self, config: WaterflowConfig):
        self.config = config
        self._refreshFields()
        self.validate()

    def applyToConfig(self) -> WaterflowConfig:
        """Write the form back into the configuration."""
        if self.config is None:
            return None

        for (section, key), (widget, kind) in self._widgets.items():
            value = self._readField(widget, kind)
            if value is None:
                continue
            self.config.set(section, key, value)

        self.validate()
        return self.config

    def validate(self) -> list:
        problems = self.config.validate() if self.config is not None else []
        self.problemsLabel.visible = bool(problems)
        self.problemsLabel.setText(" ".join(problems))
        return problems

    # -- internals ------------------------------------------------------------------------------------
    def _refreshFields(self):
        if self.config is None:
            return

        self.imageLabel.setText(describe_image(self.config))

        for (section, key), (widget, kind) in self._widgets.items():
            if kind == "bool":
                widget.setChecked(bool(self.config.get_bool(section, key, False)))
            elif kind == "bc":
                value = self.config.get_int(section, key, 0)
                index = widget.findData(value)
                widget.setCurrentIndex(index if index >= 0 else 0)
            elif kind == "int":
                widget.setValue(int(self.config.get_int(section, key, 0) or 0))
            elif kind == "float":
                widget.setValue(float(self.config.get_float(section, key, 0.0) or 0.0))
            else:
                values = self.config.get_list(section, key, []) or []
                widget.setText(", ".join(str(item) for item in values))

    @staticmethod
    def _readField(widget, kind):
        if kind == "bool":
            return bool(widget.checked)
        if kind == "bc":
            return int(widget.currentData)
        if kind == "int":
            return int(widget.value)
        if kind == "float":
            return float(widget.value)

        text = widget.text.strip()
        if not text:
            return None
        values = [item.strip() for item in text.split(",") if item.strip()]
        return [float(item) if _looks_numeric(item) else item for item in values]


def describe_image(config: WaterflowConfig) -> str:
    """One line naming the image ``config`` reads and its size, in the X×Y×Z order ``Domain.N`` uses."""
    filename = config.get_string("Domain", "Filename")
    if not filename:
        return "None yet: write one from the Case section."

    shape = config.domain_shape_zyx()
    if not shape:
        return filename
    return f"{filename} ({'×'.join(str(size) for size in reversed(shape))} voxels)"


def _looks_numeric(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False
