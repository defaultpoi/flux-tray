# Checks on a real desktop

The tests run without a panel, a tray host, a player window or a network that
answers like the real ones. Everything below needs the real thing: Void Linux,
XFCE on X11. [FEATURES.md](FEATURES.md) says which features each section covers.
Tick an item only after doing it, and write down what was not done in
[STATUS.md](STATUS.md); a green CI run does not tick anything here.

## 1. Environment and launch

- [ ] `echo "$XDG_SESSION_TYPE"` prints `x11`.
- [ ] `python3 -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk'` works, and `feedparser` imports.
- [ ] The panel's notification area (or a status notifier host) is running.
- [ ] `VOID_TRAY_DEBUG=1 void-tray` in a terminal starts without a traceback.
- [ ] `./install.sh --autostart` makes `~/.local/bin/void-tray` and `~/.config/autostart/void-tray.desktop`; after logging out and in the tray is there without a terminal.
- [ ] `./install.sh --no-autostart` removes the entry only; `./uninstall.sh` removes the link and the entry and leaves `~/.config/void-tray`.
- [ ] With a `~/.config/rss-tray` and no `~/.config/void-tray`, the first start copies config, state and sound.

## 2. Tray icon and popup

- [ ] The icon in each state: nothing unread (with the temperature), unread news, updates available, severe weather alert; the badge counts news, updates and alerts and nothing else.
- [ ] Left click and right click open the popup; click elsewhere, Escape and switching windows close it; it does not steal focus from the active window or stay stuck open.
- [ ] Compare the popup with `tests/golden/popup_full.json`'s rows: Live now, Media, feeds, Read later, Updates available, orphans, then the timer area and the buttons Launch, Timer, Edit config, Refresh, Mark all read, Quit.
- [ ] A long feed list, long titles, non-ASCII text, a narrow panel; the popup width with and without the weather bar.
- [ ] Left click on a row opens it in the browser and marks it read; right click marks it read only; the bookmark icon saves it; a feed header click marks the feed read; the feed menu (open, open all as tabs, mute, send to Read later).
- [ ] A feed whose item link is `file:///etc/hostname` or `ssh://x`: clicking the item marks it read and opens nothing.
- [ ] A breaking item pulses until it is read; an item sent to Read later makes no sound and no badge.
- [ ] Launch opens the configured entries; Edit config opens the file in the editor.
- [ ] Weather: today and forecast, the arrow button, the popup refits when data arrives; an alert changes the icon.

## 3. Background activity, network and the real tools

- [ ] Idle for 15 minutes with feeds, Twitch, YouTube, weather and media configured: `ps -o pid,pcpu,pmem,rss,etime,cmd -C python3` shows no climb in CPU or memory.
- [ ] Pull the network cable or turn Wi-Fi off: the offline banner and the diagnosis appear, nothing polls; turn it back on: everything catches up once, without a storm of checks.
- [ ] A Twitch and a YouTube channel that are live show their row; clicking plays in mpv at the configured quality, a second click reuses the window, the title reads `<Site> · <name> · <title>`.
- [ ] Without streamlink or mpv installed, a click opens the browser.
- [ ] A package update: the list, "Install all", the summary of changes afterwards, orphan removal.
- [ ] A media source of each kind in use (feed, archive.org, YouTube, an HLS plugin): check, download with progress, play, watched marks, the queue while watching.
- [ ] A master playlist whose variant is `file:///etc/hostname` is refused with a message, not read.

## 4. Shutdown, restart and files

- [ ] Quit from the popup and `kill` (SIGTERM) both leave cleanly: no traceback, the icon goes, no mpv, streamlink, yt-dlp or ffmpeg left behind (`pgrep -a 'mpv|streamlink|yt-dlp|ffmpeg'`).
- [ ] Quit during a download: no `.part` file stays that cannot be resumed or removed; the next start is clean.
- [ ] Kill -9 and start again: `state.json` and `media.json` load; a corrupt one is set aside as `*.corrupt`, not lost.
- [ ] Edit config.conf by hand while the app writes it (mark a feed muted in the menu): both changes are there afterwards, and no `config.conf.*.tmp` stays.
- [ ] Start and stop five times: no second tray icon, no leftover processes.

## 5. Timer, schedule and suspend

- [ ] A countdown survives a restart of the app and a reboot (the remaining time is right).
- [ ] Suspend past a countdown's end, resume: it is shown as missed, pulses, and acknowledging stops it.
- [ ] A scheduled action fires once for its local date, with the warning slide before it and Snooze.
- [ ] Leave it running for 24 hours with `VOID_TRAY_DEBUG=1` going to a file: no repeated exceptions, no drift in the timer, no duplicate notifications.
- [ ] Restart the XFCE panel: the tray icon returns without restarting the app.

## Evidence

Date, void-tray commit, Void package versions, XFCE, GTK3, Python, the panel's tray host, results, and the log lines that matter go in `docs/STATUS.md`.
