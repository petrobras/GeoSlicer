from deploy.GeoSlicerManual import main as macro
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path

import pytest


class TestManualMacro:
    def setup_method(self):
        self.env = MagicMock()
        config_mock = MagicMock()
        config_mock.get.return_value = "/docs"
        config_mock.theme.get.return_value = "en"

        self.env.variables = {"config": config_mock, "page": MagicMock(file=MagicMock(src_path="test_page.md"))}

    def test_search_referenced_file_url_relative_path(self):
        with patch("pathlib.Path.exists") as mock_exists, patch("pathlib.Path.is_file") as mock_is_file:
            mock_exists.return_value = True
            mock_is_file.return_value = True

            result = macro.search_referenced_file_url(
                self.env,
                docs_path=Path("/docs"),
                page_src_path=Path("test_page.md"),
                reference_url="other.md",
                source_dir=Path("/docs/some_dir"),
            )
            assert result is None

    def test_search_referenced_file_url_fallback(self):
        with patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = False

            result = macro.search_referenced_file_url(
                self.env,
                docs_path=Path("/docs"),
                page_src_path=Path("test_page.md"),
                reference_url="other.md",
                source_dir=Path("/docs/some_dir"),
            )
            assert result == "some_dir/other.md"

    def test_adjust_included_markdown(self):
        mock_content = "This is a link to [another page](other.md)."
        with (
            patch("builtins.open", mock_open(read_data=mock_content)),
            patch("deploy.GeoSlicerManual.main.search_referenced_file_url") as mock_search,
        ):
            mock_search.return_value = "some_dir/other.md"

            result = macro.adjust_included_markdown(self.env, Path("/docs/Pages/en/test.md"))
            assert result == "This is a link to [another page](some_dir/other.md)."

    def test_video_macro(self):
        macro.define_env(self.env)
        video_macro = self.env.macro.call_args_list[0][0][0]

        self.env.variables["page"].file.src_path = "index.md"
        result = video_macro("test.mp4", "My Video")
        assert 'src="assets/videos/test.mp4"' in result
        assert "<figcaption>My Video</figcaption>" in result

        self.env.variables["page"].file.src_path = "GettingStarted/InstallationGuide.md"
        result = video_macro("test.webm")
        assert 'src="../assets/videos/test.webm"' in result

        self.env.variables["page"].file.src_path = "Volumes/MicroCTImport/Import.md"
        result = video_macro("test.mp4")
        assert 'src="../../assets/videos/test.mp4"' in result

    def test_include_markdown_macro(self):
        macro.define_env(self.env)
        include_markdown_macro = self.env.macro.call_args_list[1][0][0]

        with (
            patch("pathlib.Path.exists") as mock_exists,
            patch("deploy.GeoSlicerManual.main.adjust_included_markdown") as mock_adjust,
        ):
            mock_exists.return_value = True
            mock_adjust.return_value = "Adjusted markdown"
            self.env.render.return_value = "Rendered markdown"

            result = include_markdown_macro("test_markdown")
            assert result == "Rendered markdown\n"
            mock_adjust.assert_called_once()
            self.env.render.assert_called_once_with("Adjusted markdown", self.env.variables)

    def test_include_markdown_macro_fallback(self):
        macro.define_env(self.env)
        include_markdown_macro = self.env.macro.call_args_list[1][0][0]

        with (
            patch("pathlib.Path.exists") as mock_exists,
            patch("deploy.GeoSlicerManual.main.adjust_included_markdown") as mock_adjust,
        ):
            # Simulate file not found for the given locale, but found for the default
            mock_exists.side_effect = [False, True]
            mock_adjust.return_value = "Adjusted markdown"
            self.env.render.return_value = "Rendered markdown"

            result = include_markdown_macro("test_markdown")
            assert result == "Rendered markdown\n"
            assert mock_exists.call_count == 2

    def test_include_markdown_macro_not_found(self):
        macro.define_env(self.env)
        include_markdown_macro = self.env.macro.call_args_list[1][0][0]

        with patch("pathlib.Path.exists") as mock_exists:
            mock_exists.return_value = False
            with pytest.raises(RuntimeError):
                include_markdown_macro("test_markdown")


@pytest.mark.parametrize(
    "language, file_exists_side_effect, expected_path, expect_error",
    [
        ("en", [True], "/docs/Pages/en/test.md", False),
        ("pt", [False, True], "/docs/Pages/en/test.md", False),
        ("fr", [False, True], "/docs/Pages/en/test.md", False),
        (None, [True], "/docs/Pages/en/test.md", False),
        ("pt", [False, False], None, True),
    ],
)
def test_include_markdown_language_handling(language, file_exists_side_effect, expected_path, expect_error):
    env = MagicMock()
    config_mock = MagicMock()
    config_mock.get.return_value = "/docs"
    if language:
        config_mock.theme = {"language": language}
    else:
        config_mock.theme = {}

    env.variables = {
        "config": config_mock,
        "page": MagicMock(file=MagicMock(src_path="test_page.md")),
    }

    macro.define_env(env)
    include_markdown_macro = env.macro.call_args_list[1][0][0]

    with (
        patch("pathlib.Path.exists") as mock_exists,
        patch("deploy.GeoSlicerManual.main.adjust_included_markdown") as mock_adjust,
    ):
        mock_exists.side_effect = file_exists_side_effect
        mock_adjust.return_value = "adjusted"
        env.render.return_value = "rendered"

        if expect_error:
            with pytest.raises(RuntimeError):
                include_markdown_macro("test")
        else:
            include_markdown_macro("test")
            mock_adjust.assert_called_with(env, Path(expected_path))
