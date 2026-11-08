"""Tray icon drawing and badge state."""

import functools
import math
import re

from ..gi_env import Gdk, cairo
from ..ui.weather import ALERT_SEVERITY_RANK


ALERT_BADGE_COLORS = {
    'yellow': ((0.90, 0.75, 0.0, 1), (0.55, 0.46, 0.0, 1)),
    'orange': ((0.90, 0.45, 0.0, 1), (0.55, 0.28, 0.0, 1)),
    'red': ((0.90, 0.05, 0.05, 1), (0.50, 0.05, 0.05, 1)),
}


# The tray icon draws the degree sign as a small stroked ring (a text glyph
# would be too tiny/blurry at 24px and would eat into the digits' width).
TEMP_RING_RADIUS = 1.0


TEMP_RING_LINE_WIDTH = 1.0


# Hazard icons, paths on a 64x64 viewBox (scaled to the icon): "wind" and "rain" are
# MeteoAlarm's own icons (their licence has not been checked); "thunderstorm" (a bolt),
# "rain-flood" (waves) and the fallback ring were drawn for this app.
METEOALARM_ICONS = {
    'wind': [
        # Main wind shape
        "M38.7247219,30.9917676 L1.37614506,30.9917676 C0.616121128,30.9917676 0,30.3864294 0,29.6397069 C0,28.8929844 0.616121128,28.2876463 1.37614506,28.2876463 L38.972428,28.2876463 C44.1693673,28.1910091 48.3121647,23.9905221 48.2469003,18.8840245 C48.1816359,13.7775269 43.9327918,9.68056945 38.7350213,9.71217396 C33.5372509,9.74377848 29.3403433,13.8920895 29.3394126,18.9989896 C29.3394126,19.7457121 28.7232915,20.3510502 27.9632676,20.3510502 C27.2032436,20.3510502 26.5871225,19.7457121 26.5871225,18.9989896 C26.5836689,12.4292647 31.9608251,7.07969235 38.647097,7.00088057 C45.3333688,6.9220688 50.8396034,12.1433575 50.9965706,18.7112729 C51.1535378,25.2791883 45.9028021,30.748639 39.2201341,30.978247 C39.0560924,31.0016514 38.889833,31.0061889 38.7247219,30.9917676 Z",
        # Small wind shape
        "M10.8586066,19 L1.43442623,19 C0.642214498,19 0,18.3826858 0,17.6211901 C0,16.8596945 0.642214498,16.2423803 1.43442623,16.2423803 L10.7438525,16.2423803 L11.1311475,16.2423803 C14.9933991,16.2423491 18.1258276,13.2354413 18.1310823,9.52294252 C18.136337,5.81044369 15.0124321,2.79535407 11.1501949,2.785221 C7.28795766,2.77508793 4.14697644,5.77374082 4.13114754,9.4862119 C4.13114754,10.2477076 3.48893304,10.8650218 2.69672131,10.8650218 C1.90450958,10.8650218 1.26229508,10.2477076 1.26229508,9.4862119 C1.26229508,4.24712173 5.68073083,0 11.1311475,0 C16.5815643,0 21,4.24712173 21,9.4862119 C21,14.7253021 16.5815643,18.9724238 11.1311475,18.9724238 L10.8586066,19 Z",
        # Swirl
        "M26.7651007,58 C21.6678719,57.9923951 17.537594,53.7435519 17.5302013,48.5 C17.5302013,47.7373975 18.1311614,47.119186 18.8724832,47.119186 C19.613805,47.119186 20.2147651,47.7373975 20.2147651,48.5 C20.2147651,52.2215001 23.1474502,55.2383721 26.7651007,55.2383721 C30.3827511,55.2383721 33.3154362,52.2215001 33.3154362,48.5 C33.3154362,44.7784999 30.3827511,41.7616279 26.7651007,41.7616279 L1.34228188,41.7616279 C0.600960067,41.7616279 0,41.1434164 0,40.380814 C0,39.6182115 0.600960067,39 1.34228188,39 L26.7651007,39 C31.8653947,39 36,43.2532949 36,48.5 C36,53.7467051 31.8653947,58 26.7651007,58 L26.7651007,58 Z",
    ],
    'rain': [
        # Cloud shape
        "M17.006738,57 C7.61943616,57 0.00743843253,49.1494115 0,39.4601953 C0,34.36934 3.78676179,26.9416987 6.95362663,21.6422018 C8.58422513,18.8603137 10.3361078,16.2731577 11.9128022,14.1728322 C12.5319163,13.3266481 13.1931292,12.514173 13.8937772,11.7386801 C14.6459865,10.730165 15.7773249,10.0982792 17.006738,10 C18.2313291,10.1020999 19.3570882,10.7336032 20.1062228,11.7386801 C20.8107414,12.5106274 21.4721353,13.3233249 22.0871978,14.1728322 C23.8634772,16.568228 25.5187394,19.0566943 27.0463734,21.6282924 C30.2132382,26.9416987 34,34.3554306 34,39.4462859 C34,49.1355051 26.3940369,56.9923223 17.006738,57 Z M17.006738,12.7818881 C16.7506936,12.7818881 16.4137931,13.0461675 15.8343242,13.6581829 C15.2548553,14.2701983 14.7427665,14.9378514 14.0420135,15.869784 C12.5326992,17.9005623 10.7808165,20.4598994 9.24455014,23.1026931 C5.08045977,30.0852323 2.69520412,36.0384729 2.69520412,39.4601953 C2.93247185,47.438223 9.26692797,53.7787891 17,53.7787891 C24.733072,53.7787891 31.0675281,47.438223 31.3047959,39.4601953 C31.3047959,36.0384729 28.9195402,30.0852323 24.7554499,23.1026931 C23.2774594,20.6084453 21.6761909,18.1942884 19.9579865,15.869784 L19.9579865,15.869784 C19.2572335,14.9378514 18.6103845,14.1867416 18.1656758,13.6581829 C17.7209671,13.1296241 17.2493064,12.7818881 17.006738,12.7818881 Z",
        # Raindrops
        "M40.5067697,28 C34.704041,28 30,23.1586729 30,17.1865933 C30,14.7353677 31.3609805,11.2756378 33.9468436,6.91945973 C34.7835206,5.4986976 35.6920912,4.12411976 36.6688046,2.8014007 C37.8936871,1.16258129 38.8872029,0 40.4931599,0 C42.099117,0 43.0926328,1.14857429 44.3039054,2.8014007 C45.2838069,4.12175643 46.1924962,5.4965138 47.0258665,6.91945973 L47.0258665,6.91945973 C49.6389491,11.1915958 50.999965,14.7073537 50.999965,17.1585793 C51.0071572,20.0288982 49.9052568,22.7844081 47.9370154,24.8179741 C45.9687739,26.8515401 43.2957018,27.9962916 40.5067697,28 L40.5067697,28 Z M40.5067697,2.7873937 C40.3026227,2.7873937 39.9623775,2.98349175 38.8327637,4.48224112 C37.9050875,5.73441687 37.0463234,7.03911373 36.2605105,8.3901951 C33.987673,12.186093 32.7219611,15.3096548 32.7219611,17.1865933 C32.6024496,20.1263808 34.0582359,22.8970573 36.5139713,24.4036102 C38.9697067,25.9101631 42.030223,25.9101631 44.4859584,24.4036102 C46.9416938,22.8970573 48.39748,20.1263808 48.2779686,17.1865933 C48.2779686,15.3096548 47.0258665,12.186093 44.753029,8.3901951 C43.9572922,7.05143308 43.0941623,5.75635594 42.167166,4.51025513 C41.051162,2.98349175 40.697307,2.7873937 40.5067697,2.7873937 Z",
    ],
    'thunderstorm': [
        # A lightning bolt
        "M38,2 L14,36 L29,36 L22,62 L50,26 L34,26 L42,2 Z",
    ],
    'rain-flood': [
        # Three rows of waves
        "M4,14 C12,6 20,22 32,14 C44,6 52,22 60,14 L60,22 C52,30 44,14 32,22 C20,30 12,14 4,22 Z",
        "M4,30 C12,22 20,38 32,30 C44,22 52,38 60,30 L60,38 C52,46 44,30 32,38 C20,46 12,30 4,38 Z",
        "M4,46 C12,38 20,54 32,46 C44,38 52,54 60,46 L60,54 C52,62 44,46 32,54 C20,62 12,46 4,54 Z",
    ],
    # Generic alert icon for other hazards (fallback)
    'default': [
        "M32,4 C16.56,4 4,16.56 4,32 C4,47.44 16.56,60 32,60 C47.44,60 60,47.44 60,32 C60,16.56 47.44,4 32,4 Z M32,6 C46.35,6 58,17.65 58,32 C58,46.35 46.35,58 32,58 C17.65,58 6,46.35 6,32 C6,17.65 17.65,6 32,6 Z M32,14 C22.06,14 14,22.06 14,32 C14,41.94 22.06,50 32,50 C41.94,50 50,41.94 50,32 C50,22.06 41.94,14 32,14 Z",
    ],
}


