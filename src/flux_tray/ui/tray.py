"""GTK3/X11 tray shell for the feed reader."""

from __future__ import annotations

import logging
import webbrowser

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk


class TrayController:
    def __init__(self, application, feed_service, task_manager):
        self.application = application
        self.feeds = feed_service
        self.tasks = task_manager
        self.log = logging.getLogger("flux_tray.ui")
        self.icon = Gtk.StatusIcon.new_from_icon_name("view-list-symbolic")
        self.icon.set_visible(True)
        self.icon.set_tooltip_text("Flux Tray")
        self.icon.connect("activate", self._on_activate)
        self.icon.connect("popup-menu", self._on_popup)
        self.menu = Gtk.Menu()
        GLib.timeout_add_seconds(60, self._periodic_refresh)

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
        self.menu.append(Gtk.SeparatorMenuItem())
        self._append("Add feed…", lambda _item: self._add_feed_dialog())
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
        self.icon.set_tooltip_text(f"Flux Tray — {unread} unread")

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
