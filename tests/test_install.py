from pathlib import Path


def test_install_and_uninstall_scripts_are_executable():
    root = Path(__file__).resolve().parents[1]
    for name in ("install.sh", "uninstall.sh"):
        assert (root / name).stat().st_mode & 0o111, f"{name} must be executable"

def test_user_local_install_autostart_and_uninstall_preserve_user_data(tmp_path):
    import os
    import subprocess

    root = Path(__file__).resolve().parents[1]
    home = tmp_path / "user home"
    bin_dir = tmp_path / "user bin"
    data_dir = tmp_path / "user data"
    config_dir = tmp_path / "user config"
    mock_modules = tmp_path / "mock modules"
    (mock_modules / "gi").mkdir(parents=True)
    (mock_modules / "gi" / "__init__.py").write_text(
        "def require_version(*args): pass\\n", encoding="utf-8"
    )
    (mock_modules / "gi" / "repository.py").write_text(
        "Gtk = object()\\n", encoding="utf-8"
    )
    (mock_modules / "feedparser.py").write_text("", encoding="utf-8")

    env = os.environ.copy()
    env.update({
        "HOME": str(home),
        "XDG_BIN_HOME": str(bin_dir),
        "XDG_DATA_HOME": str(data_dir),
        "XDG_CONFIG_HOME": str(config_dir),
        "PYTHONPATH": str(mock_modules),
    })

    subprocess.run([str(root / "install.sh"), "--autostart"], env=env,
                   check=True, capture_output=True, text=True)

    app_dir = home / ".local" / "lib" / "flux-tray"
    launcher = bin_dir / "flux-tray"
    desktop = data_dir / "applications" / "flux-tray.desktop"
    autostart = config_dir / "autostart" / "flux-tray.desktop"
    assert (app_dir / "flux_tray" / "__main__.py").is_file()
    assert launcher.is_file() and os.access(launcher, os.X_OK)
    assert f'Exec="{launcher}"' in desktop.read_text(encoding="utf-8")
    assert autostart.read_text(encoding="utf-8") == desktop.read_text(encoding="utf-8")

    subprocess.run([str(root / "install.sh"), "--no-autostart"], env=env,
                   check=True, capture_output=True, text=True)
    assert not autostart.exists()

    config_file = config_dir / "flux-tray" / "config.conf"
    data_file = data_dir / "flux-tray" / "feeds.json"
    config_file.parent.mkdir(parents=True)
    data_file.parent.mkdir(parents=True)
    config_file.write_text("[feeds]\\n", encoding="utf-8")
    data_file.write_text("{}\\n", encoding="utf-8")

    subprocess.run([str(root / "uninstall.sh")], env=env,
                   check=True, capture_output=True, text=True)

    assert not app_dir.exists()
    assert not launcher.exists()
    assert not desktop.exists()
    assert not autostart.exists()
    assert config_file.read_text(encoding="utf-8") == "[feeds]\\n"
    assert data_file.read_text(encoding="utf-8") == "{}\\n"

