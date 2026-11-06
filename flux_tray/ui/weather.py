"""Weather bar, alerts and their pulsing."""

import threading

from ..gi_env import GLib, Gtk
from ..config import (
    _disable_weather_alerts,
    _update_weather_region_cache,
    load_weather_refresh_interval,
    load_weather_settings,
)
from ..constants import WEATHER_GLYPH_COLOR
from ..network import run_when_online
from ..weather import (
    fetch_meteoalarm_alerts,
    fetch_weather,
    glyph_rise_units,
    mono_glyph_markup,
    reverse_geocode_region,
    weather_code_glyph,
    weather_row_pad,
    _map_alerts_to_forecast_days,
)


# ISO 3166-1 alpha-2 codes of the countries MeteoAlarm publishes feeds for.
# Anywhere else (reverse-geocoded country_code not in here) alerts are
# switched off in config.conf, since there's no feed to poll.
METEOALARM_COUNTRY_CODES = frozenset({
    'AT', 'BA', 'BE', 'BG', 'CH', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI',
    'FR', 'GB', 'GR', 'HR', 'HU', 'IE', 'IL', 'IS', 'IT', 'LT', 'LU', 'LV',
    'MD', 'ME', 'MK', 'MT', 'NL', 'NO', 'PL', 'PT', 'RO', 'RS', 'SE', 'SI',
    'SK', 'UA',
})


WEATHER_BULLET_MARKUP = '<span size="large"><b>·</b></span>'  # between weather-bar values


ALERT_SEVERITY_RANK = {'yellow': 1, 'orange': 2, 'red': 3}


# (bright, dim) hex pairs for weather-bar text/glyph coloring, and (bright, dim)
# RGBA tuples for the tray badge, per awareness color.
ALERT_TEXT_COLORS = {
    'yellow': ('#c9a600', '#6b5800'),
    'orange': ('#d97300', '#6b3900'),
    'red': ('#cc0000', '#7a1414'),
}


