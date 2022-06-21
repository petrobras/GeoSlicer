import os
from pathlib import Path
import subprocess
import sys

subprocess.check_call([sys.executable, "-m", "mkdocs", "build", "--site-dir", "site"])

import webbrowser

webbrowser.open(Path(os.getcwd()) / "site" / "index.html")