_PATH_ARITY = {'M': 2, 'L': 2, 'C': 6, 'Z': 0}


@functools.lru_cache(maxsize=None)
def _parse_svg_path(path_data):
    """The commands of an SVG path of absolute M, L, C and Z as ((command, (numbers...)), ...).
    Cached: the icon is drawn at every flip of the pulse. Numbers that follow a command's
    own repeat it (as in SVG), a repeated moveto being a lineto."""
    commands = []
    tokens = re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|[A-Za-z]', path_data)
    i = 0
    while i < len(tokens):
        command = tokens[i]
        i += 1
        arity = _PATH_ARITY.get(command)
        if arity is None:
            raise ValueError(f'unexpected {command!r} in SVG path')
        if arity == 0:
            commands.append((command, ()))
            continue
        first = True
        while i < len(tokens) and tokens[i] not in _PATH_ARITY:
            numbers = tuple(float(t) for t in tokens[i:i + arity])
            if len(numbers) < arity:
                raise ValueError(f'{command} needs {arity} numbers in SVG path')
            commands.append((command if first or command != 'M' else 'L', numbers))
            first = False
            i += arity
    return tuple(commands)


def _draw_svg_path(ctx, path_data, scale_x, scale_y, offset_x=0, offset_y=0):
    """Adds an SVG path (see _parse_svg_path) to the cairo context's path, scaled and moved."""
    for command, n in _parse_svg_path(path_data):
        points = [(n[k] * scale_x + offset_x, n[k + 1] * scale_y + offset_y) for k in range(0, len(n), 2)]
        if command == 'M':
            ctx.move_to(*points[0])
        elif command == 'L':
            ctx.line_to(*points[0])
        elif command == 'C':
            ctx.curve_to(*points[0], *points[1], *points[2])
        else:
            ctx.close_path()


