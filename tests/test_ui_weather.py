import unittest
from unittest import mock

from facade import rt


class TestForecastSegments(unittest.TestCase):
    class Stub:
        build_forecast_weather_segments = rt.FluxTray.build_forecast_weather_segments
        _forecast_alerts_by_day = rt.FluxTray._forecast_alerts_by_day
        active_alerts = upcoming_alerts = ()

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
            _forecast_alerts_by_day = rt.FluxTray._forecast_alerts_by_day
            active_alerts = upcoming_alerts = ()
            weather_data = {'forecast_days': [{'max_temp': 5.0, 'min_temp': 1.0, 'rain_prob': 50}]}
        with mock.patch.object(rt.GLib, 'markup_escape_text', side_effect=lambda x: x):
            seg = Stub().build_forecast_weather_segments()[0]
        self.assertIn('\u2614\ufe0e', seg)



class TestWeatherArrowStaysInPlace(unittest.TestCase):
    class Stub:
        rebuild_weather_bar = rt.FluxTray.rebuild_weather_bar
        on_weather_arrow_clicked = rt.FluxTray.on_weather_arrow_clicked
        _forecast_alerts_by_day = rt.FluxTray._forecast_alerts_by_day
        _forecast_alert_lines = staticmethod(rt.FluxTray._forecast_alert_lines)
        active_alerts = upcoming_alerts = ()

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


if __name__ == '__main__':
    unittest.main()


FORECAST = [{'max_temp': 12.0, 'min_temp': 4.0, 'rain_prob': 60}, {'max_temp': 14.0, 'min_temp': 6.0, 'rain_prob': 0},
            {'max_temp': 15.0, 'min_temp': 7.0, 'rain_prob': 30}, {'max_temp': 16.0, 'min_temp': 8.0, 'rain_prob': 0},
            {'max_temp': 13.0, 'min_temp': 5.0, 'rain_prob': 0}]


