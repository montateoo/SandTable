# OctoPrint-NanoLED

Drives the Sisyphus table's under-surface WS2812FX LED strip via an Arduino Nano connected to the
Pi's GPIO UART (TX/RX), instead of only the Nano's own physical button + potentiometers.

The Nano runs `LED-Arduino/LED-Control/LED-Control.ino` (in the parent `SandTable` repo), extended
with a simple line-based serial command parser. This plugin owns the serial connection and exposes:

- A manual control tab (pattern 0-10, solid color test, flicker/flash test).
- A small Python API (`set_pattern`, `set_solid`, `flicker_rainbow`, `flash_white`) that other
  OctoPrint plugins can call directly, in-process, via
  `self._plugin_manager.get_plugin("nanoled", True)`. `octoprint-f1sisyphus` uses this to drive
  race-flag-reactive lighting during a live race.

**Hardware note:** the Nano is 5V logic; the Pi's GPIO UART is 3.3V and not 5V-tolerant. The Nano's
TX line needs a voltage divider or level shifter before reaching the Pi's RX pin.

## Settings

- `enabled` -- master switch.
- `serial_port` -- e.g. `/dev/serial0` or `/dev/ttyAMA0`.
- `baud_rate` -- must match the sketch's `Serial.begin(...)` (115200).
