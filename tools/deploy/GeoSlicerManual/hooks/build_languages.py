"""MkDocs hook for the orchestrator config (mkdocs.yml).

The manual is built one language at a time (mkdocs.en.yml / mkdocs.pt.yml) so that
each language gets its own clean, single-language search index. This hook glues
those independent builds into a single output folder, so a single
``mkdocs build -f mkdocs.yml`` produces the whole multi-language site:

    <site_dir>/index.html   -> redirect to the default language
    <site_dir>/en/...        -> English site (own search index)
    <site_dir>/pt/...        -> Portuguese site (own search index)

This is what keeps ``mike`` / deploy_manual.py working unchanged: ``mike`` still runs
a single ``mkdocs build`` for the orchestrator config and commits the resulting
folder as one version.

The orchestrator config itself does NOT inherit mkdocs.base.yml and does NOT load
this file's siblings, so the per-language sub-builds (which do) never re-trigger this
hook -- there is no recursion.
"""

import subprocess
import sys
from pathlib import Path

# Languages to build, in order. The first one is used as the default for the
# site-root redirect.
LANGUAGES = ("en", "pt")
DEFAULT_LANGUAGE = LANGUAGES[0]

# Directory that holds the config files (this hook lives in <root>/hooks/).
ROOT_DIR = Path(__file__).resolve().parent.parent

REDIRECT_HTML = """<!doctype html>
<html lang="{lang}">
  <head>
    <meta charset="utf-8">
    <title>GeoSlicer Manual</title>
    <meta http-equiv="refresh" content="0; url=./{lang}/index.html">
    <link rel="canonical" href="./{lang}/index.html">
  </head>
  <body>
    <p>Redirecting to the <a href="./{lang}/index.html">GeoSlicer Manual</a>&hellip;</p>
  </body>
</html>
"""


def on_post_build(config):
    site_dir = Path(config["site_dir"])

    for language in LANGUAGES:
        language_config = ROOT_DIR / f"mkdocs.{language}.yml"
        target_dir = site_dir / language
        print(f"[build_languages] Building '{language}' -> {target_dir}")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "mkdocs",
                "build",
                "--config-file",
                str(language_config),
                "--site-dir",
                str(target_dir),
            ],
            cwd=str(ROOT_DIR),
            check=True,
        )

    redirect_path = site_dir / "index.html"
    redirect_path.write_text(REDIRECT_HTML.format(lang=DEFAULT_LANGUAGE), encoding="utf-8")
    print(f"[build_languages] Wrote root redirect -> {DEFAULT_LANGUAGE}/")
