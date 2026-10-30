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
        self.tray = TrayController(self, feeds, self.tasks)
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
