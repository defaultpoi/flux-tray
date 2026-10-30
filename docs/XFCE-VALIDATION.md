# XFCE/X11 integration checklist

This checklist is intentionally separate from the pure-Python CI result. Complete it on the target Void Linux glibc + XFCE + X11 desktop before calling the app release-ready.

## 1. Environment and launch

- [ ] Confirm the session is X11: `echo "$XDG_SESSION_TYPE"` should print `x11`.
- [ ] Confirm GTK3/PyGObject imports: `python3 -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk, Gdk, GLib'`.
- [ ] Confirm the tray host is running (XFCE Panel's notification area or Status Notifier host).
- [ ] Launch Flux Tray from a terminal once and inspect `~/.local/state/flux-tray/` for startup errors.
- [ ] Launch it a second time; verify the existing tray opens and a second icon/controller is not created.
- [ ] Launch from the intended desktop autostart entry and verify no terminal is required.

## 2. Tray icon and popup

- [ ] Verify the normal, unread, breaking-news, update-available and severe-weather icon states.
- [ ] Verify SVG icon rendering. Temporarily test with SVG loading unavailable or a theme missing the named fallback icons; confirm the generated pixbuf fallback remains visible.
- [ ] Test both left-click and right-click popup activation.
- [ ] Test popup dismissal by clicking elsewhere, pressing Escape and switching windows.
- [ ] Test popup behavior with a long feed list, long titles, non-ASCII text and narrow panel dimensions.
- [ ] Switch between available XFCE icon themes and panel sizes; confirm the icon remains visible and legible.
- [ ] Confirm the popup does not steal focus from the active application or remain stuck open.

## 3. Background activity and responsiveness

- [ ] Leave the app idle for at least 15 minutes with no configured feeds or integrations; inspect CPU and memory with `ps -o pid,pcpu,pmem,rss,etime,cmd -C flux-tray`.
- [ ] Trigger feed refresh, live checks, weather refresh and media source checks while opening/closing the popup; confirm the UI remains responsive.
- [ ] Disconnect and restore networking; confirm no duplicate task storms and that checks resume after recovery.
- [ ] Trigger a download and watch percentage updates while interacting with other menu items.
- [ ] Confirm only one operation per task key runs at a time.

## 4. Shutdown and restart

- [ ] Exit Flux Tray normally; verify its process disappears and the tray icon is removed.
- [ ] Exit while a feed/weather/live/media check is in progress; confirm shutdown completes without GTK callback tracebacks.
- [ ] Exit during a media download; confirm the child process group is terminated and the download is marked interrupted on next start.
- [ ] Restart after a forced termination; verify state files remain valid and the app recovers.
- [ ] Repeat start/stop at least five times; confirm there are no orphaned mpv, yt-dlp, Streamlink or Flux Tray processes.

## 5. Suspend/resume and extended run

- [ ] Start a countdown, suspend the laptop past its deadline, resume and verify the missed/ringing behavior.
- [ ] Suspend across a recurring alarm time; verify it fires once for that local date and offers snooze/dismiss.
- [ ] Leave the app running for 24 hours; inspect logs for repeated exceptions, timer drift, duplicate notifications or memory growth.
- [ ] Verify the tray recovers after XFCE panel restart without restarting the app.

## 6. Evidence to record

Record date, Void package versions, XFCE version, GTK3 version, Python version, panel plugin/host, test results and relevant log excerpts. Do not mark an item complete based only on CI. Keep failures and untested items explicit in `docs/STATUS.md`.
