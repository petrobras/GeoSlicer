import qt

from unittest.mock import patch

from commons.slicer.app import MANUAL_BASE_URL
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.widget.help_button import HelpButton, is_url

VALID_URL = MANUAL_BASE_URL
INVALID_URL = "not_a_url"


class HelpButtonTest(LTracePluginTest):
    def _createDefaultButton(self):
        widget = HelpButton(parent=self._module_widget.parent)
        widget.show()
        return widget

    def post_setup(self) -> None:
        self.widget = None

    def tear_down(self):
        if self.widget:
            self.widget.deleteLater()

    def test_is_url(self):
        self.assertTrue(is_url("https://example.com"))
        self.assertTrue(is_url("file://some/path"))
        self.assertTrue(is_url("https://example.com"))
        self.assertFalse(is_url("not_a_url"))
        self.assertFalse(is_url(""))
        self.assertFalse(is_url(None))

    def test_init_with_valid_url(self):
        self.widget = HelpButton(url=VALID_URL, parent=self._module_widget.parent)
        self.assertEqual(self.widget.url, VALID_URL)
        self.assertIsNone(self.widget.message)
        self.widget.deleteLater()

    def test_init_with_invalid_url(self):
        self.widget = HelpButton(url=INVALID_URL, parent=self._module_widget.parent)
        self.assertIsNone(self.widget.url)
        self.widget.deleteLater()

    def test_init_with_qurl(self):
        qurl = qt.QUrl(VALID_URL)
        self.widget = HelpButton(url=qurl, parent=self._module_widget.parent)
        self.assertEqual(self.widget.url, VALID_URL)
        self.widget.deleteLater()

    def test_init_with_message(self):
        self.widget = HelpButton(message="**Hello world**", parent=self._module_widget.parent)
        self.assertEqual(self.widget.message, "**Hello world**")
        self.widget.deleteLater()

    def test_message_property_setter(self):
        self.widget = self._createDefaultButton()
        self.assertIsNone(self.widget.message)
        self.widget.message = "Some help text"
        self.assertEqual(self.widget.message, "Some help text")
        self.assertEqual(self.widget.mdMessage, "Some help text")

    def test_update_link_with_valid_url(self):
        self.widget = self._createDefaultButton()
        self.widget.updateLink(VALID_URL)
        self.assertEqual(self.widget.url, VALID_URL)

    def test_update_link_with_invalid_url_falls_back_to_manual(self):
        self.widget = self._createDefaultButton()
        self.widget.updateLink(INVALID_URL)
        self.assertEqual(self.widget.url, MANUAL_BASE_URL)

    def test_update_link_with_qurl(self):
        self.widget = self._createDefaultButton()
        self.widget.updateLink(qt.QUrl(VALID_URL))
        self.assertEqual(self.widget.url, VALID_URL)

    @patch("commons.slicer.widget.help_button.qt.QDesktopServices.openUrl")
    def test_handle_click_with_message_shows_floating_message(self, mock_open_url):
        self.widget = self._createDefaultButton()
        self.widget.message = "**Hello world**"
        self.widget.handleClick()

        self.assertTrue(hasattr(self.widget, "text_browser"))
        self.assertTrue(self.widget.text_browser.visible)
        self.assertIn("Hello world", self.widget.text_browser.toHtml())
        mock_open_url.assert_not_called()

        self.widget.text_browser.hide()
        self.widget.text_browser.deleteLater()

    @patch("commons.slicer.widget.help_button.qt.QDesktopServices.openUrl")
    def test_handle_click_without_message_opens_link(self, mock_open_url):
        self.widget = self._createDefaultButton()
        self.widget.updateLink(VALID_URL)
        self.widget.handleClick()

        mock_open_url.assert_called_once()
        called_url = mock_open_url.call_args[0][0]
        self.assertEqual(called_url.toString(), VALID_URL)

    @patch("commons.slicer.widget.help_button.qt.QDesktopServices.openUrl")
    def test_show_floating_message_uses_replacer(self, mock_open_url):
        self.widget = self._createDefaultButton()
        self.widget.replacer = lambda message: message.replace("{name}", "GeoSlicer")
        self.widget.showFloatingMessage("Hello {name}!")

        self.assertIn("Hello GeoSlicer!", self.widget.text_browser.toHtml())

        self.widget.text_browser.hide()
        self.widget.text_browser.deleteLater()

    @patch("commons.slicer.widget.help_button.qt.QDesktopServices.openUrl", return_value=True)
    def test_handle_link_click_with_valid_string_url(self, mock_open_url):
        self.widget = self._createDefaultButton()
        self.widget.handleLinkClick(VALID_URL)

        mock_open_url.assert_called_once()
        called_url = mock_open_url.call_args[0][0]
        self.assertEqual(called_url.toString(), VALID_URL)

    @patch("commons.slicer.widget.help_button.qt.QDesktopServices.openUrl", return_value=True)
    def test_handle_link_click_with_valid_qurl(self, mock_open_url):
        self.widget = self._createDefaultButton()
        qurl = qt.QUrl(VALID_URL)
        self.widget.handleLinkClick(qurl)

        mock_open_url.assert_called_once_with(qurl)

    @patch("commons.slicer.widget.help_button.qt.QDesktopServices.openUrl")
    def test_handle_link_click_with_invalid_url_falls_back_to_manual(self, mock_open_url):
        self.widget = self._createDefaultButton()
        mock_open_url.return_value = False
        self.widget.handleLinkClick(INVALID_URL)

        self.assertEqual(mock_open_url.call_count, 1)
        fallback_url = mock_open_url.call_args[0][0]
        self.assertEqual(fallback_url.toString(), MANUAL_BASE_URL)

    @patch("commons.slicer.widget.help_button.qt.QDesktopServices.openUrl")
    def test_handle_link_click_hides_text_browser(self, mock_open_url):
        self.widget = self._createDefaultButton()
        self.widget.message = "**Hello world**"
        self.widget.handleClick()
        self.assertTrue(self.widget.text_browser.visible)

        self.widget.handleLinkClick(VALID_URL)
        self.assertFalse(self.widget.text_browser.visible)

        self.widget.text_browser.deleteLater()

    def test_event_filter_hides_widget_on_leave(self):
        self.widget = self._createDefaultButton()
        self.widget.message = "**Hello world**"
        self.widget.handleClick()
        text_browser = self.widget.text_browser
        self.assertTrue(text_browser.visible)

        event = qt.QEvent(qt.QEvent.Leave)
        self.widget.eventFilter(text_browser, event)
        self.assertFalse(text_browser.visible)

        text_browser.deleteLater()
