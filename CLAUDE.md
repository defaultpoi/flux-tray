# Flux Tray agent rules

Build a complete personal desktop tray app for Void Linux glibc + XFCE + X11 only. All requirements in docs/FEATURES.md are mandatory. Read docs/ARCHITECTURE.md, docs/OLD-APP-NOTES.md and docs/ROADMAP.md before coding.

No other distributions/desktops, Wayland, Windows/macOS, legacy migration/import/compatibility, server, web UI, database service, ORM or unnecessary framework. Do not remove features to simplify the rewrite.

GTK3/PyGObject + GLib. GTK objects are touched only on the GTK main thread. Network, filesystem-heavy and subprocess work runs in bounded background workers; dispatch UI callbacks through GLib.idle_add. UI renders service snapshots and dispatches commands; no business rules, parsing, subprocesses or persistence in widgets. Each feature service owns its state. No giant mutable app object or feature mixins.

Centralize config, logging, scheduling, task execution and process lifecycle. Use argv arrays, never shell interpolation. Add timeouts, cancellation, process-group termination and child reaping. Avoid duplicate overlapping jobs. Preserve last-known-good data on transient failures. Keep dependencies few and idle CPU/RAM low.

INI: ~/.config/flux-tray/config.conf. Trusted media plugins: ~/.config/flux-tray/media-plugins/. JSON state: ~/.local/share/flux-tray/. Logs: ~/.local/state/flux-tray/. Atomic writes, one writer per document, defaults and corruption recovery. No migration code.

Media plugins are trusted Python code. Version/document the protocol, validate outputs, isolate per-source errors and reload at source-check boundaries. Plugins return normalized episodes; services own downloads, watched state and UI.

Tests: pure tests for parsing/rules/state transitions; mock HTTP/subprocess boundaries; focused integration tests; few meaningful UI behavior tests; real GTK/XFCE validation. Do not infer XFCE focus or tray behavior from Openbox. GTK3 rejects a whole CSS sheet on one unsupported property. Implement behavior, tests and docs together. A menu item or stub is not a feature. Update roadmap honestly.