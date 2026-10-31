import unittest
from unittest import mock

from facade import rt


class TestIsWebUrl(unittest.TestCase):
    def test_http_and_https_addresses_with_a_host_are_web_urls(self):
        for url in ('http://example.com', 'https://example.com/a?b=1#c', 'https://example.com:8443/x',
                    'HTTPS://EXAMPLE.COM/', 'http://[2001:db8::1]/'):
            self.assertTrue(rt.is_web_url(url), url)

    def test_other_schemes_are_not(self):
        for url in ('file:///etc/passwd', 'javascript:alert(1)', 'ssh://host', 'smb://host/share',
                    'ftp://example.com/x', 'data:text/html,hi', 'mailto:a@example.com', 'about:blank'):
            self.assertFalse(rt.is_web_url(url), url)

    def test_no_host_whitespace_or_control_characters_or_bad_port(self):
        for url in ('http://', 'https:///path', 'example.com', '/relative', '', 'https://example.com/a b',
                    'https://example.com/\n', 'https://example.com\x00', 'https://example.com:99999/',
                    'https://example.com:abc/'):
            self.assertFalse(rt.is_web_url(url), repr(url))

    def test_things_that_are_not_text_are_not_web_urls(self):
        for value in (None, 5, b'https://example.com', ['https://example.com']):
            self.assertFalse(rt.is_web_url(value))


class TestOpenLink(unittest.TestCase):
    def test_a_web_address_is_opened(self):
        with mock.patch.object(rt.webbrowser, 'open') as opened:
            self.assertTrue(rt.open_link('https://example.com/a'))
        opened.assert_called_once_with('https://example.com/a')

    def test_a_new_tab_is_asked_for_when_requested(self):
        with mock.patch.object(rt.webbrowser, 'open_new_tab') as tab, mock.patch.object(rt.webbrowser, 'open') as opened:
            self.assertTrue(rt.open_link('https://example.com/a', new_tab=True))
        tab.assert_called_once_with('https://example.com/a')
        opened.assert_not_called()

    def test_a_local_file_or_a_custom_scheme_is_not_handed_to_the_browser(self):
        with mock.patch.object(rt.webbrowser, 'open') as opened, mock.patch.object(rt.webbrowser, 'open_new_tab') as tab:
            self.assertFalse(rt.open_link('file:///etc/passwd'))
            self.assertFalse(rt.open_link('smb://host/share', new_tab=True))
        opened.assert_not_called()
        tab.assert_not_called()

    def test_the_refusal_is_logged_for_the_debug_run(self):
        with mock.patch.object(rt.webbrowser, 'open'), mock.patch.object(rt, '_log') as log:
            rt.open_link('file:///etc/passwd')
        log.assert_called_once()
        self.assertIn('file:///etc/passwd', log.call_args[0][0])


class TestUnreadItemWithAnUnsafeLink(unittest.TestCase):
    def test_the_item_counts_as_read_but_nothing_is_opened(self):
        """Behaviour choice: a click on such an item still marks it read, it just opens nothing."""
        stub = mock.Mock(online=True)
        row = rt.types.SimpleNamespace(entry_id='e1', link='file:///etc/passwd')
        with mock.patch.object(rt.webbrowser, 'open') as opened:
            rt.RssTray.on_row_activated(stub, None, row)
        opened.assert_not_called()
        stub._remove_unread.assert_called_once_with('e1')


if __name__ == '__main__':
    unittest.main()
