"""Borderless feed popup grouped by feed title with weather, live, media, and updates."""

from __future__ import annotations

import webbrowser
from html import escape

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from flux_tray.ui.layout import clamp_scroll_value
from flux_tray.ui.links import is_valid_web_url


class FeedPopup:
    """Displays unread feed items grouped under their configured feed names,
    plus weather, live channels, media queue, and updates."""

    def __init__(
        self,
        feeds,
        *,
        width: int = 440,
        max_height: int = 620,
        on_feed_rules=None,
        weather_service=None,
        live_service=None,
        media_service=None,
        updates_service=None,
    ):
        self.feeds = feeds
        self.on_feed_rules = on_feed_rules
        self.weather_service = weather_service
        self.live_service = live_service
        self.media_service = media_service
        self.updates_service = updates_service
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
        self.window.connect("focus-out-event", self._on_focus_out)

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
        self._menu_open = False
        self._min_width = width
        self._weather_bar_width = width

        self.rebuild()

    def _get_weather_state(self):
        """Get current weather state from weather service."""
        if self.weather_service is not None:
            return self.weather_service.state
        return {}

    @property
    def visible(self) -> bool:
        return self._visible

    def _on_delete(self, *_args):
        self.hide()
        return True

    def _on_focus_out(self, _widget, event):
        # Close on focus-out unless a menu popover is open
        if not self._menu_open:
            self.hide()
        return False

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
        # Invalidate a queued scroll-restore idle callback before destroying
        # the widgets it would otherwise access.
        self._scroll_restore_generation += 1
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

    def _fit_popup_width(self):
        """Fit popup width to max(min_width, weather_bar_width) like void-tray."""
        # Get the natural width of the listing
        self.listing.get_preferred_width()
        nat_width = self.listing.get_preferred_width()[1]
        # Add scroller padding and root border
        req_width = max(self._min_width, nat_width + 40)
        # Also consider weather bar width
        req_width = max(req_width, self._weather_bar_width)
        # Limit to reasonable max
        req_width = min(req_width, 800)
        # Update window size if changed
        current_width = self.window.get_allocated_width()
        if req_width != current_width:
            self.window.resize(req_width, self.window.get_allocated_height())
            # Reposition to keep right edge against screen
            self._position()

    def set_weather_bar_width(self, width: int):
        """Update weather bar width and refit popup."""
        self._weather_bar_width = width
        if self._visible:
            self._fit_popup_width()

    def _make_section_header(self, label_text, child_widgets):
        """Create a section header (no toggle, always show children)."""
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.set_margin_top(4)
        header_box.set_margin_bottom(4)

        title_label = Gtk.Label(label=label_text)
        title_label.set_xalign(0)
        title_label.set_hexpand(True)
        header_box.pack_start(title_label, True, True, 0)

        # Pack header
        self.listing.pack_start(header_box, False, False, 0)

        # Pack all children (always visible)
        for child in child_widgets:
            self.listing.pack_start(child, False, False, 0)



    def _append_weather(self):
        """Append weather section to the listing."""
        state = self._get_weather_state()
        temperature = state.get("temperature")
        condition = state.get("condition", "Weather unavailable")

        if temperature is not None:
            weather_text = f"Weather: {temperature}°C · {condition} · wind {state.get('wind_speed', '?')} km/h"
        else:
            weather_text = condition

        child_widgets = []
        forecast = state.get("forecast", [])
        for day in forecast:
            day_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            day_box.set_margin_start(12)
            day_box.set_margin_bottom(2)
            day_label = Gtk.Label(
                label=f"{day.get('date')}: {day.get('condition')} · H {day.get('high')}° L {day.get('low')}° · rain {day.get('rain_probability')}%"
            )
            day_label.set_xalign(0)
            day_label.set_hexpand(True)
            day_box.pack_start(day_label, True, True, 0)
            child_widgets.append(day_box)

        alerts = state.get("alerts", [])
        for alert in alerts:
            alert_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            alert_box.set_margin_start(12)
            alert_box.set_margin_bottom(2)
            alert_label = Gtk.Label(
                label=f"⚠ {alert.get('severity', 'warning').title()}: {alert.get('title', 'Weather warning')} · {alert.get('area', '')}"
            )
            alert_label.set_xalign(0)
            alert_label.set_hexpand(True)
            alert_box.pack_start(alert_label, True, True, 0)
            child_widgets.append(alert_box)

        self._make_section_header(weather_text, child_widgets)

    def _append_live(self):
        """Append live channels section to the listing (only live channels)."""
        if self.live_service is None:
            return

        channels = self.live_service.state.get("channels", [])
        live_channels = [ch for ch in channels if ch.get("status") == "live"]
        live_text = f"Live now ({len(live_channels)})"

        child_widgets = []
        weekdays = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        for channel in live_channels:
            channel_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            channel_box.set_margin_start(12)
            channel_box.set_margin_bottom(4)

            metadata = channel.get("metadata", {})
            title = metadata.get("title") or channel["status"]
            category = metadata.get("category")
            viewers = metadata.get("viewers")
            started = metadata.get("created_at")
            elapsed = ""
            if started:
                try:
                    from datetime import datetime, timezone
                    began = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    seconds = max(0, int((datetime.now(timezone.utc) - began).total_seconds()))
                    hours, remainder = divmod(seconds, 3600)
                    minutes = remainder // 60
                    elapsed = f"{hours}h {minutes}m" if hours else f"{minutes}m"
                except (TypeError, ValueError):
                    pass

            details = []
            if category:
                details.append(category)
            if isinstance(viewers, int):
                details.append(f"{viewers:,} viewers")
            if elapsed:
                details.append(elapsed)

            label_text = f"{channel['name']} — {title}"
            if details:
                label_text += " · " + " · ".join(details)

            schedule = channel.get("schedule", [])
            if schedule:
                schedule_text = ", ".join(f"{weekdays[entry['weekday']]} {entry['time']}" for entry in schedule)
                label_text += f" · {schedule_text}"

            channel_label = Gtk.Label(label=label_text[:120])
            channel_label.set_xalign(0)
            channel_label.set_hexpand(True)
            channel_label.set_selectable(True)
            
            # Wrap in EventBox for click handling
            clickable = Gtk.EventBox()
            clickable.set_visible_window(False)
            clickable.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            clickable.connect("button-press-event", lambda _w, _e, ch=channel: self._play_live_channel(ch))
            clickable.add(channel_label)
            channel_box.pack_start(clickable, False, False, 0)

            child_widgets.append(channel_box)

        # Add "Check live channels" button
        check_button = Gtk.Button.new_with_label("Check live channels")
        check_button.connect("clicked", lambda _w: self._check_live_channels())
        check_button.set_halign(Gtk.Align.START)
        child_widgets.append(check_button)

        self._make_section_header(live_text, child_widgets)

    def _play_live_channel(self, channel):
        if self.live_service:
            self.live_service.play_channel(channel["id"])

    def _check_live_channels(self):
        if self.live_service:
            self.live_service.check_due(force=True)

    def _append_media(self):
        """Append media section to the listing."""
        if self.media_service is None:
            return

        sources = self.media_service.state.get("sources", [])
        queue = self.media_service.state.get("queue", [])
        media_text = f"Media: {len(sources)} sources · {len(queue)} queued"

        child_widgets = []
        download_state = self.media_service.state.get("download") or {}
        download_status = download_state.get("status")
        if download_status == "downloading":
            percent = download_state.get("percent")
            progress = f"{percent:.0f}%" if isinstance(percent, (int, float)) else "working"
            dl_label = Gtk.Label(label=f"Downloading: {download_state.get('title', 'Episode')} ({progress})")
            dl_label.set_xalign(0)
            dl_label.set_hexpand(True)
            child_widgets.append(dl_label)
        elif download_status == "failed":
            dl_label = Gtk.Label(label=f"Failed: {download_state.get('title', 'Episode')}")
            dl_label.set_xalign(0)
            dl_label.set_hexpand(True)
            child_widgets.append(dl_label)

        for source in sources:
            src_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            src_box.set_margin_start(12)
            src_box.set_margin_bottom(2)
            title = source.get("title") or source.get("url", "").split("/")[-1]
            sort = source.get("sort", "newest")
            src_label = Gtk.Label(label=f"{title} [{sort}]")
            src_label.set_xalign(0)
            src_label.set_hexpand(True)
            src_box.pack_start(src_label, True, True, 0)
            child_widgets.append(src_box)

        self._make_section_header(media_text, child_widgets)

    def _append_updates(self):
        """Append updates section to the listing."""
        if self.updates_service is None:
            return

        changes = self.updates_service.state.get("changes", [])
        updates_text = f"Updates: {len(changes)} packages"

        child_widgets = []
        if changes:
            for change in changes:
                ch_label = Gtk.Label(
                    label=f"{change.get('pkgver', 'Unknown')} ({change.get('repository', '')})"
                )
                ch_label.set_xalign(0)
                ch_label.set_hexpand(True)
                child_widgets.append(ch_label)
        else:
            no_changes = Gtk.Label(label="System is up to date")
            no_changes.set_xalign(0)
            no_changes.set_hexpand(True)
            child_widgets.append(no_changes)

        last_action = self.updates_service.state.get("last_action")
        if last_action:
            outcome = "success" if last_action.get("success") else "FAILED"
            action_text = f"Last: {last_action.get('action', 'Action')} — {outcome}"
            action_label = Gtk.Label(label=action_text)
            action_label.set_xalign(0)
            action_label.set_hexpand(True)
            child_widgets.append(action_label)

        check_button = Gtk.Button.new_with_label("Check for updates")
        check_button.connect("clicked", lambda _w: self._check_updates())
        check_button.set_halign(Gtk.Align.START)
        child_widgets.append(check_button)

        self._make_section_header(updates_text, child_widgets)

    def _check_updates(self):
        if self.updates_service:
            self.updates_service.scan_updates()

    def rebuild(self):
        adjustment = self.scroller.get_vadjustment()
        previous_scroll = adjustment.get_value()
        self._scroll_restore_generation += 1
        generation = self._scroll_restore_generation

        for child in self.listing.get_children():
            self.listing.remove(child)
            child.destroy()

        # 1. Weather section
        self._append_weather()

        # 2. Live channels section
        self._append_live()

        # 3. Media section
        self._append_media()

        # 4. Unread articles section
        feeds = self.feeds.state.get("feeds", [])
        items = self.feeds.unread_items()
        items_by_feed = {}
        for item in items:
            items_by_feed.setdefault(item.get("feed_id"), []).append(item)

        has_unread = bool(items)

        if not has_unread and not self._live_expanded and not self._media_expanded and not self._updates_expanded:
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

        # 5. Updates section (at the bottom)
        self._append_updates()

        self.root.show_all()
        # Fit width after showing
        self._fit_popup_width()

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
        self._menu_open = True
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
        add("Open all unread as tabs", lambda *_: self._open_feed_items(unread),
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
        menu.connect("selection-done", self._on_menu_closed)
        menu.popup_at_pointer(event)

    def _on_menu_closed(self, _menu):
        self._menu_open = False

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
