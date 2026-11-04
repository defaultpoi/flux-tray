import unittest
from unittest import mock

from facade import rt


class TestTodayGlyph(unittest.TestCase):
    class Stub:
        build_today_weather_segments = rt.FluxTray.build_today_weather_segments
        _pulse_on_for = rt.FluxTray._pulse_on_for
        _alert_pulse_counter = 0

        def __init__(self, alerts=None):
            self.weather_data = {'temp': 12.0, 'weather_code': 71}  # snow
            self._alerts = alerts or {}

        def _segment_alert_colors(self):
            return self._alerts

    def _first(self, stub):
        with mock.patch.object(rt.GLib, 'markup_escape_text', side_effect=lambda x: x):
            return stub.build_today_weather_segments()[0]

    def test_glyph_is_monochrome_dark_without_alert(self):
        seg = self._first(self.Stub())
        self.assertIn('foreground="#2b2b2b"', seg)
        self.assertIn('\u2744\ufe0e', seg)
        self.assertNotIn('\ufe0f', seg)

    def test_alert_on_glyph_uses_alert_color(self):
        seg = self._first(self.Stub({'glyph': 'red'}))
        self.assertTrue('#cc0000' in seg or '#7a1414' in seg)
        self.assertIn('\ufe0e', seg)
        self.assertNotIn('\ufe0f', seg)


class TestGlyphRise(unittest.TestCase):
    def test_cloud_is_lifted_others_are_not(self):
        self.assertGreater(rt.glyph_rise_units('\u2601'), 0)
        for g in ('\u2600', '\u2744', '\u26a1', '\u2614'):
            self.assertEqual(rt.glyph_rise_units(g), 0)

    def test_rise_scales_with_widget_font_size(self):
        widget = mock.MagicMock()
        widget.get_pango_context.return_value.get_font_description.return_value.get_size.return_value = 20 * 1024
        self.assertAlmostEqual(rt.glyph_rise_units('\u2601', widget), 2 * rt.glyph_rise_units('\u2601'), delta=2)

    def test_markup_includes_rise_only_when_nonzero(self):
        self.assertIn('rise="500"', rt.mono_glyph_markup('\u2601', rise=500))
        self.assertNotIn('rise', rt.mono_glyph_markup('\u2600'))

    def test_today_cloud_segment_is_raised(self):
        class Stub(TestTodayGlyph.Stub):
            def __init__(self):
                super().__init__()
                self.weather_data = {'temp': 12.0, 'weather_code': 3}
        with mock.patch.object(rt.GLib, 'markup_escape_text', side_effect=lambda x: x):
            seg = Stub().build_today_weather_segments()[0]
        self.assertIn('rise="', seg)


class TestRiseSpacer(unittest.TestCase):
    def test_spacer_markup(self):
        self.assertEqual(rt.rise_spacer_markup(0), '')
        m = rt.rise_spacer_markup(700)
        self.assertIn('rise="700"', m)
        self.assertIn('\u200b', m)

    def _segments(self, code):
        class Stub(TestTodayGlyph.Stub):
            def __init__(self):
                super().__init__()
                self.weather_data = {
                    'temp': 12.0, 'weather_code': code, 'today_max_temp': 15.0,
                    'today_min_temp': 4.0, 'wind': 10.0, 'today_max_wind': 20.0,
                    'today_rain_prob': 30.0, 'today_precip_sum': 1.2}
        with mock.patch.object(rt.GLib, 'markup_escape_text', side_effect=lambda x: x):
            return Stub().build_today_weather_segments()

    def test_all_values_share_the_raise_when_cloud_is_shown(self):
        segs = self._segments(3)
        self.assertEqual(len(segs), 4)
        for seg in segs:
            self.assertIn('rise="', seg)

    def test_every_value_is_padded_even_without_a_raised_glyph(self):
        for seg in self._segments(71):  # snow: its glyph needs no raise
            self.assertIn('rise="', seg)

    def test_forecast_segments_are_padded_too(self):
        class Stub:
            build_forecast_weather_segments = rt.FluxTray.build_forecast_weather_segments
            _forecast_alerts_by_day = rt.FluxTray._forecast_alerts_by_day
            active_alerts = upcoming_alerts = ()
            weather_data = {'forecast_days': [{'max_temp': 5.0, 'min_temp': 1.0, 'rain_prob': 0}]}
        with mock.patch.object(rt.GLib, 'markup_escape_text', side_effect=lambda x: x):
            seg = Stub().build_forecast_weather_segments()[0]
        self.assertIn('rise="', seg)


