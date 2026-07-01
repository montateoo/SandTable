# OctoPrint-SandTable

Turns a Sisyphus-style sand table (running [OctoPrint](https://octoprint.org/) on a
Raspberry pi 3 model A+) into an autonomous appliance.

While the machine is powered on, the plugin automatically runs **N rounds of
`ERASER → DRAW`** (default 2), picking patterns **round-robin** from two folders.
When the rounds finish it **cuts power to the whole machine** via a **local smart
plug**. An **external schedule** (the plug's own timer or a Google Home / Matter
routine) powers it back on later, and the plugin **auto-resumes** on boot —
continuing the round-robin where it left off.

```
[power on] → boot → OctoPrint → plugin auto-starts
   ERASER → DRAW   (round 1)
   ERASER → DRAW   (round 2)
   …N rounds…
   → smart plug OFF (after a safe delay) → clean Pi shutdown → power cut
        ⋯ external schedule powers back on later ⋯
[power on] → … repeat
```

## How it works

- **Pattern pools** are two OctoPrint upload folders, `eraser/` and `draw/` by default.
  Drop G-code files into them; the plugin lists each folder, sorts the files, and
  round-robins through them. The two pointers are persisted so the rotation survives
  the reboot between cycles.
- **The cycle** is a small state machine driven by OctoPrint's `PrintDone` event:
  `ERASER → DRAW`, repeated `rounds` times, then *power-off*. A failed/cancelled print
  **stops** the cycle and **does not** power off, so problems stay visible.
- **Safe shutdown:** because the plug also powers the Pi, the plugin tells the plug to
  switch off **after a delay** (default 60 s) and then issues a clean OS shutdown. The
  Pi halts well before power is cut, avoiding SD-card corruption. The delay lives *on
  the plug* (Shelly timer / Tasmota `Backlog Delay`) because the Pi is on its way down.

## Supported smart plugs (local LAN, no cloud)

| Type (`plug_type`) | Notes |
|--------------------|-------|
| `shelly1` | Shelly Gen1 (`/relay/0?turn=…`). Safe delayed-off via `timer`. |
| `shelly2` | Shelly Gen2 / Gen3 / **Gen4** / Plus (JSON-RPC `/rpc`). Safe delayed-off via `toggle_after`. Uses digest auth when a password is set. |
| `tasmota` | Tasmota (`/cmnd`). Safe delayed-off via `Backlog Delay …; Power Off`. |
| `kasa`   | TP-Link Kasa via `python-kasa`. **No safe delayed-off** — switches immediately. |

> If the plug also powers the Pi, prefer **Shelly or Tasmota** so the Pi can shut
> down cleanly. For **Kasa**, install the optional dependency: `pip install "python-kasa>=0.5.0"`.

## Installation

Install via OctoPrint's **Plugin Manager → Install from URL**, pointing at this repo's
archive, or manually into OctoPrint's Python environment:

```bash
pip install https://github.com/montateoo/OctoPrint-SandTable/archive/main.zip
# or, from a clone:
pip install .
```

Restart OctoPrint afterwards.

## Configuration (Settings → SandTable)

- **Enabled / Auto-start on boot** — master switch and whether to resume automatically.
- **Eraser folder / Draw folder** — the two pattern pools (OctoPrint upload folders).
- **Rounds per cycle** — how many `ERASER→DRAW` rounds before powering off.
- **Plug type / host / user / password** — your smart plug.
- **Dry run** — *ON by default.* The cycle runs but the machine never actually powers
  off or shuts down (it only logs what it would do). **Leave this on until you've
  tested everything.**
- **Power-off delay** — seconds the plug stays on after the cycle so the Pi can halt.
- **Shut down the Pi** — issue a clean OS shutdown before the plug cuts power.

### Setting up the wake-up schedule (required)

The plugin only sends the **off** signal. Something external must power the machine
back **on**:

- **Shelly / Tasmota:** configure a daily *Timer/Schedule* on the device itself to turn
  on at, say, 08:00.
- **Google Home / Matter / Home Assistant:** add a routine/automation that turns the
  plug on at your chosen time.

When power returns, the Pi boots, OctoPrint starts, and (with *Enabled* + *Auto-start*)
the plugin begins the next cycle.

> OctoPrint must be configured to **auto-connect to the printer on startup**
> (Settings → Serial Connection → "Auto-connect on server startup"), otherwise the
> plugin will wait and then give up.

## Recommended first-run / test workflow

1. **Plug only:** set the plug host, plug a **lamp** (not the Pi) into the smart plug,
   open the **SandTable** tab and press **Plug ON / Plug OFF**. Confirm it switches.
2. **Cycle, no power-off:** keep **Dry run ON**, create the `eraser/` and `draw/`
   folders, upload a couple of G-code files to each, press **Start cycle**. Watch it run
   `ERASER→DRAW` for N rounds; the power-off is only *logged*.
3. **Power-off path:** with **Dry run ON**, press **Simulate cycle-complete** — confirm
   the off command is logged/sent (test against the lamp).
4. **Go live:** move the Pi + table onto the smart plug, set the external wake schedule,
   turn **Dry run OFF**, enable **Auto-start on boot**, and run a full cycle.

## Development

```bash
python -m venv .venv
.venv/Scripts/python -m pip install pytest requests
.venv/Scripts/python -m pytest tests -q
```

The cycle logic (`cycle.py`) and plug drivers (`plug.py`) have no OctoPrint
dependencies and are covered by unit tests. The OctoPrint glue lives in
`octoprint_sandtable/__init__.py`.
```
octoprint_sandtable/
  __init__.py   # plugin: mixins, state machine glue, power-off, API, autostart
  cycle.py      # pure cycle transitions + round-robin (unit-tested)
  plug.py       # smart-plug drivers (unit-tested)
  templates/    # settings panel + status tab
  static/       # tab view model (JS) + CSS
tests/          # pytest suite for cycle.py and plug.py
```

## License

AGPLv3
