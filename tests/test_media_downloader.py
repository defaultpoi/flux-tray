from flux_tray.core.process import ProcessResult
from flux_tray.media.downloader import MediaDownloader


def test_download_uses_resume_subtitles_and_safe_output_name(tmp_path):
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return ProcessResult(tuple(argv), 0, "/tmp/Episode.mkv\n", "")

    downloader = MediaDownloader(runner=runner)
    path = downloader.download({"url": "https://example.test/video",
                                "title": "../Episode S01E01"}, tmp_path)
    assert path == "/tmp/Episode.mkv"
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
        return ProcessResult(tuple(argv), 0, "/tmp/video.mkv\n", "")
    downloader = MediaDownloader(runner=runner)
    downloader.download({"url": "https://example.test/video", "title": "Video"},
                        tmp_path, format_sort="res:653")
    assert calls[0][calls[0].index("-S") + 1] == "res:653"
