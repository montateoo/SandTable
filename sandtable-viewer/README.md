# SandTable Viewer

A standalone webapp — separate from the OctoPrint plugin — that shows what the
table is drawing right now. Scan a QR code with your phone, see the full
pattern ghosted in, and watch a glowing line trace it in sync with OctoPrint's
real job progress.

It only *reads* from OctoPrint's REST API (`/api/job`, file downloads); it
doesn't touch the cycle logic in `../octoprint_sandtable/`.

```
sandtable-viewer/
  server.py            # Flask app: serves the UI + /api/state + /api/path/<file>
  octoprint_client.py  # OctoPrint REST calls (job status, gcode download)
  gcode_path.py        # G-code -> polyline parser
  config.py            # reads secrets.toml / env vars
  qr.py                # one-off script: generates a QR code for the URL
  templates/, static/  # the canvas UI
```

## Setup (on the Pi, alongside OctoPrint)

```bash
cd sandtable-viewer
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp secrets.toml.example secrets.toml
# edit secrets.toml: set [octoprint] api_key (Settings -> Application Keys)
```

`url` defaults to `http://127.0.0.1` since this runs on the same Pi as
OctoPrint — no need to go over the network. `bed_x`/`bed_y` should match the
table's working area (370x400mm by default, same as `tools/pattern_gallery.py`).

## Run it

```bash
.venv/bin/python server.py        # listens on 0.0.0.0:8099
```

Visit `http://<pi-ip>:8099` from any device on the LAN.

### Always-on (systemd)

```ini
# /etc/systemd/system/sandtable-viewer.service
[Unit]
Description=SandTable viewer
After=network.target

[Service]
WorkingDirectory=/home/pi/sandtable-viewer
ExecStart=/home/pi/sandtable-viewer/.venv/bin/python server.py
Restart=on-failure
User=pi

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sandtable-viewer
```

## The QR code

Generate it once and print it onto a label for next to the table:

```bash
.venv/bin/python qr.py --host sandtable.local --port 8099 --out qr.png
```

`qr.py` doesn't need OctoPrint or the API key — it just encodes the URL above
into `qr.png` (and prints an ASCII preview to the terminal).

## How it works

- `/api/state` proxies OctoPrint's `/api/job` (current file, `progress.completion`,
  `printTimeLeft`) plus, if installed, `/api/plugin/sandtable` for the
  ERASER/DRAW phase and round counter.
- `/api/path/<file>` downloads the G-code once per file (cached in memory) and
  parses it into bed-space `(x, y)` points, the same modal G0/G1 handling as
  `tools/pattern_gallery.py`.
- The frontend polls `/api/state` every `poll_interval` seconds and animates
  the reveal between polls (`requestAnimationFrame`) so progress looks
  continuous rather than stepping every couple of seconds. The reveal point is
  `floor(len(points) * completion / 100)` — an approximation (OctoPrint's
  completion is byte-based, not move-based) but accurate enough to track the
  table visually.
