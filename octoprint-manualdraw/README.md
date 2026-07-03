# OctoPrint-ManualDraw

Scan a QR code stuck next to the table, hold down **"Disegna tu stesso"**
("Draw it yourself") for a few seconds, and steer the ball with your phone's
tilt like a joystick. Whatever the table was drawing — an
`octoprint_sandtable` ERASER/DRAW cycle, an `octoprint-f1sisyphus` tracking
session, or nothing — pauses while you're in control, and resumes exactly
where it left off when you let go.

No coordination with those other plugins is required: this plugin pauses
and resumes the underlying OctoPrint print job directly, which their own
cycle logic (driven by `PrintDone`/`PrintCancelled` events, never fired by a
pause/resume) simply doesn't notice.

## How it works

- The **ManualDraw** admin tab shows a QR code encoding a URL with a random
  token. The token is generated once (first boot) and then persisted, so a
  QR code you print and stick next to the table keeps working across every
  reboot — including the routine power-cycles `octoprint_sandtable` does
  after each ERASER/DRAW cycle. It only changes if you deliberately hit
  **Regenerate code** (e.g. you suspect the sticker/URL leaked). Anyone who
  scans it gets a phone page — no OctoPrint login needed, but the token is
  required for every control action.
- **Holding the button 3s** (configurable) pauses the current print (if any)
  and takes control. Releasing it resumes the paused print — or does nothing
  further if nothing was printing.
- While held, the phone's orientation is calibrated against wherever it
  happened to be pointed when you started (not "flat" — however you're
  already holding it), and further tilting moves the ball: left/right tilt
  (`gamma`) drives X, forward/back tilt (`beta`) drives Y. There's a small
  dead zone near the calibrated center and a capped max speed, so it behaves
  like a joystick rather than an absolute-position pointer.
- If the phone loses wifi or the tab gets backgrounded mid-hold without a
  clean release, a server-side watchdog auto-releases control (and resumes
  the paused print) after a short timeout — the table never gets stuck
  waiting on a phone that's gone away.
- **Only one phone controls the table at a time.** Starting a session is
  race-safe (whoever's hold completes first wins; a second phone gets a
  clean rejection instead of garbled shared control), and `/api/start`
  returns a per-session secret that must be echoed on every jog/stop call —
  so a second phone that also has the (shared, persistent) QR token can't
  jog or stop *someone else's* active session. The idle page also polls a
  lightweight status check every couple of seconds so a second visitor sees
  "Occupato" up front instead of holding for 3s just to be told no.
- Position tracking needs no `M114`/homing support from the table's firmware:
  the plugin passively watches every G-code line OctoPrint actually sends
  (from any source) and keeps a running "last known X/Y", the same way
  `octoprint-f1sisyphus` tracks its own position without ever querying the
  printer.

Because the medium is sand, there's no "pen up" — resuming a paused draw is
seamless at the print-job level, but the ball will have dragged a visible
line from wherever you left it back to the pattern's next point. That's
physics, not a bug.

## Install

```
pip install <path-to-this-folder>
```

or zip the `octoprint_manualdraw` folder + `setup.py` and install via
OctoPrint's Plugin Manager ("Install from file"). Requires `qrcode[pil]`
(installed automatically).

## Configure (Settings -> ManualDraw)

- **Enabled** — master switch; the public page and endpoints refuse
  requests while this is off.
- **Table bounds (mm)** — defaults to the real calibrated 370x400mm bed
  (matching `sandtable-viewer`/`tools/pattern_gallery.py`). Manual jogs are
  clamped to this box so a long hold can't drive the ball off the table.
- **Max speed / Jog feedrate** — max speed is the real speed limiter; keep
  the feedrate comfortably above `max_speed_mm_s * 60` so the feedrate
  itself never becomes the binding constraint.
- **Dead zone / Max tilt** — how much tilt is ignored near center, and the
  angle at which you're at full speed.
- **Hold to activate** — how long the button must be held before it takes
  control (also used to size the visual hold-progress ring on the phone).
- **Watchdog timeout** — how long without a jog update before control is
  auto-released.

## First-run checklist

1. Enable the plugin, open the **ManualDraw** tab, confirm the QR code
   renders, and scan it from a phone on the same network.
2. With the table idle, hold the button and confirm tilt moves the ball;
   release and confirm it stops.
3. Start a real ERASER/DRAW cycle, hold the button mid-draw, confirm the job
   pauses, drive it manually, release, and confirm the cycle resumes on its
   own afterward.
4. Turn off the phone's wifi mid-hold and confirm the watchdog releases
   control within `watchdog_timeout_seconds`.
5. Sanity-check `max_speed_mm_s`/`jog_feedrate` against your machine's real
   comfortable limits before leaving this enabled for guests unattended —
   same caution `octoprint-f1sisyphus`'s README gives for its own feedrate.

## Development

```bash
python -m venv .venv
.venv/Scripts/python -m pip install pytest
.venv/Scripts/python -m pytest ../tests -q
```

`manual.py` (token generation/checking, the incremental G-code position
tracker, tilt-to-velocity mapping, bounds clamping) has no OctoPrint
dependencies and is covered by `tests/test_manual.py` at the repo root,
alongside every other plugin's pure-logic tests.
