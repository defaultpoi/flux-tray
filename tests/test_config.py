from flux_tray.core.config import Config, Paths


def test_typed_values_and_fallbacks(tmp_path):
    path = tmp_path / "config.conf"
    path.write_text("[updates]\ninterval = 4\norphans = false\n", encoding="utf-8")
    config = Config(path)
    config.load()
    assert config.get_int("updates", "interval", 12, minimum=5) == 5
    assert config.get_bool("updates", "orphans", True) is False
    assert config.get_int("missing", "value", 9) == 9


def test_fresh_config_created_without_importing_other_state(tmp_path):
    path = tmp_path / "flux-tray" / "config.conf"
    config = Config(path)
    config.ensure_exists()
    assert path.exists()
    assert "[feeds]" in path.read_text(encoding="utf-8")


def test_default_paths_are_flux_tray_specific():
    paths = Paths.user_default()
    assert paths.config_dir.name == "flux-tray"
    assert paths.data_dir.name == "flux-tray"
    assert paths.plugin_dir.name == "media-plugins"
