"""MkDocs hook: translate navigation labels per language.

Replaces the mkdocs-static-i18n ``nav_translations`` option now that the i18n
plugin has been removed in favour of separate per-language builds.

The navigation tree is defined once, in English, in ``mkdocs.base.yml``. During a
build this hook rewrites the section/page labels using the ``extra.nav_translations``
map supplied by the active language config (e.g. ``mkdocs.pt.yml``). The English
build defines no map, so the hook is a no-op there.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("mkdocs.hooks.nav_i18n")


def _translate_items(items, translations: dict) -> None:
    """Recursively translate the ``title`` of every navigation item in place."""
    for item in items:
        title = getattr(item, "title", None)
        if title is not None and title in translations:
            item.title = translations[title]
        children = getattr(item, "children", None)
        if children:
            _translate_items(children, translations)


def on_nav(nav, config, files):
    extra = config.get("extra") or {}
    translations = extra.get("nav_translations") or {}
    if not translations:
        return nav

    _translate_items(nav.items, translations)
    logger.info("nav_i18n: applied %d navigation label translation(s)", len(translations))
    return nav
