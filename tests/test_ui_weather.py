import unittest
from unittest import mock

from facade import rt


class TestForecastSegments(unittest.TestCase):
    class Stub:
        build_forecast_weather_segments = rt.FluxTray.build_forecast_weather_segments

    def _segments(self, weather_data):
        s = self.Stub()
        s.weather_data = weather_data
        with mock.patch.object(rt.GLib, 'markup_escape_text', side_effect=lambda x: x):
            return s.build_forecast_weather_segments()

    def test_no_data_or_no_days_is_empty(self):
        self.assertEqual(self._segments(None), [])
        self.assertEqual(self._segments({'forecast_days': []}), [])

    def test_one_segment_per_day_with_rain_glyph_only_when_rain_likely(self):
        segs = self._segments({'forecast_days': [
            {'max_temp': 21.4, 'min_temp': 9.6, 'rain_prob': 40},
            {'max_temp': 18.0, 'min_temp': 7.0, 'rain_prob': 0},
        ]})
        self.assertEqual(len(segs), 2)
        self.assertIn('☔', segs[0])
        self.assertIn('21/10°C', segs[0])
        self.assertNotIn('☔', segs[1])
        self.assertIn('18/7°C', segs[1])

    def test_day_without_any_values_is_skipped(self):
        segs = self._segments({'forecast_days': [
            {'max_temp': None, 'min_temp': None, 'rain_prob': None},
            {'max_temp': 5.0, 'min_temp': 1.0, 'rain_prob': None},
        ]})
        self.assertEqual(len(segs), 1)


class TestPulseRedraws(unittest.TestCase):
    class Stub:
        _alert_pulse_tick = rt.FluxTray._alert_pulse_tick
        _pulse_signature = rt.FluxTray._pulse_signature
        _pulse_on_for = rt.FluxTray._pulse_on_for
        has_active_alerts = rt.FluxTray.has_active_alerts

        def __init__(self, colors):
            self.active_alerts = [{'severity_color': c} for c in colors]
            self._alert_pulse_counter = 0
            self._last_pulse_signature = None
            self.updates = 0
            self.popup = None

        def update_icon(self):
            self.updates += 1

    def test_yellow_redraws_only_when_its_phase_flips(self):
        stub = self.Stub(['yellow'])
        for _ in range(8):
            stub._alert_pulse_tick()
        self.assertEqual(stub.updates, 3)  # ticks 1, 4 and 8, not all eight

    def test_red_flips_every_tick(self):
        stub = self.Stub(['red'])
        for _ in range(8):
            stub._alert_pulse_tick()
        self.assertEqual(stub.updates, 8)

    def test_no_alerts_no_redraws(self):
        stub = self.Stub([])
        for _ in range(8):
            stub._alert_pulse_tick()
        self.assertEqual(stub.updates, 0)


class TestMonoGlyph(unittest.TestCase):
    def test_markup(self):
        m = rt.mono_glyph_markup('\u2614')
        self.assertIn('\u2614\ufe0e', m)
        self.assertIn('foreground="#2b2b2b"', m)
        self.assertIn('font_family=', m)

    def test_forecast_umbrella_is_monochrome(self):
        class Stub:
            build_forecast_weather_segments = rt.FluxTray.build_forecast_weather_segments
            weather_data = {'forecast_days': [{'max_temp': 5.0, 'min_temp': 1.0, 'rain_prob': 50}]}
        with mock.patch.object(rt.GLib, 'markup_escape_text', side_effect=lambda x: x):
            seg = Stub().build_forecast_weather_segments()[0]
        self.assertIn('\u2614\ufe0e', seg)



