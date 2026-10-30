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

[weather]
interval = 30
alerts = false
lat =
lon =

[updates]
interval = 12
installer = topgrade
orphans = true

[timer]
max = 120
step = 60

[connectivity]
interval = 10

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
- `weather.interval`: minutes; default 30, minimum 5.
- `weather.lat` and `weather.lon`: decimal coordinates. Weather is disabled until both are set.
- `updates.interval`: hours; default 12.
- `timer.max`: maximum countdown in minutes.
- `timer.step`: countdown step in seconds.
- `connectivity.interval`: seconds; default 10.

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