class TestAlertsOnTheForecast(unittest.TestCase):
    TODAY = rt.datetime(2026, 11, 3).date()

    class Stub:
        build_forecast_weather_segments = rt.FluxTray.build_forecast_weather_segments
        _forecast_alerts_by_day = rt.FluxTray._forecast_alerts_by_day
        _on_weather_fetched = rt.FluxTray._on_weather_fetched
        _forecast_alert_lines = staticmethod(rt.FluxTray._forecast_alert_lines)
        rebuild_weather_bar = rt.FluxTray.rebuild_weather_bar

    def stub(self, active=(), upcoming=()):
        stub = self.Stub()
        stub.weather_data = {'forecast_days': FORECAST}
        stub.active_alerts, stub.upcoming_alerts = list(active), list(upcoming)
        return stub

    def alert(self, onset, expires, color, hazard='Wind', upcoming=True):
        return {'onset': onset, 'expires': expires, 'severity_color': color, 'hazard': hazard, 'upcoming': upcoming, 'segment': 'wind'}

    def segments(self, stub):
        with mock.patch.object(rt, 'date') as date, mock.patch.object(rt.GLib, 'markup_escape_text', side_effect=lambda x: x), \
                mock.patch.object(rt, 'weather_row_pad', return_value=''):
            date.today.return_value = self.TODAY
            return stub.build_forecast_weather_segments()

    def tomorrow(self, color='yellow', hazard='Wind'):
        return self.alert('2026-11-04T06:00:00+00:00', '2026-11-04T18:00:00+00:00', color, hazard)

    def test_without_alerts_the_slide_is_exactly_what_it_was(self):
        segments = self.segments(self.stub())
        self.assertIn(rt.mono_glyph_markup('\u2614', rt.WEATHER_GLYPH_COLOR), segments[0])
        self.assertNotIn('\u26a0', ''.join(segments))
        self.assertNotIn('#c9a600', ''.join(segments))

    def test_the_glyph_of_an_alert_day_takes_the_colour_of_its_alert(self):
        segments = self.segments(self.stub(upcoming=[self.tomorrow('red')]))
        self.assertIn(rt.mono_glyph_markup('\u2614', rt.ALERT_TEXT_COLORS['red'][0]), segments[0])  # day 1 had rain: its glyph
        self.assertIn(rt.mono_glyph_markup('\u2614', rt.WEATHER_GLYPH_COLOR), segments[2])           # day 3, no alert: as before

    def test_an_alert_day_without_a_rain_glyph_gets_a_warning_glyph_in_the_colour(self):
        alert = self.alert('2026-11-05T06:00:00+00:00', '2026-11-05T18:00:00+00:00', 'orange')  # day 2, no rain
        segments = self.segments(self.stub(upcoming=[alert]))
        self.assertIn(rt.mono_glyph_markup('\u26a0', rt.ALERT_TEXT_COLORS['orange'][0]), segments[1])
        self.assertIn('14/6\u00b0C', segments[1])
        self.assertNotIn('\u26a0', segments[0] + segments[2] + segments[3] + segments[4])

    def test_each_day_has_its_own_colour(self):
        alerts = [self.tomorrow('yellow'), self.alert('2026-11-06T00:00:00+00:00', '2026-11-06T12:00:00+00:00', 'red')]
        segments = self.segments(self.stub(upcoming=alerts))
        self.assertIn(rt.mono_glyph_markup('\u2614', rt.ALERT_TEXT_COLORS['yellow'][0]), segments[0])
        self.assertIn(rt.mono_glyph_markup('\u2614', rt.ALERT_TEXT_COLORS['red'][0]), segments[2])

    def test_the_worst_alert_of_a_day_sets_the_colour(self):
        segments = self.segments(self.stub(upcoming=[self.tomorrow('yellow', 'Rain'), self.tomorrow('red', 'Wind')]))
        self.assertIn(rt.mono_glyph_markup('\u2614', rt.ALERT_TEXT_COLORS['red'][0]), segments[0])

    def test_an_alert_in_force_now_that_runs_into_tomorrow_colours_tomorrow(self):
        now = self.alert('2026-11-03T08:00:00+00:00', '2026-11-04T08:00:00+00:00', 'orange', upcoming=False)
        segments = self.segments(self.stub(active=[now]))
        self.assertIn(rt.mono_glyph_markup('\u2614', rt.ALERT_TEXT_COLORS['orange'][0]), segments[0])

    def test_the_colour_is_steady_not_pulsing(self):
        stub = self.stub(upcoming=[self.tomorrow('red')])
        stub._alert_pulse_counter = 0
        first = self.segments(stub)
        stub._alert_pulse_counter = 1
        self.assertEqual(self.segments(stub), first)

    def test_a_fetch_splits_alerts_into_in_force_and_upcoming_and_keeps_both_when_it_fails(self):
        stub = self.stub()
        stub.rebuild_weather_bar = stub._refit_open_popup = stub.update_icon = mock.Mock()
        now, later = self.alert('', '', 'red', upcoming=False), self.tomorrow()
        stub._on_weather_fetched(None, [now, later])
        self.assertEqual((stub.active_alerts, stub.upcoming_alerts), ([now], [later]))
        stub._on_weather_fetched(None, None)  # the feed could not be read: what is known stays
        self.assertEqual((stub.active_alerts, stub.upcoming_alerts), ([now], [later]))
        stub._on_weather_fetched(None, [])    # read, and nothing: both clear
        self.assertEqual((stub.active_alerts, stub.upcoming_alerts), ([], []))

    def rebuilt_toggle(self, stub, view='today'):
        stub.weather_view = view
        stub.weather_box = mock.Mock()
        stub.weather_box.get_children.return_value = []
        stub.on_weather_arrow_clicked = mock.Mock()
        stub._build_weather_row = lambda segments, empty: object()
        stub.build_today_weather_segments = stub.build_forecast_weather_segments = lambda: []
        buttons = []
        with mock.patch.object(rt, 'Gtk') as gtk, mock.patch.object(rt, 'weather_row_pad', return_value=''), \
                mock.patch.object(rt, '_paint_button') as paint, mock.patch.object(rt, 'date') as date:
            date.today.return_value = self.TODAY
            gtk.Button.side_effect = lambda label=None: buttons.append(mock.Mock(label=label)) or buttons[-1]
            stub.rebuild_weather_bar()
        return buttons[0], paint

    def test_without_alerts_the_toggle_is_plain(self):
        button, paint = self.rebuilt_toggle(self.stub())
        paint.assert_not_called()
        button.set_tooltip_text.assert_called_once_with('Show 5-day forecast')

    def test_with_an_alert_ahead_the_toggle_takes_the_worst_colour_and_says_what_and_when(self):
        alerts = [self.tomorrow('yellow', 'Rain'), self.alert('2026-11-06T00:00:00+00:00', '2026-11-06T12:00:00+00:00', 'red', 'Wind')]
        button, paint = self.rebuilt_toggle(self.stub(upcoming=alerts))
        paint.assert_called_once_with(button, 'red')
        tooltip = button.set_tooltip_text.call_args[0][0]
        self.assertTrue(tooltip.startswith('Show 5-day forecast\n'))
        self.assertIn('Wed: Rain (yellow)', tooltip)
        self.assertIn('Fri: Wind (red)', tooltip)

    def test_an_alert_that_is_over_by_tomorrow_does_not_colour_the_toggle(self):
        today_only = self.alert('2026-11-03T08:00:00+00:00', '2026-11-03T20:00:00+00:00', 'red', upcoming=False)
        _button, paint = self.rebuilt_toggle(self.stub(active=[today_only]))
        paint.assert_not_called()

    def test_the_back_button_of_the_forecast_slide_is_not_painted(self):
        _button, paint = self.rebuilt_toggle(self.stub(upcoming=[self.tomorrow('red')]), view='forecast')
        paint.assert_not_called()


