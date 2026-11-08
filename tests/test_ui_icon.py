import threading
import unittest
from unittest import mock

from facade import rt


class TestTempIconLayout(unittest.TestCase):
    def test_digits_and_ring_are_centred_together(self):
        left, cx, cy = rt.temp_icon_layout(24, 12.0, 9.0)
        ring_outer = 2 * rt.TEMP_RING_RADIUS + rt.TEMP_RING_LINE_WIDTH
        right_edge = cx + ring_outer / 2
        self.assertAlmostEqual(left, 24 - right_edge, places=6)  # equal margins either side

    def test_ring_follows_the_digits_and_sits_at_their_top(self):
        left, cx, cy = rt.temp_icon_layout(24, 12.0, 9.0)
        self.assertGreater(cx, left + 12.0)             # to the right of the digits
        digits_top = 24 / 2 - 9.0 / 2
        self.assertAlmostEqual(cy - (2 * rt.TEMP_RING_RADIUS + rt.TEMP_RING_LINE_WIDTH) / 2, digits_top, places=6)

    def test_ring_never_leaves_the_icon_top(self):
        _left, _cx, cy = rt.temp_icon_layout(24, 12.0, 40.0)
        self.assertGreaterEqual(cy - rt.TEMP_RING_RADIUS - rt.TEMP_RING_LINE_WIDTH / 2, -1e-9)


class FakeContext:
    """Records what render_icon draws, standing in for a cairo context."""

    def __init__(self):
        self.calls = []
        self.font_size = 12

    def _record(self, name, *args):
        self.calls.append((name, args))

    def set_source_rgba(self, *rgba):
        self._record('rgba', *rgba)

    def set_font_size(self, size):
        self.font_size = size

    def text_extents(self, text):
        return (0, 0, 0.6 * self.font_size * len(text), 0.7 * self.font_size, 0, 0)

    def __getattr__(self, name):
        return lambda *args: self._record(name, *args)

    def drawn(self, name):
        return [args for call, args in self.calls if call == name]


