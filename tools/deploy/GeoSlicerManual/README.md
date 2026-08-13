# GeoSlicer Manual

This directory contains the source files for the GeoSlicer user manual, built using
[MkDocs](https://www.mkdocs.org/) + [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
with multi-language support.

## How multi-language works

Each language is built **independently** into its own subfolder of a single output
folder. That is the key to keeping the search index clean:

- one `mkdocs build` per language → **one clean, single-language search index each**;
- the raw translation sources in `docs/Pages/` are excluded from the build, so they
  never pollute search or appear as standalone pages.

```
site/
├── index.html      # redirect to the default language (English)
├── en/             # English site   (en/search/search_index.json + .js)
└── pt/             # Portuguese site (pt/search/search_index.json + .js)
```

There is **no** `mkdocs-static-i18n` plugin. Page content is pulled per language by
the `include_markdown` macro (defined in `main.py`), and navigation labels are
translated by a small hook (`hooks/nav_i18n.py`).

### The build chain

Nothing is auto-discovered by filename — the configs reference each other explicitly:

```
mkdocs build                       (no -f defaults to mkdocs.yml)
   └─ mkdocs.yml       ORCHESTRATOR — builds the root redirect, then its hook
        │               (hooks/build_languages.py) runs, as subprocesses:
        ├─ mkdocs build -f mkdocs.en.yml  --site-dir site/en
        └─ mkdocs build -f mkdocs.pt.yml  --site-dir site/pt
                 │                    │
                 └──── INHERIT ──► mkdocs.base.yml  (shared; never built directly)
```

- `mkdocs.yml` = build **all** languages (used by `build.py`, `mike` / `deploy_manual.py`).
- `mkdocs.<lang>.yml` = build/serve **one** language (fast authoring).
- `mkdocs.base.yml` = shared include, pulled in via each language's `INHERIT`.

### Configuration & supporting files

| File | Purpose |
|------|---------|
| `mkdocs.base.yml` | Shared config: theme, plugins (`search`, `offline`, `macros`, …), markdown extensions, the (single) `nav`, `extra.alternate` language switcher, and `exclude_docs: Pages/`. Not built directly. |
| `mkdocs.en.yml` | English build. `INHERIT`s base; sets `theme.language: en`. |
| `mkdocs.pt.yml` | Portuguese build. `INHERIT`s base; sets `theme.language: pt` and the `extra.nav_translations` label map. |
| `mkdocs.yml` | **Orchestrator.** Builds the root redirect and runs `hooks/build_languages.py`, which builds every language into `site/<lang>`. This is what `build.py` and `mike` use. |
| `hooks/nav_i18n.py` | `on_nav` hook that translates navigation labels from `extra.nav_translations` (replaces the old i18n `nav_translations`). |
| `hooks/build_languages.py` | Orchestrator `on_post_build` hook. Builds each language in `LANGUAGES` into `site/<lang>` and writes the root redirect. |
| `hooks/fetch_vendor.py` | Build hook that ensures the vendored front-end libs (Mermaid, MathJax) are present before each build. |
| `redirect_docs/index.md` | Tiny docs source for the orchestrator's root redirect page. |
| `main.py` | Defines the `include_markdown` and `video` macros. |
| `vendor_assets.py` | Downloads Mermaid + MathJax into the git-ignored `docs/assets/vendor/` at build time (no CDN at runtime). |
| `build.py` | Local build + browser preview (via the orchestrator). |
| `deploy_manual.py` | Versioned deploy to GitHub Pages via `mike`. |
| `translate.py` | Translates English pages to another language using the Gemini API. |
| `docs/assets/javascripts/language-switcher.js` | Rewrites the language-switcher links at runtime so switching language keeps you on the **same** page. |

### Content structure

- Navigable pages (`docs/**/*.md`, e.g. `docs/Volumes/Introduction.md`) are thin,
  language-agnostic wrappers: front-matter + a `{{ include_markdown("PageName") }}`.
- The actual translated content lives in:
  - English: `docs/Pages/en/PageName.md`
  - Portuguese: `docs/Pages/pt/PageName.md`
- If a translated source is missing, the macro automatically falls back to English.
- Images and assets go in `docs/assets/`.

### Search (works both online and offline)

The manual is served two ways — deployed to GitHub Pages (`https://`) **and** opened
directly from disk (`file://`, e.g. `build.py` and the copy bundled with GeoSlicer).
Search works in both because of two plugins in `mkdocs.base.yml`:

- `search` builds the index (`search_index.json`), used over `http(s)://` via `fetch()`.
- `offline` (Material's own plugin) additionally emits `search_index.js`
  (`var __index = …`). Browsers block `fetch()` of local files over `file://`, so on
  that protocol Material loads the `.js` via a `<script>` tag instead.

Material's bundle picks the right one at runtime based on `location.protocol`, so the
same build searches correctly whether opened online or offline.

> **Offline without internet:** for the search *worker* to run over `file://`,
> Material uses the `iframe-worker` shim. By default it would load this from a CDN
> (`unpkg.com`), but we **self-host** it: `mkdocs.base.yml` declares the bundled copy
> under `extra.polyfills`, which makes the `offline` plugin skip the CDN. Result:
> offline search needs no internet, and the deployed site makes no external request
> for it.
> ```yaml
> extra:
>   polyfills:
>     - assets/javascripts/iframe-worker.js   # self-hosted; offline plugin skips the unpkg CDN
> ```

### Third-party assets (no CDN at runtime)

The built site loads **no third-party assets** — it works fully offline and makes no
external request on the live site either. Concretely:

- **Fonts:** `theme.font: false` uses system fonts instead of fetching Roboto from
  Google Fonts.
- **Mermaid** (diagrams) and **MathJax** (math) are **self-hosted**. Rather than
  committing several MB of libraries to git, `vendor_assets.py` (run via
  `hooks/fetch_vendor.py` on every build) downloads them into the **git-ignored**
  `docs/assets/vendor/`, and MkDocs copies them into the site. The config points
  `mermaid2.javascript` and `extra_javascript` (MathJax) at those local paths.
  Each download is verified against the `dist.integrity` (SRI) hash npm publishes for
  the pinned version, so a corrupted/tampered download fails the build. This needs no
  upkeep — the expected hash comes from npm, so bumping `*_VERSION` is all that's
  required.

> **Trade-off:** the **first** build needs network access to fetch the vendored
> libraries. They then persist locally (git-ignored) and are reused, so later builds
> — including offline ones — don't need the network. To pin/refresh versions, edit
> `MERMAID_VERSION` / `MATHJAX_VERSION` in `vendor_assets.py` and delete
> `docs/assets/vendor/`. (The only remaining external URLs in the output are ordinary
> hyperlinks in the documentation content, e.g. to GitHub or DOIs.)

## Updating the Manual

### 1. Edit English pages

Edit the English Markdown files in `docs/Pages/en/`. To add a page to the navigation,
edit `nav:` in `mkdocs.base.yml` and create the matching wrapper page under `docs/`
(copy any existing wrapper — front-matter `icon:` + a single `include_markdown` call).

### 2. Translate to Portuguese

Translated content goes in `docs/Pages/pt/` (mirroring `docs/Pages/en/`):

```bash
# Set up your Gemini API key in the repository root .env file
# GEMINI_API_KEY=your_api_key_here

# Translate a single file
python translate.py --input-path docs/Pages/en/Multicore.md --output-dir docs/Pages/pt --language Portuguese

# Translate all English pages, skipping ones already translated
python translate.py --input-path docs/Pages/en --output-dir docs/Pages/pt --language Portuguese --skip-existing

# Force re-translation of existing files
python translate.py --input-path docs/Pages/en --output-dir docs/Pages/pt --language Portuguese --force
```

If you add a new top-level navigation section, also add its Portuguese label to
`extra.nav_translations` in `mkdocs.pt.yml`.

**Important Notes:**
- The translation script preserves Markdown formatting, code blocks, URLs, and Jinja templates.
- Review translations manually for accuracy, as automated translation may not capture technical nuances perfectly.
- Keep the same file names in `docs/Pages/pt/` as in `docs/Pages/en/`.

### 3. Build and preview

```bash
python build.py
```

This builds every language into `site/` (via the orchestrator config) and opens the
site in your browser. The output layout is identical to what gets deployed.

To build/preview a single language while writing (faster):

```bash
mkdocs serve -f mkdocs.pt.yml            # live-reload preview of one language
mkdocs build -f mkdocs.en.yml --site-dir site/en
```

### 4. Deploy

```bash
# Deploy a new version (replace X.Y with actual MAJOR.MINOR version, e.g. 2.8)
python deploy_manual.py X.Y latest

# Deploy and set as default
python deploy_manual.py X.Y latest --set-default
```

Deployment uses [Mike](https://github.com/jimporter/mike) for versioned docs on
GitHub Pages. `mike` runs a single `mkdocs build` against the orchestrator
(`mkdocs.yml`), so one version contains every language under `<version>/en/` and
`<version>/pt/`.

## Adding a new language

Adding a language touches **five spots**, all explicit. The example below adds
Spanish (`es`).

### 1. Add the content — `docs/Pages/es/`

Generate translations with the existing script (a partial set is fine — anything
missing falls back to English automatically):

```bash
python translate.py --input-path docs/Pages/en --output-dir docs/Pages/es --language Spanish --skip-existing
```

### 2. Create `mkdocs.es.yml` (copy `mkdocs.pt.yml`)

```yaml
INHERIT: mkdocs.base.yml

theme:
  language: es          # drives Material's UI strings AND the macro's Pages/es/ lookup

extra:
  nav_translations:     # optional — omit and the nav stays in English
    Overview: Visión general
    Introduction: Introducción
    Installation: Instalación
    # ... same keys as mkdocs.pt.yml
```

Material ships UI translations for common locales (`es` is supported); an unsupported
locale just falls back to English chrome while your content still works.

### 3. Register it in the orchestrator hook — `hooks/build_languages.py`

```python
LANGUAGES = ("en", "pt", "es")     # add "es"
```

This is what makes `build.py` and `mike` build it into `site/es`. `DEFAULT_LANGUAGE`
(the redirect target) stays `en` unless you change it.

### 4. Add it to the language switcher — `mkdocs.base.yml`

```yaml
extra:
  alternate:
    - { name: English,   link: ../en/, lang: en }
    - { name: Português, link: ../pt/, lang: pt }
    - { name: Español,   link: ../es/, lang: es }   # new
```

### 5. Teach the switcher JS the new segment — `docs/assets/javascripts/language-switcher.js`

```js
var LANG_SEGMENT = /\/(en|pt|es)\//;   // add es
```

Without this, the "stay on the same page" language swap won't recognize `/es/` URLs.

You do **not** need to change: the `nav` in `mkdocs.base.yml` (single nav; labels are
translated by the hook), `hooks/nav_i18n.py`, `main.py`, `build.py`, or
`deploy_manual.py`. Preview while translating with `mkdocs serve -f mkdocs.es.yml`.

## Requirements

- Python 3.12+
- MkDocs with plugins (see `requirements.txt` in the parent directory). Search uses
  the `search` + Material `offline` plugins. The `mkdocs-static-i18n`,
  `mkdocs-localsearch`, and `mkdocs-exclude-search` plugins are **no longer required**.
- Network access **on the first build** (to fetch the vendored Mermaid/MathJax; see
  "Third-party assets" above). Later builds reuse the local copies.
- Gemini API key for translations
- Git remote configured for deployment

## Best Practices

- Always update both English and Portuguese versions.
- Test links, navigation, and search after changes (`python build.py`).
- Follow the existing Markdown style and structure.
- Validate builds before deploying (they should produce **no warnings**).
