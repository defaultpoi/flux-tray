"""A compact, notification-style window for unread feed items."""

from __future__ import annotations

import webbrowser

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk


class FeedPopup:
    """Displays unread feed items without menu navigation."""

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
        self._position()
        self.window.show_all()
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
        title = Gtk.Label()
        title.set_markup(f"<b>New items</b>  <span foreground='#888888'>{len(items)} unread</span>")
        title.set_xalign(0)
        header.pack_start(title, True, True, 0)
        close = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.BUTTON)
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.connect("clicked", lambda *_: self.hide())
        header.pack_end(close, False, False, 0)
        self.root.pack_start(header, False, False, 0)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.root.pack_start(separator, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(120)
        scroller.set_max_content_height(500)
        self.root.pack_start(scroller, True, True, 0)
        listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        scroller.add(listing)

        if not items:
            empty = Gtk.Label(label="You're all caught up.")
            empty.set_margin_top(24)
            empty.set_margin_bottom(24)
            listing.pack_start(empty, False, False, 0)

        for item in items[:100]:
            self._append_item(listing, item)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        mark_all = Gtk.Button(label="Mark all read")
        mark_all.connect("clicked", self._mark_all_read)
        footer.pack_start(mark_all, False, False, 0)
        done = Gtk.Button(label="Dismiss")
        done.connect("clicked", lambda *_: self.hide())
        footer.pack_end(done, False, False, 0)
        self.root.pack_start(footer, False, False, 0)

    def _append_item(self, listing, item):
        card = Gtk.Frame()
        card.set_shadow_type(Gtk.ShadowType.IN)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        body.set_border_width(9)
        card.add(body)

        source = next((feed.get("name", "Feed") for feed in self.feeds.state["feeds"]
                       if feed["id"] == item.get("feed_id")), "Feed")
        metadata = [source]
        if item.get("author"):
            metadata.append(item["author"])
        if item.get("published"):
            metadata.append(item["published"][:16].replace("T", " "))
        meta = Gtk.Label(label=" · ".join(metadata))
        meta.set_xalign(0)
        meta.set_line_wrap(True)
        meta.get_style_context().add_class("dim-label")
        body.pack_start(meta, False, False, 0)

        headline = Gtk.Label()
        headline.set_markup("<b>" + GLibMarkup.escape(item.get("title", "(untitled)")) + "</b>")
        headline.set_xalign(0)
        headline.set_line_wrap(True)
        headline.set_selectable(True)
        body.pack_start(headline, False, False, 0)

        summary = item.get("summary", "").strip()
        if summary:
            text = Gtk.Label(label=summary[:500])
            text.set_xalign(0)
            text.set_line_wrap(True)
            text.set_max_width_chars(62)
            body.pack_start(text, False, False, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        link = item.get("link", "")
        if link.startswith(("https://", "http://")):
            open_button = Gtk.Button(label="Open")
            open_button.connect("clicked", lambda *_args, url=link: webbrowser.open(url))
            actions.pack_start(open_button, False, False, 0)
        read_button = Gtk.Button(label="Mark read")
        read_button.connect("clicked", lambda *_args, item_id=item["id"]: self._mark_read(item_id))
        actions.pack_end(read_button, False, False, 0)
        body.pack_start(actions, False, False, 0)
        listing.pack_start(card, False, False, 0)

    def _mark_read(self, item_id):
        self.feeds.mark_read(item_id)
        self.rebuild()
        if not self.feeds.unread_items():
            self.hide()
        else:
            self.window.show_all()

    def _mark_all_read(self, *_args):
        for item in self.feeds.unread_items():
            self.feeds.mark_read(item["id"])
        self.rebuild()
        self.hide()


class GLibMarkup:
    @staticmethod
    def escape(value: str) -> str:
        from html import escape
        return escape(value, quote=False)
