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
        if argv == ["xbps-query", "-l"]:
            return ProcessResult(tuple(argv), 0, "[*] bash-5.1_1 (installed)\n", "")
        return ProcessResult(tuple(argv), 0, "Topgrade completed", "")
    monkeypatch.setattr("flux_tray.updates.service.shutil.which", lambda _name: "/usr/bin/topgrade")
    service = UpdateService(JsonStore(tmp_path / "updates.json", dict), runner=runner,
                            installer="topgrade", topgrade_steps=("cargo", "rustup", "cargo"))
    result = service.apply_updates()
    assert result.returncode == 0
    # Now includes --no-self-update --skip-notify
    assert calls[1][0] == ["topgrade", "--only", "system", "cargo", "rustup", "--yes", "--no-retry", "--no-self-update", "--skip-notify"]
    assert calls[1][1]["env"]["LC_ALL"] == "C.UTF-8"
    assert calls[1][1]["shutdown_protected"] is True


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
    assert calls[1][-4:] == ["xbps-install", "-y", "-u", "curl"]
    assert calls[2][-4:] == ["xbps-install", "-y", "-u", "libfoo-devel"]



def test_maintenance_result_persists_across_scans_and_can_be_dismissed(monkeypatch, tmp_path):
    calls = []
    def runner(argv, **kwargs):
        calls.append(list(argv))
        if argv[0] == "topgrade":
            return ProcessResult(tuple(argv), 1, "", "update failed")
        return ProcessResult(tuple(argv), 0, "curl-8.1_1 update x86_64 current 10 20\n", "")

    monkeypatch.setattr("flux_tray.updates.service.shutil.which", lambda _name: "/usr/bin/topgrade")
    store = JsonStore(tmp_path / "updates.json", dict)
    service = UpdateService(store, runner=runner, installer="topgrade")
    result = service.apply_updates()
    assert result.returncode == 1
    assert service.state["last_action"]["success"] is False
    assert "update failed" in service.state["last_action"]["results"][0]["stderr"]

    service.scan_updates()
    assert service.state["last_action"]["action"] == "System update (Topgrade)"
    service.dismiss_last_action()
    assert "last_action" not in service.state


def test_installed_versions_are_compared_before_and_after_topgrade(monkeypatch, tmp_path):
    snapshots = iter((
        "[*] curl-8.1_1 (installed)\n[*] libfoo-devel-1.0_1 (installed)\n",
        "[*] curl-8.2_1 (installed)\n[*] libfoo-devel-1.0_1 (installed)\n[*] newpkg-2.0_1 (installed)\n",
    ))
    calls = []

    def runner(argv, **kwargs):
        calls.append(list(argv))
        if argv == ["xbps-query", "-l"]:
            return ProcessResult(tuple(argv), 0, next(snapshots), "")
        return ProcessResult(tuple(argv), 0, "Topgrade completed", "")

    monkeypatch.setattr("flux_tray.updates.service.shutil.which", lambda _name: "/usr/bin/topgrade")
    service = UpdateService(JsonStore(tmp_path / "updates.json", dict), runner=runner,
                            installer="topgrade")
    service.apply_updates()
    changes = service.state["last_action"]["version_changes"]
    # Now drops build revision _1 unless it's the only change
    assert changes == [
        {"package": "curl", "old": "8.1", "new": "8.2"},
        {"package": "newpkg", "old": None, "new": "2.0"},
    ]


def test_version_change_parser_uses_package_name_before_version(tmp_path):
    service = UpdateService(JsonStore(tmp_path / "updates.json", dict), runner=lambda *a, **k: None)
    result = ProcessResult(("xbps-query", "-l"), 0,
                           "[*] libfoo-devel-1.2_3 (installed)\n[*] python3.14-3.14.1_1 (installed)\n", "")
    service.runner = lambda *args, **kwargs: result
    assert service._installed_versions() == {
        "libfoo-devel": "1.2_3", "python3.14": "3.14.1_1",
    }


def test_build_revision_dropped_only_when_not_only_change(tmp_path):
    """Test that build revision _N is dropped unless it's the only change."""
    service = UpdateService(JsonStore(tmp_path / "updates.json", dict), runner=lambda *a, **k: None)
    
    # Only build revision changes - should keep full version
    before = {"pkg": "1.0_1", "other": "2.0"}
    after = {"pkg": "1.0_2", "other": "2.0"}
    changes = service._version_changes(before, after)
    # pkg only had build revision change, other unchanged
    assert any(c["package"] == "pkg" and c["old"] == "1.0_1" and c["new"] == "1.0_2" for c in changes)
    # other unchanged, not in changes


def test_build_revision_dropped_when_real_version_change(tmp_path):
    """Test that build revision _N is dropped when real version changes."""
    service = UpdateService(JsonStore(tmp_path / "updates.json", dict), runner=lambda *a, **k: None)
    
    # Real version change - should drop build revision
    before = {"pkg": "1.0_1"}
    after = {"pkg": "1.1_1"}
    changes = service._version_changes(before, after)
    assert len(changes) == 1
    assert changes[0]["old"] == "1.0"
    assert changes[0]["new"] == "1.1"
