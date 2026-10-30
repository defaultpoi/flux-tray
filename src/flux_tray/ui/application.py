"""GTK application composition root."""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from flux_tray.core.config import Config, Paths
from flux_tray.core.logging import configure_logging
from flux_tray.core.storage import JsonStore
from flux_tray.core.tasks import TaskManager
from flux_tray.feeds.service import FeedService
from flux_tray.ui.tray import TrayController
from flux_tray.timers.service import CountdownTimer
from flux_tray.connectivity.service import ConnectivityService
from flux_tray.updates.service import UpdateService
from flux_tray.weather.service import WeatherService


class FluxTrayApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.github.defaultpoi.FluxTray")
        self.paths = Paths.user_default()
        self.tasks = None
        self.tray = None

    def do_activate(self) -> None:
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        logger = configure_logging(self.paths.state_dir)
        config = Config(self.paths.config_dir / "config.conf")
        config.ensure_exists()
        config.load()
        self.tasks = TaskManager(workers=2)
        store = JsonStore(self.paths.data_dir / "feeds.json",
                          lambda: {"feeds": [], "items": {}, "read_later": []})
        feeds = FeedService(store)
        timer_store = JsonStore(self.paths.data_dir / "timer.json", dict)
        timer = CountdownTimer(
            timer_store,
            maximum=config.get_int("timer", "max", 120, minimum=1) * 60,
            step=config.get_int("timer", "step", 60, minimum=1),
        )
        connectivity_store = JsonStore(self.paths.data_dir / "connectivity.json", dict)
        connectivity = ConnectivityService(connectivity_store)
        update_store = JsonStore(self.paths.data_dir / "updates.json", dict)
        updates = UpdateService(update_store)
        weather = None
        latitude = config.get("weather", "lat", "") or ""
        longitude = config.get("weather", "lon", "") or ""
        if latitude.strip() and longitude.strip():
            try:
                weather_store = JsonStore(self.paths.data_dir / "weather.json", dict)
                weather = WeatherService(
                    weather_store, float(latitude), float(longitude),
                    interval=config.get_int("weather", "interval", 30, minimum=5) * 60,
                )
            except ValueError as exc:
                logger.warning("Weather is disabled: %s", exc)
        self.tray = TrayController(self, feeds, self.tasks, timer, connectivity, updates, weather)
        self.hold()
        self.connect("shutdown", self._shutdown)
        logger.info("Flux Tray started")
        self.tray.refresh()

    def _shutdown(self, *_args):
        if self.tasks is not None:
            self.tasks.shutdown(wait=False)
            self.tasks = None
        logging.getLogger("flux_tray").info("Flux Tray stopped")
        self.release()
