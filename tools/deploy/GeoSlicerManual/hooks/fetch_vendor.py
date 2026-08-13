"""MkDocs hook: ensure vendored front-end libraries exist before a build.

Runs on every language build (declared in mkdocs.base.yml). It downloads Mermaid and
MathJax into docs/assets/vendor/ on the first build and is a no-op afterwards, so the
site can be searched, and its diagrams/math rendered, with no CDN requests. See
vendor_assets.py for details and the network trade-off.

NOTE: this file is intentionally NOT named vendor_assets.py — MkDocs registers a hook
under its file stem, which would then shadow the top-level vendor_assets module.
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import vendor_assets  # noqa: E402  (path set up above)


def on_config(config):
    vendor_assets.ensure(Path(config["docs_dir"]))
    return config
