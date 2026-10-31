from pathlib import Path


def test_install_and_uninstall_scripts_are_executable():
    root = Path(__file__).resolve().parents[1]
    for name in ("install.sh", "uninstall.sh"):
        assert (root / name).stat().st_mode & 0o111, f"{name} must be executable"
