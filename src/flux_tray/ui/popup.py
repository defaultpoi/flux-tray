"""Borderless feed popup grouped by feed title."""

from __future__ import annotations

import webbrowser
from html import escape
from urllib.parse import urlsplit

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from flux_tray.ui.layout import clamp_scroll_value
from flux_tray.ui.links import is_valid_web_url


class FeedPopup:
    """Displays unread feed items grouped under their configured feed names."""

    def __init__(self, feeds, *, width: int = 440, max_height: int = 620,
                 on_feed_rules=None):
        self.feeds = feeds
        self.on_feed_rules = on_feed_rules
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("Flux Tray")
        self.window.set_default_size(width, max_height)
        self.window.set_size_request(320, 180)
        self.window.set_resizable(False)
        self.window.set_decorated(False)
        self.window.set_keep_above(True)
        self.window.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.connect("delete-event", self._on_delete)

        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.root.set_border_width(12)
        self.window.add(self.root)
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_min_content_height(120)
        self.scroller.set_max_content_height(590)
        self.scroller.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.scroller.connect("button-press-event", self._on_blank_area_click)
        self.root.pack_start(self.scroller, True, True, 0)
        self.listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        self.listing.set_border_width(2)
        self.scroller.add(self.listing)
        self._scroll_restore_generation = 0
        self._visible = False
        self.rebuild()

    @property
    def visible(self) -> bool:
        return self._visible

    def _on_delete(self, *_args):
        self.hide()
        return True

    def _on_blank_area_click(self, _widget, event):
        if event.button == Gdk.BUTTON_SECONDARY:
            self.hide()
            return True
        return False

    def show(self):
        self.rebuild()
        if self._visible:
            return
        self.window.show_all()
        self._position()
        self._visible = True
        self.window.present()

    def hide(self):
        self.window.hide()
        self._visible = False

    def toggle(self):
        if self._visible:
            self.hide()
        else:
            self.show()

    def close(self):
        self.hide()
        self.window.destroy()

    def _position(self):
        display = Gdk.Display.get_default()
        if display is None:
            return
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        if monitor is None:
            return
        geometry = monitor.get_workarea()
        width, height = self.window.get_size()
        # The monitor workarea starts below panels that reserve screen space,
        # so this places the popup just under the XFCE panel/tray.
        self.window.move(
            geometry.x + geometry.width - width - 16,
            geometry.y + 16,
        )

    def rebuild(self):
        adjustment = self.scroller.get_vadjustment()
        previous_scroll = adjustment.get_value()
        self._scroll_restore_generation += 1
        generation = self._scroll_restore_generation

        for child in self.listing.get_children():
            self.listing.remove(child)
            child.destroy()

        feeds = self.feeds.state.get("feeds", [])
        items = self.feeds.unread_items()
        items_by_feed = {}
        for item in items:
            items_by_feed.setdefault(item.get("feed_id"), []).append(item)

        if not items:
            empty = Gtk.Label(label="You're all caught up.")
            empty.set_margin_top(24)
            empty.set_margin_bottom(24)
            self.listing.pack_start(empty, False, False, 0)

        for feed in feeds:
            feed_items = items_by_feed.get(feed["id"], [])
            if not feed_items:
                continue
            self._append_feed_title(self.listing, feed, len(feed_items))
            for item in feed_items:
                self._append_item(self.listing, item)

        saved_items = self.feeds.read_later_items()
        if saved_items:
            separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            separator.set_margin_top(6)
            separator.set_margin_bottom(4)
            self.listing.pack_start(separator, False, False, 0)
            saved_title = Gtk.Label(label=f"Read later ({len(saved_items)})")
            saved_title.set_xalign(0)
            saved_title.set_margin_top(3)
            self.listing.pack_start(saved_title, False, False, 0)
            for item in saved_items:
                self._append_read_later_item(self.listing, item)

        self.root.show_all()

        def restore_scroll():
            if generation != self._scroll_restore_generation:
                return GLib.SOURCE_REMOVE
            adjustment = self.scroller.get_vadjustment()
            adjustment.set_value(clamp_scroll_value(
                previous_scroll, adjustment.get_lower(),
                adjustment.get_upper(), adjustment.get_page_size(),
            ))
            return GLib.SOURCE_REMOVE

        GLib.idle_add(restore_scroll)

    def _append_feed_title(self, listing, feed, count):
        title = Gtk.Label()
        escaped = escape(str(feed.get("name") or feed.get("url") or "Feed"), quote=True)
        title.set_markup(
            f"<b>{escaped}</b> <span foreground='#888888'>{count}</span>"
        )
        title.set_xalign(0)
        title.set_margin_top(5)
        title.set_tooltip_text(feed.get("url", ""))
        title.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        title.connect("button-press-event", self._on_feed_title_click, feed)
        listing.pack_start(title, False, False, 0)

    def _append_item(self, listing, item):
        title = (item.get("title") or "(untitled)").strip()
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        clickable = Gtk.EventBox()
        clickable.set_visible_window(False)
        clickable.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        clickable.connect("button-press-event", self._on_item_click, item)
        details = [title]
        if item.get("author"):
            details.append(f"By {item['author']}")
        categories = item.get("categories") or []
        if categories:
            details.append("Categories: " + ", ".join(str(value) for value in categories))
        tooltip = "\n".join(details)
        clickable.set_tooltip_text(tooltip)

        label = Gtk.Label(label=title)
        label.set_xalign(0)
        label.set_single_line_mode(True)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_tooltip_text(tooltip)
        label.set_hexpand(True)
        clickable.add(label)
        row.pack_start(clickable, True, True, 0)

        bookmark = Gtk.Button.new_from_icon_name(
            "bookmark-new-symbolic", Gtk.IconSize.BUTTON
        )
        bookmark.set_relief(Gtk.ReliefStyle.NONE)
        bookmark.set_tooltip_text("Save for later")
        bookmark.connect(
            "clicked", lambda *_args, item_id=item["id"]: self._save_for_later(item_id)
        )
        row.pack_end(bookmark, False, False, 0)
        listing.pack_start(row, False, True, 0)

    def _append_read_later_item(self, listing, item):
        title = (item.get("title") or "(untitled)").strip()
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        clickable = Gtk.EventBox()
        clickable.set_visible_window(False)
        clickable.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        clickable.connect("button-press-event", self._on_read_later_click, item)
        details = [title]
        if item.get("author"):
            details.append(f"By {item['author']}")
        categories = item.get("categories") or []
        if categories:
            details.append("Categories: " + ", ".join(str(value) for value in categories))
        tooltip = "\n".join(details)
        clickable.set_tooltip_text(tooltip)

        label = Gtk.Label(label=title)
        label.set_xalign(0)
        label.set_single_line_mode(True)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_tooltip_text(tooltip)
        label.set_hexpand(True)
        clickable.add(label)
        row.pack_start(clickable, True, True, 0)

        remove = Gtk.Button.new_from_icon_name(
            "window-close-symbolic", Gtk.IconSize.BUTTON
        )
        remove.set_relief(Gtk.ReliefStyle.NONE)
        remove.set_tooltip_text("Remove from read later")
        remove.connect(
            "clicked", lambda *_args, item_id=item["id"]: self._remove_read_later(item_id)
        )
        row.pack_end(remove, False, False, 0)
        listing.pack_start(row, False, True, 0)

    def _on_read_later_click(self, _widget, event, item):
        if event.button == Gdk.BUTTON_PRIMARY:
            link = item.get("link", "")
            if self._valid_web_url(link):
                webbrowser.open(link)
            self._remove_read_later(item["id"])
            return True
        if event.button == Gdk.BUTTON_SECONDARY:
            self._remove_read_later(item["id"])
            return True
        return False

    def _remove_read_later(self, item_id):
        self.feeds.remove_read_later(item_id)
        self.rebuild()

    def _on_feed_title_click(self, _widget, event, feed):
        if event.button == Gdk.BUTTON_PRIMARY:
            self.feeds.mark_feed_read(feed["id"])
            self.rebuild()
            if not self.feeds.unread_items():
                self.hide()
            return True
        if event.button == Gdk.BUTTON_SECONDARY:
            self._show_feed_menu(feed, event)
            return True
        return False

    def _show_feed_menu(self, feed, event):
        menu = Gtk.Menu()
        feed_id = feed["id"]
        unread = [item for item in self.feeds.unread_items()
                  if item.get("feed_id") == feed_id]

        def add(label, callback, sensitive=True):
            item = Gtk.MenuItem.new_with_label(label)
            item.set_sensitive(sensitive)
            item.connect("activate", callback)
            menu.append(item)

        add("Mark all read", lambda *_: self._mark_feed_read(feed_id), bool(unread))
        add("Open all unread items", lambda *_: self._open_feed_items(unread),
            any(self._valid_web_url(item.get("link", "")) for item in unread))
        menu.append(Gtk.SeparatorMenuItem())
        website = feed.get("site_url") or ""
        add("Open feed website", lambda *_: webbrowser.open(website),
            self._valid_web_url(website))
        feed_url = feed.get("url", "")
        add("Open feed XML", lambda *_: webbrowser.open(feed_url),
            self._valid_web_url(feed_url))
        menu.append(Gtk.SeparatorMenuItem())
        muted = bool(feed.get("muted"))
        add("Unmute feed" if muted else "Mute feed",
            lambda *_: self._set_feed_muted(feed_id, not muted))
        add("Manage category/author rules…",
            lambda *_: self.on_feed_rules() if self.on_feed_rules else None,
            self.on_feed_rules is not None)
        menu.show_all()
        menu.popup_at_pointer(event)

    @staticmethod
    def _valid_web_url(url):
        return is_valid_web_url(url)

    def _open_feed_items(self, items):
        for item in items:
            link = item.get("link", "")
            if self._valid_web_url(link):
                webbrowser.open(link)
            self.feeds.mark_read(item["id"])
        self.rebuild()
        if not self.feeds.unread_items():
            self.hide()

    def _mark_feed_read(self, feed_id):
        self.feeds.mark_feed_read(feed_id)
        self.rebuild()
        if not self.feeds.unread_items():
            self.hide()

    def _set_feed_muted(self, feed_id, muted):
        self.feeds.set_muted(feed_id, muted)
        self.rebuild()

    def _on_item_click(self, _widget, event, item):
        if event.button == Gdk.BUTTON_PRIMARY:
            link = item.get("link", "")
            if self._valid_web_url(link):
                webbrowser.open(link)
            self._mark_read(item["id"])
            return True
        if event.button == Gdk.BUTTON_SECONDARY:
            self._mark_read(item["id"])
            return True
        return False

    def _mark_read(self, item_id):
        self.feeds.mark_read(item_id)
        self.rebuild()
        if not self.feeds.unread_items():
            self.hide()

    def _save_for_later(self, item_id):
        self.feeds.save_for_later(item_id)
        self.rebuild()
        if not self.feeds.unread_items():
            self.hide()

