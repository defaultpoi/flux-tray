"""GTK application composition root."""

from __future__ import annotations

import logging
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from flux_tray.core.config import Config, Paths
from flux_tray.core.logging import configure_logging
from flux_tray.core.storage import JsonStore
from flux_tray.core.tasks import TaskManager
from flux_tray.core.process import ProcessSupervisor
from flux_tray.feeds.service import FeedService
from flux_tray.ui.tray import TrayController
from flux_tray.timers.service import CountdownTimer
from flux_tray.connectivity.service import ConnectivityService
from flux_tray.updates.service import UpdateService
from flux_tray.weather.service import WeatherService
from flux_tray.weather.alerts import MeteoAlarmClient
from flux_tray.live.service import LiveService, StreamlinkProbe
from flux_tray.live.twitch import TwitchProbe
from flux_tray.media.player import MpvController
from flux_tray.media.service import MediaService
from flux_tray.media.sources import YtDlpAdapter
from flux_tray.media.downloader import MediaDownloader
from flux_tray.media.display import XrandrDisplay
from flux_tray.launcher.service import LauncherService


class FluxTrayApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.github.defaultpoi.FluxTray")
        self.paths = Paths.user_default()
        self.tasks = None
        self.tray = None
        self.player = None
        self.process = None

    def do_activate(self) -> None:
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        logger = configure_logging(self.paths.state_dir)
        config = Config(self.paths.config_dir / "config.conf")
        config.ensure_exists()
        config.load()
        self.tasks = TaskManager(workers=2)
        self.process = ProcessSupervisor()
        store = JsonStore(self.paths.data_dir / "feeds.json",
                          lambda: {"feeds": [], "items": {}, "read_later": []})
        feeds = FeedService(store, default_interval=config.get_int("feeds", "interval", 60, minimum=60))
        timer_store = JsonStore(self.paths.data_dir / "timer.json", dict)
        timer = CountdownTimer(
            timer_store,
            maximum=config.get_int("timer", "max", 120, minimum=1) * 60,
            step=config.get_int("timer", "step", 60, minimum=1),
        )
        connectivity_store = JsonStore(self.paths.data_dir / "connectivity.json", dict)
        connectivity = ConnectivityService(connectivity_store)
        update_store = JsonStore(self.paths.data_dir / "updates.json", dict)
        updates = UpdateService(update_store, process=self.process)
        weather = None
        latitude = config.get("weather", "lat", "") or ""
        longitude = config.get("weather", "lon", "") or ""
        if latitude.strip() and longitude.strip():
            try:
                weather_store = JsonStore(self.paths.data_dir / "weather.json", dict)
                alerts_client = None
                if config.get_bool("weather", "alerts", False):
                    region = config.get("weather", "region", "") or ""
                    if region.strip():
                        alerts_client = MeteoAlarmClient(
                            country=config.get("weather", "country", "romania") or "romania",
                            region=region,
                        )
                    else:
                        logger.warning("MeteoAlarm alerts are enabled but weather.region is empty")
                weather = WeatherService(
                    weather_store, float(latitude), float(longitude),
                    interval=config.get_int("weather", "interval", 30, minimum=5) * 60,
                    alerts_client=alerts_client,
                )
            except ValueError as exc:
                logger.warning("Weather is disabled: %s", exc)
        live_store = JsonStore(self.paths.data_dir / "live.json", lambda: {"channels": []})
        self.player = MpvController(self.paths.state_dir / "mpv.sock")
        live = LiveService(
            live_store,
            probe=StreamlinkProbe(process=self.process),
            twitch_probe=TwitchProbe(),
            interval=config.get_int("live", "interval", 15, minimum=1) * 60,
            player=self.player,
            quality=config.get("live", "quality", "best") or "best",
        )
        media_store = JsonStore(self.paths.data_dir / "media.json",
                                lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
        media = MediaService(
            media_store, self.paths.plugin_dir,
            ahead=config.get_int("media", "ahead", 2, minimum=0),
            interval=config.get_int("media", "interval", 60, minimum=10) * 60,
            output_dir=Path(config.get("media", "path", "~/Videos") or "~/Videos"),
            player=self.player,
            yt_dlp=YtDlpAdapter(process=self.process),
            downloader=MediaDownloader(process=self.process),
            display=XrandrDisplay(process=self.process),
            screen_height=config.get_int("media", "screen_height", 0, minimum=0) or None,
            yt_dlp_sort=config.get("media", "yt_dlp_sort", "") or None,
        )
        launcher = LauncherService(config, self.process)
        self.tray = TrayController(
            self, feeds, self.tasks, timer, connectivity, updates, weather, live, media, launcher,
            connectivity_interval=config.get_int("connectivity", "interval", 10, minimum=1),
            update_interval=config.get_int("updates", "interval", 12, minimum=1) * 3600,
        )
        self.hold()
        self.connect("shutdown", self._shutdown)
        logger.info("Flux Tray started")
        self.tray.refresh()

    def _shutdown(self, *_args):
        if self.tasks is not None:
            self.tasks.shutdown(wait=False)
            self.tasks = None
        if self.process is not None:
            self.process.terminate_all()
            self.process = None
        if self.player is not None:
            self.player.close()
            self.player = None
        logging.getLogger("flux_tray").info("Flux Tray stopped")
        self.release()
