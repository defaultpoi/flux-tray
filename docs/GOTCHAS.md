# Gotchas found the hard way

Read before touching GTK threads, popups, mpv, ffmpeg, yt-dlp, feedparser or anything that has to stay small in memory. Add a line when something costs a session an hour; say how it was found.

- `Path.with_suffix` replaces everything after the last dot, so `Dr. House - S01E01`
  became `Dr.ts`. Build file names by string concatenation.
- A CSS stylesheet with one unknown property is dropped whole (look for "Failed to
  apply CSS styles" in the log). A `Gtk.Popover` cannot leave its window.
  `set_no_show_all` blocks `show_all` on that widget. `Gdk` is main-thread only:
  workers read sizes the main thread stored. A `Gio.FileMonitor` must be kept
  referenced.
- ffmpeg's `-progress` `out_time_ms` is in microseconds. A reader that does not
  drain ffmpeg's output stalls ffmpeg. ffprobe can fail on a stream ffmpeg downloads
  fine. yt-dlp's `--print` makes it quiet unless `--progress` is given.
- `feedparser` resolves a relative `guid` against the feed URL. JSON object keys
  become strings.
- Thread tests: never release a blocked worker until the other side is provably
  waiting (an early release made one test fail one run in eight). Use a generous
  `threading.Timer` or a sequential test, and make poll intervals patchable so tests
  stay fast.
- A memory leak of a rebuilt popup shows only with a full list: with an empty Discover tab it was
  8 KB per rebuild, with 250 titles 8 MB. Measure with real rows and the real `show_popup`, under
  `xvfb-run`, and compare RSS and the number of live accordions (`gc.get_objects()`) after 20
  rebuilds. `Gtk.Window.destroy()` leaves the rows alive when Python objects hold the widgets;
  see the design notes in README.md.
- Mock-heavy UI tests are brittle, and most failures after feature work are stub
  fixtures (stubs borrow real methods: `class Stub: method = rt.FluxTray.method`).
  New logic gets pure tests; UI gets a few behaviour tests plus a real-GTK run.
