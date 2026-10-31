from pathlib import Path

from flux_tray.core.process import ProcessResult
from flux_tray.media.downloader import MediaDownloader


def _create_download(argv):
    output_dir = Path(argv[argv.index('-P') + 1])
    template = argv[argv.index('-o') + 1]
    path = output_dir / template.replace('%(ext)s', 'mkv')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'version')
    return path


def test_download_uses_resume_subtitles_and_safe_output_name(tmp_path):
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        path = _create_download(argv)
        return ProcessResult(tuple(argv), 0, f"{path}\n", "")

    downloader = MediaDownloader(runner=runner)
    path = downloader.download({"url": "https://example.test/video",
                                "title": "../Episode S01E01"}, tmp_path)
    assert Path(path).is_file()
    assert Path(path).parent == tmp_path.resolve()
    argv = calls[0][0]
    assert "--continue" in argv
    assert "--write-subs" in argv
    assert "--write-auto-subs" in argv
    assert "../" not in argv[argv.index("-o") + 1]
    assert calls[0][1]["timeout"] == downloader.timeout


def test_download_rejects_missing_url(tmp_path):
    downloader = MediaDownloader(runner=lambda *args, **kwargs: None)
    try:
        downloader.download({"title": "Missing URL"}, tmp_path)
    except ValueError:
        pass
    else:
        raise AssertionError("missing URL accepted")


def test_download_passes_resolution_sort_override(tmp_path):
    calls = []
    def runner(argv, **kwargs):
        calls.append(argv)
        path = _create_download(argv)
        return ProcessResult(tuple(argv), 0, f"{path}\n", "")
    downloader = MediaDownloader(runner=runner)
    downloader.download({"url": "https://example.test/video", "title": "Video"},
                        tmp_path, format_sort="res:653")
    assert calls[0][calls[0].index("-S") + 1] == "res:653"


def test_live_hls_episode_is_rejected(tmp_path):
    downloader = MediaDownloader(runner=lambda *args, **kwargs: None)
    try:
        downloader.download({"url": "https://example.test/live.m3u8", "title": "Live",
                              "metadata": {"live_status": "is_live"}}, tmp_path)
    except ValueError as exc:
        assert "Live HLS" in str(exc)
    else:
        raise AssertionError("live HLS episode was accepted")



def test_download_reports_progress_callback(tmp_path):
    progress = []
    def runner(argv, **kwargs):
        assert "--newline" in argv
        assert "--progress-template" in argv
        kwargs["output_callback"]("stderr", "FLUX_PROGRESS|500|1000|1000|10\n")
        path = _create_download(argv)
        return ProcessResult(tuple(argv), 0, f"{path}\n", "")

    downloader = MediaDownloader(runner=runner)
    downloader.download({"url": "https://example.test/video", "title": "Video"},
                        tmp_path, progress_callback=progress.append)
    assert progress[-1]["percent"] == 50.0
    assert progress[-1]["downloaded_bytes"] == 500.0
    assert progress[-1]["total_bytes"] == 1000.0
    assert progress[-1]["eta"] == 10.0


def test_download_uses_source_directory_and_episode_filename(tmp_path):
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        path = _create_download(argv)
        return ProcessResult(tuple(argv), 0, f"{path}\n", "")

    downloader = MediaDownloader(runner=runner)
    downloader.download(
        {"url": "https://example.test/video", "title": "Example Show S01E02 - Pilot"},
        tmp_path, source_name="Example Show",
    )
    argv = calls[0]
    assert argv[argv.index("-P") + 1] == str(tmp_path)
    assert argv[argv.index("-o") + 1] == (
        "Example Show - S01E02 - Pilot.%(ext)s"
    )

def test_download_rejects_reported_path_outside_output_directory(tmp_path):
    outside = tmp_path.parent / "outside-media.mkv"
    outside.write_bytes(b"video")

    def runner(argv, **kwargs):
        return ProcessResult(tuple(argv), 0, f"{outside}\n", "")

    downloader = MediaDownloader(runner=runner)
    try:
        downloader.download({"url": "https://example.test/video", "title": "Video"},
                            tmp_path)
    except RuntimeError as exc:
        assert "outside the configured media directory" in str(exc)
    else:
        raise AssertionError("download path outside output directory was accepted")


def test_download_rejects_missing_reported_file(tmp_path):
    def runner(argv, **kwargs):
        return ProcessResult(tuple(argv), 0, f"{tmp_path / 'missing.mkv'}\n", "")

    downloader = MediaDownloader(runner=runner)
    try:
        downloader.download({"url": "https://example.test/video", "title": "Video"},
                            tmp_path)
    except RuntimeError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("missing downloaded file was accepted")


def test_download_rejects_malformed_http_url_before_running(tmp_path):
    calls = []
    downloader = MediaDownloader(runner=lambda *args, **kwargs: calls.append(args))
    try:
        downloader.download({"url": "https://example.test:bad/video", "title": "Video"},
                            tmp_path)
    except ValueError as exc:
        assert "valid HTTP or HTTPS URL" in str(exc)
    else:
        raise AssertionError("Malformed download URL was accepted")
    assert calls == []