class TestAlertIconText(unittest.TestCase):
    class Stub:
        render_icon = rt.FluxTray.render_icon
        _draw_temperature = rt.FluxTray._draw_temperature
        _current_temperature = rt.FluxTray._current_temperature
        total_badge_count = rt.FluxTray.total_badge_count
        _should_show_weather_icon = rt.FluxTray._should_show_weather_icon
        has_pkg_update = rt.FluxTray.has_pkg_update
        has_active_alerts = rt.FluxTray.has_active_alerts
        _worst_alert_color = rt.FluxTray._worst_alert_color
        _pulse_on_for = rt.FluxTray._pulse_on_for
        _current_hazard = rt.FluxTray._current_hazard

    def render(self, temp=24.6, color='red', unread=0, updates=0, pulse=0, alert=True):
        stub = self.Stub()
        stub.schedule_warning = None
        stub._schedule_flash_on = False
        stub.weather_data = {'temp': temp} if temp is not None else None
        stub.active_alerts = [{'severity_color': color, 'hazard': 'Wind'}] if alert else []
        stub._alert_pulse_counter = pulse
        stub.state = {'unread': [object()] * unread, 'available_updates': [object()] * updates}
        stub.lock = threading.RLock()
        ctx = FakeContext()
        fake_cairo = mock.Mock(Context=lambda _surface: ctx)
        with mock.patch.object(rt, 'cairo', fake_cairo), mock.patch.object(rt, 'Gdk', mock.Mock()):
            stub.render_icon(stub.total_badge_count())
        return ctx

    def texts(self, ctx):
        return [args[0] for args in ctx.drawn('show_text')]

    def test_an_alert_with_nothing_unread_shows_the_temperature_not_zero(self):
        # Use pulse=1 (dim phase for red) to see the temperature
        ctx = self.render(temp=24.6, pulse=1)
        self.assertEqual(self.texts(ctx), ['25'])
        self.assertEqual(len(ctx.drawn('stroke')), 1)  # the degree ring

    def test_an_alert_with_nothing_unread_alternates_icon_and_temperature(self):
        # Red alert: bright on even pulses (0,2,4,6), dim on odd (1,3,5,7)
        for pulse in range(8):
            ctx = self.render(pulse=pulse)
            if pulse % 2 == 0:
                # Bright phase: MeteoAlarm icon drawn with fill
                self.assertGreater(len(ctx.drawn('fill')), 0, pulse)
                self.assertEqual(len(ctx.drawn('arc')), 0, pulse)  # no degree ring when icon shown
            else:
                # Dim phase: white temperature with degree ring (stroke/arc)
                self.assertEqual(ctx.drawn('fill'), [], pulse)
                self.assertEqual(len(ctx.drawn('arc')), 1, pulse)  # only the degree ring is an arc

    def test_both_icon_and_temperature_are_white(self):
        white = (1, 1, 1, 1)
        # Both icon phase (pulse=0) and temperature phase (pulse=1) should use white
        self.assertEqual(self.render(pulse=0).drawn('rgba'), [white])
        self.assertEqual(self.render(pulse=1).drawn('rgba'), [white])
        self.assertEqual(self.render(pulse=2).drawn('rgba'), [white])

    def test_the_digits_and_the_degree_ring_share_the_colour(self):
        for pulse in (0, 1):
            self.assertEqual(len(self.render(pulse=pulse).drawn('rgba')), 1)  # one colour set before both are drawn

    def test_each_severity_alternates_at_its_own_rate(self):
        # Now both icon and temperature are white; alternation is icon <-> temperature
        # Check that the alternation rate follows the severity pulse rates
        def icon_phases(color):
            # Returns 'I' for icon phase (fill), 'T' for temperature phase (arc)
            return ''.join(
                'I' if self.render(color=color, pulse=n).drawn('fill') else 'T'
                for n in range(8)
            )
        # Red: icon every tick (0,2,4,6) -> I T I T I T I T
        self.assertEqual(icon_phases('red'), 'ITITITIT')
        # Orange: icon every 2 ticks (0,1,4,5) -> I I T T I I T T
        self.assertEqual(icon_phases('orange'), 'IITTIITT')
        # Yellow: icon every 4 ticks (0,1,2,3) -> I I I I T T T T
        self.assertEqual(icon_phases('yellow'), 'IIIITTTT')

    def test_the_worst_of_several_alerts_sets_the_pulse_rate(self):
        # Worst alert (red) determines the pulse rate even though color is always white
        stub = self.Stub()
        stub.schedule_warning, stub._schedule_flash_on = None, False
        stub.weather_data = {'temp': 20}
        stub.active_alerts = [{'severity_color': 'yellow'}, {'severity_color': 'red'}, {'severity_color': 'orange'}]
        stub._alert_pulse_counter = 0
        stub.state = {'unread': [], 'available_updates': []}
        stub.lock = threading.RLock()
        ctx = FakeContext()
        with mock.patch.object(rt, 'cairo', mock.Mock(Context=lambda _surface: ctx)), mock.patch.object(rt, 'Gdk', mock.Mock()):
            stub.render_icon(0)
        # Should use red's pulse rate (icon on even pulses)
        self.assertTrue(ctx.drawn('fill'))  # pulse 0 = icon phase for red

    def test_negative_temperatures_keep_their_sign(self):
        # Use pulse=4 (dim phase for yellow) to see the temperature
        self.assertEqual(self.texts(self.render(temp=-5.2, color='yellow', pulse=4)), ['-5'])

    def test_without_a_temperature_the_disc_falls_back_to_zero(self):
        self.assertEqual(self.texts(self.render(temp=None)), ['0'])
        self.assertEqual(len(self.render(temp=None).drawn('stroke')), 0)

    def test_unread_items_still_show_their_count_during_an_alert(self):
        ctx = self.render(unread=3)
        self.assertEqual(self.texts(ctx), ['3'])
        self.assertEqual(len(ctx.drawn('stroke')), 0)

    def test_pending_package_updates_still_show_their_count_during_an_alert(self):
        self.assertEqual(self.texts(self.render(updates=2)), ['2'])

    def test_without_an_alert_the_temperature_is_drawn_without_a_disc(self):
        ctx = self.render(alert=False)
        self.assertEqual(self.texts(ctx), ['25'])
        self.assertEqual(len(ctx.drawn('fill')), 0)

    def test_the_alerting_temperature_is_as_big_as_the_plain_temperature_icon(self):
        plain = self.render(alert=False, temp=25)
        # Use pulse=1 (dim phase for red) to see the temperature
        alerting = self.render(temp=25, pulse=1)
        self.assertEqual(self.texts(alerting), ['25'])
        self.assertEqual(alerting.font_size, plain.font_size)

    def test_with_unread_items_the_alert_still_pulses_the_disc_that_holds_their_count(self):
        bright, dim = rt.ALERT_BADGE_COLORS['red']
        self.assertEqual(self.render(unread=3, pulse=0).drawn('rgba')[0], bright)
        self.assertEqual(self.render(unread=3, pulse=1).drawn('rgba')[0], dim)
        self.assertEqual(len(self.render(unread=3).drawn('fill')), 1)

    def test_with_package_updates_the_alert_still_pulses_the_disc_that_holds_their_count(self):
        self.assertEqual(len(self.render(updates=2).drawn('fill')), 1)

    def test_without_a_temperature_the_alert_falls_back_to_the_pulsing_disc(self):
        bright, dim = rt.ALERT_BADGE_COLORS['red']
        self.assertEqual(self.render(temp=None, pulse=0).drawn('rgba')[0], bright)
        self.assertEqual(self.render(temp=None, pulse=1).drawn('rgba')[0], dim)
        self.assertEqual(len(self.render(temp=None).drawn('fill')), 1)


