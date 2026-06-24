# OctoPrint-F1Sisyphus

Traces your favourite F1 driver's live on-track position onto a Sisyphus
sand table during race weekends, using the [OpenF1](https://openf1.org) API.

How it works: when you hit **Start Tracking**, the plugin fetches a sample
of the current session's location data for your chosen driver to learn the
track's shape (its bounding box), then maps that onto your table's working
area, preserving the track's proportions. It then polls OpenF1 every few
seconds for new position updates and sends `G1 X.. Y..` moves straight to
the printer connection, so the ball continuously traces wherever the car
currently is.

## Install

```
pip install <path-to-this-folder>
```

or zip the `octoprint_f1sisyphus` folder + `setup.py` and install via
OctoPrint's Plugin Manager ("Install from file").

Requires `requests` (installed automatically).

## Configure (Settings -> F1 Sisyphus Tracker)

- **Driver number**: the F1 car number to follow (1 = Verstappen,
  44 = Hamilton, 16 = Leclerc, etc. Full list at
  `https://api.openf1.org/v1/drivers`).
- **Session key**: leave as `latest` to follow whatever session is
  currently live. For testing outside a race weekend, set this to a
  specific past `session_key` (look one up at
  `https://api.openf1.org/v1/sessions`) — the plugin will then replay
  that session's data as fast as the table can move, which is a good way
  to sanity-check your calibration before relying on it live.
- **Table working area (X/Y range, mm)**: this MUST match the actual
  coordinate range your firmware accepts for the table — not an arbitrary
  guess. Send a few manual jogs from OctoPrint's normal control tab first
  to confirm where your real limits are.
- **Margin**: empty border kept inside the table bounds so the mapped
  track doesn't ride right up to the mechanical limits.
- **Flip X / Flip Y**: toggle if the drawn shape comes out mirrored
  relative to the real circuit.

## Using it

Go to the new **F1 Sisyphus** tab and press **Start Tracking**. The plugin
refuses to start if the table isn't connected, or if OctoPrint is in the
middle of an actual print job. It auto-stops if the printer disconnects or
a print job starts, so it won't fight a real print.

## Notes / things worth tweaking later

- Calibration currently samples the whole session's data for that driver
  in one request; for a session that's been running a long time this can
  be a sizeable JSON payload. Works fine, just give it a few seconds.
- Coordinate mapping is a simple uniform scale-and-center — it preserves
  the track's real proportions but doesn't rotate it, so depending on the
  circuit's orientation in OpenF1's coordinate frame the drawing may come
  out rotated relative to how you'd expect the track to look. Add a
  rotation setting if that bothers you.
- Right now every new point is drawn immediately as it's fetched. That's
  fine for live use (OpenF1 itself only updates a few times a second) and
  makes historical session_keys replay quickly for testing. If you want a
  literal real-time-paced replay of a historical session for demo
  purposes, you'd want to throttle sends based on the gap between each
  point's timestamp.
