"""GTK3/X11 tray shell for the feed reader."""

from __future__ import annotations

import json
import logging
import re
import webbrowser
from datetime import datetime, timezone

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

from flux_tray.ui.popup import FeedPopup


class TrayController:
    def __init__(self, application, feed_service, task_manager, timer_service=None, connectivity_service=None, update_service=None, weather_service=None, live_service=None, media_service=None, launcher_service=None,
                 connectivity_interval: int = 10, update_interval: int = 43200, config=None):
        self.application = application
        self.config = config
        self.feeds = feed_service
        self.tasks = task_manager
        self.timer = timer_service
        self.connectivity = connectivity_service
        self.updates = update_service
        self.weather = weather_service
        self.live = live_service
        self.media = media_service
        self.launcher = launcher_service
        self.connectivity_interval = max(1, int(connectivity_interval))
        self.update_interval = max(60, int(update_interval))
        self.log = logging.getLogger("flux_tray.ui")
        self.icon = Gtk.StatusIcon.new_from_icon_name("view-list-symbolic")
        self.icon.set_visible(True)
        self.icon.set_tooltip_text("Flux Tray")
        self.icon.connect("activate", self._on_activate)
        self.icon.connect("popup-menu", self._on_popup)
        self.menu = Gtk.Menu()  # Legacy action helpers; this menu is no longer shown.
        self.auto_open_popup = config.get_bool("popup", "auto_open", True) if config else True
        self.popup = FeedPopup(
            self.feeds,
            width=config.get_int("popup", "width", 440, minimum=320) if config else 440,
            max_height=config.get_int("popup", "height", 620, minimum=240) if config else 620,
        )
        self._weather_alert_items = []
        self._weather_pulse_source = None
        self._weather_pulse_phase = False
        self._weather_tray_pulse_source = None
        self._weather_tray_pulse_phase = False
        self._breaking_pulse_source = None
        self._breaking_pulse_phase = False
        self._last_schedule_alert_token = None
        self._closing = False
        self._timeout_sources = []
        self._add_timeout_seconds(60, self._periodic_refresh)
        if self.timer is not None:
            self.timer.poll()
            self._add_timeout_seconds(1, self._timer_tick)
        if self.connectivity is not None:
            self._add_timeout_seconds(self.connectivity_interval, self._connectivity_tick)
            self._connectivity_tick()
        if self.updates is not None:
            self._add_timeout_seconds(self.update_interval, self._update_scan_tick)
            self._update_scan_tick()
        if self.weather is not None:
            self._add_timeout_seconds(max(300, self.weather.interval), self._weather_tick)
            self._weather_tick()
        if self.live is not None:
            self._add_timeout_seconds(max(60, self.live.interval), self._live_tick)
            self._live_tick()
        if self.media is not None:
            self._add_timeout_seconds(max(600, self.media.interval), self._media_tick)
            self._media_tick()

    def _add_timeout_seconds(self, seconds, callback):
        source_id = None

        def invoke():
            if self._closing:
                if source_id in self._timeout_sources:
                    self._timeout_sources.remove(source_id)
                return GLib.SOURCE_REMOVE
            keep = callback()
            if keep == GLib.SOURCE_REMOVE and source_id in self._timeout_sources:
                self._timeout_sources.remove(source_id)
            return keep

        source_id = GLib.timeout_add_seconds(seconds, invoke)
        self._timeout_sources.append(source_id)
        return source_id

    def _add_timeout(self, milliseconds, callback):
        source_id = None

        def invoke():
            if self._closing:
                if source_id in self._timeout_sources:
                    self._timeout_sources.remove(source_id)
                return GLib.SOURCE_REMOVE
            keep = callback()
            if keep == GLib.SOURCE_REMOVE and source_id in self._timeout_sources:
                self._timeout_sources.remove(source_id)
            return keep

        source_id = GLib.timeout_add(milliseconds, invoke)
        self._timeout_sources.append(source_id)
        return source_id

    def _remove_timeout(self, source_id):
        if source_id is None:
            return
        try:
            GLib.source_remove(source_id)
        except GLib.Error:
            pass
        if source_id in self._timeout_sources:
            self._timeout_sources.remove(source_id)

    def _idle_add(self, callback, *args):
        if self._closing:
            return 0

        def invoke():
            if self._closing:
                return GLib.SOURCE_REMOVE
            return callback(*args)

        return GLib.idle_add(invoke)

    def close(self):
        """Stop UI timers and detach GTK objects before application shutdown."""
        if self._closing:
            return
        self._closing = True
        for source_id in tuple(self._timeout_sources):
            self._remove_timeout(source_id)
        for source_id in (self._weather_pulse_source,
                          self._weather_tray_pulse_source,
                          self._breaking_pulse_source):
            self._remove_timeout(source_id)
        self._weather_pulse_source = None
        self._weather_tray_pulse_source = None
        self._breaking_pulse_source = None
        try:
            self.popup.close()
            self.menu.destroy()
            self.icon.set_visible(False)
        except (RuntimeError, TypeError):
            self.log.debug("GTK tray objects were already disposed", exc_info=True)

    def _on_activate(self, _icon):
        self.popup.toggle()

    def _on_popup(self, _icon, _button, _activate_time):
        self.popup.toggle()

    def _append(self, label, callback=None, sensitive=True):
        item = Gtk.MenuItem.new_with_label(label)
        item.set_sensitive(sensitive)
        if callback:
            item.connect("activate", callback)
        self.menu.append(item)

    def _rebuild_menu(self, _menu):
        self._weather_alert_items = []
        for child in self.menu.get_children():
            self.menu.remove(child)
            child.destroy()
        unread = self.feeds.unread_items()
        self._append(f"Flux Tray — {len(unread)} unread", sensitive=False)
        if self.connectivity is not None:
            network = self.connectivity.state.get("status", "checking")
            self._append(f"Network: {network}", sensitive=False)
            if self.connectivity.reset_available:
                self._append("Reset network…", lambda _item: self._confirm_network_reset())
        if self.weather is not None:
            weather = self.weather.state
            temperature = weather.get("temperature")
            condition = weather.get("condition", "Weather unavailable")
            if temperature is not None:
                weather_text = f"Weather: {temperature}°C · {condition} · wind {weather.get('wind_speed', '?')} km/h"
            else:
                weather_text = condition
            self._append(weather_text, sensitive=False)
            self._append("Refresh weather", lambda _item: self._weather_tick(force=True))
            self._append("Weather settings…", lambda _item: self._weather_settings_dialog())
            for day in weather.get("forecast", []):
                label = f"{day.get('date')}: {day.get('condition')} · H {day.get('high')}° L {day.get('low')}° · rain {day.get('rain_probability')}%"
                self._append(label, sensitive=False)
            for alert in weather.get("alerts", []):
                alert_label = f"⚠ {alert.get('severity', 'warning').title()}: {alert.get('title', 'Weather warning')} · {alert.get('area', '')}"
                link = alert.get("url")
                callback = (lambda _item, target=link: webbrowser.open(target)
                            if target and target.startswith(("http://", "https://")) else None)
                alert_item = Gtk.MenuItem.new_with_label(alert_label[:110])
                alert_item.set_sensitive(bool(link))
                if alert.get("level", 0) >= 3:
                    self._weather_alert_items.append((alert_item, alert_label[:110]))
                if link:
                    alert_item.connect("activate", callback)
                self.menu.append(alert_item)
            if weather.get("alerts_error"):
                self._append("MeteoAlarm: warning feed unavailable", sensitive=False)
        if self.live is not None:
            channels = self.live.state.get("channels", [])
            self._append(f"Live channels ({len(channels)})", sensitive=False)
            for channel in channels:
                metadata = channel.get("metadata", {})
                title = metadata.get("title") or channel["status"]
                category = metadata.get("category")
                viewers = metadata.get("viewers")
                started = metadata.get("created_at")
                elapsed = ""
                if started:
                    try:
                        began = datetime.fromisoformat(started.replace("Z", "+00:00"))
                        seconds = max(0, int((datetime.now(timezone.utc) - began).total_seconds()))
                        hours, remainder = divmod(seconds, 3600)
                        minutes = remainder // 60
                        elapsed = f"{hours}h {minutes}m" if hours else f"{minutes}m"
                    except (TypeError, ValueError):
                        pass
                details = [value for value in (category, f"{viewers:,} viewers" if isinstance(viewers, int) else None, elapsed or None) if value]
                label = f"{channel['name']} — {title}"
                if details:
                    label += " · " + " · ".join(details)
                schedule = channel.get("schedule", [])
                weekdays = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
                schedule_text = ", ".join(f"{weekdays[entry['weekday']]} {entry['time']}"
                                          for entry in schedule)
                if schedule_text:
                    label += " · " + schedule_text
                if channel.get("last_error"):
                    label += " · check failed"
                item = Gtk.MenuItem.new_with_label(label[:110])
                item.set_tooltip_text(title + (" (last check failed)" if channel.get("last_error") else ""))
                submenu = Gtk.Menu()
                play = Gtk.MenuItem.new_with_label("Play")
                play.set_sensitive(channel.get("status") == "live")
                play.connect("activate", lambda _widget, current=channel: self._play_live_channel(current))
                set_schedule = Gtk.MenuItem.new_with_label("Edit schedule…")
                set_schedule.connect("activate", lambda _widget, current=channel: self._live_schedule_dialog(current))
                remove = Gtk.MenuItem.new_with_label("Remove channel")
                remove.connect("activate", lambda _widget, current=channel: self._remove_live_channel(current))
                submenu.append(play)
                submenu.append(set_schedule)
                submenu.append(remove)
                item.set_submenu(submenu)
                self.menu.append(item)
            self._append("Add live channel…", lambda _item: self._add_live_dialog())
            self._append("Check live channels", lambda _item: self._live_tick(force=True))
        if self.media is not None:
            sources = self.media.state.get("sources", [])
            queue = self.media.state.get("queue", [])
            self._append(f"Media sources: {len(sources)} · queued: {len(queue)}", sensitive=False)
            download_state = self.media.state.get("download") or {}
            download_status = download_state.get("status")
            if download_status == "downloading":
                percent = download_state.get("percent")
                progress = f"{percent:.0f}%" if isinstance(percent, (int, float)) else "working"
                self._append(f"Download {progress}: {download_state.get('title', 'Episode')}"[:100],
                             sensitive=False)
            elif download_status == "failed":
                self._append(f"Download failed: {download_state.get('title', 'Episode')}"[:100],
                             sensitive=False)
            elif download_status == "completed":
                self._append(f"Last download: {download_state.get('title', 'Episode')}"[:100],
                             sensitive=False)
            if download_status == "failed" and queue:
                self._append("Retry media download", lambda _item: self._media_download_next())
            for source in sources:
                source_label = source.get("name", source.get("url", "Media source"))
                if source.get("last_error"):
                    source_label += " · check failed"
                parent_source = Gtk.MenuItem.new_with_label(source_label[:100])
                source_menu = Gtk.Menu()
                edit_source = Gtk.MenuItem.new_with_label("Edit source…")
                edit_source.connect("activate", lambda _widget, current=source:
                                    self._edit_media_source_dialog(current))
                rename_source = Gtk.MenuItem.new_with_label("Rename…")
                rename_source.connect("activate", lambda _widget, current=source:
                                      self._rename_media_source_dialog(current))
                remove_source = Gtk.MenuItem.new_with_label("Remove source…")
                remove_source.connect("activate", lambda _widget, current=source:
                                      self._remove_media_source_dialog(current))
                source_menu.append(edit_source)
                source_menu.append(rename_source)
                source_menu.append(remove_source)
                parent_source.set_submenu(source_menu)
                self.menu.append(parent_source)
            episodes = list(self.media.state.get("episodes", {}).values())
            episodes.sort(key=lambda item: item.get("discovered_at", ""), reverse=True)
            for episode in episodes[:8]:
                label = f"{episode.get('title', 'Untitled')} [{episode.get('status', 'new')}]"[:100]
                parent = Gtk.MenuItem.new_with_label(label)
                submenu = Gtk.Menu()
                play_item = Gtk.MenuItem.new_with_label("Play")
                play_item.connect("activate", lambda _widget, current=episode: self._play_media_episode(current))
                queue_item = Gtk.MenuItem.new_with_label("Queue download")
                queue_item.connect("activate", lambda _widget, current=episode: self._queue_media_episode(current))
                submenu.append(play_item)
                submenu.append(queue_item)
                parent.set_submenu(submenu)
                self.menu.append(parent)
            self._append("Add media source…", lambda _item: self._add_media_dialog())
            self._append("Check media sources", lambda _item: self._media_tick(force=True))
            self._append("Download next", lambda _item: self._media_download_next())
            self._append("Play next unwatched", lambda _item: self._media_play_next())
        self.menu.append(Gtk.SeparatorMenuItem())
        if not self.feeds.state["feeds"]:
            self._append("No feeds configured", sensitive=False)
        for feed in self.feeds.state["feeds"]:
            count = sum(1 for item in unread if item["feed_id"] == feed["id"])
            parent = Gtk.MenuItem.new_with_label(f"{feed['name']} ({count})")
            submenu = Gtk.Menu()
            mark = Gtk.MenuItem.new_with_label("Mark all read")
            mark.connect("activate", lambda _widget, current=feed: self._mark_feed_read(current["id"]))
            muted = bool(feed.get("muted"))
            mute = Gtk.MenuItem.new_with_label("Unmute" if muted else "Mute")
            mute.connect("activate", lambda _widget, current=feed, value=not muted:
                         self._set_feed_muted(current["id"], value))
            rename = Gtk.MenuItem.new_with_label("Rename…")
            rename.connect("activate", lambda _widget, current=feed: self._rename_feed_dialog(current))
            interval = Gtk.MenuItem.new_with_label("Polling interval…")
            interval.connect("activate", lambda _widget, current=feed: self._feed_interval_dialog(current))
            remove = Gtk.MenuItem.new_with_label("Remove feed…")
            remove.connect("activate", lambda _widget, current=feed: self._remove_feed_dialog(current))
            for action in (mark, mute, rename, interval, remove):
                submenu.append(action)
            parent.set_submenu(submenu)
            self.menu.append(parent)
        if unread:
            self.menu.append(Gtk.SeparatorMenuItem())
            for item in unread[:20]:
                title = item["title"].replace("\n", " ").strip()[:70]
                details = [item.get("author", "").strip(),
                           ", ".join(item.get("categories", [])[:2])]
                details = [value for value in details if value]
                if details:
                    title += " · " + " · ".join(details)
                parent = Gtk.MenuItem.new_with_label(title[:110])
                parent.set_tooltip_text(
                    " · ".join(value for value in (
                        item.get("title", "").strip(),
                        item.get("author", "").strip(),
                        ", ".join(item.get("categories", [])),
                    ) if value)
                )
                parent.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
                parent.connect("button-press-event", self._on_unread_item_button_press,
                               item)
                submenu = Gtk.Menu()
                open_item = Gtk.MenuItem.new_with_label("Open")
                open_item.connect("activate", lambda _widget, current=item: self._open_item(current))
                save_item = Gtk.MenuItem.new_with_label("Save for later")
                save_item.connect("activate", lambda _widget, current=item: self._save_for_later(current))
                submenu.append(open_item)
                submenu.append(save_item)
                parent.set_submenu(submenu)
                self.menu.append(parent)
        saved = self.feeds.read_later_items()
        if saved:
            self.menu.append(Gtk.SeparatorMenuItem())
            self._append(f"Read later ({len(saved)})", sensitive=False)
            for item in saved[:10]:
                title = item["title"].replace("\n", " ").strip()[:90]
                self._append(title, lambda _widget, current=item: self._open_item(current))
        if unread:
            gap = Gtk.MenuItem.new()
            gap.set_size_request(-1, 12)
            gap.set_can_focus(False)
            gap.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            gap.connect("button-press-event", self._on_unread_gap_button_press)
            self.menu.append(gap)
        self.menu.append(Gtk.SeparatorMenuItem())
        self._append("Add feed…", lambda _item: self._add_feed_dialog())
        self._append("Reorder feeds…", lambda _item: self._reorder_feeds_dialog())
        self._append("Feed rules…", lambda _item: self._feed_rules_dialog())
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
            self._append("Recurring alarms", sensitive=False)
            for alarm in self.timer.schedules:
                days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
                day_text = ",".join(days[index] for index in alarm.get("weekdays", []) if 0 <= index < 7)
                parent = Gtk.MenuItem.new_with_label(f"{day_text} {alarm.get('time')} — {alarm.get('label')}"[:100])
                submenu = Gtk.Menu()
                edit = Gtk.MenuItem.new_with_label("Edit alarm…")
                edit.connect("activate", lambda _item, current=alarm: self._recurring_alarm_dialog(current))
                remove = Gtk.MenuItem.new_with_label("Remove alarm")
                remove.connect("activate", lambda _item, current=alarm: self._remove_recurring_alarm(current))
                submenu.append(edit)
                submenu.append(remove)
                parent.set_submenu(submenu)
                self.menu.append(parent)
            self._append("Add recurring alarm…", lambda _item: self._recurring_alarm_dialog())
            if self.timer.state.get("schedule_alert"):
                active_alarm = self.timer.state["schedule_alert"]
                self._append(f"Alarm: {active_alarm.get('label', 'Reminder')}", sensitive=False)
                self._append("Snooze alarm 5 minutes", lambda _item: self._snooze_recurring_alarm())
                self._append("Dismiss alarm", lambda _item: self._dismiss_recurring_alarm())
        if self.updates is not None:
            changes = self.updates.state.get("changes", [])
            self._append(f"XBPS updates: {len(changes)}", sensitive=False)
            self._append("Check for updates", lambda _item: self._scan_updates())
            if changes:
                self._append("Apply system updates…", lambda _item: self._confirm_updates())
            last_action = self.updates.state.get("last_action")
            if last_action:
                outcome = "success" if last_action.get("success") else "FAILED"
                self._append(f"Last maintenance: {last_action.get('action', 'Action')} — {outcome}",
                             sensitive=False)
                self._append("View maintenance details…",
                             lambda _item: self._show_update_action_dialog())
                self._append("Dismiss maintenance result",
                             lambda _item: self._dismiss_update_action())
            self._append("List orphan packages…", lambda _item: self._list_orphans())
        if self.launcher is not None:
            commands = self.launcher.commands()
            self._append("Launch", sensitive=False)
            for command in commands:
                parent = Gtk.MenuItem.new_with_label(command.name)
                submenu = Gtk.Menu()
                run = Gtk.MenuItem.new_with_label("Run")
                run.connect("activate", lambda _item, name=command.name: self._launch_command(name))
                edit = Gtk.MenuItem.new_with_label("Edit…")
                edit.connect("activate", lambda _item, current=command:
                             self._launcher_command_dialog(current))
                remove = Gtk.MenuItem.new_with_label("Remove…")
                remove.connect("activate", lambda _item, current=command:
                               self._remove_launcher_command_dialog(current))
                for action in (run, edit, remove):
                    submenu.append(action)
                parent.set_submenu(submenu)
                self.menu.append(parent)
            self._append("Add launcher command…", lambda _item: self._launcher_command_dialog())
        self._append("Refresh feeds", lambda _item: self.refresh(force=True))
        self._append("Quit", lambda _item: self.application.quit())
        self.menu.show_all()
        self._sync_weather_pulse()
        self._sync_breaking_pulse()
        self._update_icon()

    def _on_menu_map(self, _widget):
        self._sync_weather_pulse()
        self._sync_breaking_pulse()

    def _on_menu_unmap(self, _widget):
        if self._weather_pulse_source is not None:
            self._remove_timeout(self._weather_pulse_source)
            self._weather_pulse_source = None
        self._weather_pulse_phase = False
        for item, label in self._weather_alert_items:
            item.set_label(label)

    def _sync_weather_pulse(self):
        severe = (self.weather is not None and
                  self.weather.state.get("alert_level", 0) >= 3)
        if severe and self._weather_tray_pulse_source is None:
            self._weather_tray_pulse_source = self._add_timeout(600, self._pulse_weather_tray)
        elif not severe and self._weather_tray_pulse_source is not None:
            self._remove_timeout(self._weather_tray_pulse_source)
            self._weather_tray_pulse_source = None
            self._weather_tray_pulse_phase = False
            self._update_icon()
        if severe and self.menu.get_mapped() and self._weather_pulse_source is None:
            self._weather_pulse_source = self._add_timeout(600, self._pulse_weather_alerts)
        elif (not severe or not self.menu.get_mapped()) and self._weather_pulse_source is not None:
            self._remove_timeout(self._weather_pulse_source)
            self._weather_pulse_source = None
            self._weather_pulse_phase = False
            for item, label in self._weather_alert_items:
                item.set_label(label)

    def _pulse_weather_tray(self):
        severe = (self.weather is not None and
                  self.weather.state.get("alert_level", 0) >= 3)
        if not severe:
            self._weather_tray_pulse_source = None
            self._weather_tray_pulse_phase = False
            self._update_icon()
            return GLib.SOURCE_REMOVE
        self._weather_tray_pulse_phase = not self._weather_tray_pulse_phase
        self._update_icon()
        return GLib.SOURCE_CONTINUE

    def _sync_breaking_pulse(self):
        active = bool(self.feeds.breaking_items())
        if active and self._breaking_pulse_source is None:
            self._breaking_pulse_source = self._add_timeout(600, self._pulse_breaking_items)
        elif not active and self._breaking_pulse_source is not None:
            self._remove_timeout(self._breaking_pulse_source)
            self._breaking_pulse_source = None
            self._breaking_pulse_phase = False

    def _pulse_breaking_items(self):
        if not self.feeds.breaking_items():
            self._breaking_pulse_source = None
            self._breaking_pulse_phase = False
            self._update_icon()
            return GLib.SOURCE_REMOVE
        self._breaking_pulse_phase = not self._breaking_pulse_phase
        self._update_icon()
        return GLib.SOURCE_CONTINUE

    def _pulse_weather_alerts(self):
        severe = (self.weather is not None and
                  self.weather.state.get("alert_level", 0) >= 3)
        if not severe or not self.menu.get_mapped():
            self._weather_pulse_source = None
            self._weather_pulse_phase = False
            for item, label in self._weather_alert_items:
                item.set_label(label)
            return GLib.SOURCE_REMOVE
        self._weather_pulse_phase = not self._weather_pulse_phase
        prefix = "🚨 " if self._weather_pulse_phase else "⚠ "
        for item, label in self._weather_alert_items:
            item.set_label(prefix + label.lstrip("⚠🚨 "))
        return GLib.SOURCE_CONTINUE

    def _launcher_command_dialog(self, command=None):
        if self.config is None:
            return
        dialog = Gtk.Dialog(title="Edit launcher command" if command else "Add launcher command",
                            flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(6)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.pack_start(Gtk.Label(label="Command name (letters, numbers, _ and -)"), False, False, 0)
        name = Gtk.Entry()
        name.set_text(command.name if command else "")
        box.pack_start(name, False, False, 0)
        box.pack_start(Gtk.Label(label="Arguments as a JSON array; no shell parsing"), False, False, 0)
        argv = Gtk.Entry()
        argv.set_text(json.dumps(list(command.argv) if command else [""]))
        argv.set_placeholder_text('[ "firefox", "--private-window" ]')
        box.pack_start(argv, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        error = None
        if response == Gtk.ResponseType.OK:
            command_name = name.get_text().strip()
            try:
                if not re.fullmatch(r"[A-Za-z0-9_-]+", command_name):
                    raise ValueError("Use a simple command name with letters, numbers, _ or -")
                command_name = command_name.casefold()
                parsed = json.loads(argv.get_text())
                if (not isinstance(parsed, list) or not parsed
                        or not all(isinstance(part, str) and part for part in parsed)):
                    raise ValueError("Arguments must be a non-empty JSON array of non-empty strings")
                self.config.set_many("launcher", {command_name: json.dumps(parsed)})
                if command and command.name != command_name:
                    self.config.remove_option("launcher", command.name)
            except (ValueError, json.JSONDecodeError, OSError) as exc:
                error = str(exc)
        dialog.destroy()
        if error:
            message = Gtk.MessageDialog(flags=Gtk.DialogFlags.MODAL,
                message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE,
                text="Launcher command was not saved")
            message.format_secondary_text(error)
            message.run()
            message.destroy()
        self._rebuild_menu(self.menu)

    def _remove_launcher_command_dialog(self, command):
        dialog = Gtk.MessageDialog(flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.YES_NO,
            text=f"Remove launcher command ‘{command.name}’?") 
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES and self.config is not None:
            self.config.remove_option("launcher", command.name)
        self._rebuild_menu(self.menu)

    def _launch_command(self, name):
        try:
            self.launcher.launch(name)
        except Exception:
            self.log.exception("Could not launch configured command: %s", name)
    def _on_unread_item_button_press(self, _widget, event, item):
        if event.button == 3:
            self.feeds.mark_read(item["id"])
            self._finish_feed_read_action(True)
            self._rebuild_menu(self.menu)
            return True
        return False

    def _on_unread_gap_button_press(self, _widget, event):
        if event.button == 3:
            self.menu.popdown()
            return True
        return False

    def _finish_feed_read_action(self, was_unread):
        if was_unread and self.feeds.unread_count() == 0 and self.menu.get_mapped():
            self.menu.popdown()

    def _open_item(self, item):
        was_unread = any(current["id"] == item["id"]
                         for current in self.feeds.unread_items())
        if item.get("link"):
            try:
                webbrowser.open(item["link"])
            except Exception:
                self.log.exception("Could not open feed link")
        self.feeds.mark_read(item["id"])
        self._finish_feed_read_action(was_unread)
        self._rebuild_menu(self.menu)

    def _save_for_later(self, item):
        was_unread = any(current["id"] == item["id"]
                         for current in self.feeds.unread_items())
        self.feeds.save_for_later(item["id"])
        self._finish_feed_read_action(was_unread)
        self._rebuild_menu(self.menu)
    def _set_feed_muted(self, feed_id, muted):
        self.feeds.set_muted(feed_id, muted)
        self._rebuild_menu(self.menu)

    def _mark_feed_read(self, feed_id):
        was_unread = any(item["feed_id"] == feed_id
                         for item in self.feeds.unread_items())
        self.feeds.mark_feed_read(feed_id)
        self._finish_feed_read_action(was_unread)
        self._rebuild_menu(self.menu)

    def _update_icon(self):
        unread = self.feeds.unread_count()
        updates = len(self.updates.state.get("changes", [])) if self.updates is not None else 0
        alert_level = self.weather.state.get("alert_level", 0) if self.weather is not None else 0
        breaking = bool(self.feeds.breaking_items())
        if alert_level >= 3:
            color = "#d83b3b" if self._weather_tray_pulse_phase else "#e69a24"
            fallback = "dialog-warning-symbolic"
            mark = '<path d="M8 3v5m0 2v.2" stroke="white" stroke-width="1.8" stroke-linecap="round" fill="none"/>'
        elif updates:
            color, fallback = "#d83b3b", "software-update-urgent-symbolic"
            mark = '<path d="M8 3v7m-3-3 3 3 3-3M4 13h8" stroke="white" stroke-width="1.7" fill="none"/>'
        elif breaking:
            color = "#d83b3b" if self._breaking_pulse_phase else "#e69a24"
            fallback = "dialog-warning-symbolic"
            mark = '<path d="M8 3v5m0 2v.2" stroke="white" stroke-width="1.8" stroke-linecap="round" fill="none"/>'
        elif unread:
            color, fallback = "#e69a24", "mail-unread-symbolic"
            mark = '<circle cx="8" cy="8" r="2.2" fill="white"/>'
        else:
            color, fallback = "#36a269", "view-list-symbolic"
            mark = '<path d="m4 8 2.5 2.5L12 5" stroke="white" stroke-width="1.8" fill="none"/>'
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7.3" fill="{color}"/>{mark}</svg>'
        try:
            loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
            loader.write(svg.encode("utf-8"))
            loader.close()
            self.icon.set_from_pixbuf(loader.get_pixbuf())
        except Exception:
            theme = Gtk.IconTheme.get_default()
            if theme is not None and theme.has_icon(fallback):
                self.icon.set_from_icon_name(fallback)
            else:
                self.icon.set_from_pixbuf(self._fallback_icon_pixbuf(color))
        network = self.connectivity.state.get("status") if self.connectivity is not None else None
        suffix = f" · {network}" if network else ""
        temperature = self.weather.state.get("temperature") if self.weather is not None else None
        weather_suffix = f" · {temperature}°C" if temperature is not None else ""
        alert_suffix = " · severe weather warning" if alert_level >= 3 else ""
        breaking_suffix = " · breaking feed item" if breaking else ""
        self.icon.set_tooltip_text(f"Flux Tray — {unread} unread{suffix}{weather_suffix}{alert_suffix}{breaking_suffix}")

    @staticmethod
    def _fallback_icon_pixbuf(color: str):
        red, green, blue = (int(color[index:index + 2], 16)
                            for index in (1, 3, 5))
        pixels = bytearray(16 * 16 * 4)
        for y in range(16):
            for x in range(16):
                dx, dy = x - 7.5, y - 7.5
                if dx * dx + dy * dy > 49:
                    continue
                offset = (y * 16 + x) * 4
                pixels[offset:offset + 4] = bytes((red, green, blue, 255))
        # A small white center mark keeps the fallback recognizable without SVG support.
        for y in range(6, 10):
            for x in range(6, 10):
                offset = (y * 16 + x) * 4
                pixels[offset:offset + 4] = b"\xff\xff\xff\xff"
        return GdkPixbuf.Pixbuf.new_from_bytes(
            GLib.Bytes.new(bytes(pixels)), GdkPixbuf.Colorspace.RGB, True,
            8, 16, 16, 16 * 4,
        )

    def _reorder_feeds_dialog(self):
        dialog = Gtk.Dialog(title="Reorder feeds", flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.pack_start(Gtk.Label(label="Drag rows to set the feed order."), False, False, 0)
        model = Gtk.ListStore(str, str)
        for feed in self.feeds.state["feeds"]:
            model.append([feed["id"], feed["name"]])
        view = Gtk.TreeView(model=model)
        renderer = Gtk.CellRendererText()
        view.append_column(Gtk.TreeViewColumn("Feed", renderer, text=1))
        view.set_reorderable(True)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(220)
        scroll.add(view)
        box.pack_start(scroll, True, True, 0)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            ordered_ids = [row[0] for row in model]
            try:
                self.feeds.reorder_feeds(ordered_ids)
            except ValueError as exc:
                self.log.warning("Could not reorder feeds: %s", exc)
        dialog.destroy()
        self._rebuild_menu(self.menu)

    def _rename_feed_dialog(self, feed):
        dialog = Gtk.Dialog(title="Rename feed", flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        entry = Gtk.Entry()
        entry.set_text(feed.get("name", ""))
        entry.set_activates_default(True)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.get_content_area().pack_start(entry, True, True, 12)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            try:
                self.feeds.rename_feed(feed["id"], entry.get_text())
            except ValueError as exc:
                self.log.warning("Could not rename feed: %s", exc)
        dialog.destroy()
        self._rebuild_menu(self.menu)

    def _feed_interval_dialog(self, feed):
        dialog = Gtk.Dialog(title="Feed polling interval", flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        spin = Gtk.SpinButton.new_with_range(1, 1440, 1)
        spin.set_value(max(1, round(feed.get("interval", 60) / 60)))
        box.pack_start(Gtk.Label(label="Minutes between checks"), False, False, 8)
        box.pack_start(spin, False, False, 8)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            self.feeds.set_interval(feed["id"], int(spin.get_value()) * 60)
        dialog.destroy()
        self._rebuild_menu(self.menu)

    def _remove_feed_dialog(self, feed):
        dialog = Gtk.MessageDialog(flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.YES_NO,
            text=f"Remove feed ‘{feed.get('name', 'Feed')}’?") 
        dialog.format_secondary_text("This also removes its stored items and read-later entries.")
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            self.feeds.remove_feed(feed["id"])
        self._rebuild_menu(self.menu)

    def _feed_rules_dialog(self):
        dialog = Gtk.Dialog(title="Feed rules", flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(6)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.pack_start(Gtk.Label(label="Breaking words (one per line)"), False, False, 0)
        breaking_view = Gtk.TextView()
        breaking_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        breaking_view.set_size_request(320, 90)
        breaking_view.get_buffer().set_text("\n".join(self.feeds.breaking_words))
        box.pack_start(breaking_view, False, False, 0)
        box.pack_start(Gtk.Label(label="Route matching items to Read later (category: value / author: value)"),
                       False, False, 0)
        rules_view = Gtk.TextView()
        rules_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        rules_view.set_size_request(320, 110)
        rules = self.feeds.state.get("routing_rules", [])
        rules_view.get_buffer().set_text("\n".join(
            f"{rule.get('kind', 'category')}: {rule.get('value', '')}" for rule in rules))
        box.pack_start(rules_view, False, False, 0)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            try:
                start, end = breaking_view.get_buffer().get_bounds()
                words_text = breaking_view.get_buffer().get_text(start, end, True)
                start, end = rules_view.get_buffer().get_bounds()
                rules_text = rules_view.get_buffer().get_text(start, end, True)
                parsed_rules = []
                for line in rules_text.splitlines():
                    if not line.strip():
                        continue
                    kind, separator, value = line.partition(":")
                    if not separator:
                        raise ValueError("Routing rules must use ‘category: value’ or ‘author: value’")
                    parsed_rules.append({"kind": kind.strip(), "value": value.strip()})
                self.feeds.set_breaking_words(words_text.splitlines())
                self.feeds.set_routing_rules(parsed_rules)
            except ValueError as exc:
                self.log.warning("Invalid feed rules: %s", exc)
        dialog.destroy()
        self._rebuild_menu(self.menu)

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

    def _play_live_channel(self, channel):
        future = self.tasks.submit("live-playback", self.live.play_channel, channel["id"])
        if future is not None:
            future.add_done_callback(lambda done: self._idle_add(self._live_play_complete, done, channel["url"]))

    def _live_play_complete(self, future, fallback_url):
        try:
            future.result()
        except Exception:
            self.log.exception("Streamlink/mpv playback failed; opening browser fallback")
            webbrowser.open(fallback_url)
        return GLib.SOURCE_REMOVE
    def _media_tick(self, *, force: bool = False):
        if self.media is None:
            return GLib.SOURCE_REMOVE
        future = self.tasks.submit("media-check", self.media.check_due, force=force)
        if future is not None:
            future.add_done_callback(lambda done: GLib.idle_add(self._media_check_complete, done))
        return GLib.SOURCE_CONTINUE

    def _media_check_complete(self, future):
        try:
            added = future.result()
        except Exception:
            self.log.exception("Media source check failed")
            added = 0
        if added:
            notification = Gio.Notification.new(f"{added} new media episode(s)")
            notification.set_body("New episodes are available in Flux Tray.")
            self.application.send_notification(None, notification)
            if not self.menu.get_mapped():
                self._rebuild_menu(self.menu)
                self.menu.popup_at_pointer(None)
        elif self.menu.get_mapped():
            self._rebuild_menu(self.menu)
        if self.media.state.get("queue"):
            self._media_download_next()
        return GLib.SOURCE_REMOVE

    def _queue_media_episode(self, episode):
        self.media.queue_episode(episode["id"])
        self._media_download_next()

    def _media_download_next(self):
        future = self.tasks.submit("media-download", self.media.download_next,
                                   progress_callback=self._queue_media_progress)
        if future is not None:
            if self.menu.get_mapped():
                self._rebuild_menu(self.menu)
            future.add_done_callback(lambda done: GLib.idle_add(self._media_download_complete, done))

    def _queue_media_progress(self, download_state):
        GLib.idle_add(self._media_progress_update, download_state)

    def _media_progress_update(self, download_state):
        current = self.media.state.get("download") or {}
        if (current.get("episode_id") == download_state.get("episode_id")
                and current.get("status") == "downloading"):
            for key in ("percent", "downloaded_bytes", "total_bytes", "eta"):
                if key in download_state:
                    current[key] = download_state[key]
            percent = download_state.get("percent")
            if isinstance(percent, (int, float)):
                self.icon.set_tooltip_text(
                    f"Flux Tray — downloading {percent:.0f}%: {download_state.get('title', 'Episode')}")
            if self.menu.get_mapped():
                self._rebuild_menu(self.menu)
        return GLib.SOURCE_REMOVE

    def _media_download_complete(self, future):
        try:
            episode = future.result()
            if episode:
                self.log.info("Downloaded media episode: %s", episode.get("title"))
        except Exception as exc:
            self.log.exception("Media download failed")
            notification = Gio.Notification.new("Media download failed")
            notification.set_body(str(exc)[:180])
            self.application.send_notification(None, notification)
        else:
            if self.media.state.get("queue"):
                self._media_download_next()
        if self.menu.get_mapped():
            self._rebuild_menu(self.menu)
        self._update_icon()
        return GLib.SOURCE_REMOVE

    def _media_play_next(self):
        future = self.tasks.submit("media-playback", self.media.play_next_unwatched)
        if future is not None:
            future.add_done_callback(lambda done: GLib.idle_add(self._media_play_complete, done, None))

    def _play_media_episode(self, episode):
        future = self.tasks.submit("media-playback", self.media.play_episode, episode["id"])
        if future is not None:
            future.add_done_callback(lambda done: GLib.idle_add(
                self._media_play_complete, done, episode.get("url")))

    def _media_play_complete(self, future, fallback_url):
        try:
            future.result()
        except Exception:
            self.log.exception("Media playback failed")
            if fallback_url:
                webbrowser.open(fallback_url)
        return GLib.SOURCE_REMOVE

    def _edit_media_source_dialog(self, source):
        dialog = Gtk.Dialog(title="Edit media source", flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        kind = Gtk.ComboBoxText()
        labels = (("YouTube", "youtube"), ("RSS/Atom", "rss"),
                  ("URL (yt-dlp)", "url"), ("Plugin", "plugin"))
        for label_text, _value in labels:
            kind.append_text(label_text)
        selected = next((index for index, pair in enumerate(labels)
                         if pair[1] == source.get("kind")), 0)
        kind.set_active(selected)
        name = Gtk.Entry()
        name.set_text(source.get("name", ""))
        name.set_placeholder_text("Source name (optional)")
        url = Gtk.Entry()
        url.set_text(source.get("url", ""))
        url.set_placeholder_text("Channel, playlist, feed or URL")
        for widget in (kind, name, url):
            box.pack_start(widget, False, False, 0)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            try:
                selected_kind = labels[kind.get_active()][1]
                self.media.update_source(source["id"], selected_kind, url.get_text(),
                                         name.get_text())
                self._media_tick(force=True)
            except (ValueError, IndexError) as exc:
                self.log.warning("Could not edit media source: %s", exc)
        dialog.destroy()
        self._rebuild_menu(self.menu)

    def _rename_media_source_dialog(self, source):
        dialog = Gtk.Dialog(title="Rename media source", flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        entry = Gtk.Entry()
        entry.set_text(source.get("name", ""))
        dialog.get_content_area().pack_start(entry, True, True, 12)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            try:
                self.media.rename_source(source["id"], entry.get_text())
            except ValueError as exc:
                self.log.warning("Could not rename media source: %s", exc)
        dialog.destroy()
        self._rebuild_menu(self.menu)

    def _remove_media_source_dialog(self, source):
        dialog = Gtk.MessageDialog(flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.YES_NO,
            text=f"Remove media source ‘{source.get('name', 'Source')}’?") 
        dialog.format_secondary_text("Its episode history, queue entries and watched state will also be cleared.")
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            self.media.remove_source(source["id"])
        self._rebuild_menu(self.menu)

    def _add_media_dialog(self):
        dialog = Gtk.Dialog(title="Add media source", flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Add", Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        kind = Gtk.ComboBoxText()
        for label in ("YouTube", "RSS/Atom", "URL (yt-dlp)", "Plugin"):
            kind.append_text(label)
        kind.set_active(0)
        name = Gtk.Entry()
        name.set_placeholder_text("Source name (optional)")
        url = Gtk.Entry()
        url.set_placeholder_text("Channel, playlist, feed or URL")
        box.pack_start(kind, False, False, 0)
        box.pack_start(name, False, False, 0)
        box.pack_start(url, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            selected = (kind.get_active_text() or "YouTube").lower()
            source_kind = {"youtube": "youtube", "rss/atom": "rss",
                           "url (yt-dlp)": "url", "plugin": "plugin"}[selected]
            try:
                self.media.add_source(source_kind, url.get_text(), name.get_text().strip() or None)
                self._media_tick()
            except ValueError as exc:
                self.log.warning("Could not add media source: %s", exc)
        dialog.destroy()

    def _live_tick(self, *, force: bool = False):
        if self.live is None:
            return GLib.SOURCE_REMOVE
        future = self.tasks.submit("live-check", self.live.check_due, force=force)
        if future is not None:
            future.add_done_callback(lambda done: GLib.idle_add(self._live_complete, done))
        return GLib.SOURCE_CONTINUE

    def _live_complete(self, future):
        try:
            transitions = future.result()
        except Exception:
            self.log.exception("Live channel check failed")
            transitions = 0
        if transitions:
            notification = Gio.Notification.new(f"{transitions} channel(s) went live")
            notification.set_body("Open Flux Tray to view live channels.")
            self.application.send_notification(None, notification)
            if not self.menu.get_mapped():
                self._rebuild_menu(self.menu)
                self.menu.popup_at_pointer(None)
        elif self.menu.get_mapped():
            self._rebuild_menu(self.menu)
        return GLib.SOURCE_REMOVE

    def _live_schedule_dialog(self, channel):
        dialog = Gtk.Dialog(title=f"Schedule — {channel['name']}", flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.pack_start(Gtk.Label(label="Weekly schedule (local time), e.g. Mon 19:30, Fri 21:00"), False, False, 0)
        entry = Gtk.Entry()
        days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        current = ", ".join(f"{days[item['weekday']]} {item['time']}" for item in channel.get("schedule", []))
        entry.set_text(current)
        box.pack_start(entry, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            try:
                mapping = {day.casefold(): index for index, day in enumerate(days)}
                entries = []
                for token in entry.get_text().split(","):
                    token = token.strip()
                    if not token:
                        continue
                    day, clock = token.split(None, 1)
                    entries.append({"weekday": mapping[day[:3].casefold()], "time": clock.strip()})
                self.live.set_schedule(channel["id"], entries)
            except (ValueError, KeyError) as exc:
                self.log.warning("Invalid live schedule: %s", exc)
        dialog.destroy()
        self._rebuild_menu(self.menu)

    def _remove_live_channel(self, channel):
        self.live.remove_channel(channel["id"])
        self._rebuild_menu(self.menu)

    def _add_live_dialog(self):
        dialog = Gtk.Dialog(title="Add live channel", flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Add", Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        platform = Gtk.ComboBoxText()
        platform.append_text("Twitch")
        platform.append_text("YouTube")
        platform.set_active(0)
        name = Gtk.Entry()
        name.set_placeholder_text("Channel name")
        url = Gtk.Entry()
        url.set_placeholder_text("https://twitch.tv/channel or YouTube live URL")
        box.pack_start(platform, False, False, 0)
        box.pack_start(name, False, False, 0)
        box.pack_start(url, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            try:
                selected = (platform.get_active_text() or "Twitch").lower()
                self.live.add_channel(selected, name.get_text(), url.get_text())
                self._live_tick()
            except (ValueError, OSError) as exc:
                self.log.warning("Could not add live channel: %s", exc)
        dialog.destroy()
    def _weather_settings_dialog(self):
        if self.weather is None or self.config is None:
            return
        dialog = Gtk.Dialog(title="Weather settings", flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(6)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        def add_field(label, value, placeholder):
            box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
            entry = Gtk.Entry()
            entry.set_text(value)
            entry.set_placeholder_text(placeholder)
            box.pack_start(entry, False, False, 0)
            return entry

        location = add_field("Place name (preferred)", self.config.get("weather", "location", "") or "",
                             "e.g. Buzau, Romania")
        latitude = add_field("Latitude (optional)", self.config.get("weather", "lat", "") or "",
                             "e.g. 45.15")
        longitude = add_field("Longitude (optional)", self.config.get("weather", "lon", "") or "",
                              "e.g. 26.82")
        region = add_field("County/region for MeteoAlarm", self.config.get("weather", "region", "") or "",
                           "e.g. Buzau")
        alerts = Gtk.CheckButton.new_with_label("Enable MeteoAlarm severe-weather warnings")
        alerts.set_active(self.config.get_bool("weather", "alerts", False))
        box.pack_start(alerts, False, False, 4)
        dialog.show_all()
        response = dialog.run()
        error = None
        if response == Gtk.ResponseType.OK:
            place = location.get_text().strip()
            lat_text, lon_text = latitude.get_text().strip(), longitude.get_text().strip()
            region_text = region.get_text().strip()
            try:
                if place:
                    lat_value = lon_value = None
                    lat_text = lon_text = ""
                elif lat_text and lon_text:
                    lat_value, lon_value = float(lat_text), float(lon_text)
                    if not -90 <= lat_value <= 90 or not -180 <= lon_value <= 180:
                        raise ValueError("Latitude must be -90..90 and longitude -180..180")
                else:
                    raise ValueError("Enter a place name or both coordinates")
                if alerts.get_active() and not region_text:
                    raise ValueError("Enter a county/region before enabling MeteoAlarm")
                country = self.config.get("weather", "country", "romania") or "romania"
                self.config.set_many("weather", {
                    "location": place, "lat": lat_text, "lon": lon_text,
                    "region": region_text, "alerts": str(alerts.get_active()).lower(),
                    "country": country,
                })
                from flux_tray.weather.alerts import MeteoAlarmClient
                from flux_tray.weather.geocode import NominatimGeocoder
                alerts_client = (MeteoAlarmClient(country=country, region=region_text)
                                 if alerts.get_active() else None)
                self.weather.configure(
                    latitude=lat_value, longitude=lon_value, location=place or None,
                    geocoder=NominatimGeocoder() if place else None,
                    alerts_client=alerts_client,
                )
            except (ValueError, OSError) as exc:
                error = str(exc)
        dialog.destroy()
        if error:
            message = Gtk.MessageDialog(flags=Gtk.DialogFlags.MODAL,
                message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE,
                text="Weather settings were not saved")
            message.format_secondary_text(error)
            message.run()
            message.destroy()
        elif response == Gtk.ResponseType.OK:
            self._weather_tick(force=True)
            self._rebuild_menu(self.menu)

    def _weather_tick(self, *, force: bool = False):
        if self.weather is None:
            return GLib.SOURCE_REMOVE
        future = self.tasks.submit("weather-refresh", self.weather.refresh, force=force)
        if future is not None:
            future.add_done_callback(lambda done: GLib.idle_add(self._weather_complete, done))
        return GLib.SOURCE_CONTINUE

    def _weather_complete(self, future):
        try:
            future.result()
        except Exception:
            self.log.exception("Weather refresh failed")
        self._sync_weather_pulse()
        self._update_icon()
        if self.menu.get_mapped():
            self._rebuild_menu(self.menu)
        return GLib.SOURCE_REMOVE
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
        self._update_icon()
        if self.menu.get_mapped():
            self._rebuild_menu(self.menu)
        return GLib.SOURCE_REMOVE

    def _confirm_updates(self):
        changes = self.updates.state.get("changes", [])
        lines = []
        for change in changes[:18]:
            lines.append(f"{change.get('action', 'update')}: {change.get('pkgver', 'unknown')} "
                         f"({change.get('architecture', '?')}) · download {change.get('download_size', '?')} "
                         f"· installed {change.get('installed_size', '?')}")
        if len(changes) > 18:
            lines.append(f"…and {len(changes) - 18} more package(s)")
        summary = "\n".join(lines) or "No package details available."
        dialog = Gtk.MessageDialog(flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.YES_NO,
            text="Apply all available system updates?")
        dialog.format_secondary_text("This runs the real system upgrade. It is not a dry run.\n\n" + summary)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            future = self.tasks.submit("xbps-update", self.updates.apply_updates)
            if future is not None:
                future.add_done_callback(lambda done: GLib.idle_add(self._update_action_complete, done))

    def _show_update_action_dialog(self):
        action = self.updates.state.get("last_action") or {}
        results = action.get("results", [])
        lines = [f"{action.get('action', 'Maintenance action')} — "
                 f"{'success' if action.get('success') else 'FAILED'}"]
        for result in results:
            argv = " ".join(result.get("argv", []))
            lines.append(f"\n$ {argv}\nExit code: {result.get('returncode')}")
            output = result.get("stderr") or result.get("stdout") or ""
            if output:
                lines.append(output[-2500:])
        dialog = Gtk.MessageDialog(flags=Gtk.DialogFlags.MODAL,
            message_type=(Gtk.MessageType.INFO if action.get("success") else Gtk.MessageType.ERROR),
            buttons=Gtk.ButtonsType.CLOSE, text="Maintenance result")
        dialog.format_secondary_text("\n".join(lines)[:7000])
        dialog.run()
        dialog.destroy()

    def _dismiss_update_action(self):
        self.updates.dismiss_last_action()
        self._rebuild_menu(self.menu)

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
        else:
            action = self.updates.state.get("last_action")
            if action:
                title = "Maintenance completed" if action.get("success") else "Maintenance failed"
                notification = Gio.Notification.new(title)
                notification.set_body(action.get("action", "System maintenance"))
                self.application.send_notification(None, notification)
        self._scan_updates()
        if self.menu.get_mapped():
            self._rebuild_menu(self.menu)
        return GLib.SOURCE_REMOVE

    def _confirm_network_reset(self):
        dialog = Gtk.MessageDialog(flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.YES_NO,
            text="Run the configured network reset command?")
        dialog.format_secondary_text("This executes connectivity.reset_command from your configuration.")
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            future = self.tasks.submit("connectivity-reset", self.connectivity.reset)
            if future is not None:
                future.add_done_callback(lambda done: GLib.idle_add(self._network_reset_complete, done))

    def _network_reset_complete(self, future):
        try:
            result = future.result()
            self.log.info("Connectivity reset completed: %s", result.stdout.strip())
        except Exception:
            self.log.exception("Configured connectivity reset failed")
        self._connectivity_tick()
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
            self.refresh(force=True)
            if self.weather is not None:
                self._weather_tick(force=True)
            if self.media is not None:
                self._media_tick(force=True)
            if self.live is not None:
                self._live_tick(force=True)
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
        step_minutes = self.timer.step / 60
        maximum_minutes = (self.timer.maximum // self.timer.step) * step_minutes
        spin = Gtk.SpinButton.new_with_range(step_minutes, max(step_minutes, maximum_minutes),
                                            step_minutes)
        default_steps = max(1, round(300 / self.timer.step))
        spin.set_value(default_steps * step_minutes)
        box.pack_start(Gtk.Label(label="Duration (minutes)"), False, False, 0)
        box.pack_start(spin, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            try:
                self.timer.start(int(round(spin.get_value() * 60)))
            except ValueError as exc:
                self.log.warning("Invalid timer duration: %s", exc)
        dialog.destroy()
        self._rebuild_menu(self.menu)

    def _cancel_timer(self):
        self.timer.cancel()
        self._rebuild_menu(self.menu)

    def _recurring_alarm_dialog(self, alarm=None):
        dialog = Gtk.Dialog(title="Edit recurring alarm" if alarm else "Add recurring alarm",
                            flags=Gtk.DialogFlags.MODAL)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        days = Gtk.Entry()
        days.set_placeholder_text("Days: Mon,Tue,Wed,Thu,Fri,Sat,Sun")
        weekdays = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        if alarm:
            days.set_text(",".join(weekdays[index] for index in alarm.get("weekdays", [])
                                   if 0 <= index < 7))
        else:
            days.set_text("Mon,Tue,Wed,Thu,Fri")
        clock = Gtk.Entry()
        clock.set_placeholder_text("Time: 07:30 (24-hour local time)")
        clock.set_text(alarm.get("time", "07:30") if alarm else "07:30")
        label = Gtk.Entry()
        label.set_placeholder_text("Alarm label")
        label.set_text(alarm.get("label", "Reminder") if alarm else "Reminder")
        for widget in (days, clock, label):
            box.pack_start(widget, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            names = {"mon": 0, "tue": 1, "wed": 2, "thu": 3,
                     "fri": 4, "sat": 5, "sun": 6}
            try:
                weekdays = [names[token.strip().lower()[:3]]
                            for token in days.get_text().split(",") if token.strip()]
                if alarm:
                    self.timer.update_schedule(alarm["id"], weekdays,
                                               clock.get_text().strip(), label.get_text())
                else:
                    self.timer.add_schedule(weekdays, clock.get_text().strip(), label.get_text())
            except (KeyError, ValueError) as exc:
                self.log.warning("Could not save recurring alarm: %s", exc)
        dialog.destroy()
        self._rebuild_menu(self.menu)

    def _remove_recurring_alarm(self, alarm):
        self.timer.remove_schedule(alarm["id"])
        self._rebuild_menu(self.menu)

    def _snooze_recurring_alarm(self):
        self.timer.snooze_schedule_alert(5)
        self._last_schedule_alert_token = None
        self._rebuild_menu(self.menu)

    def _dismiss_recurring_alarm(self):
        self.timer.dismiss_schedule_alert()
        self._last_schedule_alert_token = None
        self._rebuild_menu(self.menu)

    def _timer_tick(self):
        if self.timer is None:
            return GLib.SOURCE_REMOVE
        result = self.timer.poll()
        schedule_alert = self.timer.poll_schedules()
        if schedule_alert:
            token = schedule_alert.get("fired_at")
            if token != self._last_schedule_alert_token:
                self._last_schedule_alert_token = token
                display = Gdk.Display.get_default()
                if display is not None:
                    display.beep()
                notification = Gio.Notification.new(schedule_alert.get("label", "Recurring alarm"))
                notification.set_body("Recurring alarm — snooze for 5 minutes or dismiss in Flux Tray.")
                self.application.send_notification(None, notification)
                self.icon.set_tooltip_text("Flux Tray — recurring alarm")
        if self.media is not None:
            try:
                self.media.update_playback_progress()
            except Exception:
                self.log.exception("Could not update media playback progress")
        if result == "ring":
            display = Gdk.Display.get_default()
            if display is not None:
                display.beep()
            self.icon.set_tooltip_text("Flux Tray — timer finished")
        if self.menu.get_mapped():
            self._rebuild_menu(self.menu)
        return GLib.SOURCE_CONTINUE

    def refresh(self, *, force: bool = False):
        def work():
            if self.connectivity is not None and self.connectivity.state.get("status") in {"offline", "dns-error"}:
                return 0
            return self.feeds.check_due(force=force)
        future = self.tasks.submit("feed-refresh", work)
        if future is not None:
            future.add_done_callback(lambda done: GLib.idle_add(self._refresh_complete, done))

    def _refresh_complete(self, future):
        try:
            fresh = future.result()
        except Exception:
            self.log.exception("Feed refresh failed")
            fresh = 0
        self._update_icon()
        if self.popup.visible or fresh:
            self.popup.rebuild()
        if fresh:
            breaking = self.feeds.take_unnotified_breaking_items()
            if breaking:
                display = Gdk.Display.get_default()
                if display is not None:
                    display.beep()
                notification = Gio.Notification.new(f"{len(breaking)} breaking feed item(s)")
                notification.set_body(breaking[0].get("title", "A matching feed item is available")[:180])
            else:
                notification = Gio.Notification.new(f"{fresh} new feed items")
                notification.set_body("New items are ready in Flux Tray.")
            self.application.send_notification(None, notification)
            if self.auto_open_popup:
                self.popup.show()
        return GLib.SOURCE_REMOVE

    def _periodic_refresh(self):
        self.refresh()
        return GLib.SOURCE_CONTINUE
