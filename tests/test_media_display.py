from flux_tray.core.process import ProcessResult
from flux_tray.media.display import XrandrDisplay


def test_xrandr_uses_connected_monitor_height():
    output = """Screen 0: minimum 8 x 8, current 1920 x 1080, maximum 32767 x 32767
eDP-1 connected primary 1366x768+0+0 (normal left inverted right x axis y axis)
HDMI-1 connected 1920x1080+1366+0 (normal left inverted right x axis y axis)
DP-1 disconnected (normal left inverted right x axis y axis)
"""
    display = XrandrDisplay(runner=lambda argv, **kwargs: ProcessResult(tuple(argv), 0, output, ""))
    assert display.screen_height() == 768


def test_xrandr_returns_none_when_no_monitor_mode_is_available():
    display = XrandrDisplay(runner=lambda argv, **kwargs: ProcessResult(tuple(argv), 0,
        "eDP-1 connected (normal left inverted right x axis y axis)\n", ""))
    assert display.screen_height() is None


def test_xrandr_returns_primary_monitor_dimensions():
    output = """eDP-1 connected primary 1366x768+0+0 (normal left inverted right x axis y axis)
HDMI-1 connected 1920x1080+1366+0 (normal left inverted right x axis y axis)
"""
    display = XrandrDisplay(runner=lambda argv, **kwargs: ProcessResult(
        tuple(argv), 0, output, ""
    ))
    assert display.screen_size() == (1366, 768)
