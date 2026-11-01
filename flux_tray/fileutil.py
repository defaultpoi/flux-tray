"""Writing a file so that a reader never sees half of it."""

import os
import uuid


def write_atomic(path, write):
    """Calls `write(f)` with a new temp file beside `path` and renames it into
    place, so a reader never sees a half-written file and two writers (two
    threads, or a new instance starting while the old one exits) never share a
    temp file. The temp file is removed if anything fails; the error is raised."""
    tmp = f'{path}.{uuid.uuid4().hex}.tmp'
    try:
        with open(tmp, 'x', encoding='utf-8') as f:
            write(f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