class TestTodayRainText(unittest.TestCase):
    def _rain(self, prob, precip):
        class Stub(TestTodayGlyph.Stub):
            def __init__(self):
                super().__init__()
                self.weather_data = {'today_rain_prob': prob, 'today_precip_sum': precip}
        with mock.patch.object(rt.GLib, 'markup_escape_text', side_effect=lambda x: x):
            return Stub().build_today_weather_segments()[0]

    def test_zero_chance_shows_only_amount(self):
        seg = self._rain(0.0, 0.0)
        self.assertIn('0.0mm', seg)
        self.assertNotIn('%', seg)

    def test_nonzero_chance_shows_both(self):
        self.assertIn('40%/1.2mm', self._rain(40.0, 1.2))

    def test_chance_without_amount(self):
        seg = self._rain(40.0, None)
        self.assertIn('40%', seg)
        self.assertNotIn('mm', seg)

    def test_zero_chance_without_amount_keeps_percent(self):
        self.assertIn('0%', self._rain(0.0, None))


class TestMeteoalarmFeedUrl(unittest.TestCase):
    def test_simple_country(self):
        self.assertEqual(rt.meteoalarm_feed_url('Exampleland'),
                         'https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom-exampleland')

    def test_multi_word_country_is_slugged(self):
        self.assertTrue(rt.meteoalarm_feed_url('United  Example Kingdom').endswith('-united-example-kingdom'))


class TestMeteoalarmTitleParsing(unittest.TestCase):
    def test_parse_title(self):
        self.assertEqual(
            rt.parse_meteoalarm_title('Yellow Wind Warning issued for Exampleland - Eastshire'),
            ('Wind', 'Eastshire'),
        )

    def test_parse_title_multiword_hazard(self):
        self.assertEqual(
            rt.parse_meteoalarm_title('Orange High Temperature Warning issued for Exampleland - Northshire'),
            ('High Temperature', 'Northshire'),
        )

    def test_parse_title_no_match(self):
        self.assertEqual(rt.parse_meteoalarm_title('not a real title'), (None, None))

    def test_hazard_segment_mapping(self):
        self.assertEqual(rt._hazard_to_segment('Wind'), 'wind')
        self.assertEqual(rt._hazard_to_segment('High Temperature'), 'hilo')
        self.assertEqual(rt._hazard_to_segment('Low Temperature'), 'hilo')
        self.assertEqual(rt._hazard_to_segment('Snow/Ice'), 'glyph')
        self.assertEqual(rt._hazard_to_segment('Rain'), 'rain')
        self.assertEqual(rt._hazard_to_segment('Thunderstorm'), 'rain')
        self.assertEqual(rt._hazard_to_segment('Coastal Event'), 'rain')
        self.assertIsNone(rt._hazard_to_segment('Fog'))
        self.assertIsNone(rt._hazard_to_segment('Forest Fire'))