def _draw_meteoalarm_icon(ctx, hazard, size, color, target_height=None):
    """Draw the MeteoAlarm hazard icon at the given size and color.
    If target_height is provided, scale the icon to match that height and center vertically."""
    paths = METEOALARM_ICONS.get(hazard, METEOALARM_ICONS['default'])

    if target_height is not None:
        # Scale to 1.3x the temperature digit height for better visibility
        # The SVG viewBox is 64x64, so scale factor = target_height * 1.3 / 64
        scale = (target_height * 1.3) / 64.0
        # Center horizontally: (size - icon_width) / 2, where icon_width = 64 * scale
        icon_width = 64 * scale
        offset_x = (size - icon_width) / 2
        # Center vertically: (size - icon_height) / 2
        icon_height = 64 * scale
        offset_y = (size - icon_height) / 2
    else:
        # Original behavior: scale to full icon size
        scale = size / 64.0
        offset_x = 7 * scale
        offset_y = 3 * scale

    ctx.set_source_rgba(*color)
    for path_data in paths:
        ctx.new_path()
        _draw_svg_path(ctx, path_data, scale, scale, offset_x, offset_y)
        ctx.fill()


TEMP_RING_GAP = 0.4


TEMP_RING_RESERVE = TEMP_RING_GAP + 2 * TEMP_RING_RADIUS + TEMP_RING_LINE_WIDTH


