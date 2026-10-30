from flux_tray.core.process import ProcessResult
from flux_tray.core.storage import JsonStore
from flux_tray.updates.service import UpdateService


def test_scan_parses_dry_run_and_saves_state(tmp_path):
    def runner(argv, **kwargs):
        assert argv == ["xbps-install", "-Mn", "-u"]
        assert kwargs["env"]["LC_ALL"] == "C.UTF-8"
        return ProcessResult(tuple(argv), 0, "curl-8.1_1 update x86_64 current 10 20\n", "")

    service = UpdateService(JsonStore(tmp_path / "updates.json", dict), runner=runner)
    changes = service.scan_updates()
    assert changes[0].pkgver == "curl-8.1_1"
    assert service.state["changes"][0]["action"] == "update"


def test_orphan_listing_is_sorted_and_deduplicated(tmp_path):
    def runner(argv, **kwargs):
        return ProcessResult(tuple(argv), 0, "zlib\nabc\nzlib\n", "")

    service = UpdateService(JsonStore(tmp_path / "updates.json", dict), runner=runner)
    assert service.list_orphans() == ["abc", "zlib"]
