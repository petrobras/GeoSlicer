import logging
import os
import re
from typing import Union
from pathlib import Path


logger = logging.getLogger(__name__)


def search_referenced_file_url(
    env: object,
    docs_path: Path,
    page_src_path: Path,
    reference_url: str,
    source_dir: Path,
) -> Union[str, None]:
    """Search for a referenced file and return its relative URL.

    Args:
        env: The mkdocs-macros plugin environment.
        docs_path: The path to the documentation source directory.
        page_src_path: The source path of the page being processed.
        reference_url: The URL of the referenced file.
        source_dir: The directory of the source file containing the reference.

    Returns:
        The relative URL of the referenced file, or None if it exists in the same root.
    """
    config = env.variables["config"]
    docs_dir = Path(config.get("docs_dir"))
    target_dir = docs_dir / page_src_path.parent

    # Check if the referenced URL exists in the same root as the current source file,
    # if so, maintain the relative path
    relative_link_file_path = docs_path.resolve() / page_src_path.parent / reference_url
    if relative_link_file_path.exists() and relative_link_file_path.is_file():
        return None

    # Fallback for relative path from the 'docs' directory:
    linked_file_path = source_dir / reference_url
    new_relative_url = os.path.relpath(linked_file_path, target_dir.resolve())
    new_relative_url = new_relative_url.replace("\\", "/")
    return new_relative_url


def adjust_included_markdown(env: object, locale_file_path: Path) -> str:
    """Adjusts markdown links in an included file to be relative to the page.

    Args:
        env: The mkdocs-macros plugin environment.
        locale_file_path: The path to the markdown file to be included.

    Returns:
        The rewritten markdown content.
    """
    with open(locale_file_path, "r", encoding="utf-8") as f:
        text = f.read()

    page = env.variables["page"]
    page_src_path = Path(page.file.src_path)
    config = env.variables["config"]
    docs_dir = Path(config.get("docs_dir"))

    source_dir = locale_file_path.parent

    def rewrite_link(match: re.Match) -> str:
        is_image = match.group(1)
        link_text = match.group(2)
        link_url = match.group(3)

        # Skip absolute, root-relative, anchor, and mailto links
        if link_url.startswith(("http://", "https://", "/", "#", "mailto:")):
            return match.group(0)

        # Skip video files, as they are handled by the video macro
        video_extensions = [".mp4", ".webm", ".ogg", ".mov"]
        if any(link_url.lower().endswith(ext) for ext in video_extensions):
            return match.group(0)

        url_part, anchor_part = (link_url, "")
        if "#" in link_url:
            parts = link_url.split("#", 1)
            url_part = parts[0]
            anchor_part = "#" + parts[1]
        else:
            url_part = link_url

        if not url_part:
            return match.group(0)

        url = search_referenced_file_url(
            env=env, docs_path=docs_dir, page_src_path=page_src_path, reference_url=url_part, source_dir=source_dir
        )
        if not url:
            return match.group(0)

        return f"{is_image}[{link_text}]({url}{anchor_part})"

    # Regex to find markdown links and images: ![alt](src) or [text](url)
    link_regex = r"(!?)\[([^\]]*)\]\(([^\)]+)\)"
    rewritten_text = re.sub(link_regex, rewrite_link, text)

    return rewritten_text


def define_env(env: object) -> None:
    @env.macro
    def video(name: str, caption: str = None) -> str:
        """A macro to embed a video.

        Args:
            name: The name of the video file.
            caption: An optional caption for the video.

        Returns:
            The HTML for the video.
        """
        extension = name.split(".")[-1].lower()

        page = env.variables["page"]
        page_dir = Path(page.file.src_path).parent
        depth = len(page_dir.parts) + 1

        relative_path_to_videos = Path(*[".."] * depth) / "assets" / "videos"
        video_path = (relative_path_to_videos / name).as_posix()

        video_html = (
            f'<video controls width="100%">'
            f'  <source src="{video_path}" type="video/{extension}" >'
            f"  Your browser does not support the video tag."
            f"</video>"
        )

        if caption:
            return (
                f'<figure class="video-container">'
                f"  {video_html}"
                f"  <figcaption>{caption}</figcaption>"
                f"</figure>"
            )
        else:
            return video_html

    @env.macro
    def include_markdown(markdown_file_name: str) -> str:
        """A macro to include a markdown file into another.

        This macro handles language fallbacks for internationalization.

        Args:
            markdown_file_name: The name of the markdown file to include.

        Returns:
            The rendered HTML of the included markdown file.

        Raises:
            RuntimeError: If the markdown file is not found.
        """
        config = env.variables["config"]
        theme = config.theme
        docs_dir = Path(config.get("docs_dir", "."))

        default_language = "en"
        locale = theme.get("language", default_language)

        pages_path = docs_dir / "Pages"
        locale_file_path = pages_path / locale / f"{markdown_file_name}.md"

        if not locale_file_path.exists():
            logger.warning(
                f"Markdown file '{locale_file_path}' not found. "
                f"Trying to use the default language version ({default_language})..."
            )
            locale_file_path = pages_path / default_language / f"{markdown_file_name}.md"

            if not locale_file_path.exists():
                raise RuntimeError(f"Markdown file '{locale_file_path}' not found. Cancelling process")

        rewritten_text = adjust_included_markdown(env, locale_file_path)
        return env.render(rewritten_text, env.variables) + "\n"