class TestSeverityButtonStyle(unittest.TestCase):
    def test_each_severity_has_its_background_and_text_that_reads_on_it(self):
        css = rt.severity_button_css()
        for color, text in (('yellow', '#000000'), ('orange', '#ffffff'), ('red', '#ffffff')):
            self.assertIn(f'button.severity-alert-{color} {{ background-image: none; background-color: '
                          f'{rt.ALERT_TEXT_COLORS[color][0]}; color: {text}; }}', css)
            self.assertIn(f'button.severity-alert-{color} label {{ color: {text}; }}', css)  # the label has its own colour in the popup's style

    def test_the_themes_gradient_is_switched_off_in_every_state(self):
        css = rt.severity_button_css()
        self.assertEqual(css.count('background-image: none'), 9)  # three states of three severities
        for color in ('yellow', 'orange', 'red'):
            self.assertIn(f'button.severity-alert-{color}:hover', css)
            self.assertIn(f'button.severity-alert-{color}:active', css)

    def setUp(self):
        saved = list(rt._severity_styles_installed)
        rt._severity_styles_installed.clear()
        self.addCleanup(lambda: rt._severity_styles_installed.__setitem__(slice(None), saved))

    def test_painting_gives_the_button_the_class_of_its_severity_and_nothing_else(self):
        button = mock.Mock()
        with mock.patch.object(rt, 'Gtk'):
            rt._paint_button(button, 'orange')
        button.get_style_context.return_value.add_class.assert_called_once_with('severity-alert-orange')
        button.get_style_context.return_value.add_provider.assert_not_called()  # a provider on the button would not reach its label

    def test_the_stylesheet_goes_on_the_screen_once_however_many_buttons(self):
        with mock.patch.object(rt, 'Gtk') as gtk, mock.patch.object(rt, 'Gdk'):
            for color in ('red', 'red', 'yellow'):
                rt._paint_button(mock.Mock(), color)
        gtk.StyleContext.add_provider_for_screen.assert_called_once()
        self.assertEqual(gtk.CssProvider.return_value.load_from_data.call_args[0][0], rt.severity_button_css().encode())
