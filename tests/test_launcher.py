from flux_tray.core.config import Config
from flux_tray.core.process import ProcessSupervisor
from flux_tray.launcher.service import LauncherService


def test_launcher_accepts_only_json_argv_commands(tmp_path):
    path = tmp_path / "config.conf"
    path.write_text('[launcher]\nTerminal = ["xfce4-terminal", "--disable-server"]\n'
                    'Invalid = echo ok\n', encoding="utf-8")
    config = Config(path)
    config.load()
    service = LauncherService(config, ProcessSupervisor())
    commands = {command.name: command for command in service.commands()}
    assert commands["terminal"].argv == ("xfce4-terminal", "--disable-server")
    assert "invalid" not in commands