class TestWeatherArrowStaysInPlace(unittest.TestCase):
    class Stub:
        rebuild_weather_bar = rt.FluxTray.rebuild_weather_bar
        on_weather_arrow_clicked = rt.FluxTray.on_weather_arrow_clicked
        _worst_alert_color = lambda self: None  # No alerts by default
        _worst_forecast_alert_color = lambda self: None  # No forecast alerts by default

        def __init__(self, view):
            self.weather_view = view
            self.weather_data = {'forecast_days': []}
            self.weather_box = mock.Mock()
            self.weather_box.get_children.return_value = []
            self.row = object()
            self.build_forecast_weather_segments = lambda: []
            self.build_today_weather_segments = lambda: []
            self._build_weather_row = lambda segments, empty: self.row

    def rebuilt(self, view):
        stub, buttons = self.Stub(view), []
        with mock.patch.object(rt, 'Gtk') as gtk, mock.patch.object(rt, 'weather_row_pad', return_value=''):
            gtk.Button.side_effect = lambda label=None: buttons.append(mock.Mock(label=label)) or buttons[-1]
            stub.rebuild_weather_bar()
        packed = [call.args[0] for call in stub.weather_box.pack_start.call_args_list]
        return stub, buttons, packed

    def test_the_arrow_is_the_last_thing_in_the_bar_in_both_views(self):
        for view, label in (('today', '\u203a'), ('forecast', '\u2039')):
            stub, buttons, packed = self.rebuilt(view)
            self.assertEqual([b.label for b in buttons], [label])
            self.assertEqual(packed, [stub.row, buttons[0]])  # row first, arrow at the end

    def test_each_arrow_switches_to_the_other_view(self):
        for view, target in (('today', 'forecast'), ('forecast', 'today')):
            stub, buttons, _ = self.rebuilt(view)
            buttons[0].connect.assert_called_once_with('clicked', stub.on_weather_arrow_clicked, target)



class TestWeatherFetchedRefitsThePopup(unittest.TestCase):
    class Stub:
        _on_weather_fetched = rt.FluxTray._on_weather_fetched

        def __init__(self):
            self.calls = []
            self.weather_data = None
            self.active_alerts = []
            self.rebuild_weather_bar = lambda: self.calls.append('bar')
            self._refit_open_popup = lambda: self.calls.append('refit')
            self.update_icon = lambda: self.calls.append('icon')

    def test_new_values_refit_an_open_popup_after_the_bar_is_rebuilt(self):
        stub = self.Stub()
        self.assertFalse(stub._on_weather_fetched({'temp': 1}))
        self.assertEqual(stub.weather_data, {'temp': 1})
        self.assertEqual(stub.calls, ['bar', 'refit', 'icon'])


