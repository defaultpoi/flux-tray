# User-supplied notes from previous app

These notes preserve behavior and implementation gotchas; they are not a mandate to reproduce the old architecture. **Archive.org support is explicitly excluded from Flux Tray**, even though the previous application supported it.

All GTK mutations from threads used GLib.idle_add; never block GTK on network/subprocesses. New architecture should use ownership and task de-duplication rather than copying many old locks.

Cadence to preserve: feeds 60 s; timer/schedule 1 s (also corner readout); connectivity 10 s; alert pulse 600 ms; breaking/missed pulse 700 ms, no work while popup hidden.

GTK3 rejects the entire CSS stylesheet on one unknown property. Inspect logs; use supported GTK3 properties and background shorthand. White scrolled list needs explicit dark text for custom labels. Gtk.Popover cannot reliably leave popup window even unconstrained: use inline rows or fit it. set_no_show_all blocks show_all for that widget; explicitly show children. Pango text glyphs need U+FE0E. Topgrade headings are localized: force LC_ALL=C.UTF-8. Openbox sandbox focus behavior does not prove XFCE behavior. Mock-heavy UI tests were brittle; prefer pure tests and a few UI behavior tests plus real-GTK check.

Verified in old app only: popup layout/theme/pulses; scheduler warn/fire-once/snooze/cancel/no-repeat; Topgrade install path and summary parsing; orphan flow with fake xbps/sudo; local feed mute/read-later; countdown missed state after simulated boot-clock jump; sudoers rules.

Not verified on real target in old app: real xbps-query -O output; Topgrade on Void; suspend/wake; Twitch viewersCount/createdAt; YouTube page parsing; tray icon in XFCE; popup/menu focus under XFCE; icon theme; online feeds with Website/XML buttons.

Reader view was discussed but not built. vkpurge cleanup was discussed but not built and requires a broader sudoers rule; excluded unless separately requested. Also not built: podcast episodes in popup, breaking tray pulse, reboot-needed indicator, held-but-updatable packages, disk warning, feed-link pruning, undo mute/later, Spotify. Gtk.StatusIcon deprecated, but user stays on X11/XFCE: choose what works there, no Wayland work.

Standing behavior: opening item/feed marks read; saved items not unread/badged; mute beats read-later; missed countdown does not ring late.