class TestFetchMeteoalarmAlerts(unittest.TestCase):
    def _entry(self, area, title, expires='2099-01-01T00:00:00+00:00'):
        return {'cap_areadesc': area, 'title': title, 'cap_expires': expires}

    def test_filters_by_region_case_insensitive(self):
        parsed = mock.MagicMock(bozo=False, entries=[
            self._entry('Eastshire', 'Yellow Wind Warning issued for Exampleland - Eastshire'),
            self._entry('northshire', 'Orange Rain Warning issued for Exampleland - Northshire'),
        ])
        with mock.patch.object(rt.feedparser, 'parse', return_value=parsed):
            alerts = rt.fetch_meteoalarm_alerts('Northshire', 'Exampleland')
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['hazard'], 'Rain')
        self.assertEqual(alerts[0]['segment'], 'rain')

    def test_no_match_is_empty_list(self):
        parsed = mock.MagicMock(bozo=False, entries=[
            self._entry('Eastshire', 'Yellow Wind Warning issued for Exampleland - Eastshire'),
        ])
        with mock.patch.object(rt.feedparser, 'parse', return_value=parsed):
            self.assertEqual(rt.fetch_meteoalarm_alerts('Northshire', 'Exampleland'), [])

    def test_bozo_with_no_entries_is_failure(self):
        parsed = mock.MagicMock(bozo=True, entries=[])
        with mock.patch.object(rt.feedparser, 'parse', return_value=parsed):
            self.assertIsNone(rt.fetch_meteoalarm_alerts('Northshire', 'Exampleland'))

    def test_uses_country_feed_url(self):
        parsed = mock.MagicMock(bozo=False, entries=[])
        with mock.patch.object(rt.feedparser, 'parse', return_value=parsed) as parse:
            rt.fetch_meteoalarm_alerts('Northshire', 'Exampleland')
        parse.assert_called_once_with(rt.meteoalarm_feed_url('Exampleland'))

    def test_parse_exception_is_failure(self):
        with mock.patch.object(rt.feedparser, 'parse', side_effect=Exception):
            self.assertIsNone(rt.fetch_meteoalarm_alerts('Northshire', 'Exampleland'))


class TestAlertSeverityAndTiming(unittest.TestCase):
    def test_severity_mapping(self):
        self.assertEqual(rt._severity_to_color('Moderate'), 'yellow')
        self.assertEqual(rt._severity_to_color('Severe'), 'orange')
        self.assertEqual(rt._severity_to_color('Extreme'), 'red')
        self.assertEqual(rt._severity_to_color('Minor'), 'yellow')
        self.assertEqual(rt._severity_to_color(None), 'yellow')

    def _entry(self, effective, onset, expires, severity='Moderate',
               title='Yellow Wind Warning issued for Exampleland - Northshire', area='Northshire'):
        return {
            'cap_areadesc': area, 'title': title, 'cap_effective': effective,
            'cap_onset': onset, 'cap_expires': expires, 'cap_severity': severity,
        }

    def test_expired_entry_filtered_out(self):
        now = rt.datetime(2026, 9, 29, 19, 14, 58, tzinfo=rt.timezone.utc)
        parsed = mock.MagicMock(bozo=False, entries=[
            self._entry('2026-09-28T06:53:00+00:00', '2026-09-28T07:00:00+00:00',
                         '2026-09-28T17:00:00+00:00'),
        ])
        with mock.patch.object(rt.feedparser, 'parse', return_value=parsed):
            self.assertEqual(rt.fetch_meteoalarm_alerts('Northshire', 'Exampleland', now=now), [])

    def test_future_entry_filtered_out(self):
        now = rt.datetime(2026, 9, 29, 19, 14, 58, tzinfo=rt.timezone.utc)
        parsed = mock.MagicMock(bozo=False, entries=[
            self._entry('2026-09-29T18:00:00+00:00', '2026-09-30T08:00:00+00:00',
                         '2026-09-30T20:00:00+00:00', severity='Extreme'),
        ])
        with mock.patch.object(rt.feedparser, 'parse', return_value=parsed):
            self.assertEqual(rt.fetch_meteoalarm_alerts('Northshire', 'Exampleland', now=now), [])

    def test_currently_active_entry_kept_with_severity_color(self):
        now = rt.datetime(2026, 9, 29, 19, 14, 58, tzinfo=rt.timezone.utc)
        parsed = mock.MagicMock(bozo=False, entries=[
            self._entry('2026-09-29T06:00:00+00:00', '2026-09-29T10:00:00+00:00',
                         '2026-09-30T10:00:00+00:00', severity='Severe',
                         title='Orange Rain Warning issued for Exampleland - Northshire'),
        ])
        with mock.patch.object(rt.feedparser, 'parse', return_value=parsed):
            alerts = rt.fetch_meteoalarm_alerts('Northshire', 'Exampleland', now=now)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['severity_color'], 'orange')

    def test_pulse_speed_ratios(self):
        class Stub:
            _pulse_on_for = rt.FluxTray._pulse_on_for
        s = Stub()
        def flips(color):
            states = []
            for i in range(16):
                s._alert_pulse_counter = i
                states.append(s._pulse_on_for(color))
            return sum(1 for i in range(1, 16) if states[i] != states[i - 1])
        self.assertEqual(flips('red'), 15)
        self.assertIn(flips('orange'), (7, 8))
        self.assertIn(flips('yellow'), (3, 4))