class TestForecastAlertGlyphColoring(unittest.TestCase):
    """Test that forecast day glyphs are colored by overlapping alert severity."""

    class Stub:
        build_forecast_weather_segments = rt.FluxTray.build_forecast_weather_segments
        _map_alerts_to_forecast_days = rt._map_alerts_to_forecast_days

        def __init__(self, weather_data, alerts=None):
            self.weather_data = weather_data
            self.active_alerts = alerts or []

    def _segments(self, weather_data, alerts=None):
        s = self.Stub(weather_data, alerts)
        with mock.patch.object(rt.GLib, 'markup_escape_text', side_effect=lambda x: x):
            return s.build_forecast_weather_segments()

    def test_forecast_glyph_colored_by_alert(self):
        """Day with overlapping alert shows glyph in alert color."""
        weather_data = {
            'forecast_days': [
                {'max_temp': 20.0, 'min_temp': 10.0, 'rain_prob': 50},
                {'max_temp': 18.0, 'min_temp': 8.0, 'rain_prob': 0},
            ],
            'daily_dates': [
                rt.datetime(2026, 9, 30, tzinfo=rt.timezone.utc),
                rt.datetime(2026, 10, 1, tzinfo=rt.timezone.utc),
            ],
        }
        alerts = [{
            'hazard': 'Wind',
            'severity_color': 'red',
            'onset': rt.datetime(2026, 9, 30, 6, tzinfo=rt.timezone.utc),
            'expires': rt.datetime(2026, 9, 30, 18, tzinfo=rt.timezone.utc),
            'title': 'Red Wind Warning issued for Country - Region',
        }]
        segs = self._segments(weather_data, alerts)
        # First day (index 0 in forecast_days) should have red glyph
        self.assertIn('foreground="#cc0000"', segs[0])  # bright red
        self.assertIn('☔︎', segs[0])  # rain glyph
        # Second day should not be colored (no alert overlap)
        self.assertNotIn('foreground="#cc0000"', segs[1])

    def test_forecast_glyph_tooltip_has_alert_title(self):
        """Forecast day glyph has tooltip with alert description on hover."""
        weather_data = {
            'forecast_days': [
                {'max_temp': 20.0, 'min_temp': 10.0, 'rain_prob': 50},
            ],
            'daily_dates': [
                rt.datetime(2026, 9, 30, tzinfo=rt.timezone.utc),
            ],
        }
        alerts = [{
            'hazard': 'Wind',
            'severity_color': 'orange',
            'onset': rt.datetime(2026, 9, 30, 6, tzinfo=rt.timezone.utc),
            'expires': rt.datetime(2026, 9, 30, 18, tzinfo=rt.timezone.utc),
            'title': 'Orange Wind Warning issued for Country - Region. Wind gusts will reach 50-70 km/h.',
        }]
        s = self.Stub(weather_data, alerts)
        with mock.patch.object(rt.GLib, 'markup_escape_text', side_effect=lambda x: x):
            segs = s.build_forecast_weather_segments()
        # Tooltip is stored on _forecast_tooltips for later application on label widget
        self.assertTrue(hasattr(s, '_forecast_tooltips'))
        self.assertEqual(len(s._forecast_tooltips), 1)
        self.assertIn('Wind gusts will reach 50-70 km/h', s._forecast_tooltips[0])

    def test_forecast_multiple_alerts_worst_severity(self):
        """When multiple alerts overlap a day, glyph uses worst severity color."""
        weather_data = {
            'forecast_days': [
                {'max_temp': 20.0, 'min_temp': 10.0, 'rain_prob': 50},
            ],
            'daily_dates': [
                rt.datetime(2026, 9, 30, tzinfo=rt.timezone.utc),
            ],
        }
        alerts = [
            {
                'hazard': 'Wind',
                'severity_color': 'yellow',
                'onset': rt.datetime(2026, 9, 30, 6, tzinfo=rt.timezone.utc),
                'expires': rt.datetime(2026, 9, 30, 18, tzinfo=rt.timezone.utc),
                'title': 'Yellow Wind Warning...',
            },
            {
                'hazard': 'Rain',
                'severity_color': 'red',
                'onset': rt.datetime(2026, 9, 30, 12, tzinfo=rt.timezone.utc),
                'expires': rt.datetime(2026, 10, 1, 12, tzinfo=rt.timezone.utc),
                'title': 'Red Rain Warning...',
            },
        ]
        s = self.Stub(weather_data, alerts)
        with mock.patch.object(rt.GLib, 'markup_escape_text', side_effect=lambda x: x):
            segs = s.build_forecast_weather_segments()
        # Should use red (worst)
        self.assertIn('foreground="#cc0000"', segs[0])
        # Tooltip should include both titles (stored in _forecast_tooltips)
        self.assertTrue(hasattr(s, '_forecast_tooltips'))
        self.assertIn('Yellow Wind Warning', s._forecast_tooltips[0])
        self.assertIn('Red Rain Warning', s._forecast_tooltips[0])

    def test_forecast_no_alert_no_coloring(self):
        """Forecast day without overlapping alert uses default glyph color."""
        weather_data = {
            'forecast_days': [
                {'max_temp': 20.0, 'min_temp': 10.0, 'rain_prob': 50},
            ],
            'daily_dates': [
                rt.datetime(2026, 9, 30, tzinfo=rt.timezone.utc),
            ],
        }
        segs = self._segments(weather_data, [])
        # Default glyph color
        self.assertIn(f'foreground="{rt.WEATHER_GLYPH_COLOR}"', segs[0])
        self.assertNotIn('tooltip=', segs[0])


