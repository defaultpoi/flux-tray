"""GTK3/X11 tray shell for the feed reader."""

from __future__ import annotations

import logging
import webbrowser
from datetime import datetime, timezone

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk


class TrayController:
    def __init__(self, application, feed_service, task_manager, timer_service=None, connectivity_service=None, update_service=None, weather_service=None, live_service=None, media_service=None, launcher_service=None,
                 connectivity_interval: int = 10, update_interval: int = 43200):
        self.application = application
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
        self.menu = Gtk.Menu()
        self.menu.connect("map", self._on_menu_map)
        self.menu.connect("unmap", self._on_menu_unmap)
        self._weather_alert_items = []
        self._weather_pulse_source = None
        self._weather_pulse_phase = False
        self._last_schedule_alert_token = None
        GLib.timeout_add_seconds(60, self._periodic_refresh)
        if self.timer is not None:
            self.timer.poll()
            GLib.timeout_add_seconds(1, self._timer_tick)
        if self.connectivity is not None:
            GLib.timeout_add_seconds(self.connectivity_interval, self._connectivity_tick)
            self._connectivity_tick()
        if self.updates is not None:
            GLib.timeout_add_seconds(self.update_interval, self._update_scan_tick)
            self._update_scan_tick()
        if self.weather is not None:
            GLib.timeout_add_seconds(max(300, self.weather.interval), self._weather_tick)
            self._weather_tick()
        if self.live is not None:
            GLib.timeout_add_seconds(max(60, self.live.interval), self._live_tick)
            self._live_tick()
        if self.media is not None:
            GLib.timeout_add_seconds(max(600, self.media.interval), self._media_tick)
            self._media_tick()

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
            self._append(f"{feed['name']} ({count})",
                         lambda _item, fid=feed["id"]: self._mark_feed_read(fid))
            muted = bool(feed.get("muted"))
            self._append(("Unmute " if muted else "Mute ") + feed["name"],
                         lambda _item, fid=feed["id"], value=not muted: self._set_feed_muted(fid, value))
        if unread:
            self.menu.append(Gtk.SeparatorMenuItem())
            for item in unread[:20]:
                title = item["title"].replace("\n", " ").strip()[:90]
                parent = Gtk.MenuItem.new_with_label(title)
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
            self._append("Recurring alarms", sensitive=False)
            for alarm in self.timer.schedules:
                days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
                day_text = ",".join(days[index] for index in alarm.get("weekdays", []) if 0 <= index < 7)
                parent = Gtk.MenuItem.new_with_label(f"{day_text} {alarm.get('time')} — {alarm.get('label')}"[:100])
                submenu = Gtk.Menu()
                remove = Gtk.MenuItem.new_with_label("Remove alarm")
                remove.connect("activate", lambda _item, current=alarm: self._remove_recurring_alarm(current))
                submenu.append(remove)
                parent.set_submenu(submenu)
                self.menu.append(parent)
            self._append("Add recurring alarm…", lambda _item: self._recurring_alarm_dialog())
            if self.timer.state.get("schedule_alert"):
                self._append("Snooze alarm 5 minutes", lambda _item: self._snooze_recurring_alarm())
                self._append("Dismiss alarm", lambda _item: self._dismiss_recurring_alarm())
        if self.updates is not None:
            changes = self.updates.state.get("changes", [])
            self._append(f"XBPS updates: {len(changes)}", sensitive=False)
            self._append("Check for updates", lambda _item: self._scan_updates())
            if changes:
                self._append("Apply system updates…", lambda _item: self._confirm_updates())
            self._append("List orphan packages…", lambda _item: self._list_orphans())
        if self.launcher is not None:
            commands = self.launcher.commands()
            if commands:
                self._append("Launch", sensitive=False)
                for command in commands:
                    self._append(command.name, lambda _item, name=command.name: self._launch_command(name))
        self._append("Refresh feeds", lambda _item: self.refresh(force=True))
        self._append("Quit", lambda _item: self.application.quit())
        self.menu.show_all()
        self._sync_weather_pulse()
        self._update_icon()

    def _on_menu_map(self, _widget):
        self._sync_weather_pulse()

    def _on_menu_unmap(self, _widget):
        if self._weather_pulse_source is not None:
            GLib.source_remove(self._weather_pulse_source)
            self._weather_pulse_source = None
        self._weather_pulse_phase = False
        for item, label in self._weather_alert_items:
            item.set_label(label)

    def _sync_weather_pulse(self):
        severe = (self.weather is not None and
                  self.weather.state.get("alert_level", 0) >= 3)
        if severe and self.menu.get_mapped() and self._weather_pulse_source is None:
            self._weather_pulse_source = GLib.timeout_add(600, self._pulse_weather_alerts)
        elif (not severe or not self.menu.get_mapped()) and self._weather_pulse_source is not None:
            GLib.source_remove(self._weather_pulse_source)
            self._weather_pulse_source = None
            self._weather_pulse_phase = False
            for item, label in self._weather_alert_items:
                item.set_label(label)

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

    def _launch_command(self, name):
        try:
            self.launcher.launch(name)
        except Exception:
            self.log.exception("Could not launch configured command: %s", name)
    def _open_item(self, item):
        if item.get("link"):
            try:
                webbrowser.open(item["link"])
            except Exception:
                self.log.exception("Could not open feed link")
        self.feeds.mark_read(item["id"])
        self._rebuild_menu(self.menu)

    def _save_for_later(self, item):
        self.feeds.save_for_later(item["id"])
        self._rebuild_menu(self.menu)
    def _set_feed_muted(self, feed_id, muted):
        self.feeds.set_muted(feed_id, muted)
        self._rebuild_menu(self.menu)

    def _mark_feed_read(self, feed_id):
        self.feeds.mark_feed_read(feed_id)
        self._rebuild_menu(self.menu)

    def _update_icon(self):
        unread = self.feeds.unread_count()
        updates = len(self.updates.state.get("changes", [])) if self.updates is not None else 0
        if updates:
            color, fallback = "#d83b3b", "software-update-urgent-symbolic"
            mark = '<path d="M8 3v7m-3-3 3 3 3-3M4 13h8" stroke="white" stroke-width="1.7" fill="none"/>'
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
            self.icon.set_from_icon_name(fallback)
        network = self.connectivity.state.get("status") if self.connectivity is not None else None
        suffix = f" · {network}" if network else ""
        temperature = self.weather.state.get("temperature") if self.weather is not None else None
        weather_suffix = f" · {temperature}°C" if temperature is not None else ""
        alert_level = self.weather.state.get("alert_level", 0) if self.weather is not None else 0
        alert_suffix = " · severe weather warning" if alert_level >= 3 else ""
        self.icon.set_tooltip_text(f"Flux Tray — {unread} unread{suffix}{weather_suffix}{alert_suffix}")

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
            future.add_done_callback(lambda done: GLib.idle_add(self._live_play_complete, done, channel["url"]))

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
        future = self.tasks.submit("media-download", self.media.download_next)
        if future is not None:
            future.add_done_callback(lambda done: GLib.idle_add(self._media_download_complete, done))

    def _media_download_complete(self, future):
        try:
            episode = future.result()
            if episode:
                self.log.info("Downloaded media episode: %s", episode.get("title"))
        except Exception:
            self.log.exception("Media download failed")
        else:
            if self.media.state.get("queue"):
                self._media_download_next()
        if self.menu.get_mapped():
            self._rebuild_menu(self.menu)
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

    def _recurring_alarm_dialog(self):
        dialog = Gtk.Dialog(title="Add recurring alarm", flags=Gtk.DialogFlags.MODAL)
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
        days.set_text("Mon,Tue,Wed,Thu,Fri")
        clock = Gtk.Entry()
        clock.set_placeholder_text("Time: 07:30 (24-hour local time)")
        clock.set_text("07:30")
        label = Gtk.Entry()
        label.set_placeholder_text("Alarm label")
        label.set_text("Reminder")
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
        if self.menu.get_mapped() or fresh:
            self._rebuild_menu(self.menu)
        if fresh:
            notification = Gio.Notification.new(f"{fresh} new feed items")
            notification.set_body("New items are ready in Flux Tray.")
            self.application.send_notification(None, notification)
            if not self.menu.get_mapped():
                self.menu.popup_at_pointer(None)
        return GLib.SOURCE_REMOVE

    def _periodic_refresh(self):
        self.refresh()
        return GLib.SOURCE_CONTINUE
