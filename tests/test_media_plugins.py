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

def test_plugin_resolver_output_is_normalized(tmp_path):
    directory = tmp_path / "plugins"
    directory.mkdir()
    (directory / "resolver.py").write_text(
        "NAME = 'resolver'\n"
        "def list_episodes(source):\n"
        "    return [{'id': '1', 'title': 'Episode'}]\n"
        "def resolve(episode):\n"
        "    return {'url': 'https://example.test/video.mp4', 'ext': 'mp4'}\n",
        encoding="utf-8",
    )
    registry = MediaPluginRegistry(directory)
    registry.reload()
    episode = registry.list_episodes("plugin:resolver:source")[0]
    resolved = registry.resolve_episode("plugin:resolver:source", episode)
    assert resolved["url"] == "https://example.test/video.mp4"
    assert resolved["id"] == episode["id"]


def test_plugin_download_must_return_an_existing_file(tmp_path):
    directory = tmp_path / "plugins"
    directory.mkdir()
    (directory / "downloader.py").write_text(
        "NAME = 'downloader'\n"
        "def list_episodes(source):\n"
        "    return []\n"
        "def download(episode, base, progress, cancelled):\n"
        "    return str(base / 'missing.mkv')\n",
        encoding="utf-8",
    )
    registry = MediaPluginRegistry(directory)
    registry.reload()
    try:
        registry.download_episode("plugin:downloader:source", {}, tmp_path)
    except ValueError as exc:
        assert "existing file" in str(exc)
    else:
        raise AssertionError("Missing plugin download file was accepted")

def test_plugin_download_rejects_file_outside_output_directory(tmp_path):
    directory = tmp_path / "plugins"
    directory.mkdir()
    outside = tmp_path.parent / "outside-plugin-media.mkv"
    outside.write_bytes(b"video")
    (directory / "downloader.py").write_text(
        "NAME = 'downloader'\n"
        "def list_episodes(source):\n"
        "    return []\n"
        "def download(episode, base, progress, cancelled):\n"
        f"    return {str(outside)!r}\n",
        encoding="utf-8",
    )
    registry = MediaPluginRegistry(directory)
    registry.reload()
    try:
        registry.download_episode("plugin:downloader:source", {}, tmp_path)
    except ValueError as exc:
        assert "inside its output directory" in str(exc)
    else:
        raise AssertionError("Plugin download outside its output directory was accepted")


def test_plugin_download_rejects_empty_file(tmp_path):
    directory = tmp_path / "plugins"
    directory.mkdir()
    (directory / "downloader.py").write_text(
        "NAME = 'downloader'\n"
        "def list_episodes(source):\n"
        "    return []\n"
        "def download(episode, base, progress, cancelled):\n"
        "    path = base / 'empty.mkv'\n"
        "    path.write_bytes(b'')\n"
        "    return str(path)\n",
        encoding="utf-8",
    )
    registry = MediaPluginRegistry(directory)
    registry.reload()
    try:
        registry.download_episode("plugin:downloader:source", {}, tmp_path)
    except ValueError as exc:
        assert "non-empty regular file" in str(exc)
    else:
        raise AssertionError("Empty plugin download was accepted")

def test_plugin_download_accepts_path_relative_to_output_directory(tmp_path):
    directory = tmp_path / "plugins"
    directory.mkdir()
    (directory / "downloader.py").write_text(
        "NAME = 'downloader'\n"
        "def list_episodes(source):\n"
        "    return []\n"
        "def download(episode, base, progress, cancelled):\n"
        "    (base / 'episode.mkv').write_bytes(b'video')\n"
        "    return 'episode.mkv'\n",
        encoding="utf-8",
    )
    registry = MediaPluginRegistry(directory)
    registry.reload()
    result = registry.download_episode("plugin:downloader:source", {}, tmp_path)
    assert result == str(tmp_path / "episode.mkv")



import os
import sys


def test_plugin_reload_observes_same_size_edit_with_unchanged_timestamp(tmp_path):
    directory = tmp_path / "plugins"
    directory.mkdir()
    path = directory / "example.py"
    old_source = (
        "NAME = 'example'\n"
        "def list_episodes(source):\n"
        "    return [{'id': '1', 'title': 'Old'}]\n"
    )
    new_source = old_source.replace("Old", "New")
    path.write_text(old_source, encoding="utf-8")
    stamp = 1_700_000_000_000_000_000
    os.utime(path, ns=(stamp, stamp))

    registry = MediaPluginRegistry(directory)
    registry.reload()
    assert registry.list_episodes("plugin:example:feed")[0]["title"] == "Old"

    path.write_text(new_source, encoding="utf-8")
    os.utime(path, ns=(stamp, stamp))
    registry.reload()
    assert registry.list_episodes("plugin:example:feed")[0]["title"] == "New"


def test_plugin_reload_removes_deleted_plugin_module_from_sys_modules(tmp_path):
    directory = tmp_path / "plugins"
    directory.mkdir()
    path = directory / "example.py"
    path.write_text(
        "NAME = 'example'\n"
        "def list_episodes(source):\n"
        "    return []\n",
        encoding="utf-8",
    )
    registry = MediaPluginRegistry(directory)
    registry.reload()
    module_name = "flux_tray_user_plugin_example"
    assert module_name in sys.modules

    path.unlink()
    registry.reload()
    assert module_name not in sys.modules