if __name__ == '__main__':
    unittest.main()


class TestSvgPaths(unittest.TestCase):
    def test_commands_come_with_their_numbers(self):
        self.assertEqual(rt._parse_svg_path('M1,2 L3.5,-4 C1,2,3,4,5,6 Z'),
                         (('M', (1.0, 2.0)), ('L', (3.5, -4.0)), ('C', (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)), ('Z', ())))

    def test_numbers_may_be_written_every_way_svg_allows(self):
        self.assertEqual(rt._parse_svg_path('M.5-.25L1e2,2E-1'), (('M', (0.5, -0.25)), ('L', (100.0, 0.2))))

    def test_more_numbers_repeat_the_command_and_a_repeated_moveto_is_a_lineto(self):
        self.assertEqual(rt._parse_svg_path('M0,0 5,5 10,0 L1,1 2,2'),
                         (('M', (0.0, 0.0)), ('L', (5.0, 5.0)), ('L', (10.0, 0.0)), ('L', (1.0, 1.0)), ('L', (2.0, 2.0))))

    def test_what_cannot_be_drawn_is_refused_not_guessed(self):
        for bad in ('M1,2 Q3,4,5,6', 'M1', 'C1,2,3,4,5'):
            with self.assertRaises(ValueError, msg=bad):
                rt._parse_svg_path(bad)

    def test_a_path_is_parsed_once(self):
        path = 'M1,2 L3,4 Z'
        self.assertIs(rt._parse_svg_path(path), rt._parse_svg_path(path))

    def test_every_hazard_icon_parses_and_stays_in_its_viewbox(self):
        self.assertTrue({'wind', 'rain', 'thunderstorm', 'rain-flood', 'default'} <= set(rt.METEOALARM_ICONS))
        for hazard, paths in rt.METEOALARM_ICONS.items():
            for path in paths:
                for command, numbers in rt._parse_svg_path(path):
                    for value in numbers:
                        self.assertTrue(-0.5 <= value <= 64.5, f'{hazard}: {value} outside the 64x64 viewBox')

    def test_a_path_is_scaled_and_moved_and_closing_does_not_draw_a_line_back_to_the_first_point(self):
        ctx = mock.Mock()
        rt._draw_svg_path(ctx, 'M10,10 L20,10 C1,2,3,4,5,6 Z M30,30 L40,30 Z', 2, 3, 1, 5)
        self.assertEqual(ctx.mock_calls, [
            mock.call.move_to(21, 35), mock.call.line_to(41, 35), mock.call.curve_to(3, 11, 7, 17, 11, 23),
            mock.call.close_path(),
            mock.call.move_to(61, 95), mock.call.line_to(81, 95), mock.call.close_path()])


@unittest.skipIf(isinstance(rt.cairo, mock.Mock), 'needs the real cairo')
class TestHazardIconsDrawn(unittest.TestCase):
    def drawn(self, hazard, size=24, target_height=None):
        surface = rt.cairo.ImageSurface(rt.cairo.FORMAT_ARGB32, size, size)
        ctx = rt.cairo.Context(surface)
        rt._draw_meteoalarm_icon(ctx, hazard, size, (1, 1, 1, 1), target_height)
        surface.flush()
        return bytes(surface.get_data())

    def covered(self, data):
        return sum(1 for i in range(3, len(data), 4) if data[i])

    def test_every_hazard_puts_something_on_the_icon_and_not_everything(self):
        for hazard in rt.METEOALARM_ICONS:
            data = self.drawn(hazard, target_height=9)
            self.assertTrue(20 < self.covered(data) < 24 * 24 * 0.9, hazard)

    def test_the_hazards_look_different(self):
        images = {hazard: self.drawn(hazard, target_height=9) for hazard in rt.METEOALARM_ICONS}
        self.assertEqual(len(set(images.values())), len(images))

    def test_an_unknown_hazard_gets_the_fallback_ring(self):
        self.assertEqual(self.drawn('volcano', target_height=9), self.drawn('default', target_height=9))

    def test_the_icon_is_centred_when_it_is_sized_to_the_digits(self):
        data = self.drawn('thunderstorm', target_height=9)
        columns = [x for x in range(24) if any(data[(y * 24 + x) * 4 + 3] for y in range(24))]
        rows = [y for y in range(24) if any(data[(y * 24 + x) * 4 + 3] for x in range(24))]
        self.assertLessEqual(abs((columns[0] + columns[-1]) - 23), 3)
        self.assertLessEqual(abs((rows[0] + rows[-1]) - 23), 3)
