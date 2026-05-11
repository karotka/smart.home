# firmware

Arduino sketch for the per-pack BMS monitor module.

## Layout

| File              | Role |
|-------------------|------|
| `bms_monitor.ino` | main: WiFi, UART read, HTTP POST loop |
| `jk_bms.h/.cpp`   | JK02 protocol frame parser (listening only) |
| `config.h`        | non-secret config: pack_id, server URL, pins |
| `secrets.h`       | WiFi creds, gitignored — copy `secrets.h.example` |

## One-time setup in the Arduino IDE

1. **Board** — install the ESP8266 board package
   - File → Preferences → Additional Board Manager URLs:
     `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
   - Tools → Board → Boards Manager… → install **esp8266 by ESP8266
     Community**
   - Tools → Board → ESP8266 Boards → **LOLIN(WEMOS) D1 R2 & mini**

2. **Library** — Sketch → Include Library → Manage Libraries:
   - **ArduinoJson** by Benoit Blanchon

3. Everything else (`ESP8266WiFi`, `ESP8266HTTPClient`,
   `SoftwareSerial`) comes with the ESP8266 board package.

## Per-module flash recipe

1. Copy `secrets.h.example` → `secrets.h` and fill in WiFi creds
2. Edit `config.h`:
   - `PACK_ID` to one of `tesla`, `tesla_pair`, `samsung`,
     `samsung_e`, `lg` — must match the BMS the module is on
   - confirm `SERVER_URL` reachable from the WiFi the D1 will join
3. Open `bms_monitor.ino` in the IDE — all four files in the folder
   open as tabs automatically
4. Tools → Port → the D1's USB serial port
5. Upload, then open Serial Monitor at 115200 baud

## Bring-up checklist

With the BMS plugged in and the module powered:

```
bms.monitor boot, pack_id=tesla, free heap=…
WiFi: connecting......
WiFi: connected, ip=192.168.0.xx rssi=-58 dBm
frame: 4E 57 …                          ← raw frame from BMS
BMS: 14 cells, total=53.20V, I=-1.20A, SOC=78%, min=3789 mV max=3812 mV delta=23 mV
POST http://192.168.0.222:8000/bms -> 200 (body 612 B)
```

If you see **no frames at all** after a minute:
- swap RX/TX wires (very common mistake)
- check VCC on the BMS GPS port (some revisions only enable it after
  the BMS Bluetooth dongle handshake — wire only TX/GND from BMS)
- watch with Serial Monitor at 115200 for hex dump

If frames arrive but **CRC fails repeatedly**:
- check ground continuity between BMS and the D1
- check for a flaky JST contact

`DEBUG_HEX_DUMP = true` in `config.h` keeps every frame visible on
serial; flip it off for production once the link is stable.

## Server expectation

The sketch POSTs a JSON object to `SERVER_URL` every 30 s:

```json
{
  "pack_id": "tesla",
  "uptime_s": 1234,
  "wifi_rssi": -58,
  "bms_age_ms": 720,
  "valid": true,
  "cell_count": 14,
  "cell_min_mv": 3789, "cell_max_mv": 3812,
  "cell_avg_mv": 3800, "cell_delta_mv": 23,
  "cells_mv": [3801, 3789, 3812, …],
  "total_mv": 53204,
  "current_ma": -1200,
  "soc": 78,
  "temps_dC": [257, 261, 240],
  "cycle_count": 132,
  "cycle_cap_mah": 13500,
  "charge_mos": true,
  "discharge_mos": true,
  "balancing": false
}
```

A Tornado handler at `POST /bms` will accept this and forward into
InfluxDB; that lives in the (yet-to-be-written) server phase.

## What this firmware deliberately does *not* do

- send commands to the BMS (no settings changes, ever)
- run OTA updates
- expose its own HTTP server
- talk to the BMS over BLE — ESP8266 doesn't have Bluetooth and a
  wired UART connection is more robust anyway
