# smart.home — orientation for a new session

Personal home-automation system: a FastAPI web UI + a heating-control daemon + several
data-collector daemons, plus ESP8266/ESP32 firmware for the physical sensors/relays.
This file is the map so you don't have to re-scan the repo. Detailed proxy/TLS docs live
in **`servers.conf/README.md`** — read that for anything about nginx, the Cloudflare
tunnel, or certs.

## Hosts & network

| Host | Addr | Role |
|------|------|------|
| **home** | `192.168.0.224` (Ubuntu 24.04, amd64) | **Everything runs here**: web app (Docker), all daemons, Redis :6379, Mosquitto :1883 + :8884(WS), InfluxDB :8086, Grafana :3000, Frigate NVR :5000. SSH `karotka@192.168.0.224` (sudo pw `aaa`). |
| **cml** (Pi4) | `192.168.0.222` (Raspberry Pi OS) | Legacy front door — nginx + Cloudflare tunnel only. **Being retired**: the proxy layer is now mirrored onto .224 (both tunnel connectors live). SSH `pi@192.168.0.222` (passwordless sudo). |
| BMS Pi | `192.168.1.225` | Runs `bms.monitor.pi` BLE daemon. |

**Entry paths** (detail in `servers.conf/README.md`): remote `home.karotka.cz` / `panel.karotka.cz`
via Cloudflare tunnel → nginx :80 (basic-auth; LAN `192.168.0.0/16` skips it); LAN direct
`pi.karotka.cz` :443 (Let's Encrypt via acme.sh). No router port-forward — the tunnel is outbound.
Access is **mobile-only now** — the old Pi4 wall-display/kiosk is dropped.

> **Server is the source of truth.** .224 often has uncommitted WIP and may be ahead of this
> clone; `checkerd.py` live-reloads `checker.py` each tick, and the container **bind-mounts the
> source**, so edits on .224 take effect without a rebuild. Check the server before assuming.

## (A) Server app + daemons (on .224)

### `web/` — FastAPI UI + heating daemon (Python 3.11, one Docker container)
- **Web entry:** `web/server_fastapi.py` (`app = FastAPI(...)`). WebSocket JSON-RPC at
  `/websocket` dispatches `{method, router, id, params}` → `web/methods.py`. Templates in
  `web/templ/`, static in `web/static/`. `web/server.py` (Tornado) is legacy — ignore.
- **Heating daemon:** `web/checkerd.py` — a foreground `while True:` loop (NOT systemd/cron)
  that `importlib.reload(checker)` and runs `checker.Checker(logger).check()` every ~1 s.
  All heating/solar-boost logic is in **`web/checker.py`**. Because of the reload, editing
  `checker.py` on the server takes effect next tick — no restart.
- **How both run:** `web/run.sh` launches gunicorn (`--workers 4`, uvicorn workers,
  `0.0.0.0:8000`, `server_fastapi:app`) in the background, then `checkerd.py` in the
  foreground. One container = web + heating daemon.
- **Deploy (no docker-compose):** `web/Dockerfile` (`python:3.11-slim-bookworm`, EXPOSE 8000,
  `CMD run.sh`). `web/Makefile`: `make build`, `make run` =
  `docker run -d --restart=always -p 8001:8000 -e TZ=Europe/Prague -v $(pwd):/root/project --name smart-home smart-home:latest`.
  **Host 8001 → container 8000**; the source is bind-mounted at `/root/project` (live code).
  `make enter` for a shell. The `karotka/*` registry image is legacy arm/v7 — build locally on .224.
- **Config:** `web/conf/config.ini` (via `web/config.py`). Contains **Tuya local_keys — never
  commit changes with those** (gitignored artifacts exist). Sections: `[Db]` Redis, `[Mqtt]`,
  `[Influx]` (db `invertor`, hpDb `hp`), `[Heating]` + `[HeatingSensors]` (sensor↔room↔manifold-port
  map; manifold ESP at `192.168.0.5`, heating relay at `192.168.0.6`), `[Lights]`, `[Blinds]`
  (Tuya ids/keys), `[Battery]`.
- **Deps:** `web/requirements.txt` (fastapi, uvicorn, gunicorn, jinja2, redis, pandas<2,
  numpy<2, influxdb 5.3, tinytuya, paho-mqtt<2, python-daemon).
- **Helper services** (`web/service/*`): `lights_poller.service` (caches switch states into
  Redis `light_state_<id>`); `tuya_rediscover.service` + `.timer` (hourly, refreshes Tuya LAN
  IPs into snapshot.json); `web/mqtt_bridge.py`.

### Other collector daemons
- `invertor/` — PIP solar-inverter monitor over RS232. `invertor/invertor.py` → InfluxDB
  db `invertor` + Redis + MQTT. Also `mqtt.feeder.py`, `tuya.py`, `aggregate.py` (roll-ups).
  Units in `invertor/service/`.
- `heatpump/` — Tuya heat-pump monitor. `heatpump/hp_monitor.py` (tinytuya) → InfluxDB db `hp`.
  Unit `heatpump/service/hp.service`. Web controls it via `heatpump_*` methods.
- `bms.monitor.pi/` — battery BMS BLE central, runs on the **BMS Pi (.1.225)**.
  `bms_daemon.py` → `bms-monitor-pi.service`. Talks to JK BMSes over BLE; publishes
  `home/bms/<battery-N>/snapshot` (~1 s).
- `crond/cron` — host crontab (invertor roll-ups, log truncation, 6-h service restarts).
  Note: paths there reference `/home/pi/...` (Pi4-era) — verify per host.

## (B) Data plane

- **MQTT** (`.224:1883`, WS `:8884` proxied at `/mqtt`): `home/invertor/{actual,snapshot,daily/rows,monthly/rows}`,
  `home/temp/sensor/+`, `home/bms/<battery-N>/snapshot`.
- **InfluxDB** (`.224:8086`): db **`invertor`** (live + `invertor_daily`/`invertor_monthly` +
  `bms_battery-N`), db **`hp`** (heat pump). Mostly influxdb v1 client.
- **Redis** (`.224:6379`): live state — `light_state_<id>`, `heatpump_status*`, heating
  targets `heating_<roomId>`, `__heatingCounter`, etc.

## (C) Device firmware (ESP8266/ESP32, C/C++ Arduino) & misc

Firmware dirs (flashed to MCUs, not run on servers): `bistable.relay` (relay node),
`blind` (roller blinds), `manifold.switch` (underfloor manifold valves), `temp.sensor` +
`temp.sensor.mqtt` (temp nodes), `energy.meter.6914`, `helioset` (ESP32 solar-thermal),
`stove.regulator`, `bms.monitor` + `bms.monitor.ble` (ESP BMS readers),
`generic.temp.sensor` (Tasmota-script). Build: Arduino+Makefile or PlatformIO (`platformio.ini`).
Shared: `bk/` (ESP wifi/config C++ lib), `tuya/` (Tuya CLI scripts), `mqtt.js.client/`
(browser MQTT dashboard), `influx/` (InfluxDB container), `pi.server/` (enclosure CAD).

## The tablet dashboard
`web/templ/tablet.html` — standalone dashboard (Dashboard / Ovládání / Baterie / Alerty / Radar
tabs), built as a fullscreen PWA on `panel.karotka.cz`. Served by `/tablet.html` in
`server_fastapi.py`; own manifest/service-worker (`manifest.tablet.json`, `sw-tablet.js`). Mobile
pages keep their own separate templates.

## Alerting
`web/alerts.py` evaluates rules from **`web/conf/alerts.json`** every ~15 s inside `checkerd`
(isolated try/except — never blocks heating), writing the result to Redis `alerts_view`.
`methods.alerts_status` just reads that back for the **Alerty** tab (header badge + severity cards).
Rules are declarative (`scope: per_pack`, ANDed `conditions`, `hold_s` before firing) and
**mtime-reloaded — edit thresholds in alerts.json, no restart**. v1 = battery/BMS only
(SOC, cell imbalance, over/under-voltage, temp, charging-in-frost, pack offline); packs are
14S LiPo (cell over/under-voltage 4250/3000 mV). Adding a category = add rules + extend the signal source in `alerts.py`
(currently `_battery_signals()` from `battery_packs()`). **Note:** a new `methods.py` method or
non-template code change needs a container restart (`docker restart smart-home`) — checkerd only
live-reloads `checker.py`/`alerts.py`, and gunicorn imports `methods` once.

## Battery, solar & heat-pump energy system

**Battery bank (DC-coupled, shared bus):** 5× **14S NMC** packs (Tesla/Panasonic 18650), each
with its own **JK BD6A24S10P** BMS (24S-capable), paralleled on the DC bus. ~511 Ah / ~26 kWh
total (~22 kWh usable); per-pack capacity varies ~70–135 Ah, and **battery-3 is aged** (257
cycles vs ~30 on the others). Live per-pack data: `methods.battery_packs()` (InfluxDB
`bms_battery-N`) + MQTT `home/bms/<battery-N>/snapshot`.

**Expansion in progress (LFP ordered 2026-09):** adding **1× 16S LiFePO4** pack from **EVE
LF230** cells (3.2 V nom / 3.65 V charge / 2.0 V cutoff, 230 Ah, 1C max, 8000 cyc) ≈ **11.8 kWh**,
own BMS, parallel on the same bus. Plus **9×450 W (4 kWp) PV vertical on the fence, due south**
— vertical beats the shallow 17° roof for the low winter sun (solar noon only ~16° at 50.13°N;
vertical captures ~96% of the beam vs ~55% for the 17° roof → ≈+74% in December). Roof stays for
summer; the two orientations are complementary. Bifacial worth considering (snow albedo).

**Mixed-chemistry parallel is OK here** (revised from an earlier flat "no"): a shared bus = one
shared voltage, and each pack's own BMS protects its own cells. A shared window **~57.7–46 V**
keeps both chemistries inside per-cell limits — 14S NMC 4.12→3.29 V/cell, 16S LFP 3.606→2.875
V/cell; full-charge voltages nearly coincide (58.8 vs 58.4 V). Current is NOT the constraint:
inverters cap ~140–160 A (+ new PV ~70 A ≈ 210 A total) vs LFP 1C = 230 A — just give the LFP
BMS a sane limit (~115–150 A). LFP's flat curve makes it hog mid-range current, but that's moot
at these real currents.

**Inverters:** 2× PIP-style units at **192.168.0.223 / .225** (parallel), not directly reachable
from .224 but feeding InfluxDB db `invertor` (measurement `invertor_status` holds the config;
`invertor`/`invertor_actual` live; `invertor_daily`/`_monthly` aggregates). Heat-pump data is in
db `hp` (field `power`, integrable). Config now: output priority **SOL** (Solar→Utility→**Battery
last** — that's why the battery is barely cycled in winter, grid is ahead of it), charging **OSO**
(solar-only, never grid-charges), input range **ALP** (Appliance = widest grid tolerance), float
57.7 / bulk 57.8 / mains-switch 47 / shutdown 45.5 V, solar charge 70 A/unit. These setpoints
already suit the NMC+LFP mix.

**Energy reality (winter, from data):** the **heat pump is ~80% of consumption** (~15–16 kWh/day,
overnight 17–08h ~6–8 kWh); house ~19 kWh/day, winter solar 6–10 kWh, ~10 kWh/day from grid.
Overnight-with-TC need ≈ 8–10 kWh. **The bottleneck is winter recharge, not storage** (battIN
only 2–4.5 kWh/day — not enough surplus solar); multi-day dark spells (solar ≈ 0) still need grid.

**Plan / order of operations:** fit LFP + vertical PV → **then switch inverter output priority
SOL→SBU** (Solar→Battery→Utility) so the battery actually covers the night; keep OSO (optionally
allow limited grid charging in deep winter as a safety floor against a low battery on an unstable
grid). Target ≈ 34 kWh usable ≈ 2–3 nights of TC autonomy. Past "flapping to a low battery on a
wobbling grid" was grid quality, not a bad setting (input range already Appliance) — more
capacity + PV fixes it by keeping the battery off empty. After LFP is in, give the alert rules
**separate NMC vs LFP per-cell thresholds** (NMC 4.15/3.0 V, LFP 3.65/2.5 V) — `alerts.json` is
already per-pack.

## Gotchas
- **No docker-compose**; deploy is the `web/Makefile` `docker run` with a live bind mount.
- Several `crond/cron` and `*.service` files hardcode `/home/pi/smart.home/...` (Pi4 paths) and
  a few have typos — **verify a unit before trusting/enabling it.**
- The heating decision in `checker.py` only acts when a room's `heating_direction == "heating"`;
  config `hysteresis` exists but isn't applied. The daemon is hardened so a hung manifold
  (`192.168.0.5`) no longer blocks the heating relay (`192.168.0.6`).
- Repo is public — do not commit secrets (Tuya keys, tokens, htpasswd, certs).
