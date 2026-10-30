"""Temporary GTK shell; tray/popup implementation is an M0 task."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


class FluxTrayApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.github.defaultpoi.FluxTray")

    def do_activate(self) -> None:
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("Flux Tray")
        window.set_default_size(360, 120)
        label = Gtk.Label(label="Flux Tray foundation")
        label.set_margin_top(24)
        label.set_margin_bottom(24)
        label.set_margin_start(24)
        label.set_margin_end(24)
        window.add(label)
        window.show_all()
