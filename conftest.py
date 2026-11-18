import pytest
import sys

from pathlib import Path
from unittest.mock import MagicMock

import _slicer_mocks

PROJECT_ROOT = Path(__file__).parent.resolve()


def pytest_addoption(parser):
    """Register the custom --partner flag."""
    parser.addoption(
        "--partner",
        action="store",
        default=None,
        help="Include tests for a specific partner. If omitted, partner tests are skipped.",
    )


def _configure_partner(partner_dir):
    # Support partner source roots
    partner_src = partner_dir / "src"
    if partner_src.exists():
        sys.path.insert(0, str(partner_src))

        # Support partner third-parties
        partner_tp = partner_src / "third-parties"
        if partner_tp.exists():
            for tp in partner_tp.iterdir():
                if tp.is_dir():
                    sys.path.insert(0, str(tp))

    # Fallback to partner root
    sys.path.insert(0, str(partner_dir))


def pytest_configure(config):
    """Dynamically configure the environment based on the partner flag."""
    partner_name = config.getoption("--partner")
    partners_root = PROJECT_ROOT / "src" / "partners"
    if partner_name:
        partner_dir = partners_root / partner_name
        if not partner_dir.exists():
            print(f"Error: Partner directory not found: {partner_dir}")
            sys.exit(1)
        _configure_partner(partner_dir)
    elif partners_root.exists():
        # Auto-discover all partners under src/partners
        for partner_dir in partners_root.iterdir():
            if partner_dir.is_dir():
                _configure_partner(partner_dir)


def pytest_ignore_collect(collection_path, config):
    """Ignore partner folders that don't match --partner."""
    partner_opt = config.getoption("--partner")

    # Convert to Path and get relative path to PROJECT_ROOT
    try:
        rel_path = Path(collection_path).relative_to(PROJECT_ROOT)
    except ValueError:
        return None

    path_parts = rel_path.parts
    if len(path_parts) >= 2 and path_parts[0] == "src" and path_parts[1] == "partners":
        # If a specific partner was requested, ignore every other partner's subtree.
        # path_parts[2] is the partner name (e.g., 'partner' in 'src/partners/partner/...')
        if partner_opt and len(path_parts) > 2 and path_parts[2] != partner_opt:
            return True

    return None


# Mandatory mocks for external dependencies not available in unit test environment.
# tests/mock_modules is in the pytest pythonpath, so spawned child processes (Windows) import the same mocks.
_slicer_mocks.install()

# Workaround for scipy 1.14+ compatibility with older openpnm versions
# TerminationCondition was removed/moved in scipy.optimize.nonlin
try:
    import scipy.optimize.nonlin

    if not hasattr(scipy.optimize.nonlin, "TerminationCondition"):
        scipy.optimize.nonlin.TerminationCondition = MagicMock()
except ImportError:
    pass

# Safe import for project modules
try:
    from Charts.Plots.BasePlotWidget import BasePlotWidget
except ImportError:
    BasePlotWidget = MagicMock()


@pytest.fixture
def base_plot_widget(qtbot):
    widget = BasePlotWidget(plotLabel="label_test", plotType="type_test")
    qtbot.addWidget(widget)
    yield widget
