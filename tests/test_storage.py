import json

from flux_tray.core.storage import JsonStore


def test_missing_store_returns_fresh_default(tmp_path):
    store = JsonStore(tmp_path / "state.json", dict)
    assert store.load() == {}


def test_save_load_round_trip_and_atomic_destination(tmp_path):
    path = tmp_path / "nested" / "state.json"
    store = JsonStore(path, dict)
    store.save({"title": "știre", "count": 3})
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "title": "știre", "count": 3
    }
    assert list(path.parent.glob("*.tmp")) == []


def test_corrupt_json_is_preserved_and_defaults_returned(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")
    store = JsonStore(path, list)
    assert store.load() == []
    assert (tmp_path / "state.json.corrupt").read_text(encoding="utf-8") == "{broken"
