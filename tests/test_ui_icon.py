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
        ctx = self.render(temp=24.6)
        self.assertEqual(self.texts(ctx), ['25'])
        self.assertEqual(len(ctx.drawn('stroke')), 1)  # the degree ring

    def test_an_alert_with_nothing_unread_has_no_disc(self):
        for pulse in range(8):
            ctx = self.render(pulse=pulse)
            self.assertEqual(ctx.drawn('fill'), [], pulse)
            self.assertEqual(len(ctx.drawn('arc')), 1, pulse)  # only the degree ring is an arc

    def test_the_temperature_alternates_between_the_severity_colour_and_white(self):
        bright = rt.ALERT_BADGE_COLORS['red'][0]
        white = (1, 1, 1, 1)
        self.assertEqual(self.render(pulse=0).drawn('rgba'), [bright])
        self.assertEqual(self.render(pulse=1).drawn('rgba'), [white])
        self.assertEqual(self.render(pulse=2).drawn('rgba'), [bright])

    def test_the_digits_and_the_degree_ring_share_the_colour(self):
        for pulse in (0, 1):
            self.assertEqual(len(self.render(pulse=pulse).drawn('rgba')), 1)  # one colour set before both are drawn

    def test_each_severity_alternates_at_its_own_rate(self):
        def phases(color):
            bright = rt.ALERT_BADGE_COLORS[color][0]
            return ''.join('B' if self.render(color=color, pulse=n).drawn('rgba')[0] == bright else 'w' for n in range(8))
        self.assertEqual(phases('red'), 'BwBwBwBw')        # every tick
        self.assertEqual(phases('orange'), 'BBwwBBww')     # every second tick
        self.assertEqual(phases('yellow'), 'BBBBwwww')     # every fourth tick

    def test_the_worst_of_several_alerts_sets_the_colour(self):
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
        self.assertEqual(ctx.drawn('rgba'), [rt.ALERT_BADGE_COLORS['red'][0]])

    def test_negative_temperatures_keep_their_sign(self):
        self.assertEqual(self.texts(self.render(temp=-5.2, color='yellow')), ['-5'])

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
        alerting = self.render(temp=25)
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
