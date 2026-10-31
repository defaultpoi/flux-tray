# Flux-Tray Enhancement Plan: Exceeding void-tray

Based on the void-tray handoff brief (v6), this plan identifies gaps and improvements to make flux-tray superior while retaining all features and user behavior.

## Current State Analysis

**Flux-tray has:** Core architecture (src-layout, GTK3, services), feeds, live (streamlink), media (yt-dlp, RSS, HLS), weather, updates (xbps), timer, connectivity, launcher, plugins.

**Void-tray has (from handoff brief):** Pipe-delimited config format, feed header menu (open all tabs, website, XML, mute/later rules), weather back-arrow in same slot, Twitch GQL (batched), topgrade with xbps version comparison, media plugins system, config watcher (Gio), separate state.json/media.json, lock architecture, DNS/online handling, tray icon color semantics, popup focus behavior, media partial HLS playback.

## Phase 1: Configuration & Feed System (High Priority)

### 1.1 Adopt void-tray's feed config format
- Format: `URL|display name|interval minutes|mute rules|read-later rules`
- Migrate Config class to parse pipe-delimited feed lines
- Maintain backward compatibility during transition

### 1.2 Feed header right-click menu
- Add: "Open all unread as tabs", "Open feed website", "Open feed XML", "Manage category/author rules"
- Implement mute rules and read-later rules per feed (not just global)

### 1.3 Feed mute/read-later rules per feed
- Per-feed mute rules (categories/authors to mute)
- Per-feed read-later rules (categories/authors to save)
- Global rules still apply

## Phase 2: UI & Popup Improvements (High Priority)

### 2.1 Popup width fitting (like void-tray)
- Width = max(WINDOW_WIDTH, weather bar width in either view)
- Right edge stays against screen
- Refitted when new weather arrives

### 2.2 Popup focus behavior
- Close on focus-out EXCEPT when Launch list or menu popover is open
- Right-click blank area (after unread/read-later lists, before footer) closes popup
- When only live/media remain and popup visible: collapse to "No unread items"

### 2.3 Weather UI: back arrow in same slot
- The `‹` back arrow sits in the SAME slot as `›` (right end)
- Button stays under pointer when toggling

### 2.4 Tray icon color semantics
- Green = nothing unread (show temperature with degree ring)
- Orange = unread news
- Red = package updates
- Flashing red ! = scheduled-action warning
- Pulsing = weather alert
- Live/media never count in badge

## Phase 3: Live Channels - Twitch GQL (Medium Priority)

### 3.1 Implement Twitch GQL probe
- Batched requests of 20 via logged-out GQL
- Show category/viewers/elapsed and title tooltip
- Failed check must not erase last-known state
- Keep streamlink as fallback

## Phase 4: Package Updates - Topgrade Integration (Medium Priority)

### 4.1 Topgrade integration with version comparison
- Scan via `xbps-install -Mn -u`
- Install through topgrade with configured `steps=` (topgrade --only ids)
- Unattended: `--yes --no-retry --no-self-update --skip-notify`, stdin closed, `LC_ALL=C.UTF-8`
- Summary: `name old -> new` rows (xbps via installed versions before/after)
- Drop build revision `_1` unless it's all that changed
- Read Claude Code and rustup from their step output
- Red "Not updated:" line for failures

### 4.2 Orphans handling
- `xbps-query -O` without root
- Offer: List, Remove, Remove+cache cleanup, Cancel
- Never remove without explicit click
- Orphans don't affect badge/sound/popup

## Phase 5: Media System Enhancements (High Priority)

### 5.1 Media plugins system (matching void-tray)
- Plugins in `~/.config/flux-tray/media-plugins/*.py`
- Dynamically reloaded at source-check boundary
- Plugin precedence over built-ins; named prefix syntax (`plugin:NAME:SOURCE`)
- Interface: `list_episodes(source) -> (title, [episode])`, `matches(source)`, `resolve(episode)`, `download(episode, base, progress, cancelled)`, `NAME`, `ORDER`
- Built-ins: archive.org (intentionally NOT supported), yt-dlp for YouTube, RSS/Atom
- Helpers: bounded JSON fetch, resumable download, season/episode parser
- Validate output and show per-source errors

### 5.2 Media source ordering per source
- Each source: default (driver's order), `oldest`, `newest`
- Recognize S01E05 and 1x05; else date/stable order
- Store order on source record

### 5.3 HLS partial playback
- After ~1.5 MB downloaded, click plays `.part` file
- mpv continues through final rename
- Track against playlist length (not mpv's estimate)
- Refuse live playlists as downloads

### 5.4 Config watcher for [media] sources
- Gio.FileMonitor on config.conf (800ms debounce)
- New [media] sources checked immediately (`start_media_check(only=...)`)
- Full check skipped while one runs; specific-source check queued behind it

## Phase 6: State & Concurrency Improvements (Medium Priority)

### 6.1 Separate state.json and media.json
- state.json: unread, read_later, seen, last_checked, available_updates, timer_end, live_channels, etc.
- media.json: sources, episodes, queue, watched, files, last_watched, baselined
- Atomic save via unique temp names (`<name>.<hex>.tmp`)

### 6.2 Lock architecture
- lock (state), _check_lock, _xbps_lock, _twitch_lock, _youtube_lock, _player_lock, _mpv_lock, _media_data_lock, _media_queue_lock, _media_request_lock
- Never block GTK thread on network/subprocesses

### 6.3 DNS/Online handling
- `_dns_ok` keeps at most one lookup thread in flight
- `run_when_online` appends to `_online_waiting`; one `_wait_for_network` poller serves all callers

## Phase 7: Testing & Validation (Ongoing)

### 7.1 Pure logic tests first
- Feed parsing, state transitions, media normalization, HLS variant selection

### 7.2 Integration tests with real binaries
- mpv, ffmpeg, yt-dlp, streamlink, xbps utilities

### 7.3 Real GTK checks for visual behavior
- XFCE tray, popup focus, CSS/theme, icons

## Implementation Order

1. **Phase 1** - Config & Feed System (foundational)
2. **Phase 2** - UI & Popup (user-facing)
3. **Phase 5** - Media System (core differentiator)
4. **Phase 3** - Twitch GQL (live channels)
4. **Phase 4** - Package Updates (Void-specific)
5. **Phase 6** - State & Concurrency (robustness)
6. **Phase 7** - Testing (continuous)

Each phase: implement → test → verify with real tools → commit → CI green.
