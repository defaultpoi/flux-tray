# Development

Target: Void Linux glibc, XFCE, X11. No cross-distro support or instructions.

Use system Python for GTK/PyGObject. A venv is acceptable for pure Python only if system GI bindings remain visible. Keep dependencies few and compatible with target Python.

Run python -m pytest. Ordinary tests must be offline and unprivileged. Mock HTTP and subprocess boundaries. Run real GTK checks inside XFCE/X11 before declaring tray/popup complete.

Review: GTK main-thread-only? slow work off-loop? timeouts/cancellation/reaping? one owner per state? transient failures preserve last-known data? tests assert behavior? feature genuinely complete rather than stub?