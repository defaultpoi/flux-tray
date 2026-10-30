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


def test_topgrade_runs_system_and_configured_steps(monkeypatch, tmp_path):
    calls = []
    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return ProcessResult(tuple(argv), 0, "Topgrade completed", "")
    monkeypatch.setattr("flux_tray.updates.service.shutil.which", lambda _name: "/usr/bin/topgrade")
    service = UpdateService(JsonStore(tmp_path / "updates.json", dict), runner=runner,
                            installer="topgrade", topgrade_steps=("cargo", "rustup", "cargo"))
    result = service.apply_updates()
    assert result.returncode == 0
    assert calls[0][0] == ["topgrade", "--only", "system", "cargo", "rustup", "--yes", "--no-retry"]
    assert calls[0][1]["env"]["LC_ALL"] == "C.UTF-8"
    assert calls[0][1]["shutdown_protected"] is True


def test_topgrade_missing_falls_back_to_individual_xbps_updates(monkeypatch, tmp_path):
    calls = []
    def runner(argv, **kwargs):
        calls.append(argv)
        return ProcessResult(tuple(argv), 0, "", "")
    monkeypatch.setattr("flux_tray.updates.service.shutil.which", lambda _name: None)
    service = UpdateService(JsonStore(tmp_path / "updates.json", dict), runner=runner,
                            installer="topgrade")
    service.state["changes"] = [
        {"pkgver": "curl-8.1_1"},
        {"pkgver": "libfoo-devel-1.0_1"},
    ]
    results = service.apply_updates()
    assert len(results) == 2
    assert calls[0][-4:] == ["xbps-install", "-y", "-u", "curl"]
    assert calls[1][-4:] == ["xbps-install", "-y", "-u", "libfoo-devel"]
