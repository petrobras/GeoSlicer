"""Fetch third-party front-end libraries into ``docs/assets/vendor/`` at build time.

The manual must work with **no external requests** — both when opened offline from
disk (``file://``, the copy bundled with GeoSlicer) and when deployed to GitHub Pages.
That means Mermaid (diagrams) and MathJax (math) can't be loaded from a CDN.

Rather than committing several MB of minified libraries to git, they are downloaded
here **at build time** into a git-ignored folder and copied into the site by MkDocs.
Trade-off: the first build needs network access; the files then persist locally and
are reused (the functions below are idempotent — they skip anything already present).

Integrity: each tarball is verified against the ``dist.integrity`` (SRI) hash that npm
publishes for the pinned version, so a corrupted or tampered download fails the build.
This needs no maintenance — bumping ``*_VERSION`` is enough; the expected hash comes
from npm automatically.

Invoked automatically for every language build via ``hooks/fetch_vendor.py``; can also
be run directly: ``python vendor_assets.py``.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import tarfile
import urllib.request
from pathlib import Path

logger = logging.getLogger("mkdocs.hooks.vendor_assets")

REGISTRY = "https://registry.npmjs.org"
MERMAID_VERSION = "10.4.0"
MATHJAX_VERSION = "3.2.2"

# Each entry pulls an npm package's tarball and extracts a subset into
# docs/assets/vendor/<name>/. `marker` is the file whose presence means "already
# vendored" (idempotency). `keep` selects which tarball members to extract, by their
# path relative to `prefix`.
VENDOR = [
    {
        "name": "mermaid",
        "package": "mermaid",
        "version": MERMAID_VERSION,
        "prefix": "package/dist/",
        "marker": "mermaid.min.js",
        # Self-contained UMD build (a single file) — avoids the huge ESM chunk graph.
        "keep": lambda rel: rel == "mermaid.min.js",
    },
    {
        "name": "mathjax",
        "package": "mathjax",
        "version": MATHJAX_VERSION,
        "prefix": "package/es5/",
        "marker": "tex-mml-chtml.js",
        # The combined component + the CHTML output fonts it loads at runtime.
        "keep": lambda rel: rel == "tex-mml-chtml.js" or rel.startswith("output/"),
    },
]


class IntegrityError(Exception):
    """Raised when a downloaded tarball does not match npm's published hash."""


def ensure(docs_dir: Path) -> None:
    """Make sure every vendored library is present under ``docs_dir/assets/vendor``."""
    vendor_root = Path(docs_dir) / "assets" / "vendor"
    for spec in VENDOR:
        target = vendor_root / spec["name"]
        if (target / spec["marker"]).exists():
            continue
        logger.info("vendor_assets: fetching '%s@%s'", spec["package"], spec["version"])
        try:
            _download_and_extract(spec, target)
        except IntegrityError:
            # Security signal — never silently continue with unverified bytes.
            raise
        except Exception as error:  # noqa: BLE001 - tolerate transient network issues
            logger.warning(
                "vendor_assets: could not vendor '%s' (%s). Diagrams/math may not "
                "render until this succeeds with network access.",
                spec["name"],
                error,
            )


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def _verify_integrity(payload: bytes, integrity: str, spec: dict) -> None:
    """Verify ``payload`` against an SRI string such as ``sha512-<base64>``."""
    if not integrity or "-" not in integrity:
        raise IntegrityError(f"no integrity hash published for '{spec['name']}'")
    algorithm, expected = integrity.split("-", 1)
    try:
        digest = hashlib.new(algorithm, payload).digest()
    except ValueError as error:
        raise IntegrityError(f"unsupported hash '{algorithm}' for '{spec['name']}'") from error
    actual = base64.b64encode(digest).decode("ascii")
    if actual != expected:
        raise IntegrityError(
            f"integrity mismatch for '{spec['name']}': expected {integrity}, "
            f"got {algorithm}-{actual}"
        )


def _download_and_extract(spec: dict, target: Path) -> None:
    # Ask npm for this exact version's metadata: the canonical tarball URL and the
    # integrity hash it published for it.
    meta = json.loads(_fetch(f"{REGISTRY}/{spec['package']}/{spec['version']}"))
    dist = meta["dist"]

    payload = _fetch(dist["tarball"])
    _verify_integrity(payload, dist.get("integrity", ""), spec)

    prefix = spec["prefix"]
    target_root = target.resolve()
    count = 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.startswith(prefix):
                continue
            rel = member.name[len(prefix):]
            if not rel or not spec["keep"](rel):
                continue

            dest = target / rel
            # Guard against path traversal from a malicious/broken archive.
            if not str(dest.resolve()).startswith(str(target_root)):
                continue

            dest.parent.mkdir(parents=True, exist_ok=True)
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            with extracted, open(dest, "wb") as out:
                out.write(extracted.read())
            count += 1

    logger.info("vendor_assets: verified and vendored %d file(s) into %s", count, target)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ensure(Path(__file__).parent / "docs")