def _fit_temperature_font(ctx, text, size, padding=1, max_font=20, min_font=10):
    """Sets the bold font of the current-temperature digits: the largest from max_font down
    whose `text` fits the width `size` leaves after `padding` and the degree ring."""
    ctx.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    max_width = size - 2 * padding - TEMP_RING_RESERVE
    font_size = max_font
    while font_size > min_font:
        ctx.set_font_size(font_size)
        if ctx.text_extents(text)[4] <= max_width:
            break
        font_size -= 1


def temp_icon_layout(size, text_width, text_height):
    """Horizontal start of the digits and centre of the degree ring so that
    digits + ring are centred together in a `size`-px icon, ring top level
    with the digits' top. Returns (digits_left, ring_cx, ring_cy)."""
    total = text_width + TEMP_RING_RESERVE
    digits_left = (size - total) / 2
    ring_outer = 2 * TEMP_RING_RADIUS + TEMP_RING_LINE_WIDTH
    ring_cx = digits_left + text_width + TEMP_RING_GAP + ring_outer / 2
    ring_cy = max(size / 2 - text_height / 2 + ring_outer / 2, ring_outer / 2)
    return digits_left, ring_cx, ring_cy


class IconMixin:
    def update_icon(self):
        count = self.total_badge_count()
        self.status_icon.set_from_pixbuf(self.render_icon(count))
        if self.schedule_warning:
            tooltip = (f"{self.schedule_warning['action']} in {self.schedule_warning['left']} s "
                       "\u2014 open the popup to cancel or snooze")
        elif self.has_active_alerts():
            # Show full alert message(s) from MeteoAlarm (summary has the details)
            messages = []
            for a in self.active_alerts:
                msg = a.get('summary') or a.get('title', '')
                if msg:
                    messages.append(msg)
            if messages:
                tooltip = '\n'.join(messages)
            else:
                hazards = ', '.join(sorted({a['hazard'] for a in self.active_alerts}))
                tooltip = f"\u26a0 {hazards} warning"
        elif self._should_show_weather_icon(count):
            tooltip = self.format_weather_tooltip_text()
        elif self.has_pkg_update():
            tooltip = f"{count} unread — package update available"
        elif count:
            tooltip = f"{count} unread"
        else:
            tooltip = "No unread items"
        self.status_icon.set_tooltip_text(tooltip)
        return False

    def _current_hazard(self):
        """Return the hazard type of the worst active alert, or None."""
        if not self.active_alerts:
            return None
        worst = max(self.active_alerts, key=lambda a: ALERT_SEVERITY_RANK.get(a.get('severity_color', 'yellow'), 0))
        return worst.get('hazard', '').lower()

    def total_badge_count(self):
        # Live channels intentionally excluded — they show in the popup list
        # and still trigger the sound/auto-popup notification, but shouldn't
        # affect the tray icon's badge number or color.
        with self.lock:
            return (
                len(self.state.get('unread', []))
                + len(self.state.get('available_updates', []))
            )

    def has_anything_to_show(self):
        with self.lock:
            return (
                bool(self.state.get('unread'))
                or bool(self.state.get('available_updates'))
                or bool(self.state.get('live_channels'))
                or bool(self.state.get('live_youtube_channels'))
            )

    def has_pkg_update(self):
        with self.lock:
            return bool(self.state.get('available_updates'))

    def render_icon(self, count):
        size = 24
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        ctx = cairo.Context(surface)

        if self.schedule_warning is not None and self._schedule_flash_on:
            # pending scheduled action: flash a red "!" every other second
            ctx.set_source_rgba(0.82, 0.12, 0.12, 1)
            ctx.arc(size / 2, size / 2, size / 2 - 1, 0, 2 * 3.14159265)
            ctx.fill()
            ctx.set_source_rgba(1, 1, 1, 1)
            ctx.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            ctx.set_font_size(18)
            xb, yb, w, h, _dx, _dy = ctx.text_extents('!')
            ctx.move_to(size / 2 - w / 2 - xb, size / 2 - h / 2 - yb)
            ctx.show_text('!')
            surface.flush()
            return Gdk.pixbuf_get_from_surface(surface, 0, 0, size, size)

        worst_alert_color = self._worst_alert_color()
        # an alert with nothing unread and nothing to update: alternate between
        # the MeteoAlarm hazard icon (in alert colour) and the temperature (white)
        alert_temperature = bool(count == 0 and worst_alert_color and self._current_temperature() is not None)

        # Calculate temperature text height for scaling the MeteoAlarm icon
        temp_text_height = 0
        if alert_temperature and self.weather_data and self.weather_data.get('temp') is not None:
            temp_text = f"{self.weather_data['temp']:.0f}"
            _fit_temperature_font(ctx, temp_text, size)
            temp_text_height = ctx.text_extents(temp_text)[3]

        if self._should_show_weather_icon(count):
            # plain weather icon (no alert): white temperature
            ctx.set_source_rgba(1, 1, 1, 1)
            self._draw_temperature(ctx, size)
        elif alert_temperature:
            # alert active, no unread: alternate icon <-> temperature
            if self._pulse_on_for(worst_alert_color):
                # bright phase: draw MeteoAlarm hazard icon in white
                hazard = self._current_hazard()
                _draw_meteoalarm_icon(ctx, hazard, size, (1, 1, 1, 1), temp_text_height)
            else:
                # dim phase: white temperature
                ctx.set_source_rgba(1, 1, 1, 1)
                self._draw_temperature(ctx, size)
        else:
            if worst_alert_color:
                bright, dim = ALERT_BADGE_COLORS[worst_alert_color]
                ctx.set_source_rgba(*(bright if self._pulse_on_for(worst_alert_color) else dim))
            elif self.has_pkg_update():
                ctx.set_source_rgba(0.82, 0.18, 0.18, 1)   # red: update available
            elif count > 0:
                ctx.set_source_rgba(0.92, 0.55, 0.10, 1)   # orange: unread news / live channel
            else:
                ctx.set_source_rgba(0.20, 0.65, 0.30, 1)   # green: nothing unread, weather not loaded yet
            ctx.arc(size / 2, size / 2, size / 2 - 1, 0, 2 * 3.14159265)
            ctx.fill()

            ctx.set_source_rgba(1, 1, 1, 1)
            text = str(count) if count < 100 else '99+'
            ctx.select_font_face('Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            ctx.set_font_size(12 if len(text) <= 2 else 8)
            xb, yb, w, h = ctx.text_extents(text)[:4]
            ctx.move_to(size / 2 - w / 2 - xb, size / 2 - h / 2 - yb)
            ctx.show_text(text)

        surface.flush()
        return Gdk.pixbuf_get_from_surface(surface, 0, 0, size, size)

    def _current_temperature(self):
        return self.weather_data.get('temp') if self.weather_data else None

    def _draw_temperature(self, ctx, size, padding=1, max_font=20, min_font=10):
        """Draws the current temperature in the current colour, the digits and
        the small degree ring centred together; the font shrinks from max_font
        until the digits fit the width left by `padding` and the ring."""
        temp_text = f"{self.weather_data['temp']:.0f}"
        _fit_temperature_font(ctx, temp_text, size, padding, max_font, min_font)

        xb, yb, tw, th, _dx, _dy = ctx.text_extents(temp_text)
        digits_left, ring_cx, ring_cy = temp_icon_layout(size, tw, th)
        ctx.move_to(digits_left - xb, size / 2 - th / 2 - yb)
        ctx.show_text(temp_text)
        ctx.set_line_width(TEMP_RING_LINE_WIDTH)
        ctx.new_sub_path()
        # snap the centre to a pixel centre so the tiny ring is drawn
        # crisp (full-intensity pixels) instead of a blurry grey dot
        ctx.arc(math.floor(ring_cx) + 0.5, math.floor(ring_cy) + 0.5,
                TEMP_RING_RADIUS, 0, 2 * 3.14159265)
        ctx.stroke()
