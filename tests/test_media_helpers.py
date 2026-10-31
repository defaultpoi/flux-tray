from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from flux_tray.media.helpers import download_file, fetch_json


def _serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_resumable_download_appends_only_the_requested_range(tmp_path):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.headers.get("Range"))
            body = b"world"
            self.send_response(206)
            self.send_header("Content-Range", "bytes 6-10/11")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server, thread = _serve(Handler)
    try:
        destination = tmp_path / "episode.bin"
        destination.with_suffix(".bin.part").write_bytes(b"hello ")
        result = download_file(
            f"http://127.0.0.1:{server.server_port}/episode.bin", destination
        )
        assert requests == ["bytes=6-"]
        assert result == str(destination)
        assert destination.read_bytes() == b"hello world"
        assert not destination.with_suffix(".bin.part").exists()
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_resumable_download_rejects_mismatched_content_range(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"fresh"
            self.send_response(206)
            self.send_header("Content-Range", "bytes 0-4/5")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server, thread = _serve(Handler)
    try:
        destination = tmp_path / "episode.bin"
        partial = destination.with_suffix(".bin.part")
        partial.write_bytes(b"old")
        with pytest.raises(ValueError, match="invalid range"):
            download_file(
                f"http://127.0.0.1:{server.server_port}/episode.bin", destination
            )
        assert partial.read_bytes() == b"old"
        assert not destination.exists()
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_resumable_download_restarts_when_server_ignores_range(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"fresh"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server, thread = _serve(Handler)
    try:
        destination = tmp_path / "episode.bin"
        destination.with_suffix(".bin.part").write_bytes(b"stale partial data")
        download_file(
            f"http://127.0.0.1:{server.server_port}/episode.bin", destination
        )
        assert destination.read_bytes() == b"fresh"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

def test_resumable_download_rejects_empty_response(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args):
            pass

    server, thread = _serve(Handler)
    try:
        destination = tmp_path / "empty.bin"
        with pytest.raises(RuntimeError, match="without receiving any data"):
            download_file(
                f"http://127.0.0.1:{server.server_port}/empty.bin", destination
            )
        assert not destination.exists()
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

def test_plugin_http_helpers_reject_header_line_breaks(tmp_path):
    with pytest.raises(ValueError, match="line breaks"):
        download_file(
            "https://example.test/video",
            tmp_path / "video.bin",
            headers={"X-Test": "value" + chr(13) + chr(10) + "Injected: yes"},
        )

def test_resumable_download_does_not_append_bytes_beyond_range(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"abcd"
            self.send_response(206)
            self.send_header("Content-Range", "bytes 3-5/10")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server, thread = _serve(Handler)
    try:
        destination = tmp_path / "episode.bin"
        partial = destination.with_suffix(".bin.part")
        partial.write_bytes(b"old")
        with pytest.raises(RuntimeError, match="exceeded the expected byte count"):
            download_file(
                f"http://127.0.0.1:{server.server_port}/episode.bin", destination
            )
        assert partial.read_bytes() == b"oldabc"
        assert not destination.exists()
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()




@pytest.mark.parametrize("url", ["http:///missing-host", "http://example.test:99999/video"])
def test_plugin_download_rejects_malformed_http_authorities(tmp_path, url):
    with pytest.raises(ValueError, match="valid HTTP"):
        download_file(url, tmp_path / "video.bin")
    assert not (tmp_path / "video.bin.part").exists()


@pytest.mark.parametrize("url", ["http:///missing-host", "http://example.test:99999/data"])
def test_plugin_json_fetch_rejects_malformed_http_authorities(url):
    with pytest.raises(ValueError, match="valid HTTP"):
        fetch_json(url)


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan")])
def test_plugin_download_rejects_invalid_timeout(tmp_path, timeout):
    with pytest.raises(ValueError, match="finite positive"):
        download_file("https://example.test/video", tmp_path / "video.bin", timeout=timeout)


@pytest.mark.parametrize("timeout", [0, -1, True, float("inf")])
def test_plugin_json_fetch_rejects_invalid_timeout(timeout):
    with pytest.raises(ValueError, match="finite positive"):
        fetch_json("https://example.test/data", timeout=timeout)


@pytest.mark.parametrize("max_bytes", [0, -1, True])
def test_plugin_json_fetch_requires_positive_integer_limit(max_bytes):
    with pytest.raises(ValueError, match="positive integer"):
        fetch_json("https://example.test/data", max_bytes=max_bytes)
