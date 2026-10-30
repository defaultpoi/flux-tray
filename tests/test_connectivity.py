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
