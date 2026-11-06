---
name: performance-analyzer
description: Analyze flux-tray for GTK main loop bottlenecks, thread contention, memory leaks, and startup latency
---

# Performance Analyzer — flux-tray

Specialized subagent for identifying performance issues in the flux-tray GTK3 tray application.

## Focus Areas

### 1. GTK Main Loop Latency
- **Long-running idle_add callbacks** blocking UI responsiveness
- **Excessive timeout_add calls** creating timer overhead
- **Blocking operations on main thread** (file I/O, JSON parsing, config reads)

### 2. Thread Contention
- **Lock hold times** on `self.lock`, `_check_lock`, `_xbps_lock`, etc.
- **Thread proliferation** — too many concurrent daemon threads
- **GLib.idle_add queue buildup** from rapid thread completions

### 3. Memory Leaks
- **GTK object references** not released (popovers, menus, windows)
- **Callback closures** capturing `self` preventing GC
- **Periodic callbacks** not cancelled on object destruction
- **State/media JSON growth** — unbounded `seen`/`unread` lists

### 4. Startup Latency
- **Import time** — heavy modules loaded at startup
- **Config parsing** — INI parsing on every launch
- **State loading** — JSON decode + validation
- **GTK initialization** — widget creation before first paint

### 5. Network I/O Patterns
- **Sequential vs parallel** feed/check probes
- **Timeout values** — too aggressive causing retries
- **Connection reuse** — missing HTTP keep-alive
- **Feed parser efficiency** — feedparser overhead

### 6. Media Pipeline
- **yt-dlp subprocess spawn** overhead per episode
- **HLS segment downloads** — sequential vs parallel
- **Progress callback frequency** — too many idle_add calls

## Analysis Commands

```bash
# Startup time breakdown
python -X importtime -c "import flux_tray.app" 2>&1 | head -30

# Memory profile
python -m memory_profiler flux_tray/app.py

# Main loop callback timing
# Add @profile decorator to idle_add/timeout_add callbacks

# Lock contention
python -m threading --help  # (use py-spy or manual instrumentation)

# GTK frame timing
# Run with: GDK_DEBUG=nogl xvfb-run -a python -m cProfile -o profile.stats flux-tray
```

## Key Files to Audit

| File | Concern |
|------|---------|
| `flux_tray/app.py` | Main loop setup, 7+ timeout_add, mixin initialization order |
| `flux_tray/ui/popup.py` | `refresh_list` rebuilds entire list, breaking pulse timeout |
| `flux_tray/feeds.py` | `merge_feed_check` complexity, feedparser per feed |
| `flux_tray/media.py` | Download queue, progress callbacks every segment |
| `flux_tray/updates.py` | `xbps` subprocess, package parsing |
| `flux_tray/network.py` | `diagnose_connectivity` probes, run_when_online queue |
| `flux_tray/state.py` | JSON load/save on every state change |

## Common Findings Checklist

### Main Loop
- [ ] Any `time.sleep()` on main thread?
- [ ] `GLib.timeout_add` with short intervals (<100ms) without need?
- [ ] `idle_add` callbacks doing heavy work (sorting, filtering, JSON)?
- [ ] Periodic callbacks not removed in `destroy`/`finalize`?

### Threading
- [ ] Lock held during network I/O?
- [ ] Lock held during GTK calls?
- [ ] More than 5 concurrent daemon threads typical?
- [ ] `threading.Thread` without `daemon=True`?

### Memory
- [ ] `GLib.timeout_add` source ID stored and `GLib.source_remove` on cleanup?
- [ ] `idle_add` callbacks capturing large objects?
- [ ] Popover/menu `destroy` signal connected for cleanup?
- [ ] `state.json` `seen` dict pruned (30 days implemented, verify)?
- [ ] `unread` list capped at 500 (verify enforced)?

### Startup
- [ ] `feedparser`, `pycairo`, `gi` imported at module level?
- [ ] Config parsed before GTK init?
- [ ] State loaded before first frame?
- [ ] Widgets created lazily?

### Network
- [ ] `requests`/`urllib` without connection pooling?
- [ ] Feed check interval respects `interval` setting?
- [ ] Concurrent feed checks limited?
- [ ] Probe timeout configurable?

### Media
- [ ] `yt-dlp` subprocess per episode (not batched)?
- [ ] HLS downloader creates many short-lived connections?
- [ ] Progress callback every segment (hundreds of idle_add)?
- [ ] Download queue processes sequentially?

## Output Format

Report findings as:

```markdown
## Performance Analysis: <area>

### Finding: <title>
**Severity**: High/Medium/Low
**Location**: `file.py:function` (line)
**Evidence**: <measurement or code pattern>
**Impact**: <user-visible effect: UI lag, memory growth, slow startup>
**Fix**: <specific change>
**Effort**: <S/M/L>
```

## Verification

After fixes, verify:
- `python -m pytest tests/ -k "not ui" --tb=short` (unit tests)
- `xvfb-run -a python -m unittest discover -s tests` (real GTK)
- Startup time: `time python -c "import flux_tray.app; print('ok')"`
- Memory: run for 1 hour, check RSS growth

---

**Invoke as**: `@performance-analyzer` or via Agent tool with this prompt