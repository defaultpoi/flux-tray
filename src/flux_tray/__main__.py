"""Application entry point."""

from __future__ import annotations

import logging
import sys


def main() -> int:
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401
    except (ImportError, ValueError) as exc:
        logging.error("GTK3/PyGObject is unavailable: %s", exc)
        return 1

    from flux_tray.ui.application import FluxTrayApplication
    return int(FluxTrayApplication().run(sys.argv))


if __name__ == "__main__":
    raise SystemExit(main())
