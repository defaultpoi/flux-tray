"""Small, GTK-independent layout helpers."""

def clamp_scroll_value(value: float, lower: float, upper: float, page_size: float) -> float:
    """Keep a saved scroll position within the current adjustment bounds."""
    return min(max(value, lower), max(lower, upper - page_size))
