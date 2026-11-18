"""Run an arbitrary command, then scrub partner workspace members out of uv.lock.

`pyproject.toml` declares `src/partners/*` as a uv workspace member so that local
`uv sync`/IDE tooling resolves partner packages when their (gitignored, private)
folders are checked out. But that means `uv.lock` -- a file committed to this public
repository -- ends up describing private partner packages and their dependencies
whenever it's regenerated on a machine that has those folders present.

Partner dependencies are actually installed independently of uv, via
`partner_setup.install_partner_dependencies` (plain `pip install`), so nothing relies
on uv.lock including them. This script removes them from the committed lock:
it temporarily moves any `src/partners/*` folders aside, asks `uv lock` to
re-resolve (uv then naturally omits packages nothing references anymore), and moves
the folders back.

Any pre-commit hook invoked via `uv run` (pylic-check, pytest, ...) must clean up
after itself this way, in the same process, rather than as a separate trailing hook.
`uv run` silently re-adds partner entries to uv.lock whenever it detects them missing
while the workspace member is declared and the folder exists -- so a previously
committed "clean" uv.lock gets re-dirtied the moment any `uv run`-based hook executes
against it. Bundling both steps in one hook invocation means a re-run against an
already-cleaned uv.lock is a no-op from pre-commit's point of view: whatever `uv run`
silently restores at the start, this script strips again before exiting.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from deploy.utils import get_repo_root

REPO_ROOT = get_repo_root()
PARTNERS_DIR = REPO_ROOT / "src" / "partners"
LOCK_PATH = REPO_ROOT / "uv.lock"


def clean_partner_entries_from_lock() -> None:
    partner_dirs = [d for d in PARTNERS_DIR.glob("*") if d.is_dir()] if PARTNERS_DIR.exists() else []
    if not partner_dirs:
        return

    if "src/partners/" not in LOCK_PATH.read_text():
        return

    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp:
        tmp_dir = Path(tmp)
        moved = []
        try:
            for partner_dir in partner_dirs:
                destination = tmp_dir / partner_dir.name
                shutil.move(str(partner_dir), str(destination))
                moved.append((destination, partner_dir))

            subprocess.run(["uv", "lock"], cwd=REPO_ROOT, check=True)
        finally:
            for destination, original_path in moved:
                shutil.move(str(destination), str(original_path))


def main() -> int:
    command = sys.argv[1:]
    # Force UTF-8 I/O: tools like pylic print emoji, which crashes on Windows' default cp1252 console encoding.
    env = {**os.environ, "PYTHONUTF8": "1"}
    result = subprocess.run(command, env=env)

    clean_partner_entries_from_lock()

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
