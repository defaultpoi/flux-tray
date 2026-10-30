from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from flux_tray.core.process import ProcessResult
from flux_tray.media.hls import HlsDownloader, HlsVariant, parse_playlist, pick_variant


def test_parse_hls_vod_duration_and_relative_variants():
    master = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=854x480
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1920x1080
high/index.m3u8
"""
    parsed = parse_playlist(master, "https://media.example.test/master.m3u8")
    assert parsed.variants[0].url == "https://media.example.test/low/index.m3u8"
    assert parsed.variants[1].height == 1080

    media = parse_playlist("""#EXTM3U
#EXTINF:4.5,
seg1.ts
#EXTINF:5.25,
seg2.ts
#EXT-X-ENDLIST
""", "https://media.example.test/video.m3u8")
    assert media.duration == 9.75
    assert media.ended is True


def test_pick_variant_respects_screen_headroom_and_falls_back_to_smallest():
    variants = (
        HlsVariant("480", 854, 480, 800_000),
        HlsVariant("720", 1280, 720, 2_000_000),
        HlsVariant("1080", 1920, 1080, 5_000_000),
    )
    assert pick_variant(variants, (1366, 768)).url == "720"
    assert pick_variant(variants, (640, 360)).url == "480"
    assert pick_variant(variants, None).url == "1080"


def test_hls_download_uses_playlist_duration_and_renames_partial_file(tmp_path):
    playlists = {
        "/master.m3u8": """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=1280x720
vod.m3u8
""",
        "/vod.m3u8": """#EXTM3U
#EXTINF:10,
seg.ts
#EXT-X-ENDLIST
""",
        "/sub.vtt": "WEBVTT\\n\\n00:00:00.000 --> 00:00:01.000\\nPilot\\n",
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = playlists.get(self.path)
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/master.m3u8"
        calls = []
        progress = []

        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            Path(argv[-1]).write_bytes(b"video")
            kwargs["output_callback"]("stdout", "out_time_ms=5000000\n")
            return ProcessResult(tuple(argv), 0, "", "")

        downloader = HlsDownloader(runner=runner)
        result = downloader.download(
            {"url": url, "title": "Example Show S01E02 - Pilot",
             "subs": {"en": f"http://127.0.0.1:{server.server_port}/sub.vtt",
                      "ro": f"http://127.0.0.1:{server.server_port}/missing.srt"}},
            tmp_path, source_name="Example Show", screen=(1366, 768),
            progress_callback=progress.append,
        )
        assert Path(result).name == "Example Show - S01E02 - Pilot.mkv"
        assert Path(result).read_bytes() == b"video"
        assert Path(result).with_name("Example Show - S01E02 - Pilot.en.vtt").is_file()
        assert not Path(result).with_name("Example Show - S01E02 - Pilot.ro.srt").exists()
        assert not Path(result + ".part").exists()
        assert calls[0][0][calls[0][0].index("-i") + 1].endswith("/vod.m3u8")
        assert progress[0]["part_path"].endswith(".mkv.part")
        assert progress[0]["duration"] == 10.0
        assert progress[1]["percent"] == 50.0
        assert progress[-1]["percent"] == 100.0
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_hls_download_rejects_live_playlist(tmp_path):
    playlists = """#EXTM3U
#EXTINF:5,
segment.ts
"""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(playlists)))
            self.end_headers()
            self.wfile.write(playlists.encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        downloader = HlsDownloader(runner=lambda *args, **kwargs: None)
        try:
            downloader.download({"url": f"http://127.0.0.1:{server.server_port}/live.m3u8",
                                 "title": "Live"}, tmp_path, source_name="Live")
        except ValueError as exc:
            assert "Live HLS" in str(exc)
        else:
            raise AssertionError("live playlist was accepted")
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
