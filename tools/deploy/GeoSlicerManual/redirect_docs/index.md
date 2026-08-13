<!--
  Source for the site-root redirect page produced by the orchestrator config
  (mkdocs.yml). The final index.html is rewritten by hooks/build_languages.py to a
  minimal, theme-free redirect, but this fallback keeps the page working even if
  that hook does not run. The link is raw HTML on purpose: the /en/ site is built
  by the hook (not part of this config's docs), so a Markdown link would trip
  MkDocs' link validation.
-->
<meta http-equiv="refresh" content="0; url=./en/index.html">

# GeoSlicer Manual

<p>Redirecting to the <a href="./en/index.html">English documentation</a>&hellip;</p>
