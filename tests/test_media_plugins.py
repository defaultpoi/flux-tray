from flux_tray.media.plugins import MediaPluginRegistry


def test_named_plugin_source_uses_prefix_payload_and_normalizes(tmp_path):
    directory = tmp_path / "plugins"
    directory.mkdir()
    (directory / "example.py").write_text(
        "NAME = 'example'\n"
        "ORDER = 1\n"
        "def list_episodes(source):\n"
        "    return [{'id': source, 'title': 'Show S02E04'}]\n"
        "def matches(source):\n"
        "    return source.endswith('.example')\n"
    , encoding="utf-8")
    registry = MediaPluginRegistry(directory)
    registry.reload()
    episodes = registry.list_episodes("plugin:example:feed-id")
    assert episodes[0]["id"] == "plugin:example:feed-id"
    assert episodes[0]["season"] == 2
    assert episodes[0]["episode"] == 4


def test_plugin_matcher_precedes_builtin_fallback(tmp_path):
    directory = tmp_path / "plugins"
    directory.mkdir()
    (directory / "matched.py").write_text(
        "NAME = 'matched'\n"
        "def list_episodes(source):\n"
        "    return [{'id': '1', 'title': source}]\n"
        "def matches(source):\n"
        "    return source.startswith('custom:')\n"
    , encoding="utf-8")
    registry = MediaPluginRegistry(directory)
    registry.reload()
    assert registry.list_episodes("custom:feed")[0]["title"] == "custom:feed"
def test_plugins_receive_bounded_helper_api(tmp_path):
    directory = tmp_path / "plugins"
    directory.mkdir()
    (directory / "helpers.py").write_text(
        "def list_episodes(source):\n"
        "    return []\n"
    , encoding="utf-8")
    registry = MediaPluginRegistry(directory)
    registry.reload()
    plugin = registry.plugins[0]
    assert callable(plugin.flux_tray_helpers.fetch_json)
    assert callable(plugin.flux_tray_helpers.download_file)
    assert callable(plugin.flux_tray_helpers.parse_season_episode)