if __name__ == '__main__':
    unittest.main()


class TestUpcomingAlertsInTheFeed(unittest.TestCase):
    NOW = rt.datetime(2026, 11, 3, 15, 0, tzinfo=rt.timezone.utc)

    def setUp(self):
        import os
        import time
        self.addCleanup(self.restore_tz, os.environ.get('TZ'))
        os.environ['TZ'] = 'UTC'
        time.tzset()

    @staticmethod
    def restore_tz(previous):
        import os
        import time
        if previous is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = previous
        time.tzset()

    def entry(self, onset, expires, severity='Severe', title='Orange Wind Warning issued for Exampleland - Northshire'):
        return {'cap_areadesc': 'Northshire', 'title': title, 'cap_onset': onset, 'cap_expires': expires, 'cap_severity': severity}

    def fetch(self, entries, **kw):
        parsed = mock.MagicMock(bozo=False, entries=entries)
        with mock.patch.object(rt.feedparser, 'parse', return_value=parsed):
            return rt.fetch_meteoalarm_alerts('Northshire', 'Exampleland', now=self.NOW, **kw)

    def test_by_default_only_what_is_in_force_now_as_before(self):
        alerts = self.fetch([self.entry('2026-11-03T10:00:00+00:00', '2026-11-03T20:00:00+00:00'),
                             self.entry('2026-11-04T08:00:00+00:00', '2026-11-04T20:00:00+00:00')])
        self.assertEqual(len(alerts), 1)
        self.assertFalse(alerts[0]['upcoming'])
        self.assertEqual(alerts[0]['onset'], '2026-11-03T10:00:00+00:00')

    def test_with_upcoming_days_what_starts_later_comes_too_marked_as_upcoming(self):
        alerts = self.fetch([self.entry('2026-11-03T10:00:00+00:00', '2026-11-03T20:00:00+00:00'),
                             self.entry('2026-11-04T08:00:00+00:00', '2026-11-04T20:00:00+00:00')], upcoming_days=5)
        self.assertEqual([a['upcoming'] for a in alerts], [False, True])
        self.assertEqual(alerts[1]['onset'], '2026-11-04T08:00:00+00:00')
        self.assertEqual((alerts[1]['hazard'], alerts[1]['severity_color'], alerts[1]['segment']), ('Wind', 'orange', 'wind'))

    def test_the_horizon_is_the_end_of_the_last_forecast_day(self):
        # today is 3 November; the five forecast days end at midnight starting the 9th
        inside = self.entry('2026-11-08T23:59:00+00:00', '2026-11-09T06:00:00+00:00')
        outside = self.entry('2026-11-09T00:00:00+00:00', '2026-11-09T06:00:00+00:00')
        self.assertEqual(len(self.fetch([inside, outside], upcoming_days=5)), 1)

    def test_one_that_has_already_expired_is_never_included(self):
        self.assertEqual(self.fetch([self.entry('2026-11-02T08:00:00+00:00', '2026-11-03T09:00:00+00:00')], upcoming_days=5), [])

    def test_an_entry_without_an_onset_counts_as_in_force_not_upcoming(self):
        alerts = self.fetch([self.entry('', '2026-11-04T09:00:00+00:00')], upcoming_days=5)
        self.assertEqual([a['upcoming'] for a in alerts], [False])

    def test_the_feed_is_asked_for_once_whatever_the_days(self):
        parsed = mock.MagicMock(bozo=False, entries=[])
        with mock.patch.object(rt.feedparser, 'parse', return_value=parsed) as parse:
            rt.fetch_meteoalarm_alerts('Northshire', 'Exampleland', now=self.NOW, upcoming_days=5)
        parse.assert_called_once()


