# Flux Tray as a dispatcher

This describes where the app is going. **None of it is built yet**: the app
today is the code in this repository, which already behaves like a dispatcher
in outline but decides almost everything in code. The migration at the end
changes that one service at a time, keeping the popup and every feature as they
are (the golden files and the parity matrix check that at every step).

## What it should be

A tray app that takes in data from services (weather, news, streams, media,
updates, and others to come), tracks it, and decides when and how to present
it, and how you can interact with it, according to rules you define. One
person, one machine: XFCE on Void Linux, Python 3.14.

## What it is today

Each feature owns its own copy of the same few jobs:

| Job | Where it lives now |
|-----|--------------------|
| Fetch on a schedule | a timer and a lock per feature in `app.py` and each `ui/*.py` mixin |
| Remember what was seen, unread, saved | `state.json` keys per feature (`seen`, `unread`, `read_later`, `live_channels`, `available_updates`, `orphans`), and `media.json` |
| Decide whether it matters | rules in code (age over a day, the cap of 500) and in `config.conf` (mute, read later, highlight words, live schedules), each with its own syntax |
| Decide how to present it | fixed: any new unread item, update or live channel means icon, sound and an auto-opened popup, except over a fullscreen window (`on_new_items`, `show_popup`); a fixed order of tooltips in `update_icon` |
| Offer actions | `on_row_activated`, a chain of `if hasattr(row, ...)` over row kinds |

A new service means touching all five places. The rules are the part you want
to own, and they are the part with the least structure.

## The model

Six nouns. Everything else is detail.

- **Service**: something that has things to tell you. It knows how to fetch (when, over what, what a failure means) and turns what it got into items. Weather, news, live channels, media sources, package updates, the countdown timer and its scheduled actions are services. A new one is one module.
- **Item**: one tracked thing, in one shape for every service: its service, an id, a kind, a title, a target (link, channel, package), a severity, when it was first seen and last changed, a state, and a few facts of its own (author and categories for news; viewers and category for a stream; progress for a download; the old and new version for an update).
- **State** of an item, from a small fixed set: `new` (arrived, not yet shown), `shown`, `read`, `saved`, `hidden`, `done`, `failed`. A service moves items between them (a stream going offline ends its item); you move them by interacting (a click reads, a right click hides).
- **Store**: keeps items and their states across restarts, with retention and caps (what `seen`, `unread` and `media.json` do now, in one place).
- **Rule**: `when` an item matches, `then` effects. This is the part you write.
- **Presenter**: turns the store plus the effects into what you see: the tray icon and tooltip, the badge, the popup's sections and rows, the sound, whether the popup opens by itself.

Actions are what you can do to an item: open the link, play it in mpv, download
it, install the update, remove the orphan, save it, snooze it, mute things like
it. A service says which actions its items have; a rule can add one that runs a
command of yours.

## The rules

One line each, in a `[rules]` section of `config.conf`, in the style the file
already uses: `field=value` pieces separated by `;`, `,` for alternatives, `*`
and `?` as wildcards, case and accents ignored. `->` separates what is matched
from what happens.

```
[rules]
# service=news is the default for fields a feed has
category=sports,golf                          -> hide
author=Some Name                              -> save
title=*breaking*                              -> pulse, sound, popup
service=live; channel=examplechan             -> popup, sound; during 18:00-23:00
service=live                                  -> badge=off
service=updates                               -> badge, popup=off
service=weather; severity>=orange             -> popup, pulse
service=media; state=new                      -> badge=off
service=news; feed=*example.com*              -> run: notify-send "{title}" "{link}"
```

What can be matched: `service`, `kind`, `state`, `severity`, any fact an item
carries (`category`, `author`, `title`, `summary`, `channel`, `feed`, `package`,
`viewers`...), and the clock (`during 18:00-23:00`, `on mon,tue`). What can
happen, a closed list to begin with:

- how it is shown: `hide`, `save`, `pulse`, `badge`, `badge=off`, `section=<name>`;
- how it announces itself: `sound`, `popup`, `popup=off`, `sound=off`;
- what it offers: `run: <command>` with `{title}`, `{link}`, `{id}` filled in;
- what happens to it: `expire=<time>`, `read`.

Rules apply top to bottom and their effects add up. `hide` ends the matching,
because today a mute rule beats a read-later rule and the tests pin that. Where
there is no rule about it, the defaults are today's behaviour, so an empty
`[rules]` section gives exactly the app as it is.

The existing per-feed columns (mute rules, read-later rules), `[mute]`,
`[highlight]` and the live schedules stay readable as shorthand for the rules
they are, and are translated, not kept as separate machinery.

## Adding a service

One module in `flux_tray/services/` with four things: how often and when it
runs (`interval`, and whether it needs the network), `poll()` which returns what
it found as items, the actions its items have, and how a row of its kind is
drawn. A test feeds it a canned response, as the weather and live tests do now.
Nothing else changes: the store, the rules, the icon and the popup already
handle items.

## Staying the same

The popup, its texts and every behaviour in [FEATURES.md](FEATURES.md). Each
step below is accepted only when the golden popup files and the parity matrix
are unchanged, and, where a service moves, when the old and the new code give
identical state on randomised scenarios (as was done for `check_feeds`).

## Order of work

1. The core on its own: item, state, store, the rule matcher and effects, the presenter's policy (what opens, what sounds, what the icon says). Tested without GTK. Nothing uses it yet.
2. News, the richest rules: mute, read later, highlight, age, cap become rules and effects; unread and read-later sections come from the store. This proves the model.
3. Updates and orphans, then live streams, then weather and alerts, then media (a download is an item with progress), then the timer and its scheduled actions.
4. The popup: one row kind per item kind, each owning what a click does, which retires the `hasattr` chain and `refresh_list`.
5. `FluxTray.__init__` shrinks from 83 shared attributes to the store, the services and the presenter; the mixins go.
6. `[rules]` becomes the place for what is now spread over `[feeds]` columns, `[mute]`, `[highlight]` and the schedules.

The stored state changes shape at step 2. Since this is one person's file, the
conversion is a one-time script written against the real `state.json` and
`media.json`, not a compatibility layer in the app.

## Decisions made here, to be overruled if wrong

- Rules are lines in `config.conf`, not a scripting language: you can read and edit them in the app's own Edit config button, and a mistake in one line cannot stop the app (it is reported and skipped, as an invalid channel is now).
- The list of effects is closed and small; `run:` is the escape hatch for anything else.
- Services are modules in this repository, not a plugin system. The media plugin folder stays as it is because it exists already and holds your own files.
- `hide` beats every other effect; everything else adds up.

## Not decided

- Whether severity is a number or a short fixed list (`info`, `notice`, `warn`, `alert`), and what each service maps onto it (weather alert levels, a failed download, an available update).
- Whether `popup=off` also stops the popup from refreshing in place when it is already open (today it refreshes).
