# Configuration

The application creates a fresh INI file at `~/.config/flux-tray/config.conf` on first launch. No settings are imported from the previous application.

```ini
[feeds]
interval = 60

[live]
interval = 15
quality = best

[media]
interval = 60
ahead = 2
path = ~/Videos
screen_height =
yt_dlp_sort =

[weather]
interval = 30
alerts = false
country = romania
region =
location =
lat =
lon =

[updates]
interval = 12
installer = topgrade
topgrade_steps =
orphans = true

[timer]
max = 120
step = 60

[connectivity]
interval = 10
reset_command =

[launcher]
terminal = ["xfce4-terminal"]
file_manager = ["thunar"]
```

## Units

- `feeds.interval`: seconds; minimum 60. Default for newly added feeds.
- `live.interval`: minutes; default 15.
- `media.interval`: minutes; default 60, minimum 10.
- `media.ahead`: number of episodes to keep queued for automatic sequential download; `0` disables automatic ahead downloads.
- `media.path`: download directory.
- `media.screen_height`: optional manual display-height override in pixels; empty uses the active X11 display detected by `xrandr`.
- `media.yt_dlp_sort`: optional yt-dlp `-S` value. When set, it overrides automatic monitor-aware resolution selection.
- `weather.interval`: minutes; default 30, minimum 5.
- `weather.lat` and `weather.lon`: decimal coordinates. Set both, or leave both empty and configure `weather.location`.
- `weather.location`: optional place name (for example `Buzau, Romania`); if coordinates are absent, Nominatim resolves it once and the coordinates are cached in weather state.
- `weather.alerts`: enable optional MeteoAlarm warnings.
- `weather.country`: MeteoAlarm country-feed slug (default `romania`).
- `weather.region`: required region/county text used to filter active warnings, accent-insensitively. Example: `Buzau`.
- `updates.interval`: hours; default 12.
- `updates.installer`: `topgrade` (default) or `xbps`; if Topgrade is unavailable, Flux Tray falls back to XBPS directly.
- `updates.topgrade_steps`: optional comma-separated Topgrade step names to run in addition to `system`. Use only step names accepted by your installed Topgrade version.
- `timer.max`: maximum countdown in minutes.
- `timer.step`: countdown step in seconds.\n- Recurring alarms are managed from the tray menu, use local time and accept comma-separated weekdays (`Mon,Tue,Wed,Thu,Fri,Sat,Sun`), a 24-hour `HH:MM` time and a label. They are stored in `~/.local/share/flux-tray/timer.json`; they fire once per matching date and can be snoozed for five minutes or dismissed. These alarms do not depend on the countdown `max` or `step` settings.
- `connectivity.interval`: seconds; default 10.
- `connectivity.reset_command`: optional JSON argv array for a manual network-reset action. It is never run automatically; configure only a command you trust.

## Launcher commands

Launcher values must be JSON arrays of arguments. This avoids shell parsing and interpolation. For example:

```ini
[launcher]
terminal = ["xfce4-terminal"]
firefox_private = ["firefox", "--private-window"]
```

Do not write a shell command as a plain string; it will be ignored. The current implementation intentionally supports argv commands only.

## Media plugins

Trusted Python plugins are loaded from `~/.config/flux-tray/media-plugins/` at source-check boundaries. Plugins execute with the same user permissions as Flux Tray. Only install code you trust.