class TestAlertsOnForecastDays(unittest.TestCase):
    TODAY = rt.datetime(2026, 11, 3).date()
    TZ = rt.timezone(rt.timedelta(hours=2))

    def alert(self, onset, expires, color='orange', hazard='Wind'):
        return {'onset': onset, 'expires': expires, 'severity_color': color, 'hazard': hazard}

    def days(self, *alerts):
        by_day = rt.forecast_alerts_by_day(list(alerts), self.TODAY, tz=self.TZ)
        return {n: [a['hazard'] + ':' + a['severity_color'] for a in found] for n, found in by_day.items()}

    def test_an_alert_within_tomorrow_is_on_day_one_only(self):
        self.assertEqual(self.days(self.alert('2026-11-04T10:00:00+02:00', '2026-11-04T18:00:00+02:00')), {1: ['Wind:orange']})

    def test_an_alert_that_runs_over_midnights_is_on_each_day_it_touches(self):
        self.assertEqual(sorted(self.days(self.alert('2026-11-04T20:00:00+02:00', '2026-11-06T06:00:00+02:00'))), [1, 2, 3])

    def test_one_in_force_now_that_runs_into_tomorrow_is_on_day_one(self):
        self.assertEqual(sorted(self.days(self.alert('2026-11-02T20:00:00+02:00', '2026-11-04T05:00:00+02:00'))), [1])

    def test_one_that_ends_at_midnight_does_not_touch_the_next_day(self):
        self.assertEqual(sorted(self.days(self.alert('2026-11-04T20:00:00+02:00', '2026-11-05T00:00:00+02:00'))), [1])

    def test_one_that_starts_at_midnight_is_on_that_day(self):
        self.assertEqual(sorted(self.days(self.alert('2026-11-05T00:00:00+02:00', '2026-11-05T03:00:00+02:00'))), [2])

    def test_one_that_is_over_by_tomorrow_is_not_on_any_forecast_day(self):
        self.assertEqual(self.days(self.alert('2026-11-03T08:00:00+02:00', '2026-11-03T23:59:00+02:00')), {})

    def test_the_forecast_stops_at_the_fifth_day(self):
        self.assertEqual(sorted(self.days(self.alert('2026-11-07T20:00:00+02:00', '2026-11-12T00:00:00+02:00'))), [4, 5])
        self.assertEqual(self.days(self.alert('2026-11-09T00:00:00+02:00', '2026-11-09T12:00:00+02:00')), {})

    def test_the_day_is_the_persons_own_not_utc(self):
        # 22:30 UTC on the 4th is 00:30 on the 5th at UTC+2
        self.assertEqual(sorted(self.days(self.alert('2026-11-04T22:30:00+00:00', '2026-11-05T04:00:00+00:00'))), [2])

    def test_alerts_of_several_severities_on_one_day_are_all_listed(self):
        found = self.days(self.alert('2026-11-04T08:00:00+02:00', '2026-11-04T12:00:00+02:00', 'yellow', 'Rain'),
                          self.alert('2026-11-04T09:00:00+02:00', '2026-11-04T11:00:00+02:00', 'red', 'Wind'))
        self.assertEqual(found, {1: ['Rain:yellow', 'Wind:red']})

    def test_an_alert_without_an_end_covers_only_the_day_it_starts(self):
        self.assertEqual(sorted(self.days(self.alert('2026-11-05T10:00:00+02:00', ''))), [2])

    def test_an_alert_without_a_start_reaches_back_but_ends_when_it_says(self):
        self.assertEqual(sorted(self.days(self.alert('', '2026-11-05T12:00:00+02:00'))), [1, 2])

    def test_an_alert_without_either_is_not_a_forecast_alert(self):
        self.assertEqual(self.days(self.alert('', '')), {})
        self.assertEqual(self.days(self.alert('not a time', 'neither')), {})

    def test_no_alerts_no_days(self):
        self.assertEqual(rt.forecast_alerts_by_day([], self.TODAY, tz=self.TZ), {})


class TestWorstSeverity(unittest.TestCase):
    def test_the_most_severe_colour_wins(self):
        self.assertEqual(rt.worst_severity([{'severity_color': 'yellow'}, {'severity_color': 'red'}, {'severity_color': 'orange'}]), 'red')
        self.assertEqual(rt.worst_severity([{'severity_color': 'yellow'}, {'severity_color': 'orange'}]), 'orange')

    def test_nothing_is_none_and_a_missing_colour_is_yellow(self):
        self.assertIsNone(rt.worst_severity([]))
        self.assertEqual(rt.worst_severity([{}]), 'yellow')
