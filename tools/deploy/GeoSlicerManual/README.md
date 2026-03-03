# GeoSlicer Manual

This directory contains the source files for the GeoSlicer user manual, built using [MkDocs](https://www.mkdocs.org/) with internationalization support.

## Structure

- `docs/`: Source files for the manual
  - English pages are directly in `docs/Pages/en/`
  - Portuguese translations are in `docs/Pages/pt/`
- `mkdocs.yml`: MkDocs configuration file
- `theme/`: Custom theme overrides
- `build.py`: Script to build and preview the manual locally
- `deploy_manual.py`: Script to deploy the manual to GitHub Pages
- `translate.py`: Script to translate English pages to Portuguese using Gemini API

## Updating the Manual

To update the manual, follow these steps:

### 1. Edit English Pages

Edit the English Markdown files in the `docs/` directory. The structure mirrors the navigation defined in `mkdocs.yml`.

- Use standard Markdown syntax
- Images and assets go in `docs/assets/`
- Follow the existing structure for consistency

### 2. Translate to Portuguese

After editing English pages, translate them to Portuguese:

```bash
# Set up your Gemini API key in the repository root .env file
# GEMINI_API_KEY=your_api_key_here

# Translate a single file
python translate.py --input-path docs/Pages/en/Multicore.md --output-dir docs/pt --language Portuguese

# Translate all files in a directory
python translate.py --input-path docs/ --output-dir docs/pt --language Portuguese --skip-existing

# Force re-translation of existing files
python translate.py --input-path docs/ --output-dir docs/pt --language Portuguese --force
```

**Important Notes:**
- The translation script preserves Markdown formatting, code blocks, URLs, and Jinja templates
- Review translations manually for accuracy, as automated translation may not capture technical nuances perfectly
- Maintain the same file structure in `docs/pt/` as in `docs/`

### 3. Build and Preview

Build the manual locally to preview changes:

```bash
python build.py
```

This will:
- Build the site using MkDocs
- Open the built site in your default browser

### 4. Deploy

When ready to deploy:

```bash
# Deploy a new version (replace X.Y with actual MAJOR.MINOR version, e.g. 2.8)
python deploy_manual.py X.Y latest

# Deploy and set as default
python deploy_manual.py X.Y latest --set-default
```

The script uses [Mike](https://github.com/jimporter/mike) for versioned documentation deployment to GitHub Pages.

## Requirements

- Python 3.9+
- MkDocs with plugins (see `requirements.txt` in parent directory)
- Gemini API key for translations
- Git remote configured for deployment

## Best Practices

- Always update both English and Portuguese versions
- Test links and navigation after changes
- Use descriptive commit messages
- Follow the existing Markdown style and structure
- Validate builds before deploying