class TestTodayArrowButtonBackground(unittest.TestCase):
    """Test that the forward arrow button in today view has alert-colored background
    based on forecast-period alerts."""

    class Stub:
        rebuild_weather_bar = rt.FluxTray.rebuild_weather_bar
        _worst_forecast_alert_color = rt.FluxTray._worst_forecast_alert_color
        _segment_alert_colors = rt.FluxTray._segment_alert_colors
        _pulse_on_for = rt.FluxTray._pulse_on_for
        _alert_pulse_counter = 0
        on_weather_arrow_clicked = rt.FluxTray.on_weather_arrow_clicked
        build_today_weather_segments = rt.FluxTray.build_today_weather_segments
        build_forecast_weather_segments = rt.FluxTray.build_forecast_weather_segments
        _build_weather_row = rt.FluxTray._build_weather_row
        weather_row_pad = staticmethod(rt.weather_row_pad)

        def __init__(self, alerts=None):
            self.active_alerts = alerts or []
            self.weather_view = 'today'
            self.weather_data = {
                'temp': 15.0, 'weather_code': 0, 'today_max_temp': 20.0, 'today_min_temp': 10.0,
                # daily_dates contains only forecast days (1-5), matching forecast_days indices
                'daily_dates': [
                    rt.datetime(2026, 9, 30, tzinfo=rt.timezone.utc),  # day 1 (tomorrow)
                    rt.datetime(2026, 10, 1, tzinfo=rt.timezone.utc),  # day 2
                    rt.datetime(2026, 10, 2, tzinfo=rt.timezone.utc),  # day 3
                    rt.datetime(2026, 10, 3, tzinfo=rt.timezone.utc),  # day 4
                    rt.datetime(2026, 10, 4, tzinfo=rt.timezone.utc),  # day 5
                ],
            }
            # Mock weather_box with proper font description for glyph_rise_units
            self.weather_box = mock.Mock()
            self.weather_box.get_children.return_value = []
            pango_context = mock.Mock()
            font_desc = mock.Mock()
            font_desc.get_size.return_value = 10 * 1024  # 10pt in Pango units
            pango_context.get_font_description.return_value = font_desc
            self.weather_box.get_pango_context.return_value = pango_context

    def _rebuild(self, alerts):
        stub = self.Stub(alerts)
        buttons = []
        css_providers = []
        with mock.patch.object(rt, 'Gtk') as gtk:
            gtk.Button.side_effect = lambda label=None: buttons.append(mock.Mock(label=label)) or buttons[-1]
            # Track CssProvider creation
            def track_css_provider():
                provider = mock.Mock()
                css_providers.append(provider)
                return provider
            gtk.CssProvider.side_effect = track_css_provider
            stub.rebuild_weather_bar()
        return buttons, css_providers

    def _alert(self, severity, day_index=0, duration_days=1):
        """Create a mock alert overlapping a forecast day (day_index 0=day1, 1=day2, etc.)."""
        base = rt.datetime(2026, 9, 30, 6, tzinfo=rt.timezone.utc)  # day 1
        onset = base + rt.timedelta(days=day_index)
        expires = onset + rt.timedelta(days=duration_days)
        return {
            'hazard': 'Wind',
            'severity_color': severity,
            'onset': onset,
            'expires': expires,
            'title': f'{severity.capitalize()} Wind Warning issued for Country - Region',
        }

    def test_arrow_button_background_colored_by_worst_forecast_alert(self):
        """Forward arrow button background uses worst forecast alert severity color."""
        alerts = [
            self._alert('yellow', day_index=0),  # overlaps day 1
            self._alert('red', day_index=1),     # overlaps day 2
        ]
        buttons, css_providers = self._rebuild(alerts)
        # The forward arrow button (›) should have background color from worst forecast alert (red)
        fwd_btn = buttons[0]
        self.assertEqual(fwd_btn.label, '›')
        # Check that CSS provider was created and added to button's style context
        self.assertEqual(len(css_providers), 1)
        # Verify the CSS contains the red background color
        css_provider = css_providers[0]
        css_provider.load_from_data.assert_called()
        css_arg = css_provider.load_from_data.call_args[0][0].decode()
        self.assertIn('#cc0000', css_arg)  # bright red
        self.assertIn('color: white', css_arg)

    def test_arrow_button_no_forecast_alert_no_background_color(self):
        """Forward arrow button has no special background when no forecast alerts."""
        # Current alerts that don't overlap forecast days (today only)
        alerts = [
            {'severity_color': 'red', 'onset': rt.datetime(2026, 9, 29, 6, tzinfo=rt.timezone.utc),
             'expires': rt.datetime(2026, 9, 29, 18, tzinfo=rt.timezone.utc),  # today only
             'hazard': 'Wind', 'title': 'Red Wind Warning...'},
        ]
        buttons, css_providers = self._rebuild(alerts)
        fwd_btn = buttons[0]
        self.assertEqual(fwd_btn.label, '›')
        # No CSS provider should be created when no forecast alerts
        self.assertEqual(len(css_providers), 0)


if __name__ == '__main__':
    unittest.main()
