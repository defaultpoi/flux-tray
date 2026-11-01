# Direction

What was asked for, in the words it was asked in: a tray app that takes in
data from all kinds of services (weather, news, streams, media, updates, and
others are coming), tracks them, decides when and how to present them and how
you can interact with them, based on rules you define. A personal app, tailored
to one system.

"Dispatcher" is a word for that sentence and means nothing more here. An
earlier version of this file built a model out of the word (items with states,
a store, a new `[rules]` syntax with `->`). That was invention, it changed the
config, and it is withdrawn.

## What does not change

- **How it looks.** The popup built from fixed data is compared, widget by widget, with the popup of the original, unmodified void-tray at commit `eb73c7d`: byte-identical for both golden scenarios. `tests/test_golden_popup.py` keeps it so.
- **The config.** `config.conf` has the same syntax. Every loader (27 of them) was run on 116 config texts, the README example, the default template and 112 snippets from the tests, under the original and under this code: 3248 results, no difference. What is stored in `state.json` and `media.json` was not changed (the feed part of it was also compared old against new on 400 random scenarios).
- **Behaviour.** The tests of the original pass on Python 3.14. They were changed only for the new names, in two tests that used placeholder links like `la` (now real addresses, since feed links are checked), in two that ran `build_popup_window` on a mock (now bound to the real builders), and by removing the tests of the old-directory migration.

Flux Tray keeps its own directory, `~/.config/flux-tray`, so it can sit beside
an app that is still in use without touching it. Do not run both at once: two
tray icons, two sets of sounds, and two copies of the same state.

## What the app already does, verb by verb

| Asked for | Today |
|-----------|-------|
| take in data from services | news feeds, Twitch and YouTube live, weather and alerts, media sources, package updates and orphans, the countdown timer and scheduled actions, the network state |
| track them | `state.json` (seen, unread, saved, live, updates) and `media.json` (episodes, downloads, watched) |
| decide when to present | fixed: anything new means an icon update, a sound and an auto-opened popup, except over a fullscreen window; the live checks follow per-channel schedules |
| decide how to present | fixed: the sections, their order, the badge and the order of the icon tooltips |
| interact | row clicks and menus per kind of row |
| rules you define | in `config.conf`: global mute phrases, per-feed mute and read-later rules, highlight words, live schedules, qualities and names, the update interval and installer, timer and scheduled actions, the network reset command |

Rules exist for some services and some decisions. What is fixed in code is how
and when anything is announced, and which sections show.

## Is there a more efficient way to store the rules?

It depends on repetition, and that can only be seen in your own file.

- Per-feed mute and read-later rules are columns on a feed's line. A rule that should apply to several feeds is written on each of those lines; the global `[mute]` section matches titles only.
- No rule can say "for this service" or "at this time" about announcing: the sound, the auto-open and the badge are not up to a rule.

If your config repeats the same rule on many lines, a shared place for rules
would be shorter. If it does not, the present format is already the shortest
way to say it, and a new one would only be a new thing to learn. So no new
format is proposed. If one is wanted, it would come in beside the old (every
existing line keeps working) and would be shown against your real rules before
any code is written.

## What could be done inside, invisibly

Adding a service means touching its timer and lock in `app.py`, a mixin, state
keys, rows in the popup and a click handler. Making that one place is
possible, one service at a time, with the golden files, the parity matrix and,
for each service, a run of the old and new code side by side on random inputs
(as was done for `check_feeds`) as the gate. No config change, no state change,
no visible change. It is not started; nothing here needs it before a new
service does.

Smaller, and independent of the above: `refresh_list` and `on_row_activated` in
`ui/popup.py` are the most tangled functions left (see [STATUS.md](STATUS.md)).