class WeatherMixin:
    def initial_weather_check(self):
        run_when_online(self.start_weather_fetch)
        return False

    def periodic_weather_check(self):
        self.start_weather_fetch()
        # re-arm with the interval currently in config.conf (edits apply without a restart)
        GLib.timeout_add_seconds(load_weather_refresh_interval(), self.periodic_weather_check)
        return False

    def start_weather_fetch(self):
        threading.Thread(target=self._fetch_weather_bg, daemon=True).start()

    def _fetch_weather_bg(self):
        data = fetch_weather()
        alerts = self._fetch_alerts_bg()
        if data is None and load_weather_settings()['lat'] is not None:
            self.note_request_failure()  # configured, yet nothing came back
        GLib.idle_add(self._on_weather_fetched, data, alerts)

    def _fetch_alerts_bg(self):
        """Fetches active MeteoAlarm alerts for the country/region in
        config.conf, resolving them from the coordinates (once) if they are
        missing. Returns None on failure (caller keeps the previous alerts),
        [] if alerts are disabled or the region genuinely has nothing active."""
        settings = load_weather_settings()
        if not settings['alerts_enabled'] or settings['lat'] is None or settings['lon'] is None:
            return []
        country, region = settings['country'], settings['region']
        if not (country and region):
            resolved = reverse_geocode_region(settings['lat'], settings['lon'])
            if not resolved:
                return None  # lookup failed; retried on the next poll
            country, region, code = resolved
            if code and code not in METEOALARM_COUNTRY_CODES:
                _disable_weather_alerts()  # no MeteoAlarm feed for this country
                return []
            if not (country and region):
                return None
            _update_weather_region_cache(region, country)
        return fetch_meteoalarm_alerts(region, country)

    def _on_weather_fetched(self, data, alerts=None):
        if data is not None:
            self.weather_data = data
        if alerts is not None:
            self.active_alerts = alerts
        self.rebuild_weather_bar()
        self._refit_open_popup()  # new values can need a wider or narrower popup
        self.update_icon()
        return False

    def has_active_alerts(self):
        return bool(self.active_alerts)

    def _segment_alert_colors(self):
        """{segment_key: color_name}, using the worst-severity alert
        targeting each segment when more than one does."""
        info = {}
        for a in self.active_alerts:
            seg = a.get('segment')
            if not seg:
                continue
            color = a.get('severity_color', 'yellow')
            if seg not in info or ALERT_SEVERITY_RANK[color] > ALERT_SEVERITY_RANK[info[seg]]:
                info[seg] = color
        return info

    def _worst_alert_color(self):
        """Worst alert severity among *currently active* alerts (for tray icon)."""
        colors = [a.get('severity_color', 'yellow') for a in self.active_alerts]
        if not colors:
            return None
        return max(colors, key=lambda c: ALERT_SEVERITY_RANK.get(c, 0))

    def _worst_forecast_alert_color(self):
        """Worst alert severity among alerts overlapping the 5-day forecast period.
        The forward arrow leads to the forecast view, so its color should reflect
        what the user will see there."""
        d = self.weather_data
        if not d:
            return None
        daily_dates = d.get('daily_dates', [])
        if not daily_dates:
            return None
        alert_map = _map_alerts_to_forecast_days(self.active_alerts, daily_dates)
        if not alert_map:
            return None
        colors = [info['color'] for info in alert_map.values()]
        return max(colors, key=lambda c: ALERT_SEVERITY_RANK.get(c, 0))

    def _pulse_on_for(self, color_name):
        """Whether `color_name`'s pulse is in its bright phase right now.
        Extreme (red) flips every tick (the base/fastest rate); severe
        (orange) flips half as often; moderate (yellow) a quarter as often
        -- all derived from one shared counter/timer rather than separate
        timers per color."""
        c = self._alert_pulse_counter
        if color_name == 'red':
            return (c % 2) == 0
        if color_name == 'orange':
            return (c % 4) < 2
        return (c % 8) < 4  # yellow

    def _pulse_signature(self):
        """Bright/dim phase of every alert colour in play; changes only when
        something visible would actually change."""
        colors = {a.get('severity_color', 'yellow') for a in self.active_alerts}
        return tuple(self._pulse_on_for(c) for c in sorted(colors))

    def _alert_pulse_tick(self):
        self._alert_pulse_counter += 1
        if self.has_active_alerts():
            signature = self._pulse_signature()
            if signature != self._last_pulse_signature:  # yellow/orange flip far less often than red
                self._last_pulse_signature = signature
                self.update_icon()
                # Only rebuild on pulse if showing 'today' view (forecast glyphs don't pulse)
                if self.popup and self.popup.get_visible() and self.weather_view == 'today':
                    self.rebuild_weather_bar()
        return True

    def build_forecast_weather_segments(self):
        """Returns one markup segment per forecast day (rain glyph + high/low),
        or [] if there's no forecast. Rendered by rebuild_weather_bar exactly
        like the 'today' segments: spread across the bar, bullet-separated.
        Glyphs are colored by overlapping alert severity."""
        d = self.weather_data
        if not d:
            return []

        # Map active alerts to forecast days
        daily_dates = d.get('daily_dates', [])
        alert_map = _map_alerts_to_forecast_days(self.active_alerts, daily_dates) if daily_dates else {}

        segments = []
        # Store tooltips for later application on label widgets
        self._forecast_tooltips = []
        pad = weather_row_pad(getattr(self, 'weather_box', None))
        for day_idx, day in enumerate(d.get('forecast_days', [])):
            segment = ''
            glyph_markup = ''
            # Determine glyph: rain glyph if rain_prob > 0, else weather glyph from code
            glyph = None
            if day.get('rain_prob') is not None and day['rain_prob'] > 0:
                glyph = '☔'  # umbrella
            # Check for alert coloring on this day
            alert_info = alert_map.get(day_idx)
            if alert_info:
                color_name = alert_info['color']
                bright, _ = ALERT_TEXT_COLORS[color_name]
                glyph_color = bright
                # Store tooltip for this segment index
                tooltip = '\n'.join(alert_info['titles'])
                self._forecast_tooltips.append(tooltip)
            else:
                glyph_color = WEATHER_GLYPH_COLOR
                self._forecast_tooltips.append(None)

            if glyph:
                glyph_markup = mono_glyph_markup(glyph, glyph_color) + ' '

            if day.get('max_temp') is not None and day.get('min_temp') is not None:
                segment += GLib.markup_escape_text(
                    f"{day['max_temp']:.0f}/{day['min_temp']:.0f}°C"
                )
            if segment:
                segments.append(f'<span size="large"><b>{glyph_markup}{segment}{pad}</b></span>')
        return segments
    def build_today_weather_segments(self):
        """Returns a list of independently-markup'd segments (temp, high/low,
        wind, rain) for the 'today' view — rendered as separate widgets so
        they can be evenly spaced across the full row, bullet-separated."""
        d = self.weather_data
        if not d:
            return []
        seg_colors = self._segment_alert_colors()

        def colorize(text, segment):
            color_name = seg_colors.get(segment)
            if not color_name:
                return text
            bright, dim = ALERT_TEXT_COLORS[color_name]
            hexcolor = bright if self._pulse_on_for(color_name) else dim
            return f'<span foreground="{hexcolor}">{text}</span>'

        segments = []
        glyph = weather_code_glyph(d.get('weather_code'))
        widget = getattr(self, 'weather_box', None)
        rise = glyph_rise_units(glyph, widget) if glyph else 0
        pad = weather_row_pad(widget)
        if d.get('temp') is not None:
            temp_text = GLib.markup_escape_text(f"{d['temp']:.0f}°C")
            if glyph:
                glyph_color_name = seg_colors.get('glyph')
                if glyph_color_name:
                    bright, dim = ALERT_TEXT_COLORS[glyph_color_name]
                    glyph_color = bright if self._pulse_on_for(glyph_color_name) else dim
                else:
                    glyph_color = WEATHER_GLYPH_COLOR
                temp_text = mono_glyph_markup(glyph, glyph_color, rise) + ' ' + temp_text
            segments.append(f'<span size="large"><b>{temp_text}{pad}</b></span>')
        if d.get('today_max_temp') is not None and d.get('today_min_temp') is not None:
            hi_lo = colorize(GLib.markup_escape_text(
                f"{d['today_max_temp']:.0f}/{d['today_min_temp']:.0f}°C"
            ), 'hilo')
            segments.append(f'<span size="large"><b>{hi_lo}{pad}</b></span>')
        if d.get('wind') is not None and d.get('today_max_wind') is not None:
            wind_text = colorize(GLib.markup_escape_text(
                f"{d['wind']:.0f}/{d['today_max_wind']:.0f} km/h"
            ), 'wind')
            segments.append(f'<span size="large"><b>{wind_text}{pad}</b></span>')
        elif d.get('wind') is not None:
            wind_text = colorize(GLib.markup_escape_text(f"{d['wind']:.0f} km/h"), 'wind')
            segments.append(f'<span size="large"><b>{wind_text}{pad}</b></span>')
        prob, precip = d.get('today_rain_prob'), d.get('today_precip_sum')
        if prob is not None:
            if round(prob) == 0 and precip is not None:
                rain = f"{precip:.1f}mm"  # 0% chance: just the amount, no "0%/"
            elif precip is not None:
                rain = f"{prob:.0f}%/{precip:.1f}mm"
            else:
                rain = f"{prob:.0f}%"
            rain_text = colorize(GLib.markup_escape_text(rain), 'rain')
            segments.append(f'<span size="large"><b>{rain_text}{pad}</b></span>')
        return segments

    def _build_weather_row(self, segments, empty_markup):
        """Spreads `segments` evenly across the bar's full width with a bullet
        between each pair; shared by the 'today' and 'forecast' views so
        they look identical."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.set_hexpand(True)
        row.set_valign(Gtk.Align.CENTER)
        # Align the values on their text baselines (not by box edges): the raised
        # glyph makes the first label taller, which otherwise shifts its text.
        row.set_baseline_position(Gtk.BaselinePosition.CENTER)
        if not segments:
            segments, separate = [empty_markup], False
        else:
            separate = True
        for n, seg in enumerate(segments):
            if separate and n > 0:
                bullet = Gtk.Label()
                bullet.set_markup(WEATHER_BULLET_MARKUP)
                bullet.set_valign(Gtk.Align.BASELINE)
                row.pack_start(bullet, False, False, 0)
            lbl = Gtk.Label()
            lbl.set_markup(seg)
            lbl.set_hexpand(True)
            lbl.set_xalign(0.5)
            lbl.set_valign(Gtk.Align.BASELINE)
            # Apply tooltip for forecast view segments
            if (self.weather_view == 'forecast' and hasattr(self, '_forecast_tooltips')
                    and n < len(self._forecast_tooltips) and self._forecast_tooltips[n]):
                lbl.set_tooltip_text(self._forecast_tooltips[n])
            row.pack_start(lbl, True, True, 0)
        return row

    def rebuild_weather_bar(self):
        if self.weather_box is None:
            return
        for child in self.weather_box.get_children():
            self.weather_box.remove(child)

        if self.weather_view == 'forecast':
            pad = weather_row_pad(self.weather_box)
            empty = (f'<span size="large">Weather unavailable{pad}</span>' if not self.weather_data
                     else f'<span size="large">Forecast unavailable{pad}</span>')
            row = self._build_weather_row(self.build_forecast_weather_segments(), empty)
            self.weather_box.pack_start(row, True, True, 0)

            # the same slot as the forward arrow, so the button stays under the pointer
            back_btn = Gtk.Button(label='‹')
            back_btn.set_tooltip_text('Back to today')
            back_btn.connect('clicked', self.on_weather_arrow_clicked, 'today')
            back_btn.set_valign(Gtk.Align.CENTER)
            self.weather_box.pack_start(back_btn, False, False, 0)
        else:
            row = self._build_weather_row(
                self.build_today_weather_segments(),
                f'<span size="large">Weather unavailable{weather_row_pad(self.weather_box)}</span>')
            self.weather_box.pack_start(row, True, True, 0)

            fwd_btn = Gtk.Button(label='›')
            fwd_btn.set_tooltip_text('Show 5-day forecast')
            fwd_btn.connect('clicked', self.on_weather_arrow_clicked, 'forecast')
            fwd_btn.set_valign(Gtk.Align.CENTER)
            # Color the forward arrow button background by worst alert severity in forecast period
            worst_color = self._worst_forecast_alert_color()
            if worst_color:
                bright, _ = ALERT_TEXT_COLORS[worst_color]
                fwd_btn.get_style_context().add_class('weather-alert-btn')
                css = f'''
                    .weather-alert-btn {{
                        background: {bright};
                        background-color: {bright};
                        background-image: none;
                        color: white;
                        border: none;
                        border-radius: 4px;
                    }}
                '''
                provider = Gtk.CssProvider()
                provider.load_from_data(css.encode())
                context = fwd_btn.get_style_context()
                context.add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.weather_box.pack_start(fwd_btn, False, False, 0)

        self.weather_box.show_all()

    def on_weather_arrow_clicked(self, _button, target_view):
        self.weather_view = target_view
        self.rebuild_weather_bar()

    def _should_show_weather_icon(self, count):
        return (
            count == 0 and not self.has_pkg_update() and not self.has_active_alerts()
            and self.weather_data and self.weather_data.get('temp') is not None
        )

    def format_weather_tooltip_text(self):
        """Plain-text version of the popup's 'today' weather line, for the
        tray icon's tooltip (which doesn't render Pango markup)."""
        d = self.weather_data
        if not d:
            return "Weather unavailable"
        parts = []
        if d.get('temp') is not None:
            parts.append(f"{d['temp']:.0f}°C")
        if d.get('today_max_temp') is not None and d.get('today_min_temp') is not None:
            parts.append(f"{d['today_max_temp']:.0f}/{d['today_min_temp']:.0f}°C")
        if d.get('wind') is not None and d.get('today_max_wind') is not None:
            parts.append(f"{d['wind']:.0f}/{d['today_max_wind']:.0f} km/h")
        elif d.get('wind') is not None:
            parts.append(f"{d['wind']:.0f} km/h")
        if d.get('today_rain_prob') is not None and d.get('today_precip_sum') is not None:
            parts.append(f"{d['today_rain_prob']:.0f}%/{d['today_precip_sum']:.1f}mm")
        elif d.get('today_rain_prob') is not None:
            parts.append(f"{d['today_rain_prob']:.0f}%")
        return " · ".join(parts) if parts else "Weather unavailable"
