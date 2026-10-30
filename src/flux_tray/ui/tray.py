"""GTK3/X11 tray shell for the feed reader."""

from __future__ import annotations

import logging
import webbrowser

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk


class TrayController:
    def __init__(self, application, feed_service, task_manager, timer_service=None, connectivity_service=None, update_service=None):
        self.application = application
        self.feeds = feed_service
        self.tasks = task_manager
        self.timer = timer_service
        self.connectivity = connectivity_service
        self.updates = update_service
        self.log = logging.getLogger("flux_tray.ui")
        self.icon = Gtk.StatusIcon.new_from_icon_name("view-list-symbolic")
        self.icon.set_visible(True)
        self.icon.set_tooltip_text("Flux Tray")
        self.icon.connect("activate", self._on_activate)
        self.icon.connect("popup-menu", self._on_popup)
        self.menu = Gtk.Menu()
        GLib.timeout_add_seconds(60, self._periodic_refresh)
        if self.timer is not None:
            self.timer.poll()
            GLib.timeout_add_seconds(1, self._timer_tick)
        if self.connectivity is not None:
            GLib.timeout_add_seconds(10, self._connectivity_tick)
            self._connectivity_tick()
        if self.updates is not None:
            GLib.timeout_add_seconds(43200, self._update_scan_tick)
            self._update_scan_tick()

    def _on_activate(self, _icon):
        self._rebuild_menu(self.menu)
        self.menu.popup_at_pointer(None)

    def _on_popup(self, _icon, button, activate_time):
        self._rebuild_menu(self.menu)
        self.menu.popup(None, None, Gtk.StatusIcon.position_menu, self.icon,
                        button, activate_time)

    def _append(self, label, callback=None, sensitive=True):
        item = Gtk.MenuItem.new_with_label(label)
        item.set_sensitive(sensitive)
        if callback:
            item.connect("activate", callback)
        self.menu.append(item)

    def _rebuild_menu(self, _menu):
        for child in self.menu.get_children():
            self.menu.remove(child)
            child.destroy()
        unread = self.feeds.unread_items()
        self._append(f"Flux Tray — {len(unread)} unread", sensitive=False)
        if self.connectivity is not None:
            network = self.connectivity.state.get("status", "checking")
            self._append(f"Network: {network}", sensitive=False)
        self.menu.append(Gtk.SeparatorMenuItem())
        if not self.feeds.state["feeds"]:
            self._append("No feeds configured", sensitive=False)
        for feed in self.feeds.state["feeds"]:
            self._append(f"{feed['name']} ({sum(1 for i in unread if i['feed_id'] == feed['id'])})",
                         lambda _item, fid=feed["id"]: self._mark_feed_read(fid))
        if unread:
            self.menu.append(Gtk.SeparatorMenuItem())
            for item in unread[:20]:
                title = item["title"].replace("\n", " ").strip()[:90]
                self._append(title, lambda _widget, current=item: self._open_item(current))
        saved = self.feeds.read_later_items()
        if saved:
            self.menu.append(Gtk.SeparatorMenuItem())
            self._append(f"Read later ({len(saved)})", sensitive=False)
            for item in saved[:10]:
                title = item["title"].replace("\\n", " ").strip()[:90]
                self._append(title, lambda _widget, current=item: self._open_item(current))
        self.menu.append(Gtk.SeparatorMenuItem())
        self._append("Add feed…", lambda _item: self._add_feed_dialog())
        if self.timer is not None:
            status = self.timer.state.get("status", "idle")
            if status == "running":
                self._append(f"Timer: {self.timer.remaining()}s remaining", sensitive=False)
            elif status == "missed":
                self._append("Timer missed while away", sensitive=False)
            elif status == "ringing":
                self._append("Timer finished", sensitive=False)
            self._append("Start timer…", lambda _item: self._timer_dialog())
            if status in {"running", "missed", "ringing"}:
                self._append("Cancel timer", lambda _item: self._cancel_timer())
        if self.updates is not None:
            changes = self.updates.state.get("changes", [])
            self._append(f"XBPS updates: {len(changes)}", sensitive=False)
            self._append("Check for updates", lambda _item: self._scan_updates())
            if changes:
                self._append("Apply system updates…", lambda _item: self._confirm_updates())
            self._append("List orphan packages…", lambda _item: self._list_orphans())
        self._append("Refresh feeds", lambda _item: self.refresh())
        self._append("Quit", lambda _item: self.application.quit())
        self.menu.show_all()
        self._update_icon()

    def _open_item(self, item):
        if item.get("link"):
            try:
                webbrowser.open(item["link"])
            except Exception:
                self.log.exception("Could not open feed link")
        self.feeds.mark_read(item["id"])
        self._rebuild_menu(self.menu)

    def _mark_feed_read(self, feed_id):
        self.feeds.mark_feed_read(feed_id)
        self._rebuild_menu(self.menu)

    def _update_icon(self):
        unread = self.feeds.unread_count()
        self.icon.set_from_icon_name("mail-unread-symbolic" if unread else "view-list-symbolic")
        network = self.connectivity.state.get("status") if self.connectivity is not None else None
        suffix = f" · {network}" if network else ""
        self.icon.set_tooltip_text(f"Flux Tray — {unread} unread{suffix}")

    def _add_feed_dialog(self):
        dialog = Gtk.Dialog(title="Add RSS/Atom feed", flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Add", Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        name = Gtk.Entry()
        name.set_placeholder_text("Feed name (optional)")
        url = Gtk.Entry()
        url.set_placeholder_text("https://example.com/feed.xml")
        box.pack_start(name, False, False, 0)
        box.pack_start(url, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            try:
                self.feeds.add_feed(url.get_text(), name.get_text().strip() or None)
                self.refresh()
            except (ValueError, OSError) as exc:
                error = Gtk.MessageDialog(flags=0, message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.CLOSE, text="Could not add feed")
                error.format_secondary_text(str(exc))
                error.run()
                error.destroy()
        dialog.destroy()

    def _update_scan_tick(self):
        if self.updates is None:
            return GLib.SOURCE_REMOVE
        self._scan_updates()
        return GLib.SOURCE_CONTINUE

    def _scan_updates(self):
        future = self.tasks.submit("xbps-scan", self.updates.scan_updates)
        if future is not None:
            future.add_done_callback(lambda done: GLib.idle_add(self._update_scan_complete, done))

    def _update_scan_complete(self, future):
        try:
            changes = future.result()
            self.log.info("XBPS scan found %d package changes", len(changes))
        except Exception:
            self.log.exception("XBPS update scan failed")
        if self.menu.get_mapped():
            self._rebuild_menu(self.menu)
        return GLib.SOURCE_REMOVE

    def _confirm_updates(self):
        dialog = Gtk.MessageDialog(flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.YES_NO,
            text="Apply all available system updates?")
        dialog.format_secondary_text("This runs the real XBPS system upgrade. It is not a dry run.")
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            future = self.tasks.submit("xbps-update", self.updates.apply_updates)
            if future is not None:
                future.add_done_callback(lambda done: GLib.idle_add(self._update_action_complete, done))

    def _list_orphans(self):
        future = self.tasks.submit("xbps-orphans", self.updates.list_orphans)
        if future is not None:
            future.add_done_callback(lambda done: GLib.idle_add(self._orphan_list_complete, done))

    def _orphan_list_complete(self, future):
        try:
            packages = future.result()
        except Exception as exc:
            self.log.exception("Could not list XBPS orphans")
            packages = []
            message = str(exc)
        else:
            message = "\n".join(packages) if packages else "No orphan packages found."
        dialog = Gtk.MessageDialog(flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.CLOSE,
            text="Orphan packages")
        dialog.format_secondary_text(message)
        if packages:
            dialog.add_button("Remove", 1)
            dialog.add_button("Remove + clean cache", 2)
        response = dialog.run()
        dialog.destroy()
        if response in (1, 2):
            action = self.updates.remove_orphans_and_clean_cache if response == 2 else self.updates.remove_orphans
            future = self.tasks.submit("xbps-remove-orphans", action)
            if future is not None:
                future.add_done_callback(lambda done: GLib.idle_add(self._update_action_complete, done))
        return GLib.SOURCE_REMOVE

    def _update_action_complete(self, future):
        try:
            result = future.result()
            if isinstance(result, tuple):
                results = result
            else:
                results = (result,)
            for item in results:
                if item.returncode != 0:
                    self.log.error("XBPS action failed: %s", item.stderr.strip())
                else:
                    self.log.info("XBPS action completed: %s", item.stdout.strip())
        except Exception:
            self.log.exception("XBPS action failed")
        self._scan_updates()
        if self.menu.get_mapped():
            self._rebuild_menu(self.menu)
        return GLib.SOURCE_REMOVE

    def _connectivity_tick(self):
        if self.connectivity is None:
            return GLib.SOURCE_REMOVE
        future = self.tasks.submit("connectivity-check", self._check_connectivity)
        if future is not None:
            future.add_done_callback(lambda done: GLib.idle_add(self._connectivity_complete, done))
        return GLib.SOURCE_CONTINUE

    def _check_connectivity(self):
        previous = self.connectivity.state.get("status")
        current = self.connectivity.check()
        return previous, current.status

    def _connectivity_complete(self, future):
        try:
            previous, current = future.result()
        except Exception:
            self.log.exception("Connectivity check failed")
            return GLib.SOURCE_REMOVE
        if previous in {"offline", "dns-error"} and current == "online":
            self.refresh()
        if self.menu.get_mapped():
            self._rebuild_menu(self.menu)
        self._update_icon()
        return GLib.SOURCE_REMOVE

    def _timer_dialog(self):
        dialog = Gtk.Dialog(title="Countdown timer", flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Start", Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        spin = Gtk.SpinButton.new_with_range(1, max(1, self.timer.maximum // 60),
                                            max(1, self.timer.step // 60))
        spin.set_value(5)
        box.pack_start(Gtk.Label(label="Duration (minutes)"), False, False, 0)
        box.pack_start(spin, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            try:
                self.timer.start(int(spin.get_value()) * 60)
            except ValueError as exc:
                self.log.warning("Invalid timer duration: %s", exc)
        dialog.destroy()
        self._rebuild_menu(self.menu)

    def _cancel_timer(self):
        self.timer.cancel()
        self._rebuild_menu(self.menu)

    def _timer_tick(self):
        if self.timer is None:
            return GLib.SOURCE_REMOVE
        result = self.timer.poll()
        if result == "ring":
            display = Gdk.Display.get_default()
            if display is not None:
                display.beep()
            self.icon.set_tooltip_text("Flux Tray — timer finished")
        if self.menu.get_mapped():
            self._rebuild_menu(self.menu)
        return GLib.SOURCE_CONTINUE

    def refresh(self):
        def work():
            return self.feeds.check_due()
        future = self.tasks.submit("feed-refresh", work)
        if future is not None:
            future.add_done_callback(lambda _future: GLib.idle_add(self._refresh_complete))

    def _refresh_complete(self):
        self._update_icon()
        if self.menu.get_mapped():
            self._rebuild_menu(self.menu)
        return GLib.SOURCE_REMOVE

    def _periodic_refresh(self):
        self.refresh()
        return GLib.SOURCE_CONTINUE
