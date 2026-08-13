"""Build the full multi-language GeoSlicer Manual locally and open it in a browser.

This builds the orchestrator config (mkdocs.yml), which in turn builds every
language into ``site/<lang>`` and writes a root redirect. The output layout is
identical to what gets deployed, so local previews match production.
"""

import subprocess
import sys
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).parent
SITE_DIR = BASE_DIR / "site"

subprocess.check_call(
    [
        sys.executable,
        "-m",
        "mkdocs",
        "build",
        "--config-file",
        str(BASE_DIR / "mkdocs.yml"),
        "--site-dir",
        str(SITE_DIR),
    ]
)

webbrowser.open((SITE_DIR / "index.html").as_uri())
