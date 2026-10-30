"""A compact popup listing unread feed-item titles."""

from __future__ import annotations

import webbrowser
from urllib.parse import urlsplit

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk, Pango


class FeedPopup:
    """Displays unread feed titles as a simple, one-line-per-item list."""

    def __init__(self, feeds, *, width: int = 440, max_height: int = 620):
        self.feeds = feeds
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("Flux Tray")
        self.window.set_default_size(width, max_height)
        self.window.set_size_request(320, 180)
        self.window.set_resizable(True)
        self.window.set_keep_above(True)
        self.window.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.connect("delete-event", self._on_delete)

        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.root.set_border_width(12)
        self.window.add(self.root)
        self._visible = False
        self.rebuild()

    @property
    def visible(self) -> bool:
        return self._visible

    def _on_delete(self, *_args):
        self.hide()
        return True

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
        self.window.move(
            geometry.x + geometry.width - width - 16,
            geometry.y + geometry.height - height - 16,
        )

    def rebuild(self):
        for child in self.root.get_children():
            self.root.remove(child)
            child.destroy()

        items = self.feeds.unread_items()
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        heading = Gtk.Label()
        heading.set_markup(
            f"<b>New items</b>  <span foreground='#888888'>{len(items)} unread</span>"
        )
        heading.set_xalign(0)
        header.pack_start(heading, True, True, 0)

        close = Gtk.Button.new_from_icon_name(
            "window-close-symbolic", Gtk.IconSize.BUTTON
        )
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.connect("clicked", lambda *_: self.hide())
        header.pack_end(close, False, False, 0)
        self.root.pack_start(header, False, False, 0)
        self.root.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0
        )

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(120)
        scroller.set_max_content_height(500)
        self.root.pack_start(scroller, True, True, 0)

        listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        listing.set_border_width(2)
        scroller.add(listing)

        if not items:
            empty = Gtk.Label(label="You're all caught up.")
            empty.set_margin_top(24)
            empty.set_margin_bottom(24)
            listing.pack_start(empty, False, False, 0)

        for item in items[:100]:
            self._append_item(listing, item)

        dismiss = Gtk.Button(label="Dismiss")
        dismiss.set_halign(Gtk.Align.END)
        dismiss.connect("clicked", lambda *_: self.hide())
        self.root.pack_end(dismiss, False, False, 0)

    def _append_item(self, listing, item):
        title = (item.get("title") or "(untitled)").strip()
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        clickable = Gtk.EventBox()
        clickable.set_visible_window(False)
        clickable.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        clickable.connect("button-press-event", self._on_item_click, item)
        clickable.set_tooltip_text(title)

        label = Gtk.Label(label=title)
        label.set_xalign(0)
        label.set_single_line_mode(True)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_tooltip_text(title)
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

    def _on_item_click(self, _widget, event, item):
        if event.button == Gdk.BUTTON_PRIMARY:
            link = item.get("link", "")
            parsed = urlsplit(link)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
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
        else:
            self.window.show_all()

    def _save_for_later(self, item_id):
        self.feeds.save_for_later(item_id)
        self.rebuild()
        if not self.feeds.unread_items():
            self.hide()
        else:
            self.window.show_all()
