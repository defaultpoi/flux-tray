import pytest

from flux_tray.ui.layout import clamp_scroll_value


@pytest.mark.parametrize(
    ("saved", "lower", "upper", "page_size", "expected"),
    [
        (120, 0, 500, 100, 120),
        (450, 0, 500, 100, 400),
        (-20, 0, 500, 100, 0),
        (120, 0, 80, 100, 0),
        (25.5, 2, 100, 20, 25.5),
    ],
)
def test_clamp_scroll_value_preserves_position_within_new_bounds(
    saved, lower, upper, page_size, expected
):
    assert clamp_scroll_value(saved, lower, upper, page_size) == expected
