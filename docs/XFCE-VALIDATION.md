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
- [ ] `FLUX_TRAY_DEBUG=1 flux-tray` in a terminal starts without a traceback.
- [ ] `./install.sh --autostart` makes `~/.local/bin/flux-tray` and `~/.config/autostart/flux-tray.desktop`; after logging out and in the tray is there without a terminal.
- [ ] `./install.sh --no-autostart` removes the entry only; `./uninstall.sh` removes the link and the entry and leaves `~/.config/flux-tray`.

## 2. Tray icon and popup

- [ ] The icon in each state: nothing unread (with the temperature), unread news, updates available, severe weather alert (the temperature alternating between the severity colour and white at the severity's rate, no disc; with unread items the disc with the count pulses instead); the badge counts news, updates and alerts and nothing else.
- [ ] Left click and right click open the popup; click elsewhere, Escape and switching windows close it; it does not steal focus from the active window or stay stuck open.
- [ ] Compare the popup with `tests/golden/popup_full.json`'s rows: Live now, Media, feeds, Read later, Updates available, orphans, then the timer area and the buttons Launch, Timer, Edit config, Refresh, Mark all read, Quit.
- [ ] A long feed list, long titles, non-ASCII text, a narrow panel; the popup width with and without the weather bar.
- [ ] Left click on a row opens it in the browser and marks it read; right click marks it read only; the bookmark icon saves it; a feed header click marks the feed read; the feed menu (open, open all as tabs, mute, send to Read later).
- [ ] A feed whose item link is `file:///etc/hostname` or `ssh://x`: clicking the item marks it read and opens nothing.
- [ ] A breaking item pulses until it is read; an item sent to Read later makes no sound and no badge.
- [ ] Right-click a Media row: the menu opens beside it and the popup stays open; *Remove from list* is greyed (with the count in its tooltip) while episodes are unwatched and works when all are watched, taking the row (and the Media heading with the last one) out without the popup closing or the other rows moving; *Remove all N fully watched* appears with two or more such sources; the line is gone from `[media]` and the downloaded files are still there.
- [ ] Launch opens the configured entries; Edit config opens the file in the editor.
- [ ] Weather: today and forecast, the arrow button, the popup refits when data arrives; an alert changes the icon.
- [ ] With the MeteoAlarm feed listing an alert for a coming day: the `›` button on the first slide takes the severity colour (its arrow stays readable), its tooltip names the day and the hazard, and on the forecast slide that day's glyph has the colour (a ⚠ if the day had no rain glyph). Note how many days ahead your country's feed really goes, and whether an alert that spans midnight lands on the right days.
- [ ] Discovery, with one plugin that has `fetch_discovery`: its new films and series show under the Media sources (title, genres, the sites, an HD or CAM badge); a left click adds the source and the row goes; a right click dismisses it for good (restart and check). New items play the sound and open the popup. Hover a row and a source: the preview opens to the left of the popup, shows the poster once it is cached, and closes when the mouse leaves. Leave a download running with the popup open for a minute and hover: the preview appears once, not repeatedly.

## 3. Background activity, network and the real tools

- [ ] Idle for 15 minutes with feeds, Twitch, YouTube, weather and media configured: `ps -o pid,pcpu,pmem,rss,etime,cmd -C python3` shows no climb in CPU or memory.
- [ ] Pull the network cable or turn Wi-Fi off: the offline banner and the diagnosis appear, nothing polls; turn it back on: everything catches up once, without a storm of checks.
- [ ] A Twitch and a YouTube channel that are live show their row; clicking plays in mpv at the configured quality, a second click reuses the window, the title reads `<Site> · <name> · <title>`.
- [ ] Without streamlink or mpv installed, a click opens the browser.
- [ ] A package update: the list, "Install all", the summary of changes afterwards, orphan removal.
- [ ] A media source of each kind in use (feed, archive.org, YouTube, an HLS plugin): check, download with progress, play, watched marks, the queue while watching.
- [ ] A master playlist whose variant is `file:///etc/hostname` is refused with a message, not read.
- [ ] Start a movie, switch to a Twitch or YouTube stream from the Live section: the same mpv window is reused (no second window, no flicker of closing and reopening) and `pgrep -a streamlink` shows only the new stream's. Click the movie's row again: it carries on from a few seconds before where it was left, and the stream's streamlink is gone.
- [ ] With mpv 0.38 or newer (what Void ships), resuming works. If it does not, the log (`FLUX_TRAY_DEBUG=1`) says "mpv did not take start=" and the file plays from the beginning.
- [ ] Sleep timer: with `sleep=5`, leave a film playing untouched for 5 minutes: it pauses with "Still watching?" on screen, and a key or a mouse move carries it on. Let it play a further 5 minutes unattended: it pauses again. Without `libXScrnSaver` nothing happens and the log says so.
- [ ] Suspend and resume while an episode plays: tracking carries on after the wake (finish the episode: it counts as watched).
- [ ] Fall asleep through an episode that then plays to its end: it counts as watched (unavoidable); *Mark as not watched* puts it back. A movie marked `movie` shows "removed in 23 h"; *I didn't finish it* stops that; after the grace period the file is in the XFCE Trash and the line is gone from `[media]`.
- [ ] `behind=1` with three watched episodes downloaded: the two older ones (and their subtitles) are in the Trash, the newest is still on disk, none is downloaded again.
- [ ] With a real `tmdb_key` (and an `omdb_key`) in `[media]`: after a discovery check the titles get genres, posters, ratings and ids (`FLUX_TRAY_DEBUG=1` shows the lookups; no key appears in it); the same film from two sites becomes one row. With a wrong key nothing is cached as not found (fix the key: the next check looks again). Note which of TMDb's fields were empty.
- [ ] With two or more live channels, start one; **Right** and **Left** in the mpv window switch to the next and previous live channel (and not to the same one when it is the only live one). Then play a downloaded episode in the same window: Left and Right seek again. Note the mpv version.
- [ ] A stream whose title has emoji and non-Latin text (Japanese, Cyrillic): the window title keeps the text and drops the emoji.

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
- [ ] Leave it running for 24 hours with `FLUX_TRAY_DEBUG=1` going to a file: no repeated exceptions, no drift in the timer, no duplicate notifications.
- [ ] Restart the XFCE panel: the tray icon returns without restarting the app.

## Evidence

Date, Flux Tray commit, Void package versions, XFCE, GTK3, Python, the panel's tray host, results, and the log lines that matter go in `docs/STATUS.md`.
