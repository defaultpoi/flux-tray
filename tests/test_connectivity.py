from flux_tray.connectivity.service import ConnectivityService
from flux_tray.core.storage import JsonStore


class Connection:
    def close(self):
        pass


def make_service(tmp_path, dns=True, network=True):
    def resolver(*args, **kwargs):
        if not dns:
            raise OSError("name resolution failed")
        return []

    def connector(*args, **kwargs):
        if not network:
            raise OSError("network unreachable")
        return Connection()

    store = JsonStore(tmp_path / "connectivity.json", dict)
    return ConnectivityService(store, resolver=resolver, connector=connector)


def test_online_state(tmp_path):
    result = make_service(tmp_path).check()
    assert result.status == "online"
    assert result.dns_ok and result.network_ok


def test_dns_failure_is_distinguished_from_network_failure(tmp_path):
    result = make_service(tmp_path, dns=False, network=True).check()
    assert result.status == "dns-error"
    assert not result.dns_ok and result.network_ok


def test_network_failure(tmp_path):
    result = make_service(tmp_path, dns=False, network=False).check()
    assert result.status == "offline"
    assert not result.network_ok


def test_manual_reset_runs_only_configured_argv(tmp_path):
    from flux_tray.core.process import ProcessResult
    class Process:
        def __init__(self):
            self.calls = []
        def run(self, argv, **kwargs):
            self.calls.append((argv, kwargs))
            return ProcessResult(tuple(argv), 0, "reset done", "")
    process = Process()
    service = ConnectivityService(JsonStore(tmp_path / "connectivity.json", dict),
                                  process=process,
                                  reset_command=["sudo", "-n", "wg-quick", "down", "wg0"])
    assert service.reset_available
    assert service.reset().stdout == "reset done"
    assert process.calls[0][0] == ["sudo", "-n", "wg-quick", "down", "wg0"]


def test_reset_is_unavailable_without_explicit_configuration(tmp_path):
    service = ConnectivityService(JsonStore(tmp_path / "connectivity.json", dict))
    assert not service.reset_available
    try:
        service.reset()
    except RuntimeError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("unconfigured reset unexpectedly ran")
